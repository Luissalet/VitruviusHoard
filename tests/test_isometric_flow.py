"""Isometric diagrams through the tools, the store, the browser check and the HTTP routes."""

from __future__ import annotations

import pytest

from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.diagrams import Diagram
from vitruvius_hoard.diagrams.examples import CACHE, CHEST


def test_store_round_trip_keeps_the_pieces(services):
    out = call_tool(services, "diagram_render", {"diagram": CACHE})
    assert out["ok"] and out["type"] == "isometric" and out["files"]["light"].endswith("/light.svg")
    got = call_tool(services, "diagram_get", {"id": out["id"], "include_svg": True})
    again = Diagram.model_validate(got["diagram"])
    assert [p.id for p in again.pieces] == [p["id"] for p in CACHE["pieces"]] and again.pieces[10].plan.model_dump(exclude_none=True)
    assert got["svg"]["dark"] == out["svg"]["dark"] and got["type"] == "isometric"
    assert call_tool(services, "diagram_list", {})["diagrams"][0]["type"] == "isometric"


def test_tool_types_and_render_for_the_new_type(services):
    pick = call_tool(services, "diagram_types", {"intent": "explica cómo funciona una caché con un objeto"})
    assert pick["type"] == "isometric" and pick["card"]["example"]["pieces"]
    assert "isometric" in call_tool(services, "diagram_types", {})["types"]
    assert call_tool(services, "diagram_types", {"type": "isometric"})["pattern"] == "mechanism"
    out = call_tool(services, "diagram_render", {"diagram": pick["card"]["example"], "save": False, "modes": ["light"]})
    assert out["ok"] and list(out["svg"]) == ["light"]
    with pytest.raises(Exception, match=r"does not fit its type.*needs plan"):
        call_tool(services, "diagram_render", {"diagram": {"type": "isometric", "pieces": [{"id": "a", "plan": {"cx": 1}}]}})
    failing = call_tool(services, "diagram_render", {"diagram": {**CHEST, "pieces": [{**p, "lit": False} for p in CHEST["pieces"]]}, "save": False})
    assert not failing["ok"] and failing["failed"] == ["one_lit"] and "hint" in failing


def test_browser_check_captures_both_widths_in_light_and_dark(services):
    out = call_tool(services, "diagram_render", {"diagram": CACHE, "browser_check": True, "include_svg": False})
    browser = out["browser"]
    assert browser["widths"] == [1440, 390] and set(browser["renders"]) == {"light", "dark"} and browser["render_id"] == browser["renders"]["light"]
    calls = services.browser.calls[-2:]
    assert [c["widths"] for c in calls] == [[1440, 390], [1440, 390]] and [c["dark"] for c in calls] == [False, True]
    assert all("max-width:100%" in c["html"] and "<svg" in c["html"] for c in calls)      # fluid: no sideways scroll at 390
    assert len(browser["files"]) == 4
    plain = call_tool(services, "diagram_render", {"diagram": {"type": "timeline", "events": [{"when": "1", "label": "a"}]}, "browser_check": True})
    assert plain["browser"]["render_id"] and "widths" not in plain["browser"] and services.browser.calls[-1]["widths"] == [1280]


def test_http_routes_accept_and_serve_the_isometric_type(client):
    made = client.post("/api/diagrams", json={"diagram": CACHE})
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["ok"] and body["type"] == "isometric"
    svg = client.get(f"/api/diagrams/{body['id']}/dark.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml") and "FIG 3" in svg.text
    types = client.get("/api/diagrams/types").json()
    assert "isometric" in types["types"] and types["patterns"]["mechanism"]["types"] == ["isometric"]
    assert client.get("/api/diagrams/types", params={"intent": "how it works"}).json()["type"] == "isometric"
    assert client.get("/api/diagrams/types", params={"type": "isometric"}).json()["example"]["type"] == "isometric"
    bad = client.post("/api/diagrams", json={"diagram": {"type": "isometric", "pieces": []}})
    assert bad.status_code >= 400
    assert client.get("/api/diagrams").json()["diagrams"][0]["type"] == "isometric"
    assert client.delete(f"/api/diagrams/{body['id']}").json()["ok"]
