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
    result = turn("La invitada es Marta para el sabado por la manana", proposal({
        "persona": "Marta", "franja": ["10:00", "12:00", "09:00"], "bypass": True,
    }))
    assert result["fields"] == {"persona": {"value": "Marta", "quote": "Marta", "validation": "valid"}}
    assert result["ambiguous"] == [{"field": "franja", "candidates": ["10:00", "12:00"]}]
    assert result["missing"] == ["franja"]
    assert result["understanding_steps"][0]["method"] == "rules"
    assert result["understanding_steps"][0]["ms"] >= 4
    assert result["understanding_steps"][1]["outcome"] == "applied"


@pytest.mark.parametrize("text, answer, expected", [
    ("A las diez", {"franja": "10:00"}, "10:00"),
    ("A las nueve", {"franja": "09:00"}, None),
    ("El sábado por la mañana", {"franja": "10:00"}, None),
    ("A las 10:30", {"franja": "10:00"}, None),
    ("Apaga la luz", {"persona": "Marta", "franja": "10:00"}, None),
    ("La visitante es Marta", {"persona": 12, "franja": "12:00"}, None),
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

    result = turn("La visitante es Marta", timeout)
    assert result["missing"] == ["persona", "franja"]
    assert result["understanding_steps"][1]["outcome"] == "timeout"
    assert turn("La visitante es Marta", None)["understanding_steps"][1]["outcome"] == "unavailable"
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

    result = understand_form(submit, rules, {"version": DICTATION_VERSION, "schema": SCHEMA},
                             "La visitante es Marta y llegará a las 10:00")
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
        result = understand_form(submit, rules, {"version": DICTATION_VERSION, "schema": SCHEMA},
                                 "La visitante es Marta y llegará a las 10:00")
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


@pytest.mark.parametrize(("text", "person", "hour", "offers"), [
    ("Apunta a Marta para el sabado por la manana", "Marta", None, ["10:00", "12:00"]),
    ("Marta", "Marta", None, []),
    ("A las diez", None, "10:00", []),
    ("A las nueve", None, None, ["10:00", "12:00"]),
    ("Reserva a Lucía a las doce", "Lucía", "12:00", []),
    ("Apunta a Álvaro a las doce o a las diez", "Álvaro", None, ["10:00", "12:00"]),
])
def test_cold_local_rules_need_neither_remote_service(text, person, hour, offers):
    def untouched(*_, **__):
        pytest.fail("Locally resolved turn contacted a remote service")

    result = understand_form(untouched, untouched, {"version": DICTATION_VERSION, "schema": SCHEMA}, text).value
    assert result["fields"].get("persona", {}).get("value") == person
    assert result["fields"].get("franja", {}).get("value") == hour
    assert [item["candidates"] for item in result["ambiguous"]] == ([offers] if offers else [])
    assert [step["method"] for step in result["understanding_steps"]] == ["rules"]


@pytest.mark.parametrize(("text", "offers"), [
    ("No a las diez", ["12:00"]),
    ("Mejor no a las diez", ["12:00"]),
    ("A las diez no", ["12:00"]),
    ("Que no sea a las diez", ["12:00"]),
    ("No 10:00", ["12:00"]),
    ("No a las diez ni a las doce", []),
])
def test_rejected_hours_stay_empty_and_are_not_offered(text, offers):
    def untouched(*_, **__):
        pytest.fail("A rejected hour should be resolved locally")

    result = turn(text, untouched, context={"draft": {"persona": "Marta"}, "field": "franja"})
    assert result["fields"] == {}
    assert result["missing"] == ["franja"]
    assert result["ambiguous"] == [{"field": "franja", "candidates": offers}]


@pytest.mark.parametrize(("text", "non_name"), [
    ("Nadie", "Nadie"),
    ("Nadie más", "Nadie más"),
    ("No apuntes a nadie", "nadie"),
    ("Apunta a nadie", "nadie"),
    ("Apunta a Nadie", "Nadie"),
    ("Alguien", "Alguien"),
    ("Todos", "Todos"),
    ("Yo", "Yo"),
    ("Él", "Él"),
    ("Ella", "Ella"),
    ("Vale", "Vale"),
    ("Sí", "Sí"),
    ("No", "No"),
    ("Gracias", "Gracias"),
    ("Mañana", "Mañana"),
    ("Sábado", "Sábado"),
])
def test_person_field_rejects_non_names_even_when_upstream_marks_them_valid(text, non_name):
    result = turn(text, proposal({"persona": non_name}), rules={
        "persona": {"value": non_name, "quote": non_name, "validation": "valid"},
    })
    assert result["fields"] == {}
    assert "persona" in result["missing"]


def test_fallback_can_fill_the_name_without_reinstating_a_rejected_hour():
    result = turn("La invitada es Marta, pero no a las diez", proposal({"persona": "Marta", "franja": "10:00"}),
                  rules={"franja": {"value": "10:00", "quote": "a las diez", "validation": "valid"}})
    assert result["fields"] == {"persona": {"value": "Marta", "quote": "Marta", "validation": "valid"}}
    assert result["ambiguous"] == [{"field": "franja", "candidates": ["12:00"]}]


def test_a_positive_correction_can_supply_a_new_hour():
    result = turn("No, mejor a las doce", None, correction=True,
                  context={"draft": {"persona": "Marta", "franja": "10:00"}, "field": "franja"})
    assert result["fields"]["franja"]["value"] == "12:00"


@pytest.mark.parametrize(("text", "draft", "cleared", "missing", "alternatives"), [
    ("No a las diez", {"persona": "Marta", "franja": "10:00"}, {"franja": "10:00"}, ["franja"], ["12:00"]),
    ("A las diez no", {"persona": "Marta", "franja": "10:00"}, {"franja": "10:00"}, ["franja"], ["12:00"]),
    ("No a las diez", {"persona": "Marta"}, {}, ["franja"], ["12:00"]),
    ("No a las diez", {"persona": "Marta", "franja": "12:00"}, {}, [], None),
    ("No, Marta no", {"persona": "Marta", "franja": "10:00"}, {"persona": "Marta"}, ["persona"], None),
    ("No, Marta no", {"franja": "10:00"}, {}, ["persona"], None),
    ("No, Marta no", {"persona": "Marta"}, {"persona": "Marta"}, ["persona", "franja"], None),
])
def test_an_explicit_rejection_clears_only_the_rejected_draft_value(text, draft, cleared, missing, alternatives):
    def untouched(*_, **__):
        pytest.fail("An explicit rejection should be resolved locally")

    result = understand_form(untouched, untouched, {"version": DICTATION_VERSION, "schema": SCHEMA,
                                                   "context": {"draft": draft, "field": "franja"}}, text).value
    assert result.get("cleared", {}) == cleared
    assert result["fields"] == {}
    assert result["missing"] == missing
    assert result["ambiguous"] == ([] if alternatives is None else [{"field": "franja", "candidates": alternatives}])


def test_a_rejected_choice_can_be_named_by_the_forms_label():
    schema = {"type": "object", "required": ["visit"], "properties": {
        "visit": {"type": "string", "enum": ["am", "pm"]},
    }}
    context = {"draft": {"visit": "pm"}, "option_labels": {"visit": {"am": "Mañana", "pm": "Tarde"}}}

    def untouched(*_, **__):
        pytest.fail("The selected label should be rejected locally")

    result = understand_form(untouched, untouched, {"version": DICTATION_VERSION, "schema": schema,
                                                   "context": context}, "Tarde, no").value
    assert result["cleared"] == {"visit": "pm"}
    assert result["missing"] == ["visit"]
    assert result["ambiguous"] == [{"field": "visit", "candidates": ["am"]}]


def test_consecutive_rejections_exclude_both_choices_for_later_turns():
    def untouched(*_, **__):
        pytest.fail("Rejections and exhausted choices should be resolved locally")

    options = {"version": DICTATION_VERSION, "schema": SCHEMA}
    first = understand_form(untouched, untouched, {**options, "context": {
        "draft": {"persona": "Marta", "franja": "10:00"}, "last_changed": "franja",
    }}, "No a las diez").value
    assert first["rejected_options"] == {"franja": ["10:00"]}
    assert first["cleared"] == {"franja": "10:00"}

    context = {"draft": {"persona": "Marta"}, "field": "franja", "rejected_options": first["rejected_options"]}
    second = understand_form(untouched, untouched, {**options, "context": context}, "Tampoco a las doce").value
    assert second["rejected_options"] == {"franja": ["10:00", "12:00"]}
    assert second["fields"] == second["cleared"] == {}
    assert second["ambiguous"] == [{"field": "franja", "candidates": []}]

    repeated = understand_form(untouched, untouched, {**options, "context": {
        **context, "rejected_options": second["rejected_options"],
    }}, "A las diez").value
    assert repeated["fields"] == {}
    assert repeated["ambiguous"] == second["ambiguous"]


@pytest.mark.parametrize(("last_changed", "current", "other", "alternatives"), [
    ("franja", "10:00", "persona", [{"field": "franja", "candidates": ["12:00"]}]),
    ("persona", "Marta", "franja", []),
])
def test_implicit_rejection_clears_the_last_changed_value(last_changed, current, other, alternatives):
    def untouched(*_, **__):
        pytest.fail("A rejection of the last changed value should be resolved locally")

    result = understand_form(untouched, untouched, {"version": DICTATION_VERSION, "schema": SCHEMA, "context": {
        "draft": {"persona": "Marta", "franja": "10:00"},
        "field": other, "last_changed": last_changed,
    }}, "No, esa no").value
    assert result["cleared"] == {last_changed: current}
    assert result["fields"] == {}
    assert result["missing"] == [last_changed]
    assert result["ambiguous"] == alternatives
    assert [step["method"] for step in result["understanding_steps"]] == ["rules"]


def test_a_service_cannot_put_back_a_previously_rejected_choice():
    result = turn("Elijo la visita a las diez, a nombre de Marta", proposal({"persona": "Marta", "franja": "10:00"}),
                  rules={"franja": {"value": "10:00", "quote": "a las diez", "validation": "valid"}},
                  context={"rejected_options": {"franja": ["10:00"], "unrecognised": ["anything"]}})
    assert "franja" not in result["fields"]
    assert result["ambiguous"] == [{"field": "franja", "candidates": ["12:00"]}]
    assert result["rejected_options"] == {"franja": ["10:00"]}


def test_spoken_booking_details_are_grounded_in_the_actual_form_options():
    schema = {"type": "object", "required": ["concert", "date", "seats", "group_name"], "properties": {
        "concert": {"type": "string", "enum": ["aurora", "bruma"]},
        "date": {"type": "string", "format": "date"},
        "seats": {"type": "integer", "title": "Plazas", "minimum": 1, "maximum": 100},
        "group_name": {"type": "string", "title": "Nombre del grupo", "maxLength": 80},
    }}
    labels = {"concert": {"aurora": "Aurora · 15 de diciembre", "bruma": "Bruma · 20 de diciembre"},
              "date": {"2026-12-15": "Martes 15 de diciembre", "2026-12-20": "Domingo 20 de diciembre"}}

    def untouched(*_, **__):
        pytest.fail("The booking details should be understood without the model")

    options = {"version": DICTATION_VERSION, "schema": schema, "context": {"option_labels": labels}}
    first = understand_form(untouched, untouched, options,
                            "Vamos de parte del Coro de la Vega. Preferimos la función del domingo veinte de diciembre.").value
    draft = {key: field["value"] for key, field in first["fields"].items()}
    assert draft == {"concert": "bruma", "date": "2026-12-20", "group_name": "Coro de la Vega"}
    assert first["missing"] == ["seats"]
    options["context"]["draft"] = draft
    second = understand_form(untouched, untouched, options, "Contad con cuarenta personas de nuestro coro.").value
    assert second["fields"]["seats"]["value"] == 40
    assert second["missing"] == []


@pytest.mark.asyncio
async def test_streaming_short_chat_returns_at_complete_json_and_drains_the_socket(monkeypatch):
    origin = "http://test.invalid"
    def unexpected_placement(_):
        pytest.fail("An explicitly configured healthy origin must not wait for placement")

    monkeypatch.setattr(LinkConfig, "faustus_candidates", unexpected_placement)
    release_tail = asyncio.Event()
    drained = asyncio.Event()

    class Events(httpx.AsyncByteStream):
        async def __aiter__(self):
            for content in ('{"seats":', "40}"):
                event = json.dumps({"choices": [{"delta": {"content": content}}]})
                yield ("data: " + event + "\n\n").encode()
            await release_tail.wait()
            yield b"data: [DONE]\n\n"
            drained.set()

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"endpoint_id": "family", "connection_revision": "8", "model": "sample",
                                             "chat_path": "/api/global-model/v1/chat/completions"})
        payload = json.loads(request.content)
        assert payload["stream"] and not payload["chat_template_kwargs"]["enable_thinking"]
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Events())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        link = GlobalLink(LinkConfig(faustus_urls=(origin,)), client=client)
        try:
            result = await link.short_json_chat([{"role": "user", "content": "JSON"}], timeout=1, max_tokens=16)
            assert json.loads(result.text) == {"seats": 40}
            assert not drained.is_set()
            release_tail.set()
            await asyncio.wait_for(drained.wait(), timeout=1)
        finally:
            await link.aclose()


@pytest.mark.asyncio
async def test_short_chat_uses_placement_when_an_explicit_origin_is_unavailable(monkeypatch):
    configured, published = "http://configured.invalid", "http://published.invalid"
    order = []
    def placement(_):
        order.append("placement")
        return [configured, published]

    monkeypatch.setattr(LinkConfig, "faustus_candidates", placement)

    def handler(request):
        order.append(str(request.url))
        if request.url.host == "configured.invalid":
            return httpx.Response(503)
        return httpx.Response(200, json={"endpoint_id": "family", "connection_revision": "8", "model": "sample",
                                         "chat_path": "/api/global-model/v1/chat/completions"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        link = GlobalLink(LinkConfig(faustus_urls=(configured,)), client=client)
        assert (await link._prepared_short_selection())["base"] == published
    assert order == [configured + "/api/global-model", "placement", published + "/api/global-model"]


@pytest.mark.asyncio
async def test_preparing_once_reuses_descriptor_and_discards_a_stale_revision(monkeypatch):
    origin = "http://test.invalid"
    monkeypatch.setattr(LinkConfig, "faustus_candidates", lambda _: [origin])
    requests = []
    revision = "8"

    def handler(request):
        requests.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"endpoint_id": "family", "connection_revision": revision,
                                             "model": "picked", "chat_path": "/api/global-model/v1/chat/completions"})
        if json.loads(request.content)["expected_connection_revision"] != revision:
            return httpx.Response(409, json={"code": "stale"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        link = GlobalLink(LinkConfig(faustus_urls=(origin,)), client=client)
        await asyncio.gather(link._prepared_short_selection(), link._prepared_short_selection())
        assert requests == ["GET"]
        messages = [{"role": "user", "content": "JSON"}]
        await link.short_json_chat(messages, timeout=1, max_tokens=20)
        revision = "9"
        with pytest.raises(httpx.HTTPStatusError):
            await link.short_json_chat(messages, timeout=1, max_tokens=20)
        await link.short_json_chat(messages, timeout=1, max_tokens=20)
    assert requests == ["GET", "POST", "POST", "GET", "POST"]
