"""The captured-render critique reports what finished within its model budget."""

import asyncio
import json
from pathlib import Path
from threading import Event
import time

import httpx

from hoard_link import LinkConfig
from vitruvius_hoard.agent_tools import call_tool, tool_catalog
from vitruvius_hoard.critique import DEFAULT_TIMEOUT_S
from vitruvius_hoard.software.global_models import GlobalLink


def test_confined_render_id_keeps_the_successful_vision_contract(services):
    class PromptRecorder:
        def chat(self, messages, *, images, effort, timeout):
            assert 0 < timeout <= DEFAULT_TIMEOUT_S
            assert images and effort == "high"
            return {"model": "fixture-vision", "text": '{"score": 9, "summary": "Visual feedback", "findings": []}'}

    services.link_sync = PromptRecorder()
    render = services.render(html="<main><h1>An owned render</h1></main>", widths=[390])
    report = call_tool(services, "design_critique", {"render_id": render["id"]})
    assert report["vision_model"] == "fixture-vision" and report["vision"] == {"status": "complete"}
    assert report["summary"] == "Visual feedback"
    assert report["score"] == round((report["heuristic_score"] + 9) / 2, 2)
    assert report["missing"] == [] and report["partial"] is False


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
    assert partial["partial"] is True and partial["missing"] == ["vision", "clean_review"]
    assert partial["review"]["status"] == "timed_out" and partial["review"]["verdict"] is None
    assert "use_vision=false" in partial["next_action"]["es"]
    assert deterministic["vision"] == {"status": "not_requested"} and deterministic["partial"] is False
    for key in ("score", "heuristic_score", "findings", "gate", "ship_ready", "rules_run"):
        assert partial[key] == deterministic[key], key


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
