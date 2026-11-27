"""Functional page checking through Vitruvius's incorporated browser engine.

The checker opens a page in a real browser and derives observable cases
from its controls. Optional explicit criteria verify requested behavior.
Generic coverage alone cannot infer every intended button effect; failed
and unchecked cases remain visible. No model is used.

This compatibility facade owns the worker boundary: the page is written to
``data/assay/<id>/index.html`` (or an existing local folder/page is used),
the incorporated Python worker runs in a subprocess with the existing timeout, and the
JSON run is reduced to what an assistant needs: did it work, what failed,
what the page offers. Nothing here needs assay at import time.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .hoard_link import proc

INSTALL_HINT = "The page checker is incorporated in Vitruvius; its Playwright browser dependency must be installed."
# The Hub normally allows 120 seconds, without forwarding its transport timeout.
DEFAULT_TIMEOUT_S = 105
RESPONSE_RESERVE_S = 4


def available() -> bool:
    """True when the incorporated worker's browser library is available."""
    return importlib.util.find_spec("playwright") is not None


def _command(folder: Path, entry: str) -> list[str]:
    base = [sys.executable, str(Path(__file__).with_name("functional_check") / "worker.py")]
    return [*base, str(folder), "-e", entry, "--json"]


def prepare(data_dir: Path, *, html: Optional[str] = None, path: Optional[str] = None) -> tuple[Path, str, str]:
    """Return (folder, entry, run_id) for the page to check.

    `html` is written to a fresh folder; `path` must be an existing local
    .html file or a folder holding index.html.
    """
    run_id = uuid.uuid4().hex[:12]
    if html is not None:
        folder = data_dir / "assay" / run_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.html").write_text(html, encoding="utf-8")
        return folder, "index.html", run_id
    if path:
        target = Path(path).expanduser().resolve()
        if target.is_file():
            return target.parent, target.name, run_id
        if target.is_dir():
            return target, "index.html", run_id
        raise ValueError(f"No such page or folder: {path}")
    raise ValueError("page_assay needs html or a local path")


def reduce_run(run: dict[str, Any], *, max_cases: int = 40) -> dict[str, Any]:
    """The parts of an assay run worth handing to an assistant."""
    cases = run.get("cases") or []
    failing = [c for c in cases if c.get("outcome") not in (None, "passed")]
    return {
        "works": bool(run.get("works")),
        "planned": run.get("planned", len(cases)),
        "passed": run.get("passed", len(cases) - len(failing)),
        "failed": run.get("failed", len(failing)),
        **({"startup_blocked_writes": run["startup_blocked_writes"]} if run.get("startup_blocked_writes") else {}),
        "surface": [{"kind": s.get("kind"), "label": s.get("label"), "selector": s.get("selector"), "enabled": s.get("enabled")}
                    for s in (run.get("surface") or [])][:80],
        "failing": [{"id": c.get("id"), "what": c.get("what"), "detail": c.get("detail"), "measured": c.get("measured"),
                     "acts": c.get("acts"), "environment": c.get("environment", {})} for c in failing][:max_cases],
        "cases_sample": [{"id": c.get("id"), "what": c.get("what"), "outcome": c.get("outcome"),
                          "environment": c.get("environment", {}), "measured": c.get("measured"),
                          "detail": c.get("detail", "")} for c in cases[:max_cases]],
    }


def _read_progress(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _run_worker(cmd: list[str], *, timeout: float, cwd: Path, output: Path) -> tuple[int, str, str]:
    # Files allow timeout recovery without waiting for inherited pipe handles
    # held by the Playwright driver or Chromium after the worker is stopped.
    stdout = output / "stdout.json"
    stderr = output / "stderr.log"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with stdout.open("wb") as out, stderr.open("wb") as err:
        child = proc.popen(cmd, cwd=cwd, stdout=out, stderr=err, env=env, low_priority=True)
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            child.kill()
            raise
    return code, stdout.read_text(encoding="utf-8"), stderr.read_text(encoding="utf-8", errors="replace")


def _partial(progress: Path, run_id: str, t0: float) -> dict[str, Any]:
    snapshot = _read_progress(progress)
    finished = snapshot.get("cases", [])
    finished_by_id = {case["id"]: case for case in finished}
    unchecked_cases = []
    for case in snapshot.get("plan", []):
        observed = finished_by_id.get(case["id"])
        if observed is None:
            unchecked_cases.append(case)
        elif observed["outcome"] == "unknown":
            unchecked_cases.append({**case, "detail": observed["detail"]})
    result = reduce_run({**snapshot, "works": False,
                         "passed": sum(c["outcome"] == "passed" for c in finished),
                         "failed": sum(c["outcome"] == "failed" for c in finished)})
    result.update({
        "id": run_id, "ms": int((time.monotonic() - t0) * 1000), "timed_out": True,
        "stopped_at": snapshot.get("stopped_at", {"stage": "start_worker"}),
        "unchecked": max(0, result["planned"] - len(finished))
        + sum(c["outcome"] == "unknown" for c in finished),
        "unchecked_cases": unchecked_cases,
    })
    return result


def run(data_dir: Path, *, html: Optional[str] = None, path: Optional[str] = None,
        url: Optional[str] = None, timeout_s: int = DEFAULT_TIMEOUT_S, runner: Any = None,
        criteria: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Run assay on a page and return the reduced result (never raises for a failed page).

    `runner(cmd, timeout_s) -> (returncode, stdout, stderr)` can be injected by tests.
    """
    if not available() and runner is None:
        return {"error": "page checker browser dependency is not installed", "hint": INSTALL_HINT}
    folder, entry, run_id = (data_dir, "index.html", uuid.uuid4().hex[:12]) if url else prepare(data_dir, html=html, path=path)
    cmd = _command(folder, entry)
    if url:
        cmd.extend(["--url", url])
    run_dir = data_dir / "assay" / run_id
    progress = run_dir / "progress.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    if criteria:
        criterion_path = run_dir / "criteria.json"
        criterion_path.write_text(json.dumps(criteria, ensure_ascii=False), encoding="utf-8")
        cmd.extend(["--criteria", str(criterion_path)])
    t0 = time.monotonic()
    if runner is None:
        work_budget = max(0.1, timeout_s - RESPONSE_RESERVE_S)
        cmd.extend(["--progress", str(progress), "--budget", str(work_budget)])
        try:
            code, out, err = _run_worker(cmd, timeout=timeout_s, cwd=folder, output=run_dir)
        except subprocess.TimeoutExpired:
            return _partial(progress, run_id, t0)
        except OSError as error:
            return {"error": f"assay could not start: {error}", "hint": INSTALL_HINT, "id": run_id}
    else:
        code, out, err = runner(cmd, timeout_s)
    if code == 124:
        return _partial(progress, run_id, t0)
    ms = int((time.monotonic() - t0) * 1000)
    try:
        payload = json.loads(out.strip()) if out.strip() else None
    except ValueError:
        payload = None
    if payload is None:
        tail = (err or out or "").strip().splitlines()[-3:]
        last = _read_progress(progress).get("stopped_at")
        hint = " | ".join(tail) or f"exit code {code}"
        if last:
            hint += f" (last step: {last['stage']})"
        return {"error": "assay gave no JSON", "hint": hint, "id": run_id, "ms": ms}
    if not isinstance(payload, dict) or "cases" not in payload:
        tail = (err or "").strip().splitlines()[-2:]
        return {"error": "assay could not check this page", "hint": " | ".join(tail) or "not a page assay can open", "id": run_id, "ms": ms}
    result = reduce_run(payload)
    result["engine"] = payload.get("engine", "Vitruvius page checker")
    result["unchecked"] = int(payload.get("unchecked", 0))
    result.update({"id": run_id, "ms": ms, "folder": str(folder), "entry": entry,
                   "exit_code": code, "timed_out": False})
    return result


__all__ = ["available", "prepare", "reduce_run", "run", "INSTALL_HINT"]
