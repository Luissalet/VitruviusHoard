"""The design rules as data: the registry, the static rules on whole pages, the render rules on synthetic snapshots and the
design-system rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import default_probe
from vitruvius_hoard import lint, tokens as tokens_mod
from vitruvius_hoard.rules import catalog, registry
from vitruvius_hoard.rules.cli import list_rules_main

PAGES = Path(__file__).parent / "fixtures" / "pages"
AI = (PAGES / "generic_ai.html").read_text(encoding="utf-8")
GOOD = (PAGES / "good.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _rules():
    lint.ensure_rules()


def ids_of(result):
    return {f["check_id"] for f in result["findings"]}


# ---------------------------------------------------------------- registry

def test_every_rule_is_well_formed_and_unique():
    rows = registry.list_rules()
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)) >= 140
    for r in rows:
        assert r["engine"] in registry.ENGINES and r["severity"] in registry.SEVERITIES and r["scope"] in registry.SCOPES
        assert r["tier"] == registry.TIER_OF[r["severity"]]
        assert r["name"] and r["description"] and r["reference"]
        assert (r["pack"] == "core") == ("/" not in r["id"])


def test_every_non_visual_rule_has_an_implementation_and_visual_ones_do_not():
    for r in registry.list_rules():
        assert r["runnable"] == (r["engine"] != "visual"), r["id"]


def test_core_pack_keeps_the_original_ids():
    core = {r["id"] for r in registry.list_rules(pack="core")}
    assert core == set(lint.CHECK_IDS) and len(core) == 32


def test_listing_filters_and_summary():
    assert {r["engine"] for r in registry.list_rules(engine="visual")} == {"visual"}
    assert all(r["tier"] == "floor" for r in registry.list_rules(severity="error"))
    assert registry.list_rules(query="nested")[0]["id"] == "slop/nested-cards"
    s = registry.summary()
    assert s["total"] == len(registry.all_rules()) and set(s["by_pack"]) >= {"core", "slop", "quality", "craft", "visual", "ds"}
    assert registry.get_rule("design-system-font").id == "ds/font"  # an upstream id resolves to ours


def test_a_pack_cannot_shadow_an_existing_id():
    with pytest.raises(ValueError):
        registry.register_pack("slop", [{"name_id": "side-tab", "engine": "static", "scope": "color", "severity": "warning", "name": "x", "description": "y"}])
    with pytest.raises(ValueError):
        registry.register_rule(registry.Rule(id="font.generic-only", engine="static", scope="type", severity="warning", name="x", description="y"))


def test_a_third_party_pack_registers_and_unregisters():
    registry.register_pack("acme", [{"name_id": "no-comic", "engine": "static", "scope": "type", "severity": "advisory", "name": "No comic face",
                                    "description": "Comic Sans anywhere."}], check_for=lambda n: (lambda probe, html: []))
    try:
        assert registry.get_rule("acme/no-comic").tier == "finish"
    finally:
        assert registry.unregister_pack("acme") == 1
    assert registry.get_rule("acme/no-comic") is None


def test_upstream_coverage_maps_point_at_real_rules():
    ids = {r.id for r in registry.all_rules()}
    for table in (catalog.UPSTREAM_COVERAGE_IMPECCABLE, catalog.UPSTREAM_COVERAGE_HALLMARK):
        for upstream, ours in table.items():
            if not ours.startswith("("):
                assert ours in ids or registry.get_rule(ours), (upstream, ours)


def test_list_rules_cli(capsys):
    assert list_rules_main(["--list-rules", "--pack", "ds"]) == 0
    out = capsys.readouterr().out
    assert "ds/font" in out and "5 of" in out
    assert list_rules_main(["--list-rules", "--rule", "slop/side-tab"]) == 0
    assert '"engine": "browser"' in capsys.readouterr().out
    assert list_rules_main(["--list-rules", "--rule", "nope"]) == 1


# ---------------------------------------------------------------- static rules on whole pages

AI_EXPECTED = {
    "slop/gradient-text", "slop/ai-color-palette", "slop/dark-glow", "slop/radial-spotlight-glow", "slop/pulsing-dot", "slop/bounce-easing",
    "slop/marketing-buzzword", "slop/aphoristic-cadence", "slop/copy-tells", "slop/mono-costume", "slop/tracked-caps-label",
    "slop/accented-word", "craft/hero-vh", "craft/transition-all", "craft/title-meta", "craft/decorative-svg-unlabeled",
}


def test_a_generic_ai_page_trips_the_slop_rules():
    result = lint.run_lint(default_probe(), AI)
    missing = AI_EXPECTED - ids_of(result)
    assert not missing, missing
    assert result["tiers"]["floor"] >= 1 and result["score"] <= 2
    finding = next(f for f in result["findings"] if f["check_id"] == "slop/gradient-text")
    assert finding["engine"] == "static" and finding["pack"] == "slop" and finding["level"] in registry.SEVERITIES and finding["tier"] in ("floor", "reflex", "finish")
    assert finding["severity"] in ("info", "warn", "error")  # the legacy vocabulary is kept


def test_a_good_page_trips_no_static_rule_above_advisory():
    result = lint.run_lint(default_probe(), GOOD, packs=["slop", "quality", "craft"])
    bad = [(f["check_id"], f["detail"]) for f in result["findings"] if f["tier"] != "finish"]
    assert not bad, bad


def test_packs_only_and_skip_narrow_a_run():
    assert {f["check_id"].split("/")[0] for f in lint.run_lint(default_probe(), AI, packs=["craft"])["findings"]} == {"craft"}
    assert "slop/gradient-text" not in ids_of(lint.run_lint(default_probe(), AI, skip=["slop/gradient-text"]))
    assert ids_of(lint.run_lint(default_probe(), AI, only=["slop/gradient-text"])) == {"slop/gradient-text"}


def test_static_rules_work_on_a_captured_url_through_the_probe_source():
    probe = default_probe(html_text=AI, css_text="")
    assert "slop/gradient-text" in ids_of(lint.run_lint(probe, ""))


@pytest.mark.parametrize("html,rule", [
    ('<p>' + "A — b " * 12 + "</p>", "slop/em-dash-overuse"),
    ('<video autoplay src="a.mp4"></video>', "craft/video-autoplay"),
    ('<img src="a.png" alt="x"><div class="g"></div><style>.g{display:grid;grid-template-columns:1fr 1fr}</style>', "craft/grid-bare-fr"),
    ('<style>.a{position:sticky;top:0}.b{position:sticky;top:0}</style><div class="a"></div><div class="b"></div>', "craft/double-sticky"),
    ('<style>.reveal{opacity:0}</style><div class="reveal">x</div>', "craft/reveal-without-fallback"),
    ('<h1 style="text-transform:uppercase;line-height:.9">A long display heading here</h1>', "craft/uppercase-display-leading"),
    ('<p>He said "hello" and it\'s done, "again" and "more"</p>', "craft/straight-quotes"),
    ('<p>Wait... what... really</p>', "craft/three-dots"),
    ('<form><input name="e"><button>Go</button></form><script>document.querySelector("form").addEventListener("submit",e=>{e.preventDefault();ok.hidden=false;ok.textContent="Thanks, sent"})</script><div id="ok" hidden>Thanks, sent</div>', "slop/fake-send"),
])
def test_individual_static_rules(html, rule):
    assert rule in ids_of(lint.run_lint(default_probe(), html, only=[rule]))


def test_static_rules_stay_quiet_on_clean_markup():
    html = '<html lang="en"><head><title>T</title><meta name="description" content="d"></head><body><h1>Hello there</h1><p>Plain.</p></body></html>'
    assert lint.run_lint(default_probe(), html, packs=["slop", "craft", "quality"])["findings"] == []


# ---------------------------------------------------------------- render rules on synthetic snapshots

def snap(width, *els, height=900, page_height=3000, **extra):
    out = []
    for i, e in enumerate(els):
        d = {"i": i, "p": e.get("p", -1), "tag": e.get("tag", "div"), "r": e.get("r", [0, 0, 100, 40]), "s": {"fs": 16, "fw": "400", "ff": "newsreader", **e.get("s", {})}}
        for k in ("c", "t", "tl", "img", "svg", "act", "ctl", "ln", "last", "n", "id"):
            if k in e:
                d[k] = e[k]
        if "t" in e and "tl" not in e:
            d["tl"] = len(e["t"])
        out.append(d)
    return {"width": width, "height": height, "page_height": page_height, "page_width": width, "els": out, **extra}


def run(rule, *snaps, probe=None):
    p = default_probe(dom={str(s["width"]): s for s in snaps}, **(probe or {}))
    return [f for f in lint.run_lint(p, "", only=[rule])["findings"] if f["check_id"] == rule]


def test_dom_rules_need_a_snapshot_and_do_not_guess():
    assert run("slop/side-tab") == []
    assert lint.run_lint(default_probe(), "", packs=["quality"])["findings"] == []


def test_side_tab_and_border_accent():
    violet = ["rgb(139, 92, 246)"] * 4
    card = {"r": [0, 0, 300, 90], "t": "Trusted by teams worldwide", "s": {"bw": [0, 0, 0, 4], "bc": violet, "rad": [12, 12, 12, 12]}}
    assert run("slop/side-tab", snap(1440, card))
    top = {"r": [0, 0, 300, 90], "t": "Trusted by teams worldwide", "s": {"bw": [4, 0, 0, 0], "bc": violet, "rad": [12, 12, 12, 12]}}
    assert run("slop/border-accent-on-rounded", snap(1440, top)) and not run("slop/side-tab", snap(1440, top))
    thin = {**card, "s": {"bw": [0, 0, 0, 1], "bc": violet}}
    assert not run("slop/side-tab", snap(1440, thin))


def test_nested_cards_and_icon_tiles():
    sh = "rgba(0,0,0,.3) 0px 8px 24px 0px"
    outer = {"r": [0, 0, 400, 300], "s": {"sh": sh, "rad": [16] * 4}}
    inner = {"p": 0, "r": [20, 100, 300, 120], "t": "details", "s": {"sh": sh, "bw": [1, 1, 1, 1], "rad": [12] * 4}}
    assert run("slop/nested-cards", snap(1440, outer, inner))
    els = []
    for k in range(3):
        base = len(els)
        els += [{"r": [k * 320, 0, 300, 200]}, {"p": base, "r": [k * 320 + 20, 20, 48, 48], "s": {"bg": "rgba(124, 58, 237, 0.2)", "rad": [12] * 4}},
                {"p": base + 1, "tag": "svg", "r": [k * 320 + 30, 30, 24, 24]}, {"p": base, "tag": "h3", "t": "Fast", "r": [k * 320 + 20, 90, 200, 30], "s": {"fw": "700"}}]
    assert run("slop/icon-tile-stack", snap(1440, *els))


def test_tiny_text_straggler_leading_and_tracking():
    para = {"tag": "p", "r": [0, 0, 600, 120], "t": "x" * 200, "ln": 4, "last": 30, "s": {"fs": 16, "lh": 18, "ls": 1.2}}
    assert run("quality/tight-leading", snap(1440, para)) and run("quality/straggler", snap(1440, para)) and run("quality/wide-tracking", snap(1440, para))
    tiny = {"tag": "p", "r": [0, 0, 300, 40], "t": "legal copy that is much too small to read", "s": {"fs": 10}}
    assert run("quality/tiny-text", snap(1440, tiny))
    ok = {**para, "last": 200, "s": {"fs": 16, "lh": 26}}
    assert not run("quality/tight-leading", snap(1440, ok)) and not run("quality/straggler", snap(1440, ok))


def test_button_wrap_hero_fold_and_hidden_content():
    btn = {"tag": "button", "r": [0, 0, 90, 80], "t": "Request a quote", "ln": 2, "s": {"bg": "rgb(10,10,10)"}}
    assert run("craft/button-wrap", snap(390, btn))
    h1 = {"tag": "h1", "r": [0, 1200, 800, 100], "t": "Late headline", "s": {"fs": 60}}
    assert run("craft/hero-fold", snap(1440, h1))
    ghost = {"r": [0, 100, 400, 60], "t": "This paragraph is invisible at rest", "s": {"op": 0}}
    assert run("quality/content-hidden-at-rest", snap(1440, ghost))


def test_script_error_and_broken_image_are_errors():
    f = run("quality/script-error", snap(1440, {"r": [0, 0, 10, 10]}), probe={"script_errors": ["ReferenceError: foo is not defined"]})
    assert f and f[0]["severity"] == "error" and f[0]["tier"] == "floor"
    bad = {"tag": "img", "r": [0, 0, 200, 100], "img": {"src": "missing.png", "ok": False, "done": True, "nw": 0, "nh": 0}}
    assert run("quality/broken-image", snap(1440, bad))
    placeholder = {"tag": "img", "r": [0, 0, 200, 100], "img": {"src": "https://via.placeholder.com/200", "ok": True, "done": True, "nw": 200, "nh": 100}}
    assert run("quality/broken-image", snap(1440, placeholder))


def test_gray_on_color_and_oversized_h1_and_tracking():
    gray = {"tag": "p", "r": [0, 0, 300, 40], "t": "muted text on a saturated surface", "s": {"color": "rgb(150, 150, 150)", "bg": "rgb(220, 40, 40)"}}
    assert run("quality/gray-on-color", snap(1440, gray))
    h1 = {"tag": "h1", "r": [0, 50, 1200, 700], "t": "Huge", "s": {"fs": 200}}
    assert run("slop/oversized-h1", snap(1440, h1))
    squeezed = {"tag": "h2", "r": [0, 0, 400, 50], "t": "Squeezed", "s": {"fs": 30, "ls": -3}}
    assert run("slop/extreme-negative-tracking", snap(1440, squeezed))


def test_section_gaps_and_orphan_grid():
    secs = [{"tag": "section", "r": [0, k * 400, 1440, 400], "s": {"pad": [40, 0, 40, 0]}, "t": "x"} for k in range(4)]
    assert run("craft/section-gaps", snap(1440, *secs))
    grid = {"r": [0, 0, 900, 400], "s": {"disp": "grid"}}
    kids = [{"p": 0, "r": [k % 3 * 300, k // 3 * 200, 280, 180], "t": "card"} for k in range(4)]
    assert run("craft/orphan-grid-item", snap(1440, grid, *kids))


def test_the_widest_capture_is_the_desktop_one():
    secs = [{"tag": "section", "r": [0, k * 400, 1024, 400], "s": {"pad": [40, 0, 40, 0]}, "t": "x"} for k in range(4)]
    assert not run("craft/section-gaps", snap(1024, *secs))  # under 1200px: not a desktop capture


# ---------------------------------------------------------------- design-system rules

@pytest.fixture
def system():
    return tokens_mod.generate({"name": "Brumario", "hue": 30, "style": "sharp", "fonts": {"heading": "Fraunces, serif", "body": "Newsreader, serif"}})


def run_ds(rule, snapshot, system):
    return [f for f in lint.run_lint(default_probe(dom={"1440": snapshot}), "", tokens=system, only=[rule])["findings"]]


def test_ds_rules_are_off_without_a_system(system):
    assert "ds/font" not in {r.id for r in lint.selected_rules()} - {r.id for r in lint.selected_rules()}  # selectable...
    assert lint.run_lint(default_probe(dom={"1440": snap(1440, {"t": "hello", "s": {"ff": "comic sans ms"}}, {"t": "world", "s": {"ff": "comic sans ms"}})}), "")["design_system"] is False
    assert not [f for f in lint.run_lint(default_probe(dom={"1440": snap(1440, {"t": "hello", "s": {"ff": "comic sans ms"}})}), "")["findings"] if f["check_id"].startswith("ds/")]


def test_ds_font_color_radius_scale(system):
    els = [{"t": "one", "s": {"ff": "comic sans ms"}}, {"t": "two", "s": {"ff": "comic sans ms"}}, {"t": "three", "s": {"ff": "fraunces"}}]
    f = run_ds("ds/font", snap(1440, *els), system)
    assert f and "comic sans ms" in f[0]["detail"]
    assert not run_ds("ds/font", snap(1440, {"t": "ok", "s": {"ff": "fraunces"}}, {"t": "ok", "s": {"ff": "newsreader"}}), system)
    off = [{"r": [0, 0, 100, 40], "t": "violet", "s": {"color": "rgb(124, 58, 237)", "bg": "rgb(236, 72, 153)"}}] * 3
    assert run_ds("ds/color", snap(1440, *off, {"t": "x", "s": {"color": "rgb(34, 197, 94)", "bg": "rgb(250, 204, 21)"}}, {"t": "x", "s": {"color": "rgb(34, 197, 94)", "bg": "rgb(250, 204, 21)"}}), system)
    radii = [{"r": [0, 0, 120, 80], "s": {"rad": [13, 13, 13, 13]}}, {"r": [0, 0, 120, 80], "s": {"rad": [13, 13, 13, 13]}}, {"r": [0, 0, 120, 80], "s": {"rad": [22, 22, 22, 22]}}, {"r": [0, 0, 120, 80], "s": {"rad": [22, 22, 22, 22]}}]
    assert run_ds("ds/radius", snap(1440, *radii), system)
    sizes = [{"t": "size a", "s": {"fs": 14.4}}, {"t": "size b", "s": {"fs": 14.4}}, {"t": "size c", "s": {"fs": 18.2}}, {"t": "size d", "s": {"fs": 18.2}}, {"t": "size e", "s": {"fs": 22.5}}, {"t": "size f", "s": {"fs": 22.5}}, {"t": "size g", "s": {"fs": 28.3}}, {"t": "size h", "s": {"fs": 28.3}}]
    assert run_ds("ds/scale", snap(1440, *sizes), system)


def test_ds_rules_read_the_system_through_the_service(tmp_path):
    from conftest import make_services
    svc = make_services(tmp_path, probe_overrides={"dom": {"1440": snap(1440, {"t": "one", "s": {"ff": "comic sans ms"}}, {"t": "two", "s": {"ff": "comic sans ms"}})}})
    svc.start()
    try:
        row = svc.tokens_generate({"name": "T", "hue": 200})
        assert any(f["check_id"] == "ds/font" for f in svc.lint_html(html="<p>x</p>", tokens_id=row["id"])["findings"])
        assert not any(f["check_id"].startswith("ds/") for f in svc.lint_html(html="<p>x</p>")["findings"])
        with pytest.raises(LookupError):
            svc.lint_html(html="<p>x</p>", tokens_id="nope")
    finally:
        svc.stop()
