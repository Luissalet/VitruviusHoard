import json

from vitruvius_hoard.config import Config
from vitruvius_hoard.db import Database
from vitruvius_hoard.ingest.runner import ingest_source


def make_local_source(tmp_path, structured=False):
    folder = tmp_path / "local_src"
    folder.mkdir()
    (folder / "README.md").write_text("# My Skill\n## Rules\n- Never use lorem ipsum.\n- Always set alt text.\n")
    (folder / "GUIDE.md").write_text("---\ntitle: Guide\n---\n# Guide\nSome guidance text.\n")
    if structured:
        (folder / "styles.csv").write_text("name,description,keywords\nGlass,Frosted panels,glass;blur\n")
        (folder / "palettes.json").write_text(json.dumps([{"name": "Ocean", "colors": "#112233;#445566"}]))
        (folder / "fonts.csv").write_text("heading,body,mood\nFraunces,Inter,editorial\n")
    (folder / "big.bin").write_bytes(b"\x00\x01" * 500)  # binary, skipped
    huge = "x" * 500_000
    (folder / "huge.md").write_text(huge)  # too large, skipped
    return folder


def make_config(tmp_path):
    return Config(data_dir=tmp_path / "data")


def test_ingest_local_source_creates_documents_and_chunks(tmp_path):
    folder = make_local_source(tmp_path)
    config = make_config(tmp_path)
    db = Database(config.db_path)
    db.execute(
        "INSERT INTO sources(id, kind, url, paths, status) VALUES ('demo', 'local', ?, '[]', 'idle')",
        (str(folder),),
    )
    row = dict(db.one("SELECT * FROM sources WHERE id = 'demo'"))
    result = ingest_source(db, config, row)
    assert result["ok"] is True
    assert result["docs"] == 2  # README.md and GUIDE.md; huge.md and big.bin skipped
    docs = db.query("SELECT * FROM documents WHERE source_id = 'demo'")
    assert len(docs) == 2
    status = dict(db.one("SELECT * FROM sources WHERE id = 'demo'"))
    assert status["status"] == "ready"


def test_ingest_mines_rules_from_readme(tmp_path):
    folder = make_local_source(tmp_path)
    config = make_config(tmp_path)
    db = Database(config.db_path)
    db.execute("INSERT INTO sources(id, kind, url, paths, status) VALUES ('demo', 'local', ?, '[]', 'idle')", (str(folder),))
    ingest_source(db, config, dict(db.one("SELECT * FROM sources WHERE id = 'demo'")))
    rules = db.query("SELECT * FROM rules WHERE source_id = 'demo'")
    assert len(rules) >= 2


def test_ingest_structured_source_parses_catalog(tmp_path):
    folder = make_local_source(tmp_path, structured=True)
    config = make_config(tmp_path)
    db = Database(config.db_path)
    db.execute(
        "INSERT INTO sources(id, kind, url, paths, structured, status) VALUES ('cat', 'local', ?, '[]', 1, 'idle')",
        (str(folder),),
    )
    result = ingest_source(db, config, dict(db.one("SELECT * FROM sources WHERE id = 'cat'")))
    assert result["styles"] == 1
    assert result["palettes"] == 1
    assert result["font_pairings"] == 1
    styles = db.query("SELECT * FROM styles WHERE source_id = 'cat'")
    assert styles[0]["name"] == "Glass"


def test_ingest_local_missing_path_errors(tmp_path):
    config = make_config(tmp_path)
    db = Database(config.db_path)
    db.execute("INSERT INTO sources(id, kind, url, paths, status) VALUES ('bad', 'local', '/no/such/dir', '[]', 'idle')")
    result = ingest_source(db, config, dict(db.one("SELECT * FROM sources WHERE id = 'bad'")))
    assert result["ok"] is False
    status = dict(db.one("SELECT * FROM sources WHERE id = 'bad'"))
    assert status["status"] == "error"


def test_ingest_url_kind_is_a_noop(tmp_path):
    config = make_config(tmp_path)
    db = Database(config.db_path)
    db.execute("INSERT INTO sources(id, kind, url, paths, status) VALUES ('page', 'url', 'https://example.com', '[]', 'idle')")
    result = ingest_source(db, config, dict(db.one("SELECT * FROM sources WHERE id = 'page'")))
    assert result["ok"] is True
    assert result["docs"] == 0
    status = dict(db.one("SELECT * FROM sources WHERE id = 'page'"))
    assert status["status"] == "ready"


def test_ingest_unknown_kind_errors(tmp_path):
    config = make_config(tmp_path)
    db = Database(config.db_path)
    db.execute("INSERT INTO sources(id, kind, url, paths, status) VALUES ('weird', 'ftp', 'ftp://x', '[]', 'idle')")
    result = ingest_source(db, config, dict(db.one("SELECT * FROM sources WHERE id = 'weird'")))
    assert result["ok"] is False


def test_ingest_respects_paths_glob(tmp_path):
    folder = tmp_path / "globsrc"
    (folder / "docs").mkdir(parents=True)
    (folder / "docs" / "keep.md").write_text("# Keep\nkeep this")
    (folder / "skip.md").write_text("# Skip\nskip this")
    config = make_config(tmp_path)
    db = Database(config.db_path)
    db.execute(
        "INSERT INTO sources(id, kind, url, paths, status) VALUES ('globby', 'local', ?, ?, 'idle')",
        (str(folder), json.dumps(["docs/**"])),
    )
    result = ingest_source(db, config, dict(db.one("SELECT * FROM sources WHERE id = 'globby'")))
    docs = db.query("SELECT path FROM documents WHERE source_id = 'globby'")
    paths = [d["path"] for d in docs]
    assert any("keep.md" in p for p in paths)
    assert not any(p == "skip.md" for p in paths)


def test_reingest_clears_old_rows(tmp_path):
    folder = make_local_source(tmp_path)
    config = make_config(tmp_path)
    db = Database(config.db_path)
    db.execute("INSERT INTO sources(id, kind, url, paths, status) VALUES ('demo', 'local', ?, '[]', 'idle')", (str(folder),))
    row = dict(db.one("SELECT * FROM sources WHERE id = 'demo'"))
    ingest_source(db, config, row)
    ingest_source(db, config, dict(db.one("SELECT * FROM sources WHERE id = 'demo'")))
    docs = db.query("SELECT * FROM documents WHERE source_id = 'demo'")
    assert len(docs) == 2  # not doubled
