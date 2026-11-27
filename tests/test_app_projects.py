import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from types import SimpleNamespace

import pytest

from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.app_preview import SCRIPT_ROOT
from vitruvius_hoard.hoard_link.app_bridge import BRIDGE_JS
from vitruvius_hoard.app_projects import AppProjects, starter_files
from vitruvius_hoard.app_runtime import Records, make_server


def request(url, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.status, response.read()


@pytest.mark.parametrize(("template", "starter"), [("inventory", "inventory"), ("custom", "work-board")])
def test_agent_create_completes_partial_source_from_starter(tmp_path, template, starter):
    projects = AppProjects(tmp_path)
    files = {
        "pages/index.html": "<h1>Field notes</h1>",
        "assets/style.css": "h1 { color: #285744; }",
    }
    arguments = {"name": "Research log", "template": template, "files": files, "include_files": True}
    project = call_tool(SimpleNamespace(app_projects=projects), "app_project_create", arguments)

    expected = {**starter_files("Research log", starter), **files}
    assert project["files"] == expected
    assert projects.get(project["id"])["files"] == expected
    assert project["undo"]["arguments"]["expected_revision"] == project["revision"]


def test_agent_create_complete_custom_source_only_adds_runtime(tmp_path):
    projects = AppProjects(tmp_path)
    files = {
        "project.json": json.dumps({
            "format": "vitruvius-app/v2", "name": "Notes",
            "collections": {"notes": {"fields": [{"name": "title", "type": "text"}]}}, "actions": {},
        }),
        "layout.html": "<html lang='en'><body>{{content}}</body></html>",
        "pages/index.html": "<h1>Field notes</h1>",
    }
    arguments = {"name": "Notes", "template": "custom", "files": files, "include_files": True}
    services = SimpleNamespace(app_projects=projects)
    builtin = call_tool(services, "app_project_create", arguments)

    assert builtin["files"] == {**files, "server.py": starter_files("Notes")["server.py"]}

    custom_files = {**files, "server.py": "# Supplied standalone runtime\n"}
    explicit = call_tool(services, "app_project_create", {**arguments, "files": custom_files})

    assert explicit["files"] == custom_files


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
        assert page.count((SCRIPT_ROOT + "app-bridge.js").encode()) == 1
        _, script = request(url + SCRIPT_ROOT + "app-bridge.js")
        assert script == BRIDGE_JS.encode("utf-8")
        _, css = request(url + "/assets/style.css")
        assert css == original["files"]["assets/style.css"].encode("utf-8")
        assert SCRIPT_ROOT.encode() not in css
        with pytest.raises(urllib.error.HTTPError) as error:
            request(url + "/actions/create", "POST", {"name": "Bad", "quantity": "2", "location": "Shelf"})
        assert error.value.code == 400
        request(url + "/api/records/" + record["id"], "PATCH", {"quantity": 3})
        changed = projects.update(id, {"pages/index.html": "<h1>Revised page</h1>{{table}}"}, original["revision"])
        assert changed["revision"] != original["revision"]
        assert projects.get(id, original["revision"])["files"] == original["files"]
        assert projects.status(id) == changed["preview"]
        assert changed["preview"]["revision"] == changed["revision"]
        preview = changed["preview"]
        assert preview["url"] == url
        _, raw = request(preview["url"] + "/api/records")
        assert json.loads(raw)["records"][0]["quantity"] == 3
        exported = projects.export(id, include_data=True)
        extracted = tmp_path / "standalone"
        with zipfile.ZipFile(exported["path"]) as archive:
            assert all("app-bridge" not in name and "preview-inspector" not in name for name in archive.namelist())
            for name in archive.namelist():
                assert SCRIPT_ROOT.encode() not in archive.read(name)
            archive.extractall(extracted)
            for path, text in changed["files"].items():
                assert archive.read(path) == text.encode("utf-8")
        # Execute the extracted source itself with isolated import paths.
        ready = extracted / "ready.json"
        log = (extracted / "output.log").open("wb")
        process = subprocess.Popen(
            [sys.executable, "-I", "server.py", "--port", "0", "--ready-file", str(ready)],
            cwd=extracted, stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            import time
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            assert ready.exists(), (extracted / "output.log").read_text(encoding="utf-8")
            independent = json.loads(ready.read_text())["url"]
            _, page = request(independent + "/")
            assert b"Revised page" in page and b"Widget &lt;script&gt;" in page
            assert SCRIPT_ROOT.encode() not in page
            with pytest.raises(urllib.error.HTTPError) as error:
                request(independent + SCRIPT_ROOT + "app-bridge.js")
            assert error.value.code == 404
            _, raw = request(independent + "/api/records")
            assert json.loads(raw)["records"][0]["quantity"] == 3
        finally:
            process.terminate(); process.wait(timeout=5); log.close()
        projects.stop(id)
        assert projects.status(id)["state"] == "stopped"
    finally:
        projects.close()


def test_failed_revision_keeps_the_visible_runtime(tmp_path):
    projects = AppProjects(tmp_path)
    try:
        original = projects.create("Before a failed start")
        id = original["id"]
        preview, runtime_url = projects.preview_runtime(id)
        assert runtime_url != preview["url"]
        _, direct = request(runtime_url + "/")
        assert SCRIPT_ROOT.encode() not in direct
        saved = projects.update(id, {"server.py": "raise RuntimeError('broken')"}, original["revision"])
        assert saved["revision"] != original["revision"] and saved["preview"] == preview
        assert "Application did not start" in saved["preview_warning"]
        assert projects.get(id)["revision"] == saved["revision"]

        with pytest.raises(ValueError, match="Application did not start"):
            projects.preview(id)
        assert projects.status(id) == preview
        _, health = request(preview["url"] + "/api/health")
        assert json.loads(health)["revision"] == original["revision"]
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


def test_stable_preview_link_starts_and_reuses_the_project(client):
    from concurrent.futures import ThreadPoolExecutor

    project = client.post("/api/app-projects", json={"name": "Preview link"}).json()
    id = project["id"]
    projects = client.svc.app_projects
    base = f"/api/app-projects/{id}/preview"
    stable = base + "/open"
    path = "/records?q=hola%20mundo"

    for missing in ("0" * 16, "invalid"):
        assert client.get(f"/api/app-projects/{missing}/preview/open").status_code == 404
    for invalid in ("https://example.test", "//example.test", "/\\example.test"):
        assert client.get(stable, params={"path": invalid}, follow_redirects=False).status_code == 400
    assert projects.status(id)["state"] == "stopped"

    def open_link():
        return client.get(stable, params={"path": path}, follow_redirects=False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [pool.submit(open_link) for _ in range(2)]
    first = projects.status(id)
    assert first["open_path"] == stable and first["revision"] == project["revision"]
    assert len(list((projects.root / id / "runs").iterdir())) == 1
    for future in responses:
        response = future.result()
        assert response.status_code == 307 and response.headers["cache-control"] == "no-store"
        assert response.headers["location"] == first["url"] + path

    updated = projects.update(id, {"pages/index.html": "<h1>Current revision</h1>"}, project["revision"])
    assert open_link().headers["location"] == first["url"] + path
    assert projects.status(id) == updated["preview"]
    assert updated["preview"]["session"] == first["session"]
    assert updated["preview"]["revision"] == updated["revision"]
    client.post(base, json={"operation": "stop"})
    assert open_link().status_code == 307
    current = projects.status(id)
    assert current["session"] != first["session"] and current["revision"] == updated["revision"]
    projects.archive(id, updated["revision"], confirm=True)
    assert open_link().status_code == 404


def test_stable_preview_link_reports_a_start_failure(client, monkeypatch):
    project = client.post("/api/app-projects", json={"name": "Unavailable preview"}).json()
    stable = f"/api/app-projects/{project['id']}/preview/open"

    def fail_start(*args):
        raise ValueError("Private startup diagnostics")

    monkeypatch.setattr(client.svc.app_projects, "preview", fail_start)
    for lang, message in (("es", "No se pudo iniciar"), ("en", "The preview could not start")):
        response = client.get(stable, params={"lang": lang}, follow_redirects=False)
        assert response.status_code == 503 and response.text.startswith(message)
        assert response.headers["cache-control"] == "no-store"
        assert "Private startup diagnostics" not in response.text


def test_app_render_retains_source_context(services):
    project = services.app_projects.create("Context board")
    try:
        render = services.app_project_render(project["id"], widths=[390])
        context = services.get_render(render["id"])["metrics"]["app_project"]
        assert context == {"id": project["id"], "revision": project["revision"], "source_sha256": project["source_sha256"]}
    finally:
        services.app_projects.stop(project["id"])


def test_browser_fields_can_share_form_member_names(tmp_path):
    import os
    if os.environ.get("VITRUVIUS_BROWSER_TESTS") != "1":
        pytest.skip("Set VITRUVIUS_BROWSER_TESTS=1 to run the real browser flow")
    from playwright.sync_api import sync_playwright, expect
    names = ["title", "elements", "querySelector", "addEventListener", "dataset", "namedItem"]
    projects = AppProjects(tmp_path)
    try:
        project = projects.create("Form member fields", fields=[{"name": name, "label": name, "type": "text"} for name in names])
        preview = projects.preview(project["id"])
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True, args=["--disable-gpu", "--use-angle=swiftshader"])
            try:
                page = browser.new_page()
                page.goto(preview["url"] + "/records")
                for name in names:
                    page.get_by_label(name, exact=True).fill("value " + name)
                with page.expect_navigation(wait_until="domcontentloaded") as created_navigation:
                    page.get_by_role("button", name="Add record", exact=True).click()
                assert created_navigation.value is not None and created_navigation.value.status == 200
                expect(page.get_by_role("heading", name="value title", exact=True)).to_be_visible()
                record_url = page.url
                record_id = page.locator("#record-form").get_attribute("data-id")
                assert record_id and record_url == preview["url"] + "/records/" + record_id
                origin_responses = []
                def observe_save(route):
                    # Read the real origin body before the client navigates;
                    # forward its status, headers and bytes without inventing a response.
                    origin = route.fetch(max_redirects=0)
                    raw = origin.body()
                    origin_responses.append((origin.status, raw, route.request.post_data_json))
                    route.fulfill(response=origin, body=raw)
                page.route(preview["url"] + "/actions/update", observe_save)
                page.get_by_label("elements", exact=True).fill("updated elements")
                with page.expect_navigation(url=record_url, wait_until="domcontentloaded") as saved_navigation:
                    with page.expect_response(lambda response: response.url == preview["url"] + "/actions/update"
                            and response.request.method == "POST") as saved_response:
                        page.get_by_role("button", name="Save changes", exact=True).click()
                expected = {"id": record_id, **{name: "value " + name for name in names}, "elements": "updated elements"}
                assert saved_response.value.status == 200 and len(origin_responses) == 1
                status, raw, submitted = origin_responses[0]
                assert status == 200 and json.loads(raw) == expected
                assert submitted == {"id": record_id, "elements": "updated elements"}
                (tmp_path / "observed-origin-save-response.json").write_bytes(raw)
                navigation = saved_navigation.value
                assert navigation is not None and navigation.status == 200 and navigation.url == record_url
                assert navigation.request.method == "GET" and navigation.request.is_navigation_request()
                assert navigation.request.frame == page.main_frame
                expect(page.get_by_label("elements", exact=True)).to_have_value("updated elements")
                _, raw = request(preview["url"] + "/api/records")
                rows = json.loads(raw)["records"]
                assert len(rows) == 1
                assert rows[0] == expected
            finally:
                browser.close()
    finally:
        projects.close()


def test_revision_history_records_author_and_walks_back_without_reapplying_undone_source(client, services):
    created = client.post("/api/app-projects", json={"name": "History"}).json()
    id = created["id"]
    route = f"/api/app-projects/{id}"
    first = services.app_projects.update(id, {"pages/index.html": "<h1>First</h1>"}, created["revision"],
                                         actor={"id": "editor", "name": "Editor"})
    second = client.put(route, json={"files": {"pages/index.html": "<h1>Second</h1>"},
                                     "expected_revision": first["revision"]}).json()
    assert second["history"][-2]["author"] == {"kind": "agent", "id": "editor", "name": "Editor"}
    assert second["history"][-1]["author"] == {"kind": "person"}

    def undo(project):
        return client.post(route + "/undo", json={"expected_revision": project["revision"],
                           "expected_updated_ts": project["updated_ts"],
                           "revision": project["history"][-1]["undo_revision"]})

    assert undo(first).status_code == 400
    restored = undo(second).json()
    assert restored["revision"] == first["revision"]
    assert restored["history"][-1]["action"] == "undo"
    assert restored["history"][-1]["previous_revision"] == second["revision"]
    assert restored["history"][-1]["undo_revision"] == created["revision"]
    original = undo(restored).json()
    assert original["revision"] == created["revision"]
    assert original["history"][-1]["undo_revision"] is None
    assert original["revisions"] == second["revisions"]


def test_undo_one_history_step_preserves_other_changes_and_reports_conflict(client, services):
    created = client.post("/api/app-projects", json={"name": "History steps"}).json()
    project_id = created["id"]
    route = f"/api/app-projects/{project_id}"
    source = "pages/index.html"
    first = services.app_projects.update(
        project_id, {source: "<h1>Edited</h1>"}, created["revision"],
        actor={"id": "editor", "name": "Editor"}, target={"selector": "h1"},
        examples=["editorial"], tokens_id="paper-ink",
    )
    step = first["history"][-1]
    assert (step["files"], step["target"], step["examples"], step["tokens_id"]) == (
        [source], "h1", ["editorial"], "paper-ink",
    )
    second = services.app_projects.update(project_id, {"assets/added.css": "a{color:blue}"},
                                           first["revision"])

    def undo(project, change=step["id"]):
        return client.post(route + "/undo-change", json={"change_id": change,
                           "expected_revision": project["revision"], "expected_updated_ts": project["updated_ts"]})

    reversed_step = undo(second).json()
    assert reversed_step["files"][source] == created["files"][source]
    assert reversed_step["files"]["assets/added.css"] == "a{color:blue}"
    assert reversed_step["history"][-1]["reverted_change"] == step["id"]
    assert reversed_step["undo"]["arguments"]["revision"] == second["revision"]
    assert undo(reversed_step).json()["already_undone"]

    later = services.app_projects.update(project_id, {source: "Later edit"}, reversed_step["revision"])
    response = undo(later)
    assert response.status_code == 409 and response.json()["files"] == [source]
    assert "Later changes overlap" in response.json()["error"]
    assert services.app_projects.get(project_id)["files"][source] == "Later edit"
