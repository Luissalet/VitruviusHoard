"""``python -m vitruvius_hoard --list-rules [--pack P] [--engine E] [--severity S] [--tier T] [--source S] [--query Q] [--json] [--rule ID]``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence


def list_rules_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="vitruvius-hoard --list-rules", description="List the design rules (the registry the lint, the critique and the tools run).")
    parser.add_argument("--list-rules", action="store_true")
    parser.add_argument("--pack")
    parser.add_argument("--engine", choices=("static", "browser", "visual"))
    parser.add_argument("--severity", choices=("error", "warning", "advisory"))
    parser.add_argument("--tier", choices=("floor", "reflex", "finish"))
    parser.add_argument("--source")
    parser.add_argument("--scope")
    parser.add_argument("--query")
    parser.add_argument("--rule", help="show one rule in full")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    from ..lint import ensure_rules
    from . import registry
    ensure_rules()
    if args.rule:
        rule = registry.get_rule(args.rule)
        if rule is None:
            print(f"unknown rule {args.rule!r}", file=sys.stderr)
            return 1
        print(json.dumps(rule.row(), indent=2, ensure_ascii=False))
        return 0
    rows = registry.list_rules(engine=args.engine, scope=args.scope, severity=args.severity, tier=args.tier, pack=args.pack, source=args.source, query=args.query)
    if args.json:
        print(json.dumps({"summary": registry.summary(), "rules": rows}, indent=2, ensure_ascii=False))
        return 0
    width = max([len(r["id"]) for r in rows] + [4])
    print(f"{'id'.ljust(width)}  {'engine':8} {'scope':8} {'severity':9} {'tier':7} name")
    for r in rows:
        print(f"{r['id'].ljust(width)}  {r['engine']:8} {r['scope']:8} {r['severity']:9} {r['tier']:7} {r['name']}")
    s = registry.summary()
    print(f"\n{len(rows)} of {s['total']} rules  |  packs: " + ", ".join(f"{k} {v}" for k, v in s["by_pack"].items()))
    return 0
