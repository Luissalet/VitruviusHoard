"""The captured-render critique reports what finished within its model budget."""

import asyncio
import io
import json
from pathlib import Path
from threading import Event
import time
import urllib.request

import httpx
import pytest

from hoard_link import LinkConfig, where
from vitruvius_hoard.agent_tools import call_tool, tool_catalog
from vitruvius_hoard.critique import DEFAULT_TIMEOUT_S
from vitruvius_hoard.software import global_models
from vitruvius_hoard.software.global_models import GlobalLink, global_job


def test_confined_render_id_keeps_the_successful_vision_contract(services):
    class PromptRecorder:
        def chat(self, messages, *, images, effort, max_tokens, timeout):
            assert 0 < timeout <= DEFAULT_TIMEOUT_S
            assert len(images) == 1 and effort == "off" and max_tokens == 768
            return {"model": "fixture-vision", "text": '{"score": 9, "summary": "Visual feedback", "findings": []}'}

    services.link_sync = PromptRecorder()
    render = services.render(html="<main><h1>An owned render</h1></main>", widths=[390])
    report = call_tool(services, "design_critique", {"render_id": render["id"]})
    assert report["vision_model"] == "fixture-vision"
    assert report["vision"] == {"status": "complete", "reason": None, "model": "fixture-vision"}
    assert report["summary"] == "Visual feedback"
    assert report["score"] == round((report["heuristic_score"] + 9) / 2, 2)
    assert report["score_source"] == "vision_blend"
    assert report["missing"] == [] and report["partial"] is False


@pytest.mark.parametrize("model_score", ["unrated", "NaN", "Infinity", -0.01, 10.01, True, None])
def test_invalid_visual_score_leaves_the_deterministic_report_unchanged(services, model_score):
    class UnratedVision:
        def chat(self, messages, **kwargs):
            return {"model": "fixture-vision", "text": json.dumps({
                "score": model_score, "summary": "Visual-only summary",
                "findings": [{"area": "typography", "title": "Visual-only finding", "severity": "warn"}],
            })}

    services.link_sync = UnratedVision()
    args = {"render_id": services.render(html="<h1>Captured page</h1>", widths=[390])["id"]}
    deterministic = call_tool(services, "design_critique", {**args, "use_vision": False})
    report = call_tool(services, "design_critique", args)
    assert report["partial"] is True and report["missing"] == ["vision"]
    assert report["vision"] == {"status": "unavailable", "reason": "invalid_score", "model": "fixture-vision"}
    assert report["vision_model"] == "fixture-vision" and report["score_source"] == "heuristic"
    for key in ("score", "heuristic_score", "findings", "summary", "gate", "ship_ready"):
        assert report[key] == deterministic[key], key


def test_cutoff_returns_a_deterministic_report_and_cancels_the_model_request(services, monkeypatch):
    cancelled = Event()

    async def provider(request):
        if request.method == "GET":
            return httpx.Response(200, json={"endpoint_id": "fixture", "model": "fixture-vision", "connection_revision": "1",
                                             "vision": True, "chat_path": "/api/global-model/v1/chat/completions"})
        body = json.loads(request.content)
        assert body["max_tokens"] == 768 and body["chat_template_kwargs"]["enable_thinking"] is False
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    origin = "http://vision-fixture.invalid"
    monkeypatch.setattr(LinkConfig, "faustus_origin", lambda config: origin)
    transport = httpx.MockTransport(provider)
    client = httpx.AsyncClient(transport=transport)
    link = GlobalLink(LinkConfig(faustus_urls=(origin,)), client=client)
    services.link_sync = link.sync
    render_id = services.render(html="<h1>Captured page</h1>", widths=[390])["id"]
    args = {"render_id": render_id}

    try:
        started = time.monotonic()
        partial = call_tool(services, "design_critique", {**args, "timeout_s": 1, "clean_review": True})
        assert time.monotonic() - started < 3
        assert cancelled.is_set()
        deterministic = call_tool(services, "design_critique", {**args, "use_vision": False})
    finally:
        link.sync.close()
        asyncio.run(client.aclose())

    assert partial["vision"] == {"status": "timed_out", "reason": "generation_timeout", "model": "fixture-vision"}
    assert partial["vision_model"] == "fixture-vision"
    assert partial["partial"] is True and partial["missing"] == ["vision", "clean_review"]
    assert partial["review"]["status"] == "timed_out" and partial["review"]["verdict"] is None
    assert all("render_id" in action and "timeout_s" in action for action in partial["next_action"].values())
    assert deterministic["vision"] == {"status": "not_requested", "reason": None, "model": None}
    assert deterministic["partial"] is False
    assert deterministic["score_source"] == "heuristic"
    for key in ("score", "heuristic_score", "score_source", "findings", "gate", "ship_ready", "rules_run"):
        assert partial[key] == deterministic[key], key



@pytest.mark.parametrize(("descriptor_ready", "reason"), [(True, "no_model"), (False, "resolution_timeout")])
def test_missing_vision_is_classified_before_generation(services, monkeypatch, descriptor_ready, reason):
    monkeypatch.setattr(global_models, "VISION_RESOLUTION_TIMEOUT_S", 0.1, raising=False)
    requests = []
    cancelled = Event()

    async def provider(request):
        requests.append(request.method)
        if request.method == "GET" and descriptor_ready:
            return httpx.Response(200, json={"endpoint_id": "text-only", "model": "fixture-text",
                                             "connection_revision": "1", "vision": False,
                                             "chat_path": "/api/global-model/v1/chat/completions"})
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    origin = "http://vision-fixture.invalid"
    monkeypatch.setattr(LinkConfig, "faustus_origin", lambda config: origin)
    client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    link = GlobalLink(LinkConfig(faustus_urls=(origin,)), client=client)
    services.link_sync = link.sync
    render = services.render(html="<h1>Captured page</h1>", widths=[390])
    try:
        with global_job():
            report = call_tool(services, "design_critique", {
                "render_id": render["id"], "timeout_s": 1, "clean_review": True,
            })
    finally:
        link.sync.close()
        asyncio.run(client.aclose())

    assert requests == ["GET"]
    assert cancelled.is_set() is not descriptor_ready
    assert report["vision"] == {"status": "unavailable", "reason": reason, "model": None}
    assert report["vision_model"] is None and report["partial"]
    assert report["missing"] == ["vision", "clean_review"] and report["score_source"] == "heuristic"
    assert report["review"]["status"] == "unavailable" and report["review"]["reason"] == reason
    assert all("render_id" in action and "use_vision=false" not in action for action in report["next_action"].values())


@pytest.mark.parametrize("route", ["default-loopbacks", "explicit-loopback", "blocked-spark", "both-ready"])
def test_cold_vision_resolution_prefers_healthy_origin(monkeypatch, route):
    hub = "http://hub-fixture.invalid"
    spark = "http://spark-fixture.invalid"
    defaults = LinkConfig(hub_url=hub)
    first_local = defaults.faustus_urls[0]
    config = LinkConfig(hub_url=hub, faustus_urls=(first_local,)) if route == "explicit-loopback" else defaults
    expected_origin = first_local if route in {"explicit-loopback", "blocked-spark"} else spark
    expected_model = "fixture-local" if expected_origin == first_local else "fixture-spark"
    probes = []

    class PlacementAndHealth:
        def open(self, request, timeout):
            url = request.full_url
            probes.append(url)
            if url == hub + "/api/placement":
                body = {"location": "sparks", "urls": {"faustus": spark}}
            elif url == spark + "/api/health" and route == "blocked-spark":
                time.sleep(min(timeout, 0.65))
                raise TimeoutError("Unresponsive advertised Spark")
            elif url in {origin + "/api/health" for origin in defaults.faustus_urls} and route == "default-loopbacks":
                time.sleep(0.3)
                raise TimeoutError("Slow implicit loopback")
            else:
                assert url in {origin + "/api/health" for origin in (*defaults.faustus_urls, spark)}
                body = {"status": "healthy"}
            response = io.BytesIO(json.dumps(body).encode())
            response.status = 200
            return response

    async def provider(request):
        assert request.method == "GET" and str(request.url) == expected_origin + "/api/global-model"
        return httpx.Response(200, json={"endpoint_id": "fixture", "model": expected_model,
                                         "connection_revision": "1", "vision": True,
                                         "chat_path": "/api/global-model/v1/chat/completions"})

    async def resolve_and_pin():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            link = GlobalLink(config, client=client)

            async def verify_selected_model(*args, **kwargs):
                return (await link.resolve("vision")).model

            monkeypatch.setattr(link, "chat", verify_selected_model)
            return await link.vision_chat([], images=[], effort="high", timeout=2)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: PlacementAndHealth())
    monkeypatch.setattr(global_models, "VISION_RESOLUTION_TIMEOUT_S", 0.5)
    where.forget()
    try:
        assert asyncio.run(resolve_and_pin()) == expected_model
    finally:
        where.forget()
    expected_probes = [hub + "/api/placement"]
    if route == "blocked-spark":
        expected_probes.append(spark + "/api/health")
    assert probes == [*expected_probes, expected_origin + "/api/health"]


def test_published_critique_schema_matches_the_native_tool():
    file = Path(__file__).resolve().parents[1] / "vitruvius_hoard" / "software" / "catalog.json"
    cold = next(tool for tool in json.loads(file.read_text(encoding="utf-8")) if tool["name"] == "design_critique")
    native = next(tool for tool in tool_catalog() if tool["name"] == "design_critique")
    assert cold["inputSchema"] == native["inputSchema"]
    assert cold["description"] == native["description"]


def test_native_http_critique_can_opt_into_the_budget(client):
    observed = []

    class PromptRecorder:
        def chat(self, messages, **kwargs):
            observed.append(kwargs.get("timeout"))
            return {"model": "fixture-vision", "text": '{"score": 9}'}

    client.svc.link_sync = PromptRecorder()
    render = client.svc.render(html="<h1>Captured page</h1>", widths=[390])
    route = f"/api/renders/{render['id']}/critique"
    for arguments in ({}, {"timeout_s": 2}):
        response = client.post(route, json=arguments)
        assert response.status_code == 200
        assert response.json()["vision"]["status"] == "complete"
    assert observed[0] is None
    assert 0 < observed[1] <= 2
