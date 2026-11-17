"""The control style sets: the bundled MIT sets (Sakuga VFX, Rubber Hose UI, Pixel Worlds) and the on-demand effects pack with a required credit."""
from __future__ import annotations

import asyncio
import hashlib
import io
from pathlib import Path

import pytest

from vitruvius_hoard import craft
from vitruvius_hoard.craft import ui_sets
from vitruvius_hoard.craft.tools import catalog, execute
from vitruvius_hoard.browser import _sync_playwright_available

HERE = Path(__file__).resolve().parent.parent
BUNDLED = {"sakuga-vfx": 11, "rubber-hose-ui": 11, "pixel-worlds": 6}


def test_three_bundled_sets_each_with_their_licence_and_pinned_commit():
    by_id = {s["id"]: s for s in ui_sets.sets()}
    assert {k: len(v["controls"]) for k, v in by_id.items()} == BUNDLED
    for set_id, owner in by_id.items():
        assert owner["license"] == "MIT" and len(owner["commit"]) == 40 and owner["source"].startswith("https://github.com/")
        assert "MIT License" in (ui_sets.ROOT / set_id / "LICENSE").read_text(encoding="utf-8")
        for c in owner["controls"]:
            assert (ui_sets.ROOT / set_id / c["file"]).stat().st_size == c["bytes"] > 1000
            assert c["use_when_es"] and c["avoid_when_es"] and c["demo"].startswith("<" + c["tag"])


def test_search_finds_the_style_for_what_is_asked():
    assert craft.search("controles anime con efectos", kind="ui-set")["items"][0]["id"] == "sakuga-vfx"
    assert craft.search("pixel art carga", kind="ui-set")["items"][0]["id"] == "pixel-worlds"
    assert craft.search("dibujos animados 1930", kind="ui-set")["items"][0]["id"] == "rubber-hose-ui"
    ids = [i["id"] for i in craft.search("boton anime", kind="ui-control", limit=3)["items"]]
    assert ids[0] == "sakuga-vfx/button"
    kinds = craft.search("anime")["by_kind"]
    assert kinds.get("ui-set", 0) >= 2 and kinds.get("ui-control", 0) >= 11
    with pytest.raises(ValueError):
        craft.search("x", kind="ui-sets")


def test_read_a_set_and_a_control():
    owner = craft.read("ui-set", "sakuga-vfx")
    assert owner["delivery"] == "bundled" and len(owner["controls"]) == 11 and owner["board_url"] == "/craft/ui-sets/sakuga-vfx/index.html"
    one = craft.read("ui-control", "sakuga-vfx/tooltip")
    assert one["tag"] == "sakuga-tooltip" and "Una ayuda" in one["usage"] and one["preview_url"].endswith("/tooltip/index.html")
    assert craft.read("ui-control", "pixel-worlds/hoard")["accessibility_note"]
    with pytest.raises(LookupError):
        craft.read("ui-control", "sakuga-vfx/nope")
    with pytest.raises(LookupError):
        craft.read("ui-set", "nope")


def test_the_credit_pack_is_listed_but_never_bundled():
    row = next(s for s in ui_sets.listing() if s["id"] == "kanaworks-sakuga-vfx")
    assert row["delivery"] == "on_demand" and row["credit"] == "VFX: KanaWorks_AI (@KanaWorks_AI)"
    read = craft.read("ui-set", "kanaworks-sakuga-vfx")
    assert "descargan bajo demanda" in read["conditions_es"] and "controls" not in read
    assert not (ui_sets.ROOT / "kanaworks-sakuga-vfx").exists()
    assert not list((HERE / "vitruvius_hoard").rglob("*.flipbook.json"))
    with pytest.raises(LookupError):
        craft.page("ui-set", "kanaworks-sakuga-vfx")


def test_a_control_page_is_a_complete_document_with_its_script_inline():
    doc = craft.page("ui-control", "rubber-hose-ui/button")
    assert doc["html"].startswith("<!doctype html>") and "customElements.define" in doc["html"] and "<hose-button>Confirmar</hose-button>" in doc["html"]
    assert "MIT" in doc["html"] and 'lang="es"' in doc["html"]
    linked = craft.page("ui-control", "sakuga-vfx/button", {"inline": False})
    assert '<script src="/craft/ui-sets/sakuga-vfx/button.js">' in linked["html"] and len(linked["html"]) < 6000
    assert "show('Guardado')" in craft.page("ui-control", "sakuga-vfx/toast")["html"]
    assert "Sakuga VFX" in craft.page("ui-set", "sakuga-vfx")["html"]


def test_install_writes_only_into_the_chosen_folder_with_the_licence(tmp_path):
    result = ui_sets.install("sakuga-vfx", str(tmp_path), ["button", "toast"])
    assert sorted(p.name for p in (tmp_path / "sakuga-vfx").iterdir()) == ["LICENSE", "button.js", "toast.js"]
    assert result["snippet"].count("<script") == 2 and "<sakuga-toast></sakuga-toast>" in result["snippet"]
    assert (tmp_path / "sakuga-vfx" / "button.js").read_bytes() == (ui_sets.ROOT / "sakuga-vfx" / "button.js").read_bytes()
    assert len(list((tmp_path / "pixel-worlds").iterdir())) == 0 if (tmp_path / "pixel-worlds").exists() else True
    everything = ui_sets.install("pixel-worlds", str(tmp_path))
    assert len([f for f in everything["files"] if f.endswith(".js")]) == 6
    with pytest.raises(LookupError):
        ui_sets.install("sakuga-vfx", str(tmp_path), ["nope"])
    with pytest.raises(LookupError):
        ui_sets.install("kanaworks-sakuga-vfx", str(tmp_path))


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_the_credit_pack_downloads_one_effect_with_its_credit_beside_it(tmp_path):
    seen = []

    def opener(url):
        seen.append(url)
        return _Response(b"PK\x03\x04 effect")

    result = ui_sets.fetch("kanaworks-sakuga-vfx", "fire_impact_01", str(tmp_path), opener=opener)
    assert seen == ["https://github.com/kanaworksai-hue/kanaworks-sakuga-vfx/releases/download/v1.0.0/fire_impact_01.zip"]
    folder = tmp_path / "kanaworks-sakuga-vfx"
    assert (folder / "fire_impact_01.zip").read_bytes() == b"PK\x03\x04 effect"
    assert result["sha256"] == hashlib.sha256(b"PK\x03\x04 effect").hexdigest()
    credit = (folder / "CREDIT.txt").read_text(encoding="utf-8")
    assert credit.startswith("VFX: KanaWorks_AI (@KanaWorks_AI)") and "License" in credit
    for bad in ("../x", "fire_impact_09", "fire impact", "lava_impact_01", ""):
        with pytest.raises(ValueError):
            ui_sets.fetch("kanaworks-sakuga-vfx", bad, str(tmp_path), opener=opener)
    with pytest.raises(LookupError):
        ui_sets.fetch("sakuga-vfx", "fire_impact_01", str(tmp_path), opener=opener)
    with pytest.raises(ValueError):
        ui_sets.fetch("kanaworks-sakuga-vfx", "fire_impact_01", str(tmp_path), opener=lambda url: _Response(b"x" * 40_000_001))


def test_tools_search_read_page_install(tmp_path):
    names = {t["name"] for t in catalog(lambda name, *args, **kwargs: {"name": name})}
    assert {"ui_set_install", "ui_set_fetch"} <= names
    found = asyncio.run(execute(None, "craft_search", {"query": "anime", "kind": "ui-set"}))
    assert {"sakuga-vfx", "kanaworks-sakuga-vfx"} <= {i["id"] for i in found["items"][:2]}
    assert asyncio.run(execute(None, "craft_read", {"kind": "ui-control", "id": "sakuga-vfx/button"}))["tag"] == "sakuga-button"
    assert "<sakuga-slider" in asyncio.run(execute(None, "craft_page", {"kind": "ui-control", "id": "sakuga-vfx/slider"}))["html"]
    out = asyncio.run(execute(None, "ui_set_install", {"set": "rubber-hose-ui", "out_dir": str(tmp_path), "controls": ["toggle"]}))
    assert (tmp_path / "rubber-hose-ui" / "toggle.js").is_file() and out["license"] == "MIT"


def test_rest_pages_and_files(tmp_path, monkeypatch):
    monkeypatch.setenv("VITRUVIUS_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("HOARD_EVENTS", "0")
    from fastapi.testclient import TestClient
    from vitruvius_hoard.software.host import create_app
    with TestClient(create_app(), base_url="http://127.0.0.1:5191") as client:
        _rest(client)


def _rest(client):
    assert "Sakuga VFX" in client.get("/craft/ui-sets/").text
    assert "Pestañas" in client.get("/craft/ui-sets/sakuga-vfx/index.html").text
    assert "<sakuga-tabs" in client.get("/craft/ui-sets/sakuga-vfx/tabs/index.html").text
    script = client.get("/craft/ui-sets/pixel-worlds/sage.js")
    assert script.status_code == 200 and "customElements.define" in script.text
    assert "MIT License" in client.get("/craft/ui-sets/pixel-worlds/LICENSE").text
    for url in ("/craft/ui-sets/nope/index.html", "/craft/ui-sets/sakuga-vfx/../catalog.json", "/craft/ui-sets/sakuga-vfx/secret.js", "/craft/ui-sets/kanaworks-sakuga-vfx/index.html"):
        assert client.get(url).status_code == 404
    assert client.get("/api/craft/ui-control/sakuga-vfx/button").json()["tag"] == "sakuga-button"
    assert "<sakuga-button>" in client.get("/api/craft/ui-control/sakuga-vfx/button/page").text
    assert client.get("/api/craft/texture/grass").status_code == 200 and client.get("/api/craft/ui-control/sakuga-vfx/nope").status_code == 404


@pytest.mark.skipif(not _sync_playwright_available(), reason="no browser available")
def test_every_bundled_control_loads_and_takes_keyboard_focus_in_a_real_browser(tmp_path):
    from vitruvius_hoard.browser import BrowserWorker
    worker = BrowserWorker(tmp_path)
    worker.start()
    try:
        for owner in ui_sets.sets():
            for c in owner["controls"]:
                doc = craft.page("ui-control", f"{owner['id']}/{c['id']}")
                shot = worker.capture(html=doc["html"], widths=[900], full_page=False, wait_ms=150)
                if shot.get("error"):
                    pytest.skip(str(shot["error"]))
                probe = shot["probe"]
                assert probe["script_errors"] == [], (owner["id"], c["id"])
                assert probe["keyboard"]["tab_stops"] >= 1, (owner["id"], c["id"])
    finally:
        worker.stop()
