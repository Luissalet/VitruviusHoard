"""Vendored web guides, their search and reader, the legacy scan and the cold MCP tools."""
import asyncio
import os
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vitruvius_hoard import webguide
from vitruvius_hoard.webguide import legacy
from vitruvius_hoard.webguide.tools import execute


def test_every_guide_is_indexed_with_unique_ids_and_a_summary():
    listing = webguide.listing()
    assert listing["total"] == 210 and len(listing["categories"]) == 17
    ids = [g["id"] for g in listing["guides"]]
    assert len(ids) == len(set(ids))
    assert all(g["title"] and g["summary"] and g["cite"] == f"[vitruvius: webguide/{g['id']}]" for g in listing["guides"])


@pytest.mark.parametrize("query,expected", [
    ("animate a dialog modal backdrop", "animate-to-from-top-layer"),
    ("diálogo modal", "dialog"),
    ("tabla adaptable", "responsive-table"),
    ("modo oscuro", "dark-mode"),
    ("textura de grano", "visually-texture-content"),
    ("paralaje al hacer scroll", "parallax-scroll-effects"),
])
def test_search_finds_the_right_guide_in_english_and_spanish(query, expected):
    assert expected in [g["id"] for g in webguide.search(query, limit=5)["guides"]]


def test_search_filters_by_category_and_empty_query_lists_all():
    only = webguide.search("form", category="forms", limit=50)["guides"]
    assert only and {g["category"] for g in only} == {"forms"}
    assert webguide.search("zzzqqq")["guides"] == []


def test_read_returns_markdown_reports_unknown_ids_and_rewrites_the_command_line():
    out = webguide.read("menu,nope")
    assert out["missing"] == ["nope"] and out["guides"][0]["id"] == "menu"
    text = out["guides"][0]["markdown"]
    assert "npx" not in text and "web_guide_read" in text
    with pytest.raises(LookupError):
        webguide.read("nope")
    with pytest.raises(ValueError):
        webguide.read("")


def test_every_legacy_rule_points_at_an_existing_guide():
    ids = {g["id"] for g in webguide.listing()["guides"]}
    assert len(legacy.RULES) >= 25
    for rule in legacy.RULES:
        assert rule["guide"] in ids, rule["id"]
        assert rule["native"] and rule["native_es"] and rule["keep_when"] and rule["name_es"]
    assert len({rule["id"] for rule in legacy.RULES}) == len(legacy.RULES)


LEGACY_HTML = """<html><style>.a{float:left}.b{float:right}.c{float:left}.modal-overlay{z-index:99999}.x{transition:max-height .3s}
.w{height:100vh}</style><div class="modal"></div>
<script>$('.x').fadeIn();if(confirm('x'))alert(1);document.addEventListener('click',e=>{if(!menu.contains(e.target))close()});
el.classList.toggle('dark');document.execCommand('copy');window.addEventListener('scroll',()=>{el.style.opacity=1})</script></html>"""


def test_legacy_scan_finds_the_old_patterns_with_lines_and_guides():
    found = {f["rule"]: f for f in legacy.scan_text(LEGACY_HTML, "t.html")}
    assert {"float-layout", "modal-div", "alert-confirm", "click-outside-close", "jquery-animation", "scroll-listener-effects", "dark-class-toggle",
            "clipboard-exec-command", "max-height-transition", "z-index-ceiling", "viewport-height"} <= set(found)
    assert found["float-layout"]["count"] == 3 and found["float-layout"]["guide"] == "css-layout"
    assert found["modal-div"]["cite"] == "[vitruvius: webguide/dialog]"
    assert found["float-layout"]["locations"][0]["line"] == 1


def test_legacy_scan_respects_the_native_feature_already_in_use():
    modern = '<dialog id="d"></dialog><script>d.showModal()</script><div class="modal"></div><style>.w{min-height:100vh;min-height:100dvh}</style>'
    assert {f["rule"] for f in legacy.scan_text(modern, "m.html")} & {"modal-div", "viewport-height"} == set()
    assert legacy.scan_text("<p>plain</p>", "p.html") == []


def test_scan_path_skips_vendor_folders_and_minified_files(tmp_path):
    (tmp_path / "app.css").write_text(".a{float:left}.b{float:right}.c{float:left}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.css").write_text(".a{float:left}.b{float:right}.c{float:left}", encoding="utf-8")
    (tmp_path / "x.min.js").write_text("$('a').fadeIn();", encoding="utf-8")
    report = legacy.scan_path(str(tmp_path))
    assert report["files_scanned"] == 1 and [f["file"] for f in report["findings"]] == ["app.css"]
    assert report["summary"][0]["rule"] == "float-layout"
    with pytest.raises(FileNotFoundError):
        legacy.scan_path(str(tmp_path / "missing"))


def test_mcp_tools_run_with_modules_off(tmp_path):
    out = asyncio.run(execute(None, "web_guide_search", {"query": "popover tooltip"}))
    assert out["guides"]
    assert asyncio.run(execute(None, "web_guide_search", {}))["total"] == 210
    assert asyncio.run(execute(None, "web_guide_read", {"ids": "dialog"}))["guides"][0]["markdown"]
    scan = asyncio.run(execute(None, "web_legacy_scan", {"sources": [{"name": "a.html", "text": LEGACY_HTML}]}))
    assert scan["findings"]
    (tmp_path / "a.css").write_text(".a{float:left}.b{float:right}.c{float:left}", encoding="utf-8")
    assert asyncio.run(execute(None, "web_legacy_scan", {"path": str(tmp_path)}))["findings"]


def test_host_catalogue_and_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("VITRUVIUS_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("HOARD_EVENTS", "0")
    from vitruvius_hoard.software.host import create_app
    with TestClient(create_app(), base_url="http://127.0.0.1:5191") as client:
        token_file = Path(os.environ.get("VITRUVIUS_TOKEN_FILE") or tmp_path / "mcp-token")
        token = token_file.read_text().strip()
        names = {row["name"] for row in client.get("/api/agent/tools").json()["tools"]}
        assert {"web_guide_search", "web_guide_read", "web_legacy_scan"} <= names
        assert client.get("/api/webguide", params={"query": "dialog"}).json()["guides"]
        assert client.get("/api/webguide/dialog").json()["guides"][0]["id"] == "dialog"
        assert client.get("/api/webguide/none").status_code == 404
        assert client.get("/api/webguide/legacy-rules").json()["rules"]
        scanned = client.post("/api/webguide/scan", json={"sources": [{"name": "a.html", "text": LEGACY_HTML}]}).json()
        assert scanned["findings"]
        called = client.post("/api/agent/call", headers={"Authorization": "Bearer " + token},
                             json={"name": "web_guide_read", "arguments": {"ids": "menu"}})
        assert called.status_code == 200 and "menu" in json.dumps(called.json())
