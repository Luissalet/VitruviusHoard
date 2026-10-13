import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zipfile

import pytest

from vitruvius_hoard.app_projects import AppProjects, starter_files
from vitruvius_hoard.app_runtime import Records, make_server


def request(url, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.status, response.read()


def test_real_preview_source_revisions_data_and_standalone_export(tmp_path):
    projects = AppProjects(tmp_path)
    try:
        original = projects.create("Inventory á 👩‍🚀 </script>", "inventory")
        id = original["id"]
        preview = projects.preview(id)
        assert preview["state"] == "running"
        url = preview["url"]
        _, raw = request(url + "/actions/create", "POST", {"name": "Widget <script>", "quantity": 2.5, "location": "Shelf A"})
        record = json.loads(raw)
        _, page = request(url + "/records/" + record["id"])
        assert b"Widget &lt;script&gt;" in page and b"Save changes" in page
        with pytest.raises(urllib.error.HTTPError) as error:
            request(url + "/actions/create", "POST", {"name": "Bad", "quantity": "2", "location": "Shelf"})
        assert error.value.code == 400
        request(url + "/api/records/" + record["id"], "PATCH", {"quantity": 3})
        changed = projects.update(id, {"pages/index.html": "<h1>Revised page</h1>{{table}}"}, original["revision"])
        assert changed["revision"] != original["revision"]
        assert projects.get(id, original["revision"])["files"] == original["files"]
        assert projects.status(id)["revision"] == original["revision"]
        preview = projects.preview(id)
        _, raw = request(preview["url"] + "/api/records")
        assert json.loads(raw)["records"][0]["quantity"] == 3
        exported = projects.export(id, include_data=True)
        extracted = tmp_path / "standalone"
        with zipfile.ZipFile(exported["path"]) as archive:
            archive.extractall(extracted)
            for path, text in changed["files"].items():
                assert archive.read(path) == text.encode("utf-8")
        # Execute the extracted source itself with isolated import paths.
        ready = extracted / "ready.json"
        log = (extracted / "output.log").open("wb")
        process = subprocess.Popen([sys.executable, "-I", "server.py", "--port", "0", "--ready-file", str(ready)], cwd=extracted, stdout=log, stderr=log)
        try:
            import time
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            assert ready.exists(), (extracted / "output.log").read_text(encoding="utf-8")
            independent = json.loads(ready.read_text())["url"]
            _, page = request(independent + "/")
            assert b"Revised page" in page and b"Widget &lt;script&gt;" in page
            _, raw = request(independent + "/api/records")
            assert json.loads(raw)["records"][0]["quantity"] == 3
        finally:
            process.terminate(); process.wait(timeout=5); log.close()
        projects.stop(id)
        assert projects.status(id)["state"] == "stopped"
    finally:
        projects.close()


def test_update_conflict_and_path_preserve_existing_source(tmp_path):
    projects = AppProjects(tmp_path)
    original = projects.create("Board")
    id = original["id"]
    projects.update(id, {"pages/index.html": "changed"}, original["revision"])
    with pytest.raises(ValueError, match="changed"):
        projects.update(id, {"pages/index.html": "stale"}, original["revision"])
    current = projects.get(id)
    with pytest.raises(ValueError, match="relative"):
        projects.update(id, {"../outside.txt": "bad"}, current["revision"])
    assert not (tmp_path / "outside.txt").exists()
    assert projects.get(id)["files"] == current["files"]


def test_actual_record_updates_keep_independent_fields(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store = Records(tmp_path / "records.db")
    original = store.create({"a": "one", "b": "two"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda update: store.update(original["id"], update), [{"a": "new a"}, {"b": "new b"}]))
    assert store.get(original["id"]) == {"id": original["id"], "a": "new a", "b": "new b"}


@pytest.mark.parametrize("template", ["work-board", "reference-library", "inventory"])
def test_every_starter_compiles_without_external_packages(tmp_path, template):
    files = starter_files("Literal </script> á", template)
    path = tmp_path / "server.py"
    path.write_bytes(files["server.py"].encode())
    subprocess.run([sys.executable, "-m", "py_compile", str(path)], check=True)
    assert "/actions/create" in files["assets/api.js"]
    assert "RecordInput" in files["contracts.d.ts"]


def test_independent_file_updates_merge_and_originals_remain(tmp_path):
    projects = AppProjects(tmp_path)
    original = projects.create("Board")
    first = projects.update(original["id"], {"pages/index.html": "one"}, original["revision"])
    second = projects.update(original["id"], {"assets/style.css": "two"}, original["revision"])
    assert second["files"]["pages/index.html"] == "one"
    assert second["files"]["assets/style.css"] == "two"
    assert projects.get(original["id"], original["revision"])["files"] == original["files"]


def test_native_api_and_tools(client):
    response = client.post("/api/app-projects", json={"name": "Native board"})
    assert response.status_code == 201
    project = response.json(); id = project["id"]
    created = client.post(f"/api/app-projects/{id}/call", json={"operation": "create", "data": {"title": "Native", "status": "To do", "notes": ""}})
    assert created.status_code == 200 and created.json()["id"]
    assert client.get(f"/api/app-projects/{id}").json()["preview"]["state"] == "running"
    result = client.post(f"/api/app-projects/{id}/export", json={"include_data": True}).json()
    assert client.get(result["download_url"]).status_code == 200
    assert result["includes_data"]
    assert client.post(f"/api/app-projects/{id}/preview", json={"operation": "stop"}).json()["state"] == "stopped"


def test_app_render_retains_source_context(services):
    project = services.app_projects.create("Context board")
    try:
        render = services.app_project_render(project["id"], widths=[390])
        context = services.get_render(render["id"])["metrics"]["app_project"]
        assert context == {"id": project["id"], "revision": project["revision"], "source_sha256": project["source_sha256"]}
    finally:
        services.app_projects.stop(project["id"])
