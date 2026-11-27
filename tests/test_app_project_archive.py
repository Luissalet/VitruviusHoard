"""Archive follows source history without deleting projects, records or exports."""
import json
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.app_projects import AppProjects
from vitruvius_hoard.hoard_link.agentkit import AppError


def test_edit_then_undo_then_archive_keeps_source_records_and_export(services):
    def call(tool, **args):
        return call_tool(services, tool, args)

    projects = services.app_projects
    original = call("app_project_create", name="Archive round trip", include_files=True)
    id = original["id"]
    source = original["files"]["pages/index.html"]
    column = source.index("<h2>Current records") + 1
    preview = call("app_project_preview", id=id)
    try:
        request = Request(preview["url"] + "/actions/create",
                          data=b'{"title":"Keep this record","status":"To do","notes":"Archive round trip"}',
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=5) as response:
            record = json.load(response)
        edit = call("app_project_edit_source", id=id, vsrc=f"pages/index.html:1:{column}", tag="h2",
                    expected_revision=original["revision"], change={"kind": "text", "value": "Edited records"})
        restored_source = call("app_project_undo", **edit["undo"]["arguments"])
        assert restored_source["revision"] == original["revision"]
        assert restored_source["revisions"] == [original["revision"], edit["revision"]]
        with pytest.raises(ValueError, match="Application revision changed after the original operation"):
            call("app_project_undo", **original["undo"]["arguments"])

        export = Path(call("app_project_export", id=id, include_data=True)["path"])
        exported_bytes = export.read_bytes()
        archived = call("app_project_archive", id=id, expected_revision=restored_source["revision"], confirm=True)
        assert archived["archived"] and archived["changed"] and archived["revision"] == restored_source["revision"]
        assert projects.status(id)["state"] == "stopped"
        assert call("app_project_list")["projects"] == []
        [listing] = call("app_project_list", archived=True)["projects"]
        assert listing["id"] == id and listing["revisions"] == restored_source["revisions"]
        assert listing["updated_ts"] == archived["updated_ts"]
        for tool in ("app_project_get", "app_project_preview", "app_project_export"):
            with pytest.raises(AppError, match="Application project not found") as error:
                call(tool, id=id)
            assert error.value.code == "not_found"
        assert export.read_bytes() == exported_bytes

        reversal = archived["undo"]
        assert reversal["tool"] == "app_project_archive"
        recovered = call(reversal["tool"], **reversal["arguments"])
        assert recovered["changed"] and not recovered["archived"]
        assert call("app_project_list", archived=True)["projects"] == []
        assert call("app_project_get", id=id, include_files=True)["files"] == original["files"]
        historical = call("app_project_get", id=id, revision=edit["revision"], include_files=True)
        assert "Edited records" in historical["files"]["pages/index.html"]
        assert projects.status(id)["state"] == "stopped"
        preview = call("app_project_preview", id=id)
        with urlopen(preview["url"] + "/api/records/" + record["id"], timeout=5) as response:
            assert json.load(response) == record
        assert export.read_bytes() == exported_bytes
    finally:
        projects.stop(id)


def test_archive_api_checks_confirmation_revision_and_lifecycle(client):
    created = client.post("/api/app-projects", json={"name": "Archive API"}).json()
    id = created["id"]
    revision = created["revision"]
    path = f"/api/app-projects/{id}/archive"
    body = {"expected_revision": revision, "lang": "es"}

    unconfirmed = client.post(path, json=body)
    assert unconfirmed.status_code == 400 and unconfirmed.json()["code"] == "confirm_required"
    string_confirm = client.post(path, json={**body, "confirm": "true"})
    assert string_confirm.status_code >= 400
    stale = client.post(path, json={**body, "expected_revision": "old", "confirm": True})
    assert stale.status_code == 409 and stale.json()["code"] == "conflict"
    assert client.get("/api/app-projects").json()["projects"][0]["id"] == id

    archived = client.post(path, json={**body, "confirm": True}).json()
    assert archived["changed"] and archived["archived"]
    same = client.post(path, json={**body, "confirm": True}).json()
    assert not same["changed"] and "undo" not in same and same["updated_ts"] == archived["updated_ts"]
    assert client.get(f"/api/app-projects/{id}").status_code == 404
    assert client.get("/api/app-projects?archived=true").json()["projects"][0]["id"] == id

    restored = client.post(path, json=archived["undo"]["arguments"]).json()
    assert restored["changed"] and not restored["archived"] and restored["revision"] == revision
    assert client.get(f"/api/app-projects/{id}").status_code == 200
    archived_again = client.post(path, json=restored["undo"]["arguments"]).json()
    assert archived_again["revision"] == revision and archived_again["archived"]
    denied = client.post(path, json=archived["undo"]["arguments"])
    assert denied.status_code == 409 and denied.json()["code"] == "conflict"
    assert client.get("/api/app-projects?archived=true").json()["projects"][0]["updated_ts"] == archived_again["updated_ts"]


def test_legacy_archived_marker_can_be_restored_and_state_survives_reload(tmp_path):
    projects = AppProjects(tmp_path)
    original = projects.create("Legacy archive")
    id = original["id"]
    root = projects.root / id
    (root / "archived").touch()

    with pytest.raises(LookupError):
        projects.get(id)
    assert projects.list() == []
    [legacy] = projects.list(archived=True)
    assert legacy["id"] == id and legacy["archived"]

    restored = projects.archive(id, original["revision"], confirm=True, operation="restore")
    reopened = AppProjects(tmp_path)
    assert reopened.get(id)["files"] == original["files"]
    assert reopened.list(archived=True) == []
    assert reopened.archive(**restored["undo"]["arguments"])["archived"]
    [archived] = AppProjects(tmp_path).list(archived=True)
    assert archived["id"] == id and archived["revisions"] == original["revisions"]


def test_undoing_untouched_creation_remains_an_archive(services):
    project = call_tool(services, "app_project_create", {"name": "Untouched creation"})
    result = call_tool(services, "app_project_undo", project["undo"]["arguments"])
    assert result == {"id": project["id"], "archived": True, "revision": project["revision"]}
    [row] = services.app_projects.list(archived=True)
    assert row["id"] == project["id"]
    assert services.app_projects.archive(row["id"], row["revision"], confirm=True, operation="restore")["changed"]


def test_archive_refuses_an_updated_source_even_if_confirmation_was_open(services):
    old = services.app_projects.create("Source changed before confirmation")
    new = services.app_projects.update(old["id"], {"notes.txt": "Written after opening confirmation"}, old["revision"])
    with pytest.raises(AppError) as error:
        services.app_projects.archive(old["id"], old["revision"], confirm=True, expected_updated_ts=old["updated_ts"])
    assert error.value.code == "conflict"
    assert services.app_projects.get(old["id"])["revision"] == new["revision"]
    assert services.app_projects.list(archived=True) == []
