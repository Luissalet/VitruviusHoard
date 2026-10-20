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
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .hoard_link import proc

INSTALL_HINT = "The page checker is incorporated in Vitruvius; its Playwright browser dependency must be installed."
DEFAULT_TIMEOUT_S = 300


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
        "surface": [{"kind": s.get("kind"), "label": s.get("label"), "selector": s.get("selector"), "enabled": s.get("enabled")}
                    for s in (run.get("surface") or [])][:80],
        "failing": [{"id": c.get("id"), "what": c.get("what"), "detail": c.get("detail"), "measured": c.get("measured"),
                     "acts": c.get("acts"), "environment": c.get("environment", {})} for c in failing][:max_cases],
        "cases_sample": [{"id": c.get("id"), "what": c.get("what"), "outcome": c.get("outcome"),
                          "environment": c.get("environment", {}), "measured": c.get("measured")} for c in cases[:max_cases]],
    }


def run(data_dir: Path, *, html: Optional[str] = None, path: Optional[str] = None,
        timeout_s: int = DEFAULT_TIMEOUT_S, runner: Any = None, criteria: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Run assay on a page and return the reduced result (never raises for a failed page).

    `runner(cmd, timeout_s) -> (returncode, stdout, stderr)` can be injected by tests.
    """
    if not available() and runner is None:
        return {"error": "page checker browser dependency is not installed", "hint": INSTALL_HINT}
    folder, entry, run_id = prepare(data_dir, html=html, path=path)
    cmd = _command(folder, entry)
    if criteria:
        criterion_dir = data_dir / "assay" / run_id
        criterion_dir.mkdir(parents=True, exist_ok=True)
        criterion_path = criterion_dir / "criteria.json"
        criterion_path.write_text(json.dumps(criteria, ensure_ascii=False), encoding="utf-8")
        cmd.extend(["--criteria", str(criterion_path)])
    t0 = time.monotonic()
    if runner is None:
        try:
            done = proc.run(cmd, timeout=timeout_s, cwd=folder)  # the whole process tree is killed on a timeout
            code, out, err = done.returncode, done.stdout, done.stderr
        except subprocess.TimeoutExpired:
            return {"error": "assay timed out", "hint": f"the page kept the browser busy for more than {timeout_s} s", "id": run_id}
        except OSError as error:
            return {"error": f"assay could not start: {error}", "hint": INSTALL_HINT, "id": run_id}
    else:
        code, out, err = runner(cmd, timeout_s)
    ms = int((time.monotonic() - t0) * 1000)
    try:
        payload = json.loads(out.strip()) if out.strip() else None
    except ValueError:
        payload = None
    if payload is None:
        tail = (err or out or "").strip().splitlines()[-3:]
        return {"error": "assay gave no JSON", "hint": " | ".join(tail) or f"exit code {code}", "id": run_id, "ms": ms}
    if not isinstance(payload, dict) or "cases" not in payload:
        tail = (err or "").strip().splitlines()[-2:]
        return {"error": "assay could not check this page", "hint": " | ".join(tail) or "not a page assay can open", "id": run_id, "ms": ms}
    result = reduce_run(payload)
    result["engine"] = payload.get("engine", "Vitruvius page checker")
    result["unchecked"] = int(payload.get("unchecked", 0))
    result.update({"id": run_id, "ms": ms, "folder": str(folder), "entry": entry, "exit_code": code})
    return result


__all__ = ["available", "prepare", "reduce_run", "run", "INSTALL_HINT"]
