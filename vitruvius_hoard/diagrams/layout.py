"""Layout in code: layered placement on a grid and orthogonal routing, so a small model only has to get the structure right.

Graph types (flowchart, architecture, state, er) use a layered layout: cycles are broken by reversing back edges, ranks come
from the longest path, long edges get one dummy per layer they cross (so they run in the gaps, never through a box), layers
are ordered by barycentre sweeps and boxes are pulled toward their neighbours without overlapping. Every edge is drawn as
vertical and horizontal segments through the gap between two layers, each edge in its own lane of that gap. Architecture
keeps each group's members in one band so the group frame never encloses a foreign box. Swimlane puts lanes in rows and
ranks in columns and routes long or backward edges along the lane borders.

Everything is computed in "primary" (along the flow) and "cross" coordinates and mapped to x/y at the end, so TB and LR share
one code path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .spec import Diagram, Node

FONT = 13.0
CHAR_W = 0.58           # average advance of a sans glyph, in ems: estimates text width without a font engine
LINE_H = 17.0
PAD_X, PAD_Y = 14.0, 10.0
WRAP = 24               # characters per label line
LAYER_GAP = 64.0        # free space between two layers (the routing channel)
NODE_GAP = 36.0         # free space between two boxes of one layer
MARGIN = 28.0
GROUP_PAD = 18.0
GROUP_LABEL_H = 20.0


def text_width(text: str, size: float = FONT) -> float:
    return len(text) * size * CHAR_W


def wrap(text: str, width: int = WRAP) -> list[str]:
    lines: list[str] = []
    for para in (text or "").split("\n"):
        line = ""
        for word in para.split():
            while len(word) > width:                       # a single word longer than the box: cut it
                if line:
                    lines.append(line)
                    line = ""
                lines.append(word[:width])
                word = word[width:]
            if not line:
                line = word
            elif len(line) + 1 + len(word) <= width:
                line += " " + word
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines or [""]


@dataclass
class Box:
    id: str
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    lines: list[str] = field(default_factory=list)
    shape: str = "box"
    group: str = ""
    header_h: float = 0.0                                  # er: height of the title band
    dummy: bool = False

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def rect(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)


@dataclass
class Route:
    source: str
    target: str
    points: list[tuple[float, float]]
    label: str = ""
    style: str = "solid"
    cardinality: str = ""
    label_at: Optional[tuple[float, float]] = None


@dataclass
class Frame:
    id: str
    label: str
    x: float
    y: float
    w: float
    h: float
    members: list[str] = field(default_factory=list)
    kind: str = "group"                                    # group | lane


@dataclass
class Layout:
    width: float
    height: float
    boxes: dict[str, Box]
    routes: list[Route]
    frames: list[Frame]
    title_h: float = 0.0


def size_box(node: Node, kind: str) -> Box:
    if kind == "er":
        rows = [f"{f.name}{(' : ' + f.type) if f.type else ''}{'  ' + f.key.upper() if f.key else ''}" for f in node.fields]
        title = node.label
        w = max(140.0, text_width(title, FONT + 1) + 2 * PAD_X, *(text_width(r) + 2 * PAD_X for r in rows)) if rows else \
            max(140.0, text_width(title, FONT + 1) + 2 * PAD_X)
        header = LINE_H + 2 * PAD_Y - 4
        h = header + (len(rows) * LINE_H + PAD_Y if rows else 0)
        return Box(node.id, w=w, h=h, lines=[title, *rows], shape="er", group=node.group, header_h=header)
    lines = wrap(node.label)
    tw = max(text_width(ln) for ln in lines)
    w = max(96.0, tw + 2 * PAD_X)
    h = len(lines) * LINE_H + 2 * PAD_Y
    if node.shape == "diamond":
        w, h = max(w * 1.45, h * 2.2), h * 1.7
    elif node.shape == "cylinder":
        h += 14
    elif node.shape == "pill":
        w += 12
    return Box(node.id, w=w, h=h, lines=lines, shape=node.shape, group=node.group)


# ------------------------------------------------------------------------------------------------ layered (graph types)
def _ranks(ids: list[str], edges: list[tuple[str, str]]) -> tuple[dict[str, int], set[int]]:
    """Longest-path ranks after reversing the back edges found by a DFS in input order; returns the reversed edge indexes."""
    out: dict[str, list[tuple[int, str]]] = {i: [] for i in ids}
    for k, (a, b) in enumerate(edges):
        if a != b:
            out[a].append((k, b))
    state: dict[str, int] = {}
    reversed_: set[int] = set()

    def dfs(v: str) -> None:
        stack = [(v, iter(out[v]))]
        state[v] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
                continue
            k, w = nxt
            if state.get(w) == 1:
                reversed_.add(k)
            elif w not in state:
                state[w] = 1
                stack.append((w, iter(out[w])))

    indeg = {i: 0 for i in ids}
    for a, b in edges:
        if a != b:
            indeg[b] += 1
    for v in [i for i in ids if indeg[i] == 0] + ids:     # sources first so the flow starts where the reader expects
        if v not in state:
            dfs(v)
    dag = [(b, a) if k in reversed_ else (a, b) for k, (a, b) in enumerate(edges) if a != b]
    rank = {i: 0 for i in ids}
    for _ in range(len(ids)):
        changed = False
        for a, b in dag:
            if rank[b] < rank[a] + 1:
                rank[b] = rank[a] + 1
                changed = True
        if not changed:
            break
    return rank, reversed_


def layered(d: Diagram) -> Layout:
    kind = d.type
    lr = d.direction == "LR"
    boxes = {n.id: size_box(n, kind) for n in d.nodes}
    ids = [n.id for n in d.nodes]
    pairs = [(e.source, e.target) for e in d.edges]
    rank, reversed_ = _ranks(ids, pairs)

    def cross_size(b: Box) -> float:
        return b.h if lr else b.w

    def prim_size(b: Box) -> float:
        return b.w if lr else b.h

    # chains through dummies: one dummy per layer an edge crosses
    chains: list[list[str]] = []
    for k, e in enumerate(d.edges):
        a, b = (e.target, e.source) if k in reversed_ else (e.source, e.target)
        if a == b:
            chains.append([a, a])
            continue
        chain = [a]
        for r in range(rank[a] + 1, rank[b]):
            dummy = f"__d{k}_{r}"
            boxes[dummy] = Box(dummy, w=8, h=8, dummy=True)
            rank[dummy] = r
            chain.append(dummy)
        chain.append(b)
        chains.append(chain)
    nlayers = max(rank.values()) + 1
    layers: list[list[str]] = [[] for _ in range(nlayers)]
    for v in list(boxes):
        layers[rank[v]].append(v)
    up: dict[str, list[str]] = {v: [] for v in boxes}
    down: dict[str, list[str]] = {v: [] for v in boxes}
    for chain in chains:
        for a, b in zip(chain, chain[1:]):
            if a != b:
                down[a].append(b)
                up[b].append(a)

    group_order = {g.id: i for i, g in enumerate(d.groups)}

    def gkey(v: str) -> int:
        b = boxes[v]
        if kind != "architecture" or b.dummy:
            return 0
        return group_order.get(b.group, len(group_order)) + 1

    pos = {v: float(i) for layer in layers for i, v in enumerate(layer)}
    for sweep in range(8):
        rng = range(1, nlayers) if sweep % 2 == 0 else range(nlayers - 2, -1, -1)
        for r in rng:
            nb = up if sweep % 2 == 0 else down

            def bary(v: str) -> float:
                ns = nb[v]
                return sum(pos[n] for n in ns) / len(ns) if ns else pos[v]
            layers[r].sort(key=lambda v: (gkey(v), bary(v)) if kind == "architecture" else (bary(v),))
            for i, v in enumerate(layers[r]):
                pos[v] = float(i)
    if kind == "architecture":
        layers[0].sort(key=lambda v: (gkey(v), pos[v]))

    # cross coordinates: pack each layer, then pull toward neighbours (both directions), keeping NODE_GAP between boxes
    cross: dict[str, float] = {}
    for layer in layers:
        c = 0.0
        for v in layer:
            cross[v] = c + cross_size(boxes[v]) / 2
            c += cross_size(boxes[v]) + NODE_GAP

    def settle(layer: list[str], want: dict[str, float]) -> None:
        for v in layer:
            cross[v] = want.get(v, cross[v])
        for i in range(1, len(layer)):                   # push right
            a, b = layer[i - 1], layer[i]
            gap = NODE_GAP + (GROUP_PAD * 2 if kind == "architecture" and gkey(a) != gkey(b) else 0)
            lo = cross[a] + cross_size(boxes[a]) / 2 + gap + cross_size(boxes[b]) / 2
            if cross[b] < lo:
                cross[b] = lo
        for i in range(len(layer) - 2, -1, -1):          # and back left, so the block stays centred on its wishes
            a, b = layer[i], layer[i + 1]
            gap = NODE_GAP + (GROUP_PAD * 2 if kind == "architecture" and gkey(a) != gkey(b) else 0)
            hi = cross[b] - cross_size(boxes[b]) / 2 - gap - cross_size(boxes[a]) / 2
            if cross[a] > hi:
                cross[a] = hi

    for it in range(6):
        order = range(1, nlayers) if it % 2 == 0 else range(nlayers - 2, -1, -1)
        for r in order:
            nb = up if it % 2 == 0 else down
            want = {v: sum(cross[n] for n in nb[v]) / len(nb[v]) for v in layers[r] if nb[v]}
            settle(layers[r], want)
    if kind == "architecture":
        # one cross band per group, the same in every layer, so a group frame can never take in a foreign box
        keys = sorted({gkey(v) for layer in layers for v in layer})
        need = {k: 0.0 for k in keys}
        for layer in layers:
            for k in keys:
                members = [v for v in layer if gkey(v) == k]
                if members:
                    need[k] = max(need[k], sum(cross_size(boxes[v]) for v in members) + NODE_GAP * (len(members) - 1))
        start, c = {}, 0.0
        for k in keys:
            start[k] = c
            c += need[k] + NODE_GAP + 2 * GROUP_PAD + (GROUP_LABEL_H if k else 0)
        for layer in layers:
            for k in keys:
                members = [v for v in layer if gkey(v) == k]
                used = sum(cross_size(boxes[v]) for v in members) + NODE_GAP * (len(members) - 1)
                c = start[k] + (need[k] - used) / 2
                for v in members:
                    cross[v] = c + cross_size(boxes[v]) / 2
                    c += cross_size(boxes[v]) + NODE_GAP
    # primary coordinates: one band per layer as thick as its thickest box
    thick = [max((prim_size(boxes[v]) for v in layer), default=0.0) for layer in layers]
    starts, p = [], 0.0
    for t in thick:
        starts.append(p)
        p += t + LAYER_GAP
    for r, layer in enumerate(layers):
        for v in layer:
            b = boxes[v]
            pc = starts[r] + (thick[r] - prim_size(b)) / 2
            cc = cross[v] - cross_size(b) / 2
            b.x, b.y = (pc, cc) if lr else (cc, pc)

    # groups (architecture): a frame around the members, label on top
    frames: list[Frame] = []
    if kind == "architecture":
        for g in d.groups:
            members = [boxes[n.id] for n in d.nodes if n.group == g.id]
            if not members:
                continue
            x0 = min(m.x for m in members) - GROUP_PAD
            y0 = min(m.y for m in members) - GROUP_PAD - GROUP_LABEL_H
            x1 = max(m.x + m.w for m in members) + GROUP_PAD
            y1 = max(m.y + m.h for m in members) + GROUP_PAD
            frames.append(Frame(g.id, g.label or g.id, x0, y0, x1 - x0, y1 - y0, [m.id for m in members]))

    # routing: per inter-layer gap, give every crossing segment its own channel line
    gap_segments: dict[int, list[tuple[str, str, int]]] = {}
    for ci, chain in enumerate(chains):
        for a, b in zip(chain, chain[1:]):
            if a != b:
                gap_segments.setdefault(rank[a], []).append((a, b, ci))
    channel: dict[tuple[int, str, str], float] = {}
    for r, segs in gap_segments.items():
        segs.sort(key=lambda s: (min(cross[s[0]], cross[s[1]]), max(cross[s[0]], cross[s[1]])))
        lo = starts[r] + thick[r]
        n = len(segs)
        for i, (a, b, ci) in enumerate(segs):
            channel[(ci, a, b)] = lo + LAYER_GAP * (i + 1) / (n + 1)

    def port(v: str, toward: str, side: str) -> float:
        """Cross position on v's side where the segment to/from `toward` attaches: spread over the box face."""
        b = boxes[v]
        if b.dummy or b.shape in ("diamond", "pill", "round"):
            return cross[v]
        peers = sorted(down[v] if side == "out" else up[v], key=lambda n: cross[n])
        if len(peers) <= 1:
            return cross[v]
        span = cross_size(b) * 0.6
        i = peers.index(toward)
        return cross[v] - span / 2 + span * i / (len(peers) - 1)

    def pt(prim: float, crs: float) -> tuple[float, float]:
        return (prim, crs) if lr else (crs, prim)

    routes: list[Route] = []
    for k, (e, chain) in enumerate(zip(d.edges, chains)):
        if chain[0] == chain[1] and len(chain) == 2:      # self loop: a small square on the far side
            b = boxes[chain[0]]
            if lr:
                pts = [(b.x + b.w * 0.7, b.y + b.h), (b.x + b.w * 0.7, b.y + b.h + 18), (b.x + b.w * 0.3, b.y + b.h + 18),
                       (b.x + b.w * 0.3, b.y + b.h)]
            else:
                pts = [(b.x + b.w, b.y + b.h * 0.3), (b.x + b.w + 18, b.y + b.h * 0.3), (b.x + b.w + 18, b.y + b.h * 0.7),
                       (b.x + b.w, b.y + b.h * 0.7)]
            routes.append(Route(e.source, e.target, pts, e.label, e.style, e.cardinality,
                                label_at=(pts[1][0] + 6, pts[1][1]) if not lr else (pts[1][0], pts[1][1] + 12)))
            continue
        if k in reversed_:
            # a loop back: leave through the gap after the source's layer, run outside every box of the layers it spans,
            # come back through the gap before the target's layer and enter the target from the flow side
            sb, tb = boxes[e.source], boxes[e.target]
            rs, rt = rank[e.source], rank[e.target]
            nback = sum(1 for j in range(k) if j in reversed_)
            far = max(cross[v] + cross_size(boxes[v]) / 2 for r in range(rt, rs + 1) for v in layers[r]) + 22 + 10 * nback
            below = starts[rs] + thick[rs] + LAYER_GAP * 0.86
            above = starts[rt] - LAYER_GAP * 0.86
            s_face = (sb.x + sb.w) if lr else (sb.y + sb.h)
            t_face = tb.x if lr else tb.y
            sc, tc = cross[e.source] + cross_size(sb) * 0.18, cross[e.target] + cross_size(tb) * 0.18
            if sb.shape in ("diamond", "pill", "round"):
                sc = cross[e.source]
            if tb.shape in ("diamond", "pill", "round"):
                tc = cross[e.target]
            pts = _simplify([pt(s_face, sc), pt(below, sc), pt(below, far), pt(above, far), pt(above, tc), pt(t_face, tc)])
            label_at = None
            if e.label:
                i = max(range(len(pts) - 1), key=lambda j: abs(pts[j + 1][0] - pts[j][0]) + abs(pts[j + 1][1] - pts[j][1]))
                label_at = ((pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2)
            routes.append(Route(e.source, e.target, pts, e.label, e.style, e.cardinality, label_at))
            continue
        pts: list[tuple[float, float]] = []
        for a, b in zip(chain, chain[1:]):
            ba, bb = boxes[a], boxes[b]
            pa = (ba.x + ba.w if lr else ba.y + ba.h) if not ba.dummy else (ba.x + ba.w / 2 if lr else ba.y + ba.h / 2)
            pb = (bb.x if lr else bb.y) if not bb.dummy else (bb.x + bb.w / 2 if lr else bb.y + bb.h / 2)
            ca, cb = port(a, b, "out"), port(b, a, "in")
            mid = channel[(k, a, b)]
            seg = [pt(pa, ca), pt(mid, ca), pt(mid, cb), pt(pb, cb)]
            if pts and pts[-1] == seg[0]:
                seg = seg[1:]
            pts.extend(seg)
        if k in reversed_:
            pts.reverse()
        pts = _simplify(pts)
        label_at = None
        if e.label:
            longest = max(range(len(pts) - 1), key=lambda i: abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1]))
            (x0, y0), (x1, y1) = pts[longest], pts[longest + 1]
            label_at = ((x0 + x1) / 2, (y0 + y1) / 2)
        routes.append(Route(e.source, e.target, pts, e.label, e.style, e.cardinality, label_at))

    real = {k: v for k, v in boxes.items() if not v.dummy}
    return _finish(real, routes, frames, d.title)


def _simplify(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in pts:
        if out and abs(out[-1][0] - p[0]) < 0.01 and abs(out[-1][1] - p[1]) < 0.01:
            continue
        if len(out) >= 2:
            (ax, ay), (bx, by) = out[-2], out[-1]
            if (abs(ax - bx) < 0.01 and abs(bx - p[0]) < 0.01) or (abs(ay - by) < 0.01 and abs(by - p[1]) < 0.01):
                out[-1] = p                                    # collinear: drop the middle point
                continue
        out.append(p)
    return out


def _finish(boxes: dict[str, Box], routes: list[Route], frames: list[Frame], title: str) -> Layout:
    """Shift everything so the drawing starts at the margin (below the title) and compute the canvas."""
    xs = [b.x for b in boxes.values()] + [f.x for f in frames] + [p[0] for r in routes for p in r.points]
    ys = [b.y for b in boxes.values()] + [f.y for f in frames] + [p[1] for r in routes for p in r.points]
    x2 = [b.x + b.w for b in boxes.values()] + [f.x + f.w for f in frames] + [p[0] for r in routes for p in r.points]
    y2 = [b.y + b.h for b in boxes.values()] + [f.y + f.h for f in frames] + [p[1] for r in routes for p in r.points]
    for r in routes:
        if r.label_at and r.label:
            lw = text_width(r.label, FONT - 1) / 2 + 6
            xs.append(r.label_at[0] - lw)
            x2.append(r.label_at[0] + lw)
            ys.append(r.label_at[1] - 10)
            y2.append(r.label_at[1] + 10)
    title_h = 36.0 if title else 0.0
    dx, dy = MARGIN - min(xs), MARGIN + title_h - min(ys)
    for b in boxes.values():
        b.x += dx
        b.y += dy
    for f in frames:
        f.x += dx
        f.y += dy
    for r in routes:
        r.points = [(x + dx, y + dy) for x, y in r.points]
        if r.label_at:
            r.label_at = (r.label_at[0] + dx, r.label_at[1] + dy)
    width = max(x2) - min(xs) + 2 * MARGIN
    if title:
        width = max(width, text_width(title, FONT + 5) + 2 * MARGIN)
    height = max(y2) - min(ys) + 2 * MARGIN + title_h
    return Layout(width, height, boxes, routes, frames, title_h)


# ------------------------------------------------------------------------------------------------ swimlane
LANE_HEAD = 120.0
COL_GAP = 72.0
ROW_GAP = 22.0
LANE_PAD = 22.0


def swimlane(d: Diagram) -> Layout:
    boxes = {n.id: size_box(n, "swimlane") for n in d.nodes}
    lanes = [g.id for g in d.groups]
    for n in d.nodes:
        if n.group not in lanes:
            lanes.append(n.group)
    rank, _ = _ranks([n.id for n in d.nodes], [(e.source, e.target) for e in d.edges])
    ncols = max(rank.values()) + 1
    col_w = [0.0] * ncols
    for v, b in boxes.items():
        col_w[rank[v]] = max(col_w[rank[v]], b.w)
    col_x, x = [], LANE_HEAD + LANE_PAD
    for w in col_w:
        col_x.append(x)
        x += w + COL_GAP
    total_w = x - COL_GAP + LANE_PAD
    cells: dict[tuple[str, int], list[str]] = {}
    for n in d.nodes:
        cells.setdefault((n.group, rank[n.id]), []).append(n.id)
    frames, y = [], 0.0
    lane_label = {g.id: g.label or g.id for g in d.groups}
    for lane in lanes:
        stacks = [cells.get((lane, c), []) for c in range(ncols)]
        lane_h = max((sum(boxes[v].h for v in s) + ROW_GAP * (len(s) - 1) for s in stacks if s), default=40.0) + 2 * LANE_PAD
        for c, s in enumerate(stacks):
            yy = y + LANE_PAD
            for v in s:
                b = boxes[v]
                b.x = col_x[c] + (col_w[c] - b.w) / 2
                b.y = yy
                yy += b.h + ROW_GAP
        frames.append(Frame(lane or "lane", lane_label.get(lane, lane or "—"), 0.0, y, total_w, lane_h,
                            [n.id for n in d.nodes if n.group == lane], kind="lane"))
        y += lane_h
    lane_of = {n.id: n.group for n in d.nodes}
    lane_frame = {f.id: f for f in frames}
    routes = []
    border_use: dict[float, int] = {}
    for e in d.edges:
        a, b = boxes[e.source], boxes[e.target]
        ra, rb = rank[e.source], rank[e.target]
        if e.source == e.target:
            pts = [(a.x + a.w * 0.7, a.y), (a.x + a.w * 0.7, a.y - 14), (a.x + a.w * 0.3, a.y - 14), (a.x + a.w * 0.3, a.y)]
        elif rb == ra + 1:
            gx = col_x[ra] + col_w[ra] + COL_GAP / 2
            pts = [(a.x + a.w, a.cy), (gx, a.cy), (gx, b.cy), (b.x, b.cy)]
        elif rb == ra and abs(a.cx - b.cx) < 1:
            top, bottom = (a, b) if a.y < b.y else (b, a)
            pts = [(a.cx, a.y + a.h if a is top else a.y), (b.cx, b.y if b is bottom else b.y + b.h)]
        else:
            # leave right into the gap, run along the border above the target's lane, enter from the gap left of the target
            out_x = col_x[ra] + col_w[ra] + COL_GAP / 2
            in_x = col_x[rb] - COL_GAP / 2 if rb > 0 else LANE_HEAD + LANE_PAD / 2
            fr = lane_frame[lane_of[e.target] or "lane"]
            base = fr.y + 6.0
            k = border_use.get(base, 0)
            border_use[base] = k + 1
            by = base + 5.0 * k
            pts = [(a.x + a.w, a.cy), (out_x, a.cy), (out_x, by), (in_x, by), (in_x, b.cy), (b.x, b.cy)]
        pts = _simplify(pts)
        label_at = None
        if e.label:
            longest = max(range(len(pts) - 1), key=lambda i: abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1]))
            (x0, y0), (x1, y1) = pts[longest], pts[longest + 1]
            label_at = ((x0 + x1) / 2, (y0 + y1) / 2)
        routes.append(Route(e.source, e.target, pts, e.label, e.style, "", label_at))
    return _finish(boxes, routes, frames, d.title)
