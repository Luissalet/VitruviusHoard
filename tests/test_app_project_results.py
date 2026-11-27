from hashlib import sha256
import json

from vitruvius_hoard.agent_tools import AppCreateArgs, call_tool, run_app_project_create


def as_json(result):
    return json.dumps(result, ensure_ascii=False).encode("utf-8")


def test_source_tools_return_small_receipts_and_preserve_full_source(services, monkeypatch):
    def call(tool, **arguments):
        return call_tool(services, tool, arguments)

    projects = services.app_projects
    full = run_app_project_create(services, AppCreateArgs(name="Work Board"))
    id = full["id"]
    with monkeypatch.context() as patched:
        patched.setattr(projects, "create", lambda **_kwargs: full)
        creation = call("app_project_create", name="Work Board")
        assert as_json(call("app_project_create", name="Work Board", include_files=True)) == as_json(full)

    read = call("app_project_get", id=id)
    assert creation["undo"] == full["undo"]
    assert read["file_manifest"] == creation["file_manifest"]
    assert read["selected_revision"] == creation["revision"]
    assert "files" not in creation and "files" not in read
    assert {entry["path"] for entry in read["file_manifest"]} == set(full["files"])
    assert as_json(call("app_project_get", id=id, include_files=True)) == as_json(projects.get(id))

    path = "pages/index.html"
    column = full["files"][path].index("<h2>Current records") + 1
    edit_args = {"id": id, "vsrc": f"{path}:1:{column}", "tag": "h2",
                 "expected_revision": creation["revision"],
                 "change": {"kind": "text", "value": "Registros de edición"}}
    edit = call("app_project_edit_source", **edit_args)
    assert len(as_json(edit)) < 4000 and edit["changed"]
    assert edit["revision"] != creation["revision"]
    assert edit["selected_revision"] == edit["revision"]
    assert edit["preview"] == full["preview"]
    current = projects.get(id)
    contents = current["files"][path].encode("utf-8")
    assert "Registros de edición" in current["files"][path]
    assert edit["changed_files"] == [{"path": path, "bytes": len(contents), "sha256": sha256(contents).hexdigest()}]
    assert "files" not in edit
    assert as_json(call("app_project_get", id=id, revision=creation["revision"], include_files=True)) == as_json(
        projects.get(id, creation["revision"])
    )

    repeated = {**edit_args, "expected_revision": edit["revision"]}
    noop = call("app_project_edit_source", **repeated)
    assert not noop["changed"] and noop["changed_files"] == [] and "undo" not in noop
    assert as_json(call("app_project_edit_source", **repeated, include_files=True)) == as_json(current)
    restored = call(edit["undo"]["tool"], **edit["undo"]["arguments"])
    assert restored["files"] == full["files"]

    original_edit = projects.edit_source
    saved = []

    def record_edit(*args, **kwargs):
        receipt = original_edit(*args, **kwargs)
        saved.append(as_json(receipt))
        return receipt

    monkeypatch.setattr(projects, "edit_source", record_edit)
    full_edit = call("app_project_edit_source", **edit_args, include_files=True)
    assert full_edit["files"] == current["files"] and full_edit["undo"]["tool"] == "app_project_undo"
    assert saved == [as_json(full_edit)]
