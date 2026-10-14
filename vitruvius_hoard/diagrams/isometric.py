"""The ``isometric`` diagram: an idea explained as one working object drawn as an isometric technical figure.

The model gives parametric pieces (slab, plate, cylinder, post, ring, coil) with a plan on the floor, a height and a tone;
code does the camera fit, the visible faces, the four-tone shading, the painter's order and the frame (figure number, title,
hint, readout). The tones come from the brand profile: paper is the card, side faces are paper pulled toward the ink (light)
or toward black (dark), edges use ink / muted / border, and the one ``lit`` piece takes the accent.

Gates (deterministic, run before anyone looks): contrast of every engraved label on its face, labels that do not fit or would
be too small, solids that interpenetrate at the same height, everything inside the canvas and clear of the frame text, frame
text that fits, one lit piece, a painter's order without conflicts, and *line ends*: every tick, seam and groove line must end
on another stroke, a dot or an outline, or sit under a fill painted after it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from html import escape
from typing import Any, Optional

from ..tokens import contrast_ratio, hex_to_oklch, parse_hex, to_hex
from . import iso as K
from .spec import RECT_KINDS, Diagram, Piece

W, H = 640.0, 420.0
PAD = (30.0, 56.0, 30.0, 56.0)               # left, top, right, bottom of the room kept for the frame text
FRAME_FONT = 12.0
LABEL_MIN_PX = 7.0
TOL = 1.0                                    # px a line end may be off the stroke it lands on
EPS = 1e-6
MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
TICK_STEP_PX = 6.0


# ------------------------------------------------------------------------------------------------ colour
def mix(a: str, b: str, t: float) -> str:
    ra, rb = parse_hex(a), parse_hex(b)
    return to_hex(*(x * (1 - t) + y * t for x, y in zip(ra, rb)))


def palette(p: dict) -> dict[str, Any]:
    """Every colour of the figure for one mode, derived from the profile's roles."""
    paper, ink, muted, accent, border = p["paper"], p["ink"], p["muted"], p["accent"], p["border"]
    dark = hex_to_oklch(paper)[0] < 0.5
    if dark:
        top = mix(paper, "#ffffff", 0.08)
        shades = [mix(paper, "#000000", a) for a in (0.32, 0.24, 0.16, 0.08)]
    else:
        top = mix(paper, "#ffffff", 0.6)
        shades = [mix(paper, ink, a) for a in (0.18, 0.12, 0.07, 0.03)]
    lit_top = mix(top, accent, 0.20 if not dark else 0.28)
    return {
        "paper": paper, "ink": ink, "muted": muted, "accent": accent, "border": border, "dark": dark,
        "fill": paper, "top": top, "shades": shades,
        "lit_fill": mix(paper, accent, 0.10), "lit_top": lit_top, "lit_shades": [mix(s, accent, 0.22) for s in shades],
        "tone": {"hi": ink, "mid": muted, "lo": border, "faint": mix(paper, border, 0.55), "lit": accent},
        "crease": mix(paper, border, 0.55), "lit_crease": mix(paper, accent, 0.5),
        "halo": ("#000000", 0.5) if dark else (border, 0.28),
    }


# ------------------------------------------------------------------------------------------------ geometry
@dataclass
class Deco:
    tag: str                                   # tick | seam | knurl | groove | screw | seat | hole | coil
    tone: str                                  # faint | lo | mid | hi
    lines: list[K.Line] = field(default_factory=list)
    dots: list[tuple[K.Pt, float]] = field(default_factory=list)
    inner: bool = False                        # drawn under the outline (seams, grooves on the side)
    fill: Optional[str] = None                 # hole: name of the shade that fills it


@dataclass
class Geo:
    piece: Piece
    box: tuple[float, float, float, float, float, float]   # x0 y0 z0 x1 y1 z1
    solid: Optional[K.Solid] = None
    decos: list[Deco] = field(default_factory=list)
    back: list[K.Line] = field(default_factory=list)         # coil
    front: list[K.Line] = field(default_factory=list)
    label: Optional[dict] = None
    halo: bool = False
    rank: int = 0                                            # position in the painter's order (coil: the back half)
    rank_front: int = 0


def piece_box(pc: Piece) -> tuple[float, float, float, float, float, float]:
    x0, y0, x1, y1 = pc.footprint()
    return (x0, y0, pc.z, x1, y1, pc.z + pc.h)


def _steps_for(radius_px: float) -> int:
    """Facets of a round part: enough that the chord sags under a third of a pixel."""
    if radius_px < 1:
        return 16
    return int(min(96, max(24, math.ceil(math.pi / math.acos(max(0.0, 1 - 0.3 / radius_px))))))


def _snap(steps: int, divisor: int) -> int:
    return steps if steps % divisor == 0 else steps + divisor - steps % divisor


def build_geo(pc: Piece, proj: K.Projection, u: float, low_z: float) -> Geo:
    """Solid and decorations of one piece in screen space. ``u`` is the world size of one design unit (span / 200)."""
    box = piece_box(pc)
    x0, y0, z0, x1, y1, z1 = box
    g = Geo(pc, box)
    k = proj.scale * math.sqrt(1.6)
    p = pc.plan
    h = pc.h
    bevel = min(1.0 * u, h / 3) if h >= 3 * u else 0.0
    if pc.kind in RECT_KINDS:
        w, d = p.w, p.d
        corner = p.corner if p.corner is not None else min(2.0 * u, w / 2, d / 2)
        plan = K.Rect(p.x, p.y, w, d, corner)
        g.solid = K.slab_of(plan, pc.z, h, proj, 8, min(bevel, 0.2 * min(w, d)))
        g.halo = pc.kind in RECT_KINDS and abs(pc.z - low_z) < EPS
        _rect_details(g, pc, plan, proj, u)
    elif pc.kind == "coil":
        r = p.r
        center = (p.cx, p.cy)
        g.back, g.front = K.coil(pc.z, z1, center, r, pc.turns, "z", proj)
        steps = _snap(_steps_for(r * k), 4)
        for z in (pc.z, z1):
            g.decos.append(Deco("seat", "faint", [K.ring_line(p.cx, p.cy, r, z, proj, steps)]))
    else:
        r = p.r
        steps = _snap(_steps_for(r * k), 12)
        ring = K.circle_ring(p.cx, p.cy, r, steps)
        g.solid = K.extrude(ring, pc.z, h, proj, convex=True, bevel=min(bevel, 0.15 * r))
        _round_details(g, pc, ring, steps, proj, u)
    if pc.label and pc.kind not in ("ring", "coil", "post"):
        g.label = _label(pc, box, proj, u)
    return g


def _rect_details(g: Geo, pc: Piece, plan: K.Rect, proj: K.Projection, u: float) -> None:
    x0, y0, z0, x1, y1, z1 = g.box
    w, d, h = plan.w, plan.d, pc.h
    side_label = bool(pc.label) and _label_face(pc, u, proj) in ("left", "right")
    for detail in pc.details:
        if detail == "seam":
            frac = 0.86 if side_label else 0.5
            g.decos.append(Deco("seam", "faint", K.side_seam(plan, z0 + h * frac, proj), inner=True))
        elif detail == "groove":
            ins = min(5 * u, 0.18 * min(w, d))
            if min(w, d) > 4 * ins and ins > 0:
                g.decos.append(Deco("groove", "faint", [K.plan_outline(K.inset_plan(plan, ins), z1, proj)]))
        elif detail == "screws":
            ins = min(8 * u, 0.2 * min(w, d))
            if min(w, d) > 4 * ins and ins > 0:
                rr = min(2.2 * u, 0.4 * ins)
                pts = K.corners(plan, ins)
                g.decos.append(Deco("screw", "lo", [K.ring_line(cx, cy, rr, z1, proj, 16) for cx, cy in pts],
                                    dots=[(K.iso((cx, cy, z1), proj), 0.9) for cx, cy in pts]))
        elif detail == "ticks":
            step = max(4 * u, (w / 60))
            lengths = (min(2 * u, 0.12 * d), min(3.6 * u, 0.22 * d))
            margin = plan.r + step + (8 * u if "screws" in pc.details else 0)
            if w - 2 * margin > 4 * step and lengths[0] > 0:
                minor, major = K.top_ticks(x0 + margin, x1 - margin, step, 5, y1, z1, lengths, proj, "x", inward=-1.0)
                g.decos.append(Deco("tick", "lo", minor))
                g.decos.append(Deco("tick", "mid", major))


def _round_details(g: Geo, pc: Piece, ring: list[K.Pt], steps: int, proj: K.Projection, u: float) -> None:
    p = pc.plan
    x0, y0, z0, x1, y1, z1 = g.box
    k = proj.scale * math.sqrt(1.6)
    circ_px = 2 * math.pi * p.r * k
    for detail in pc.details:
        if detail == "seam":
            g.decos.append(Deco("seam", "faint", K.ring_seam(ring, z0 + pc.h * (0.86 if pc.label else 0.5), proj), inner=True))
        elif detail == "knurl":
            count = max(12, min(steps, round(circ_px / 6)))
            while steps % count:
                count -= 1
            vx, vy = K.toward_viewer(proj)
            lines = []
            for j in range(count):
                px, py = ring[j * steps // count]
                nx, ny = (px - p.cx) / p.r, (py - p.cy) / p.r
                if nx * vx + ny * vy >= 0.15:
                    lines.append(K.segment((px, py, z0), (px, py, z1), proj))
            g.decos.append(Deco("knurl", "lo", lines, inner=True))
        elif detail == "ticks":
            count = max(12, min(72, round(circ_px / TICK_STEP_PX / 12) * 12))
            span = p.r - (p.r2 if (pc.kind == "ring" and p.r2) else 0)
            lengths = (min(0.07 * p.r, 0.3 * span), min(0.14 * p.r, 0.5 * span))
            minor, major = K.rim_ticks(ring, (p.cx, p.cy), count, 6 if count % 6 == 0 else 4, z1, lengths, proj)
            g.decos.append(Deco("tick", "lo", minor))
            g.decos.append(Deco("tick", "mid", major))
    if pc.kind == "ring":
        r2 = p.r2 if p.r2 else p.r * 0.65
        hole = K.ring_line(p.cx, p.cy, r2, z1, proj, steps)
        g.decos.insert(0, Deco("hole", "lo", [hole], fill="hole"))


def _label_face(pc: Piece, u: float, proj: K.Projection) -> str:
    """top, left (normal +y, runs along x) or right (normal +x, runs along y). Auto: a tall piece takes the side face that
    shows most to the camera (face width times how square-on it is), a flat one its top."""
    if pc.kind not in RECT_KINDS:
        return "top"
    face = pc.face
    if face == "auto":
        c = K.camera_of(proj)
        face = "top" if pc.h < 8 * u else ("left" if pc.plan.w * c.sin_a >= pc.plan.d * c.cos_a else "right")
    return face


def _label(pc: Piece, box, proj: K.Projection, u: float) -> dict:
    """Where a label is engraved, how big it is and which tone is under it."""
    x0, y0, z0, x1, y1, z1 = box
    text = pc.label
    face = _label_face(pc, u, proj)
    n = max(1, len(text))
    if pc.kind in RECT_KINDS:
        w, d, h = x1 - x0, y1 - y0, pc.h
    else:
        w = d = pc.plan.r * 1.5
        h = pc.h
    if face == "top":
        avail_w, avail_h = (w * 0.88, d * 0.6) if pc.kind in RECT_KINDS else (pc.plan.r * 1.5, pc.plan.r * 0.9)
        center = ((x0 + x1) / 2, (y0 + y1) / 2)
        m = K.top_matrix(center, z1, proj, "x")
        at = (0.0, 0.0)
        bg = ("top", 0)
    elif face == "left":
        avail_w, avail_h = w * 0.9, h * 0.8
        m = K.side_matrix((x0, y1), z1, proj, "left")
        at = (w / 2, h / 2)
        bg = ("shade", K.face_shade((0.0, 1.0), proj))
    else:
        avail_w, avail_h = d * 0.9, h * 0.8
        m = K.side_matrix((x1, y1), z1, proj, "right")
        at = (d / 2, h / 2)
        bg = ("shade", K.face_shade((1.0, 0.0), proj))
    size = min(9 * u, avail_h * 0.55, avail_w / (n * 0.62))
    width = n * 0.62 * size
    px = size * math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))                 # on-screen size, shear included
    half_w, half_h = width / 2, size / 2
    corners = [K.apply_matrix(m, at[0] + sx * half_w, at[1] + sy * half_h) for sx in (-1, 1) for sy in (-1, 1)]
    return {"text": text, "face": face, "matrix": m, "at": at, "size": size, "size_px": px, "width": width,
            "avail": avail_w, "bg": bg, "corners": corners}


# ------------------------------------------------------------------------------------------------ painter's order
@dataclass
class Node:
    id: str
    role: str                                  # solid | back | front
    box: tuple[float, float, float, float, float, float]
    key: float = 0.0
    screen: tuple[float, float, float, float] = (0, 0, 0, 0)


def _overlap3(a: Node, b: Node) -> bool:
    return (min(a.box[3], b.box[3]) - max(a.box[0], b.box[0]) > EPS and min(a.box[4], b.box[4]) - max(a.box[1], b.box[1]) > EPS
            and min(a.box[5], b.box[5]) - max(a.box[2], b.box[2]) > EPS)


def _precedes(a: Node, b: Node, sx: int, sy: int) -> bool:
    """True when ``a`` must be painted before ``b`` (b is in front of a, or a is the back half of a coil around b)."""
    if a.id == b.id:
        return a.role == "back" and b.role == "front"
    if "back" in (a.role, b.role) or "front" in (a.role, b.role):
        if _overlap3(a, b):
            return a.role == "back" or b.role == "front"
    ax0, ay0, az0, ax1, ay1, az1 = a.box
    bx0, by0, bz0, bx1, by1, bz1 = b.box
    return ((sx > 0 and bx0 >= ax1 - EPS) or (sx < 0 and bx1 <= ax0 + EPS) or (sy > 0 and by0 >= ay1 - EPS)
            or (sy < 0 and by1 <= ay0 + EPS) or bz0 >= az1 - EPS)


def paint_order(nodes: list[Node], proj: K.Projection) -> tuple[list[int], list[tuple[int, int]]]:
    """Indices of ``nodes`` from back to front, and the pairs that could not be ordered (interlocked).

    A pair is ordered when one box sits wholly in front of the other along x, y or z (toward the viewer) and the two
    overlap on screen; the rest follow the depth of their centres. Sorting by centre alone paints a small part standing on
    the far corner of a big base *before* the base.
    """
    c = K.camera_of(proj)
    sx = 1 if c.cos_a >= 0 else -1
    sy = 1 if c.sin_a >= 0 else -1
    for nd in nodes:
        x0, y0, z0, x1, y1, z1 = nd.box
        pts = [K.iso((x, y, z), proj) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
        nd.screen = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        nd.key = K.depth_of(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), proj)
    n = len(nodes)
    before: list[set[int]] = [set() for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            a, b = nodes[i], nodes[j]
            if a.screen[0] >= b.screen[2] or b.screen[0] >= a.screen[2] or a.screen[1] >= b.screen[3] or b.screen[1] >= a.screen[3]:
                continue
            ij, ji = _precedes(a, b, sx, sy), _precedes(b, a, sx, sy)
            if ij and not ji:
                before[j].add(i)
            elif ji and not ij:
                before[i].add(j)
    remaining = set(range(n))
    order: list[int] = []
    while remaining:
        ready = [i for i in remaining if not (before[i] & remaining)]
        pick = min(ready or remaining, key=lambda i: (nodes[i].key, i))
        order.append(pick)
        remaining.discard(pick)
    pos = {idx: p for p, idx in enumerate(order)}
    conflicts = [(i, j) for j in range(n) for i in before[j] if pos[i] > pos[j]]
    return order, conflicts


# ------------------------------------------------------------------------------------------------ layout
def layout(d: Diagram) -> dict[str, Any]:
    pieces = d.pieces
    xs = [v for pc in pieces for v in (pc.footprint()[0], pc.footprint()[2])]
    ys = [v for pc in pieces for v in (pc.footprint()[1], pc.footprint()[3])]
    zs = [v for pc in pieces for v in (pc.z, pc.z + pc.h)]
    span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1e-9)
    u = span / 200.0
    pts: list[tuple[float, float, float]] = []
    for pc in pieces:
        x0, y0, x1, y1 = pc.footprint()
        if pc.kind in RECT_KINDS:
            pts += [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (pc.z, pc.z + pc.h)]
        else:
            for i in range(24):
                a = i / 24 * 2 * math.pi
                for z in (pc.z, pc.z + pc.h):
                    pts.append((pc.plan.cx + pc.plan.r * math.cos(a), pc.plan.cy + pc.plan.r * math.sin(a), z))
    proj = K.fit_projection(pts, W, H, pad=PAD, azimuth=d.azimuth, elevation=d.elevation)
    low_z = min(pc.z for pc in pieces if pc.kind in RECT_KINDS) if any(pc.kind in RECT_KINDS for pc in pieces) else 0.0
    geos = [build_geo(pc, proj, u, low_z) for pc in pieces]
    nodes: list[Node] = []
    owner: list[tuple[int, str]] = []
    for i, g in enumerate(geos):
        if g.piece.kind == "coil":
            nodes.append(Node(g.piece.id, "back", g.box))
            owner.append((i, "back"))
            nodes.append(Node(g.piece.id, "front", g.box))
            owner.append((i, "front"))
        else:
            nodes.append(Node(g.piece.id, "solid", g.box))
            owner.append((i, "solid"))
    order, conflicts = paint_order(nodes, proj)
    for rank, idx in enumerate(order):
        i, role = owner[idx]
        if role == "front":
            geos[i].rank_front = rank
        else:
            geos[i].rank = rank
            if role == "solid":
                geos[i].rank_front = rank
    draw = [owner[idx] for idx in order]
    named = [(nodes[a].id, nodes[b].id) for a, b in conflicts]
    return {"width": W, "height": H, "proj": proj, "geos": geos, "draw": draw, "conflicts": named, "unit": u, "span": span}


# ------------------------------------------------------------------------------------------------ frame text
def frame_texts(d: Diagram) -> dict[str, str]:
    return {"fig": f"FIG {d.figure}", "title": (d.title or "").upper(), "hint": (d.hint or "").upper(), "readout": d.readout or ""}


def mono_width(text: str, spaced: bool = True) -> float:
    return len(text) * FRAME_FONT * (0.66 if spaced else 0.6)


def frame_boxes(d: Diagram) -> dict[str, tuple[float, float, float, float]]:
    """Screen boxes (x0, y0, x1, y1) of the four corner texts."""
    t = frame_texts(d)
    top_y, bot_y, left_x, right_x = 32.0, H - 30.0, 26.0, W - 26.0
    half = FRAME_FONT / 2
    out = {"fig": (left_x, top_y - half, left_x + mono_width(t["fig"]), top_y + half)}
    if t["title"]:
        out["title"] = (right_x - mono_width(t["title"]), top_y - half, right_x, top_y + half)
    if t["hint"]:
        out["hint"] = (left_x, bot_y - half, left_x + mono_width(t["hint"]), bot_y + half)
    if t["readout"]:
        out["readout"] = (right_x - mono_width(t["readout"], False), bot_y - half, right_x, bot_y + half)
    return out


# ------------------------------------------------------------------------------------------------ svg
def _deco_svg(dec: Deco, pal: dict, lit: bool) -> str:
    color = pal["tone"][dec.tone]
    if dec.tag == "hole":
        shade = pal["lit_shades"][0] if lit else pal["shades"][0]
        return f'<path d="{K.d_of(dec.lines)}" fill="{shade}" stroke="{pal["tone"]["lo"]}" {K.STROKE_BASE}/>'
    out = K.line_svg(dec.lines, color)
    if dec.dots:
        out += K.dots_svg([p for p, _ in dec.dots], pal["tone"]["hi"], dec.dots[0][1])
    return out


def _piece_svg(g: Geo, pal: dict) -> str:
    pc = g.piece
    lit = pc.lit
    edge = pal["tone"]["lit"] if lit else pal["tone"][pc.tone]
    crease = pal["lit_crease"] if lit else (pal["tone"]["lo"] if pc.tone == "hi" else pal["crease"])
    inner = "".join(_deco_svg(dec, pal, lit) for dec in g.decos if dec.inner)
    after = "".join(_deco_svg(dec, pal, lit) for dec in g.decos if not dec.inner)
    shades = pal["lit_shades"] if lit else pal["shades"]
    svg = K.solid_svg(g.solid, fill=pal["lit_fill"] if lit else pal["fill"], shades=shades,
                      top=pal["lit_top"] if lit else pal["top"], edge=edge, crease=crease,
                      halo=pal["halo"] if g.halo else None, inner=inner, data_id=pc.id)
    return svg[:-4] + after + _label_svg(g, pal) + "</g>"


def _label_svg(g: Geo, pal: dict) -> str:
    lb = g.label
    if not lb:
        return ""
    return K.face_text_svg(lb["matrix"], lb["text"], pal["ink"], size=lb["size"], at=lb["at"])


def _coil_svg(g: Geo, pal: dict, role: str) -> str:
    lit = g.piece.lit
    if role == "back":
        seats = "".join(_deco_svg(dec, pal, lit) for dec in g.decos)
        return f'<g data-piece="{escape(g.piece.id, quote=True)}" data-part="back">{seats}{K.line_svg(g.back, pal["tone"]["lo"])}</g>'
    color = pal["tone"]["lit"] if lit else pal["tone"]["mid"]
    return f'<g data-piece="{escape(g.piece.id, quote=True)}" data-part="front">{K.line_svg(g.front, color)}</g>'


def _frame_svg(d: Diagram, pal: dict) -> str:
    t = frame_texts(d)
    top_y, bot_y, left_x, right_x = 32.0, H - 30.0, 26.0, W - 26.0
    common = f'font-family="{escape(MONO, quote=True)}" font-size="{FRAME_FONT:g}" dominant-baseline="central"'
    parts = [f'<rect x="10" y="10" width="{W - 20:g}" height="{H - 20:g}" fill="none" stroke="{pal["tone"]["lo"]}" stroke-width="1"/>',
             f'<text x="{left_x:g}" y="{top_y:g}" fill="{pal["ink"]}" letter-spacing="0.06em" {common}>{escape(t["fig"])}</text>']
    if t["title"]:
        parts.append(f'<text x="{right_x:g}" y="{top_y:g}" fill="{pal["muted"]}" letter-spacing="0.06em" text-anchor="end" {common}>{escape(t["title"])}</text>')
    if t["hint"]:
        parts.append(f'<text x="{left_x:g}" y="{bot_y:g}" fill="{pal["muted"]}" letter-spacing="0.06em" {common}>{escape(t["hint"])}</text>')
    if t["readout"]:
        parts.append(f'<text x="{right_x:g}" y="{bot_y:g}" fill="{pal["ink"]}" text-anchor="end" {common}>{escape(t["readout"])}</text>')
    return "".join(parts)


def svg(d: Diagram, profile: dict, mode: str, lay: dict[str, Any], font: str) -> str:
    pal = palette(profile[mode])
    body = []
    for i, role in lay["draw"]:
        g = lay["geos"][i]
        body.append(_coil_svg(g, pal, role) if g.piece.kind == "coil" else _piece_svg(g, pal))
    defs = '<defs><filter id="iso-blur" x="-20%" y="-30%" width="140%" height="160%"><feGaussianBlur stdDeviation="6"/></filter></defs>'
    desc = escape(f"{d.title or 'Isometric figure'}. {d.readout}".strip())
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:g} {H:g}" width="{W:g}" height="{H:g}" '
            f'font-family="{escape(font, quote=True)}" role="img" aria-label="{escape(d.title or "Isometric figure", quote=True)}">'
            f'<desc>{desc}</desc>{defs}<rect width="100%" height="100%" fill="{pal["paper"]}"/>'
            f'{_frame_svg(d, pal)}{"".join(body)}</svg>')


# ------------------------------------------------------------------------------------------------ gates
def _seg_dist(p: K.Pt, a: K.Pt, b: K.Pt) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    ln = dx * dx + dy * dy
    t = 0.0 if ln < 1e-12 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / ln))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _near_line(p: K.Pt, pts: list[K.Pt], closed: bool, tol: float) -> bool:
    if len(pts) == 1:
        return math.hypot(p[0] - pts[0][0], p[1] - pts[0][1]) <= tol
    segs = list(zip(pts, pts[1:])) + ([(pts[-1], pts[0])] if closed else [])
    return any(_seg_dist(p, a, b) <= tol for a, b in segs)


def _in_hull(p: K.Pt, hull: list[K.Pt]) -> bool:
    """Strictly inside a convex polygon (any winding)."""
    n = len(hull)
    if n < 3:
        return False
    sign = 0
    for i in range(n):
        ax, ay = hull[i]
        bx, by = hull[(i + 1) % n]
        cr = (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)
        if abs(cr) < 1e-9:
            continue
        s = 1 if cr > 0 else -1
        if sign and s != sign:
            return False
        sign = s
    return sign != 0


@dataclass
class LineRef:
    pts: list[K.Pt]
    tag: str
    piece: str
    rank: int
    closed: bool = False
    free: bool = False


def line_refs(lay: dict[str, Any]) -> list[LineRef]:
    out: list[LineRef] = []
    for g in lay["geos"]:
        pid = g.piece.id
        for dec in g.decos:
            for ln in dec.lines:
                out.append(LineRef(ln.pts, dec.tag, pid, g.rank, ln.closed))
        for ln in g.back:
            out.append(LineRef(ln.pts, "coil", pid, g.rank))
        for ln in g.front:
            out.append(LineRef(ln.pts, "coil", pid, g.rank_front))
    return out


def floating_ends(lines: list[LineRef], solids: list[tuple[str, int, K.Solid]], dots: list[tuple[K.Pt, float]],
                  tol: float = TOL) -> list[str]:
    """Ends of open lines that land on nothing.

    A line end is fine when it is within ``tol`` px of another stroke (any outline, crease or bevel, a closed line, another
    open line), of a dot, or when a solid painted after the line covers it. A tick (short mark) needs one rooted end; seams,
    knurls and the rest need both.
    """
    strokes: list[tuple[list[K.Pt], bool, Optional[LineRef], tuple[float, float, float, float]]] = []

    def box(pts: list[K.Pt]) -> tuple[float, float, float, float]:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs) - tol, min(ys) - tol, max(xs) + tol, max(ys) + tol)

    for _, _, s in solids:
        for ln in s.outline + s.crease + s.bevel:
            if ln.pts:
                strokes.append((ln.pts, ln.closed, None, box(ln.pts)))
    for ref in lines:
        if ref.pts:
            strokes.append((ref.pts, ref.closed, ref, box(ref.pts)))
    bad: list[str] = []
    for ref in lines:
        if ref.closed or ref.free or len(ref.pts) < 2:
            continue
        ends = [ref.pts[0], ref.pts[-1]]
        rooted = []
        for e in ends:
            ok = any(math.hypot(e[0] - c[0], e[1] - c[1]) <= r + tol for c, r in dots)
            if not ok:
                ok = any(other is not ref and bx0 <= e[0] <= bx1 and by0 <= e[1] <= by1 and _near_line(e, pts, closed, tol)
                         for pts, closed, other, (bx0, by0, bx1, by1) in strokes)
            if not ok:
                ok = any(rank > ref.rank and _in_hull(e, s.hull) for _, rank, s in solids)
            rooted.append(ok)
        need = 1 if ref.tag == "tick" else 2
        if sum(rooted) < need:
            floating = [ends[i] for i in range(2) if not rooted[i]]
            bad.append(f"{ref.tag} on '{ref.piece}' ends in the air at ({floating[0][0]:.0f}, {floating[0][1]:.0f})")
    return bad


def solid_overlaps(pieces: list[Piece]) -> list[str]:
    """Pairs of solids that occupy the same space (same height, footprints that cross). Touching faces are fine."""
    solids = [pc for pc in pieces if pc.kind != "coil"]
    bad = []
    for i, a in enumerate(solids):
        for b in solids[i + 1:]:
            if min(a.z + a.h, b.z + b.h) - max(a.z, b.z) <= EPS:
                continue
            if _footprints_cross(a, b):
                bad.append(f"{a.id} / {b.id}")
    return bad


def _footprints_cross(a: Piece, b: Piece) -> bool:
    ra, rb = a.kind in RECT_KINDS, b.kind in RECT_KINDS
    if ra and rb:
        ax0, ay0, ax1, ay1 = a.footprint()
        bx0, by0, bx1, by1 = b.footprint()
        return min(ax1, bx1) - max(ax0, bx0) > EPS and min(ay1, by1) - max(ay0, by0) > EPS
    if not ra and not rb:
        return math.hypot(a.plan.cx - b.plan.cx, a.plan.cy - b.plan.cy) < a.plan.r + b.plan.r - EPS
    rect, circ = (a, b) if ra else (b, a)
    x0, y0, x1, y1 = rect.footprint()
    nx = min(max(circ.plan.cx, x0), x1)
    ny = min(max(circ.plan.cy, y0), y1)
    return math.hypot(circ.plan.cx - nx, circ.plan.cy - ny) < circ.plan.r - EPS


def _label_bg(lb: dict, pal: dict, lit: bool) -> str:
    kind, idx = lb["bg"]
    if kind == "top":
        return pal["lit_top"] if lit else pal["top"]
    return (pal["lit_shades"] if lit else pal["shades"])[idx]


def gates(d: Diagram, profile: dict, lay: dict[str, Any]) -> list[dict]:
    out: list[dict] = []

    def gate(gid: str, ok: bool, detail: str = "", items: Optional[list] = None) -> None:
        out.append({"id": gid, "ok": bool(ok), "detail": detail, **({"items": items[:12]} if items else {})})

    geos: list[Geo] = lay["geos"]
    lit = [g.piece.id for g in geos if g.piece.lit]
    gate("one_lit", len(lit) == 1,
         f"'{lit[0]}' is the lit piece" if len(lit) == 1 else "mark the one piece the reader should watch with lit: true")
    over = solid_overlaps(d.pieces)
    gate("no_interpenetration", not over,
         "no two solids share space at the same height (keep the hole of a ring empty)" if not over
         else "these solids cross each other: separate them in the plan or stack them with z", over)
    conflicts = [f"{a} / {b}" for a, b in lay["conflicts"]]
    gate("depth_order", not conflicts, "every part is painted in front of what it hides" if not conflicts
         else "these parts interlock and cannot be ordered: move one so they no longer wrap each other", conflicts)
    # labels: size, fit and contrast on the face they are engraved on
    small, loose = [], []
    for g in geos:
        lb = g.label
        if not lb:
            continue
        if lb["size_px"] < LABEL_MIN_PX:
            small.append(f"{g.piece.id} '{lb['text']}' would be {lb['size_px']:.1f} px")
        if lb["width"] > lb["avail"] * 1.001:
            loose.append(f"{g.piece.id} '{lb['text']}' is wider than its face")
    gate("label_size", not small, f"every engraved label is at least {LABEL_MIN_PX:g} px" if not small
         else "make the piece bigger or the label shorter", small)
    gate("label_fits", not loose, "every label fits the face it is engraved on", loose)
    for mode in ("light", "dark"):
        pal = palette(profile[mode])
        low = []
        for g in geos:
            if g.label:
                bg = _label_bg(g.label, pal, g.piece.lit)
                ratio = contrast_ratio(pal["ink"], bg)
                if ratio < 4.5:
                    low.append(f"{g.piece.id} {ratio:.2f}:1")
        gate(f"label_contrast_{mode}", not low, "engraved text 4.5:1 on its face" if not low else "text under 4.5:1 on its face", low)
    # frame text
    t = frame_texts(d)
    top_w = mono_width(t["fig"]) + mono_width(t["title"]) + (24 if t["title"] else 0)
    bot_w = mono_width(t["hint"]) + mono_width(t["readout"], False) + (24 if t["hint"] and t["readout"] else 0)
    room = W - 52
    tight = []
    if top_w > room:
        tight.append(f"title is too long ({top_w:.0f} > {room:.0f} px)")
    if bot_w > room:
        tight.append(f"hint and readout together are too long ({bot_w:.0f} > {room:.0f} px)")
    gate("frame_text_fit", not tight, "figure number, title, hint and readout fit the frame" if not tight
         else "shorten them", tight)
    # canvas: every drawn point inside the frame and clear of its text
    pts: list[K.Pt] = []
    for g in geos:
        if g.solid:
            pts += g.solid.hull
        for ln in g.back + g.front:
            pts += ln.pts
        for dec in g.decos:
            for ln in dec.lines:
                pts += ln.pts
        if g.label:
            pts += g.label["corners"]
    outside = [p for p in pts if not (14 <= p[0] <= W - 14 and 14 <= p[1] <= H - 14)]
    boxes = frame_boxes(d)
    hits = []
    for name, (bx0, by0, bx1, by1) in boxes.items():
        if any(bx0 - 4 <= p[0] <= bx1 + 4 and by0 - 4 <= p[1] <= by1 + 4 for p in pts):
            hits.append(f"the drawing touches the {name} text")
    gate("inside_canvas", not outside and not hits, f"{W:g} x {H:g}, inside the frame and clear of its text" if not (outside or hits)
         else "the drawing leaves the frame or touches its text", [f"{len(outside)} points outside"] * bool(outside) + hits)
    # line ends
    solids = [(g.piece.id, g.rank, g.solid) for g in geos if g.solid]
    dots = [(p, r) for g in geos for dec in g.decos for p, r in dec.dots]
    floating = floating_ends(line_refs(lay), solids, dots)
    gate("line_ends", not floating, "line ends: 0 (every tick, seam and groove ends on a stroke, a dot or an outline)"
         if not floating else f"line ends: {len(floating)}", floating)
    return out
