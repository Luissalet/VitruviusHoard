"""Owned, isolated process boundary for the normal page_check and page_assay tools."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time

# The owned worker is invoked by absolute path even when its cwd is the page.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vitruvius_hoard.functional_check import check, PASSED, Case


def case_row(row):
    return {"id": row.case.id, "what": row.case.what, "outcome": row.outcome,
            "detail": row.detail, "measured": row.evidence, "acts": row.case.acts,
            "environment": row.case.environment}


class _BudgetReached(BaseException):
    """Unwind the browser even when a case handles ordinary driver errors."""


def main():
    parser = argparse.ArgumentParser(description="Measure and exercise a local page in a real browser")
    parser.add_argument("folder")
    parser.add_argument("-e", "--entry", default="index.html")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--criteria", type=Path)
    parser.add_argument("--url", help="Read-only loopback preview to check in place")
    parser.add_argument("--progress", type=Path)
    parser.add_argument("--budget", type=float)
    args = parser.parse_args()
    criteria = json.loads(args.criteria.read_text(encoding="utf-8")) if args.criteria else []
    cases = [Case(**{**row, "origin": "criterion"}) for row in criteria]
    completed = {}
    planned_cases = []
    startup_writes = []
    deadline = time.monotonic() + args.budget if args.budget else float("inf")

    def checkpoint(stage, *, case=None, result=None, action=None, plan=None, startup_blocked_writes=None):
        nonlocal planned_cases, startup_writes
        if plan is not None:
            planned_cases = [{"id": case.id, "what": case.what} for case in plan]
        if startup_blocked_writes is not None:
            startup_writes = startup_blocked_writes
        if result is not None:
            completed[case.id] = case_row(result)
        position = {"stage": stage}
        if case is not None:
            position.update(case_id=case.id, what=case.what)
        if action is not None:
            position["action"] = action
        data = {"stopped_at": position, "planned": len(planned_cases), "plan": planned_cases,
                "cases": list(completed.values()),
                "startup_blocked_writes": startup_writes}
        scratch = args.progress.with_suffix(".tmp")
        scratch.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        scratch.replace(args.progress)

        if time.monotonic() >= deadline:
            raise _BudgetReached

    try:
        result = check(args.folder, args.entry, criteria=cases, url=args.url,
                       on_progress=checkpoint if args.progress else None)
    except _BudgetReached:
        return 124
    payload = {
        "engine": "Vitruvius page checker", "format": "vitruvius-page-check/v1",
        "planned": len(result.plan), "passed": sum(row.outcome == PASSED for row in result.results.values()),
        "failed": sum(row.failed for row in result.results.values()), "works": result.works and not result.unchecked,
        "unchecked": len(result.unchecked),
        "startup_blocked_writes": result.startup_blocked_writes,
        "surface": [{"kind": row.kind, "selector": row.selector, "label": row.label, "enabled": row.enabled} for row in result.surface.controls] if result.surface else [],
        "cases": [case_row(row) for row in result.results.values()],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["works"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
