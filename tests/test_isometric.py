"""Isometric diagrams: painter's order, the piece schema, the figure and its gates (line ends included)."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from vitruvius_hoard.diagrams import DEFAULT_PROFILE, Diagram, make, pick_type, type_card
from vitruvius_hoard.diagrams import iso as K
from vitruvius_hoard.diagrams import isometric as I
from vitruvius_hoard.diagrams.examples import CACHE, CHEST
from vitruvius_hoard.diagrams.render import DEFAULT, layout_of
from vitruvius_hoard.diagrams.spec import MAX_PIECES

PLUNGER = {"type": "isometric", "title": "Plunger with spring", "figure": 2, "hint": "Press the plunger", "readout": "k 4 N/mm",
           "azimuth": 40, "pieces": [
               {"id": "base", "kind": "slab", "plan": {"x": 0, "y": 0, "w": 120, "d": 90}, "z": 0, "h": 6, "tone": "lo", "details": ["screws", "groove"]},
               {"id": "guide", "kind": "ring", "plan": {"cx": 60, "cy": 45, "r": 22, "r2": 14}, "z": 6, "h": 6, "details": ["ticks"]},
               {"id": "spring", "kind": "coil", "plan": {"cx": 25, "cy": 25, "r": 8}, "z": 6, "h": 40, "turns": 8},
               {"id": "rod", "kind": "post", "plan": {"cx": 25, "cy": 25, "r": 2.5}, "z": 6, "h": 52, "tone": "hi"},
               {"id": "cap", "kind": "plate", "plan": {"x": 14, "y": 14, "w": 22, "d": 22, "corner": 3}, "z": 58, "h": 3, "label": "K"},
               {"id": "knob", "kind": "cylinder", "plan": {"cx": 95, "cy": 60, "r": 12}, "z": 6, "h": 10, "lit": True,
                "details": ["knurl", "ticks"], "label": "SET"},
               {"id": "rule", "kind": "plate", "plan": {"x": 70, "y": 10, "w": 40, "d": 8}, "z": 6, "h": 2, "details": ["ticks"]}]}


def failed(result):
    return [g for g in result["gates"] if not g["ok"]]


def gate(result, gid):
    return next(g for g in result["gates"] if g["id"] == gid)


def spec(**changes):
    out = copy.deepcopy(CHEST)
    out.update(changes)
    return out


# ------------------------------------------------------------------------------------------------ camera maths
# ------------------------------------------------------------------------------------------------ solids and faces
# ------------------------------------------------------------------------------------------------ painter's order
def node(i, x0, y0, z0, x1, y1, z1, role="solid"):
    return I.Node(i, role, (x0, y0, z0, x1, y1, z1))


def test_depth_order_is_back_to_front():
    proj = K.Projection((0, 0), 1.0, 45, 30)
    far, near = node("far", 0, 0, 0, 10, 10, 10), node("near", 10, 10, 0, 20, 20, 10)
    order, conflicts = I.paint_order([near, far], proj)
    assert [([near, far][i]).id for i in order] == ["far", "near"] and not conflicts
    assert K.depth_of((15, 15, 5), proj) > K.depth_of((5, 5, 5), proj)


def test_a_part_on_the_far_corner_of_a_big_base_is_still_painted_after_the_base():
    proj = K.Projection((0, 0), 1.0, 45, 30)
    base, little = node("base", 0, 0, 0, 200, 200, 6), node("little", 0, 0, 6, 10, 10, 16)
    assert K.depth_of((5, 5, 11), proj) < K.depth_of((100, 100, 3), proj)             # sorting by centre would get it wrong
    order, conflicts = I.paint_order([little, base], proj)
    assert [[little, base][i].id for i in order] == ["base", "little"] and not conflicts


def test_a_coil_is_painted_back_half_then_the_rod_then_front_half():
    proj = K.Projection((0, 0), 1.0, 45, 30)
    nodes = [node("rod", -2, -2, 0, 2, 2, 30), node("spring", -8, -8, 0, 8, 8, 30, "back"), node("spring", -8, -8, 0, 8, 8, 30, "front"),
             node("plate", -20, -20, -4, 20, 20, 0)]
    order, conflicts = I.paint_order(nodes, proj)
    names = [(nodes[i].id, nodes[i].role) for i in order]
    assert names == [("plate", "solid"), ("spring", "back"), ("rod", "solid"), ("spring", "front")] and not conflicts


def test_layout_paints_the_example_from_the_floor_up():
    lay = layout_of(Diagram.model_validate(CACHE))
    ranks = {g.piece.id: g.rank for g in lay["geos"]}
    assert ranks["base"] == 0 and ranks["set-0"] < ranks["set-1"] < ranks["set-2"] < ranks["set-3"] < ranks["top"] < ranks["index"]
    assert ranks["set-2"] < ranks["pull-2"] and not lay["conflicts"]


# ------------------------------------------------------------------------------------------------ the schema
def test_validation_says_what_is_wrong():
    with pytest.raises(ValueError, match=r"piece 'a' \(slab\) needs plan \{x, y, w, d\}"):
        Diagram.model_validate({"type": "isometric", "pieces": [{"id": "a", "kind": "slab", "plan": {"cx": 1, "cy": 1, "r": 2}}]})
    with pytest.raises(ValueError, match=r"piece 'a' \(cylinder\) needs plan \{cx, cy, r\}"):
        Diagram.model_validate({"type": "isometric", "pieces": [{"id": "a", "kind": "cylinder", "plan": {"x": 1, "y": 1, "w": 2, "d": 2}}]})
    with pytest.raises(ValueError, match="w and d must be above 0"):
        Diagram.model_validate({"type": "isometric", "pieces": [{"id": "a", "plan": {"x": 0, "y": 0, "w": 0, "d": 5}}]})
    with pytest.raises(ValueError, match="r must be above 0"):
        Diagram.model_validate({"type": "isometric", "pieces": [{"id": "a", "kind": "post", "plan": {"cx": 0, "cy": 0, "r": -1}}]})
    with pytest.raises(ValueError, match="h must be above 0"):
        Diagram.model_validate({"type": "isometric", "pieces": [{"id": "a", "plan": {"x": 0, "y": 0, "w": 5, "d": 5}, "h": 0}]})
    with pytest.raises(ValueError, match="r2"):
        Diagram.model_validate({"type": "isometric", "pieces": [{"id": "a", "kind": "ring", "plan": {"cx": 0, "cy": 0, "r": 5, "r2": 7}}]})
    with pytest.raises(ValueError, match="detail 'knurl' only applies to cylinder"):
        Diagram.model_validate({"type": "isometric", "pieces": [{"id": "a", "plan": {"x": 0, "y": 0, "w": 5, "d": 5}, "details": ["knurl"]}]})
    with pytest.raises(ValueError, match="cannot carry a label"):
        Diagram.model_validate({"type": "isometric", "pieces": [{"id": "a", "kind": "coil", "plan": {"cx": 0, "cy": 0, "r": 5}, "label": "x"}]})
    with pytest.raises(ValueError, match="appears twice"):
        Diagram.model_validate({"type": "isometric", "pieces": [{"id": "a", "plan": {"x": 0, "y": 0, "w": 5, "d": 5}}] * 2})
    with pytest.raises(ValueError, match="needs pieces"):
        Diagram.model_validate({"type": "isometric"})
    with pytest.raises(ValueError, match="only one piece can be lit"):
        Diagram.model_validate(spec(pieces=[{**p, "lit": True} for p in CHEST["pieces"][:2]]))
    with pytest.raises(ValueError):
        Diagram.model_validate(spec(figure=0))
    with pytest.raises(ValueError):
        Diagram.model_validate(spec(hint="x" * 41))


def test_at_most_150_pieces():
    many = [{"id": f"p{i}", "plan": {"x": i * 3, "y": 0, "w": 2, "d": 2}, "h": 2} for i in range(MAX_PIECES)]
    assert len(Diagram.model_validate({"type": "isometric", "pieces": many}).pieces) == MAX_PIECES
    with pytest.raises(ValueError, match="at most 150 pieces"):
        Diagram.model_validate({"type": "isometric", "pieces": many + [{"id": "extra", "plan": {"x": 0, "y": 9, "w": 2, "d": 2}}]})


def test_a_small_model_can_be_loose_with_kinds_and_defaults():
    d = Diagram.model_validate({"type": "isometric", "pieces": [
        {"id": "a", "kind": "box", "plan": {"x": 0, "y": 0, "w": 10, "d": 10}}, {"id": "b", "kind": "Disc", "plan": {"cx": 5, "cy": 5, "r": 2}, "z": 4},
        {"id": "c", "kind": "spring", "plan": {"cx": 20, "cy": 5, "r": 2}}, {"id": "e", "kind": "pin", "plan": {"cx": 30, "cy": 5, "r": 1}}]})
    assert [p.kind for p in d.pieces] == ["slab", "cylinder", "coil", "post"] and [p.h for p in d.pieces] == [8, 8, 12, 12]
    assert d.figure == 1 and d.azimuth == 45 and d.elevation == 30 and d.pieces[0].tone == "mid" and not d.pieces[0].lit


def test_the_pattern_and_card_are_in_the_catalogue():
    for text in ("cómo funciona una caché", "explica con un objeto el cifrado", "how it works: a lock", "mecanismo de un cerrojo",
                 "isométrico de una cola", "show the mechanism of the cache", "explain with an object how a hash works"):
        pick = pick_type(text)
        assert pick["type"] == "isometric" and pick["pattern"] == "mechanism", text
    assert pick_type("diagrama de secuencia del login")["type"] == "sequence"
    card = type_card("isometric")
    assert card["pattern"] == "mechanism" and "pieces[" in card["fields"] and any("lit" in r for r in card["rules"])
    assert Diagram.model_validate(card["example"]).type == "isometric"


# ------------------------------------------------------------------------------------------------ the figure and its gates
@pytest.mark.parametrize("example", [CHEST, CACHE, PLUNGER], ids=["chest", "cache", "plunger"])
def test_examples_pass_every_gate_in_both_modes(example):
    d = Diagram.model_validate(example)
    result = make(d)
    assert result["ok"], failed(result)
    ids = {g["id"] for g in result["gates"]}
    assert {"one_lit", "no_interpenetration", "depth_order", "label_size", "label_fits", "label_contrast_light", "label_contrast_dark",
            "frame_text_fit", "inside_canvas", "line_ends", "contrast_light", "contrast_dark"} <= ids
    for mode in ("light", "dark"):
        text = result["svg"][mode]
        root = ET.fromstring(text)
        assert root.attrib["viewBox"] == "0 0 640 420" and root.attrib["role"] == "img"
        assert f"FIG {d.figure}" in text and d.title.upper() in text and d.hint.upper() in text and d.readout in text
        assert DEFAULT[mode]["paper"] in text
    assert result["svg"]["light"] != result["svg"]["dark"]
    assert len(make(d)["svg"]["light"]) == len(result["svg"]["light"])                # deterministic


def test_the_cache_example_is_a_chest_of_drawers_of_8_to_15_pieces():
    d = Diagram.model_validate(CACHE)
    assert 8 <= len(d.pieces) <= 15 and sum(p.lit for p in d.pieces) == 1
    svg = make(d)["svg"]["light"]
    assert svg.count("data-piece=") == len(d.pieces)
    assert "SET 2 HIT" in svg and svg.count("<text") >= 5                              # labels engraved on the faces plus the frame
    assert "transform=\"matrix(" in svg


def test_tones_come_from_the_profile_and_the_lit_piece_takes_the_accent():
    profile = {"name": "x", "font": "Lora, serif",
               "light": {**DEFAULT["light"], "accent": "#c2185b", "paper": "#fffdf7", "ink": "#2a1f14"}, "dark": DEFAULT["dark"]}
    result = make(Diagram.model_validate(CHEST), profile)
    assert result["ok"], failed(result)
    light = result["svg"]["light"]
    assert "#c2185b" in light and "#fffdf7" in light and "#2a1f14" in light and "Lora" in light
    pal = I.palette(profile["light"])
    assert len(set(pal["shades"])) == 4 and pal["shades"][0] != pal["shades"][3] and not pal["dark"]
    assert I.palette(DEFAULT["dark"])["dark"]
    for shade in pal["shades"]:
        assert shade != pal["paper"]


def test_zero_or_two_lit_pieces_fail_the_gate():
    d = Diagram.model_validate(CHEST)
    for p in d.pieces:
        p.lit = False
    assert "one_lit" in make(d)["failed"]
    d.pieces[0].lit = d.pieces[1].lit = True                                           # validation only runs on input, the gate is the net
    assert not gate(make(d), "one_lit")["ok"]


def test_solids_that_interpenetrate_at_the_same_height_are_reported_but_stacking_is_not():
    clash = copy.deepcopy(CHEST)
    clash["pieces"][4]["plan"]["y"] = 20                                               # drawer-a now crosses drawer-b in plan, but not in z
    assert make(Diagram.model_validate(clash))["ok"]
    clash["pieces"][4]["z"] = 20                                                       # now it shares height with drawer-b (26..44)
    result = make(Diagram.model_validate(clash))
    assert "no_interpenetration" in result["failed"]
    assert any("drawer-a" in i and "drawer-b" in i for i in gate(result, "no_interpenetration")["items"])
    touching = {"type": "isometric", "pieces": [{"id": "a", "plan": {"x": 0, "y": 0, "w": 10, "d": 10}, "h": 5, "lit": True},
                                                {"id": "b", "plan": {"x": 10, "y": 0, "w": 10, "d": 10}, "h": 5},
                                                {"id": "c", "plan": {"x": 0, "y": 0, "w": 10, "d": 10}, "z": 5, "h": 5}]}
    assert make(Diagram.model_validate(touching))["ok"]                                # side by side and stacked share only faces
    circles = {"type": "isometric", "pieces": [{"id": "a", "kind": "cylinder", "plan": {"cx": 0, "cy": 0, "r": 5}, "lit": True},
                                               {"id": "b", "kind": "post", "plan": {"cx": 3, "cy": 0, "r": 2}},
                                               {"id": "c", "kind": "ring", "plan": {"cx": 20, "cy": 0, "r": 6, "r2": 3}, "details": ["ticks"]},
                                               {"id": "d", "kind": "slab", "plan": {"x": 18, "y": -2, "w": 4, "d": 4}}]}
    result = make(Diagram.model_validate(circles))
    assert sorted(gate(result, "no_interpenetration")["items"]) == ["a / b", "c / d"]  # even inside a ring's hole


def test_a_label_too_long_for_its_piece_fails_size():
    d = copy.deepcopy(CHEST)
    d["pieces"].append({"id": "tag", "plan": {"x": 0, "y": 0, "w": 8, "d": 6}, "z": 6, "h": 2, "label": "ABCDEFGH"})
    result = make(Diagram.model_validate(d))
    assert "label_size" in result["failed"] and gate(result, "label_size")["items"][0].startswith("tag 'ABCDEFGH' would be")


def test_bad_contrast_in_a_profile_is_caught_for_labels_and_text():
    bad = {"light": {**DEFAULT["light"], "ink": "#e6e6e6"}, "dark": DEFAULT["dark"]}
    result = make(Diagram.model_validate(CHEST), bad)
    assert "label_contrast_light" in result["failed"] and "contrast_light" in result["failed"]
    assert gate(result, "label_contrast_dark")["ok"]


def test_frame_text_that_does_not_fit_is_reported():
    d = Diagram.model_validate(spec(title="A very long title that will never fit in the frame of the figure at all", figure=12))
    result = make(d)
    assert "frame_text_fit" in result["failed"]


def test_everything_inside_the_canvas_or_the_gate_fails():
    d = Diagram.model_validate(CHEST)
    lay = layout_of(d)
    assert I.gates(d, DEFAULT_PROFILE, lay)[[g["id"] for g in I.gates(d, DEFAULT_PROFILE, lay)].index("inside_canvas")]["ok"]
    for g in lay["geos"]:
        if g.solid:
            xs = [x for x, _ in g.solid.hull]
            assert min(xs) >= 30 and max(xs) <= 610                                    # inside the padding the fit leaves
    lay["geos"][0].solid.hull.append((700.0, 200.0))
    out = {g["id"]: g for g in I.gates(d, DEFAULT_PROFILE, lay)}
    assert not out["inside_canvas"]["ok"] and "outside" in out["inside_canvas"]["items"][0]
    lay = layout_of(d)
    lay["geos"][0].solid.hull.append((60.0, 32.0))                                     # on top of the figure number
    assert any("figure number" in i or "fig" in i for i in {g["id"]: g for g in I.gates(d, DEFAULT_PROFILE, lay)}["inside_canvas"]["items"])


# ------------------------------------------------------------------------------------------------ line ends
def square_solid(proj):
    return K.slab_of(K.Rect(0, 0, 40, 30, 0), 0, 4, proj, 4)


def test_line_ends_pass_when_ticks_hang_from_an_edge():
    proj = K.Projection((300, 200), 3.0, 45, 30)
    solid = square_solid(proj)
    minor, major = K.top_ticks(6, 34, 4, 5, 30, 4, (2, 4), proj, "x", inward=-1.0)
    refs = [I.LineRef(l.pts, "tick", "plate", 1) for l in minor + major]
    assert I.floating_ends(refs, [("plate", 0, solid)], []) == []


def test_line_ends_fail_for_a_tick_floating_on_a_bare_face():
    proj = K.Projection((300, 200), 3.0, 45, 30)
    solid = square_solid(proj)
    # the same ruler pulled 10 units in from the edge: nothing for it to hang from
    minor, major = K.top_ticks(6, 34, 4, 5, 20, 4, (2, 4), proj, "x", inward=-1.0)
    refs = [I.LineRef(l.pts, "tick", "plate", 1) for l in minor + major]
    bad = I.floating_ends(refs, [("plate", 0, solid)], [])
    assert len(bad) == len(refs) and "tick on 'plate' ends in the air" in bad[0]


def test_line_ends_a_seam_needs_both_ends_and_a_tick_needs_one():
    proj = K.Projection((300, 200), 3.0, 45, 30)
    solid = square_solid(proj)
    seam = K.side_seam(K.Rect(0, 0, 40, 30, 0), 2, proj, 4)[0]
    assert I.floating_ends([I.LineRef(seam.pts, "seam", "plate", 1)], [("plate", 0, solid)], []) == []
    cut = K.Line(seam.pts[:-1] + [((seam.pts[-2][0] + seam.pts[-1][0]) / 2, (seam.pts[-2][1] + seam.pts[-1][1]) / 2 - 3)])
    assert len(I.floating_ends([I.LineRef(cut.pts, "seam", "plate", 1)], [("plate", 0, solid)], [])) == 1
    one_rooted = K.Line([seam.pts[0], (seam.pts[0][0] + 9, seam.pts[0][1] - 9)])
    assert I.floating_ends([I.LineRef(one_rooted.pts, "tick", "plate", 1)], [("plate", 0, solid)], []) == []
    assert len(I.floating_ends([I.LineRef(one_rooted.pts, "seam", "plate", 1)], [("plate", 0, solid)], [])) == 1


def test_line_ends_accept_dots_other_strokes_and_a_fill_painted_later():
    proj = K.Projection((300, 200), 3.0, 45, 30)
    solid = square_solid(proj)
    air = K.Line([(100.0, 100.0), (130.0, 100.0)])
    ref = I.LineRef(air.pts, "groove", "plate", 1)
    assert len(I.floating_ends([ref], [("plate", 0, solid)], [])) == 1
    assert I.floating_ends([ref], [("plate", 0, solid)], [((100.0, 100.0), 1.0), ((130.0, 100.0), 1.0)]) == []          # dots at both ends
    other = I.LineRef([(100.0, 80.0), (100.0, 120.0)], "groove", "plate", 1, False)
    assert I.floating_ends([ref, other], [], []) != []                                                                     # only one end touches
    cover = K.slab_of(K.Rect(0, 0, 400, 400, 0), 0, 400, K.Projection((0, 0), 3.0, 45, 30))
    hidden = [("later", 5, cover)]
    assert I._in_hull((100.0, 100.0), cover.hull) and not I._in_hull((9000.0, 9000.0), cover.hull)
    assert I.floating_ends([ref], hidden, []) == []                                                                        # under a later fill
    assert I.floating_ends([I.LineRef(air.pts, "groove", "plate", 9)], hidden, []) != []                                  # painted before it: no


def test_the_gate_catches_a_stray_line_in_a_real_figure_and_passes_without_it():
    d = Diagram.model_validate(CACHE)
    lay = layout_of(d)
    clean = [g for g in I.gates(d, DEFAULT_PROFILE, lay) if g["id"] == "line_ends"][0]
    assert clean["ok"] and clean["detail"].startswith("line ends: 0")
    refs = I.line_refs(lay)
    assert any(r.tag == "tick" for r in refs) and any(r.tag == "seam" for r in refs) and any(r.tag == "knurl" for r in refs)
    lay["geos"][0].decos.append(I.Deco("groove", "faint", [K.Line([(300.0, 20.0), (340.0, 25.0)])]))
    stray = [g for g in I.gates(d, DEFAULT_PROFILE, lay) if g["id"] == "line_ends"][0]
    assert not stray["ok"] and stray["detail"] == "line ends: 1" and "groove on 'base'" in stray["items"][0]


def test_coils_end_on_their_seats_and_rings_ticks_on_their_rim():
    d = Diagram.model_validate(PLUNGER)
    lay = layout_of(d)
    tags = {r.tag for r in I.line_refs(lay)}
    assert {"coil", "seat", "tick", "knurl", "hole"} <= tags
    assert gate(make(d), "line_ends")["ok"]


# ------------------------------------------------------------------------------------------------ the flow around it
def test_svg_is_self_contained_and_scales_strokes_on_screen():
    svg = make(Diagram.model_validate(CACHE))["svg"]["light"]
    assert "vector-effect=\"non-scaling-stroke\"" in svg and "http://" not in svg.replace("http://www.w3.org/2000/svg", "")
    assert "<script" not in svg and re.search(r'<filter id="iso-blur"', svg)


ROOT = Path(__file__).resolve().parent.parent


def test_the_docs_example_is_the_cache_example_and_its_drawings_exist():
    spec_file = ROOT / "docs" / "examples" / "isometric-cache.json"
    assert json.loads(spec_file.read_text(encoding="utf-8")) == CACHE
    for mode in ("light", "dark"):
        text = (ROOT / "docs" / "examples" / f"isometric-cache-{mode}.svg").read_text(encoding="utf-8")
        assert ET.fromstring(text).attrib["viewBox"] == "0 0 640 420" and "SET-ASSOCIATIVE CACHE" in text


def test_the_ported_kit_keeps_its_licence_notice():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    header = (ROOT / "vitruvius_hoard" / "diagrams" / "iso.py").read_text(encoding="utf-8")[:2500]
    for text in (notices, header):
        assert "Copyright (c) 2026 Ryan" in text and "Permission is hereby granted, free of charge" in text
