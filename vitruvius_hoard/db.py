"""SQLite connection (WAL) and ordered schema migrations."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1: library (sources, documents, chunks + FTS5, styles, palettes, font_pairings, rules)
    """
    CREATE TABLE sources (
      id TEXT PRIMARY KEY,
      kind TEXT NOT NULL DEFAULT 'git',
      url TEXT NOT NULL DEFAULT '',
      license TEXT NOT NULL DEFAULT '',
      category TEXT NOT NULL DEFAULT '',
      tags TEXT NOT NULL DEFAULT '[]',
      paths TEXT NOT NULL DEFAULT '[]',
      structured INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'idle',
      error TEXT NOT NULL DEFAULT '',
      docs INTEGER NOT NULL DEFAULT 0,
      chunks INTEGER NOT NULL DEFAULT 0,
      commit_sha TEXT NOT NULL DEFAULT '',
      last_ingest_ts REAL,
      note TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE documents (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_id TEXT NOT NULL,
      path TEXT NOT NULL,
      title TEXT NOT NULL DEFAULT '',
      kind TEXT NOT NULL DEFAULT 'other',
      lang TEXT NOT NULL DEFAULT '',
      bytes INTEGER NOT NULL DEFAULT 0,
      hash TEXT NOT NULL DEFAULT '',
      updated_ts REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX documents_source ON documents(source_id);
    CREATE TABLE chunks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      document_id INTEGER NOT NULL,
      heading TEXT NOT NULL DEFAULT '',
      ordinal INTEGER NOT NULL DEFAULT 0,
      text TEXT NOT NULL DEFAULT '',
      tokens INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX chunks_document ON chunks(document_id);
    CREATE VIRTUAL TABLE chunks_fts USING fts5(heading, text, content='chunks', content_rowid='id');
    CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
      INSERT INTO chunks_fts(rowid, heading, text) VALUES (new.id, new.heading, new.text);
    END;
    CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
      INSERT INTO chunks_fts(chunks_fts, rowid, heading, text) VALUES ('delete', old.id, old.heading, old.text);
    END;
    CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN
      INSERT INTO chunks_fts(chunks_fts, rowid, heading, text) VALUES ('delete', old.id, old.heading, old.text);
      INSERT INTO chunks_fts(rowid, heading, text) VALUES (new.id, new.heading, new.text);
    END;
    CREATE TABLE chunk_vectors (
      chunk_id INTEGER PRIMARY KEY,
      dim INTEGER NOT NULL,
      vec BLOB NOT NULL
    );
    CREATE TABLE styles (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_id TEXT NOT NULL,
      name TEXT NOT NULL DEFAULT '',
      slug TEXT NOT NULL DEFAULT '',
      description TEXT NOT NULL DEFAULT '',
      keywords TEXT NOT NULL DEFAULT '[]',
      colors TEXT NOT NULL DEFAULT '[]',
      typography TEXT NOT NULL DEFAULT '{}',
      effects TEXT NOT NULL DEFAULT '[]',
      best_for TEXT NOT NULL DEFAULT '[]',
      avoid TEXT NOT NULL DEFAULT '[]',
      css_hints TEXT NOT NULL DEFAULT '',
      raw TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX styles_source ON styles(source_id);
    CREATE TABLE palettes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_id TEXT NOT NULL,
      name TEXT NOT NULL DEFAULT '',
      product_type TEXT NOT NULL DEFAULT '',
      colors TEXT NOT NULL DEFAULT '[]',
      notes TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX palettes_source ON palettes(source_id);
    CREATE TABLE font_pairings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_id TEXT NOT NULL,
      heading TEXT NOT NULL DEFAULT '',
      body TEXT NOT NULL DEFAULT '',
      mono TEXT NOT NULL DEFAULT '',
      category TEXT NOT NULL DEFAULT '',
      mood TEXT NOT NULL DEFAULT '',
      google_fonts_url TEXT NOT NULL DEFAULT '',
      notes TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX font_pairings_source ON font_pairings(source_id);
    CREATE TABLE rules (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_id TEXT NOT NULL,
      area TEXT NOT NULL DEFAULT 'content',
      severity TEXT NOT NULL DEFAULT 'info',
      title TEXT NOT NULL DEFAULT '',
      text TEXT NOT NULL DEFAULT '',
      check_id TEXT
    );
    CREATE INDEX rules_source ON rules(source_id);
    CREATE INDEX rules_area ON rules(area);
    CREATE INDEX rules_check_id ON rules(check_id);
    """,
    # 2: renders, critiques, design systems, references + FTS, settings
    """
    CREATE TABLE renders (
      id TEXT PRIMARY KEY,
      created_ts REAL NOT NULL,
      kind TEXT NOT NULL DEFAULT 'html',
      input_hash TEXT NOT NULL DEFAULT '',
      url TEXT NOT NULL DEFAULT '',
      title TEXT NOT NULL DEFAULT '',
      widths TEXT NOT NULL DEFAULT '[]',
      dark INTEGER NOT NULL DEFAULT 0,
      files TEXT NOT NULL DEFAULT '[]',
      metrics TEXT NOT NULL DEFAULT '{}',
      lint TEXT NOT NULL DEFAULT '{}',
      ms REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX renders_created ON renders(created_ts);
    CREATE TABLE critiques (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      render_id TEXT NOT NULL,
      created_ts REAL NOT NULL,
      focus TEXT NOT NULL DEFAULT '',
      score REAL NOT NULL DEFAULT 0,
      heuristic_score REAL NOT NULL DEFAULT 0,
      vision_model TEXT,
      findings TEXT NOT NULL DEFAULT '[]',
      summary TEXT NOT NULL DEFAULT '',
      ms REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX critiques_render ON critiques(render_id);
    CREATE TABLE design_systems (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL DEFAULT '',
      created_ts REAL NOT NULL,
      brief TEXT NOT NULL DEFAULT '{}',
      tokens TEXT NOT NULL DEFAULT '{}',
      css TEXT NOT NULL DEFAULT '',
      tailwind TEXT NOT NULL DEFAULT '',
      preview_render_id TEXT
    );
    CREATE INDEX design_systems_created ON design_systems(created_ts);
    CREATE TABLE references_t (
      id TEXT PRIMARY KEY,
      created_ts REAL NOT NULL,
      url TEXT NOT NULL DEFAULT '',
      title TEXT NOT NULL DEFAULT '',
      description TEXT NOT NULL DEFAULT '',
      tags TEXT NOT NULL DEFAULT '[]',
      note TEXT NOT NULL DEFAULT '',
      vibe TEXT NOT NULL DEFAULT '',
      files TEXT NOT NULL DEFAULT '{}',
      palette TEXT NOT NULL DEFAULT '[]',
      fonts TEXT NOT NULL DEFAULT '[]',
      libs TEXT NOT NULL DEFAULT '[]',
      motion TEXT NOT NULL DEFAULT '{}',
      analysis TEXT NOT NULL DEFAULT '{}',
      source_id TEXT
    );
    CREATE INDEX references_created ON references_t(created_ts);
    CREATE VIRTUAL TABLE references_fts USING fts5(title, description, tags, note, vibe, fonts, libs, content='references_t', content_rowid='rowid');
    CREATE TRIGGER references_ai AFTER INSERT ON references_t BEGIN
      INSERT INTO references_fts(rowid, title, description, tags, note, vibe, fonts, libs)
      VALUES (new.rowid, new.title, new.description, new.tags, new.note, new.vibe, new.fonts, new.libs);
    END;
    CREATE TRIGGER references_ad AFTER DELETE ON references_t BEGIN
      INSERT INTO references_fts(references_fts, rowid, title, description, tags, note, vibe, fonts, libs)
      VALUES ('delete', old.rowid, old.title, old.description, old.tags, old.note, old.vibe, old.fonts, old.libs);
    END;
    CREATE TRIGGER references_au AFTER UPDATE ON references_t BEGIN
      INSERT INTO references_fts(references_fts, rowid, title, description, tags, note, vibe, fonts, libs)
      VALUES ('delete', old.rowid, old.title, old.description, old.tags, old.note, old.vibe, old.fonts, old.libs);
      INSERT INTO references_fts(rowid, title, description, tags, note, vibe, fonts, libs)
      VALUES (new.rowid, new.title, new.description, new.tags, new.note, new.vibe, new.fonts, new.libs);
    END;
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
]


class Database:
    """One connection shared by every thread, guarded by a re-entrant lock.

    The app is the only writer; the MCP bridge never opens this file.
    """

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.migrate()

    def migrate(self) -> None:
        with self.lock:
            self.conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self.conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = row["v"] or 0
            for index, sql in enumerate(MIGRATIONS, start=1):
                if index <= current:
                    continue
                script = f"BEGIN;\n{sql}\nINSERT INTO schema_version(version) VALUES ({index});\nCOMMIT;"
                try:
                    self.conn.executescript(script)
                except Exception:
                    if self.conn.in_transaction:
                        self.conn.execute("ROLLBACK")
                    raise

    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, params)

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def transaction(self):
        """`with db.transaction():` — BEGIN IMMEDIATE / COMMIT (ROLLBACK on error) under the lock."""
        return _Transaction(self)

    def close(self) -> None:
        with self.lock:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self.conn.close()


class _Transaction:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        self.db.conn.execute("BEGIN IMMEDIATE")
        return self.db.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.db.conn.execute("COMMIT")
            else:
                self.db.conn.execute("ROLLBACK")
        finally:
            self.db.lock.release()
        return False
