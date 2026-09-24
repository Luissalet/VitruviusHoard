"""Functional check of a generated page with `assay` (pip install assay-ui).

The design lint says whether a page *looks* right; assay says whether it
*works*: it opens the page in a real browser, measures every control it
finds, works out a test plan from the rendered interface (no tests written,
no model) and reports contradictions — a button that does nothing, a value
shown as `undefined`, a control that answers differently to the same input.

This module only wraps the CLI: the page is written to
``data/assay/<id>/index.html`` (or an existing local folder/page is used),
``assay <folder> --json`` runs in a subprocess with a hard timeout, and the
JSON run is reduced to what an assistant needs: did it work, what failed,
what the page offers. Nothing here needs assay at import time.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

INSTALL_HINT = "pip install assay-ui (in the app's venv) — see https://github.com/awss1i/assay"
DEFAULT_TIMEOUT_S = 300


def available() -> bool:
    """True when the `assay` package is importable by this interpreter or on PATH."""
    return importlib.util.find_spec("assay") is not None or shutil.which("assay") is not None


def _command(folder: Path, entry: str) -> list[str]:
    if importlib.util.find_spec("assay") is not None:
        base = [sys.executable, "-c", "from assay.cli import main; raise SystemExit(main())"]
    else:
        base = [shutil.which("assay") or "assay"]
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
                     "acts": c.get("acts")} for c in failing][:max_cases],
        "cases_sample": [{"id": c.get("id"), "what": c.get("what"), "outcome": c.get("outcome")} for c in cases[:max_cases]],
    }


def run(data_dir: Path, *, html: Optional[str] = None, path: Optional[str] = None,
        timeout_s: int = DEFAULT_TIMEOUT_S, runner: Any = None) -> dict[str, Any]:
    """Run assay on a page and return the reduced result (never raises for a failed page).

    `runner(cmd, timeout_s) -> (returncode, stdout, stderr)` can be injected by tests.
    """
    if not available() and runner is None:
        return {"error": "assay is not installed", "hint": INSTALL_HINT}
    folder, entry, run_id = prepare(data_dir, html=html, path=path)
    cmd = _command(folder, entry)
    t0 = time.monotonic()
    if runner is None:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, cwd=str(folder))
            code, out, err = proc.returncode, proc.stdout, proc.stderr
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
    result.update({"id": run_id, "ms": ms, "folder": str(folder), "entry": entry, "exit_code": code})
    return result


__all__ = ["available", "prepare", "reduce_run", "run", "INSTALL_HINT"]
