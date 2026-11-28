"""Craft library: textures, heroes, 3D scenes, dashboard rules, the model-site recipe, the critique rules and the cold tools."""
import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vitruvius_hoard import craft, critique as critique_mod, lint
from vitruvius_hoard.craft import dashboard, heroes, model_site, pages, scenes, textures
from vitruvius_hoard.craft.tools import execute


def test_ten_texture_recipes_are_complete_working_css():
    assert [t["id"] for t in textures.TEXTURES] == ["thermal", "blueprint", "waves", "graphite", "fluted", "contour", "grain", "landscape", "grass", "softshadow"]
    for t in textures.TEXTURES:
        assert re.search(rf"\.tx-{t['id']}\b", t["css"]) and t["controls"] and t["use_when"] and t["avoid_when"] and t["why"] and t["title_es"] and t["summary_es"]
        for c in t["controls"]:
            assert c["key"].startswith("--tx-") and c["min"] <= c["default"] <= c["max"]
            assert f"{c['key']}:" in t["css"], (t["id"], c["key"])  # every control is a property the recipe declares
        assert t["css"].count("{") == t["css"].count("}")
        assert "http://" not in t["css"].replace("http://www.w3.org/2000/svg", "")  # nothing loads from the network


def test_landscape_builder_is_seeded():
    assert textures.landscape_svg(7) == textures.landscape_svg(7) != textures.landscape_svg(8)


def test_search_read_and_cites():
    out = craft.search("textura de grano")
    assert "[vitruvius: craft/texture/grain]" in [i["cite"] for i in out["items"][:2]]
    assert craft.search("grano")["items"][0]["cite"] == "[vitruvius: craft/texture/grain]"
    assert craft.search("grass", kind="texture")["items"][0]["id"] == "grass"
    assert craft.search("panel", kind="dashboard-rule")["items"]
    assert craft.search("modelo 3d blender corte")["items"][0]["id"] == "model-site"
    assert craft.search("hero", kind="threeui")["by_kind"] == {"threeui": craft.search("hero", kind="threeui")["matched"]}
    with pytest.raises(ValueError):
        craft.search("x", kind="nope")
    assert "example_html" in craft.read("texture", "thermal") and craft.read("hero", "index-list")["decisions"]["why"]
    assert craft.read("dashboard-rule", "type-scale")["check"]
    detail = craft.read("threeui", "orbital-sphere")
    assert detail["origin"]["license"] == "MIT" and detail["controls"]
    with pytest.raises(LookupError):
        craft.read("texture", "nope")


def test_threeui_catalogue_keeps_provenance_and_counts():
    rows = craft.threeui()
    assert len(rows) == 104 and sum(len(r.get("variants", [])) for r in rows) == 163
    assert all(r["id"] and r["category"] and r["description"] for r in rows)
    assert (craft.ROOT.parent / "craft" / "THIRD_PARTY.md").exists()


def test_every_generated_page_is_clean_under_the_critique_rules():
    pages_ = [pages.texture_page(t["id"]) for t in textures.TEXTURES] + [heroes.page(h["id"]) for h in heroes.HEROES] + [dashboard.calm_dashboard()]
    for doc in pages_:
        result = lint.run_lint({}, doc["html"], packs=["webcraft"])
        assert result["findings"] == [], (doc["title"], [f["title"] for f in result["findings"]])
        assert 'lang="es"' in doc["html"] and doc["sha256"]


def test_dashboard_rules_catch_the_generic_dashboard_and_pass_the_calm_one():
    found = {f["check_id"] for f in lint.run_lint({}, dashboard.slop_dashboard()["html"], packs=["webcraft"])["findings"]}
    assert {"webcraft/dashboard-type-scale", "webcraft/dashboard-card-styles", "webcraft/dashboard-welcome-banner",
            "webcraft/dashboard-actions-below", "webcraft/dashboard-command-palette"} <= found
    assert lint.run_lint({}, dashboard.calm_dashboard()["html"], packs=["webcraft"])["findings"] == []
    registered = {r["id"] for r in __import__("vitruvius_hoard.rules.registry", fromlist=["x"]).list_rules(pack="webcraft")}
    assert {rule["rule"] for rule in dashboard.RULES if rule["rule"]} <= registered


def test_a_non_dashboard_is_never_judged_as_one():
    page = "<html><body><h1>Welcome back</h1><button>Go</button></body></html>"
    assert lint.run_lint({}, page, packs=["webcraft"])["findings"] == []


def test_flat_surface_and_legacy_findings_cite_references_and_guides():
    flat = "<html><head><style>body{background:#fff}.a{float:left}.b{float:right}.c{float:left}</style></head><body><h1>Hola</h1><p>" + "texto " * 60 + "</p></body></html>"
    result = critique_mod.critique(probe={}, html=flat, use_vision=False)
    ids = {f["check_id"] for f in result["findings"]}
    assert {"webcraft/flat-hero-surface", "webcraft/legacy-pattern"} <= ids
    assert any(g["guide"] == "css-layout" and g["cite"] == "[vitruvius: webguide/css-layout]" for g in result["web_guidance"])
    assert {"texture"} <= {r["kind"] for r in result["references"]}
    dash = critique_mod.critique(probe={}, html=dashboard.slop_dashboard()["html"], use_vision=False, focus="dashboard panel")
    assert any(r["kind"] == "dashboard-rule" and r["id"] == "type-scale" for r in dash["references"])


def test_new_rules_have_spanish_text_and_are_registered():
    from vitruvius_hoard import i18n_es
    from vitruvius_hoard.rules.registry import list_rules
    lint.ensure_rules()
    rows = list_rules(pack="webcraft")
    assert len(rows) == 10 and all(r["runnable"] and r["id"] in i18n_es.RULES_ES for r in rows)


def test_scene_pages_carry_their_controls():
    for s in scenes.SCENES:
        doc = scenes.page(s["id"])
        assert f'data-scene="{s["id"]}"' in doc["html"] and "/craft/scenes.js" in doc["html"]
        assert all(c["min"] <= c["default"] <= c["max"] for c in s["controls"])


def test_model_site_script_is_valid_python_and_validates_inputs():
    script = model_site.blender_script("C:/m/house.glb", "C:/out", None)
    compile(script, "blender_script.py", "exec")
    assert "bpy.ops.render.render(animation=True)" in script and script.count('"name": "') == 4
    custom = model_site.blender_script("m.obj", "out", [{"name": "a b", "azimuth": 10}], section=False)
    assert '"name": "a-b"' in custom and '"enabled": false' in custom
    for bad in ({"section_axis": "w"}, {"section_view": 5}, {"engine": "X"}):
        with pytest.raises(ValueError):
            model_site.blender_script("m.glb", "o", [{"name": "v"}], **bad)
    page = model_site.site_page("Casa", "Vistas", model_site.DEFAULT_VIEWS)["html"]
    assert "corte-de-seccion.mp4" in page and page.count("<img") == 3 and "alt=" in page


def test_cold_tools_and_host_routes(tmp_path, monkeypatch):
    out = asyncio.run(execute(None, "craft_search", {"query": "vidrio", "kind": "texture"}))
    assert out["items"][0]["id"] == "fluted"
    assert asyncio.run(execute(None, "craft_read", {"kind": "texture", "id": "grain"}))["css"]
    html = asyncio.run(execute(None, "craft_page", {"kind": "texture", "id": "blueprint", "params": {"title": "Planos", "--tx-cell": 24}}))["html"]
    assert "Planos" in html and "--tx-cell:24" in html
    plan = asyncio.run(execute(None, "craft_model_site", {"model": "m.glb", "out_dir": "o"}))
    assert plan["outputs"][-1] == "corte-de-seccion.mp4" and "bpy" in plan["script"] and plan["page"]["html"]
    monkeypatch.setenv("VITRUVIUS_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("HOARD_EVENTS", "0")
    from vitruvius_hoard.software.host import create_app
    with TestClient(create_app(), base_url="http://127.0.0.1:5191") as client:
        token_file = Path(os.environ.get("VITRUVIUS_TOKEN_FILE") or tmp_path / "mcp-token")
        token = token_file.read_text().strip()
        names = {row["name"] for row in client.get("/api/agent/tools").json()["tools"]}
        assert {"craft_search", "craft_read", "craft_page", "craft_model_site"} <= names
        for url in ("/craft/", "/craft/textures/", "/craft/dashboard/index.html", "/craft/scenes.js", "/craft/heroes/index-list/index.html",
                    "/craft/scenes/orbital/index.html", "/api/craft/texture/grass/page"):
            assert client.get(url).status_code == 200, url
        assert client.get("/api/craft", params={"query": "grano"}).json()["items"]
        assert client.get("/api/craft/texture/nope").status_code == 404 and client.get("/api/craft", params={"kind": "x"}).status_code == 400
        called = client.post("/api/agent/call", headers={"Authorization": "Bearer " + token}, json={"name": "craft_read", "arguments": {"kind": "hero", "id": "typographic-wall"}})
        assert called.status_code == 200


def _blender():
    import glob
    return shutil.which("blender") or next(iter(sorted(glob.glob("C:/Program Files/Blender Foundation/*/blender.exe"))[::-1]), None)


@pytest.mark.skipif(not _blender(), reason="Blender is not installed")
def test_blender_runs_the_generated_script(tmp_path):
    glb = tmp_path / "m.obj"
    glb.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0 0 1\nv 1 0 1\nv 1 1 1\nv 0 1 1\nf 1 4 3 2\nf 5 6 7 8\nf 1 2 6 5\nf 2 3 7 6\nf 3 4 8 7\nf 4 1 5 8\n", encoding="utf-8")
    script = tmp_path / "s.py"
    script.write_text(model_site.blender_script(str(glb), str(tmp_path / "out"), model_site.DEFAULT_VIEWS[:2], engine="WORKBENCH", width=320, height=180, fps=8, seconds=2), encoding="utf-8")
    done = subprocess.run([_blender(), "--background", "--factory-startup", "--python", str(script)], capture_output=True, text=True, timeout=300)
    assert "DONE" in done.stdout, done.stdout[-800:] + done.stderr[-800:]
    assert (tmp_path / "out" / "tres-cuartos-frontal.png").exists() and (tmp_path / "out" / "corte-de-seccion.mp4").exists()
