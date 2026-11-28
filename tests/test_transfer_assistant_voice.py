from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Event

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vitruvius_hoard.hoard_link.agentkit import make_agent_router
from vitruvius_hoard.transfer_assistant import ASSETS, ENTRY, assistant_assets
from vitruvius_hoard.transfer_assistant import voice, voice_directory, voice_trace


ORIGIN = "http://127.0.0.1:59731"
TRACE_ID = "123456789abcdeff123456789abcdeff"
JSON = "application/json"


def payload(response):
    return json.loads(response[1])


def post(relay, route, **body):
    return relay.handle("POST", route, f"trace={TRACE_ID}", JSON, json.dumps(body).encode())


def test_exposed_sources_can_be_saved_as_project_assets():
    result = assistant_assets()
    assert ENTRY in result["files"]
    assert {Path(path).name for path in result["files"]} == set(ASSETS)
    assert ENTRY in result["script"] and "data-transfer-assistant" in result["mount"]


@pytest.fixture
def loopback(monkeypatch, tmp_path):
    monkeypatch.delenv("CYRANO_URL", raising=False)
    token = tmp_path / "mcp-token"
    token.write_text("fixture", encoding="ascii")
    reads, calls = [], []
    reject_discovery = Event()
    tools = {
        "/api/agent/tools": lambda: {
            "tools": [{"name": name} for name in sorted(voice.DICTATION_TOOLS | {voice.SPEECH_TOOL, voice.END_TURN_TOOL})],
        },
        "/api/speech/transcribe": lambda: {
            "text": "Cuarenta", "engine": "faster-whisper", "model": "large-v3-turbo", "gpu": 2,
        },
        "/api/dictation/understand": lambda: {
            "version": voice.DICTATION_VERSION, "raw_transcript": "Cuarenta", "is_final": True,
        },
        "/api/dictation/end-turn": lambda: {
            "decision": "short", "silence_ms": 650, "interpretation": {"is_final": False},
        },
    }

    def discover():
        if reject_discovery.is_set():
            raise AssertionError("A healthy turn must not consult the Hub")
        reads.append("directory")
        return [{"id": "cyrano", "url": ORIGIN, "name": "cyrano"},
                {"id": "funes", "url": "http://localhost:59732", "token_file": str(token)},
                {"id": "prospero", "url": "http://[::1]:59733", "token_file": str(token)}]

    def request(url, path, **kwargs):
        calls.append((url, path, kwargs))
        if path == "/api/agent/tools" and url != ORIGIN:
            return httpx.Response(200, json={"tools": [
                {"name": "transcribe_file"} if url.endswith(":59732") else {"name": "voice_tts"}
            ]})
        value = tools[path]()
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)

    monkeypatch.setattr(voice_directory, "_hub_apps", discover)
    monkeypatch.setattr(voice_directory, "_request", request)
    monkeypatch.setattr(voice, "_cache_phrases", lambda _: {})
    return voice.TransferVoice(), reads, calls, tools, reject_discovery


def test_first_typed_turn_discovers_voice_without_a_capabilities_request(loopback):
    relay, reads, calls, _, reject = loopback
    assert not reads and not calls

    first = post(relay, "understand", version=voice.DICTATION_VERSION,
                 text="Apunta a Marta para el sabado por la manana", schema={"type": "object"})
    assert first[0] == 200, payload(first)
    assert payload(first)["dictation_route"] == "direct"
    assert reads == ["directory"]
    assert [path for _, path, _ in calls] == ["/api/agent/tools"] * 3 + ["/api/dictation/understand"]

    reject.set()
    assert post(relay, "understand", version=voice.DICTATION_VERSION, text="Cuarenta")[0] == 200
    assert reads == ["directory"]


def test_concurrent_first_turns_share_the_initial_discovery(loopback, monkeypatch):
    relay, reads, calls, _, _ = loopback
    discover = voice_directory._hub_apps
    entered, release = Event(), Event()

    def delayed_discovery():
        entered.set()
        assert release.wait(3)
        return discover()

    monkeypatch.setattr(voice_directory, "_hub_apps", delayed_discovery)
    args = {"version": voice.DICTATION_VERSION, "text": "Cuarenta"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post, relay, "understand", **args)
        try:
            assert entered.wait(1)
            second = pool.submit(post, relay, "understand", **args)
            with pytest.raises(TimeoutError):
                second.result(timeout=0.1)
        finally:
            release.set()
        assert first.result(timeout=2)[0] == second.result(timeout=2)[0] == 200
    assert reads == ["directory"]
    assert [path for _, path, _ in calls].count("/api/dictation/understand") == 2


def test_one_discovery_and_zero_hub_reads_during_typed_spoken_and_provisional_turns(loopback):
    relay, reads, calls, _, reject = loopback
    assert payload(relay.handle("GET", "capabilities", "", "", b"")) == {
        "stt": True, "tts": False, "dictation": True, "dictation_route": "direct",
        "dictation_name": "Boltagon", "adaptive_turn": True,
    }
    assert reads == ["directory"]
    assert [path for _, path, _ in calls] == ["/api/agent/tools"] * 3
    reject.set()
    assert relay.replies.origin() == ORIGIN
    assert relay.handle("GET", "capabilities", "", "", b"")[0] == 200

    for query in ("partial=true&adaptive=true&", ""):
        response = payload(relay.handle("POST", "transcribe", query + "trace=" + TRACE_ID, "audio/webm", b"test"))
        assert response["text"] == "Cuarenta"
        assert response["provider"] == "Boltagon · GPU 2 · large-v3-turbo"
        assert 0 <= response["timing"]["service_ms"] <= response["timing"]["gateway_ms"]
        sent = calls[-1][2]["arguments"]
        assert sent["audio"] == {"mime_type": "audio/webm", "data_base64": "dGVzdA=="}
        assert sent["fallback"] is False and "path" not in sent
    typed = post(relay, "understand", version=voice.DICTATION_VERSION, text="cuarenta",
                 schema={"type": "object"}, context={"field": "amount_cents"})
    assert typed[0] == 200 and payload(typed)["dictation_route"] == "direct"
    audio = {"mime_type": "audio/wav", "data_base64": "dGVzdA=="}
    assert post(relay, "understand", version=voice.DICTATION_VERSION, audio=audio)[0] == 200
    assert calls[-2][2]["arguments"]["audio"] == audio
    assert calls[-2][2]["arguments"]["fallback"] is False
    assert calls[-1][2]["arguments"]["text"] == "Cuarenta"
    provisional = post(relay, "end-turn", version=voice.DICTATION_VERSION, text="cuarenta", dialogue="slots")
    assert payload(provisional)["interpretation"]["is_final"] is False
    assert all(call[0] == ORIGIN and call[2]["trace"].startswith(TRACE_ID + "/") for call in calls[3:])
    assert reads == ["directory"]


def test_local_fallback_reason_only_when_the_direct_contract_fails(loopback):
    relay, _, _, tools, reject = loopback
    relay.directory.prepare()
    reject.set()

    def timeout():
        raise httpx.ReadTimeout("fixture")

    for double, reason in [
        (timeout, "boltagon_timeout"),
        (lambda: httpx.Response(404, json={}), "boltagon_contract_missing"),
        (lambda: httpx.Response(503, json={}), "boltagon_failed"),
        (lambda: {"text": "bad contract"}, "boltagon_contract_invalid"),
    ]:
        tools["/api/dictation/understand"] = double
        response = post(relay, "understand", version=voice.DICTATION_VERSION, text="Cuarenta")
        assert response[0] == 503 and payload(response)["code"] == reason


def test_refresh_does_not_hold_the_cached_route_or_wait_for_hub(loopback, monkeypatch):
    relay, _, calls, _, _ = loopback
    relay.directory.prepare()
    entered, release, completed = Event(), Event(), Event()

    def discovery():
        entered.set()
        assert release.wait(5)
        completed.set()
        return None

    monkeypatch.setattr(voice_directory, "_hub_apps", discovery)
    relay.directory._refresh_at = 0
    relay.directory.prepare()
    assert entered.wait(2)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            final = pool.submit(post, relay, "understand", version=voice.DICTATION_VERSION, text="cuarenta")
            assert final.result(timeout=1)[0] == 200
        assert calls[-1][0] == ORIGIN
    finally:
        release.set()
    assert completed.wait(2)


def test_partial_never_submits_to_the_reserve_and_final_can_use_it_directly(loopback):
    relay, _, calls, tools, reject = loopback
    relay.directory.prepare()
    reject.set()
    tools["/api/speech/transcribe"] = lambda: httpx.Response(
        503, json={"detail": {"trace": {"fallback_reason": "resident_queue_timeout"}}},
    )
    requests = []

    def transcribe(name, arguments):
        requests.append((name, arguments))
        if name == "transcribe_file":
            assert Path(arguments["path"]).read_bytes() == b"test"
            return {"job_id": "once", "status": "queued"}
        assert name == "transcribe_status" and arguments["job_id"] == "once"
        return {"job_id": "once", "status": "done", "text": "Reserva"}

    app = FastAPI()
    app.include_router(make_agent_router(tools_fn=lambda: [], call_fn=transcribe, token_fn=lambda: "fixture",
                                         instructions="", app_name="funes", skills=False))
    native = TestClient(app)

    def reserve():
        url, path, options = calls[-1]
        assert url == "http://localhost:59732"
        return native.post(path, json=options["arguments"], headers={"Authorization": "Bearer " + options["token"]})

    tools["/api/agent/call"] = reserve
    response = relay.handle("POST", "transcribe", "partial=true&adaptive=true", "audio/wav", b"test")
    assert response[0] == 503
    assert not requests
    response = relay.handle("POST", "transcribe", "", "audio/wav", b"test")
    assert response[0] == 200
    assert payload(response)["provider"] == voice.FAMILY_TRANSCRIPTION
    assert payload(response)["fallback_reason"] == "resident_queue_timeout"
    assert [name for name, _ in requests] == ["transcribe_file", "transcribe_status"]
    assert not Path(requests[0][1]["path"]).exists()


def test_resident_silence_does_not_launch_a_duplicate_and_preserves_alternate_details(loopback):
    relay, _, calls, tools, _ = loopback
    relay.directory.prepare()
    tools["/api/speech/transcribe"] = lambda: {"text": "", "model": "small", "gpu": 2,
                                               "trace": {"fallback_reason": "resident_model_load_failed"}}
    result = payload(relay.handle("POST", "transcribe", "", "audio/webm", b"test"))
    assert result["text"] == "" and result["provider"] == "Boltagon · GPU 2 · small"
    assert result["fallback_reason"] == "resident_model_load_failed"
    assert [path for _, path, _ in calls[3:]] == ["/api/speech/transcribe"]


def test_override_ignores_a_discovered_token_and_rejects_remote_origin(loopback, monkeypatch):
    _, _, calls, _, _ = loopback
    monkeypatch.setenv("CYRANO_URL", "http://example.test:8810")
    relay = voice.TransferVoice()
    assert post(relay, "understand", version=voice.DICTATION_VERSION, text="cuarenta")[0] == 503
    assert all(not url.startswith("http://example.test") for url, *_ in calls)


def test_piper_and_legacy_cache_keep_their_public_route(loopback, monkeypatch, tmp_path):
    relay, _, calls, tools, _ = loopback
    relay.directory.prepare()
    phrases = {"confirmar": "¿Confirmas la transferencia?"}
    monkeypatch.setattr(voice, "_cache_phrases", lambda _: phrases)
    monkeypatch.setenv("VITRUVIUS_VOICE_CACHE", str(tmp_path))
    wav = b"RIFF1234WAVE"
    path = tmp_path / "confirmar.wav"
    path.write_bytes(wav)
    monkeypatch.setattr(voice, "VOICE_MODE", "cache-natural")
    assert post(relay, "speak", phrase_id="confirmar") == (200, wav, "audio/wav; source=cache-natural")
    assert post(relay, "speak", phrase_id="../confirmar")[0] == 404
    monkeypatch.setattr(voice, "VOICE_MODE", "piper")
    tools["/api/agent/call"] = lambda: {"result": {"path": str(path)}}
    assert post(relay, "speak", phrase_id="confirmar") == (200, wav, "audio/wav")
    url, route, request = calls[-1]
    assert (url, route) == ("http://[::1]:59733", "/api/agent/call")
    assert request["arguments"] == {"name": "voice_tts", "arguments": {
        "text": phrases["confirmar"], "lang": "es", "voice": voice.SPANISH_TTS_VOICE, "engine": "piper",
    }}
    tools["/api/agent/call"] = lambda: {"result": {"error": "generation is OFF"}}
    assert post(relay, "speak", phrase_id="confirmar")[0] == 409


@pytest.mark.parametrize(("route", "args", "status"), [
    ("understand", {"version": "0", "text": "test"}, 400),
    ("understand", {"version": voice.DICTATION_VERSION, "audio": {"mime_type": "audio/wav", "data_base64": "?"}}, 400),
    ("end-turn", {"version": voice.DICTATION_VERSION, "text": "", "dialogue": "slots"}, 400),
    ("speak", {"language": "zz"}, 400),
])
def test_input_validation_is_local(route, args, status):
    assert post(voice.TransferVoice(), route, **args)[0] == status


def test_turn_trace_enqueues_without_waiting_and_limits_metadata(monkeypatch):
    monkeypatch.setattr(voice_trace.family, "status", lambda: {"enabled": True})
    entered, release, sent = Event(), Event(), []

    def send(batch):
        entered.set()
        assert release.wait(5)
        sent.extend(batch)

    tracer = voice_trace.TurnTrace(send=send)
    relay = voice.TransferVoice(tracer=tracer)
    try:
        response = post(relay, "trace", trace_id=TRACE_ID, ignored="private",
                        stages=[["voice.turn", 100, 900, "ok"], ["voice.transcribe", 100.2, 300, "ok"]])
        assert response[0] == 202 and payload(response)["queued"]
        assert entered.wait(1) and not sent
        assert not payload(post(relay, "trace", trace_id=TRACE_ID,
                                stages=[["private transcript", 100, 900, "ok"]]))["queued"]
    finally:
        release.set()
    tracer.queue.join()
    root, child = sent
    assert root["parent_id"] is None and child["parent_id"] == root["span_id"]
    assert root["trace_id"] == child["trace_id"] == TRACE_ID
    assert (child["caller"], child["callee"], child["operation"], child["duration_ms"]) == (
        "vitruvius", "cyrano", "voice.transcribe", 300,
    )
    assert "private" not in repr(sent)
