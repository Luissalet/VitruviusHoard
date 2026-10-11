"""Bring diagrams drawn elsewhere into the diagram model so they can be redrawn with the brand: Mermaid (flowchart, sequence,
state, er, timeline, gantt), Excalidraw scenes (.excalidraw JSON) and draw.io files (plain or compressed XML).

Only structure is imported (boxes, labels, arrows, groups); positions and colours are dropped on purpose.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from datetime import date
from typing import Any

from .spec import Diagram

_SHAPES = [  # mermaid node syntax -> shape (longest openers first)
    ("([", "])", "pill"), ("((", "))", "round"), ("[(", ")]", "cylinder"), ("{{", "}}", "diamond"),
    ("[", "]", "box"), ("(", ")", "round"), ("{", "}", "diamond"), (">", "]", "box"),
]
_NODE = re.compile(r"^\s*([A-Za-z0-9_\-.]+)\s*(.*)$")
_ARROW = re.compile(r"\s*(-->|---|-\.->|==>|-.-|--x|--o|<-->)\s*(?:\|([^|]*)\|)?\s*")
_TEXT_ARROW = re.compile(r"\s*--\s+([^-][^>]*?)\s+-->\s*")


def _clean(label: str) -> str:
    return label.strip().strip('"').replace("<br>", " ").replace("<br/>", " ").strip()


def _parse_node(token: str, nodes: dict[str, dict], group: str) -> str:
    m = _NODE.match(token)
    if not m:
        raise ValueError(f"cannot read the node '{token.strip()}'")
    nid, rest = m.group(1), m.group(2).strip()
    node = nodes.setdefault(nid, {"id": nid, "label": nid})
    if group and not node.get("group"):
        node["group"] = group
    for opener, closer, shape in _SHAPES:
        if rest.startswith(opener) and rest.endswith(closer):
            node["label"] = _clean(rest[len(opener):len(rest) - len(closer)]) or nid
            node["shape"] = shape
            break
    return nid


def _flowchart(lines: list[str], header: str) -> dict:
    m = re.match(r"(?:graph|flowchart)\s+(TD|TB|BT|LR|RL)", header, re.I)
    direction = "LR" if m and m.group(1).upper() in ("LR", "RL") else "TB"
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    groups: list[dict] = []
    stack: list[str] = []
    for raw in lines:
        line = raw.split("%%")[0].strip().rstrip(";")
        if not line or line.startswith(("classDef", "class ", "style ", "linkStyle", "click ", "direction ")):
            continue
        sg = re.match(r"subgraph\s+([A-Za-z0-9_\-]+)?\s*(?:\[(.*)\])?\s*(.*)$", line)
        if sg:
            gid = sg.group(1) or f"group{len(groups) + 1}"
            groups.append({"id": gid, "label": _clean(sg.group(2) or sg.group(3) or gid)})
            stack.append(gid)
            continue
        if line == "end":
            if stack:
                stack.pop()
            continue
        group = stack[-1] if stack else ""
        line = _TEXT_ARROW.sub(lambda t: f" -->|{t.group(1)}| ", line)
        parts = _ARROW.split(line)
        # parts: node, arrow, label, node, arrow, label, node ...
        prev = None
        i = 0
        while i < len(parts):
            token = parts[i]
            ids = [_parse_node(t, nodes, group) for t in token.split("&") if t.strip()]
            if prev is not None:
                arrow, label = parts[i - 2], parts[i - 1]
                for a in prev:
                    for b in ids:
                        edges.append({"from": a, "to": b, "label": _clean(label or ""),
                                      "style": "dashed" if "." in arrow else "solid"})
            prev = ids
            i += 3
    kind = "architecture" if groups else "flowchart"
    return {"type": kind, "direction": direction, "nodes": list(nodes.values()), "edges": edges, "groups": groups}


def _sequence(lines: list[str]) -> dict:
    participants, messages = [], []
    alias: dict[str, str] = {}
    for raw in lines:
        line = raw.split("%%")[0].strip()
        if not line:
            continue
        m = re.match(r"(?:participant|actor)\s+(\S+)(?:\s+as\s+(.+))?$", line)
        if m:
            name = _clean(m.group(2) or m.group(1))
            alias[m.group(1)] = name
            participants.append(name)
            continue
        m = re.match(r"(\S+?)\s*(-->>|->>|-->|->|--x|-x|--\)|-\))\s*(\S+?)\s*:\s*(.*)$", line)
        if m:
            a, arrow, b, text = m.groups()
            messages.append({"from": alias.get(a, a), "to": alias.get(b, b), "label": _clean(text), "reply": arrow.startswith("--")})
    return {"type": "sequence", "participants": participants, "messages": messages}


def _state(lines: list[str]) -> dict:
    nodes: dict[str, dict] = {}
    edges = []
    for raw in lines:
        line = raw.split("%%")[0].strip()
        m = re.match(r"(\[\*\]|[A-Za-z0-9_]+)\s*-->\s*(\[\*\]|[A-Za-z0-9_]+)\s*(?::\s*(.*))?$", line)
        if not m:
            m2 = re.match(r"state\s+\"(.+)\"\s+as\s+([A-Za-z0-9_]+)", line)
            if m2:
                nodes.setdefault(m2.group(2), {"id": m2.group(2), "shape": "round"})["label"] = m2.group(1)
            continue
        a, b, label = m.groups()
        ids = []
        for i, s in enumerate((a, b)):
            if s == "[*]":
                sid = "start" if i == 0 else "end"
                nodes.setdefault(sid, {"id": sid, "label": "start" if sid == "start" else "end", "shape": "pill"})
            else:
                sid = s
                nodes.setdefault(sid, {"id": sid, "label": sid, "shape": "round"})
            ids.append(sid)
        edges.append({"from": ids[0], "to": ids[1], "label": _clean(label or "")})
    return {"type": "state", "nodes": list(nodes.values()), "edges": edges}


_CARD = {"||": "1", "|o": "0..1", "o|": "0..1", "}|": "1..n", "|{": "1..n", "}o": "0..n", "o{": "0..n"}


def _er(lines: list[str]) -> dict:
    nodes: dict[str, dict] = {}
    edges = []
    current = None
    for raw in lines:
        line = raw.split("%%")[0].strip()
        if not line:
            continue
        if current:
            if line == "}":
                current = None
                continue
            bits = line.split()
            if len(bits) >= 2:
                key = "pk" if "PK" in bits[2:] else "fk" if "FK" in bits[2:] else ""
                nodes[current]["fields"].append({"name": bits[1], "type": bits[0], "key": key})
            continue
        m = re.match(r"([A-Za-z0-9_\-]+)\s*\{$", line)
        if m:
            current = m.group(1)
            nodes.setdefault(current, {"id": current, "label": current, "fields": []})
            continue
        m = re.match(r"([A-Za-z0-9_\-]+)\s+([|}o][|o]|[|o][|{o])(?:--|\.\.)([|}o][|o]|[|o][|{o])\s+([A-Za-z0-9_\-]+)\s*:\s*(.*)$", line)
        if m:
            a, _left, right, b, label = m.groups()
            for n in (a, b):
                nodes.setdefault(n, {"id": n, "label": n, "fields": []})
            edges.append({"from": a, "to": b, "label": _clean(label), "cardinality": _CARD.get(right, "")})
    return {"type": "er", "nodes": list(nodes.values()), "edges": edges}


def _timeline(lines: list[str]) -> dict:
    events, title = [], ""
    for raw in lines:
        line = raw.strip()
        if line.startswith("title "):
            title = line[6:].strip()
            continue
        if ":" in line and not line.startswith("section"):
            when, _, rest = line.partition(":")
            for label in rest.split(":"):
                if label.strip():
                    events.append({"when": when.strip(), "label": label.strip()})
    return {"type": "timeline", "title": title, "events": events}


def _gantt(lines: list[str]) -> dict:
    tasks, lane, title, origin = [], "", "", None
    ends: dict[str, float] = {}
    for raw in lines:
        line = raw.split("%%")[0].strip()
        if not line or line.startswith(("dateFormat", "axisFormat", "excludes", "todayMarker")):
            continue
        if line.startswith("title "):
            title = line[6:].strip()
            continue
        if line.startswith("section "):
            lane = line[8:].strip()
            continue
        if ":" not in line:
            continue
        label, _, spec = line.partition(":")
        bits = [b.strip() for b in spec.split(",") if b.strip()]
        bits = [b for b in bits if b not in ("done", "active", "crit", "milestone")]
        tid = bits[0] if bits and not re.match(r"^\d{4}-\d{2}-\d{2}$|^after |^\d+[dhw]$", bits[0]) else ""
        rest = bits[1:] if tid else bits
        start = None
        if rest and rest[0].startswith("after "):
            start = max((ends.get(x, 0.0) for x in rest[0][6:].split()), default=0.0)
            rest = rest[1:]
        elif rest and re.match(r"^\d{4}-\d{2}-\d{2}$", rest[0]):
            day = date.fromisoformat(rest[0])
            origin = origin or day
            start = float((day - origin).days)
            rest = rest[1:]
        if start is None:
            start = tasks[-1]["end"] if tasks else 0.0
        dur = 1.0
        if rest:
            m = re.match(r"^(\d+(?:\.\d+)?)([dhw]?)$", rest[0])
            if m:
                dur = float(m.group(1)) * {"d": 1, "h": 1 / 24, "w": 7, "": 1}[m.group(2)]
            elif re.match(r"^\d{4}-\d{2}-\d{2}$", rest[0]) and origin:
                dur = max(0.0, (date.fromisoformat(rest[0]) - origin).days - start)
        task = {"id": tid, "label": label.strip(), "start": start, "end": start + dur, "lane": lane}
        tasks.append(task)
        if tid:
            ends[tid] = task["end"]
    return {"type": "gantt", "title": title, "tasks": tasks, "unit": "d"}


def from_mermaid(text: str) -> Diagram:
    lines = [ln for ln in (text or "").replace("\r", "").split("\n")]
    body = [ln for ln in lines if ln.strip() and not ln.strip().startswith("%%")]
    if not body:
        raise ValueError("the Mermaid text is empty")
    title = ""
    if body[0].strip() == "---":                           # front matter: title
        end = next((i for i in range(1, len(body)) if body[i].strip() == "---"), 0)
        for ln in body[1:end]:
            if ln.strip().startswith("title:"):
                title = ln.split(":", 1)[1].strip()
        body = body[end + 1:]
    header, rest = body[0].strip(), body[1:]
    head = header.split()[0].lower()
    if head in ("graph", "flowchart"):
        data = _flowchart(rest, header)
    elif head == "sequencediagram":
        data = _sequence(rest)
    elif head.startswith("statediagram"):
        data = _state(rest)
    elif head == "erdiagram":
        data = _er(rest)
    elif head == "timeline":
        data = _timeline(rest)
    elif head == "gantt":
        data = _gantt(rest)
    else:
        raise ValueError(f"Mermaid '{header.split()[0]}' is not supported: use flowchart, sequenceDiagram, stateDiagram, erDiagram, timeline or gantt")
    if title and not data.get("title"):
        data["title"] = title
    return Diagram.model_validate(data)


def from_excalidraw(scene: Any) -> Diagram:
    if isinstance(scene, str):
        scene = json.loads(scene)
    elements = [e for e in scene.get("elements", []) if not e.get("isDeleted")]
    by_id = {e["id"]: e for e in elements}
    texts: dict[str, str] = {}
    for e in elements:
        if e.get("type") == "text" and e.get("containerId"):
            texts[e["containerId"]] = e.get("text") or e.get("originalText") or ""
    shape = {"rectangle": "box", "ellipse": "round", "diamond": "diamond"}
    nodes, edges = [], []
    for e in elements:
        if e.get("type") in shape:
            nodes.append({"id": e["id"], "label": texts.get(e["id"], "").strip() or e["id"][:8], "shape": shape[e["type"]]})
    ids = {n["id"] for n in nodes}
    for e in elements:
        if e.get("type") == "arrow":
            a = (e.get("startBinding") or {}).get("elementId")
            b = (e.get("endBinding") or {}).get("elementId")
            if a in ids and b in ids:
                edges.append({"from": a, "to": b, "label": texts.get(e["id"], "").strip(),
                              "style": "dashed" if e.get("strokeStyle") in ("dashed", "dotted") else "solid"})
    if not nodes:
        raise ValueError("the Excalidraw scene has no rectangles, ellipses or diamonds")
    _ = by_id
    return Diagram.model_validate({"type": "flowchart", "nodes": nodes, "edges": edges})


def _drawio_xml(text: str) -> ET.Element:
    root = ET.fromstring(text)
    if root.tag == "mxGraphModel":
        return root
    diagram = root.find(".//diagram")
    if diagram is None:
        model = root.find(".//mxGraphModel")
        if model is None:
            raise ValueError("no diagram in the draw.io file")
        return model
    model = diagram.find("mxGraphModel")
    if model is not None:
        return model
    raw = (diagram.text or "").strip()
    inflated = zlib.decompress(base64.b64decode(raw), -15).decode("utf-8")
    return ET.fromstring(urllib.parse.unquote(inflated))


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def from_drawio(text: str) -> Diagram:
    model = _drawio_xml(text)
    cells = model.findall(".//mxCell")
    groups, nodes, edges = {}, [], []
    parents = {c.get("id"): c.get("parent") for c in cells}
    containers = {c.get("id") for c in cells if "container=1" in (c.get("style") or "") or "swimlane" in (c.get("style") or "")}
    for c in cells:
        style = c.get("style") or ""
        if c.get("vertex") == "1":
            cid = c.get("id")
            label = _strip_html(c.get("value") or "")
            if cid in containers:
                groups[cid] = {"id": cid, "label": label or cid}
                continue
            shp = "diamond" if "rhombus" in style else "cylinder" if "cylinder" in style else "round" if ("ellipse" in style or "rounded=1" in style) else "box"
            parent = parents.get(cid)
            nodes.append({"id": cid, "label": label or cid, "shape": shp, "group": parent if parent in containers else ""})
    ids = {n["id"] for n in nodes}
    for c in cells:
        if c.get("edge") == "1" and c.get("source") in ids and c.get("target") in ids:
            edges.append({"from": c.get("source"), "to": c.get("target"), "label": _strip_html(c.get("value") or ""),
                          "style": "dashed" if "dashed=1" in (c.get("style") or "") else "solid"})
    if not nodes:
        raise ValueError("the draw.io diagram has no shapes")
    kind = "architecture" if groups else "flowchart"
    return Diagram.model_validate({"type": kind, "nodes": nodes, "edges": edges, "groups": list(groups.values())})


def load(source: str, fmt: str = "auto") -> Diagram:
    """Any of the three formats; ``auto`` sniffs: JSON with elements = Excalidraw, XML = draw.io, otherwise Mermaid."""
    text = (source or "").strip()
    if fmt == "auto":
        fmt = "excalidraw" if text.startswith("{") and '"elements"' in text else "drawio" if text.startswith("<") else "mermaid"
    if fmt == "excalidraw":
        return from_excalidraw(text)
    if fmt == "drawio":
        return from_drawio(text)
    if fmt == "mermaid":
        return from_mermaid(text)
    raise ValueError(f"unknown format '{fmt}': use mermaid, excalidraw or drawio")
