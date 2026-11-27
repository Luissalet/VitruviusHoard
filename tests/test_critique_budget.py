"""The captured-render critique reports what finished within its model budget."""

import asyncio
import json
from pathlib import Path
from threading import Event
import time

import httpx
import pytest

from hoard_link import LinkConfig
from vitruvius_hoard.agent_tools import call_tool, tool_catalog
from vitruvius_hoard.critique import DEFAULT_TIMEOUT_S
from vitruvius_hoard.software import global_models
from vitruvius_hoard.software.global_models import GlobalLink, global_job


def test_confined_render_id_keeps_the_successful_vision_contract(services):
    class PromptRecorder:
        def chat(self, messages, *, images, effort, timeout):
            assert 0 < timeout <= DEFAULT_TIMEOUT_S
            assert len(images) == 1 and effort == "high"
            return {"model": "fixture-vision", "text": '{"score": 9, "summary": "Visual feedback", "findings": []}'}

    services.link_sync = PromptRecorder()
    render = services.render(html="<main><h1>An owned render</h1></main>", widths=[390])
    report = call_tool(services, "design_critique", {"render_id": render["id"]})
    assert report["vision_model"] == "fixture-vision" and report["vision"] == {"status": "complete"}
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
    assert report["vision"] == {"status": "unavailable", "reason": "invalid_score"}
    assert report["vision_model"] is None and report["score_source"] == "heuristic"
    for key in ("score", "heuristic_score", "findings", "summary", "gate", "ship_ready"):
        assert report[key] == deterministic[key], key


def test_cutoff_returns_a_deterministic_report_and_cancels_the_model_request(services, monkeypatch):
    cancelled = Event()

    async def provider(request):
        if request.method == "GET":
            return httpx.Response(200, json={"endpoint_id": "fixture", "model": "fixture-vision", "connection_revision": "1",
                                             "vision": True, "chat_path": "/api/global-model/v1/chat/completions"})
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

    assert partial["vision"] == {"status": "timed_out"}
    assert partial["vision_model"] == "fixture-vision"
    assert partial["partial"] is True and partial["missing"] == ["vision", "clean_review"]
    assert partial["review"]["status"] == "timed_out" and partial["review"]["verdict"] is None
    assert "use_vision=false" in partial["next_action"]["es"]
    assert deterministic["vision"] == {"status": "not_requested"} and deterministic["partial"] is False
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
    assert report["vision"] == {"status": "unavailable", "reason": reason}
    assert report["vision_model"] is None and report["partial"]
    assert report["missing"] == ["vision", "clean_review"] and report["score_source"] == "heuristic"
    assert report["review"]["status"] == "unavailable" and report["review"]["reason"] == reason
    assert "use_vision=false" in report["next_action"]["es"]


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
