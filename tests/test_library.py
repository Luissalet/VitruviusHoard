import json

from vitruvius_hoard import library
from vitruvius_hoard.config import Config
from vitruvius_hoard.db import Database


def seeded_db(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    db = Database(config.db_path)
    db.execute("INSERT INTO sources(id, kind, url, license, status) VALUES ('src1','git','u','MIT','ready')")
    doc = db.execute(
        "INSERT INTO documents(source_id, path, title, kind) VALUES ('src1', 'AGENTS.md', 'Agents', 'rule')"
    )
    doc_id = doc.lastrowid
    db.execute(
        "INSERT INTO chunks(document_id, heading, ordinal, text) VALUES (?, 'Motion', 0, 'Use eased transitions with short duration for UI motion.')",
        (doc_id,),
    )
    db.execute(
        "INSERT INTO chunks(document_id, heading, ordinal, text) VALUES (?, 'Contrast', 1, 'Text must have sufficient contrast against its background.')",
        (doc_id,),
    )
    db.execute(
        "INSERT INTO rules(source_id, area, severity, title, text, check_id) VALUES ('src1','motion','warn','No linear easing','Do not use linear easing for UI transitions.','motion.linear-easing')"
    )
    db.execute(
        "INSERT INTO rules(source_id, area, severity, title, text, check_id) VALUES ('src1','color','error','Avoid generic gradient','Avoid the purple to blue gradient on buttons.','color.purple-blue-gradient')"
    )
    db.execute(
        "INSERT INTO styles(source_id, name, slug, description, keywords) VALUES ('src1','Aurora','aurora','Vibrant gradient aesthetic','[\"gradient\",\"vibrant\"]')"
    )
    db.execute(
        "INSERT INTO palettes(source_id, name, product_type, colors) VALUES ('src1','Finance Dark','finance','[{\"role\":\"primary\",\"hex\":\"#1b2f9e\"}]')"
    )
    db.execute(
        "INSERT INTO font_pairings(source_id, heading, body, mood) VALUES ('src1','Fraunces','Inter','editorial')"
    )
    return db


def test_search_finds_chunk_by_keyword(tmp_path):
    db = seeded_db(tmp_path)
    items = library.search(db, "contrast")
    assert len(items) == 1
    assert "contrast" in items[0]["text"].lower()


def test_search_cite_format(tmp_path):
    db = seeded_db(tmp_path)
    items = library.search(db, "motion")
    assert items[0]["cite"].startswith("[vitruvius: src1/AGENTS.md")
    assert "§ Motion" in items[0]["cite"]


def test_search_filters_by_kind(tmp_path):
    db = seeded_db(tmp_path)
    items = library.search(db, "motion", kind="rule")
    assert len(items) == 1
    items_none = library.search(db, "motion", kind="catalog")
    assert items_none == []


def test_search_no_hits_returns_empty(tmp_path):
    db = seeded_db(tmp_path)
    assert library.search(db, "nonexistentzzz") == []


def test_search_with_area_includes_rules(tmp_path):
    db = seeded_db(tmp_path)
    items = library.search(db, "zzzznohit", area="motion")
    assert any(i["kind"] == "rule" for i in items)


def test_list_rules_filters(tmp_path):
    db = seeded_db(tmp_path)
    rules = library.list_rules(db, area="color")
    assert len(rules) == 1
    assert rules[0]["check_id"] == "color.purple-blue-gradient"


def test_list_rules_by_severity(tmp_path):
    db = seeded_db(tmp_path)
    rules = library.list_rules(db, severity="error")
    assert len(rules) == 1


def test_brief_composition_deterministic(tmp_path):
    db = seeded_db(tmp_path)
    b1 = library.brief(db, subject="finance dashboard", vibe="aurora", product_type="finance")
    b2 = library.brief(db, subject="finance dashboard", vibe="aurora", product_type="finance")
    assert b1 == b2


def test_brief_picks_matching_style_and_palette(tmp_path):
    db = seeded_db(tmp_path)
    result = library.brief(db, subject="finance dashboard", vibe="aurora", product_type="finance")
    assert any(s["name"] == "Aurora" for s in result["styles"])
    assert result["palette"]["name"] == "Finance Dark"
    assert result["font_pairing"]["heading"] == "Fraunces"


def test_brief_falls_back_to_generated_palette_when_no_catalog_match(tmp_path):
    db = seeded_db(tmp_path)
    result = library.brief(db, subject="something else entirely", product_type="unknown-type-xyz")
    assert result["palette"] is not None
    assert "colors" in result["palette"]


def test_brief_includes_cites(tmp_path):
    db = seeded_db(tmp_path)
    result = library.brief(db, subject="finance dashboard", vibe="aurora")
    assert all(c.startswith("[vitruvius:") for c in result["cites"])
    assert len(result["cites"]) > 0


def test_brief_includes_anti_patterns_and_checklist(tmp_path):
    db = seeded_db(tmp_path)
    result = library.brief(db, subject="anything")
    assert len(result["anti_patterns"]) > 0
    assert len(result["checklist"]) > 0


def test_brief_with_use_model_calls_link(tmp_path):
    from conftest import FakeLink

    db = seeded_db(tmp_path)
    link = FakeLink(chat_text="A bold, editorial direction with warm serif headings.")
    result = library.brief(db, subject="finance dashboard", use_model=True, link=link)
    assert result.get("direction")
    assert len(link.chat_calls) == 1


def test_brief_use_model_failure_is_graceful(tmp_path):
    class BrokenLink:
        def chat(self, *a, **k):
            raise RuntimeError("no model")

    db = seeded_db(tmp_path)
    result = library.brief(db, subject="x", use_model=True, link=BrokenLink())
    assert result["direction"] is None
    assert "direction_error" in result
