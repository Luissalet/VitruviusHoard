"""Slop audit (unslop pack, score, mode, passes, direction brief), presets (catalogue, registry, pick, apply), Figma import."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import FakeLink, default_probe, make_services
from vitruvius_hoard import figma, lint, presets, slop_audit
from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.rules import registry
from vitruvius_hoard.rules.unslop import SIGN_COVERAGE, implemented

FIX = Path(__file__).resolve().parent / "fixtures"
SLOPPY = (FIX / "pages" / "sloppy.html").read_text(encoding="utf-8")
FRAME = json.loads((FIX / "figma" / "frame_nodes.json").read_text(encoding="utf-8"))


def snap(width, *els, height=900, page_height=3000):
    out = []
    for i, e in enumerate(els):
        d = {"i": i, "p": e.get("p", -1), "tag": e.get("tag", "div"), "r": e.get("r", [0, 0, 100, 40]), "s": {"fs": 16, "fw": "400", "ff": "newsreader", **e.get("s", {})}}
        for k in ("c", "t", "tl", "act", "id"):
            if k in e:
                d[k] = e[k]
        if "t" in e and "tl" not in e:
            d["tl"] = len(e["t"])
        out.append(d)
    return {"width": width, "height": height, "page_height": page_height, "page_width": width, "els": out}


def run(rule, *snaps, html=""):
    p = default_probe(dom={str(s["width"]): s for s in snaps})
    return [f for f in lint.run_lint(p, html, only=[rule])["findings"] if f["check_id"] == rule]


def test_every_unslop_rule_is_registered_runnable_and_credited():
    lint.ensure_rules()
    rows = registry.list_rules(pack="unslop")
    assert len(rows) == len(implemented()) >= 20 and all(r["runnable"] for r in rows)
    assert all(r["source"] == "unslop" and "CC BY 4.0" in r["reference"] for r in rows)
    for sign, ids in SIGN_COVERAGE.items():
        assert any(registry.get_rule(i) for i in ids), sign


def test_measured_colour_rules_fire_and_carry_boxes():
    grad = {"tag": "span", "r": [10, 20, 300, 60], "t": "future of work", "s": {"bg_clip": "text", "bgi": "linear-gradient(90deg, rgb(253, 230, 138), rgb(244, 114, 182))"}}
    found = run("unslop/gradient-text-measured", snap(1440, grad), snap(390, grad))
    assert found and found[0]["evidence"]["boxes"] == [[10, 20, 300, 60]] and found[0]["evidence"]["widths"] == [390, 1440]
    glow = {"r": [0, 0, 300, 200], "t": "card", "s": {"sh": "rgba(139, 92, 246, 0.55) 0px 10px 30px 0px"}}
    grey = {"r": [0, 0, 300, 200], "t": "card", "s": {"sh": "rgba(0, 0, 0, 0.2) 0px 10px 30px 0px"}}
    assert run("unslop/saturated-shadow", snap(1440, glow)) and not run("unslop/saturated-shadow", snap(1440, grey))
    hero = {"tag": "section", "r": [0, 60, 1440, 600], "s": {"bgi": "linear-gradient(135deg, rgb(109, 40, 217) 0%, rgb(139, 92, 246) 45%, rgb(236, 72, 153) 100%)"}}
    assert run("unslop/purple-gradient-hero", snap(1440, hero))
    teal = {**hero, "s": {"bgi": "linear-gradient(135deg, rgb(13, 148, 136), rgb(20, 184, 166))"}}
    assert not run("unslop/purple-gradient-hero", snap(1440, teal))


def test_spacing_sizes_cards_and_type_rules():
    off = [{"r": [0, i * 50, 300, 40], "t": "x", "s": {"pad": [13, 22, 13, 22], "gap": 18}} for i in range(6)]
    on = [{"r": [0, i * 50, 300, 40], "t": "x", "s": {"pad": [12, 24, 12, 24], "gap": 16}} for i in range(6)]
    assert run("unslop/off-grid-spacing", snap(1440, *off)) and not run("unslop/off-grid-spacing", snap(1440, *on))
    sizes = [{"tag": "p", "r": [0, i * 40, 300, 30], "t": "some text", "s": {"fs": 10 + i * 3}} for i in range(10)]
    assert run("unslop/too-many-sizes", snap(1440, *sizes)) and not run("unslop/too-many-sizes", snap(1440, *sizes[:5]))
    row = [{"p": 0, "r": [0, 0, 1200, 300]}] + [{"p": 0, "r": [40 + k * 380, 50, 360, 220], "t": "card text here", "s": {"bg": "rgb(255, 255, 255)", "sh": "rgba(0,0,0,.1) 0px 4px 12px 0px"}} for k in range(3)]
    row[0] = {"r": [0, 0, 1200, 300], "s": {"bg": "rgb(240, 240, 240)"}}
    assert run("unslop/uniform-card-grid", snap(1440, *row))
    inter = [{"tag": "p", "r": [0, i * 40, 600, 30], "t": "x" * 80, "s": {"ff": "Inter"}} for i in range(4)]
    assert run("unslop/single-default-sans", snap(1440, *inter))
    assert not run("unslop/single-default-sans", snap(1440, *[{**e, "s": {"ff": "Newsreader"}} for e in inter]))
    caps = [{"tag": "span", "r": [0, i * 30, 80, 16], "t": "Speed", "s": {"fs": 11, "tt": "uppercase", "ls": 2.2}} for i in range(3)]
    assert run("unslop/tracked-caps-measured", snap(1440, *caps))


def test_copy_icon_and_hero_rules():
    assert run("unslop/greeting-headline", snap(1440, {"tag": "h1", "r": [0, 100, 900, 80], "t": "Welcome to the future of work"}))
    assert not run("unslop/greeting-headline", snap(1440, {"tag": "h1", "r": [0, 100, 900, 80], "t": "Shipments this week"}))
    nav = [{"tag": "nav", "r": [0, 0, 1440, 60]}, {"tag": "a", "p": 0, "r": [100, 10, 120, 30], "t": "\U0001F680 Features"}]
    assert run("unslop/emoji-in-ui", snap(1440, *nav))
    btns = [{"tag": "a", "r": [400 + k * 200, 500, 180, 50], "t": "Go", "s": {"bg": "rgb(255, 255, 255)"}} for k in range(3)]
    assert run("unslop/too-many-ctas", snap(1440, *btns)) and not run("unslop/too-many-ctas", snap(1440, *btns[:2]))
    proof = {"tag": "p", "r": [0, 600, 600, 20], "t": "Trusted by 500+ teams and 10,000+ happy users"}
    assert run("unslop/unsourced-proof", snap(1440, proof))


def test_static_motion_rules_read_the_source():
    assert run("unslop/hover-scale", html="<style>.btn:hover{transform:scale(1.08)}</style><a class=btn>x</a>")
    assert not run("unslop/hover-scale", html="<style>.btn:hover{transform:scale(1.01)}</style><a class=btn>x</a>")
    float_css = "<style>@keyframes float{50%{transform:translateY(-18px)}} .orb{animation: float 4s ease-in-out infinite}</style><div class=orb></div>"
    assert run("unslop/floating-loop", html=float_css)
    assert run("unslop/hover-scale", html=SLOPPY) and run("unslop/floating-loop", html=SLOPPY)


# ---------------------------------------------------------------- the audit

def _f(rid, level="warning", scope="color", pack="unslop"):
    return {"check_id": rid, "level": level, "tier": registry.TIER_OF[level], "scope": scope, "pack": pack, "title": rid, "fix": "do it"}


def test_score_mode_and_ordered_passes():
    assert slop_audit.score([])["mode"] == "none"
    light = [_f("unslop/neon-border", "advisory"), _f("unslop/greeting-headline", "warning", "copy")]
    assert slop_audit.score(light)["mode"] == "light"
    heavy = [_f(f"unslop/x{k}", "warning", s) for k, s in enumerate(["color", "type", "copy", "layout", "motion", "imagery"])]
    heavy += [_f("unslop/off-grid-spacing", "warning", "layout")]
    s = slop_audit.score(heavy)
    assert s["mode"] == "heavy" and s["slop_score"] == 63 and s["signs"] == 7
    plan = slop_audit.plan(heavy, "heavy")
    order = [p["pass"] for p in plan["passes"]]
    assert order == [p for p in slop_audit.PASSES if p in order] and order[0] == "spacing"
    assert slop_audit.plan([], "none")["passes"] == [] and "leave the page" in slop_audit.plan([], "none")["summary"]
    # a waived sign does not count; a craft finding is in the plan but not in the score
    assert slop_audit.score([{**heavy[0], "waived": True}])["signs"] == 0
    assert slop_audit.score([_f("craft/hero-vh", "error", "layout", "craft")])["signs"] == 0


def _sloppy_dom(width):
    hero = {"tag": "section", "r": [0, 60, width, 600], "s": {"bgi": "linear-gradient(135deg, rgb(109, 40, 217), rgb(236, 72, 153))"}}
    h1 = {"tag": "h1", "p": 0, "r": [100, 200, min(900, width - 40), 80], "t": "Welcome to the future of work!", "s": {"fs": 66, "fw": "900", "ff": "Inter"}}
    nav = {"tag": "a", "r": [40, 10, 120, 30], "t": "\U0001F680 Features", "s": {"ff": "Inter"}}
    body = [{"tag": "p", "r": [0, 700 + i * 40, 600, 30], "t": "Supercharge your workflow " * 4, "s": {"ff": "Inter"}} for i in range(3)]
    return snap(width, hero, h1, nav, *body)


def test_audit_run_on_a_render_with_eight_widths(tmp_path):
    dom = {str(w): _sloppy_dom(w) for w in slop_audit.AUDIT_WIDTHS}
    svc = make_services(tmp_path, probe_overrides={"dom": dom})
    try:
        out = slop_audit.run(svc, html=SLOPPY)
        assert out["widths"] == slop_audit.AUDIT_WIDTHS and out["display_width"] == 1440
        ids = {f["check_id"] for f in out["findings"]}
        assert {"unslop/purple-gradient-hero", "unslop/greeting-headline", "unslop/emoji-in-ui", "unslop/hover-scale"} <= ids
        assert out["mode"] in ("heavy", "light") and out["slop_score"] > 0
        hero = next(f for f in out["findings"] if f["check_id"] == "unslop/purple-gradient-hero")
        assert hero["boxes"] and hero["pass"] == "color" and len(hero["evidence"]["widths"]) == 8
        assert slop_audit.get(svc, out["render_id"])["slop_score"] == out["slop_score"]
        again = slop_audit.run(svc, render_id=out["render_id"])           # 8 widths already: no re-render
        assert again["render_id"] == out["render_id"]
        compact = call_tool(svc, "design_slop_audit", {"render_id": out["render_id"]})
        assert compact["mode"] == out["mode"] and len(compact["screenshots"]) == 8 and compact["plan"]["mode"] == out["mode"]
    finally:
        svc.stop()


def test_direction_brief_from_the_model_and_the_fallback(tmp_path):
    reply = ("Product: A shipment tracker for small importers.\nCharacter: Calm and exact, like a customs ledger.\n"
             "Bright moment: The delayed count and the New shipment button.\nSignature: Container codes set in mono.\nAvoid: purple gradients, emoji, glows")
    svc = make_services(tmp_path, link=FakeLink(chat_text=reply))
    try:
        out = slop_audit.direction_brief(svc, text="SynthFlow tracks shipments for small importers and flags delays at customs.")
        assert out["source"] == "model" and out["product"].startswith("A shipment tracker") and out["text"].count("\n") == 4
    finally:
        svc.stop()
    svc = make_services(tmp_path / "b", link=FakeLink(chat_text="I cannot help with that."))
    try:
        out = slop_audit.direction_brief(svc, html=SLOPPY)
        assert out["source"] == "fallback" and all(out[k] for k in slop_audit.BRIEF_KEYS)
        with pytest.raises(ValueError):
            slop_audit.direction_brief(svc, text="hi")
    finally:
        svc.stop()


# ---------------------------------------------------------------- presets

def test_preset_catalogue_sources_and_contrast():
    cat = presets.catalogue()
    by = {}
    for p in cat:
        by.setdefault(p["source"], []).append(p)
    assert len(by["vitruvius"]) >= 20 and len(by["hallmark"]) == 50 and len(by["hoard"]) >= 10
    assert presets.get("hoard-writer")["tokens"]["colors"]["dark"]["primary"] == "#d5b575"
    for p in cat:
        light, dark = p["tokens"]["colors"]["light"], p["tokens"]["colors"]["dark"]
        assert {"background", "foreground", "primary", "primary-foreground", "muted", "border", "ring"} <= set(light) == set(dark)
        assert p["contrast"]["light_text"] >= 7 and p["contrast"]["dark_text"] >= 7, p["name"]
        assert p["contrast"]["light_primary"] >= 3 and p["contrast"]["dark_primary"] >= 3, p["name"]


def test_registry_item_has_the_shadcn_shape(client):
    item = client.get("/api/design/registry/ledger-ink.json").json()
    assert item["$schema"].endswith("registry-item.json") and item["type"] == "registry:theme" and item["name"] == "ledger-ink"
    assert item["cssVars"]["light"]["background"].startswith("oklch(") and "radius" in item["cssVars"]["theme"]
    index = client.get("/api/design/registry.json").json()
    assert index["$schema"].endswith("registry.json") and any(i["name"] == "hoard-hub" for i in index["items"])
    assert client.get("/api/design/registry/nope.json").status_code == 404
    listed = client.get("/api/presets", params={"source": "hoard"}).json()
    assert listed["count"] >= 10 and listed["presets"][0]["swatches"]["dark"]


def test_pick_uses_the_model_order_and_falls_back_to_keywords(tmp_path):
    keyword = presets.pick(None, "invoices and bookkeeping for a small bakery", use_model=False)
    assert keyword["source"] == "keywords" and len(keyword["candidates"]) == 3 and keyword["recommended"] == keyword["candidates"][0]["name"]
    short = [p["name"] for _, p, _ in presets.keyword_rank("invoices and bookkeeping for a small bakery")[:12]]
    svc = make_services(tmp_path, link=FakeLink(chat_text=f"{short[2]} | warm and exact\n{short[0]} | plain\nnot-a-preset | x"))
    try:
        out = presets.pick(svc, "invoices and bookkeeping for a small bakery")
        assert out["source"] == "model" and out["recommended"] == short[2] and [c["name"] for c in out["candidates"]][:2] == [short[2], short[0]]
        with pytest.raises(ValueError):
            presets.pick(svc, "")
    finally:
        svc.stop()


def test_apply_writes_only_the_chosen_parts(tmp_path):
    svc = make_services(tmp_path)
    try:
        base = svc.tokens_generate({"name": "Base", "hue": 30, "style": "pill"})
        before = svc.tokens_get(base["id"])["tokens"]
        out = presets.apply(svc, "ledger-ink", tokens_id=base["id"], parts=["colors"])
        after = svc.tokens_get(base["id"])
        assert out["created"] is False and after["tokens"]["radius"] == before["radius"] and after["tokens"]["typography"] == before["typography"]
        assert after["tokens"]["color"]["surfaces"]["light"]["bg"] == presets.get("ledger-ink")["tokens"]["colors"]["light"]["background"]
        assert after["tokens"]["preset"]["parts"] == ["colors"] and "--color-bg" in after["css"]
        presets.apply(svc, "ledger-ink", tokens_id=base["id"], parts=["radius", "type"])
        again = svc.tokens_get(base["id"])["tokens"]
        assert again["radius"]["md"] == "4px" and "IBM Plex Serif" in again["typography"]["heading"]
        new = call_tool(svc, "design_preset_apply", {"preset": "hoard-hub", "name": "Hub look"})
        assert new["created"] and svc.tokens_get(new["tokens_id"])["name"] == "Hub look"
        with pytest.raises(Exception):
            presets.apply(svc, "ledger-ink", tokens_id=base["id"], parts=["sound"])
    finally:
        svc.stop()


# ---------------------------------------------------------------- Figma

def test_parse_link_forms():
    assert figma.parse_link("https://www.figma.com/design/AbCdEfGhIjKl/Harbor?node-id=12-34&t=x") == ("AbCdEfGhIjKl", "12:34")
    assert figma.parse_link("https://www.figma.com/file/AbCdEfGhIjKl/Harbor") == ("AbCdEfGhIjKl", None)
    assert figma.parse_link("AbCdEfGhIjKl:12-34") == ("AbCdEfGhIjKl", "12:34")
    with pytest.raises(ValueError):
        figma.parse_link("https://example.com/x")


def test_reduce_reads_auto_layout_and_dedupes_styles():
    spec = figma.reduce(figma.document_of(FRAME, "12:34"))
    root = spec["root"]
    assert spec["width"] == 960 and root["layout"]["mode"] == "column" and root["layout"]["gap"] == 24
    header, stats, image, dot = root["children"]
    assert header["layout"]["justify"] == "space-between" and header["sizing"]["h"] == "fill"
    cards = stats["children"]
    assert len(cards) == 3 and len({tuple(c["style"]) for c in cards}) == 1          # three cards, one set of style ids
    assert image["image"] and dot["absolute"] and dot["box"] == [890.0, 260.0, 12.0, 12.0]
    assert spec["counts"]["style_uses"] > spec["counts"]["styles"]
    page = figma.to_html(spec)
    assert "display: flex" in page and "flex-direction: column" in page and "Shipments this week" in page
    assert "position: absolute" in page and "fonts.googleapis.com" in page and 'role="img"' in page


def test_import_without_a_token_explains_what_to_paste(client):
    r = client.post("/api/figma/import", json={"link": "https://www.figma.com/design/AbCdEfGhIjKl/x?node-id=1-2"})
    assert r.status_code == 400 and "Personal access tokens" in r.text
    s = client.put("/api/settings", json={"figma_token": "figd_secret_value_1234"}).json()
    assert s["figma_token_set"] is True and s["figma_token_hint"].endswith("1234") and "secret" not in json.dumps(s)
    assert client.put("/api/settings", json={"figma_token": ""}).json()["figma_token_set"] is False


def test_import_from_recorded_json_makes_a_design_project(tmp_path):
    import base64, io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (960, 640), (247, 248, 250)).save(buf, format="PNG")
    svc = make_services(tmp_path)
    try:
        out = call_tool(svc, "design_figma_import", {"nodes_json": FRAME, "image_base64": base64.b64encode(buf.getvalue()).decode()})
        assert out["render_id"] and out["tokens_id"] and Path(out["html_path"]).is_file() and out["counts"]["nodes"] == 14
        assert out["compare"]["diff_pct"] is not None and out["critique"]["score"] is not None
        cmp = out["compare"]
        assert cmp["reference_size"] == [960, 640] and cmp["scope"] in ("full", "normalized", "partial")
        assert cmp["diff_pct"] >= cmp["overlap_diff_pct"] * cmp["coverage"] - 0.01 and 0 < cmp["coverage"] <= 1.0
        system = svc.tokens_get(out["tokens_id"])
        assert "Barlow" in system["tokens"]["typography"]["body"] and system["name"].startswith("Figma:")
        assert figma.imports(svc.config.data_dir)[0]["import_id"] == out["import_id"]
    finally:
        svc.stop()


# ---------------------------------------------------------------- the Figma pixel diff covers the whole canvas

def _png(path, size, red_from=None):
    from PIL import Image
    img = Image.new("RGB", size, "white")
    if red_from is not None:
        img.paste((255, 0, 0), (0, red_from, size[0], size[1]))
    img.save(path)
    return path


def test_figma_diff_counts_the_missing_half_of_a_truncated_render(tmp_path):
    from PIL import Image
    ref = _png(tmp_path / "ref.png", (64, 64), red_from=32)        # white top, red bottom
    shot = _png(tmp_path / "shot.png", (64, 32))                   # only the white top was rendered
    out = figma._diff(ref, shot, tmp_path / "diff.png")
    assert out["diff_pct"] == 50.0 and out["overlap_diff_pct"] == 0.0
    assert out["scope"] == "partial" and out["coverage"] == 0.5 and out["compared_rect"] == [0, 0, 64, 32]
    assert out["reference_size"] == [64, 64] and out["render_size"] == [64, 32] and (out["width"], out["height"]) == (64, 64)
    assert out["missing_rows"] == 32 and out["extra_rows"] == 0 and out["render_scale"] == 1.0
    diff = Image.open(out["diff_image"])
    assert diff.size == (64, 64) and diff.getpixel((10, 50)) == (255, 0, 255) and diff.getpixel((10, 10)) == (0, 0, 0)


def test_figma_diff_counts_an_extra_footer_of_the_render(tmp_path):
    ref = _png(tmp_path / "ref.png", (64, 32))
    shot = _png(tmp_path / "shot.png", (64, 64))                   # same top, plus a (white) footer the frame lacks
    out = figma._diff(ref, shot, tmp_path / "diff.png")
    assert out["diff_pct"] == 50.0 and out["overlap_diff_pct"] == 0.0 and out["scope"] == "partial"
    assert out["extra_rows"] == 32 and out["missing_rows"] == 0 and out["coverage"] == 0.5 and out["height"] == 64


def test_figma_diff_declares_the_width_normalisation(tmp_path):
    ref = _png(tmp_path / "ref.png", (64, 64), red_from=32)
    shot = _png(tmp_path / "shot.png", (128, 128), red_from=64)    # the same frame at 2x
    out = figma._diff(ref, shot, tmp_path / "diff.png")
    assert out["scope"] == "normalized" and out["render_scale"] == 0.5 and out["render_compared_size"] == [64, 64]
    assert out["normalization"] and "64px" in out["normalization"] and out["coverage"] == 1.0
    assert out["missing_rows"] == 0 and out["extra_rows"] == 0 and out["diff_pct"] < 2.0
    short = _png(tmp_path / "short.png", (128, 64))                # 2x wide but only the white top
    cut = figma._diff(ref, short, tmp_path / "diff2.png")
    assert cut["scope"] == "partial" and cut["render_scale"] == 0.5 and cut["render_compared_size"] == [64, 32]
    assert cut["diff_pct"] == 50.0 and cut["missing_rows"] == 32 and cut["coverage"] == 0.5


def test_figma_diff_of_identical_images_is_zero_and_full(tmp_path):
    ref = _png(tmp_path / "ref.png", (64, 64), red_from=32)
    same = _png(tmp_path / "same.png", (64, 64), red_from=32)
    out = figma._diff(ref, same, tmp_path / "diff.png")
    assert out["diff_pct"] == 0.0 and out["overlap_diff_pct"] == 0.0 and out["scope"] == "full"
    assert out["coverage"] == 1.0 and out["normalization"] is None and out["render_scale"] == 1.0
    assert out["missing_rows"] == out["extra_rows"] == 0 and out["reference_size"] == out["render_size"] == [64, 64]
    other = _png(tmp_path / "other.png", (64, 64))                 # same size, bottom half differs
    assert figma._diff(ref, other, tmp_path / "diff3.png")["diff_pct"] == 50.0


def test_figma_diff_drops_only_flat_viewport_padding(tmp_path):
    from PIL import Image
    ref = _png(tmp_path / "ref.png", (64, 40))
    shot = _png(tmp_path / "shot.png", (64, 90))                   # a 40px frame captured in a 90px viewport
    out = figma._diff(ref, shot, tmp_path / "diff.png", viewport_fill_from=40)
    assert out["viewport_fill_rows"] == 50 and out["render_compared_size"] == [64, 40] and out["render_size"] == [64, 90]
    assert out["scope"] == "normalized" and "viewport-padding" in out["normalization"] and out["diff_pct"] == 0.0
    drawn = Image.new("RGB", (64, 90), "white")
    drawn.paste((0, 0, 255), (0, 70, 64, 74))                     # something is drawn below the frame: real extra content
    drawn.save(tmp_path / "drawn.png")
    over = figma._diff(ref, tmp_path / "drawn.png", tmp_path / "diff2.png", viewport_fill_from=40)
    assert over["viewport_fill_rows"] == 0 and over["extra_rows"] == 50 and over["scope"] == "partial"
    assert over["diff_pct"] == round(100 * 50 / 90, 2)
    assert figma._diff(ref, shot, tmp_path / "diff3.png")["extra_rows"] == 50      # without the flag nothing is dropped


def test_figma_dialog_uploads_the_frame_png_and_shows_the_rendered_preview(tmp_path):
    """Opt-in real browser flow: JSON + PNG through the dialog, the diff line, and a preview that is not blank."""
    import io, os, socket, threading, time
    from contextlib import asynccontextmanager
    import uvicorn
    from fastapi import FastAPI
    from PIL import Image
    from playwright.sync_api import expect, sync_playwright
    from vitruvius_hoard.main import create_app

    if os.environ.get("VITRUVIUS_BROWSER_TESTS") != "1":
        pytest.skip("Set VITRUVIUS_BROWSER_TESTS=1 to run the real browser flow")
    reference = tmp_path / "frame.png"
    Image.new("RGB", (960, 640), (247, 248, 250)).save(reference)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    svc = make_services(tmp_path, port=port)
    design = create_app(svc.config, svc)

    @asynccontextmanager
    async def lifespan(_app):
        async with design.router.lifespan_context(design):
            yield

    owner = FastAPI(lifespan=lifespan)
    owner.mount("/design", design)
    server = uvicorn.Server(uvicorn.Config(owner, log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True, args=["--disable-gpu", "--use-angle=swiftshader"])
            try:
                page = browser.new_page(viewport={"width": 1400, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{port}/design/#/tokens")
                page.get_by_test_id("figma-open").click()
                page.get_by_test_id("figma-json").fill(json.dumps(FRAME))
                page.get_by_test_id("figma-png").set_input_files(str(reference))
                expect(page.get_by_test_id("figma-dialog")).to_contain_text("frame.png")
                with page.expect_response(lambda r: r.url.endswith("/api/figma/import"), timeout=180_000) as answer:
                    page.get_by_test_id("figma-import").click()
                assert json.loads(answer.value.request.post_data)["image_base64"]
                compare = answer.value.json()["compare"]
                assert compare["reference_size"] == [960, 640] and compare["diff_pct"] is not None
                expect(page.get_by_test_id("figma-compare")).to_contain_text("Figma 960×640")
                expect(page.get_by_test_id("figma-diff")).to_be_visible()
                preview = page.get_by_test_id("figma-result").locator("figure").nth(1)
                frame = page.frame_locator("[data-testid=figma-result] iframe")
                expect(frame.locator("body")).to_contain_text("Shipments this week", timeout=20_000)
                page.wait_for_timeout(500)
                shot = Image.open(io.BytesIO(preview.locator("div").first.screenshot())).convert("L")
                dark = sum(1 for v in shot.getdata() if v < 235) / (shot.width * shot.height)
                assert dark > 0.2, f"the HTML/CSS preview is blank ({dark:.3f} non-white)"
                assert not errors
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        svc.stop()


def test_import_drops_the_capture_viewport_padding_of_a_short_frame(tmp_path, monkeypatch):
    """A 640px frame is captured in a 900px viewport: the flat padding goes, the frame is compared whole."""
    import io
    from PIL import Image
    svc = make_services(tmp_path)
    try:
        shot = tmp_path / "960.png"
        img = Image.new("RGB", (960, 900), "white")
        img.paste((247, 248, 250), (0, 0, 960, 640))
        img.save(shot)
        real_render = svc.render

        def render(**kw):
            out = real_render(**kw)
            out["files"] = [{"width": 960, "path": str(shot), "full_page": True, "w": 960, "h": 900}]
            return out
        monkeypatch.setattr(svc, "render", render)
        buf = io.BytesIO()
        Image.new("RGB", (960, 640), (247, 248, 250)).save(buf, format="PNG")
        cmp = figma.import_frame(svc, nodes_json=FRAME, image_png=buf.getvalue(), make_tokens=False, critique=False)["compare"]
        assert cmp["render_size"] == [960, 900] and cmp["viewport_fill_rows"] == 260 and cmp["render_compared_size"] == [960, 640]
        assert cmp["extra_rows"] == cmp["missing_rows"] == 0 and cmp["scope"] == "normalized" and cmp["diff_pct"] == 0.0
        img.paste((0, 0, 255), (0, 800, 960, 810))               # something drawn below the frame is never dropped
        img.save(shot)
        cmp = figma.import_frame(svc, nodes_json=FRAME, image_png=buf.getvalue(), make_tokens=False, critique=False)["compare"]
        assert cmp["viewport_fill_rows"] == 0 and cmp["extra_rows"] == 260 and cmp["scope"] == "partial"
    finally:
        svc.stop()
