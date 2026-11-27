import base64
import json
from pathlib import Path

import pytest

from vitruvius_hoard.hoard_link.service_contracts import OWNERS
from vitruvius_hoard.transfer_assistant import ASSETS, ENTRY, assistant_assets
from vitruvius_hoard.transfer_assistant import voice


@pytest.fixture(autouse=True)
def use_family_transport(monkeypatch):
    """These tests exercise the family registry with injected replies."""
    monkeypatch.setattr(voice, "_direct_voice", lambda *_args, **_kwargs: None)


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
        "/api/apps/cyrano": {"name": "Boltagon's Hoard"},
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
    assert payload(result) == {"stt": True, "tts": False, "dictation": True, "dictation_route": "common",
                               "dictation_name": "Boltagon's Hoard"}
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
    assert ready["dictation_name"] == "Boltagon"
    monkeypatch.setattr(voice, "_hub_get", lambda path, **kwargs: (503, {}))
    down = payload(voice.TransferVoice().handle("GET", "capabilities", "", "", b""))
    assert not down["dictation"] and down["dictation_route"] == "local"


def test_first_dictation_uses_health_name_and_reuses_it_after_discovery(monkeypatch):
    calls = []
    now = 0

    def hub_get(path, **kwargs):
        calls.append(path)
        return 200, {"url": "http://127.0.0.1:59731", "name": "cyrano", "health": {"name": "cyrano"}}

    def health(url, **kwargs):
        calls.append(url)
        if now < voice.DICTATION_NAME_TTL:
            return 200, {"service": "cyrano-hoard", "name": "  Visible Dictation's Hoard  "}
        return 503, {}

    monkeypatch.setattr(voice, "monotonic", lambda: now)
    monkeypatch.setattr(voice, "_hub_get", hub_get)
    monkeypatch.setattr(voice, "fetch", health)
    relay = voice.TransferVoice()
    monkeypatch.setattr(relay, "_dictation_call", lambda *_args, **_kwargs: ({"version": voice.DICTATION_VERSION}, "app"))
    request = json.dumps({"version": voice.DICTATION_VERSION, "text": "treinta"}).encode()

    def name():
        status, result, _ = relay.handle("POST", "understand", "", "application/json", request)
        assert status == 200
        return json.loads(result)["dictation_name"]

    assert name() == name() == "Visible Dictation's Hoard"
    reads = ["/api/apps/cyrano", "http://127.0.0.1:59731/api/health"]
    assert calls == reads
    now = voice.DICTATION_NAME_TTL
    assert name() == "Visible Dictation's Hoard"
    assert calls == reads * 2


def test_first_dictation_uses_visible_default_when_hub_and_health_are_unavailable(monkeypatch):
    monkeypatch.setenv("CYRANO_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(voice, "_hub_get", lambda *_args, **_kwargs: (503, {}))
    monkeypatch.setattr(voice, "fetch", lambda *_args, **_kwargs: (503, {}))
    relay = voice.TransferVoice()
    monkeypatch.setattr(relay, "_dictation_call", lambda *_args, **_kwargs: ({"version": voice.DICTATION_VERSION}, "app"))
    request = json.dumps({"version": voice.DICTATION_VERSION, "text": "treinta"}).encode()
    assert payload(relay.handle("POST", "understand", "", "application/json", request))["dictation_name"] == "Boltagon"


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
    calls, order = [], []

    def cyrano(tool, args, timeout):
        order.append((tool, args["path"]))
        assert args["fallback"] is False
        return None, "common"

    def transcribe(path, **arguments):
        source = Path(path)
        assert source.suffix == ".webm" and source.read_bytes() == b"synthetic audio"
        calls.append((source, arguments))
        order.append(("family", path))
        return {"ok": True, "text": "Treinta euros"}

    monkeypatch.setattr(voice.fam_media, "transcribe", transcribe)
    relay = voice.TransferVoice()
    monkeypatch.setattr(relay, "_dictation_call", cyrano)
    for partial in (True, False):
        result = relay.handle("POST", "transcribe", f"language=es&partial={str(partial).lower()}&initial_prompt=Luc%C3%ADa%2C+Cuenta+diaria",
                              "audio/webm;codecs=opus", b"synthetic audio")
        assert result[0] == 200 and payload(result) == {
            "text": "Treinta euros", "final": not partial, "provider": "Funes / Talos (reserva)",
            "fallback_reason": "resident_unavailable",
        }
    assert all(not source.exists() for source, _ in calls)
    assert [args["local_fallback"] for _, args in calls] == [False, False]
    assert [args["vad"] for _, args in calls] == [False, True]
    assert [args["initial_prompt"] for _, args in calls] == ["Lucía, Cuenta diaria"] * 2
    assert calls[1][1]["timeout_s"] > 11
    assert [tool for tool, _ in order] == [voice.SPEECH_TOOL, "family"] * 2
    assert order[0][1] == order[1][1] and order[2][1] == order[3][1]


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
    monkeypatch.setattr(voice, "_hub_get", lambda path, **kwargs: (
        200, {"name": "Boltagon's Hoard"} if path == "/api/apps/cyrano" else {"services": []},
    ))
    relay = voice.TransferVoice()
    options = {"version": voice.DICTATION_VERSION, "language": "es-ES", "vocabulary": ["Ana"],
               "context": {"field": "amount_cents"}, "schema": {"type": "object"}}
    for item in [{"text": "treinta"}, {"audio": {"mime_type": "audio/wav",
                                               "data_base64": base64.b64encode(b"synthetic").decode("ascii")}}]:
        response = relay.handle("POST", "understand", "", "application/json", json.dumps({**options, **item}).encode())
        assert response[0] == 200 and payload(response)["fields"]["amount_cents"]["value"] == 3000
        assert payload(response)["dictation_route"] == "app"
        assert payload(response)["dictation_name"] == "Boltagon's Hoard"
    assert [call[0] for call in calls] == ["dictation_understand", "dictation_audio"]
    assert calls[0][1]["text"] == "treinta"
    assert calls[1][1]["context"] == {"field": "amount_cents"}
    assert not Path(calls[1][1]["path"]).exists()


def test_fallback_and_invalid_local_requests_have_separate_statuses(monkeypatch):
    monkeypatch.setattr(voice, "VOICE_MODE", "piper")
    monkeypatch.setattr(voice, "_cache_phrases", lambda _root: {"saludo": "Hola"})
    monkeypatch.setattr(voice.fam_media, "speak_bytes", lambda *_args, **_kwargs: {"ok": False})
    monkeypatch.setattr(voice.fam_media, "transcribe", lambda *_args, **_kwargs: {"ok": False})
    monkeypatch.setattr(voice.family, "call", lambda *_args, **_kwargs: {"ok": False})
    monkeypatch.setattr(voice, "_hub_get", lambda path, **kwargs: (404, {}))
    relay = voice.TransferVoice()
    cases = [
        ("transcribe", "", "audio/webm", b"synthetic", 503, "stt_unavailable"),
        ("transcribe", "", "text/html", b"synthetic", 415, "unsupported_audio"),
        ("speak", "", "application/json", b'{"text":"Hola","phrase_id":"saludo"}', 503, "tts_unavailable"),
        ("speak", "", "application/json", b"[]", 400, "invalid_voice_request"),
        ("understand", "", "application/json", b'{"version":"cyrano.dictation/v0","text":"hola"}', 503, "dictation_unavailable"),
        ("understand", "", "application/json", b'{"version":"cyrano.dictation/v0","audio":{"mime_type":"audio/wav","data_base64":"?"}}', 400, "invalid_audio"),
    ]
    for route, query, media, body, status, code in cases:
        result = relay.handle("POST", route, query, media, body)
        assert result[0] == status and payload(result)["code"] == code


def test_disabled_voice_generation_preserves_expected_conflict(monkeypatch):
    monkeypatch.setattr(voice, "VOICE_MODE", "piper")
    monkeypatch.setattr(voice, "_cache_phrases", lambda _root: {"saludo": "Hola"})
    monkeypatch.setattr(voice.fam_media, "speak_bytes",
                        lambda *_a, **_kw: {"ok": False, "error": "generation is OFF"})
    reply = voice.TransferVoice().handle("POST", "speak", "", "application/json", b'{"text":"Hola","phrase_id":"saludo"}')
    assert reply[0] == 409 and payload(reply)["code"] == "tts_disabled"


def test_shared_voice_returns_playable_bytes_without_server_fallback(monkeypatch):
    monkeypatch.setattr(voice, "VOICE_MODE", "piper")
    monkeypatch.setattr(voice, "_cache_phrases", lambda _root: {"confirmar": "¿Confirmas la transferencia?"})
    def speak(text, **arguments):
        assert text == "¿Confirmas la transferencia?"
        assert arguments["lang"] == "es" and arguments["local_fallback"] is False
        assert arguments["engine"] == "piper" and arguments["voice"] == voice.SPANISH_TTS_VOICE
        assert arguments["timeout_s"] >= 8
        return {"ok": True, "data": b"RIFF synthetic WAV"}

    monkeypatch.setattr(voice.fam_media, "speak_bytes", speak)
    body = json.dumps({"text": "¿Confirmas la transferencia?", "language": "es", "phrase_id": "confirmar"}).encode()
    assert voice.TransferVoice().handle("POST", "speak", "", "application/json", body) == (200, b"RIFF synthetic WAV", "audio/wav")
    by_id = b'{"language":"es","phrase_id":"confirmar"}'
    assert voice.TransferVoice().handle("POST", "speak", "", "application/json", by_id) == (200, b"RIFF synthetic WAV", "audio/wav")
    legacy_request = b'{"text":"Confirma esta transferencia de 40 euros","phrase_id":"confirmar"}'
    assert voice.TransferVoice().handle("POST", "speak", "", "application/json", legacy_request) == (200, b"RIFF synthetic WAV", "audio/wav")
    unknown = voice.TransferVoice().handle("POST", "speak", "", "application/json", b'{"text":"variable","phrase_id":"unknown"}')
    assert unknown[0] == 404


def test_natural_cache_uses_only_the_matching_manifest_phrase(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "VOICE_MODE", "cache-natural")
    monkeypatch.setenv("VITRUVIUS_PROFILE_DIR", str(tmp_path / "other-profile"))
    monkeypatch.setenv("VITRUVIUS_VOICE_CACHE", str(tmp_path))
    monkeypatch.setattr(voice.fam_media, "speak_bytes",
                        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("The cache never calls speech generation")))
    text = "Revisa los datos y dime si la envío."
    (tmp_path / "frases.json").write_text(json.dumps({"phrases": {"confirmar": text, "saludo": "Dime"}}), encoding="utf-8")
    wav = b"RIFF1234WAVE"
    (tmp_path / "confirmar.wav").write_bytes(wav)
    relay = voice.TransferVoice()
    monkeypatch.setattr(voice, "_hub_get", lambda *_a, **_kw: (404, {}))
    monkeypatch.setattr(voice._famsvc, "call_tool", lambda *_a, **_kw: {"ok": False})
    availability = payload(relay.handle("GET", "capabilities", "", "", b""))
    assert availability["tts"] and availability["voice_phrases"]["confirmar"] == text

    def speak(phrase, words):
        body = json.dumps({"text": words, "phrase_id": phrase, "language": "es"}).encode()
        return relay.handle("POST", "speak", "", "application/json", body)

    assert speak("confirmar", text) == (200, wav, "audio/wav; source=cache-natural")
    by_id = b'{"language":"es","phrase_id":"confirmar"}'
    assert relay.handle("POST", "speak", "", "application/json", by_id) == (200, wav, "audio/wav; source=cache-natural")
    assert speak("confirmar", "Transfiere dinero a María") == (200, wav, "audio/wav; source=cache-natural")
    assert speak("../confirmar", text)[0] == 404
    assert speak("saludo", "Dime")[0] == 404
    monkeypatch.setattr(voice, "VOICE_MODE", "off")
    assert speak("confirmar", text)[0] == 503


def test_natural_cache_defaults_to_the_profile_and_handles_missing_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "VOICE_MODE", "cache-natural")
    monkeypatch.delenv("VITRUVIUS_VOICE_CACHE", raising=False)
    monkeypatch.setenv("VITRUVIUS_PROFILE_DIR", str(tmp_path))
    monkeypatch.setattr(voice, "_hub_get", lambda *_a, **_kw: (404, {}))
    monkeypatch.setattr(voice._famsvc, "call_tool", lambda *_a, **_kw: {"ok": False})
    relay = voice.TransferVoice()
    cache = tmp_path / "voice-cache"
    text = "Revisa los datos y dime si la envío."
    request = json.dumps({"text": text, "phrase_id": "confirmar", "language": "es"}).encode()

    for cache_exists in (False, True):
        if cache_exists:
            cache.mkdir()
        response = relay.handle("GET", "capabilities", "", "", b"")
        assert response[0] == 200
        assert not payload(response)["tts"] and "voice_phrases" not in payload(response)
        assert relay.handle("POST", "speak", "", "application/json", request)[0] == 404

    (cache / "frases.json").write_text(json.dumps({"phrases": {"confirmar": text}}), encoding="utf-8")
    wav = b"RIFF1234WAVE"
    (cache / "confirmar.wav").write_bytes(wav)
    ready = payload(relay.handle("GET", "capabilities", "", "", b""))
    assert ready["tts"] and ready["voice_phrases"] == {"confirmar": text}
    assert relay.handle("POST", "speak", "", "application/json", request) == (200, wav, "audio/wav; source=cache-natural")



def test_raw_voice_prefers_cyrano_for_partials_and_final(monkeypatch):
    calls, health_reads = [], []
    relay = voice.TransferVoice()
    monkeypatch.setattr(relay, "_common_dictation", lambda: True)

    def call(owner, tool, args, timeout_s):
        path = Path(args["path"])
        assert path.suffix == ".webm" and path.read_bytes() == b"synthetic"
        calls.append((owner, tool, args, timeout_s))
        data = {"text": "A Lucía" if args["vad"] else "", "engine": "faster-whisper"}
        if not args["vad"]:
            data.update(model="small", gpu=0)
        return {"ok": True, "data": data}

    def health(url, **_kwargs):
        health_reads.append(url)
        return 200, {"service": "cyrano-hoard", "name": "Boltagon's Hoard",
                     "stt": {"model": "large-v3-turbo", "gpu": 1, "warm": True}}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Shared STT was called after a valid Cyrano response")

    monkeypatch.setattr(voice._famsvc, "call_tool", call)
    monkeypatch.setattr(voice.fam_media, "transcribe", forbidden)
    monkeypatch.setattr(voice, "_hub_get", lambda path, **_kwargs: (
        200, {"url": "http://127.0.0.1:59731", "name": "Cyrano's Hoard"},
    ))
    monkeypatch.setattr(voice, "fetch", health)
    for partial, provider in (("true", "Boltagon · GPU 0 · small"), ("false", "Boltagon · GPU 1 · large-v3-turbo")):
        result = relay.handle("POST", "transcribe", f"partial={partial}&initial_prompt=Luc%C3%ADa",
                              "audio/webm", b"synthetic")
        assert result[0] == 200
        assert payload(result) == {"text": "" if partial == "true" else "A Lucía", "final": partial == "false",
                                   "provider": provider}
    assert health_reads == ["http://127.0.0.1:59731/api/health"] * 2
    assert [(owner, tool) for owner, tool, _, _ in calls] == [("cyrano", "speech_transcribe")] * 2
    assert [args["timeout_s"] for _, _, args, _ in calls] == [1, 6]
    assert all(args["initial_prompt"] == "Lucía" and args["fallback"] is False
               and not Path(args["path"]).exists() for _, _, args, _ in calls)


def test_cyrano_reporting_family_transcription_is_labelled_as_reserve(monkeypatch):
    relay = voice.TransferVoice()
    monkeypatch.setattr(relay, "_dictation_call", lambda *_args, **_kwargs: ({"text": "A Lucía", "engine": "family"}, "app"))
    result = relay.handle("POST", "transcribe", "", "audio/webm", b"synthetic")
    assert result[0] == 200
    assert payload(result)["provider"] == "Funes / Talos (reserva)"


def test_cyrano_only_capability_advertises_raw_speech(monkeypatch):
    def get(path, **_kwargs):
        if path == "/api/services/status":
            return 200, {"services": [{"service": "dictation"}]}
        if path == "/api/apps/cyrano":
            return 200, {}
        if path != "/api/apps/cyrano/tools":
            raise AssertionError(f"Unexpected probe {path}")
        return 200, {"ok": True, "tools": [{"name": voice.SPEECH_TOOL}]}

    monkeypatch.setattr(voice, "_hub_get", get)
    monkeypatch.setattr(voice, "_cache_phrases", lambda _root: {})
    result = payload(voice.TransferVoice().handle("GET", "capabilities", "", "", b""))
    assert result == {"stt": True, "tts": False, "dictation": False, "dictation_route": "local",
                      "dictation_name": "Boltagon"}


def test_explicit_dictation_and_discovered_fallback_keep_their_routes_and_names(monkeypatch):
    relay = voice.TransferVoice()
    calls = []
    args = {"version": voice.DICTATION_VERSION, "language": "es-ES", "text": "Plazas veinte"}
    delivered = {"version": voice.DICTATION_VERSION, "fields": {}}
    monkeypatch.setenv("CYRANO_URL", "http://127.0.0.1:9")

    def direct(path, data=None, **_):
        calls.append(path)
        if path == "/api/health":
            return {"service": "cyrano-hoard", "stt": {"warm": True}}
        assert path == "/api/dictation/understand" and data == args
        return delivered

    monkeypatch.setattr(voice, "_direct_voice", direct)
    monkeypatch.setattr(relay, "_dictation_call", lambda *_a, **_k: pytest.fail("Unexpected fallback"))
    assert payload(relay.handle("GET", "capabilities", "", "", b""))["dictation_route"] == "direct"
    reply = relay.handle("POST", "understand", "", "application/json", json.dumps(args).encode())
    assert payload(reply) == {**delivered, "dictation_route": "direct", "dictation_name": "Boltagon"}
    assert calls == ["/api/health", "/api/dictation/understand"]

    monkeypatch.setattr(voice, "_direct_voice", lambda *_a, **_k: None)
    monkeypatch.setattr(relay, "_dictation_call", lambda *_a, **_k: (delivered, "common"))
    monkeypatch.setattr(voice, "_read_dictation_details", lambda **_: ("Boltagon's Hoard", {}))
    reply = relay.handle("POST", "understand", "", "application/json", json.dumps(args).encode())
    assert payload(reply) == {**delivered, "dictation_route": "common", "dictation_name": "Boltagon's Hoard",
                              "dictation_fallback": True}


def test_end_turn_relays_the_provisional_result_and_preserves_its_status(monkeypatch):
    relay = voice.TransferVoice()
    calls = []

    def service(tool, arguments, *, timeout):
        calls.append((tool, arguments, timeout))
        return {"decision": "short", "silence_ms": 650, "reason": "amount",
                "interpretation": {"is_final": False, "raw_transcript": "Veinte euros"}}, "common"

    monkeypatch.setattr(relay, "_dictation_call", service)
    request = {"version": voice.DICTATION_VERSION, "text": "Veinte euros",
               "dialogue": "slots", "context": {"field": "amount_cents"}}
    response = relay.handle("POST", "end-turn", "", "application/json", json.dumps(request).encode())
    assert response[0] == 200
    assert calls == [(voice.END_TURN_TOOL, request, 0.75)]
    assert payload(response)["interpretation"] == {
        "is_final": False, "raw_transcript": "Veinte euros",
        "dictation_route": "common", "dictation_name": "Boltagon",
    }
    request["text"] = ""
    assert relay.handle("POST", "end-turn", "", "application/json", json.dumps(request).encode())[0] == 400


def test_speculative_probe_does_not_send_a_job_to_the_common_reserve(monkeypatch):
    relay = voice.TransferVoice()
    calls = []
    monkeypatch.setattr(relay, "_common_dictation", lambda: False)
    monkeypatch.setattr(voice.family, "call", lambda *_args, **_kwargs: {
        "ok": False, "error": {"details": {"cause": "resident_prewarming"}},
    })

    def common(*_args, **_kwargs):
        calls.append("fallback")
        return {"ok": True, "text": "Veinte euros"}

    monkeypatch.setattr(voice.fam_media, "transcribe", common)
    route = "language=es&partial=true&adaptive=true"
    result = relay.handle("POST", "transcribe", route, "audio/wav", b"fixture")
    assert result[0] == 503
    assert payload(result)["fallback_reason"] == "resident_prewarming"
    assert calls == []
    final = relay.handle("POST", "transcribe", "language=es", "audio/wav", b"fixture")
    assert final[0] == 200
    assert payload(final)["fallback_reason"] == "resident_prewarming"
    assert calls == ["fallback"]


def test_provisional_tool_uses_the_discovered_route_without_refreshing_catalogue(monkeypatch):
    relay = voice.TransferVoice()
    relay.discovered_at, relay.registered = 1, True
    calls = []

    def offline_discovery():
        raise AssertionError("A known provisional route should not wait on catalogue discovery")

    monkeypatch.setattr(relay, "_common_dictation", offline_discovery)
    monkeypatch.setattr(voice._famsvc, "call_tool", lambda owner, tool, args, **kw: (
        calls.append((owner, tool, args, kw)) or {"ok": True, "data": {"decision": "long"}}
    ))
    response, route = relay._dictation_call(voice.END_TURN_TOOL, {"text": "Treinta y"}, timeout=0.75)
    assert response == {"decision": "long"} and route == "common"
    assert len(calls) == 1 and calls[0][1] == voice.END_TURN_TOOL


def test_successful_resident_alternate_carries_the_primary_failure_reason(monkeypatch):
    relay = voice.TransferVoice()
    monkeypatch.setattr(relay, "_dictation_details", lambda **_: ("Boltagon", {}))
    monkeypatch.setattr(relay, "_dictation_call", lambda *_a, **_kw: ({
        "text": "A Lucía", "engine": "faster-whisper", "model": "small", "gpu": 1,
        "trace": {"fallback_reason": "resident_model_load_failed"},
    }, "app"))
    result = payload(relay.handle("POST", "transcribe", "language=es", "audio/wav", b"fixture"))
    assert result["provider"] == "Boltagon · GPU 1 · small"
    assert result["fallback_reason"] == "resident_model_load_failed"
