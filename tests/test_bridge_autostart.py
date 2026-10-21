"""The incorporated MCP owner is cold and ignores retired autostart flags."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent


def load(monkeypatch, tmp_path):
    monkeypatch.setenv("VITRUVIUS_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("VITRUVIUS_BRIDGE_AUTOSTART", "1")
    spec = importlib.util.spec_from_file_location("vitruvius_bridge_under_test", ROOT / "mcp_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    token = tmp_path / "mcp-token"
    token.write_text("synthetic-token", encoding="utf8")
    monkeypatch.setattr(module, "token_path", lambda: token)
    return module


@pytest.mark.asyncio
async def test_discovery_never_calls_http_even_with_retired_autostart_enabled(monkeypatch, tmp_path):
    owner = load(monkeypatch, tmp_path)
    def unexpected(*args, **kwargs):
        pytest.fail("Discovery attempted HTTP")
    monkeypatch.setattr(owner, "HTTP_CLIENT", unexpected)
    tools = await owner.tools()
    assert len(tools) == 125
    assert {"diagram_document_save", "software_modules"} <= {tool.name for tool in tools}


@pytest.mark.asyncio
async def test_explicit_call_uses_the_configured_owner_and_native_envelope(monkeypatch, tmp_path):
    owner = load(monkeypatch, tmp_path)
    def respond(request):
        assert str(request.url) == "http://127.0.0.1:1/api/agent/call"
        assert request.headers["Authorization"] == "Bearer synthetic-token"
        assert json.loads(request.content) == {"name": "software_modules", "arguments": {}}
        return httpx.Response(200, json={"modules": [{"id": "design", "enabled": False}]})
    monkeypatch.setattr(owner, "HTTP_CLIENT", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs))
    result = await owner.call("software_modules", {})
    assert json.loads(result[0].text)["modules"][0]["enabled"] is False


@pytest.mark.asyncio
async def test_unavailable_owner_reports_failure_without_launching_an_app(monkeypatch, tmp_path):
    owner = load(monkeypatch, tmp_path)
    from vitruvius_hoard.hoard_link import launch
    monkeypatch.setattr(launch, "spawn_orphan", lambda *args, **kwargs: pytest.fail("MCP attempted autostart"))
    def unavailable(request):
        raise httpx.ConnectError("Synthetic owner unavailable", request=request)
    monkeypatch.setattr(owner, "HTTP_CLIENT", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(unavailable), **kwargs))
    result = await owner.call("software_modules", {})
    assert result.isError
    assert json.loads(result.content[0].text)["code"] == "vitruvius_unavailable"
