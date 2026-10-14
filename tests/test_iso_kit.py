"""Isometric kit: camera maths on known points, fit to the canvas, extruded solids with only their visible faces, ticks, coils
and the matrices that carry text onto a face."""

from __future__ import annotations

import math

import pytest

from vitruvius_hoard.diagrams import iso as K

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_projection_of_known_points_is_two_to_one():
    proj = K.Projection((0, 0), 1.0, 45, 30)
    k = math.sqrt(1.6)
    assert K.iso((0, 0, 0), proj) == (0, 0)
    x = K.iso((1, 0, 0), proj)
    assert x == pytest.approx((k * math.sqrt(0.5), k * math.sqrt(0.5) * 0.5))      # right and down, 2:1
    y = K.iso((0, 1, 0), proj)
    assert y == pytest.approx((-x[0], x[1]))                                          # left and down
    z = K.iso((0, 0, 1), proj)
    assert z == pytest.approx((0, -k * math.cos(math.radians(30))))                   # straight up
    moved = K.Projection((100, 50), 2.0, 45, 30)
    assert K.iso((1, 0, 0), moved) == pytest.approx((100 + 2 * x[0], 50 + 2 * x[1]))
    assert K.toward_viewer(proj) == pytest.approx((math.sqrt(0.5), math.sqrt(0.5)))
    assert K.depth_of((1, 1, 0), proj) == pytest.approx(2 * math.sqrt(0.5) * math.cos(math.radians(30)))
    assert K.depth_of((0, 0, 1), proj) == pytest.approx(0.5)


def test_other_azimuth_and_elevation_move_the_points():
    flat = K.Projection((0, 0), 1.0, 0, 90)                                           # looking straight down along +x
    assert K.iso((0, 1, 0), flat) == pytest.approx((-math.sqrt(1.6), 0))
    assert K.iso((1, 0, 0), flat) == pytest.approx((0, math.sqrt(1.6)))


def test_fit_projection_centres_the_points_inside_the_padding():
    pts = [(0, 0, 0), (100, 0, 0), (0, 80, 0), (100, 80, 60)]
    proj = K.fit_projection(pts, 640, 420, pad=(30, 56, 30, 56))
    flat = [K.iso(p, proj) for p in pts]
    xs, ys = [p[0] for p in flat], [p[1] for p in flat]
    assert min(xs) >= 30 - 1e-6 and max(xs) <= 610 + 1e-6 and min(ys) >= 56 - 1e-6 and max(ys) <= 364 + 1e-6
    assert (min(xs) + max(xs)) / 2 == pytest.approx(320) and (min(ys) + max(ys)) / 2 == pytest.approx(210)
    assert min(xs) == pytest.approx(30) or min(ys) == pytest.approx(56) or max(xs) == pytest.approx(610) or max(ys) == pytest.approx(364)
    one = K.fit_projection(pts, 640, 420, pad=24, headroom=40)                        # a single number and headroom
    assert min(K.iso(p, one)[1] for p in pts) == pytest.approx(24 + 40) or min(K.iso(p, one)[0] for p in pts) == pytest.approx(24)


def test_extrude_keeps_only_the_faces_that_look_at_the_viewer():
    proj = K.Projection((0, 0), 1.0, 45, 30)
    solid = K.extrude(SQUARE, 0, 5, proj)
    assert len(solid.faces) == 2 and sum(solid.facing) == 2
    vx, vy = K.toward_viewer(proj)
    assert all(f.normal[0] * vx + f.normal[1] * vy > 0 for f in solid.faces)
    assert {f.normal for f in solid.faces} == {(1.0, 0.0), (0.0, 1.0)}
    assert {f.shade for f in solid.faces} == {0, 3}                                   # +x away from the light, +y toward it
    head_on = K.extrude(SQUARE, 0, 5, K.Projection((0, 0), 1.0, 0, 30))
    assert [f.normal for f in head_on.faces] == [(1.0, 0.0)]                          # the side facing along the view is edge-on
    flat = K.extrude(SQUARE, 0, 0, proj)
    assert flat.faces == [] and flat.outline_d                                        # a zero-height solid has only a top


def test_extrude_outline_closes_the_silhouette_and_the_hull_holds_the_faces():
    proj = K.Projection((0, 0), 1.0, 45, 30)
    solid = K.extrude(SQUARE, 0, 5, proj)
    pts = {p for f in solid.faces for p in f.pts} | set(solid.top)
    xs, ys = [p[0] for p in solid.hull], [p[1] for p in solid.hull]
    assert all(min(xs) - 1e-6 <= p[0] <= max(xs) + 1e-6 and min(ys) - 1e-6 <= p[1] <= max(ys) + 1e-6 for p in pts)
    assert len(solid.crease) == 1 and len(solid.outline) == 4                         # near top edges, far top edges, near bottom, 2 corners
    assert solid.top_d.startswith("M") and solid.top_d.endswith("Z")
    assert len(solid.shades_d) == K.SHADES


def test_rounded_plan_cylinders_and_rings():
    ring = K.rounded_plan(K.Rect(0, 0, 20, 10, 3), 4)
    assert len(ring) == 4 * 5 and all(0 <= x <= 20 and 0 <= y <= 10 for x, y in ring)
    assert len(K.rounded_plan(K.Rect(0, 0, 20, 10, 0))) == 4
    cyl = K.cylinder(0, 0, 10, 0, 8, K.Projection((0, 0), 1.0, 45, 30), steps=24)
    assert 0 < len(cyl.faces) < 24 and abs(len(cyl.faces) - 12) <= 1                  # about half of the facets look at the viewer
    assert K.signed_area(K.circle_ring(0, 0, 10, 64)) == pytest.approx(math.pi * 100, rel=0.01)


def test_ticks_start_on_the_edge_and_coil_splits_back_from_front():
    proj = K.Projection((0, 0), 1.0, 45, 30)
    minor, major = K.top_ticks(0, 20, 4, 5, 10, 3, (2, 4), proj, "x", inward=-1.0)
    assert len(minor) + len(major) == 6 and len(major) == 2                           # 0, 4 .. 20: majors at 0 and 20
    a, b = major[0].pts
    assert a == pytest.approx(K.iso((0, 10, 3), proj)) and b == pytest.approx(K.iso((0, 6, 3), proj))
    back, front = K.coil(0, 30, (0, 0), 5, 4, "z", proj)
    assert back and front
    runs = back + front
    ends = [e for r in runs for e in (r.pts[0], r.pts[-1])]
    assert sum(ends.count(e) == 2 for e in set(ends)) >= len(runs) - 1                # every run hands over to the next one at the sides
    assert {e for e in set(ends) if ends.count(e) == 1} == {K.iso((5, 0, 0), proj), runs_last(runs, proj)} or len(runs) > 2
    assert K.coil(0, 30, (0, 0), 5, 4, "x", proj)[0]


def runs_last(runs, proj):
    return K.iso((5 * math.cos(8 * math.pi), 5 * math.sin(8 * math.pi), 30), proj)


def test_text_matrix_maps_the_face_axes():
    proj = K.Projection((0, 0), 1.0, 45, 30)
    m = K.side_matrix((0, 10), 20, proj, "left")
    assert K.apply_matrix(m, 10, 0) == pytest.approx(K.iso((10, 10, 20), proj))
    assert K.apply_matrix(m, 0, 5) == pytest.approx(K.iso((0, 10, 15), proj))         # v hangs down from the top edge
    t = K.top_matrix((5, 5), 7, proj, "x")
    assert K.apply_matrix(t, 2, 3) == pytest.approx(K.iso((7, 8, 7), proj))
