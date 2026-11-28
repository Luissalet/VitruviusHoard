import asyncio
from concurrent.futures import Future
import json
from threading import Event
from types import SimpleNamespace

import httpx
import pytest

from hoard_link import LinkConfig
from vitruvius_hoard.software.global_models import GlobalLink
from vitruvius_hoard.transfer_assistant.form_extraction import understand_form
from vitruvius_hoard.transfer_assistant.voice import DICTATION_VERSION, TransferVoice
from vitruvius_hoard.transfer_assistant.voice_directory import VoiceCall


SCHEMA = {"type": "object", "required": ["persona", "franja"], "properties": {
    "persona": {"type": "string", "title": "Nombre", "maxLength": 30},
    "franja": {"type": "string", "title": "Hora", "enum": ["10:00", "12:00"]},
}}


class Rules:
    def __init__(self, fields=None):
        self.fields = fields or {}

    def app(self, _):
        return None

    def dictation(self, operation, args, **_):
        assert operation == "dictation_understand"
        return VoiceCall({"version": DICTATION_VERSION, "is_final": True, "fields": self.fields,
                          "changed": list(self.fields), "missing": [k for k in SCHEMA["required"] if k not in self.fields],
                          "ambiguous": []}, ms=4)


def turn(text, extract, *, rules=None, context=None, correction=False, route="form-understand"):
    relay = TransferVoice(directory=Rules(rules), replies=object(), form_chat=extract)
    body = {"version": DICTATION_VERSION, "schema": SCHEMA, "text": text,
            "context": context or {}, "correction": correction}
    status, result, _ = relay.handle("POST", route, "", "application/json", json.dumps(body).encode())
    assert status == 200
    return json.loads(result)


def proposal(value):
    def chat(messages, *, timeout, max_tokens):
        assert timeout == 3 and max_tokens <= 96
        payload = json.loads(messages[-1]["content"])
        assert "fields" in payload
        result = Future()
        result.set_result(SimpleNamespace(text=json.dumps(value), model="sample-model"))
        return result
    return chat


def test_model_proposes_literal_name_but_keeps_ambiguous_hours_open():
    result = turn("Apunta a Marta para el sabado por la manana", proposal({
        "persona": "Marta", "franja": ["10:00", "12:00", "09:00"], "bypass": True,
    }))
    assert result["fields"] == {"persona": {"value": "Marta", "quote": "Marta", "validation": "valid"}}
    assert result["ambiguous"] == [{"field": "franja", "candidates": ["10:00", "12:00"]}]
    assert result["missing"] == ["franja"]
    assert result["understanding_steps"][0] == {"method": "rules", "ms": 4}
    assert result["understanding_steps"][1]["outcome"] == "applied"


@pytest.mark.parametrize("text, answer, expected", [
    ("A las diez", {"franja": "10:00"}, "10:00"),
    ("A las nueve", {"franja": "09:00"}, None),
    ("El sábado por la mañana", {"franja": "10:00"}, None),
    ("A las 10:30", {"franja": "10:00"}, None),
    ("Apaga la luz", {"persona": "Marta", "franja": "10:00"}, None),
    ("Marta", {"persona": 12, "franja": "12:00"}, None),
])
def test_proposals_require_a_known_value_and_current_utterance_evidence(text, answer, expected):
    result = turn(text, proposal(answer))
    assert result["fields"].get("franja", {}).get("value") == expected
    assert "persona" not in result["fields"]


def test_rules_and_draft_values_are_preserved_and_only_the_target_can_be_corrected():
    existing = {"persona": {"value": "Marta", "quote": "Marta", "validation": "valid"}}
    result = turn("Marta, a las 10:00", proposal({"persona": "inventado", "franja": "10:00"}), rules=existing)
    assert result["fields"]["persona"] == existing["persona"]
    assert result["fields"]["franja"]["value"] == "10:00"

    result = turn("No, mejor el domingo", proposal({"persona": "domingo", "franja": "10:00"}), correction=True,
                  context={"draft": {"persona": "Marta", "franja": "10:00"}, "field": "franja"})
    assert result["fields"] == {}


def test_two_supported_options_remain_ambiguous_even_if_the_model_picks_one():
    result = turn("A las 10:00 o a las 12:00", proposal({"franja": "10:00"}))
    assert result["fields"] == {}
    assert result["ambiguous"] == [{"field": "franja", "candidates": ["10:00", "12:00"]}]


def test_timeout_retains_rules_and_legacy_understand_does_not_consult_model():
    def timeout(*_, **__):
        raise TimeoutError

    result = turn("Marta", timeout)
    assert result["missing"] == ["persona", "franja"]
    assert result["understanding_steps"][1]["outcome"] == "timeout"
    assert turn("Marta", None)["understanding_steps"][1]["outcome"] == "unavailable"
    assert "understanding_steps" not in turn("Marta", timeout, route="understand")


def test_complete_rules_cancel_the_model_already_started_in_parallel():
    started = Event()
    pending = Future()

    def submit(*_, **__):
        started.set()
        return pending

    def rules():
        assert started.wait(1)
        fields = {"persona": {"value": "Marta", "quote": "Marta", "validation": "valid"},
                  "franja": {"value": "10:00", "quote": "10:00", "validation": "valid"}}
        return Rules(fields).dictation("dictation_understand", {})

    result = understand_form(submit, rules, {"version": DICTATION_VERSION, "schema": SCHEMA}, "Marta a las 10:00")
    assert result.value["fields"]["franja"]["value"] == "10:00"
    assert result.value["understanding_steps"][1]["outcome"] == "superseded"
    assert pending.cancelled()


def test_complete_model_can_finish_before_rules_return():
    started, release = Event(), Event()

    def rules():
        started.set()
        assert release.wait(2)
        return Rules().dictation("dictation_understand", {})

    def submit(*args, **kwargs):
        assert started.wait(1)
        return proposal({"persona": "Marta", "franja": "10:00"})(*args, **kwargs)

    try:
        result = understand_form(submit, rules, {"version": DICTATION_VERSION, "schema": SCHEMA}, "Marta a las 10:00")
        assert result.value["missing"] == []
        assert result.value["understanding_steps"][0]["outcome"] == "superseded"
    finally:
        release.set()


@pytest.mark.asyncio
async def test_short_json_chat_pins_the_family_model_and_enforces_its_budget(monkeypatch):
    origin = "http://test.invalid"
    monkeypatch.setattr(LinkConfig, "faustus_candidates", lambda _: [origin])
    calls = []

    async def handler(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"endpoint_id": "family", "connection_revision": "8", "model": "picked",
                                             "chat_path": "/api/global-model/v1/chat/completions"})
        body = json.loads(request.content)
        assert (body["expected_endpoint_id"], body["expected_connection_revision"], body["model"]) == ("family", "8", "picked")
        assert body["max_tokens"] == 24 and not body["chat_template_kwargs"]["enable_thinking"]
        assert body["response_format"] == {"type": "json_object"}
        await asyncio.sleep(2)
        pytest.fail("The pending request should have been cancelled")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        link = GlobalLink(LinkConfig(faustus_urls=(origin,)), client=client)
        with pytest.raises(TimeoutError):
            await link.short_json_chat([{"role": "user", "content": "JSON"}], timeout=0.1, max_tokens=24)
    assert calls == ["GET", "POST"]
