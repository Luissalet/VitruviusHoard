import json

import httpx
import pytest

from vitruvius_hoard.agent_tools import tool_catalog
from vitruvius_hoard.app_projects import AppProjects
from vitruvius_hoard.software.host import catalog
from vitruvius_hoard.transfer_assistant import ENTRY, FORM_ENTRY
from vitruvius_hoard.transfer_assistant import voice


SCHEMA = {"type": "object", "properties": {"seats": {"type": "integer", "title": "Plazas"}},
          "required": ["seats"]}


def test_one_revision_adds_an_undoable_voice_assistant_without_changing_the_form(tmp_path):
    projects = AppProjects(tmp_path)
    initial = projects.create("Reservations")
    page = "pages/index.html"
    source = '<h1>Reservas</h1><form id="booking"><input name="seats" required></form>'
    original = projects.update(initial["id"], {page: source, ENTRY: "// existing transfer assistant"},
                               initial["revision"])
    arguments = {"id": original["id"], "page": page, "form_selector": "#booking", "schema": SCHEMA}
    added = projects.add_voice_assistant(**arguments, expected_revision=original["revision"])
    updated = projects.get(original["id"])
    assert updated["files"][page].startswith(source)
    assert FORM_ENTRY in updated["files"]
    assert updated["files"][ENTRY] == original["files"][ENTRY]
    assert updated["files"]["layout.html"] == original["files"]["layout.html"]
    assert added["undo"]["tool"] == "app_project_undo"

    retry = projects.add_voice_assistant(**arguments, expected_revision=original["revision"])
    assert retry == {**{name: value for name, value in added.items() if name != "undo"}, "changed": False}
    restored = projects.undo(**added["undo"]["arguments"])
    assert restored["files"] == original["files"]


def test_form_assistant_is_in_the_cold_mcp_catalog():
    name = "app_project_add_voice_assistant"
    frozen = next(tool for tool in catalog() if tool["name"] == name)
    native = next(tool for tool in tool_catalog() if tool["name"] == name)
    assert frozen == native
    assert not frozen["annotations"]["readOnlyHint"]
    assert "schema" in frozen["inputSchema"]["required"]


@pytest.mark.parametrize("schema", [
    {"type": "string"},
    {"type": "object", "properties": {"seats": {"type": "guess"}}},
    {**SCHEMA, "required": ["other"]},
])
def test_invalid_field_schema_does_not_create_a_revision(tmp_path, schema):
    projects = AppProjects(tmp_path)
    original = projects.create("Reservations")
    with pytest.raises(ValueError, match="[Ss]chema|required"):
        projects.add_voice_assistant(original["id"], original["revision"], "pages/index.html", "form", schema)
    assert projects.get(original["id"])["revision"] == original["revision"]


def test_configured_boltagon_handles_final_audio_and_structured_text_without_hub(monkeypatch):
    monkeypatch.setenv("CYRANO_URL", "http://127.0.0.1:56253")
    calls = []

    def incoming(request):
        assert request.url.port == 56253
        data = json.loads(request.content)
        calls.append(request.url.path)
        if request.url.path == "/api/speech/transcribe":
            assert data["audio"] == {"mime_type": "audio/wav", "data_base64": "dGVzdA=="}
            assert data["fallback"] is False
            return httpx.Response(200, json={"text": "Plazas veinte", "ms": 410, "engine": "faster-whisper"})
        assert data["schema"] == SCHEMA
        assert data["context"] == {"draft": {"seats": 10}}
        return httpx.Response(200, json={"version": voice.DICTATION_VERSION,
                                        "fields": {"seats": {"value": 20, "quote": "veinte"}}})

    client = httpx.Client
    monkeypatch.setattr(voice.httpx, "Client", lambda **opts: client(transport=httpx.MockTransport(incoming), **opts))
    monkeypatch.setattr(voice, "_hub_get", lambda *args, **kwargs: pytest.fail("Unexpected Hub discovery"))
    relay = voice.TransferVoice()
    status, data, _ = relay.handle("POST", "transcribe", "language=es", "audio/wav", b"test")
    assert status == 200
    assert json.loads(data) == {"text": "Plazas veinte", "ms": 410, "final": True,
                                "provider": "Boltagon · faster-whisper"}
    body = {"version": voice.DICTATION_VERSION, "text": "Plazas veinte", "schema": SCHEMA,
            "context": {"draft": {"seats": 10}}}
    status, data, _ = relay.handle("POST", "understand", "", "application/json", json.dumps(body).encode())
    assert status == 200
    assert json.loads(data)["dictation_route"] == "direct"
    assert calls == ["/api/speech/transcribe", "/api/dictation/understand"]
