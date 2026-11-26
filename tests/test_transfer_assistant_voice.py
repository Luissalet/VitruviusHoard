import base64
import json
from pathlib import Path

from vitruvius_hoard.transfer_assistant import ASSETS, ENTRY, assistant_assets
from vitruvius_hoard.transfer_assistant import voice


def payload(response):
    return json.loads(response[1])


def test_exposed_sources_can_be_saved_as_project_assets():
    result = assistant_assets()
    assert ENTRY in result["files"]
    assert {Path(path).name for path in result["files"]} == set(ASSETS)
    assert ENTRY in result["script"] and "data-transfer-assistant" in result["mount"]


def test_capabilities_have_independent_provider_states(monkeypatch):
    monkeypatch.setattr(voice.fam_media, "available", lambda name: name == "stt")
    result = voice.TransferVoice().handle("GET", "capabilities", "", "", b"")
    assert result[0] == 200
    assert payload(result) == {"stt": True, "tts": False, "dictation": False}


def test_shared_transcription_handles_provisional_and_final_audio(monkeypatch):
    calls = []

    def transcribe(path, **arguments):
        source = Path(path)
        assert source.suffix == ".webm" and source.read_bytes() == b"synthetic audio"
        calls.append((source, arguments))
        return {"ok": True, "text": "Treinta euros"}

    monkeypatch.setattr(voice.fam_media, "transcribe", transcribe)
    relay = voice.TransferVoice()
    for partial in (True, False):
        result = relay.handle("POST", "transcribe", f"language=es&partial={str(partial).lower()}",
                              "audio/webm;codecs=opus", b"synthetic audio")
        assert result[0] == 200 and payload(result) == {"text": "Treinta euros", "final": not partial}
    assert all(not source.exists() for source, _ in calls)
    assert [args["local_fallback"] for _, args in calls] == [False, False]
    assert [args["vad"] for _, args in calls] == [False, True]


def test_versioned_text_and_audio_follow_the_common_tools(monkeypatch):
    calls = []

    def call(app, tool, arguments, *, timeout):
        assert app == "cyrano"
        calls.append((tool, arguments))
        if source := arguments.get("path"):
            assert Path(source).read_bytes() == b"synthetic"
        return {"ok": True, "result": {"version": voice.DICTATION_VERSION, "raw_transcript": "treinta",
                                       "is_final": True, "fields": {"amount_cents": {"value": 3000}}}}

    monkeypatch.setattr(voice.family, "call", call)
    relay = voice.TransferVoice()
    options = {"version": voice.DICTATION_VERSION, "language": "es-ES", "vocabulary": ["Ana"],
               "context": {"field": "amount_cents"}, "schema": {"type": "object"}}
    for item in [{"text": "treinta"}, {"audio": {"mime_type": "audio/wav",
                                               "data_base64": base64.b64encode(b"synthetic").decode("ascii")}}]:
        response = relay.handle("POST", "understand", "", "application/json", json.dumps({**options, **item}).encode())
        assert response[0] == 200 and payload(response)["fields"]["amount_cents"]["value"] == 3000
    assert [call[0] for call in calls] == ["dictation_understand", "dictation_audio"]
    assert calls[0][1]["text"] == "treinta"
    assert calls[1][1]["context"] == {"field": "amount_cents"}
    assert not Path(calls[1][1]["path"]).exists()


def test_fallback_and_invalid_local_requests_have_separate_statuses(monkeypatch):
    monkeypatch.setattr(voice.fam_media, "speak_bytes", lambda *_args, **_kwargs: {"ok": False})
    monkeypatch.setattr(voice.fam_media, "transcribe", lambda *_args, **_kwargs: {"ok": False})
    monkeypatch.setattr(voice.family, "call", lambda *_args, **_kwargs: {"ok": False})
    relay = voice.TransferVoice()
    cases = [
        ("transcribe", "", "audio/webm", b"synthetic", 503, "stt_unavailable"),
        ("transcribe", "", "text/html", b"synthetic", 415, "unsupported_audio"),
        ("speak", "", "application/json", b'{"text":"Hola"}', 503, "tts_unavailable"),
        ("speak", "", "application/json", b"[]", 400, "invalid_voice_request"),
        ("understand", "", "application/json", b'{"version":"cyrano.dictation/v0","text":"hola"}', 503, "dictation_unavailable"),
        ("understand", "", "application/json", b'{"version":"cyrano.dictation/v0","audio":{"mime_type":"audio/wav","data_base64":"?"}}', 400, "invalid_audio"),
    ]
    for route, query, media, body, status, code in cases:
        result = relay.handle("POST", route, query, media, body)
        assert result[0] == status and payload(result)["code"] == code


def test_shared_voice_returns_playable_bytes_without_server_fallback(monkeypatch):
    def speak(text, **arguments):
        assert text == "¿Confirmas la transferencia?"
        assert arguments["lang"] == "es" and arguments["local_fallback"] is False
        return {"ok": True, "data": b"RIFF synthetic WAV"}

    monkeypatch.setattr(voice.fam_media, "speak_bytes", speak)
    body = json.dumps({"text": "¿Confirmas la transferencia?", "language": "es"}).encode()
    assert voice.TransferVoice().handle("POST", "speak", "", "application/json", body) == (200, b"RIFF synthetic WAV", "audio/wav")
