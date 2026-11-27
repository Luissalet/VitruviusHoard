"""Literal project patches through the agent write path."""
from hashlib import sha256
from urllib.request import urlopen

import pytest


CSS = ".card { padding: 12px; }\n"
FILES = {
    "assets/style.css": CSS,
    "assets/logo.png": "iVBORw0KGgo=",
    "notes.md": "aaa\n",
    "pages/index.html": "<h1>Initial</h1>\n",
}


@pytest.fixture
def project(client):
    projects = client.svc.app_projects
    created = projects.create("Patch example", files=FILES)
    return projects.get(created["id"])


def call(client, name, arguments):
    return client.post("/api/agent/call", headers={
        "Authorization": f"Bearer {client.svc.token}", "X-Agent-Id": "patch-author",
    }, json={"name": name, "arguments": arguments})


def patch(client, project, replacements, **options):
    return call(client, "app_project_patch", {
        "id": project["id"], "expected_revision": project["revision"],
        "replacements": replacements, **options,
    })


def replacement(file, old, new):
    return {"file": file, "old": old, "new": new}


def test_one_literal_patch_updates_live_preview_and_returns_undo(client, project):
    projects = client.svc.app_projects
    opened = projects.preview(project["id"])
    new_css = CSS.replace("12px", "16px") + "/* edición */\n"
    response = patch(client, project, [replacement("assets/style.css", CSS, new_css)])
    assert response.status_code == 200, response.text
    receipt = response.json()
    content = new_css.encode("utf-8")
    assert receipt["changed"] and receipt["revision"] != project["revision"]
    assert receipt["bytes"] == len(content)
    assert receipt["changed_files"] == [{
        "path": "assets/style.css", "bytes": len(content), "sha256": sha256(content).hexdigest(),
    }]
    assert "files" not in receipt and "history" not in receipt
    current = projects.get(project["id"])
    assert current["preview"] == receipt["preview"]
    assert current["preview"]["revision"] == receipt["revision"]
    assert all(current["preview"][key] == opened[key] for key in ("url", "session"))
    with urlopen(opened["url"] + "/assets/style.css", timeout=5) as asset:
        assert asset.read() == content
        assert asset.headers["X-Vitruvius-Revision"] == receipt["revision"]
    assert current["history"][-1]["author"] == {"kind": "agent", "id": "patch-author", "name": "patch-author"}
    undo = receipt["undo"]
    restored = call(client, undo["tool"], undo["arguments"])
    assert restored.status_code == 200, restored.text
    assert restored.json()["files"] == project["files"]
    assert restored.json()["preview"]["revision"] == project["revision"]


def test_multiple_replacements_are_ordered_and_saved_together(client, project):
    response = patch(client, project, [
        replacement("assets/style.css", "12px", "16px"),
        replacement("pages/index.html", "Initial", "Revised"),
        replacement("assets/style.css", "16px", "20px"),
    ])
    assert response.status_code == 200, response.text
    receipt = response.json()
    current = client.svc.app_projects.get(project["id"])
    assert current["history"][:-1] == project["history"]
    assert current["files"]["assets/style.css"] == CSS.replace("12px", "20px")
    assert current["files"]["pages/index.html"] == "<h1>Revised</h1>\n"
    assert current["preview"]["state"] == "stopped"
    assert [file["path"] for file in receipt["changed_files"]] == ["assets/style.css", "pages/index.html"]
    assert receipt["bytes"] == sum(file["bytes"] for file in receipt["changed_files"])


@pytest.mark.parametrize(("old", "matches"), [("missing", 0), ("aa", 2)])
def test_match_error_counts_occurrences_and_rolls_back_prior_entries(client, project, old, matches):
    response = patch(client, project, [
        replacement("assets/style.css", "12px", "16px"),
        replacement("notes.md", old, "b"),
    ], lang="es")
    assert response.status_code == 400, response.text
    result = response.json()
    assert result["file"] == "notes.md" and result["replacement"] == 2
    assert result["occurrences"] == matches
    assert str(matches) + " apariciones" in result["error"]
    assert client.svc.app_projects.get(project["id"]) == project


def test_stale_patch_conflicts_even_with_disjoint_files(client, project):
    projects = client.svc.app_projects
    latest = projects.update(project["id"], {"notes.md": "Updated\n"}, project["revision"])
    response = patch(client, project, [replacement("assets/style.css", "12px", "16px")])
    assert response.status_code == 409
    assert response.json()["revision"] == latest["revision"]
    assert projects.get(project["id"])["files"] == latest["files"]


@pytest.mark.parametrize(("path", "new", "status", "code"), [
    ("assets/logo.png", "ignored", 400, "unsupported_file"),
    ("../notes.md", "ignored", 400, "invalid_path"),
    ("C:/notes.md", "ignored", 400, "invalid_path"),
    ("/notes.md", "ignored", 400, "invalid_path"),
    ("assets/new.css", "ignored", 404, "not_found"),
    ("assets/style.css", "\0binary", 400, "invalid_text"),
])
def test_rejects_binary_missing_files_and_paths_outside_project(client, project, path, new, status, code):
    response = patch(client, project, [replacement(path, "12px", new)])
    assert response.status_code == status, response.text
    assert response.json()["code"] == code
    assert client.svc.app_projects.get(project["id"]) == project


def test_no_effective_change_has_zero_bytes_and_no_undo(client, project):
    response = patch(client, project, [
        replacement("assets/style.css", "12px", "16px"),
        replacement("assets/style.css", "16px", "12px"),
    ])
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["revision"] == project["revision"]
    assert not receipt["changed"] and receipt["bytes"] == 0 and receipt["changed_files"] == []
    assert "undo" not in receipt
    assert client.svc.app_projects.get(project["id"]) == project
