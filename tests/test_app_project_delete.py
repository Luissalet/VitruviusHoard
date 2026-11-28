"""Permanent removal is guarded by both versions and scoped to one archive."""
from pathlib import Path

import pytest

from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.hoard_link.agentkit import AppError


def _conditions(project):
    return {"expected_revision": project["revision"], "expected_updated_ts": project["updated_ts"],
            "confirm": True}


def _archive(projects, project, operation="archive"):
    return projects.archive(project["id"], operation=operation, **_conditions(project))


def _files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_delete_http_requires_confirmation_and_an_archived_project(client):
    projects = client.svc.app_projects
    active = projects.create("Still active")
    id = active["id"]
    root = projects.root / id
    before = _files(root)
    route = f"/api/app-projects/{id}/delete"
    body = {**_conditions(active), "lang": "es"}

    active_result = client.post(route, json=body)
    assert active_result.status_code == 409 and active_result.json()["code"] == "project_active"
    assert "archiva" in active_result.json()["error"].lower()
    absent = client.post("/api/app-projects/0000000000000000/delete", json=body)
    assert absent.status_code == 404
    assert _files(root) == before

    archived = _archive(projects, active)
    body = {**_conditions(archived), "lang": "es"}
    before = _files(root)
    unconfirmed = client.post(route, json={**body, "confirm": False})
    assert unconfirmed.status_code == 400 and unconfirmed.json()["code"] == "confirm_required"
    assert client.post(route, json={**body, "confirm": "true"}).status_code == 422
    for required in ("expected_revision", "expected_updated_ts"):
        assert client.post(route, json={key: value for key, value in body.items() if key != required}).status_code == 422
    assert client.post(route, json={**body, "expected_updated_ts": None}).status_code == 422
    assert _files(root) == before


def test_delete_rejects_stale_revision_and_archive_timestamp(client):
    projects = client.svc.app_projects
    original = projects.create("Changed since confirmation")
    id = original["id"]
    changed = projects.update(id, {"notes.txt": "New revision"}, original["revision"])
    archive = _archive(projects, changed)
    restored = _archive(projects, archive, "restore")
    current = _archive(projects, restored)
    assert archive["revision"] == current["revision"]
    assert archive["updated_ts"] < current["updated_ts"]
    root = projects.root / id
    before = _files(root)

    for body in (
        {**_conditions(current), "expected_revision": original["revision"]},
        _conditions(archive),
    ):
        response = client.post(f"/api/app-projects/{id}/delete", json=body)
        assert response.status_code == 409 and response.json()["code"] == "conflict"
        assert _files(root) == before
    assert [row["id"] for row in projects.list(archived=True)] == [id]


def test_confirmed_tool_deletion_receipt_and_other_projects(client):
    projects = client.svc.app_projects
    target = projects.create("Remove this archive")
    neighbor = projects.create("Keep this active project")
    other_archive = projects.create("Keep this archive")
    _archive(projects, other_archive)
    id = target["id"]
    directory = projects.root / id
    # Older versions used a marker. An existing preview may still be attached to one.
    preview = projects.preview(id)
    process = projects.processes[id]["process"]
    (directory / "archived").touch()
    files = _files(directory)
    intact = {row["id"]: _files(projects.root / row["id"]) for row in (neighbor, other_archive)}
    assert files and any(path.startswith("runs/") for path in files)
    assert any(path.startswith("data/") for path in files)

    receipt = call_tool(client.svc, "app_project_delete", {"id": id, **_conditions(target)})
    assert receipt == {"id": id, "name": target["name"], "path": str(directory),
                       "files": len(files), "bytes": sum(map(len, files.values())), "deleted": True}
    assert not Path(receipt["path"]).exists()
    assert process.poll() is not None
    assert preview["state"] == "running" and projects.status(id)["state"] == "stopped"
    assert [row["id"] for row in projects.list()] == [neighbor["id"]]
    assert [row["id"] for row in projects.list(archived=True)] == [other_archive["id"]]
    assert {other_id: _files(projects.root / other_id) for other_id in intact} == intact
    with pytest.raises(AppError) as missing:
        call_tool(client.svc, "app_project_delete", {"id": id, **_conditions(target)})
    assert missing.value.code == "not_found"
    assert client.post(f"/api/app-projects/{id}/archive", json={**_conditions(target), "operation": "restore"}).status_code == 404


def test_delete_never_follows_reparse_entries(client, monkeypatch):
    import stat
    from types import SimpleNamespace

    projects = client.svc.app_projects
    project = projects.create("Retain unexpected link")
    archived = _archive(projects, project)
    root = projects.root / project["id"]
    link = root / "unexpected"
    link.write_text("A reparse marker in this test")
    before = _files(root)
    original_lstat = Path.lstat

    def lstat(path):
        if path == link:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", lstat)
    route = f"/api/app-projects/{project['id']}/delete"
    response = client.post(route, json=_conditions(archived))
    assert response.status_code == 400 and response.json()["code"] == "unsafe_project_data"
    assert _files(root) == before


def test_storage_error_keeps_archive_available_for_a_retry(client, monkeypatch):
    projects = client.svc.app_projects
    project = projects.create("Retry this archive")
    archived = _archive(projects, project)
    root = projects.root / project["id"]
    original_rmdir = Path.rmdir

    def rmdir(path):
        if path == root:
            raise PermissionError("Open directory in this test")
        return original_rmdir(path)

    route = f"/api/app-projects/{project['id']}/delete"
    with monkeypatch.context() as patch:
        patch.setattr(Path, "rmdir", rmdir)
        response = client.post(route, json=_conditions(archived))
        assert response.status_code == 500 and response.json()["code"] == "delete_failed"
    [row] = projects.list(archived=True)
    assert row["id"] == project["id"] and row["updated_ts"] == archived["updated_ts"]
    assert client.post(route, json=_conditions(row)).status_code == 200
    assert not root.exists()
