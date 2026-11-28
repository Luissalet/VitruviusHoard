import json
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

import pytest

from vitruvius_hoard.app_projects import AppProjects, starter_files


def test_preview_repeated_source_edit_and_undo(tmp_path):
    projects = AppProjects(tmp_path)
    files = {
        "layout.html": "<!doctype html>\r\n<html><body><main>{{content}}</main><aside>{{content}}</aside></body></html>",
        "pages/index.html": "\ufeff<h2>Original</h2>\r\n<div>{{table}}</div>",
    }
    original = projects.create("Preview board", files=files)
    project_id = original["id"]
    vsrc = "pages/index.html:1:2"
    generated = "pages/index.html:2:6"
    try:
        preview = projects.preview(project_id)
        with urlopen(preview["url"] + "/", timeout=5) as response:
            page = response.read().decode()
        assert page.count(f'<h2 data-vsrc="{vsrc}">Original</h2>') == 2
        assert 'data-vsrc="layout.html:2:1"' in page
        assert 'data-vgen="table"' in page
        assert projects.source_count(project_id, vsrc)["same_vsrc_count"] == 2
        assert projects.source_count(project_id, generated)["same_vsrc_count"] == 4
        source_dir = projects.root / project_id / "revisions" / original["revision"] / "source"
        for name, text in files.items():
            assert (source_dir / name).read_bytes() == text.encode()
        with pytest.raises(ValueError, match=r"Viene de \{\{table\}\}"):
            projects.edit_source(project_id, generated, "table", original["revision"],
                                 {"kind": "text", "value": "X"}, lang="es")
        with pytest.raises(ValueError, match="expected HTML tag"):
            projects.edit_source(project_id, vsrc, "p", original["revision"], {"kind": "text", "value": "X"})
        unchanged = projects.edit_source(project_id, vsrc, "h2", original["revision"],
                                         {"kind": "text", "value": "Original"})
        assert unchanged["revision"] == original["revision"] and unchanged["updated_ts"] == original["updated_ts"]
        assert "undo" not in unchanged
        updated = projects.edit_source(project_id, vsrc, "h2", original["revision"],
                                       {"kind": "text", "value": "Revisado á <mapa>"})
        assert updated["revision"] != original["revision"]
        assert updated["files"]["pages/index.html"] == files["pages/index.html"].replace("Original", "Revisado á &lt;mapa&gt;")
        assert projects.get(project_id, original["revision"])["files"] == original["files"]
        with pytest.raises(ValueError, match="revision changed"):
            projects.edit_source(project_id, vsrc, "h2", original["revision"], {"kind": "text", "value": "Stale"})
        assert projects.source_count(project_id, vsrc)["revision"] == updated["revision"]
        new_preview = updated["preview"]
        with urlopen(new_preview["url"] + "/", timeout=5) as response:
            saved = response.read().decode()
        assert saved.count(f'<h2 data-vsrc="{vsrc}">Revisado á &lt;mapa&gt;</h2>') == 2
        restored = projects.undo(**updated["undo"]["arguments"])
        assert restored["files"] == original["files"]
        assert restored["revision"] == original["revision"]
        restored_preview = restored["preview"]
        assert restored_preview["session"] == new_preview["session"] == preview["session"]
        assert restored_preview["url"] == new_preview["url"] == preview["url"]
        assert projects.source_count(project_id, vsrc)["revision"] == original["revision"]
    finally:
        projects.close()


def test_same_revision_concurrent_edit_has_one_winner(tmp_path):
    projects = AppProjects(tmp_path)
    start = projects.create("Race", files={"pages/index.html": "<h2>Initial</h2>"})

    def write(title):
        try:
            return projects.edit_source(start["id"], "pages/index.html:1:1", "h2", start["revision"],
                                        {"kind": "text", "value": title})
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ("First", "Second")))
    saved = [result for result in results if isinstance(result, dict)]
    assert len(saved) == 1 and "undo" in saved[0]
    assert any(isinstance(result, str) and "The revision changed." in result for result in results)
    assert projects.get(start["id"])["revision"] == saved[0]["revision"]


@pytest.mark.parametrize("template", ["work-board", "booking"])
def test_export_is_exact_source_and_standalone_serves_without_annotations(tmp_path, template):
    projects = AppProjects(tmp_path)
    items = [{"id": "chart", "title": "Estuary chart", "category": "Maps"}]
    project = projects.create("Standalone board", template, items=items if template == "booking" else None)
    project_id = project["id"]
    extracted = tmp_path / "standalone"
    try:
        preview = projects.preview(project_id)
        route = "/" if template == "work-board" else "/records"
        with urlopen(preview["url"] + route, timeout=5) as response:
            assert b"data-vsrc=" in response.read()
        exported = projects.export(project_id)
        with zipfile.ZipFile(exported["path"]) as archive:
            assert set(archive.namelist()) == set(project["files"]) | {"vitruvius-export.json"}
            for name, text in project["files"].items():
                source = archive.read(name)
                assert source == text.encode("utf-8")
                assert b"data-vsrc" not in source and b"data-vgen" not in source
            archive.extractall(extracted)
    finally:
        projects.close()
    ready = tmp_path / "standalone.json"
    with (tmp_path / "standalone.log").open("wb") as log:
        process = subprocess.Popen([sys.executable, "-I", "server.py", "--port", "0", "--ready-file", str(ready)],
                                   cwd=extracted, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            assert ready.exists(), (tmp_path / "standalone.log").read_text(encoding="utf-8")
            origin = json.loads(ready.read_text(encoding="utf-8"))["url"]
            for route in ("/", "/records"):
                with urlopen(origin + route, timeout=5) as response:
                    html = response.read()
                    assert b"data-vsrc" not in html and b"data-vgen" not in html
        finally:
            process.terminate()
            process.wait(timeout=5)


def test_custom_runtime_keeps_its_preview_behavior(tmp_path):
    files = starter_files("Custom board")
    original_runtime = files["server.py"].replace(
        '    preview_renderer = os.environ.get("VITRUVIUS_PREVIEW_SOURCE_MAP")',
        '    preview_renderer = None',
    )
    files["server.py"] = original_runtime
    projects = AppProjects(tmp_path)
    project = projects.create_from_files("Custom board", "work-board", files)
    try:
        preview = projects.preview(project["id"])
        with urlopen(preview["url"], timeout=5) as response:
            assert b"data-vsrc" not in response.read()
        with zipfile.ZipFile(projects.export(project["id"])["path"]) as archive:
            assert archive.read("server.py") == original_runtime.encode()
    finally:
        projects.close()


def test_native_routes_expose_source_edit_and_count(client):
    created = client.post("/api/app-projects", json={"name": "Source board"}).json()
    base = f"/api/app-projects/{created['id']}"
    preview = client.post(base + "/preview", json={}).json()
    try:
        count = client.get(base + "/source-count", params={"vsrc": "pages/index.html:1:1"}).json()
        assert count["same_vsrc_count"] == 1 and count["revision"] == preview["revision"]
        bad = client.get(base + "/source-count", params={"vsrc": "pages/index.html:1:1",
                                                        "path": "//other-origin/records"})
        assert bad.status_code == 400
        args = {"vsrc": "pages/index.html:1:1", "tag": "h1", "expected_revision": created["revision"],
                "change": {"kind": "class", "operation": "add", "value": "highlight"}}
        result = client.post(base + "/source-edit", json=args)
        assert result.status_code == 200
        assert result.json()["files"]["pages/index.html"].startswith('<h1 class="highlight">')
        assert result.json()["undo"]["tool"] == "app_project_undo"
    finally:
        client.post(base + "/preview", json={"operation": "stop"})
