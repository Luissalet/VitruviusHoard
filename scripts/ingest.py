"""CLI: `python scripts/ingest.py [--all|id] [--data-dir DIR]` — runs the
ingestor synchronously (no background thread) and prints doc/chunk counts.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vitruvius_hoard.config import Config  # noqa: E402
from vitruvius_hoard.db import Database  # noqa: E402
from vitruvius_hoard.ingest.runner import ingest_source  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest one or every Vitruvius's Hoard source.")
    parser.add_argument("id", nargs="?", help="Source id to ingest.")
    parser.add_argument("--all", action="store_true", help="Ingest every known source.")
    parser.add_argument("--data-dir", default=None, help="Override VITRUVIUS_DATA_DIR.")
    args = parser.parse_args()

    if not args.id and not args.all:
        parser.error("give a source id or --all")

    config = Config.from_env()
    if args.data_dir:
        config.data_dir = Path(args.data_dir)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.sources_dir.mkdir(parents=True, exist_ok=True)
    db = Database(config.db_path)

    import json
    seeds_path = ROOT / "vitruvius_hoard" / "seeds.json"
    if seeds_path.is_file():
        seeds = json.loads(seeds_path.read_text(encoding="utf-8"))
        for s in seeds.get("sources", []):
            if db.one("SELECT id FROM sources WHERE id = ?", (s["id"],)):
                continue
            db.execute(
                "INSERT INTO sources(id, kind, url, license, category, tags, paths, structured, status, note) "
                "VALUES (?,?,?,?,?,?,?,?, 'idle', ?)",
                (s["id"], s.get("kind", "git"), s.get("url", ""), s.get("license", ""), s.get("category", ""),
                 json.dumps(s.get("tags", [])), json.dumps(s.get("paths", [])), int(bool(s.get("structured", False))),
                 s.get("note", "")),
            )

    ids = [args.id] if args.id else [r["id"] for r in db.query("SELECT id FROM sources")]
    total_docs = total_chunks = 0
    for source_id in ids:
        row = db.one("SELECT * FROM sources WHERE id = ?", (source_id,))
        if row is None:
            print(f"unknown source: {source_id}", file=sys.stderr)
            continue
        print(f"ingesting {source_id} ...")
        result = ingest_source(db, config, dict(row))
        if result.get("ok"):
            print(f"  ok: {result.get('docs', 0)} docs, {result.get('chunks', 0)} chunks")
            total_docs += result.get("docs", 0)
            total_chunks += result.get("chunks", 0)
        else:
            print(f"  error: {result.get('error')}", file=sys.stderr)

    print(f"Done: {total_docs} docs, {total_chunks} chunks across {len(ids)} source(s).")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
