"""SVG drawing with brand tokens, plus the gates that check the drawing before anyone looks at it.

A *profile* is the colour roles of one mode: ``paper`` (background), ``ink`` (text), ``muted`` (secondary text and lines),
``accent`` (arrows, highlights), ``surface`` (box fill), ``border`` and ``series`` (lanes, bars, groups). It comes from a stored
design system (``tokens.roles_of``), from colours given inline, or from the neutral default below.

Gates are deterministic: contrast (text 4.5:1 on paper and on box fills, lines and accent 3:1), boxes that overlap, edges
that cross a box they do not belong to, labels wider than their box, group frames that enclose a foreign box, and anything
outside the canvas.
"""

from __future__ import annotations

from html import escape
from typing import Any, Optional

from ..tokens import contrast_ratio, roles_of
from .layout import FONT, LINE_H, MARGIN, PAD_X, PAD_Y, Box, Layout, layered, swimlane, text_width
from . import isometric
from .spec import Diagram

DEFAULT = {
    "light": {"paper": "#ffffff", "ink": "#1d2433", "muted": "#5b6474", "accent": "#2f5bd3", "surface": "#f3f5f9",
              "border": "#8a94a6", "series": ["#2f5bd3", "#b4541f", "#2a7d4f", "#8a3fb0", "#9a6a00", "#c0325a"]},
    "dark": {"paper": "#11151c", "ink": "#e8ecf3", "muted": "#a5afc0", "accent": "#86a8ff", "surface": "#1b212c",
             "border": "#6b768a", "series": ["#86a8ff", "#f0a36b", "#6cc895", "#c79bf0", "#e7c56a", "#f08aa5"]},
}
FONT_STACK = "Inter, 'Segoe UI', system-ui, -apple-system, sans-serif"
ROLE_KEYS = ("paper", "ink", "muted", "accent", "surface", "border")


def profile_from_tokens(tokens: dict[str, Any]) -> dict[str, dict]:
    """Diagram roles for light and dark from a stored design system."""
    roles = roles_of(tokens)
    out: dict[str, dict] = {"name": roles.get("name", ""), "font": (roles.get("fonts") or {}).get("body") or FONT_STACK}
    for mode in ("light", "dark"):
        r = roles.get(mode)
        if not r:
            out[mode] = dict(DEFAULT[mode])
            continue
        out[mode] = {"paper": r["background"], "ink": r["text"], "muted": r["muted"], "accent": r["accent"],
                     "surface": r["surface2"], "border": r["border"],
                     "series": [r["accent"], r["accent2"], *DEFAULT[mode]["series"][2:]]}
    return out


def profile_from_colors(colors: dict[str, Any], base: Optional[dict] = None) -> dict[str, dict]:
    """Inline roles: ``{"light": {"accent": "#..."}, "dark": {...}}`` or a flat dict applied to light; missing roles fall back."""
    base = base or {"light": DEFAULT["light"], "dark": DEFAULT["dark"]}
    out: dict[str, Any] = {"name": colors.get("name", "custom"), "font": colors.get("font") or base.get("font") or FONT_STACK}
    flat = {k: v for k, v in colors.items() if k in ROLE_KEYS or k == "series"}
    for mode in ("light", "dark"):
        given = colors.get(mode) or (flat if mode == "light" else {})
        out[mode] = {**base[mode], **{k: v for k, v in given.items() if k in ROLE_KEYS or k == "series"}}
    return out


# ------------------------------------------------------------------------------------------------ simple layouts
def _sequence(d: Diagram) -> dict[str, Any]:
    col_w = max(140.0, *(text_width(p) + 2 * PAD_X for p in d.participants))
    gaps = [max(60.0, text_width(m.label, FONT - 1) + 40) for m in d.messages if m.source != m.target]
    col_gap = max([col_w + 40] + [g for g in gaps])
    head_h = LINE_H + 2 * PAD_Y
    title_h = 36.0 if d.title else 0.0
    xs = {p: MARGIN + col_w / 2 + i * col_gap for i, p in enumerate(d.participants)}
    y = MARGIN + title_h + head_h + 30
    rows = []
    for m in d.messages:
        rows.append({"from": xs[m.source], "to": xs[m.target], "y": y, "label": m.label, "reply": m.reply, "self": m.source == m.target})
        y += 52 if m.source == m.target else 40
    width = MARGIN * 2 + col_w + col_gap * (len(d.participants) - 1)
    if d.title:
        width = max(width, text_width(d.title, FONT + 5) + 2 * MARGIN)
    return {"xs": xs, "col_w": col_w, "head_h": head_h, "rows": rows, "end_y": y, "width": width,
            "height": y + head_h + MARGIN, "title_h": title_h}


def _timeline(d: Diagram) -> dict[str, Any]:
    step = max(130.0, *(min(text_width(e.label, FONT - 1), 200) + 30 for e in d.events))
    title_h = 36.0 if d.title else 0.0
    axis_y = MARGIN + title_h + 90
    xs = [MARGIN + 60 + i * step for i in range(len(d.events))]
    width = (xs[-1] if xs else MARGIN) + 60 + MARGIN
    if d.title:
        width = max(width, text_width(d.title, FONT + 5) + 2 * MARGIN)
    return {"axis_y": axis_y, "xs": xs, "width": width, "height": axis_y + 90 + MARGIN, "title_h": title_h, "step": step}


def _gantt(d: Diagram) -> dict[str, Any]:
    t0 = min(t.start for t in d.tasks)
    t1 = max(t.end for t in d.tasks)
    span = max(t1 - t0, 1e-9)
    label_w = max(120.0, *(text_width(t.label) + 2 * PAD_X for t in d.tasks))
    chart_w = max(480.0, min(1100.0, 40.0 * span))
    title_h = 36.0 if d.title else 0.0
    lanes: list[str] = []
    for t in d.tasks:
        if t.lane not in lanes:
            lanes.append(t.lane)
    row_h, top = 30.0, MARGIN + title_h + 30
    rows = []
    y = top
    for lane in lanes:
        for t in [t for t in d.tasks if t.lane == lane]:
            x0 = MARGIN + label_w + (t.start - t0) / span * chart_w
            x1 = MARGIN + label_w + (t.end - t0) / span * chart_w
            rows.append({"task": t, "lane": lanes.index(lane), "y": y, "x0": x0, "x1": max(x1, x0 + 3)})
            y += row_h
    width = MARGIN * 2 + label_w + chart_w
    if d.title:
        width = max(width, text_width(d.title, FONT + 5) + 2 * MARGIN)
    return {"t0": t0, "t1": t1, "span": span, "label_w": label_w, "chart_w": chart_w, "rows": rows, "top": top, "row_h": row_h,
            "lanes": lanes, "width": width, "height": y + 34 + MARGIN, "title_h": title_h}


# ------------------------------------------------------------------------------------------------ svg
def _f(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _text(x: float, y: float, s: str, fill: str, *, size: float = FONT, anchor: str = "middle", weight: int = 400,
          cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return (f'<text x="{_f(x)}" y="{_f(y)}" fill="{fill}" font-size="{_f(size)}" font-weight="{weight}" '
            f'text-anchor="{anchor}" dominant-baseline="central"{c}>{escape(s)}</text>')


def _defs(p: dict) -> str:
    return ('<defs>'
            f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{p["accent"]}"/></marker>'
            f'<marker id="arrow-muted" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{p["muted"]}"/></marker></defs>')


def _shape(b: Box, p: dict) -> str:
    fill, stroke = p["surface"], p["border"]
    x, y, w, h = b.x, b.y, b.w, b.h
    if b.shape == "diamond":
        cx, cy = b.cx, b.cy
        return f'<path d="M{_f(cx)},{_f(y)} L{_f(x + w)},{_f(cy)} L{_f(cx)},{_f(y + h)} L{_f(x)},{_f(cy)} Z" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>'
    if b.shape == "cylinder":
        e = 7.0
        return (f'<path d="M{_f(x)},{_f(y + e)} A{_f(w / 2)},{_f(e)} 0 0 1 {_f(x + w)},{_f(y + e)} V{_f(y + h - e)} '
                f'A{_f(w / 2)},{_f(e)} 0 0 1 {_f(x)},{_f(y + h - e)} Z" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>'
                f'<path d="M{_f(x)},{_f(y + e)} A{_f(w / 2)},{_f(e)} 0 0 0 {_f(x + w)},{_f(y + e)}" fill="none" stroke="{stroke}" stroke-width="1.4"/>')
    rx = {"round": 12, "pill": h / 2, "er": 6}.get(b.shape, 6)
    out = f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" rx="{_f(rx)}" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>'
    if b.shape == "er":
        out += f'<path d="M{_f(x)},{_f(y + b.header_h)} H{_f(x + w)}" stroke="{stroke}" stroke-width="1.2"/>'
    return out


def _box_text(b: Box, p: dict) -> str:
    if b.shape == "er":
        parts = [_text(b.cx, b.y + b.header_h / 2, b.lines[0], p["ink"], size=FONT + 1, weight=600)]
        for i, row in enumerate(b.lines[1:]):
            parts.append(_text(b.x + PAD_X, b.y + b.header_h + PAD_Y / 2 + LINE_H * (i + 0.5), row, p["ink"], anchor="start"))
        return "".join(parts)
    top = b.cy - LINE_H * (len(b.lines) - 1) / 2 + (3.5 if b.shape == "cylinder" else 0)
    return "".join(_text(b.cx, top + LINE_H * i, ln, p["ink"], weight=500) for i, ln in enumerate(b.lines))


def _label_chip(x: float, y: float, s: str, p: dict) -> str:
    w = text_width(s, FONT - 1) + 10
    return (f'<rect x="{_f(x - w / 2)}" y="{_f(y - 9)}" width="{_f(w)}" height="18" rx="4" fill="{p["paper"]}"/>'
            + _text(x, y, s, p["muted"], size=FONT - 1))


def _graph_svg(d: Diagram, lay: Layout, p: dict, styles: Optional[dict] = None) -> list[str]:
    out = []
    for i, f in enumerate(lay.frames):
        color = p["series"][i % len(p["series"])]
        if f.kind == "lane":
            out.append(f'<rect x="{_f(f.x)}" y="{_f(f.y)}" width="{_f(f.w)}" height="{_f(f.h)}" fill="none" stroke="{p["border"]}" stroke-width="1"/>')
            out.append(f'<rect x="{_f(f.x)}" y="{_f(f.y)}" width="6" height="{_f(f.h)}" fill="{color}"/>')
            out.append(_text(f.x + 16, f.y + 16, f.label, p["ink"], anchor="start", weight=600))
        else:
            out.append(f'<rect x="{_f(f.x)}" y="{_f(f.y)}" width="{_f(f.w)}" height="{_f(f.h)}" rx="10" fill="none" '
                       f'stroke="{color}" stroke-width="1.6" stroke-dasharray="6 4"/>')
            out.append(_text(f.x + 12, f.y + 12, f.label, p["ink"], anchor="start", weight=600, size=FONT - 1))
    for index, r in enumerate(lay.routes):
        d_attr = "M" + " L".join(f"{_f(x)},{_f(y)}" for x, y in r.points)
        dash = ' stroke-dasharray="6 4"' if r.style == "dashed" else ""
        edge_id = escape(d.edges[index].id, quote=True) if index < len(d.edges) else str(index)
        out.append(f'<path data-edge-id="{edge_id}" d="{d_attr}" fill="none" stroke="{p["accent"]}" stroke-width="1.6"{dash} marker-end="url(#arrow)"/>')
    for b in lay.boxes.values():
        style = (styles or {}).get(b.id, {})
        colours = {**p, **{role: style[key] for key, role in (("fill", "surface"), ("stroke", "border"), ("ink", "ink")) if key in style}}
        out.append(f'<g data-node-id="{escape(b.id, quote=True)}">{_shape(b, colours)}{_box_text(b, colours)}</g>')
    for r in lay.routes:
        if r.label and r.label_at:
            out.append(_label_chip(r.label_at[0], r.label_at[1], r.label, p))
        if r.cardinality and len(r.points) >= 2:
            (x0, y0), (x1, y1) = r.points[-2], r.points[-1]
            ox, oy = (12, -10) if abs(x1 - x0) < 0.5 else (-14, -10)
            out.append(_text(x1 + ox, y1 + oy - (8 if abs(x1 - x0) < 0.5 else 0), r.cardinality, p["muted"], size=FONT - 2, anchor="start"))
    return out


def _sequence_svg(d: Diagram, s: dict, p: dict) -> list[str]:
    out = []
    top = MARGIN + s["title_h"]
    for i, (name, x) in enumerate(s["xs"].items()):
        for y in (top, s["end_y"]):
            out.append(f'<rect x="{_f(x - s["col_w"] / 2)}" y="{_f(y)}" width="{_f(s["col_w"])}" height="{_f(s["head_h"])}" rx="6" '
                       f'fill="{p["surface"]}" stroke="{p["border"]}" stroke-width="1.4"/>')
            out.append(_text(x, y + s["head_h"] / 2, name, p["ink"], weight=600))
        out.append(f'<path d="M{_f(x)},{_f(top + s["head_h"])} V{_f(s["end_y"])}" stroke="{p["border"]}" stroke-width="1.2" stroke-dasharray="4 4"/>')
    for row in s["rows"]:
        y, x0, x1 = row["y"], row["from"], row["to"]
        dash = ' stroke-dasharray="6 4"' if row["reply"] else ""
        color, marker = (p["muted"], "arrow-muted") if row["reply"] else (p["accent"], "arrow")
        if row["self"]:
            out.append(f'<path d="M{_f(x0)},{_f(y)} H{_f(x0 + 40)} V{_f(y + 22)} H{_f(x0 + 2)}" fill="none" stroke="{color}" stroke-width="1.6"{dash} marker-end="url(#{marker})"/>')
            out.append(_text(x0 + 48, y + 11, row["label"], p["ink"], size=FONT - 1, anchor="start"))
        else:
            end = x1 - 2 if x1 > x0 else x1 + 2
            out.append(f'<path d="M{_f(x0)},{_f(y)} H{_f(end)}" fill="none" stroke="{color}" stroke-width="1.6"{dash} marker-end="url(#{marker})"/>')
            out.append(_text((x0 + x1) / 2, y - 10, row["label"], p["ink"], size=FONT - 1))
    return out


def _timeline_svg(d: Diagram, t: dict, p: dict) -> list[str]:
    ay = t["axis_y"]
    out = [f'<path d="M{_f(MARGIN)},{_f(ay)} H{_f(t["width"] - MARGIN)}" stroke="{p["border"]}" stroke-width="2"/>']
    for i, (e, x) in enumerate(zip(d.events, t["xs"])):
        up = i % 2 == 0
        color = p["series"][i % len(p["series"])]
        out.append(f'<circle cx="{_f(x)}" cy="{_f(ay)}" r="6" fill="{color}" stroke="{p["paper"]}" stroke-width="2"/>')
        ty = ay - 22 if up else ay + 22
        out.append(_text(x, ty, e.when, p["ink"], weight=700))
        for j, ln in enumerate(_lines(e.label, t["step"] - 20)):
            out.append(_text(x, (ay - 44 - 16 * j) if up else (ay + 44 + 16 * j), ln, p["muted"], size=FONT - 1))
    return out


def _lines(text: str, width: float) -> list[str]:
    from .layout import wrap
    per = max(8, int(width / ((FONT - 1) * 0.58)))
    return wrap(text, per)[:3]


def _gantt_svg(d: Diagram, g: dict, p: dict) -> list[str]:
    out = []
    x_chart = MARGIN + g["label_w"]
    bottom = g["rows"][-1]["y"] + g["row_h"] if g["rows"] else g["top"]
    ticks = 6
    for i in range(ticks + 1):
        v = g["t0"] + g["span"] * i / ticks
        x = x_chart + g["chart_w"] * i / ticks
        out.append(f'<path d="M{_f(x)},{_f(g["top"] - 6)} V{_f(bottom)}" stroke="{p["border"]}" stroke-width="0.8" stroke-dasharray="2 4"/>')
        out.append(_text(x, bottom + 14, f"{_f(v)}{d.unit}", p["muted"], size=FONT - 2))
    for row in g["rows"]:
        t, y = row["task"], row["y"]
        color = p["series"][row["lane"] % len(p["series"])]
        out.append(_text(MARGIN + g["label_w"] - PAD_X, y + g["row_h"] / 2, t.label, p["ink"], anchor="end"))
        out.append(f'<rect x="{_f(row["x0"])}" y="{_f(y + 6)}" width="{_f(row["x1"] - row["x0"])}" height="{_f(g["row_h"] - 12)}" rx="4" fill="{color}"/>')
    if any(g["lanes"]):
        for i, lane in enumerate(g["lanes"]):
            first = next(r for r in g["rows"] if r["lane"] == i)
            out.append(_text(MARGIN, first["y"] - 2, lane, p["series"][i % len(p["series"])], size=FONT - 2, anchor="start", weight=700))
    return out


def layout_of(d: Diagram) -> Any:
    if d.type == "isometric":
        return isometric.layout(d)
    if d.type == "swimlane":
        return swimlane(d)
    if d.type in ("flowchart", "architecture", "state", "er"):
        return layered(d)
    return {"sequence": _sequence, "timeline": _timeline, "gantt": _gantt}[d.type](d)


def svg(d: Diagram, profile: dict, mode: str = "light", lay: Any = None, node_styles: Optional[dict] = None) -> str:
    p = profile[mode]
    font = profile.get("font") or FONT_STACK
    lay = lay if lay is not None else layout_of(d)
    if d.type == "isometric":
        return isometric.svg(d, profile, mode, lay, font)
    if isinstance(lay, Layout):
        width, height, body = lay.width, lay.height, _graph_svg(d, lay, p, node_styles)
    else:
        width, height = lay["width"], lay["height"]
        body = {"sequence": _sequence_svg, "timeline": _timeline_svg, "gantt": _gantt_svg}[d.type](d, lay, p)
    title = _text(MARGIN, MARGIN + 10, d.title, p["ink"], size=FONT + 5, anchor="start", weight=700) if d.title else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_f(width)} {_f(height)}" width="{_f(width)}" height="{_f(height)}" '
            f'font-family="{escape(font, quote=True)}" role="img" aria-label="{escape(d.title or d.type, quote=True)}">'
            f'{_defs(p)}<rect width="100%" height="100%" fill="{p["paper"]}"/>{title}{"".join(body)}</svg>')


# ------------------------------------------------------------------------------------------------ gates
def _overlap(a: tuple, b: tuple, pad: float = 0.0) -> bool:
    return a[0] < b[2] + pad and b[0] < a[2] + pad and a[1] < b[3] + pad and b[1] < a[3] + pad


def _segment_hits(p0: tuple, p1: tuple, r: tuple, shrink: float = 2.0) -> bool:
    x0, y0, x1, y1 = r[0] + shrink, r[1] + shrink, r[2] - shrink, r[3] - shrink
    (ax, ay), (bx, by) = p0, p1
    if abs(ax - bx) < 0.01:                                 # vertical
        return x0 < ax < x1 and min(ay, by) < y1 and max(ay, by) > y0
    if abs(ay - by) < 0.01:                                 # horizontal
        return y0 < ay < y1 and min(ax, bx) < x1 and max(ax, bx) > x0
    return False


def gates(d: Diagram, profile: dict, lay: Any) -> list[dict]:
    out: list[dict] = []

    def gate(gid: str, ok: bool, detail: str = "", items: Optional[list] = None) -> None:
        out.append({"id": gid, "ok": bool(ok), "detail": detail, **({"items": items[:12]} if items else {})})

    for mode in ("light", "dark"):
        p = profile[mode]
        pairs = [("ink/paper", p["ink"], p["paper"], 4.5), ("ink/surface", p["ink"], p["surface"], 4.5),
                 ("muted/paper", p["muted"], p["paper"], 4.5), ("accent/paper", p["accent"], p["paper"], 3.0),
                 ("border/paper", p["border"], p["paper"], 3.0 if d.type in ("sequence", "timeline", "gantt") else 1.5)]
        bad = [f"{name} {contrast_ratio(a, b):.2f}:1 < {need}:1" for name, a, b, need in pairs if contrast_ratio(a, b) < need]
        bad += [f"series {i} {contrast_ratio(c, p['paper']):.2f}:1 < 3:1" for i, c in enumerate(p["series"][:4])
                if contrast_ratio(c, p["paper"]) < 3.0]
        gate(f"contrast_{mode}", not bad, "text 4.5:1, lines and accents 3:1" if not bad else "; ".join(bad))
    if d.type == "isometric":
        return out + isometric.gates(d, profile, lay)
    if not isinstance(lay, Layout):
        width, height = lay["width"], lay["height"]
        if d.type == "gantt":
            narrow = [r["task"].label for r in lay["rows"] if r["x1"] - r["x0"] < 4]
            gate("bars_visible", not narrow, "every bar is at least 4 px wide", narrow)
        gate("inside_canvas", width > 0 and height > 0, f"{_f(width)} x {_f(height)}")
        return out
    boxes = list(lay.boxes.values())
    overlaps = [f"{a.id} / {b.id}" for i, a in enumerate(boxes) for b in boxes[i + 1:] if _overlap(a.rect(), b.rect(), 4)]
    gate("no_overlap", not overlaps, "boxes keep at least 4 px apart", overlaps)
    crossings = []
    for r in lay.routes:
        for b in boxes:
            if b.id in (r.source, r.target):
                continue
            if any(_segment_hits(p0, p1, b.rect()) for p0, p1 in zip(r.points, r.points[1:])):
                crossings.append(f"{r.source}->{r.target} crosses {b.id}")
    gate("edges_clear_of_boxes", not crossings, "no edge runs through a box it does not connect", crossings)
    tight = []
    for b in boxes:
        room = b.w - 2 * PAD_X + (0 if b.shape != "diamond" else -b.w * 0.3)
        widest = max((text_width(ln, FONT + (1 if b.shape == "er" and i == 0 else 0)) for i, ln in enumerate(b.lines)), default=0)
        if widest > room + 0.5:
            tight.append(f"{b.id} ({_f(widest)} > {_f(room)} px)")
    gate("labels_fit", not tight, "every label line fits its box", tight)
    foreign = []
    for f in lay.frames:
        if f.kind != "group":
            continue
        for b in boxes:
            if b.id not in f.members and _overlap(b.rect(), (f.x, f.y, f.x + f.w, f.y + f.h)):
                foreign.append(f"{b.id} inside {f.id}")
    gate("groups_hold_only_members", not foreign, "a group frame encloses only its own boxes", foreign)
    labels_on_boxes = []
    for r in lay.routes:
        if r.label and r.label_at:
            w = text_width(r.label, FONT - 1) + 10
            rect = (r.label_at[0] - w / 2, r.label_at[1] - 9, r.label_at[0] + w / 2, r.label_at[1] + 9)
            labels_on_boxes += [f"'{r.label}' on {b.id}" for b in boxes if _overlap(rect, b.rect())]
    gate("edge_labels_clear", not labels_on_boxes, "edge labels sit off the boxes", labels_on_boxes)
    on_border = []
    lane_lines = [f.y for f in lay.frames if f.kind == "lane"] + [f.y + f.h for f in lay.frames if f.kind == "lane"]
    for r in lay.routes:
        for (x0, y0), (x1, y1) in zip(r.points, r.points[1:]):
            if abs(y0 - y1) < 0.01 and abs(x1 - x0) > 8 and any(abs(y0 - ly) < 3 for ly in lane_lines):
                on_border.append(f"{r.source}->{r.target}")
                break
    gate("edge_off_lane_borders", not on_border, "no edge runs along a lane border", on_border)
    xs = [v for b in boxes for v in (b.x, b.x + b.w)] + [x for r in lay.routes for x, _ in r.points]
    ys = [v for b in boxes for v in (b.y, b.y + b.h)] + [y for r in lay.routes for _, y in r.points]
    inside = min(xs) >= 0 and min(ys) >= 0 and max(xs) <= lay.width + 0.5 and max(ys) <= lay.height + 0.5
    gate("inside_canvas", inside, f"{_f(lay.width)} x {_f(lay.height)}")
    return out
