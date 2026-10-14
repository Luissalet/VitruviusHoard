"""Write the isometric example of the docs: spec JSON plus the light and dark SVG, with the gate report.

    python scripts/make_isometric_example.py [--out docs/examples]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vitruvius_hoard.diagrams import Diagram, make  # noqa: E402
from vitruvius_hoard.diagrams.examples import CACHE  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "docs" / "examples"))
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    result = make(Diagram.model_validate(CACHE))
    (out / "isometric-cache.json").write_text(json.dumps(CACHE, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for mode, text in result["svg"].items():
        (out / f"isometric-cache-{mode}.svg").write_text(text + "\n", encoding="utf-8")
    print(f"gates: {'all pass' if result['ok'] else 'FAILED ' + ', '.join(result['failed'])}; wrote {out}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
