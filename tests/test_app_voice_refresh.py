from importlib.util import find_spec
from pathlib import Path

import httpx
import pytest

from test_app_project_collections import source_files, transfer_spec
from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.hoard_link.agentkit import AppError
from vitruvius_hoard.transfer_assistant import ENTRY, assistant_assets, voice
from vitruvius_hoard.transfer_assistant.embedded import FORM_ENTRY


LEGACY = "// old embedded assistant: fixed cached replies\n"
TOOL = "app_project_refresh_voice_assistant"


def project_with_old_assistant(services):
    files = source_files(transfer_spec())
    files["pages/index.html"] += '<section data-transfer-assistant="manual" id="tesela-voice"></section>'
    files["assets/transfer-assistant/project-notes.txt"] = "Project-owned source"
    files[ENTRY] = LEGACY
    return call_tool(services, "app_project_create", {"name": "Voice update fixture", "template": "custom", "files": files})


def refresh(services, project):
    return call_tool(services, TOOL, {"id": project["id"], "expected_revision": project["revision"]})


def test_refresh_versions_only_packaged_assets_and_undo_preserves_project_data(services):
    project = project_with_old_assistant(services)
    original = project["files"]
    projects = services.app_projects
    services.app_project_call(project["id"], "invoke", action="transfer",
                  data={"source_account_id": "daily", "destination_contact_id": "supplier",
                        "amount_cents": 80, "concept": "Existing transfer"})
    data_before = services.app_project_call(project["id"], "list", collection="movements")
    accounts_before = services.app_project_call(project["id"], "list", collection="accounts")

    receipt = refresh(services, project)
    assert receipt["changed"] and receipt["revision"] != project["revision"]
    current = projects.get(project["id"])
    assets = assistant_assets()["files"]
    assert receipt["files"] == sorted(assets)
    assert current["files"] == {**original, **assets}
    assert projects.get(project["id"], project["revision"])["files"] == original
    assert services.app_project_call(project["id"], "list", collection="movements") == data_before
    assert services.app_project_call(project["id"], "list", collection="accounts") == accounts_before

    assert refresh(services, current) == {"id": project["id"], "revision": current["revision"],
                                         "changed": False, "files": []}
    assert len(projects.get(project["id"])["revisions"]) == 2
    with pytest.raises(AppError, match="current project revision"):
        refresh(services, project)

    undo = receipt["undo"]
    assert undo["tool"] == "app_project_undo"
    call_tool(services, undo["tool"], undo["arguments"])
    assert projects.get(project["id"])["files"] == original
    assert services.app_project_call(project["id"], "list", collection="movements") == data_before
    assert services.app_project_call(project["id"], "list", collection="accounts") == accounts_before


def test_refresh_rest_leaves_projects_without_an_assistant_as_they_were(client):
    project = client.post("/api/app-projects", json={"name": "Without voice"}).json()
    url = f"/api/app-projects/{project['id']}/voice-assistant/refresh"
    assert client.post(url, json={"expected_revision": "stale"}).status_code == 409
    failed = client.post(url, json={"expected_revision": project["revision"]})
    assert failed.status_code == 400
    assert client.get(f"/api/app-projects/{project['id']}").json()["revision"] == project["revision"]


@pytest.mark.skipif(find_spec("vitruvius_hoard.transfer_assistant.voice_directory") is None,
                    reason="Direct dictation activates when its preview transport is integrated")
def test_refresh_uses_direct_preview_when_transport_is_integrated(services, monkeypatch):
    from urllib.request import ProxyHandler, build_opener
    import json

    from vitruvius_hoard.transfer_assistant import voice_directory

    origin = "http://127.0.0.1:59731"
    reads = []

    def catalog():
        reads.append("catalog")
        return [{"id": "cyrano", "url": origin, "name": "Boltagon"}]

    def request(url, path, **settings):
        assert url == origin
        assert path == "/api/agent/tools"
        return httpx.Response(200, json={"tools": [{"name": name} for name in
                             (voice.SPEECH_TOOL, voice.END_TURN_TOOL, *voice.DICTATION_TOOLS)]})

    monkeypatch.delenv("CYRANO_URL", raising=False)
    monkeypatch.setattr(voice_directory, "_hub_apps", catalog)
    monkeypatch.setattr(voice_directory, "_request", request)
    project = project_with_old_assistant(services)
    receipt = refresh(services, project)
    opened = call_tool(services, "app_project_preview", {"id": project["id"], "operation": "start"})
    assert opened["revision"] == receipt["revision"]
    own = build_opener(ProxyHandler({}))
    try:
        with own.open(opened["url"] + "/" + ENTRY, timeout=5) as response:
            assert b"assessTransferEndTurn" in response.read()
        capabilities = opened["url"] + voice.VOICE_PREFIX + "capabilities"
        for _ in range(2):
            with own.open(capabilities, timeout=5) as response:
                result = json.load(response)
                assert result["dictation_route"] == "direct"
                assert result["adaptive_turn"]
        assert reads == ["catalog"]
    finally:
        call_tool(services, "app_project_preview", {"id": project["id"], "operation": "stop"})


@pytest.mark.skipif(not Path(voice.__file__).with_name("form.js").is_file(),
                    reason="Form voice assets activate when the form assistant is integrated")
def test_refresh_form_keeps_configuration_and_other_assets(services):
    files = source_files(transfer_spec())
    files["pages/index.html"] += '<span data-voice-assistant="{&quot;formSelector&quot;:&quot;#existing&quot;}"></span>'
    files[FORM_ENTRY] = LEGACY
    project = call_tool(services, "app_project_create", {"name": "Legacy form assistant", "template": "custom", "files": files})
    receipt = refresh(services, project)
    assert receipt["changed"] and FORM_ENTRY in receipt["files"]
    current = services.app_projects.get(project["id"])["files"]
    assert current["pages/index.html"] == project["files"]["pages/index.html"]
    assert current["project.json"] == project["files"]["project.json"]
