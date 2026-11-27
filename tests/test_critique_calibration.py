"""Replay the reviewed exports without storing app sources or screenshots in Git."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from vitruvius_hoard import browser
from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.config import Config
from vitruvius_hoard.services import Services


CASES = [
    ("01-lampara", "01-lampara.zip", 4, 7, "13b868136841b91f42deb3c3ca54f7a27790bbe70105d67bb6feae59dc8fb0b6"),
    ("02-estaciones", "02-estaciones.zip", 3, 6, "99064b8399c2d05516c010bad9f61da555f25695db6d27a987968630a0688ba7"),
    ("03-ceramica", "03-ceramica.zip", 2, 7, "30892d6cd6498d95ad2fef772d5c8a4a5b02414ba7fbbde86db7457c21b91368"),
    ("04-fisio", "04-fisio.zip", 3, 5, "23bfda48e06e26580fbbd4804ad149b2c182953dcb390ae5198816eaab707db1"),
    ("05-fotografa", "05-fotografa.zip", 2, 8, "68da9e74cba93ffb65c24071c50f1e93d8c051431e3b83b8447b3636047603c7"),
    ("06-alta-autonomo", "06-orlavia.zip", 4, 6, "cdd0a5787d7fce66cbfacad4d735bbb52101ccde064f12f9498361a5fafc6ccb"),
    ("07-precios", "07-pliegoa.zip", 4, 6, "c56ea06680dca0360d855fabc31f68e69d6e0264c096a874e7d1d920adc956ef"),
    ("08-plantas", "08-brotavia.zip", 2, 6, "631eaa1f4705d0982b51dcab1616d5bfc781c8729dcc587db92e94bd08f97cc0"),
    ("09-restaurante", "09-veravell.zip", 3, 7, "f946efaccfb77a50f851699894c57afda70d8fac3e56fb048ce2824aabfaad71"),
    ("10-banco", "10-ribera-nacar.zip", 4, 7, "0bb15747e67f01b4e641df72cc096bab771af99d90840eab11c50a55ab238280"),
]
COMPOSITION = "webcraft/category-composition"
NATIVE = "webcraft/native-control-chrome"
SCAFFOLD = "webcraft/scaffold-copy"


@pytest.fixture(scope="module")
def calibration_browser(tmp_path_factory):
    bank_requested = bool(os.environ.get("VITRUVIUS_CRITIQUE_BANK"))
    if bank_requested:
        assert browser._sync_playwright_available(), "The reviewed exports need Playwright and Chrome"
    else:
        pytest.importorskip("playwright.sync_api")
    with pytest.MonkeyPatch.context() as patch:
        if bank_requested:
            patch.setattr(browser, "launch_attempts", lambda: [("chrome", {"channel": "chrome"})])
        launch_args = browser.launch_args
        patch.setattr(browser, "launch_args", lambda: [*launch_args(), "--disable-gpu"])
        services = Services(
            Config(data_dir=tmp_path_factory.mktemp("critique"), port=56164, render_timeout_s=75, embed_backend="none"),
            link=SimpleNamespace(),
        )
        try:
            yield services
        finally:
            services.stop()


@pytest.fixture(scope="module")
def reviewed_exports():
    path = os.environ.get("VITRUVIUS_CRITIQUE_BANK")
    if not path:
        pytest.skip("Set VITRUVIUS_CRITIQUE_BANK to the external reviewed exports")
    directory = Path(path)
    assert directory.is_dir(), f"Missing calibration bank: {directory}"
    return directory


def _critique(services, render):
    error = render["metrics"].get("error")
    if error == "no browser" and not os.environ.get("VITRUVIUS_CRITIQUE_BANK"):
        pytest.skip("No headless browser available")
    assert not error, render["metrics"]
    assert render["files"], "The browser produced no captures"
    return call_tool(services, "design_critique", {"render_id": render["id"], "use_vision": False}, cap=False)


@pytest.mark.parametrize(("name", "filename", "round_seen", "judge", "digest"), CASES, ids=[c[0] for c in CASES])
def test_export_critique_matches_blind_review(calibration_browser, reviewed_exports, name, filename, round_seen, judge, digest):
    case = reviewed_exports / name
    archive_path = case / "export" / filename
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == digest
    review = json.loads((case / "revisor.json").read_text(encoding="utf-8-sig"))
    assert (review["ronda_vista"], review["nota"]) == (round_seen, judge)

    with ZipFile(archive_path) as archive:
        files = {
            name: archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if not name.endswith("/") and name != "vitruvius-export.json"
        }
    project = calibration_browser.app_projects.create_from_files(
        name, json.loads(files["project.json"]).get("template", "local"), files,
    )
    try:
        preview = call_tool(calibration_browser, "app_project_preview", {"id": project["id"]}, cap=False)
        assert preview["state"] == "running"
        render = call_tool(calibration_browser, "app_project_render", {
            "id": project["id"], "revision": project["revision"], "widths": [390, 834, 1440],
        }, cap=False)
        assert render["app_project"]["revision"] == project["revision"]
        result = _critique(calibration_browser, render)
        findings = {f["check_id"]: f for f in result["findings"]}
        print(f"{name}: judge {judge}, critique {result['score']:.2f}, "
              f"gap {abs(result['score'] - judge):.2f}")
        assert abs(result["score"] - judge) <= 1.5
        assert result["score"] == result["heuristic_score"]

        if name == "01-lampara":
            assert "repeated-editorial-bands" in {p["kind"] for p in findings[COMPOSITION]["evidence"]["patterns"]}
        if name == "04-fisio":
            lint = call_tool(calibration_browser, "design_lint", {"render_id": render["id"]}, cap=False)
            assert "font.generic-only" in {f["check_id"] for f in lint["findings"]}
            assert {"font.generic-only", NATIVE, COMPOSITION} <= findings.keys()
            fonts = findings["font.generic-only"]["evidence"]["fonts"]
            assert any("Atkinson Hyperlegible" in stack for font in fonts for stack in font["requested"])
            assert "atkinson hyperlegible" not in {font["rendered"] for font in fonts}
        if name == "06-alta-autonomo":
            assert "Entorno de prueba" in findings[SCAFFOLD]["detail"]
            assert "single-form-card" in {p["kind"] for p in findings[COMPOSITION]["evidence"]["patterns"]}
        if name == "07-precios":
            assert "featured-middle-price" in {p["kind"] for p in findings[COMPOSITION]["evidence"]["patterns"]}
        if name == "09-restaurante":
            assert any(c["type"] == "date" and c["state"] == "closed_dialog"
                       for c in findings[NATIVE]["evidence"]["controls"])
        for rule in ({COMPOSITION, NATIVE, SCAFFOLD, "font.generic-only"} & findings.keys()):
            assert findings[rule]["score_weight"] > 0 and findings[rule]["detail_es"]
    finally:
        calibration_browser.app_projects.stop(project["id"])


def test_hidden_copy_and_custom_indicators_do_not_count(calibration_browser):
    result = call_tool(calibration_browser, "render_preview", {"widths": [1440], "html": """
        <!doctype html><html lang=en><meta name=viewport content="width=device-width">
        <style>
        body {font-family:system-ui;max-width:60rem;margin:auto}
        h1 {font-family:Georgia,serif}
        #custom {appearance:none;background:#edfcf9;border:1px solid #366}
        </style>
        <main><h1>Reading room</h1><p>Books are available all week.</p>
        <label>Day <select id=native><option>Monday</option></select></label>
        <label>Room <select id=custom><option>North</option></select></label>
        <p hidden>Entorno de prueba</p><div style="opacity:0"><span>Portfolio de muestra</span></div><div hidden><input type=date id=hidden-date></div>
        </main></html>
    """}, cap=False)
    critique = _critique(calibration_browser, result)
    findings = {f["check_id"]: f for f in critique["findings"]}
    assert SCAFFOLD not in findings
    assert "font.generic-only" not in findings
    assert [c["selector"] for c in findings[NATIVE]["evidence"]["controls"]] == ["select#native"]



def test_scaffold_copy_split_across_inline_elements(calibration_browser):
    render = call_tool(calibration_browser, "render_preview", {"widths": [1440], "html": '''
        <!doctype html><html lang=es><meta name=viewport content="width=device-width">
        <main><h1>Biblioteca</h1><p id=notice>Entorno <strong>de prueba</strong></p></main></html>
    '''}, cap=False)
    result = _critique(calibration_browser, render)
    finding = next(f for f in result["findings"] if f["check_id"] == SCAFFOLD)
    assert finding["evidence"]["items"] == [{"text": "Entorno de prueba", "element": "p#notice"}]


@pytest.mark.parametrize("changed_split", [False, True])
def test_editorial_bands_need_three_consecutive_matching_splits(calibration_browser, changed_split):
    layout = "1fr 1fr" if changed_split else "2fr 3fr"
    render = call_tool(calibration_browser, "render_preview", {"widths": [1440], "html": f"""
        <!doctype html><html lang="en"><meta name="viewport" content="width=device-width">
        <style>
          main {{max-width: 70rem; margin: auto}}
          section {{display: grid; grid-template-columns: 2fr 3fr; min-height: 170px}}
          section:nth-child(2) {{grid-template-columns: {layout}}}
        </style>
        <main>
          <section><h1>Archive</h1><p>Paper, leather and photographs.</p></section>
          <section><h2>Workshop</h2><p>Bindings and paper repair.</p></section>
          <section><h2>Visits</h2><p>Table space for eight readers.</p></section>
        </main>
    """}, cap=False)
    result = _critique(calibration_browser, render)
    patterns = {pattern["kind"] for item in result["findings"] if item["check_id"] == COMPOSITION
                for pattern in item["evidence"]["patterns"]}
    assert ("repeated-editorial-bands" in patterns) is not changed_split
