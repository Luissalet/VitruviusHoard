from hashlib import sha256
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

import pytest

from vitruvius_hoard.agent_tools import call_tool, tool_catalog
from vitruvius_hoard.app_projects import AppProjects


PAGE = """<article class="card" id="one">First <strong>middle</strong> &amp; after</article>
<article class="card" id="two">Second</article>
<article id="bare">Unique</article>
<p>{{description}}</p>
<div>{{table}}</div>"""
CSS = """:root { --accent: #f90; --step: 1.5rem; --alias: var(--step) }
.card, aside.other {
  margin: 8px;
}
:root { --another: 40px; --cyclic: var(--cyclic) }
"""


@pytest.fixture
def opened(tmp_path):
    projects = AppProjects(tmp_path)
    original = projects.create("Canvas", description="Generated description")
    project = projects.update(original["id"], {"pages/index.html": PAGE, "assets/style.css": CSS}, original["revision"])
    try:
        projects.preview(project["id"])
        yield projects, project
    finally:
        projects.close()


def edit(projects, project, line, prop="margin-left", pixels=24, **options):
    return projects.canvas_edit(
        project["id"], f"pages/index.html:{line}:1", "article", project["revision"],
        {"kind": "style", "property": prop, "pixels": pixels}, **options,
    )


def test_canvas_edit_emits_the_agent_actor_only_for_a_change(opened, monkeypatch):
    projects, project = opened
    presence = []
    def record_presence(*args, change):
        assert change["files"] == ["pages/index.html"]
        presence.append(args)
    monkeypatch.setattr(projects.canvas, "prepare_edit", record_presence)
    services = SimpleNamespace(app_projects=projects)
    actor = {"id": "foreman", "name": "Foreman", "color": "#5b42d3"}
    args = {"id": project["id"], "vsrc": "pages/index.html:3:1", "tag": "article",
            "expected_revision": project["revision"], "actor": actor,
            "change": {"kind": "text", "index": 0, "original": "Unique", "value": "Updated"}}

    plan = call_tool(services, "app_project_canvas_edit", {**args, "operation": "plan"})
    assert not plan["changed"]
    assert not presence
    saved = call_tool(services, "app_project_canvas_edit", args)
    assert saved["changed"] and saved["undo"]["tool"] == "app_project_undo"
    assert presence == [(project["id"], project["revision"], actor, {"vsrc": args["vsrc"], "box": None})]


def test_token_and_shared_authored_rule_confirm_then_undo(opened):
    projects, project = opened
    plan = edit(projects, project, 1, operation="plan")
    assert plan["target"] == {"kind": "class", "selector": ".card, aside.other", "file": "assets/style.css"}
    assert plan["affects"] == 2 and plan["confirmation_required"] and plan["token"] == "--step"
    assert plan["scale"] == [{"name": "--step", "pixels": 24.0}, {"name": "--alias", "pixels": 24.0},
                             {"name": "--another", "pixels": 40.0}]
    assert edit(projects, project, 1, expected_count=1)["confirmation_required"]
    assert projects.get(project["id"])["revision"] == project["revision"]

    result = edit(projects, project, 1, expected_count=2)
    assert result["changed"] and result["revision"] != project["revision"]
    current = projects.get(project["id"])
    assert current["files"]["assets/style.css"] == CSS.replace("  margin: 8px;", "  margin: 8px;\n  margin-left: var(--step);")
    assert current["files"]["pages/index.html"] == PAGE
    assert projects.undo(**result["undo"]["arguments"])["files"] == project["files"]


def test_pixel_edit_uses_existing_rule_even_without_a_token(opened):
    projects, project = opened
    result = edit(projects, project, 1, "padding-right", 19, expected_count=2)
    assert result["token"] is None and result["target"]["kind"] == "class"
    assert "padding-right: 19px;" in projects.get(project["id"])["files"]["assets/style.css"]


def test_new_class_is_written_once_and_reused(opened):
    projects, project = opened
    result = edit(projects, project, 3, "height", 41)
    assert result["changed"] and result["affects"] == 1 and not result["confirmation_required"]
    assert result["target"]["kind"] == "new_class"
    selected = result["target"]["selector"]
    current = projects.get(project["id"])
    assert f'<article class="{selected.split(".")[-1]}" id="bare">' in current["files"]["pages/index.html"]
    assert selected.startswith("#bare.canvas-")
    assert selected + " { height: 41px; }" in current["files"]["assets/style.css"]
    assert all(' style=' not in source for name, source in current["files"].items() if name.startswith("pages/index"))
    projects.preview(project["id"])
    same_rule = edit(projects, current, 3, "padding-top", 11, expected_count=1)
    assert same_rule["target"]["selector"] == selected
    updated = projects.get(project["id"])
    assert updated["files"]["assets/style.css"].count(selected) == 1
    projects.preview(project["id"])
    edit(projects, updated, 3, "height", 48, expected_count=1)
    source = projects.get(project["id"])["files"]["assets/style.css"]
    assert source.count("height:") == 1 and "height: 48px;" in source


def test_inline_declarations_keep_unrelated_properties_and_use_separate_rule(tmp_path):
    projects = AppProjects(tmp_path)
    project = projects.create("Inline")
    page = '<article class="card" style="padding:8px;color:red">Example</article>'
    project = projects.update(project["id"], {"pages/index.html": page, "assets/style.css": CSS}, project["revision"])
    try:
        projects.preview(project["id"])
        saved = edit(projects, project, 1, "padding-top", 18)
        assert saved["target"]["kind"] == "new_class"
        current = projects.get(project["id"])
        assert 'style="padding:8px;color:red"' in current["files"]["pages/index.html"]
        assert "padding-top: 18px !important;" in current["files"]["assets/style.css"]
    finally:
        projects.close()


def test_repeat_without_stylesheet_saves_one_link_and_confirms_both_instances(tmp_path):
    projects = AppProjects(tmp_path)
    original = projects.create("Repeated")
    project = projects.update(original["id"], {
        "layout.html": "<!doctype html><html><head></head><body>{{content}}{{content}}</body></html>",
        "pages/index.html": "<article>Example</article>",
    }, original["revision"])
    try:
        projects.preview(project["id"])
        planned = edit(projects, project, 1, "width", 181)
        assert planned["affects"] == 2 and planned["confirmation_required"]
        saved = edit(projects, project, 1, "width", 181, expected_count=2)
        current = projects.get(project["id"])
        assert saved["target"]["file"] == "assets/canvas-edits.css"
        assert '<head><link rel="stylesheet" href="/assets/canvas-edits.css"></head>' in current["files"]["layout.html"]
        assert "width: 181px;" in current["files"]["assets/canvas-edits.css"]
        assert projects.undo(**saved["undo"]["arguments"])["files"] == project["files"]
    finally:
        projects.close()


def test_linked_stylesheets_public_precedence_and_route(opened):
    projects, project = opened
    path = "public/assets/style.css"
    patched = projects.update(project["id"], {path: CSS.replace(".card,", "article.card,")}, project["revision"])
    projects.preview(project["id"], patched["revision"])
    plan = edit(projects, patched, 1, "margin-right", 19, path="/?q=test", operation="plan")
    assert plan["target"]["file"] == path and plan["target"]["selector"] == "article.card, aside.other"


def test_edit_the_chosen_literal_among_direct_text_nodes(opened):
    projects, project = opened
    result = projects.canvas_edit(project["id"], "pages/index.html:1:1", "article", project["revision"],
                                  {"kind": "text", "index": 1, "original": "& after", "value": "New & literal"})
    assert result["changed"]
    current = projects.get(project["id"])
    assert current["files"]["pages/index.html"] == PAGE.replace("&amp; after", "New &amp; literal")
    assert projects.undo(**result["undo"]["arguments"])["files"] == project["files"]


def test_generated_text_and_stale_preview_are_rejected(opened):
    projects, project = opened
    project_id = project["id"]
    revision = project["revision"]
    with pytest.raises(ValueError, match=r"Viene de \{\{description\}\}"):
        projects.canvas_edit(project_id, "pages/index.html:4:1", "p", revision,
                             {"kind": "text", "index": 0, "original": "Generated description", "value": "X"}, lang="es")
    with pytest.raises(ValueError, match=r"Comes from \{\{table\}\}"):
        projects.canvas_edit(project_id, "pages/index.html:5:6", "table", revision,
                             {"kind": "style", "property": "height", "pixels": 12})
    with pytest.raises(ValueError, match="position no longer points"):
        projects.canvas_edit(project_id, "pages/index.html:1:1", "article", revision,
                             {"kind": "text", "index": 1, "original": "wrong", "value": "X"})
    projects.update(project_id, {"assets/style.css": CSS + "aside{color:red}\n"}, revision)
    with pytest.raises(ValueError, match="revisión cambió"):
        edit(projects, project, 3, lang="es")


def test_http_and_agent_share_the_same_plan_and_agent_catalog(client):
    row = next(tool for tool in tool_catalog() if tool["name"] == "app_project_canvas_edit")
    path = Path(__file__).resolve().parents[1] / "vitruvius_hoard" / "software" / "catalog.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    assert row == {key: value for key, value in next(tool for tool in entries if tool["name"] == row["name"]).items() if key != "module"}
    projects = client.svc.app_projects
    root = projects.create("Canvas HTTP")
    project = projects.update(root["id"], {"pages/index.html": PAGE, "assets/style.css": CSS}, root["revision"])
    base = f"/api/app-projects/{project['id']}"
    assert client.post(base + "/preview", json={}).status_code == 200
    try:
        args = {
            "id": project["id"], "vsrc": "pages/index.html:1:1", "tag": "article", "expected_revision": project["revision"],
            "change": {"kind": "style", "property": "margin-left", "pixels": 24}, "operation": "plan",
        }
        response = client.post(base + "/canvas-edit", json=args)
        assert response.status_code == 200
        plan = response.json()
        assert plan == call_tool(client.svc, "app_project_canvas_edit", args)
        write = call_tool(client.svc, "app_project_canvas_edit", {**args, "operation": "apply", "expected_count": plan["affects"]})
        assert write["changed"] and write["undo"]["tool"] == "app_project_undo"
        new = projects.preview(project["id"])
        with urlopen(new["url"] + "/assets/style.css", timeout=5) as stylesheet:
            assert "margin-left: var(--step)" in stylesheet.read().decode("utf-8")
    finally:
        client.post(base + "/preview", json={"operation": "stop"})


def test_canvas_text_and_preview_work_without_the_style_parser(opened, monkeypatch):
    projects, project = opened
    monkeypatch.setitem(sys.modules, "tinycss2", None)
    with pytest.raises(ValueError, match="requiere tinycss2"):
        edit(projects, project, 1, lang="es")
    assert projects.get(project["id"])["preview"]["state"] == "running"
    result = projects.canvas_edit(
        project["id"], "pages/index.html:1:1", "article", project["revision"],
        {"kind": "text", "index": 0, "original": "First", "value": "Updated"},
    )
    assert result["changed"] and result["undo"]["tool"] == "app_project_undo"


def test_shared_rule_receipt_distinguishes_open_page_from_other_routes(opened):
    projects, project = opened
    project = projects.update(project["id"], {
        "pages/other.html": '<article class="card">Other route</article>',
    }, project["revision"])
    projects.preview(project["id"])
    plan = edit(projects, project, 1, operation="plan")
    assert plan["affects"] == 2 and plan["confirmation_required"]
    assert plan["affects_scope"] == "page" and plan["shared_stylesheet"] is True


def test_new_class_avoids_retained_rule_and_existing_class_on_another_page(opened):
    projects, project = opened
    vsrc = "pages/index.html:3:1"
    reserved = "canvas-" + sha256(vsrc.encode()).hexdigest()[:12]
    project = projects.update(project["id"], {
        "assets/dormant.css": "@media (min-width: 0px) { ." + reserved + " { color: red; } }",
        "pages/other.html": '<article class="' + reserved + '-2">Other route</article>',
    }, project["revision"])
    projects.preview(project["id"])
    result = edit(projects, project, 3, "width", 90)
    assert result["target"]["selector"] == "#bare." + reserved + "-3"
    new = projects.get(project["id"])
    assert new["files"]["assets/dormant.css"] == project["files"]["assets/dormant.css"]
