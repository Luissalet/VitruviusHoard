"""Isometric drawing kit: projection, extruded solids with visible faces and four tones, cylinders, ticks, coils, text on faces.

This module is a Python port of the maths and drawing primitives of an MIT-licensed isometric figure kit (JavaScript).
The original copyright and permission notice are kept below and in THIRD_PARTY_NOTICES.md.

    MIT License

    Copyright (c) 2026 Ryan

    Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
    documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
    rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
    persons to whom the Software is furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
    Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
    WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
    COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
    OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

World space: x and y on the floor, z up. The camera looks from azimuth (turn around z, 45 degrees by default) and elevation
(30 degrees). The viewer sits toward ``(cos a, sin a)`` on the floor; a side face is visible when its outward normal points
that way. Differences from the original: helpers return structured lines (``Line``: points, closed or open) next to the SVG
path text, so the gates can check them, and a coil can run along z as well as x and y.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape
from typing import Optional, Sequence

Pt = tuple[float, float]
Pt3 = tuple[float, float, float]

AZIMUTH = 45.0
ELEVATION = 30.0
SHADES = 4
_RAD = math.pi / 180.0
_UNIT = math.sqrt(1.6)


# ------------------------------------------------------------------------------------------------ camera
@dataclass(frozen=True)
class Projection:
    origin: Pt = (0.0, 0.0)
    scale: float = 1.0
    azimuth: float = AZIMUTH
    elevation: float = ELEVATION


@dataclass(frozen=True)
class Camera:
    sin_a: float
    cos_a: float
    sin_e: float
    cos_e: float
    k: float


def camera_of(proj: Projection) -> Camera:
    a, e = proj.azimuth * _RAD, proj.elevation * _RAD
    return Camera(math.sin(a), math.cos(a), math.sin(e), math.cos(e), proj.scale * _UNIT)


def iso(p: Sequence[float], proj: Projection) -> Pt:
    """World point (x, y, z) to screen (x, y)."""
    c = camera_of(proj)
    x, y, z = p
    return (proj.origin[0] + (x * c.sin_a - y * c.cos_a) * c.k,
            proj.origin[1] + ((x * c.cos_a + y * c.sin_a) * c.sin_e - z * c.cos_e) * c.k)


def toward_viewer(proj: Projection) -> Pt:
    c = camera_of(proj)
    return (c.cos_a, c.sin_a)


def depth_of(p: Sequence[float], proj: Projection) -> float:
    """Distance toward the viewer: bigger is nearer, so painting in ascending order goes back to front."""
    c = camera_of(proj)
    x, y, z = p
    return (x * c.cos_a + y * c.sin_a) * c.cos_e + z * c.sin_e


def fit_projection(points: Sequence[Sequence[float]], width: float, height: float, *, pad=24.0, headroom: float = 0.0,
                   azimuth: float = AZIMUTH, elevation: float = ELEVATION) -> Projection:
    """The scale and origin that centre the projected world points in the canvas.

    ``pad`` is one number or ``(left, top, right, bottom)``; ``headroom`` keeps extra room at the top.
    """
    left_p, top_p, right_p, bottom_p = pad if isinstance(pad, (tuple, list)) else (pad, pad, pad, pad)
    unit = Projection((0.0, 0.0), 1.0, azimuth, elevation)
    flat = [iso(p, unit) for p in points]
    xs, ys = [p[0] for p in flat], [p[1] for p in flat]
    left, right, up, down = min(xs), max(xs), min(ys), max(ys)
    avail_w = width - left_p - right_p
    avail_h = height - top_p - bottom_p - headroom
    scale = min(avail_w / max(right - left, 1e-9), avail_h / max(down - up, 1e-9))
    cx = left_p + avail_w / 2
    cy = top_p + headroom + avail_h / 2
    return Projection((cx - (left + right) / 2 * scale, cy - (up + down) / 2 * scale), scale, azimuth, elevation)


# ------------------------------------------------------------------------------------------------ paths
@dataclass
class Line:
    """A polyline in screen space; ``closed`` joins the last point to the first."""

    pts: list[Pt]
    closed: bool = False


def tenth(v: float) -> str:
    text = f"{math.floor(v * 10 + 0.5) / 10:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return "0" if text == "-0" else text


def path_of(points: Sequence[Pt], closed: bool = False) -> str:
    if not points:
        return ""
    return "".join(f"{'L' if i else 'M'}{tenth(x)} {tenth(y)}" for i, (x, y) in enumerate(points)) + ("Z" if closed else "")


def d_of(lines) -> str:
    """SVG path data of one Line or a list of them."""
    if isinstance(lines, Line):
        lines = [lines]
    return "".join(path_of(l.pts, l.closed) for l in lines if l.pts)


# ------------------------------------------------------------------------------------------------ plans and rings
@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    d: float
    r: float = 0.0


def rounded_plan(plan: Rect, steps: int = 8) -> list[Pt]:
    """The outline ring of a rounded rectangle on the floor, counter-clockwise from the +x/-y corner."""
    x, y, w, d = plan.x, plan.y, plan.w, plan.d
    radius = max(0.0, min(plan.r, w / 2, d / 2))
    corners = [(x + w - radius, y + radius, -90), (x + w - radius, y + d - radius, 0),
               (x + radius, y + d - radius, 90), (x + radius, y + radius, 180)]
    out: list[Pt] = []
    for cx, cy, start in corners:
        count = steps if radius > 0 else 0
        for step in range(count + 1):
            angle = (start + (90 * step / count if count else 45)) * _RAD
            out.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return out


ring_of = rounded_plan


def circle_ring(cx: float, cy: float, radius: float, steps: int = 40) -> list[Pt]:
    return [(cx + radius * math.cos(s / steps * 2 * math.pi), cy + radius * math.sin(s / steps * 2 * math.pi)) for s in range(steps)]


def inset_plan(plan: Rect, by: float) -> Rect:
    return Rect(plan.x + by, plan.y + by, plan.w - 2 * by, plan.d - 2 * by, max(0.0, plan.r - by))


def corners(plan: Rect, inset: float = 0.0) -> list[Pt]:
    x, y, w, d = plan.x, plan.y, plan.w, plan.d
    return [(x + inset, y + inset), (x + w - inset, y + inset), (x + inset, y + d - inset), (x + w - inset, y + d - inset)]


def box_corners(plan: Rect, z0: float, z1: float) -> list[Pt3]:
    return [(px, py, z) for px in (plan.x, plan.x + plan.w) for py in (plan.y, plan.y + plan.d) for z in (z0, z1)]


def signed_area(points: Sequence[Pt]) -> float:
    area = 0.0
    for i, (ax, ay) in enumerate(points):
        bx, by = points[(i + 1) % len(points)]
        area += ax * by - bx * ay
    return area / 2


def oriented(points: Sequence[Pt]) -> list[Pt]:
    return list(reversed(points)) if signed_area(points) < 0 else list(points)


def convex_hull(points: Sequence[Pt]) -> list[Pt]:
    pts = sorted(points)
    if len(pts) < 3:
        return list(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Pt] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Pt] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def runs_of(flags: Sequence[bool], want: bool) -> list[list[int]]:
    """Runs of consecutive vertex indices around a ring whose edge flag equals ``want`` (each run lists its edge ends too)."""
    count = len(flags)
    start = next((i for i in range(count) if flags[i] != flags[(i + count - 1) % count]), -1)
    if start < 0:
        return [[i % count for i in range(count + 1)]] if flags[0] == want else []
    runs: list[list[int]] = []
    run: Optional[list[int]] = None
    for step in range(count):
        index = (start + step) % count
        if flags[index] == want:
            if run is None:
                run = [index]
            run.append((index + 1) % count)
        elif run is not None:
            runs.append(run)
            run = None
    if run is not None:
        runs.append(run)
    return runs


# ------------------------------------------------------------------------------------------------ solids
@dataclass
class Face:
    index: int                 # the ring edge it stands on
    shade: int                 # 0 (away from the light) .. 3 (toward it)
    pts: list[Pt]              # screen quad
    normal: Pt                 # outward floor normal


@dataclass
class Solid:
    hull: list[Pt]             # the filled silhouette (convex hull of the top and bottom rings)
    fill_d: str
    top: list[Pt]
    faces: list[Face]          # only the side faces that look at the viewer
    outline: list[Line]
    crease: list[Line]
    bevel: list[Line]
    facing: list[bool]
    ring: list[Pt]
    z: float
    height: float

    @property
    def shades_d(self) -> list[str]:
        out = ["" for _ in range(SHADES)]
        for f in self.faces:
            out[f.shade] += path_of(oriented(f.pts), True)
        return out

    @property
    def top_d(self) -> str:
        return path_of(oriented(self.top), True)

    @property
    def outline_d(self) -> str:
        return d_of(self.outline)

    @property
    def crease_d(self) -> str:
        return d_of(self.crease)

    @property
    def bevel_d(self) -> str:
        return d_of(self.bevel)


def _normals(ring: Sequence[Pt]) -> list[Pt]:
    count = len(ring)
    counter = signed_area(ring) > 0
    out = []
    for i, (ax, ay) in enumerate(ring):
        bx, by = ring[(i + 1) % count]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy) or 1.0
        out.append((dy / length, -dx / length) if counter else (-dy / length, dx / length))
    return out


def face_shade(normal: Pt, proj: Projection) -> int:
    """The tone bucket (0 darkest .. 3 lightest) of a side face with this outward floor normal."""
    c = camera_of(proj)
    lit = (normal[0] * -c.sin_a + normal[1] * c.cos_a + 1) / 2
    return min(SHADES - 1, max(0, math.floor(lit * SHADES)))


def extrude(ring: Sequence[Pt], z: float, height: float, proj: Projection, *, convex: bool = True, bevel: float = 0.0) -> Solid:
    """A prism over a floor ring. Only side faces that look at the viewer are returned, each in one of four tones by facing."""
    count = len(ring)
    vx, vy = toward_viewer(proj)
    normals = _normals(ring)
    facing = [nx * vx + ny * vy > 1e-9 for nx, ny in normals]
    top = [iso((x, y, z + height), proj) for x, y in ring]
    bottom = [iso((x, y, z), proj) for x, y in ring]
    outline: list[Line] = []
    crease: list[Line] = []
    for run in runs_of(facing, False):
        outline.append(Line([top[i] for i in run]))
    for run in runs_of(facing, True):
        crease.append(Line([top[i] for i in run]))
        if height > 0:
            outline.append(Line([bottom[i] for i in run]))
    if height > 0:
        for i in range(count):
            if facing[(i + count - 1) % count] != facing[i]:
                outline.append(Line([top[i], bottom[i]]))
    hull = convex_hull(top + bottom)
    if convex:
        fill_d = path_of(hull, True)
    else:
        parts = [path_of(oriented(top), True), path_of(oriented(bottom), True)]
        for i in range(count):
            if facing[i]:
                n = (i + 1) % count
                parts.append(path_of(oriented([top[i], top[n], bottom[n], bottom[i]]), True))
        fill_d = "".join(parts)
    faces: list[Face] = []
    if height > 0:
        for i in range(count):
            if not facing[i]:
                continue
            n = (i + 1) % count
            faces.append(Face(i, face_shade(normals[i], proj), [top[i], top[n], bottom[n], bottom[i]], normals[i]))
    bevel_lines: list[Line] = []
    if bevel and bevel > 0:
        inset = []
        for i, (x, y) in enumerate(ring):
            ax, ay = normals[(i + count - 1) % count]
            bx, by = normals[i]
            mx, my = ax + bx, ay + by
            length = math.hypot(mx, my) or 1.0
            inset.append((x - mx / length * bevel, y - my / length * bevel))
        inset_top = [iso((x, y, z + height), proj) for x, y in inset]
        for run in runs_of(facing, True):
            bevel_lines.append(Line([top[run[0]], *[inset_top[i] for i in run[1:-1]], top[run[-1]]]))
    return Solid(hull, fill_d, top, faces, outline, crease, bevel_lines, facing, list(ring), z, height)


def slab_of(plan: Rect, z: float, height: float, proj: Projection, steps: int = 8, bevel: float = 0.0) -> Solid:
    return extrude(rounded_plan(plan, steps), z, height, proj, convex=True, bevel=bevel)


def cylinder(cx: float, cy: float, radius: float, z: float, height: float, proj: Projection, steps: int = 32, bevel: float = 0.0) -> Solid:
    return extrude(circle_ring(cx, cy, radius, steps), z, height, proj, convex=True, bevel=bevel)


def halo_of(plan: Rect, z: float, height: float, proj: Projection) -> str:
    return slab_of(plan, z, height, proj).fill_d


# ------------------------------------------------------------------------------------------------ lines on surfaces
def on_top(points: Sequence[Pt], z: float, proj: Projection, closed: bool = False) -> Line:
    return Line([iso((x, y, z), proj) for x, y in points], closed)


def plan_outline(plan: Rect, z: float, proj: Projection, steps: int = 8) -> Line:
    return on_top(rounded_plan(plan, steps), z, proj, True)


def line_on_top(a: Pt, b: Pt, z: float, proj: Projection) -> Line:
    return on_top([a, b], z, proj)


def segment(a: Pt3, b: Pt3, proj: Projection) -> Line:
    return Line([iso(a, proj), iso(b, proj)])


def rise(at: Pt, z0: float, z1: float, proj: Projection) -> Line:
    return segment((at[0], at[1], z0), (at[0], at[1], z1), proj)


def ring_line(cx: float, cy: float, radius: float, z: float, proj: Projection, steps: int = 40) -> Line:
    return on_top(circle_ring(cx, cy, radius, steps), z, proj, True)


def dot_grid(x: float, y: float, columns: int, rows: int, gap: float, z: float, proj: Projection) -> list[Pt]:
    return [iso((x + c * gap, y + r * gap, z), proj) for r in range(rows) for c in range(columns)]


def knurl(cx: float, cy: float, radius: float, z0: float, z1: float, count: int, proj: Projection) -> list[Line]:
    """Vertical grooves on the visible half of a cylinder, each running the whole side from rim to rim."""
    vx, vy = toward_viewer(proj)
    lines = []
    for i in range(count):
        angle = i / count * 2 * math.pi
        nx, ny = math.cos(angle), math.sin(angle)
        if nx * vx + ny * vy < 0.15:
            continue
        lines.append(segment((cx + radius * nx, cy + radius * ny, z0), (cx + radius * nx, cy + radius * ny, z1), proj))
    return lines


def ring_seam(ring: Sequence[Pt], z: float, proj: Projection) -> list[Line]:
    """A band round the visible half of a prism at height z, ending exactly on the silhouette corners."""
    vx, vy = toward_viewer(proj)
    normals = _normals(ring)
    facing = [nx * vx + ny * vy > 1e-9 for nx, ny in normals]
    return [Line([iso((ring[i][0], ring[i][1], z), proj) for i in run]) for run in runs_of(facing, True)]


def side_seam(plan: Rect, z: float, proj: Projection, steps: int = 8) -> list[Line]:
    return ring_seam(rounded_plan(plan, steps), z, proj)


def side_arc(cx: float, cy: float, radius: float, z: float, proj: Projection, steps: int = 24) -> Line:
    vx, vy = toward_viewer(proj)
    facing = math.atan2(vy, vx)
    pts = []
    for s in range(steps + 1):
        angle = facing - math.pi / 2 + s / steps * math.pi
        pts.append(iso((cx + radius * math.cos(angle), cy + radius * math.sin(angle), z), proj))
    return Line(pts)


def coil(start: float, end: float, center: Pt, radius: float, turns: float, axis: str, proj: Projection,
         per_turn: int = 16) -> tuple[list[Line], list[Line]]:
    """A helix of ``turns`` turns along an axis (x, y or z) as (back, front) strokes: draw back, the rod, then front.

    ``center`` is the two coordinates across the axis: (y, z) for x, (x, z) for y, (x, y) for z.
    """
    count = max(1, round(turns * per_turn))
    back: list[Line] = []
    front: list[Line] = []
    run: list[Pt] = []
    near: Optional[bool] = None
    for index in range(count + 1):
        share = index / count
        angle = share * turns * 2 * math.pi
        u, v = radius * math.cos(angle), radius * math.sin(angle)
        along = start + (end - start) * share
        if axis == "x":
            point, normal = (along, center[0] + u, center[1] + v), (0.0, math.cos(angle), math.sin(angle))
        elif axis == "y":
            point, normal = (center[0] + u, along, center[1] + v), (math.cos(angle), 0.0, math.sin(angle))
        else:
            point, normal = (center[0] + u, center[1] + v, along), (math.cos(angle), math.sin(angle), 0.0)
        facing = depth_of(normal, proj) > 0
        flat = iso(point, proj)
        if near is None:
            near = facing
        if facing != near:
            run.append(flat)
            (front if near else back).append(Line(run))
            run = [flat]
            near = facing
            continue
        run.append(flat)
    if len(run) > 1:
        (front if near else back).append(Line(run))
    return back, front


def rim_ticks(ring: Sequence[Pt], center: Pt, count: int, every: int, z: float, lengths: tuple[float, float],
              proj: Projection) -> tuple[list[Line], list[Line]]:
    """Ticks on a round top that start exactly on ring vertices (so they land on the drawn rim) and hang toward the centre.

    ``count`` ticks are spread over the ring; a tick that is a multiple of ``every`` is long.
    """
    minor: list[Line] = []
    major: list[Line] = []
    n = len(ring)
    for j in range(count):
        px, py = ring[round(j * n / count) % n]
        dx, dy = center[0] - px, center[1] - py
        dist = math.hypot(dx, dy) or 1.0
        length = lengths[1] if j % every == 0 else lengths[0]
        end = (px + dx / dist * length, py + dy / dist * length)
        (major if j % every == 0 else minor).append(line_on_top((px, py), end, z, proj))
    return minor, major


def top_ticks(start: float, end: float, step: float, every: int, edge: float, z: float, lengths: tuple[float, float],
              proj: Projection, axis: str = "x", inward: float = 1.0) -> tuple[list[Line], list[Line]]:
    """Ruler ticks hanging from a floor line (``edge``) over [start, end]: (minor, major). ``inward`` is +1 or -1."""
    minor: list[Line] = []
    major: list[Line] = []
    first = math.ceil(start / step - 1e-9) * step
    at, index = first, round(first / step)
    while at <= end + 1e-9:
        big = index % every == 0
        length = (lengths[1] if big else lengths[0]) * inward
        a = (at, edge) if axis == "x" else (edge, at)
        b = (at, edge + length) if axis == "x" else (edge + length, at)
        (major if big else minor).append(line_on_top(a, b, z, proj))
        at += step
        index += 1
    return minor, major


def side_ticks(start: float, end: float, step: float, every: int, face: float, top: float, lengths: tuple[float, float],
               proj: Projection, axis: str = "x") -> tuple[list[Line], list[Line]]:
    """Ticks hanging down from the top edge of a vertical face: (minor, major)."""
    minor: list[Line] = []
    major: list[Line] = []
    first = math.ceil(start / step - 1e-9) * step
    at, index = first, round(first / step)
    while at <= end + 1e-9:
        big = index % every == 0
        length = lengths[1] if big else lengths[0]
        a = (at, face, top) if axis == "x" else (face, at, top)
        b = (at, face, top - length) if axis == "x" else (face, at, top - length)
        (major if big else minor).append(segment(a, b, proj))
        at += step
        index += 1
    return minor, major


def radial_ticks(cx: float, cy: float, radius: float, count: int, every: int, z: float, lengths: tuple[float, float],
                 proj: Projection, start: float = 0.0, span: float = 2 * math.pi) -> tuple[list[Line], list[Line]]:
    """Ticks round a dial, hanging inward from its rim: (minor, major)."""
    minor: list[Line] = []
    major: list[Line] = []
    closed = abs(span - 2 * math.pi) < 1e-9
    for index in range(count if closed else count + 1):
        angle = start + index / count * span
        big = index % every == 0
        inner = radius - (lengths[1] if big else lengths[0])
        sx, sy = math.sin(angle), -math.cos(angle)
        (major if big else minor).append(line_on_top((cx + sx * inner, cy + sy * inner), (cx + sx * radius, cy + sy * radius), z, proj))
    return minor, major


# ------------------------------------------------------------------------------------------------ faces for text
Matrix = tuple[float, float, float, float, float, float]


def axis_vector(proj: Projection, delta: Pt3) -> Pt:
    o = iso((0.0, 0.0, 0.0), proj)
    m = iso(delta, proj)
    return (m[0] - o[0], m[1] - o[1])


def _axes_at(at: Pt, z: float, proj: Projection):
    origin = iso((at[0], at[1], z), proj)

    def along(p):
        q = iso(p, proj)
        return (q[0] - origin[0], q[1] - origin[1])

    return origin, along((at[0] + 1, at[1], z)), along((at[0], at[1] + 1, z)), along((at[0], at[1], z + 1))


def top_matrix(at: Pt, z: float, proj: Projection, along: str = "x") -> Matrix:
    """SVG matrix that maps flat (u, v) text coordinates onto the floor plane at height z, starting at ``at``."""
    origin, x, y, _ = _axes_at(at, z, proj)
    if along == "x":
        return (x[0], x[1], y[0], y[1], origin[0], origin[1])
    return (-y[0], -y[1], x[0], x[1], origin[0], origin[1])


def side_matrix(at: Pt, z: float, proj: Projection, face: str) -> Matrix:
    """SVG matrix onto a vertical face: ``left`` (normal +y, runs along +x) or ``right`` (normal +x, runs along -y).

    Local v points down, so text at (u, v) hangs ``v`` below ``z`` from the start corner ``at``.
    """
    origin, x, y, up = _axes_at(at, z, proj)
    down = (-up[0], -up[1])
    if face == "left":
        return (x[0], x[1], down[0], down[1], origin[0], origin[1])
    return (-y[0], -y[1], down[0], down[1], origin[0], origin[1])


def matrix_str(m: Matrix) -> str:
    return "matrix(" + " ".join(f"{round(v * 1000) / 1000:g}" for v in m) + ")"


def apply_matrix(m: Matrix, u: float, v: float) -> Pt:
    return (m[0] * u + m[2] * v + m[4], m[1] * u + m[3] * v + m[5])


# ------------------------------------------------------------------------------------------------ svg strings
#: stroke look shared by every drawn line: thin, round, and the same width on screen at any scale
STROKE_BASE = 'stroke-width="1" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"'
STROKE = 'fill="none" ' + STROKE_BASE


def solid_svg(solid: Solid, *, fill: str, shades: Sequence[str], top: str, edge: str, crease: str, flat: bool = False,
              halo: Optional[tuple[str, float]] = None, inner: str = "", cls: str = "", data_id: str = "") -> str:
    """The SVG group of one solid: paper fill, four side tones, lighter top, crease, bevel, inner lines, outline."""
    parts = []
    if halo:
        parts.append(f'<path d="{solid.fill_d}" fill="{halo[0]}" fill-opacity="{halo[1]:.2f}" filter="url(#iso-blur)" '
                     f'transform="translate(0 3)"/>')
    parts.append(f'<path d="{solid.fill_d}" fill="{fill}"/>')
    if not flat:
        for shade, d in enumerate(solid.shades_d):
            if d:
                parts.append(f'<path d="{d}" fill="{shades[shade]}" data-shade="{shade}"/>')
        parts.append(f'<path d="{solid.top_d}" fill="{top}"/>')
    if solid.crease:
        parts.append(f'<path {STROKE} d="{solid.crease_d}" stroke="{crease}"/>')
    if solid.bevel:
        parts.append(f'<path {STROKE} d="{solid.bevel_d}" stroke="{crease}"/>')
    if inner:
        parts.append(inner)
    parts.append(f'<path {STROKE} d="{solid.outline_d}" stroke="{edge}"/>')
    ident = f' data-piece="{escape(data_id, quote=True)}"' if data_id else ""
    return f'<g class="iso-solid{(" " + cls) if cls else ""}"{ident}>{"".join(parts)}</g>'


def line_svg(lines, stroke: str, *, dashed: bool = False, width: Optional[float] = None) -> str:
    d = d_of(lines)
    if not d:
        return ""
    extra = ' stroke-dasharray="3 3"' if dashed else ""
    w = f' stroke-width="{width}"' if width else ""
    return f'<path {STROKE} d="{d}" stroke="{stroke}"{extra}{w}/>'


def dots_svg(points: Sequence[Pt], fill: str, size: float = 0.9) -> str:
    dots = "".join(f'<circle cx="{tenth(x)}" cy="{tenth(y)}" r="{size}"/>' for x, y in points)
    return f'<g fill="{fill}">{dots}</g>' if dots else ""


def face_text_svg(matrix: Matrix, text: str, fill: str, *, size: float = 3.0, anchor: str = "middle", at: Pt = (0.0, 0.0),
                  weight: int = 600, font: str = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace") -> str:
    """Text engraved on a face: drawn in the face's own flat coordinates and carried onto it by the matrix."""
    return (f'<text transform="{matrix_str(matrix)}" x="{tenth(at[0])}" y="{tenth(at[1])}" font-size="{size:g}" '
            f'font-weight="{weight}" font-family="{escape(font, quote=True)}" fill="{fill}" text-anchor="{anchor}" '
            f'dominant-baseline="central">{escape(text)}</text>')
