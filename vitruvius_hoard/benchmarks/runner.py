"""Durable, versioned batches through the normal Rehacer entry point."""

import hashlib
import json
from pathlib import Path
import threading
import time
import uuid

from ..hoard_link.atomic import write_json_atomic
from . import corpus, references, runtime

METRIC = "vitruvius-stable-pixels/1"
ACTIVE = {"queued", "running"}


def summary(run):
    rows = run["cases"]
    measured = [row for row in rows if row["status"] == "measured"]
    scores = [row["score"] for row in measured]
    return {
        "selected": len(rows),
        "measured": len(measured),
        "failed": sum(row["status"] == "failed" for row in rows),
        "passed": sum(bool(row.get("passed")) for row in measured),
        "coverage_percent": round(100 * len(measured) / len(rows), 2),
        "mean_score": round(sum(scores) / len(scores), 4) if scores else None,
        "complete": len(measured) == len(rows),
    }


class Benchmarks:
    def __init__(self, services):
        self.svc = services
        self.root = Path(services.config.data_dir) / "benchmarks"
        self.lock = threading.RLock()
        self.thread = None
        self.cancel = threading.Event()
        self.current = None
        for path in self.root.glob("runs/*/run.json"):
            run = json.loads(path.read_text(encoding="utf8"))
            if run["status"] in ACTIVE:
                run["status"] = "interrupted"
                for row in run["cases"]:
                    if row["status"] in {"preparing", "remaking"}:
                        row["status"] = "interrupted"
                self._save(run)

    def _path(self, run_id):
        if len(run_id) != 12 or any(char not in "0123456789abcdef" for char in run_id):
            raise ValueError("Invalid evaluation id")
        return self.root / "runs" / run_id / "run.json"

    def _load(self, run_id):
        path = self._path(run_id)
        if not path.is_file():
            raise LookupError("Unknown evaluation")
        return json.loads(path.read_text(encoding="utf8"))

    def _save(self, run):
        run["updated_ts"] = time.time()
        run["summary"] = summary(run)
        write_json_atomic(self._path(run["id"]), run)

    def catalog(self):
        return corpus.catalog()

    def start(
        self,
        *,
        version,
        cases=None,
        mode="copy",
        max_rounds=1,
        widths=None,
        pass_score=98.0,
        tolerance=0.10,
        note="",
        runtime_kind="container",
    ):
        manifest = corpus.catalog()
        if runtime_kind not in {"native", "container"}:
            raise ValueError("Choose a container or native reference runtime")
        ids = cases or [row["id"] for row in manifest["cases"]]
        known = {row["id"] for row in manifest["cases"]}
        if not version.strip() or len(version) > 200:
            raise ValueError("A version label is required (up to 200 characters)")
        if len(ids) != len(set(ids)) or set(ids) - known:
            raise ValueError("Choose unique case ids from benchmark_catalog")
        widths = sorted(set(widths or [1440, 390]), reverse=True)
        if not 1 <= len(widths) <= 3 or any(not 200 <= w <= 3000 for w in widths):
            raise ValueError("Choose one to three widths between 200 and 3000")
        if mode not in {"copy", "rebuild"} or not 1 <= max_rounds <= 20:
            raise ValueError("Invalid remake mode or round budget")
        if not 50 <= pass_score <= 100 or not 0 <= tolerance <= 0.5:
            raise ValueError("Invalid parity thresholds")
        with self.lock:
            self._idle()
            run = {
                "id": uuid.uuid4().hex[:12],
                "version": version.strip(),
                "created_ts": time.time(),
                "status": "queued",
                "implementation_sha256": corpus.implementation(),
                "environment": corpus.environment(),
                "runtime_kind": runtime_kind,
                "corpus": manifest,
                "metric": METRIC,
                "scope": "frozen-reference-entry-page",
                "official_reward": None,
                "settings": {
                    "mode": mode,
                    "max_rounds": max_rounds,
                    "widths": widths,
                    "pass_score": pass_score,
                    "tolerance": tolerance,
                    "note": note,
                },
                "cases": [
                    {"id": case_id, "status": "pending", "attempts": []}
                    for case_id in ids
                ],
            }
            self._save(run)
            self._launch(run["id"])
            return self.get(run["id"])

    def _idle(self):
        if self.thread and self.thread.is_alive():
            raise ValueError("An evaluation is already running. Read or stop it first.")

    def _launch(self, run_id):
        self.cancel = threading.Event()
        self.current = run_id
        self.thread = threading.Thread(
            target=self._run, args=(run_id,), name="vitruvius-evaluation", daemon=True
        )
        self.thread.start()

    def resume(self, run_id):
        with self.lock:
            self._idle()
            run = self._load(run_id)
            if run["implementation_sha256"] != corpus.implementation():
                raise ValueError(
                    "Implementation changed. Start a new version to preserve comparable results."
                )
            if run["status"] == "done":
                raise ValueError(
                    "This evaluation has finished. Start a new version to repeat it."
                )
            run["status"] = "queued"
            self._save(run)
            self._launch(run_id)
            return self.get(run_id)

    def stop(self, run_id):
        with self.lock:
            run = self._load(run_id)
            if run_id == self.current and self.thread and self.thread.is_alive():
                self.cancel.set()
            return self.get(run_id)

    def get(self, run_id):
        with self.lock:
            run = self._load(run_id)
            run["running"] = bool(
                self.current == run_id and self.thread and self.thread.is_alive()
            )
            run["export_url"] = f"/api/benchmarks/runs/{run_id}/export"
            return run

    def list(self, limit=50):
        with self.lock:
            runs = [
                self.get(path.parent.name) for path in self.root.glob("runs/*/run.json")
            ]
        runs.sort(key=lambda run: run["created_ts"], reverse=True)
        return {
            "runs": [
                {
                    key: run[key]
                    for key in (
                        "id",
                        "version",
                        "created_ts",
                        "status",
                        "summary",
                        "settings",
                        "implementation_sha256",
                        "running",
                    )
                }
                for run in runs[:limit]
            ]
        }

    def compare(self, before, after):
        a, b = self.get(before), self.get(after)
        reasons = []
        for key in ("metric", "scope", "settings", "environment", "runtime_kind"):
            if a.get(key) != b.get(key):
                reasons.append(key)
        if a["corpus"]["manifest_sha256"] != b["corpus"]["manifest_sha256"]:
            reasons.append("corpus")
        if [row["id"] for row in a["cases"]] != [row["id"] for row in b["cases"]]:
            reasons.append("selection")
        pairs = []
        old = {row["id"]: row for row in a["cases"]}
        for row in b["cases"]:
            previous = old.get(row["id"], {})
            if row["status"] == previous.get("status") == "measured":
                if row["reference"]["sha256"] != previous["reference"]["sha256"]:
                    reasons.append("reference:" + row["id"])
                pairs.append(
                    {
                        "id": row["id"],
                        "before": previous["score"],
                        "after": row["score"],
                        "delta": round(row["score"] - previous["score"], 4),
                    }
                )
        comparable = not reasons
        return {
            "before": before,
            "after": after,
            "comparable": comparable,
            "differences": reasons,
            "paired_measured": len(pairs),
            "selected": len(b["cases"]),
            "mean_delta": (
                round(sum(p["delta"] for p in pairs) / len(pairs), 4)
                if comparable and pairs
                else None
            ),
            "cases": pairs if comparable else [],
            "before_summary": a["summary"],
            "after_summary": b["summary"],
        }

    def close(self):
        self.cancel.set()
        if self.thread:
            self.thread.join()

    def _run(self, run_id):
        run = self._load(run_id)
        run["status"] = "running"
        self._save(run)
        try:
            run["environment"]["runtime"] = runtime.prepare(
                self.cancel, self._path(run_id).parent, run["runtime_kind"]
            )
            self._save(run)
            for row in run["cases"]:
                if self.cancel.is_set():
                    raise references.Cancelled()
                if row["status"] in {"measured", "failed"}:
                    continue
                try:
                    row.update(status="preparing", error=None)
                    self._save(run)
                    source, row["reference"] = references.prepare(
                        self.root, run["corpus"], row["id"], self.cancel
                    )
                    folder = self._path(run_id).parent / row["id"]
                    folder.mkdir(exist_ok=True)
                    # New state per attempt makes a resumed reference deterministic.
                    attempt = len(row["attempts"])
                    reference_runner = (
                        runtime.running
                        if run["runtime_kind"] == "container"
                        else references.running
                    )
                    with reference_runner(
                        source,
                        folder / f"state-{attempt}",
                        folder / f"reference-{attempt}.log",
                        self.cancel,
                    ) as url:
                        row["status"] = "remaking"
                        self._save(run)
                        project = self.svc.remake.start(
                            url=url,
                            label=f"{run['version']} / {row['id']}",
                            **run["settings"],
                        )
                        row["remake_id"] = project["id"]
                        row["attempts"].append(project["id"])
                        self._save(run)
                        while project["running"] or project["status"] in ACTIVE:
                            if self.cancel.wait(0.25):
                                self.svc.remake.stop(project["id"])
                                time.sleep(0.25)
                            project = self.svc.remake.get(project["id"])
                        if self.cancel.is_set():
                            raise references.Cancelled()
                        self._retain(row, project)
                except references.Cancelled:
                    row["status"] = "interrupted"
                    raise
                except Exception as error:
                    row.update(status="failed", error=str(error))
                self._save(run)
            run["status"] = "done"
        except references.Cancelled:
            run["status"] = "stopped"
        except Exception as error:
            run.update(status="interrupted", error=str(error))
        finally:
            self._save(run)

    def _retain(self, row, project):
        row.update(
            remake_status=project["status"],
            rounds=project["rounds"],
            model=project.get("model"),
            report_url=project["report_url"],
            site_url=project["site_url"],
            measured_ts=time.time(),
        )
        if project["best_score"] is None:
            raise ValueError(
                project.get("error") or "Rehacer produced no measured round"
            )
        row.update(
            status="measured",
            score=project["best_score"],
            passed=project["passed"],
            error=project.get("error"),
        )
        folder = Path(self.svc.config.data_dir) / "remake" / project["id"]
        row["artifacts"] = [
            {
                "path": file.relative_to(folder).as_posix(),
                "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            }
            for file in sorted(folder.rglob("*.png"))
        ]
        for round_ in project["rounds"]:
            if round_.get("parity_id"):
                parity = Path(self.svc.config.data_dir) / "parity" / round_["parity_id"]
                row["artifacts"].extend(
                    {
                        "path": file.relative_to(
                            Path(self.svc.config.data_dir)
                        ).as_posix(),
                        "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                    }
                    for file in sorted(parity.rglob("*.png"))
                )
