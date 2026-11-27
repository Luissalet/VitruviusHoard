import json
from hashlib import sha256
from types import SimpleNamespace

import httpx
import pytest

from vitruvius_hoard.agent_tools import call_tool, tool_catalog
from vitruvius_hoard.app_projects import AppProjects
from vitruvius_hoard.app_runtime import _text
from vitruvius_hoard.app_source_map import render_template
from vitruvius_hoard.hoard_link.agentkit import AppError
from vitruvius_hoard.software.host import catalog


@pytest.fixture
def service(tmp_path):
    return SimpleNamespace(app_projects=AppProjects(tmp_path, host_port=9))


def create(service, files=None):
    args = {"name": "Taller", "template": "static-page", "lang": "es", "description_es": "Presentación del taller."}
    if files is not None:
        args["files"] = files
    return call_tool(service, "app_project_create", args)


def edit(service, project, **fields):
    return call_tool(service, "app_project_edit_template_data",
                     {"id": project["id"], "expected_revision": project["revision"], **fields})


def test_edits_only_project_data_and_has_one_step_undo(service, tmp_path):
    project = create(service, {
        "layout.html": '<html lang="es"><head><title>{{name}}</title>'
                       '<meta name="description" content="{{description}}"></head><body>{{content}}</body></html>',
        "pages/index.html": '<h1 title="{{name}}">{{name}}</h1><p>{{description}}</p>',
    })
    before = service.app_projects.get(project["id"])["files"]
    name = 'Clínica del papel & "archivo"'
    description = "<em>Encuadernación y reparación</em>"
    saved = edit(service, project, name=name, description=description)
    files = service.app_projects.get(project["id"])["files"]
    raw = files["project.json"].encode("utf-8")
    field_data = json.loads(raw)
    assert field_data == {**json.loads(before["project.json"]), "name": name, "description": description}
    assert files == {**before, "project.json": files["project.json"]}
    assert saved["changed"] and saved["revision"] != project["revision"]
    assert saved["changed_files"] == [{"path": "project.json", "bytes": len(raw), "sha256": sha256(raw).hexdigest()}]
    assert "files" not in saved and "history" not in saved

    entry = tmp_path / "pages" / "index.html"
    entry.parent.mkdir()
    entry.write_text(files["pages/index.html"], encoding="utf-8")
    layout = tmp_path / "layout.html"
    layout.write_text(files["layout.html"], encoding="utf-8")
    values = {key: _text(field_data[key]) for key in ("name", "description")}
    rendered = render_template(tmp_path, layout, {**values, "content": render_template(tmp_path, entry, values)})
    assert ">Clínica del papel &amp; &quot;archivo&quot;</title>" in rendered
    assert rendered.count("Clínica del papel &amp; &quot;archivo&quot;") == 3
    assert rendered.count("&lt;em&gt;Encuadernación y reparación&lt;/em&gt;") == 2

    call_tool(service, saved["undo"]["tool"], saved["undo"]["arguments"])
    restored = service.app_projects.get(project["id"])
    assert restored["revision"] == project["revision"] and restored["files"] == before


def test_same_values_leave_the_revision_and_empty_description_can_be_saved(service):
    project = create(service)
    unchanged = edit(service, project, name="Taller")
    assert unchanged["revision"] == project["revision"] and unchanged["updated_ts"] == project["updated_ts"]
    assert not unchanged["changed"] and unchanged["changed_files"] == [] and "undo" not in unchanged
    cleared = edit(service, project, description="")
    assert cleared["changed"] and cleared["revision"] != project["revision"]
    assert json.loads(service.app_projects.get(project["id"])["files"]["project.json"])["description"] == ""


def test_old_revision_and_empty_edit_are_refused(service):
    original = create(service)
    current = edit(service, original, name="Nuevo nombre")
    with pytest.raises(AppError) as stale:
        edit(service, original, description="Otra descripción")
    assert stale.value.status == 409 and stale.value.details["revision"] == current["revision"]
    for invalid in ({}, {"name": " \t "}):
        with pytest.raises(AppError) as rejected:
            edit(service, current, **invalid)
        assert rejected.value.status == 400
    assert service.app_projects.get(original["id"])["revision"] == current["revision"]


@pytest.mark.parametrize("source", [
    '<a href="{{name}}">Enlace</a>',
    '<p title={{name}}>Texto</p>',
    '<{{name}}>Texto</{{name}}>',
    '<script>const label = {{name}};</script>',
    '<style>.label { color: {{name}} }</style>',
    '<meta http-equiv="refresh" content="{{name}}">',
])
def test_template_data_rejects_unsafe_contexts_without_saving(service, source):
    project = create(service, {"pages/index.html": source})
    with pytest.raises(AppError) as error:
        edit(service, project, name="New value")
    assert error.value.code == "invalid_template_use" and error.value.details["path"] == "pages/index.html"
    assert service.app_projects.get(project["id"])["revision"] == project["revision"]


def test_cold_catalogue_has_the_same_template_editor_contract():
    name = "app_project_edit_template_data"
    native = next(row for row in tool_catalog() if row["name"] == name)
    frozen = next(row for row in catalog() if row["name"] == name)
    assert native == {key: value for key, value in frozen.items() if key != "module"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("endpoint", "body_identity", "header_identity", "actor", "expected_author"), [
    ("/api/agent/call", {"caller": "copy-editor"}, None, None, {"kind": "agent", "id": "copy-editor"}),
    ("/design/api/agent/call", {}, "copy-editor", None, {"kind": "agent", "id": "copy-editor"}),
    ("/compat/design/api/agent/call", {}, "copy-editor", None, {"kind": "agent", "id": "copy-editor"}),
    ("/api/agent/call", {}, None, None, {"kind": "agent"}),
    ("/api/agent/call", {"caller": "copy-editor"}, None, {"id": "cursor"}, {"kind": "agent", "id": "copy-editor"}),
    ("/api/ui/call", {}, None, None, {"kind": "person"}),
])
async def test_http_template_edit_records_the_project_author(client, tmp_path, monkeypatch, endpoint,
                                                       body_identity, header_identity, actor, expected_author):
    from vitruvius_hoard.software.host import create_app

    token_file = tmp_path / "design" / "mcp-token"
    token_file.parent.mkdir()
    token_file.write_text(client.svc.token, encoding="utf-8")
    monkeypatch.setenv("VITRUVIUS_PROFILE_DIR", str(tmp_path))
    owner = create_app()
    design = owner.state.runtime.modules["design"]
    design.app, design.state = client.app, "on"

    project = create(client.svc)
    args = {"id": project["id"], "expected_revision": project["revision"], "description": "Updated project text"}
    if actor is not None:
        args["actor"] = actor
    headers = {"Authorization": f"Bearer {client.svc.token}"}
    if header_identity:
        headers["X-Agent-Id"] = header_identity

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=owner), base_url="http://127.0.0.1:9") as api:
        response = await api.post(endpoint, headers=headers, json={
            "name": "app_project_edit_template_data", "arguments": args, **body_identity,
        })
        assert response.status_code == 200, response.text
        result = response.json()
        stored = (await api.get(f"/design/api/app-projects/{project['id']}")).json()

    assert result["changed"] and stored["revision"] == result["revision"]
    event = stored["history"][-1]
    assert event["files"] == ["project.json"]
    assert {key: value for key, value in event["author"].items() if key != "name"} == expected_author
