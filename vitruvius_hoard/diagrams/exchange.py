"""Editable interchange and rendering of a captured revision, without external apps."""
from copy import deepcopy
import json
import math
import xml.etree.ElementTree as ET

from .documents import normalize, document_layout
from .importers import load, _drawio_xml


def import_document(source, format="auto"):
    text = source.strip()
    if text.startswith("{"):
        parsed = json.loads(text)
        if parsed.get("format") == "vitruvius.diagram/1":
            return normalize(parsed["content"]), []
        if "diagram" in parsed:
            return normalize(parsed), []
        if "type" in parsed and "nodes" in parsed:
            return normalize({"diagram": parsed}), []
    if text.startswith('<'):
        root = ET.fromstring(text)
        pages = root.findall('./diagram') if root.tag == 'mxfile' else []
        if pages:
            from .editorial import import_pages
            content = import_pages(pages, source)
            ids = {n['id'] for n in content['diagram']['nodes']}
            # Cross-page semantic links have no visible connector on a draw.io page.
            # Retain them explicitly, never resurrect links to deleted objects.
            for cell in root.findall('./vitruviusLinks/edge'):
                edge = json.loads(cell.text or '{}')
                if edge.get('from') in ids and edge.get('to') in ids:
                    content['diagram']['edges'].append(edge)
            return normalize(content), ['Draw.io pages, text and raster images are imported; unsupported external styles are not preserved.']
    diagram = load(text, format)
    content = {"diagram": diagram.model_dump(by_alias=True), "source": source, "view": {"nodes": {}, "edges": {}}}
    warnings = ["The source is retained; unsupported style and shape data may not be represented."]
    if text.startswith("<") or format == "drawio":
        model = _drawio_xml(text)
        cells = {cell.get("id"): cell for cell in model.findall(".//mxCell")}
        def offset(cid, seen=None):
            seen = set() if seen is None else seen
            if cid in seen or cid not in cells:
                return 0, 0
            seen.add(cid)
            cell = cells[cid]
            geo = cell.find("mxGeometry")
            px, py = offset(cell.get("parent"), seen)
            return px + float(geo.get("x", 0) if geo is not None else 0), py + float(geo.get("y", 0) if geo is not None else 0)
        for node in diagram.nodes:
            cell = cells[node.id]
            geo = cell.find("mxGeometry")
            if geo is not None:
                x, y = offset(node.id)
                content["view"]["nodes"][node.id] = {"x": max(0, x), "y": max(0, y),
                    "width": max(24, float(geo.get("width", 176))), "height": max(24, float(geo.get("height", 64)))}
        original_edges = [cell for cell in cells.values() if cell.get("edge") == "1" and cell.get("source") in {n.id for n in diagram.nodes} and cell.get("target") in {n.id for n in diagram.nodes}]
        for edge, cell in zip(content["diagram"]["edges"], original_edges):
            edge["id"] = cell.get("id") or edge["id"]
            points = cell.findall('./mxGeometry/Array[@as="points"]/mxPoint')
            if points:
                content["view"]["edges"][edge["id"]] = {"points": [[float(p.get("x", 0)), float(p.get("y", 0))] for p in points]}
        identities = {cid: cell.get("vitruviusId", cid) for cid, cell in cells.items()}
        for node in content["diagram"]["nodes"]:
            original = node["id"]
            node["id"] = identities[original]
            node["group"] = identities.get(node["group"], node["group"])
            if original in content["view"]["nodes"]:
                content["view"]["nodes"][node["id"]] = content["view"]["nodes"].pop(original)
        for group in content["diagram"]["groups"]:
            group["id"] = identities[group["id"]]
        for edge in content["diagram"]["edges"]:
            original = edge["id"]
            edge["id"] = identities.get(original, original)
            edge["from"], edge["to"] = identities[edge["from"]], identities[edge["to"]]
            if original in content["view"]["edges"]:
                content["view"]["edges"][edge["id"]] = content["view"]["edges"].pop(original)
    return normalize(content), warnings


def drawio(row):
    content = row["content"]
    if content.get("view", {}).get("kind") == "infographic":
        from .editorial import ordered_pages, project
        file = ET.Element("mxfile")
        for page in ordered_pages(content):
            child = ET.SubElement(file, "diagram", id=page['id'], name=page.get('title', ''))
            model = ET.fromstring(drawio({'content': project(content, page)}))
            model.set('pageWidth', str(page['width']))
            model.set('pageHeight', str(page['height']))
            model.set('page', '1')
            child.append(model)
        links = ET.SubElement(file, 'vitruviusLinks')
        for edge in content['diagram']['edges']:
            if content['view']['nodes'][edge['from']]['page_id'] != content['view']['nodes'][edge['to']]['page_id']:
                ET.SubElement(links, 'edge').text = json.dumps(edge, ensure_ascii=False)
        return ET.tostring(file, encoding='unicode')
    d, lay = document_layout(content)
    from .spec import GRAPH_TYPES
    if d.type not in GRAPH_TYPES:
        raise ValueError("Editable draw.io export currently supports graph diagrams.")
    model = ET.Element("mxGraphModel")
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")
    frames = {frame.id: frame for frame in lay.frames}
    for group in d.groups:
        frame = frames.get(group.id)
        if frame:
            cell = ET.SubElement(root, "mxCell", id="g:" + group.id, vitruviusId=group.id, parent="1", value=group.label, vertex="1", style="swimlane;container=1;")
            ET.SubElement(cell, "mxGeometry", x=str(frame.x), y=str(frame.y), width=str(frame.w), height=str(frame.h), **{"as": "geometry"})
    shapes = {"diamond": "rhombus;", "cylinder": "shape=cylinder;", "round": "rounded=1;", "pill": "rounded=1;arcSize=50;"}
    for node in d.nodes:
        box = lay.boxes[node.id]
        frame = frames.get(node.group)
        style = content.get('view', {}).get('nodes', {}).get(node.id, {})
        extra = ''.join(f'{dest}={style[key]};' for key,dest in (('font_size','fontSize'),('font_weight','fontWeight'),('align','align'),('fill','fillColor'),('stroke','strokeColor'),('ink','fontColor')) if key in style)
        if not style.get('border', True):
            extra += 'strokeColor=none;fillColor=none;'
        if style.get('asset_id'):
            extra += 'shape=image;image=' + content['view']['assets'][style['asset_id']]['data'] + ';'
        if not style.get('show_label',True):
            extra += 'labelPosition=none;'
        cell = ET.SubElement(root, "mxCell", id="n:" + node.id, vitruviusId=node.id, parent="g:" + node.group if frame else "1", value=node.label, vertex="1", style=shapes.get(node.shape, "rounded=0;") + extra)
        ET.SubElement(cell, "mxGeometry", x=str(box.x - (frame.x if frame else 0)), y=str(box.y - (frame.y if frame else 0)), width=str(box.w), height=str(box.h), **{"as": "geometry"})
    for edge, route in zip(d.edges, lay.routes):
        cell = ET.SubElement(root, "mxCell", id="e:" + edge.id, vitruviusId=edge.id, parent="1", source="n:" + edge.source, target="n:" + edge.target, value=edge.label, edge="1", style="edgeStyle=orthogonalEdgeStyle;" + ("dashed=1;" if edge.style == "dashed" else ""))
        geometry = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
        points = ET.SubElement(geometry, "Array", **{"as": "points"})
        for x, y in route.points[1:-1]:
            ET.SubElement(points, "mxPoint", x=str(x), y=str(y))
    return ET.tostring(model, encoding="unicode")


def image(row, kind, mode="light"):
    """Render a frozen SVG directly; no network resources or model requests."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("Install the optional render package to export PNG/PDF.") from exc
    svg = row["rendering"]["svg"][mode]
    root = ET.fromstring(svg)
    width, height = (math.ceil(float(root.get(key))) for key in ("width", "height"))
    with sync_playwright() as runtime:
        browser = None
        failures = []
        for channel in ("msedge", "chrome", None):
            try:
                browser = runtime.chromium.launch(headless=True, **({"channel": channel} if channel else {}))
                break
            except Exception as error:
                failures.append(str(error).splitlines()[0])
        if browser is None:
            raise ValueError("No rendering browser is available: " + "; ".join(failures))
        try:
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.set_content('<!doctype html><meta charset="utf-8"><style>html,body{margin:0}svg{display:block}</style>' + svg)
            page.evaluate("document.fonts.ready")
            if kind == "png":
                return page.screenshot(full_page=True)
            pages = row['rendering'].get('pages')
            if pages:
                styles = ''.join(f'@page p{i}{{size:{p["width"]}px {p["height"]}px;margin:0}}.p{i}{{page:p{i};break-after:page;width:{p["width"]}px;height:{p["height"]}px}}' for i,p in enumerate(pages))
                body = ''.join(f'<section class="p{i}">{p["svg"][mode]}</section>' for i,p in enumerate(pages))
                page.set_content('<meta charset="utf-8"><style>html,body{margin:0}svg{display:block}'+styles+'</style>'+body)
                page.evaluate('document.fonts.ready')
                return page.pdf(prefer_css_page_size=True, print_background=True)
            return page.pdf(width=f"{width}px", height=f"{height}px", print_background=True, margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        finally:
            browser.close()


def mermaid(row):
    """Portable graph source. Manual geometry/styles remain in native JSON."""
    from .spec import GRAPH_TYPES
    d, _ = document_layout(row["content"])
    if d.type not in GRAPH_TYPES:
        raise ValueError("Mermaid graph export currently supports graph diagrams.")
    ids = {node.id: f"n{index}" for index, node in enumerate(d.nodes)}
    quote = lambda text: text.replace("&", "&amp;").replace('"', "&quot;").replace("\n", "<br/>")
    lines = [f"flowchart {d.direction}", "%% Layout, source identities and styles are retained in the native JSON export."]
    for node in d.nodes:
        label = '"' + quote(node.label) + '"'
        a, b = {"diamond": ("{", "}"), "pill": ("([", "])"), "cylinder": ("[(", "])")}.get(node.shape, ("[", "]"))
        lines.append(f"  {ids[node.id]}{a}{label}{b}")
    for edge in d.edges:
        arrow = "-.->" if edge.style == "dashed" else "-->"
        label = f'|"{quote(edge.label)}"|' if edge.label else ""
        lines.append(f"  {ids[edge.source]} {arrow}{label} {ids[edge.target]}")
    return "\n".join(lines) + "\n"
