import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from vitruvius_hoard.transfer_assistant.reply import NDJSON, VERSION, ReplyError, ReplyRelay
from vitruvius_hoard.transfer_assistant.voice import TransferVoice


JOB = "a" * 32
REQUEST = "b" * 32
ENGINE = "qwen3-tts"
ORIGIN = "http://127.0.0.1:9"


class Parts(httpx.SyncByteStream):
    def __iter__(self):
        yield b'{"type":"start"}\n'
        yield b'{"type":"end","cached":true}\n'


def mock_replies(handler, origin=ORIGIN):
    return ReplyRelay(lambda: origin, lambda **options: httpx.Client(
        transport=httpx.MockTransport(handler), **options,
    ))


def ticket(engine=ENGINE, stream_url=None):
    return {"version": VERSION, "job_id": JOB, "engine_id": engine,
            "stream_url": stream_url or f"/api/voice/jobs/{JOB}/stream"}


def request(text="Confirma 40 euros a María por la cena", language="es", **options):
    return json.dumps({"version": VERSION, "text": text, "language": language, **options},
                      ensure_ascii=False).encode()


@pytest.mark.parametrize(("language", "provider_lang"), [("es", "es-ES"), ("en", "en")])
def test_full_reply_uses_the_resident_cache_and_stream_in_the_same_voice(language, provider_lang):
    calls = []
    text = "Confirma 40 euros a María por la cena"

    def respond(message):
        calls.append((message.method, message.url.path))
        assert message.url.host == "127.0.0.1" and message.url.port == 9
        if message.method == "POST":
            assert json.loads(message.content) == {
                "version": VERSION, "text": text, "voice": "default", "lang": provider_lang,
                "speed": 1, "wait": False, "engine": ENGINE,
            }
            return httpx.Response(200, json=ticket())
        return httpx.Response(200, headers={"Content-Type": NDJSON}, stream=Parts())

    replies = mock_replies(respond)
    with TransferVoice(replies=replies).reply(request(text, language, engine=ENGINE)) as stream:
        assert (stream.job_id, stream.engine) == (JOB, ENGINE)
        packets = iter(stream.chunks)
        assert next(packets) == b'{"type":"start"}\n'
        assert list(packets) == [b'{"type":"end","cached":true}\n']
    assert calls == [("POST", "/api/voice/speak"), ("GET", f"/api/voice/jobs/{JOB}/stream")]
    assert not replies.active


@pytest.mark.parametrize("invalid", [
    b'{"version":"old","text":"Hola","language":"es"}', b'[]', b'not json',
    request(" "), request(language="it"), request(engine="invalid\r\nheader"), request("x" * 20001),
    request(request_id="not-a-client-id"),
])
def test_malformed_reply_does_not_contact_the_voice_worker(invalid):
    def unreachable(_request):
        pytest.fail("No voice request was expected")

    with pytest.raises(ReplyError) as error:
        TransferVoice(replies=mock_replies(unreachable)).reply(invalid)
    assert (error.value.code, error.value.status) == ("invalid_voice_request", 400)


@pytest.mark.parametrize("reply", [ticket(engine="other"), ticket(stream_url="http://remote.invalid/audio")])
def test_refuses_an_engine_change_or_redirect_and_cancels_its_job(reply):
    calls = []

    def respond(message):
        calls.append((message.method, message.url.path))
        return httpx.Response(200, json=reply if message.method == "POST" else {})

    relay = TransferVoice(replies=mock_replies(respond))
    with pytest.raises(ReplyError, match="tts_invalid_reply"):
        with relay.reply(request(engine=ENGINE)):
            pytest.fail("Unexpected stream")
    assert calls == [("POST", "/api/voice/speak"), ("DELETE", f"/api/voice/jobs/{JOB}")]


@pytest.mark.parametrize("ending", ["leave", "cancel", "close"])
def test_early_close_and_explicit_cancel_cancel_only_owned_jobs(ending):
    calls = []

    def respond(message):
        calls.append((message.method, message.url.path))
        if message.method == "GET":
            return httpx.Response(200, headers={"Content-Type": NDJSON}, stream=Parts())
        return httpx.Response(200, json=ticket())

    replies = mock_replies(respond)
    relay = TransferVoice(replies=replies)
    with relay.reply(request()) as stream:
        assert next(iter(stream.chunks)) == b'{"type":"start"}\n'
        assert relay.handle("DELETE", "reply/" + "f" * 32, "", "", b"")[0] == 200
        if ending == "cancel":
            assert relay.handle("DELETE", f"reply/{JOB}", "", "", b"")[0] == 200
        elif ending == "close":
            replies.close()
    assert calls == [("POST", "/api/voice/speak"), ("GET", f"/api/voice/jobs/{JOB}/stream"),
                     ("DELETE", f"/api/voice/jobs/{JOB}")]
    assert not replies.active


def test_provider_unavailable_returns_text_fallback_without_trying_another_voice():
    def refuse(message):
        raise httpx.ConnectError("closed test connection", request=message)

    relay = TransferVoice(replies=mock_replies(refuse))
    with pytest.raises(ReplyError) as error:
        with relay.reply(request()):
            pytest.fail("Unexpected stream")
    assert (error.value.code, error.value.status) == ("tts_unavailable", 503)


@pytest.mark.parametrize("blocked_method", ["POST", "GET"])
def test_cancel_by_client_id_while_the_browser_has_no_headers(blocked_method):
    blocked, release, cancelled = Event(), Event(), Event()
    calls = []

    def respond(message):
        calls.append((message.method, message.url.path))
        if message.method == blocked_method:
            blocked.set()
            assert release.wait(5), "double cleanup missed"
        if message.method == "POST":
            return httpx.Response(200, json=ticket())
        if message.method == "GET":
            return httpx.Response(200, headers={"Content-Type": NDJSON}, stream=Parts())
        assert message.url.path == f"/api/voice/jobs/{JOB}"
        cancelled.set()
        return httpx.Response(200, json={"ok": True})

    replies = mock_replies(respond)
    relay = TransferVoice(replies=replies)

    def serve_browser():
        with relay.reply(request(request_id=REQUEST)):
            pytest.fail("The browser should never receive the cancelled stream")

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(serve_browser)
        try:
            assert blocked.wait(3)
            assert relay.handle("DELETE", f"reply/request/{REQUEST}", "", "", b"")[0] == 200
            assert not replies.active
            assert cancelled.is_set() == (blocked_method == "GET")
        finally:
            release.set()
        with pytest.raises(ReplyError, match="tts_cancelled"):
            result.result(timeout=3)
    assert calls.count(("DELETE", f"/api/voice/jobs/{JOB}")) == 1
    assert cancelled.is_set()
    assert any(method == "GET" for method, _ in calls) == (blocked_method == "GET")


def test_cancel_can_arrive_before_the_post():
    def unreachable(_message):
        pytest.fail("The cancelled request should not reach the worker")

    replies = mock_replies(unreachable)
    relay = TransferVoice(replies=replies)
    assert relay.handle("DELETE", f"reply/request/{REQUEST}", "", "", b"")[0] == 200
    with pytest.raises(ReplyError, match="tts_cancelled"):
        with relay.reply(request(request_id=REQUEST)):
            pytest.fail("Unexpected stream")
    assert not replies.active
