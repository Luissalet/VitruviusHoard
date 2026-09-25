"""Background ingest runner: one source at a time, progress kept in `sources.status`.

`ingest_now()` is the synchronous variant used by the CLI and by tests.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import queue
import threading
import time
from pathlib import Path
from typing import Any, Optional

from ..db import Database
from . import catalog as catalog_mod
from . import rules as rules_mod
from .git import clone_or_pull
from .markdown import chunk_markdown

MAX_FILE_BYTES = 400_000
TEXT_EXTENSIONS = {".md", ".mdx", ".txt", ".rst"}
STRUCTURED_EXTENSIONS = {".csv", ".json"}


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:1024]


def _matches_any(rel_posix: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    low = rel_posix.lower()
    return any(fnmatch.fnmatch(low, pat.lower()) for pat in patterns)


_SKIP_DIR_RE = re.compile(r"(^|/)(node_modules|dist|build|e2e|tests?|__tests__|changelog|changelogs|contributing|\.github|coverage|vendor|vendors|third[_-]party|examples?/[^/]+/node_modules)(/|$)", re.IGNORECASE)
_SKIP_FILE_RE = re.compile(r"(^|/)(changelog|contributing|code_of_conduct|security|package(-lock)?\.json|.*\.lock|.*\.min\.(js|css)|.*\.(umd|bundle)\.js)$", re.IGNORECASE)


def looks_minified(text: str) -> bool:
    """Bundled or minified code: very long lines, no prose worth citing."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    longest = max(len(ln) for ln in lines)
    average = sum(len(ln) for ln in lines) / len(lines)
    return longest > 2000 or average > 300


def _iter_files(root: Path, patterns: list[str]):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        if _SKIP_DIR_RE.search(rel) or _SKIP_FILE_RE.search(rel):
            continue
        if _matches_any(rel, patterns):
            yield path, rel


def _guess_catalog_kind(rel_path: str) -> Optional[str]:
    low = rel_path.lower()
    if "style" in low:
        return "styles"
    if "palette" in low or "color" in low:
        return "palettes"
    if "font" in low or "typograph" in low:
        return "font_pairings"
    return "table"


def _row_dict(source_id: str) -> dict[str, Any]:
    return {"id": source_id}


def ingest_source(db: Database, config: Any, source: dict[str, Any]) -> dict[str, Any]:
    """Run one source's ingest synchronously. `source` is a dict from the `sources` row."""
    source_id = source["id"]
    kind = source.get("kind", "git")
    url = source.get("url", "")
    paths = json.loads(source.get("paths") or "[]")
    structured = bool(source.get("structured"))

    db.execute("UPDATE sources SET status = 'cloning', error = '' WHERE id = ?", (source_id,))

    dest = Path(config.sources_dir) / source_id
    commit_sha = source.get("commit_sha") or ""

    if kind == "git":
        ok, message, commit = clone_or_pull(url, dest)
        if not ok:
            db.execute("UPDATE sources SET status = 'error', error = ? WHERE id = ?", (message, source_id))
            return {"ok": False, "error": message}
        commit_sha = commit or commit_sha
    elif kind == "local":
        dest = Path(url)
        if not dest.is_dir():
            db.execute("UPDATE sources SET status = 'error', error = ? WHERE id = ?", ("local path not found", source_id))
            return {"ok": False, "error": "local path not found"}
    elif kind == "url":
        db.execute(
            "UPDATE sources SET status = 'ready', docs = 0, chunks = 0, last_ingest_ts = ?, note = ? WHERE id = ?",
            (time.time(), "Single-URL sources are not crawled; use reference_add for that URL instead.", source_id),
        )
        return {"ok": True, "docs": 0, "chunks": 0}
    else:
        db.execute("UPDATE sources SET status = 'error', error = ? WHERE id = ?", (f"unknown kind {kind}", source_id))
        return {"ok": False, "error": f"unknown kind {kind}"}

    db.execute("UPDATE sources SET status = 'ingesting' WHERE id = ?", (source_id,))

    doc_count = 0
    chunk_count = 0
    style_rows: list[dict] = []
    palette_rows: list[dict] = []
    font_rows: list[dict] = []
    rule_rows: list[dict] = []

    with db.transaction() as conn:
        conn.execute("DELETE FROM chunks WHERE document_id IN (SELECT id FROM documents WHERE source_id = ?)", (source_id,))
        conn.execute("DELETE FROM documents WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM styles WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM palettes WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM font_pairings WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM rules WHERE source_id = ?", (source_id,))

        for path, rel in _iter_files(dest, paths):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if _is_binary(data):
                continue
            ext = path.suffix.lower()
            text = data.decode("utf-8", errors="replace")

            if structured and ext in STRUCTURED_EXTENSIONS:
                catalog_kind = _guess_catalog_kind(rel)
                try:
                    rows = catalog_mod.read_csv_rows(text) if ext == ".csv" else catalog_mod.read_json_rows(text)
                except Exception:  # noqa: BLE001
                    rows = []
                if catalog_kind == "styles":
                    style_rows.extend(catalog_mod.parse_styles(rows, source_id))
                elif catalog_kind == "palettes":
                    palette_rows.extend(catalog_mod.parse_palettes(rows, source_id))
                elif catalog_kind == "font_pairings":
                    font_rows.extend(catalog_mod.parse_font_pairings(rows, source_id))
                if rows and ext == ".csv":
                    # Every tabular catalog is also searchable row by row (motion recipes,
                    # UX guidelines, landing patterns, chart advice, per-stack notes).
                    table_chunks = catalog_mod.rows_to_chunks(rows, path.stem.replace("-", " "))
                    if table_chunks:
                        cur = conn.execute(
                            "INSERT INTO documents(source_id, path, title, kind, lang, bytes, hash, updated_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (source_id, rel, path.stem, "catalog", "", size, hashlib.sha1(data).hexdigest(), time.time()),
                        )
                        doc_id = cur.lastrowid
                        doc_count += 1
                        for c in table_chunks:
                            conn.execute(
                                "INSERT INTO chunks(document_id, heading, ordinal, text, tokens) VALUES (?, ?, ?, ?, ?)",
                                (doc_id, c["heading"], c["ordinal"], c["text"], max(1, len(c["text"]) // 4)),
                            )
                            chunk_count += 1
                    rule_rows.extend(catalog_mod.rows_to_rules(rows, source_id))
                continue

            if ext not in TEXT_EXTENSIONS and ext not in (".py", ".js", ".ts", ""):
                continue
            if ext in (".js", ".ts", "") and looks_minified(text):
                continue

            result = chunk_markdown(text, default_title=path.stem)
            cur = conn.execute(
                "INSERT INTO documents(source_id, path, title, kind, lang, bytes, hash, updated_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (source_id, rel, result["title"], _doc_kind(rel), "", size, hashlib.sha1(data).hexdigest(), time.time()),
            )
            doc_id = cur.lastrowid
            doc_count += 1
            for c in result["chunks"]:
                conn.execute(
                    "INSERT INTO chunks(document_id, heading, ordinal, text, tokens) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, c["heading"], c["ordinal"], c["text"], c["tokens"]),
                )
                chunk_count += 1

            rule_rows.extend(rules_mod.mine_rules(text, source_id))

        for row in style_rows:
            conn.execute(
                "INSERT INTO styles(source_id, name, slug, description, keywords, colors, typography, effects, best_for, avoid, css_hints, raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["source_id"], row["name"], row["slug"], row["description"], json.dumps(row["keywords"]),
                 json.dumps(row["colors"]), json.dumps(row["typography"]), json.dumps(row["effects"]),
                 json.dumps(row["best_for"]), json.dumps(row["avoid"]), row["css_hints"], json.dumps(row["raw"])),
            )
        for row in palette_rows:
            conn.execute(
                "INSERT INTO palettes(source_id, name, product_type, colors, notes) VALUES (?,?,?,?,?)",
                (row["source_id"], row["name"], row["product_type"], json.dumps(row["colors"]), row["notes"]),
            )
        for row in font_rows:
            conn.execute(
                "INSERT INTO font_pairings(source_id, heading, body, mono, category, mood, google_fonts_url, notes) VALUES (?,?,?,?,?,?,?,?)",
                (row["source_id"], row["heading"], row["body"], row["mono"], row["category"], row["mood"],
                 row["google_fonts_url"], row["notes"]),
            )
        for row in rule_rows:
            conn.execute(
                "INSERT INTO rules(source_id, area, severity, title, text, check_id) VALUES (?,?,?,?,?,?)",
                (row["source_id"], row["area"], row["severity"], row["title"], row["text"], row["check_id"]),
            )

    db.execute(
        "UPDATE sources SET status = 'ready', docs = ?, chunks = ?, commit_sha = ?, last_ingest_ts = ?, error = '' WHERE id = ?",
        (doc_count, chunk_count, commit_sha, time.time(), source_id),
    )
    return {"ok": True, "docs": doc_count, "chunks": chunk_count, "styles": len(style_rows),
            "palettes": len(palette_rows), "font_pairings": len(font_rows), "rules": len(rule_rows)}


def _doc_kind(rel_path: str) -> str:
    low = rel_path.lower()
    if "readme" in low:
        return "readme"
    if "skill" in low:
        return "skill"
    if "rule" in low or "agents" in low:
        return "rule"
    if "guide" in low:
        return "guide"
    if "catalog" in low:
        return "catalog"
    if "demo" in low:
        return "reference"
    return "other"


class IngestRunner:
    """A single background worker thread processing one source at a time."""

    def __init__(self, db: Database, config: Any, emit=None):
        self.db = db
        self.config = config
        self.emit = emit or (lambda *a, **k: None)
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="vitruvius-ingest", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put("")
        if self._thread is not None:
            self._thread.join(timeout=5)

    def enqueue(self, source_id: str) -> None:
        self.db.execute("UPDATE sources SET status = 'idle' WHERE id = ? AND status = 'error'", (source_id,))
        self._queue.put(source_id)

    def _run(self) -> None:
        while not self._stop.is_set():
            source_id = self._queue.get()
            if not source_id:
                continue
            row = self.db.one("SELECT * FROM sources WHERE id = ?", (source_id,))
            if row is None:
                continue
            try:
                result = ingest_source(self.db, self.config, dict(row))
                self.emit("vitruvius.source.ingested", {"source_id": source_id, **result})
            except Exception as error:  # noqa: BLE001
                self.db.execute("UPDATE sources SET status = 'error', error = ? WHERE id = ?", (str(error), source_id))
