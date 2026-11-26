from hashlib import sha256
import json
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

import pytest

from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.app_preview import PREVIEW_SCRIPTS, SCRIPT_DIR, inject_scripts
from vitruvius_hoard.app_projects import AppProjects
from vitruvius_hoard.hoard_link.agentkit import AppError


ITEMS = [{"id": "estuary", "title": {"es": "Carta de la ría", "en": "Estuary chart"},
          "category": {"es": "Siglo XVII", "en": "17th century"}}]


def test_booking_export_has_the_same_page_as_the_owned_preview(tmp_path):
    projects = AppProjects(tmp_path)
    try:
        project = projects.create("Cartas de costa", template="booking", items=ITEMS, lang="es")
        preview = projects.preview(project["id"])
        export = projects.export(project["id"], project["revision"])
        assert sha256(Path(export["path"]).read_bytes()).hexdigest() == export["sha256"]
        with ZipFile(export["path"]) as archive:
            page = archive.read("public/index.html")
            assert b'<html lang="es">' in page
            assert "Carta de la ría" in page.decode()
            assert json.loads(archive.read("website.json"))["form"]["fields"]["item"] == "estuary"
        with urlopen(preview["url"], timeout=5) as response:
            scripts = ("app-bridge.js", *(name for name in PREVIEW_SCRIPTS if (SCRIPT_DIR / name).is_file()))
            expected = inject_scripts(page.decode("utf-8"), scripts, preview["revision"])
            assert response.read().decode("utf-8") == expected
        with pytest.raises(ValueError, match="unique"):
            projects.create("Duplicate", template="booking", items=ITEMS * 2)
    finally:
        projects.close()


def test_project_render_keeps_all_capture_widths_after_capping(client, monkeypatch):
    widths = [390, 768, 1440]
    captures = [{"width": width, "path": f"{width}.png"} for width in widths]
    monkeypatch.setattr(client.svc, "app_project_render", lambda *_: {
        "widths": widths, "files": captures, "metrics": {}, "_probe": {"huge": ["x" * 30000]},
    })
    result = call_tool(client.svc, "app_project_render", {"widths": widths})
    assert result["widths"] == widths and result["files"] == captures


def test_project_undo_checks_current_revision_and_keeps_saved_edits(tmp_path):
    projects = AppProjects(tmp_path)
    original = projects.create("Booking", template="booking", items=ITEMS)
    changed = projects.update(original["id"], {"notes.txt": "Edited"}, original["revision"])
    with pytest.raises(ValueError, match="revision changed"):
        projects.undo(**original["undo"]["arguments"])
    restored = projects.undo(**changed["undo"]["arguments"])
    assert restored["revision"] == original["revision"] and "notes.txt" not in restored["files"]
    assert projects.get(original["id"], changed["revision"])["files"]["notes.txt"] == "Edited"
    disposable = projects.create("Disposable")
    assert projects.undo(**disposable["undo"]["arguments"])["archived"]
    assert {row["id"] for row in projects.list()} == {original["id"]}


def test_clean_profile_uses_bundled_rules_and_requested_palette(client):
    result = call_tool(client.svc, "design_rules", {"area": "a11y", "limit": 10})
    catalog = call_tool(client.svc, "design_rules_list", {"scope": "a11y"})
    assert result["count"] == 10
    assert {rule["id"] for rule in result["rules"]} <= {rule["id"] for rule in catalog["rules"]}
    brief = call_tool(client.svc, "design_brief", {"subject": "Cartas de costa", "vibe": "marfil y azul tinta"})
    assert brief["rules"] and brief["palette"]["colors"][0]["hex"] == "#18364d"


def test_assay_passes_local_preview_url_to_browser_worker(client):
    calls = []

    def runner(cmd, timeout_s):
        calls.append(cmd)
        return 0, '{"works":true,"cases":[]}', ""

    client.svc.assay_runner = runner
    url = "http://127.0.0.1:1234/app?lang=es"
    result = call_tool(client.svc, "page_assay", {"url": url, "timeout_s": 45})
    assert result["works"] and calls[0][-2:] == ["--url", url]


def test_assay_timeout_is_a_tool_error(client, monkeypatch):
    monkeypatch.setattr(client.svc, "assay_page", lambda **_: {"error": "assay timed out", "works": False})
    with pytest.raises(AppError, match="assay timed out") as error:
        call_tool(client.svc, "page_assay", {"html": "<p>Test</p>"})
    assert error.value.status == 504


def test_assay_detects_one_link_and_one_button_despite_their_nested_labels(tmp_path):
    pytest.importorskip("playwright")
    from vitruvius_hoard.functional_check.browser import elements, moved, signature, unreached
    from vitruvius_hoard.functional_check.run import Browser

    (tmp_path / "index.html").write_text(
        '<style>button {cursor:pointer}</style><a href="#here"><span>Chart</span> <span>XVII</span></a>'
        '<button id="here"><span>Reserve</span></button><p>' + ("Chart " * 100) + '</p><p id="message"></p>',
        encoding="utf-8",
    )
    with Browser(tmp_path, "index.html") as engine, engine.open() as (page, *_):
        assert [control.kind for control in elements(page) if control.kind] == ["link", "button"]
        assert "pointer" not in unreached(page)
        before = signature(page)
        page.locator("#message").evaluate("(message) => { message.textContent = 'A reservation needs an email address'; }")
        assert moved(before, signature(page))
