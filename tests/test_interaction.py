"""The interaction pack: keyboard, focus and ARIA. Static rules on fixtures, browser rules on a real Tab walk."""
from __future__ import annotations

from pathlib import Path

import pytest

from vitruvius_hoard import critique, i18n_es, lint
from vitruvius_hoard.browser import BrowserWorker, _sync_playwright_available
from vitruvius_hoard.rules import registry

PAGES = Path(__file__).resolve().parent / "fixtures" / "pages"
BAD = (PAGES / "inaccessible.html").read_text(encoding="utf-8")
GOOD = (PAGES / "accessible.html").read_text(encoding="utf-8")
STATIC = {"click-on-static-element", "unnamed-control", "positive-tabindex", "dangling-aria-reference", "incomplete-aria-widget", "duplicate-id", "link-without-destination"}
BROWSER = {"pointer-only-control", "focus-ring-missing", "keyboard-unreachable"}


def _ids(html, probe=None):
    return {f["check_id"].split("/", 1)[1]: f for f in lint.run_lint(probe or {}, html, packs=["interaction"])["findings"]}


def test_the_pack_is_registered_with_spanish_text():
    lint.ensure_rules()
    rules = {r["id"].split("/", 1)[1]: r for r in registry.list_rules(pack="interaction")}
    assert set(rules) == STATIC | BROWSER
    assert all(r["scope"] == "a11y" for r in rules.values())
    assert {n for n, r in rules.items() if r["engine"] == "browser"} == BROWSER
    assert all(f"interaction/{n}" in i18n_es.RULES_ES for n in rules)
    assert rules["unnamed-control"]["tier"] == "floor" and rules["duplicate-id"]["tier"] == "reflex"


def test_static_rules_find_what_the_inaccessible_page_does_wrong():
    found = _ids(BAD)
    assert set(found) == STATIC
    assert "div.chip" in found["click-on-static-element"]["detail"]
    assert "button.icon" in found["unnamed-control"]["detail"] and "input" in found["unnamed-control"]["detail"]
    assert {e["missing_id"] for e in found["dangling-aria-reference"]["evidence"]} == {"missing", "ghost"}
    assert {e["problem"] for e in found["incomplete-aria-widget"]["evidence"]} >= {"has no aria-label or aria-labelledby", "has no aria-selected", "is not inside role=tablist"}
    assert found["duplicate-id"]["evidence"] == [{"id": "dup", "count": 2}]
    assert found["positive-tabindex"]["evidence"][0]["tabindex"] == "3"


def test_the_accessible_page_has_no_static_findings():
    assert _ids(GOOD) == {}


@pytest.mark.parametrize("snippet, rule", [
    ('<span role="button" tabindex="0" aria-label="x">y</span>', None),
    ('<div role="button" onclick="x()">Go</div>', "click-on-static-element"),
    ('<div onclick="x()"><button>ok</button></div>', "click-on-static-element"),
    ('<button onclick="x()">Go</button>', None),
    ('<a href="/x" onclick="x()">Go</a>', None),
    ('<a href="#" onclick="x()">Go</a>', "link-without-destination"),
    ('<a href="javascript:void(0)">Go</a>', "link-without-destination"),
    ('<a href="#top">Top</a>', None),
    ('<button><img alt="Close" src="x.png"></button>', None),
    ('<button></button>', "unnamed-control"),
    ('<input type="checkbox">', "unnamed-control"),
    ('<label>Name <input></label>', None),
    ('<label for="n">Name</label><input id="n">', None),
    ('<input type="submit">', None),
    ('<input type="hidden" name="x">', None),
    ('<div hidden><button></button></div>', None),
    ('<input placeholder="Search">', "unnamed-control"),
    ('<div role="switch" aria-checked="false" aria-label="Wi-Fi" tabindex="0"></div>', None),
    ('<div role="switch" aria-label="Wi-Fi" tabindex="0"></div>', "incomplete-aria-widget"),
    ('<dialog aria-labelledby="t"><h2 id="t">T</h2></dialog>', None),
    ('<div role="dialog" aria-label="Settings"></div>', None),
    ('<div role="slider" aria-label="Volume" aria-valuenow="3" tabindex="0"></div>', None),
])
def test_static_cases(snippet, rule):
    found = set(_ids(f'<!doctype html><html lang="en"><body><main>{snippet}</main></body></html>'))
    assert found == ({rule} if rule else set()), (snippet, found)


def test_a_text_only_lint_never_guesses_the_browser_rules():
    assert set(_ids(BAD)) & BROWSER == set()


@pytest.fixture(scope="module")
def worker(tmp_path_factory):
    if not _sync_playwright_available():
        pytest.skip("no browser available")
    w = BrowserWorker(tmp_path_factory.mktemp("kb"))
    w.start()
    yield w
    w.stop()


def _capture(worker, html):
    shot = worker.capture(html=html, widths=[1024], full_page=False, wait_ms=100)
    if shot.get("error"):
        pytest.skip(str(shot["error"]))
    return shot["probe"]


def test_a_real_tab_walk_finds_what_only_a_browser_can_see(worker):
    probe = _capture(worker, BAD)
    kb = probe["keyboard"]
    assert kb["complete"] and kb["tab_stops"] == 8 and kb["unreached"] == []
    assert [s["label"] for s in kb["stops"]][0] == "span"       # the positive tabindex jumps the queue
    assert [i["text"] for i in kb["pointer_only"]] == ["Light", "Dark"]
    found = _ids(BAD, probe)
    assert BROWSER - {"keyboard-unreachable"} <= set(found) and "button.save" in found["focus-ring-missing"]["detail"]
    assert found["pointer-only-control"]["severity"] == "error"


def test_the_accessible_page_is_clean_in_the_browser_too(worker):
    probe = _capture(worker, GOOD)
    kb = probe["keyboard"]
    assert kb["tab_stops"] == 6 and kb["complete"] and kb["pointer_only"] == [] and all(s["ring"] for s in kb["stops"])
    assert _ids(GOOD, probe) == {}


def test_a_control_taken_out_of_the_tab_order_is_reported(worker):
    page = '<!doctype html><html lang="en"><body><button>One</button><button tabindex="-1">Two</button><a href="/x">Three</a></body></html>'
    kb = _capture(worker, page)["keyboard"]
    assert kb["tab_stops"] == 2 and kb["unreached"] == []        # tabindex -1 is a decision, not a miss
    page = '<!doctype html><html lang="en"><body><button>One</button><div id="d" contenteditable="true">x</div></body></html>'
    assert _capture(worker, page)["keyboard"]["tab_stops"] == 2


def test_critique_lowers_the_score_and_blocks_shipping_for_floor_findings(worker):
    probe = _capture(worker, BAD)
    result = critique.critique(probe=probe, html=BAD, use_vision=False)
    ids = {f["check_id"] for f in result["findings"] if f.get("check_id")}
    assert {"interaction/unnamed-control", "interaction/pointer-only-control", "interaction/focus-ring-missing"} <= ids
    assert result["ship_ready"] is False
    assert result["keyboard"]["tab_stops"] == 8 and result["keyboard"]["pointer_only"] == 2 and result["keyboard"]["without_focus_ring"] == 1
    assert "interaction/unnamed-control" in result["keyboard"]["rules"]
    assert any(f["area"] == "a11y" for f in result["findings"])
    clean = critique.critique(probe=_capture(worker, GOOD), html=GOOD, use_vision=False)
    assert not [f for f in clean["findings"] if str(f.get("check_id", "")).startswith("interaction/")]
    assert clean["keyboard"]["open_findings"] == 0 and critique.critique(probe={}, html=GOOD, use_vision=False)["keyboard"] is None
