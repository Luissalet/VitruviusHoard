"""Diagrams: type picking, layout and routing gates on every type, brand profiles, importers, tools and HTTP routes."""

from __future__ import annotations

import base64
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zlib

import pytest

from vitruvius_hoard.agent_tools import TOOLS_BY_NAME, call_tool
from vitruvius_hoard.diagrams import CARDS, Diagram, make, pick_type, type_card
from vitruvius_hoard.diagrams.brand import from_folder, from_probe
from vitruvius_hoard.diagrams.importers import from_drawio, from_excalidraw, from_mermaid, load
from vitruvius_hoard.diagrams.layout import layered
from vitruvius_hoard.diagrams.render import DEFAULT, gates, layout_of
from vitruvius_hoard.tokens import contrast_ratio

CHECKOUT = {"type": "flowchart", "title": "Checkout", "nodes": [
    {"id": "s", "label": "Start", "shape": "pill"}, {"id": "cart", "label": "Review cart"},
    {"id": "logged", "label": "Signed in?", "shape": "diamond"}, {"id": "login", "label": "Sign in or continue as guest"},
    {"id": "addr", "label": "Shipping address"}, {"id": "pay", "label": "Payment"},
    {"id": "ok", "label": "Payment accepted?", "shape": "diamond"}, {"id": "retry", "label": "Show error and retry"},
    {"id": "done", "label": "Order confirmed", "shape": "pill"}],
    "edges": [{"from": "s", "to": "cart"}, {"from": "cart", "to": "logged"}, {"from": "logged", "to": "login", "label": "no"},
              {"from": "logged", "to": "addr", "label": "yes"}, {"from": "login", "to": "addr"}, {"from": "addr", "to": "pay"},
              {"from": "pay", "to": "ok"}, {"from": "ok", "to": "done", "label": "yes"}, {"from": "ok", "to": "retry", "label": "no"},
              {"from": "retry", "to": "pay"}, {"from": "cart", "to": "done", "label": "empty", "style": "dashed"}]}
ARCH = {"type": "architecture", "direction": "LR", "groups": [{"id": "pc", "label": "PC"}, {"id": "sp", "label": "Cluster"}],
        "nodes": [{"id": "ui", "label": "Studio"}, {"id": "f", "label": "API", "group": "pc"}, {"id": "hub", "label": "Hub", "group": "pc"},
                  {"id": "db", "label": "SQLite", "group": "pc", "shape": "cylinder"}, {"id": "llm", "label": "Model server", "group": "sp"},
                  {"id": "q", "label": "Small model", "group": "sp"}],
        "edges": [{"from": "ui", "to": "f", "label": "HTTP"}, {"from": "f", "to": "db"}, {"from": "f", "to": "hub"},
                  {"from": "f", "to": "llm", "label": "chat"}, {"from": "hub", "to": "q"}]}


def failed(result):
    return [g for g in result["gates"] if not g["ok"]]


@pytest.mark.parametrize("kind", sorted(CARDS))
def test_every_card_example_draws_clean_in_both_modes(kind):
    card = type_card(kind)
    assert card["pattern"] and card["fields"] and card["rules"]
    result = make(Diagram.model_validate(card["example"]))
    assert result["ok"], failed(result)
    for mode in ("light", "dark"):
        svg = result["svg"][mode]
        ET.fromstring(svg)                                      # well-formed
        assert DEFAULT[mode]["paper"] in svg and 'role="img"' in svg


@pytest.mark.parametrize("spec", [CHECKOUT, ARCH, {**CHECKOUT, "direction": "LR"}], ids=["flow-tb", "arch-lr", "flow-lr"])
def test_bigger_graphs_pass_every_geometry_gate(spec):
    result = make(Diagram.model_validate(spec))
    assert result["ok"], failed(result)


def test_layered_routes_are_orthogonal_and_long_edges_avoid_boxes():
    lay = layered(Diagram.model_validate(CHECKOUT))
    for r in lay.routes:
        for (x0, y0), (x1, y1) in zip(r.points, r.points[1:]):
            assert abs(x0 - x1) < 0.01 or abs(y0 - y1) < 0.01, r
    empty = next(r for r in lay.routes if r.label == "empty")
    assert len(empty.points) >= 4                            # the long dashed edge bends around, not through, the middle boxes


def test_architecture_groups_hold_only_their_members():
    lay = layout_of(Diagram.model_validate(ARCH))
    frames = {f.id: f for f in lay.frames}
    assert set(frames) == {"pc", "sp"} and set(frames["pc"].members) == {"f", "hub", "db"}
    assert next(g for g in gates(Diagram.model_validate(ARCH), {"light": DEFAULT["light"], "dark": DEFAULT["dark"]}, lay)
                if g["id"] == "groups_hold_only_members")["ok"]


def test_gates_catch_bad_contrast_and_forced_overlap():
    d = Diagram.model_validate(type_card("flowchart")["example"])
    bad = {"light": {**DEFAULT["light"], "ink": "#dddddd"}, "dark": DEFAULT["dark"]}
    result = make(d, bad)
    assert "contrast_light" in result["failed"] and "ink/paper" in next(g for g in result["gates"] if g["id"] == "contrast_light")["detail"]
    lay = layout_of(d)
    a, b = list(lay.boxes.values())[:2]
    b.x, b.y = a.x, a.y
    ids = [g["id"] for g in gates(d, {"light": DEFAULT["light"], "dark": DEFAULT["dark"]}, lay) if not g["ok"]]
    assert "no_overlap" in ids


def test_validation_explains_what_is_wrong():
    with pytest.raises(ValueError, match="unknown nodes: z"):
        Diagram.model_validate({"type": "flowchart", "nodes": [{"id": "a"}], "edges": [{"from": "a", "to": "z"}]})
    with pytest.raises(ValueError, match="appears twice"):
        Diagram.model_validate({"type": "flowchart", "nodes": [{"id": "a"}, {"id": "a"}]})
    with pytest.raises(ValueError, match="needs messages"):
        Diagram.model_validate({"type": "sequence"})


def test_pick_type_goes_pattern_first():
    assert pick_type("diagrama de secuencia del login con la API")["type"] == "sequence"
    assert pick_type("architecture of the services and databases")["type"] == "architecture"
    assert pick_type("roadmap del Q3 con duraciones")["type"] == "gantt"
    assert pick_type("tablas y relaciones de la base de datos")["type"] == "er"
    vague = pick_type("algo bonito")
    assert vague["type"] == "flowchart" and not vague["matched"]


def test_mermaid_flowchart_with_labels_subgraph_and_shapes():
    d = from_mermaid("flowchart LR\n  A[Write code] --> B{Tests pass?}\n  B -->|yes| C([Merge])\n  B -- no --> A\n"
                     "  subgraph ci [CI]\n  B\n  end\n  C -.-> D[(Store)]")
    assert d.type == "architecture" and d.direction == "LR"
    nodes = {n.id: n for n in d.nodes}
    assert nodes["B"].shape == "diamond" and nodes["C"].shape == "pill" and nodes["D"].shape == "cylinder"
    assert nodes["B"].group == "ci" and d.groups[0].label == "CI"
    labels = {(e.source, e.target): (e.label, e.style) for e in d.edges}
    assert labels[("B", "C")] == ("yes", "solid") and labels[("B", "A")] == ("no", "solid") and labels[("C", "D")][1] == "dashed"
    assert make(d)["ok"]


def test_mermaid_sequence_state_er_timeline_gantt():
    seq = from_mermaid("sequenceDiagram\n participant U as User\n U->>API: GET /x\n API-->>U: 200")
    assert seq.participants == ["User", "API"] and seq.messages[1].reply
    st = from_mermaid("stateDiagram-v2\n [*] --> Draft\n Draft --> Sent : submit\n Sent --> [*]")
    assert {n.id for n in st.nodes} == {"start", "Draft", "Sent", "end"} and st.edges[1].label == "submit"
    er = from_mermaid("erDiagram\n USER ||--o{ ORDER : places\n USER {\n string id PK\n string email\n }")
    user = next(n for n in er.nodes if n.id == "USER")
    assert user.fields[0].key == "pk" and er.edges[0].cardinality == "0..n"
    tl = from_mermaid("timeline\n title History\n 2024 : Prototype\n 2025 : Launch : Funding")
    assert tl.title == "History" and len(tl.events) == 3
    g = from_mermaid("gantt\n dateFormat YYYY-MM-DD\n section Dev\n Build :a1, 2026-01-01, 10d\n Test :after a1, 5d")
    assert [(t.start, t.end, t.lane) for t in g.tasks] == [(0.0, 10.0, "Dev"), (10.0, 15.0, "Dev")]
    for d in (seq, st, er, tl, g):
        assert make(d)["ok"], (d.type, failed(make(d)))
    with pytest.raises(ValueError, match="not supported"):
        from_mermaid("pie\n \"a\" : 1")


def test_excalidraw_and_drawio_imports():
    scene = {"elements": [
        {"id": "r1", "type": "rectangle"}, {"id": "t1", "type": "text", "containerId": "r1", "text": "Inbox"},
        {"id": "r2", "type": "diamond"}, {"id": "t2", "type": "text", "containerId": "r2", "text": "Spam?"},
        {"id": "a1", "type": "arrow", "startBinding": {"elementId": "r1"}, "endBinding": {"elementId": "r2"}, "strokeStyle": "dashed"},
        {"id": "gone", "type": "rectangle", "isDeleted": True}]}
    d = from_excalidraw(json.dumps(scene))
    assert [(n.label, n.shape) for n in d.nodes] == [("Inbox", "box"), ("Spam?", "diamond")] and d.edges[0].style == "dashed"
    xml = ('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
           '<mxCell id="g" value="Backend" style="swimlane;container=1" vertex="1" parent="1"/>'
           '<mxCell id="a" value="&lt;b&gt;API&lt;/b&gt;" style="rounded=1" vertex="1" parent="g"/>'
           '<mxCell id="b" value="DB" style="shape=cylinder" vertex="1" parent="1"/>'
           '<mxCell id="e" value="SQL" edge="1" source="a" target="b" parent="1"/></root></mxGraphModel>')
    d2 = from_drawio(xml)
    assert d2.type == "architecture" and {n.id: (n.label, n.group) for n in d2.nodes} == {"a": ("API", "g"), "b": ("DB", "")}
    raw = urllib.parse.quote(xml)
    deflate = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = base64.b64encode(deflate.compress(raw.encode()) + deflate.flush()).decode()
    d3 = load(f'<mxfile><diagram id="x" name="p">{packed}</diagram></mxfile>')
    assert {n.id for n in d3.nodes} == {"a", "b"} and d3.edges[0].label == "SQL"
    assert load(json.dumps(scene)).nodes[0].label == "Inbox"


def test_brand_from_site_probe_and_folder(tmp_path):
    probe = {"colors": [{"color": "rgb(30,30,40)", "background": "rgb(250,248,240)", "count": 40},
                        {"color": "rgb(255,255,255)", "background": "rgb(200,40,90)", "count": 5}],
             "contrast_pairs": [{"color": "rgb(30,30,40)", "background": "rgb(250,248,240)", "text": "long body text here"},
                                {"color": "rgb(110,110,120)", "background": "rgb(250,248,240)", "text": "caption"}],
             "fonts": {"p": "Lora, serif"}}
    prof = from_probe(probe, "Shop")
    light = prof["light"]
    assert light["paper"] == "#faf8f0" and light["ink"] == "#1e1e28" and prof["font"] == "Lora, serif"
    assert contrast_ratio(light["accent"], light["paper"]) >= 3 and contrast_ratio(light["muted"], light["paper"]) >= 4.5
    assert contrast_ratio(prof["dark"]["accent"], prof["dark"]["paper"]) >= 3
    css = tmp_path / "theme.css"
    css.write_text(":root { --background: #ffffff; --foreground: #0f172a; --primary: #0ea5e9; --border: #94a3b8; }\n"
                   ".dark { --background: #020617; --foreground: #f8fafc; --primary: #38bdf8; }", encoding="utf-8")
    fp = from_folder(tmp_path, "Site")
    assert fp["light"]["paper"] == "#ffffff" and fp["light"]["ink"] == "#0f172a" and fp["dark"]["paper"] == "#020617"
    assert contrast_ratio(fp["light"]["accent"], "#ffffff") >= 3
    with pytest.raises(LookupError):
        from_folder(tmp_path / "missing")


def test_tools_end_to_end(services, tmp_path):
    for name in ("diagram_types", "diagram_render", "diagram_get", "diagram_list", "diagram_delete", "diagram_brand_onboard",
                 "diagram_brands", "diagram_brand_delete"):
        assert name in TOOLS_BY_NAME
    pick = call_tool(services, "diagram_types", {"intent": "quién hace cada paso del proceso de devoluciones"})
    assert pick["type"] == "swimlane" and pick["card"]["example"]
    assert set(call_tool(services, "diagram_types", {})["types"]) == set(CARDS)
    out = call_tool(services, "diagram_render", {"diagram": CHECKOUT, "browser_check": True})
    assert out["ok"] and re.fullmatch(r"[0-9a-f]{12}", out["id"]) and out["files"]["dark"].endswith("/dark.svg")
    assert out["svg"]["light"].startswith("<svg") and out["browser"]["render_id"]
    assert "<svg" in services.browser.calls[-1]["html"]
    got = call_tool(services, "diagram_get", {"id": out["id"], "include_svg": True})
    assert got["diagram"]["type"] == "flowchart" and got["svg"]["light"] == out["svg"]["light"]
    assert call_tool(services, "diagram_list", {})["diagrams"][0]["id"] == out["id"]
    mer = call_tool(services, "diagram_render", {"source": "sequenceDiagram\n A->>B: hi", "modes": ["dark"], "include_svg": False})
    assert mer["type"] == "sequence" and set(mer["files"]) == {"dark"} and "svg" not in mer
    brand = call_tool(services, "diagram_brand_onboard", {"name": "Acme", "colors": {"accent": "#c2185b", "paper": "#fffdf7"}})
    assert brand["profile"] == "acme" and all(g["ok"] for g in brand["contrast"])
    styled = call_tool(services, "diagram_render", {"diagram": ARCH, "profile": "Acme", "save": False})
    assert "#c2185b" in styled["svg"]["light"] and "#fffdf7" in styled["svg"]["light"] and "id" not in styled
    site = call_tool(services, "diagram_brand_onboard", {"name": "Site", "url": "https://example.com"})
    assert site["source"] == "url:https://example.com" and services.browser.calls[-1]["url"] == "https://example.com"
    tokens = services.tokens_generate({"name": "Marea", "base_color": "#006bbd"})
    by_tokens = call_tool(services, "diagram_render", {"diagram": ARCH, "profile": tokens["id"], "include_svg": False})
    assert by_tokens["profile"] == f"tokens:{tokens['id']}"
    assert {p["profile"] for p in call_tool(services, "diagram_brands", {})["profiles"]} == {"acme", "site"}
    assert call_tool(services, "diagram_brand_delete", {"name": "Site"})["ok"]
    assert call_tool(services, "diagram_delete", {"id": out["id"]})["ok"]
    with pytest.raises(Exception):
        call_tool(services, "diagram_get", {"id": out["id"]})
    with pytest.raises(Exception, match="Unknown profile"):
        call_tool(services, "diagram_render", {"diagram": ARCH, "profile": "nope"})
    with pytest.raises(Exception, match="does not fit its type"):
        call_tool(services, "diagram_render", {"diagram": {"type": "flowchart", "nodes": [{"id": "a"}], "edges": [{"from": "a", "to": "b"}]}})


def test_http_routes(client):
    made = client.post("/api/diagrams", json={"diagram": ARCH})
    assert made.status_code == 201, made.text
    did = made.json()["id"]
    svg = client.get(f"/api/diagrams/{did}/light.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml") and svg.text.startswith("<svg")
    assert client.get(f"/api/diagrams/{did}").json()["type"] == "architecture"
    assert client.get("/api/diagrams").json()["count"] == 1
    assert client.get("/api/diagrams/types", params={"intent": "timeline of releases"}).json()["type"] == "timeline"
    assert client.post("/api/diagrams/brands", json={"name": "Blue", "colors": {"accent": "#1d4ed8"}}).status_code == 201
    assert client.get("/api/diagrams/brands").json()["profiles"][0]["profile"] == "blue"
    assert client.delete("/api/diagrams/brands/blue").json()["ok"]
    assert client.get(f"/api/diagrams/{did}/sepia.svg").status_code == 404
    assert client.get("/api/diagrams/zzzzzzzzzzzz").status_code == 404
    assert client.delete(f"/api/diagrams/{did}").json()["ok"]
