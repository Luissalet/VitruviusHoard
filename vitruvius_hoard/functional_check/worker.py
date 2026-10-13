"""Owned, isolated process boundary for the normal page_check and page_assay tools."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

# The owned worker is invoked by absolute path even when its cwd is the page.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vitruvius_hoard.functional_check import check, PASSED, Case


def main():
    parser = argparse.ArgumentParser(description="Measure and exercise a local page in a real browser")
    parser.add_argument("folder")
    parser.add_argument("-e", "--entry", default="index.html")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--criteria", type=Path)
    args = parser.parse_args()
    criteria = json.loads(args.criteria.read_text(encoding="utf-8")) if args.criteria else []
    cases = [Case(**{**row, "origin": "criterion"}) for row in criteria]
    result = check(args.folder, args.entry, criteria=cases)
    payload = {
        "engine": "Vitruvius page checker", "format": "vitruvius-page-check/v1",
        "planned": len(result.plan), "passed": sum(row.outcome == PASSED for row in result.results.values()),
        "failed": sum(row.failed for row in result.results.values()), "works": result.works and not result.unchecked,
        "unchecked": len(result.unchecked),
        "surface": [{"kind": row.kind, "selector": row.selector, "label": row.label, "enabled": row.enabled} for row in result.surface.controls] if result.surface else [],
        "cases": [{"id": row.case.id, "what": row.case.what, "outcome": row.outcome,
                   "detail": row.detail, "measured": row.evidence, "acts": row.case.acts} for row in result.results.values()],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["works"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
