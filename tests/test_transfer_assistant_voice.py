import base64
import json
from pathlib import Path

from vitruvius_hoard.hoard_link.service_contracts import OWNERS
from vitruvius_hoard.transfer_assistant import ASSETS, ENTRY, assistant_assets
from vitruvius_hoard.transfer_assistant import voice


def payload(response):
    return json.loads(response[1])


def test_exposed_sources_can_be_saved_as_project_assets():
    result = assistant_assets()
    assert ENTRY in result["files"]
    assert {Path(path).name for path in result["files"]} == set(ASSETS)
    assert ENTRY in result["script"] and "data-transfer-assistant" in result["mount"]


def test_capabilities_probe_callable_owner_even_if_state_is_foreign(monkeypatch):
    assert OWNERS["dictation"] == "cyrano"
    reads = []
    catalogue = {
        "/api/services/status": {"services": [{"service": "dictation", "owner": "cyrano"}]},
        "/api/apps/funes": {"state": "foreign"},
        "/api/apps/funes/tools": {"ok": True, "tools": [{"name": name} for name in ("transcribe_file", "transcribe_status")]},
        "/api/apps/cyrano/tools": {"ok": True, "tools": [{"name": name} for name in voice.DICTATION_TOOLS]},
        "/api/apps/prospero/tools": {"ok": False},
    }

    def hub_get(path, **kwargs):
        reads.append(path)
        return 200, catalogue[path]

    monkeypatch.setattr(voice, "_hub_get", hub_get)
    result = voice.TransferVoice().handle("GET", "capabilities", "", "", b"")
    assert result[0] == 200
    assert payload(result) == {"stt": True, "tts": False, "dictation": True, "dictation_route": "common"}
    assert "/api/apps/funes/tools" in reads and "/api/apps/funes" not in reads


def test_capabilities_distinguish_legacy_app_and_local_paths(monkeypatch):
    monkeypatch.setattr(voice._famsvc, "call_tool", lambda *_args, **_kwargs: {"ok": False})
    def hub_get(path, **kwargs):
        if path == "/api/services/status":
            return 200, {"services": []}
        if path == "/api/apps/cyrano/tools":
            return 200, {"ok": True, "tools": [{"name": name} for name in voice.DICTATION_TOOLS]}
        return 404, {}

    monkeypatch.setattr(voice, "_hub_get", hub_get)
    relay = voice.TransferVoice()
    ready = payload(relay.handle("GET", "capabilities", "", "", b""))
    assert ready["dictation"] and ready["dictation_route"] == "app"
    monkeypatch.setattr(voice, "_hub_get", lambda path, **kwargs: (503, {}))
    down = payload(voice.TransferVoice().handle("GET", "capabilities", "", "", b""))
    assert not down["dictation"] and down["dictation_route"] == "local"


def test_transcription_readiness_accepts_a_call_through_a_hidden_tool_catalogue(monkeypatch):
    monkeypatch.setattr(voice, "_hub_get", lambda *_args, **_kwargs: (503, {}))
    calls = []

    def call(owner, tool, args, **kwargs):
        calls.append((owner, tool, args))
        return {"ok": False, "status": 404, "error": "no such job"}

    monkeypatch.setattr(voice._famsvc, "call_tool", call)
    result = voice.TransferVoice().handle("GET", "capabilities", "", "", b"")
    assert payload(result)["stt"]
    [(owner, tool, args)] = calls
    assert (owner, tool) == ("funes", "transcribe_status")
    assert len(args["job_id"]) == 32


def test_registered_service_uses_common_contract_and_never_replays_through_app(monkeypatch):
    calls = []

    def shared_call(owner, tool, args, timeout_s):
        calls.append((owner, tool, args, timeout_s))
        if args["text"] == "fail":
            return {"ok": False}
        return {"ok": True, "data": {"version": voice.DICTATION_VERSION, "raw_transcript": "treinta"}}

    monkeypatch.setattr(voice, "_hub_get", lambda path, **kwargs: (200, {"services": [{"service": "dictation"}]}))
    monkeypatch.setattr(voice._famsvc, "call_tool", shared_call)
    monkeypatch.setattr(voice.family, "call", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Unexpected direct call")))
    relay = voice.TransferVoice()
    for phrase, status in (("treinta", 200), ("fail", 503)):
        req = json.dumps({"version": voice.DICTATION_VERSION, "text": phrase}).encode()
        reply = relay.handle("POST", "understand", "", "application/json", req)
        assert reply[0] == status
        if status == 200:
            assert payload(reply)["dictation_route"] == "common"
    assert [entry[:2] for entry in calls] == [("cyrano", "dictation_understand")] * 2


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
        result = relay.handle("POST", "transcribe", f"language=es&partial={str(partial).lower()}&initial_prompt=Luc%C3%ADa%2C+Cuenta+diaria",
                              "audio/webm;codecs=opus", b"synthetic audio")
        assert result[0] == 200 and payload(result) == {"text": "Treinta euros", "final": not partial}
    assert all(not source.exists() for source, _ in calls)
    assert [args["local_fallback"] for _, args in calls] == [False, False]
    assert [args["vad"] for _, args in calls] == [False, True]
    assert [args["initial_prompt"] for _, args in calls] == ["Lucía, Cuenta diaria"] * 2
    assert calls[1][1]["timeout_s"] > 11


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
    monkeypatch.setattr(voice, "_hub_get", lambda path, **kwargs: (200, {"services": []}))
    relay = voice.TransferVoice()
    options = {"version": voice.DICTATION_VERSION, "language": "es-ES", "vocabulary": ["Ana"],
               "context": {"field": "amount_cents"}, "schema": {"type": "object"}}
    for item in [{"text": "treinta"}, {"audio": {"mime_type": "audio/wav",
                                               "data_base64": base64.b64encode(b"synthetic").decode("ascii")}}]:
        response = relay.handle("POST", "understand", "", "application/json", json.dumps({**options, **item}).encode())
        assert response[0] == 200 and payload(response)["fields"]["amount_cents"]["value"] == 3000
        assert payload(response)["dictation_route"] == "app"
    assert [call[0] for call in calls] == ["dictation_understand", "dictation_audio"]
    assert calls[0][1]["text"] == "treinta"
    assert calls[1][1]["context"] == {"field": "amount_cents"}
    assert not Path(calls[1][1]["path"]).exists()


def test_fallback_and_invalid_local_requests_have_separate_statuses(monkeypatch):
    monkeypatch.setattr(voice, "VOICE_MODE", "piper")
    monkeypatch.setattr(voice.fam_media, "speak_bytes", lambda *_args, **_kwargs: {"ok": False})
    monkeypatch.setattr(voice.fam_media, "transcribe", lambda *_args, **_kwargs: {"ok": False})
    monkeypatch.setattr(voice.family, "call", lambda *_args, **_kwargs: {"ok": False})
    monkeypatch.setattr(voice, "_hub_get", lambda path, **kwargs: (404, {}))
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


def test_disabled_voice_generation_preserves_expected_conflict(monkeypatch):
    monkeypatch.setattr(voice, "VOICE_MODE", "piper")
    monkeypatch.setattr(voice.fam_media, "speak_bytes",
                        lambda *_a, **_kw: {"ok": False, "error": "generation is OFF"})
    reply = voice.TransferVoice().handle("POST", "speak", "", "application/json", b'{"text":"Hola"}')
    assert reply[0] == 409 and payload(reply)["code"] == "tts_disabled"


def test_shared_voice_returns_playable_bytes_without_server_fallback(monkeypatch):
    monkeypatch.setattr(voice, "VOICE_MODE", "piper")
    def speak(text, **arguments):
        assert text == "¿Confirmas la transferencia?"
        assert arguments["lang"] == "es" and arguments["local_fallback"] is False
        assert arguments["engine"] == "piper" and arguments["voice"] == voice.SPANISH_TTS_VOICE
        assert arguments["timeout_s"] >= 8
        return {"ok": True, "data": b"RIFF synthetic WAV"}

    monkeypatch.setattr(voice.fam_media, "speak_bytes", speak)
    body = json.dumps({"text": "¿Confirmas la transferencia?", "language": "es"}).encode()
    assert voice.TransferVoice().handle("POST", "speak", "", "application/json", body) == (200, b"RIFF synthetic WAV", "audio/wav")


def test_natural_cache_uses_only_the_matching_manifest_phrase(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "VOICE_MODE", "cache-natural")
    monkeypatch.setattr(voice, "VOICE_CACHE", str(tmp_path))
    monkeypatch.setattr(voice.fam_media, "speak_bytes",
                        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("The cache never calls speech generation")))
    text = "Revisa los datos y dime si la envío."
    (tmp_path / "frases.json").write_text(json.dumps({"phrases": {"confirmar": text, "saludo": "Dime"}}), encoding="utf-8")
    wav = b"RIFF1234WAVE"
    (tmp_path / "confirmar.wav").write_bytes(wav)
    relay = voice.TransferVoice()

    def speak(phrase, words):
        body = json.dumps({"text": words, "phrase_id": phrase, "language": "es"}).encode()
        return relay.handle("POST", "speak", "", "application/json", body)

    assert speak("confirmar", text) == (200, wav, "audio/wav; source=cache-natural")
    assert speak("confirmar", "Transfiere dinero a María")[0] == 404
    assert speak("../confirmar", text)[0] == 404
    assert speak("saludo", "Dime")[0] == 404
    monkeypatch.setattr(voice, "VOICE_MODE", "off")
    assert speak("confirmar", text)[0] == 503
