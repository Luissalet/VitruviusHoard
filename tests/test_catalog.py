import json

from vitruvius_hoard.ingest import catalog


def test_read_csv_rows():
    text = "name,description\nGlass,Frosted panels\nBrutalist,Raw and bold\n"
    rows = catalog.read_csv_rows(text)
    assert len(rows) == 2
    assert rows[0]["name"] == "Glass"


def test_read_json_rows_list():
    rows = catalog.read_json_rows(json.dumps([{"name": "A"}, {"name": "B"}]))
    assert len(rows) == 2


def test_read_json_rows_wrapped_in_items_key():
    rows = catalog.read_json_rows(json.dumps({"items": [{"name": "A"}]}))
    assert rows == [{"name": "A"}]


def test_read_json_rows_single_object_fallback():
    rows = catalog.read_json_rows(json.dumps({"name": "solo"}))
    assert rows == [{"name": "solo"}]


def test_parse_styles_basic():
    rows = [{"name": "Glassmorphism", "description": "Frosted glass panels", "keywords": "glass;blur",
            "best_for": "dashboards", "avoid": "print"}]
    out = catalog.parse_styles(rows, "src1")
    assert len(out) == 1
    style = out[0]
    assert style["name"] == "Glassmorphism"
    assert style["slug"] == "glassmorphism"
    assert "glass" in style["keywords"]
    assert style["raw"] == rows[0]


def test_parse_styles_skips_rows_without_name():
    rows = [{"description": "no name here"}]
    assert catalog.parse_styles(rows, "src1") == []


def test_parse_palettes_from_hex_list():
    rows = [{"name": "Ocean", "colors": "#123456;#abcdef"}]
    out = catalog.parse_palettes(rows, "src1")
    assert out[0]["name"] == "Ocean"
    hexes = [c["hex"] for c in out[0]["colors"]]
    assert "#123456" in hexes and "#abcdef" in hexes


def test_parse_palettes_from_role_columns():
    rows = [{"name": "Brand", "primary": "112233", "accent": "#ff00ff"}]
    out = catalog.parse_palettes(rows, "src1")
    roles = {c["role"]: c["hex"] for c in out[0]["colors"]}
    assert roles["primary"] == "#112233"
    assert roles["accent"] == "#ff00ff"


def test_parse_font_pairings():
    rows = [{"heading": "Fraunces", "body": "Inter", "mood": "editorial"}]
    out = catalog.parse_font_pairings(rows, "src1")
    assert out[0]["heading"] == "Fraunces"
    assert out[0]["body"] == "Inter"
    assert out[0]["mood"] == "editorial"


def test_parse_font_pairings_skips_empty_rows():
    rows = [{"notes": "nothing useful"}]
    assert catalog.parse_font_pairings(rows, "src1") == []


def test_list_field_handles_separators():
    assert catalog._list_field("a; b; c") == ["a", "b", "c"]
    assert catalog._list_field("a,b") == ["a", "b"]
    assert catalog._list_field("solo") == ["solo"]
    assert catalog._list_field("") == []
