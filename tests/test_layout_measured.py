"""Layout measured in the browser at each captured width: sideways scroll, text cut by its box, text over text."""

import pytest

from vitruvius_hoard.browser import LAYOUT_JS
from vitruvius_hoard.lint import run_lint

FIXTURE = """<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width"><style>
body{margin:0;font:16px/1.4 sans-serif;max-width:100%} .wide{width:1300px;background:#eee}
.card{width:200px;height:44px;overflow:hidden;border:1px solid #999}
.ell{width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.scroller{overflow-x:auto} .scroller div{width:2000px}
.stack{position:relative;height:60px} .stack h2{position:absolute;top:0;margin:0} .stack p{position:absolute;top:4px;margin:0;font-size:22px}
.slider{width:300px;overflow:hidden;white-space:nowrap} .slider span{display:inline-block;width:300px}
.menu{height:30px;overflow:hidden} .menu ul{visibility:hidden}
</style></head><body>
<div class="wide" id="banner">A fixed banner wider than phones</div>
<div class="card" id="bio">This biography is much longer than the little card can hold, so its last lines are simply cut off by the box without any ellipsis at all.</div>
<div class="ell">An intentionally truncated label</div>
<div class="scroller"><div>wide table inside a scroller</div></div>
<div class="stack"><h2>Overlapping heading</h2><p>Overlapping paragraph text</p></div>
<div class="slider"><span>Slide one</span><span>Slide two</span></div>
<div class="menu">Menu<ul><li>a</li><li>b</li></ul></div>
<p>Plain paragraph that is fine.</p>
</body></html>"""


def layout_probe():
    return {"layout": {
        "390": {"width": 390, "page_width": 1300, "overflow_px": 910,
                "overflowing": [{"el": "div#banner.wide", "text": "A banner", "width": 1300, "right": 1300, "by": 910}],
                "clipped": [{"el": "div#bio.card", "text": "This biography", "axis": "y", "lines_cut": 0, "lines_hidden": 3,
                             "hidden_px": 68, "intended": False},
                            {"el": "div.ell", "text": "A label", "axis": "x", "lines_cut": 1, "lines_hidden": 0,
                             "hidden_px": 98, "intended": True}],
                "overlaps": [{"a": "h2", "a_text": "Heading", "b": "p", "b_text": "Paragraph", "share": 89, "at": [0, 119]}]},
        "1440": {"width": 1440, "page_width": 1440, "overflow_px": 0, "overflowing": [],
                 "clipped": [{"el": "div#bio.card", "text": "This biography", "axis": "y", "lines_cut": 0, "lines_hidden": 3,
                              "hidden_px": 68, "intended": False}],
                 "overlaps": [{"a": "h2", "a_text": "Heading", "b": "p", "b_text": "Paragraph", "share": 89, "at": [0, 119]}]},
    }}


def by_id(result, check_id):
    return [f for f in result["findings"] if f["check_id"] == check_id]


def test_measured_checks_report_each_problem_once_with_its_widths():
    html = "<style>.x{width:1600px}</style>"  # would trip the HTML guess, which steps aside when there is a measurement
    result = run_lint(layout_probe(), html)
    assert not by_id(result, "layout.horizontal-overflow")
    side = by_id(result, "layout.sideways-scroll")
    assert len(side) == 1 and side[0]["severity"] == "error" and "390px" in side[0]["title"]
    assert "div#banner.wide (+910px)" in side[0]["detail"]
    clipped = by_id(result, "layout.clipped-text")
    assert len(clipped) == 1 and clipped[0]["evidence"]["widths"] == [390, 1440]  # the ellipsis is intended: not reported
    overlap = by_id(result, "layout.text-overlap")
    assert len(overlap) == 1 and overlap[0]["evidence"]["widths"] == [390, 1440] and "89%" in overlap[0]["detail"]
    assert all(f["fix"] for f in side + clipped + overlap)


def test_without_a_measurement_the_html_guess_still_works():
    result = run_lint({}, "<style>.x{width:1600px}</style>")
    assert by_id(result, "layout.horizontal-overflow")
    assert not by_id(result, "layout.sideways-scroll")
    assert run_lint({"layout": {"bad": None, "390": None}}, "")["findings"] is not None  # junk never breaks the lint


def test_a_failed_measurement_keeps_the_html_guess_and_a_clean_one_replaces_it():
    html = "<style>.x{width:1600px}</style>"
    failed = {"layout": {"390": {"error": "Execution context was destroyed"}, "1440": {"error": "timeout"}}}
    result = run_lint(failed, html)
    assert by_id(result, "layout.horizontal-overflow")  # a probe that failed is no evidence the page fits
    assert not by_id(result, "layout.sideways-scroll")
    mixed = {"layout": {"390": {"error": "timeout"}, "1440": {"width": 1440, "page_width": 1440, "overflow_px": 0,
                                                             "overflowing": [], "clipped": [], "overlaps": []}}}
    result = run_lint(mixed, html)
    assert not by_id(result, "layout.horizontal-overflow")  # one real measurement takes precedence
    assert not by_id(result, "layout.sideways-scroll")
    junk = {"layout": {"390": {"overflow_px": "910"}, "1024": {"overflow_px": True}, "1440": []}}
    assert by_id(run_lint(junk, html), "layout.horizontal-overflow")


def _browser():
    try:
        from playwright.sync_api import sync_playwright

        p = sync_playwright().start()
        try:
            return p, p.chromium.launch()
        except Exception:
            p.stop()
            return None, None
    except Exception:
        return None, None


def test_probe_measures_the_real_page():
    p, browser = _browser()
    if browser is None:
        pytest.skip("no Chromium for Playwright here")
    try:
        page = browser.new_page()
        page.set_content(FIXTURE)
        layout = {}
        for width in (390, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            layout[str(width)] = page.evaluate(LAYOUT_JS)
    finally:
        browser.close()
        p.stop()
    narrow, wide = layout["390"], layout["1440"]
    assert narrow["overflow_px"] == 910 and [o["el"] for o in narrow["overflowing"]] == ["div#banner.wide"]
    assert wide["overflow_px"] == 0 and wide["overflowing"] == []  # the scroller's wide child is inside its own box
    clipped = {c["el"]: c for c in narrow["clipped"]}
    assert clipped["div#bio.card"]["lines_hidden"] >= 2 and not clipped["div#bio.card"]["intended"]
    assert clipped["div.ell"]["intended"]
    assert "div.slider" not in clipped and "div.menu" not in clipped  # hidden slides and invisible menus are not "cut"
    assert [(o["a"], o["b"]) for o in narrow["overlaps"]] == [("h2", "p")]  # clipped ink does not count as overlap
    findings = run_lint({"layout": layout}, FIXTURE)["findings"]
    assert {f["check_id"] for f in findings} >= {"layout.sideways-scroll", "layout.clipped-text", "layout.text-overlap"}


def test_critique_of_a_stored_render_lints_what_the_render_measured(tmp_path):
    from conftest import make_services

    services = make_services(tmp_path, probe_overrides=layout_probe())
    page = "<html lang='en'><style>main{max-width:72ch}</style><body><main><h1>Hi</h1></main></body></html>"
    render = services.render(html=page, widths=[390, 1440])
    at_render = {f["check_id"] for f in render["lint"]["findings"]}
    critique = services.critique_render(render["id"], use_vision=False)
    later = {f["check_id"] for f in critique["findings"]}
    assert {"layout.sideways-scroll", "layout.clipped-text", "layout.text-overlap"} <= later
    assert "layout.no-max-width" not in later  # the stored source is linted too, not an empty page
    assert at_render == {f["check_id"] for f in services.lint_html(render_id=render["id"])["findings"]}
    assert "probe" not in services.get_render(render["id"])["metrics"]  # kept for lint, not sent to the UI
