import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from vitruvius_hoard import assay
from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.functional_check import browser
from vitruvius_hoard.functional_check.qa import UNKNOWN
from vitruvius_hoard.functional_check.run import Browser, check, judge
from vitruvius_hoard.functional_check.surface import Case


def test_timeout_retains_completed_criterion_and_blocking_action(tmp_path, monkeypatch):
    def time_out(command, **kwargs):
        progress = Path(command[command.index("--progress") + 1])
        progress.write_text(json.dumps({
            "planned": 4,
            "plan": [
                {"id": "C001", "what": "Show validation"},
                {"id": "C002", "what": "Save a reservation"},
                {"id": "C003", "what": "Read availability"},
                {"id": "C004", "what": "Clear the form"},
            ],
            "startup_blocked_writes": ["POST /startup-ping"],
            "cases": [
                {"id": "C001", "what": "Show validation", "outcome": "passed"},
                {"id": "C002", "what": "Save a reservation", "outcome": "unknown",
                 "detail": "The preview blocked the write."},
            ],
            "stopped_at": {"stage": "perform_action", "case_id": "C003",
                           "what": "Read availability", "action": {"verb": "click", "target": "#read"}},
        }), encoding="utf-8")
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(assay, "available", lambda: True)
    monkeypatch.setattr(assay, "_run_worker", time_out)
    result = assay.run(tmp_path, html="<form></form>", timeout_s=15)
    assert result["timed_out"] is True
    assert result["works"] is False
    assert result["passed"] == 1 and result["failed"] == 0 and result["unchecked"] == 3
    assert result["stopped_at"]["action"] == {"verb": "click", "target": "#read"}
    assert result["unchecked_cases"] == [
        {"id": "C002", "what": "Save a reservation", "detail": "The preview blocked the write."},
        {"id": "C003", "what": "Read availability"},
        {"id": "C004", "what": "Clear the form"},
    ]
    assert result["cases_sample"][0]["what"] == "Show validation"
    assert result["startup_blocked_writes"] == ["POST /startup-ping"]


def test_agent_retains_all_unchecked_cases_when_capping_large_results():
    missing = [{"id": f"C{index:03d}", "what": f"Check {index} " + "description " * 20}
               for index in range(100)]
    services = SimpleNamespace(assay_page=lambda **_: {
        "timed_out": True,
        "unchecked": len(missing),
        "unchecked_cases": missing,
        "cases_sample": [{"id": f"X{index:03d}", "detail": "details " * 100} for index in range(40)],
    })

    result = call_tool(services, "page_check", {"html": "<p>Page</p>"})

    assert result["unchecked_cases"] == missing
    assert result["truncated"]["original_lengths"] == {"cases_sample": 40}


def test_read_only_preview_separates_startup_and_action_writes(tmp_path, monkeypatch):
    url = "http://127.0.0.1:56158"
    page = Mock()
    engine = Browser(tmp_path, "index.html", url=url)
    engine._engine = Mock()
    engine._engine.new_context.return_value.new_page.return_value = page
    page.query_selector.return_value = object()
    engine._engine.new_context.return_value.pages = [page]
    monkeypatch.setattr(browser, "settle", lambda *args, **kwargs: None)
    monkeypatch.setattr(browser, "answer_dialogs", lambda page: None)

    def post(path):
        route = Mock(request=SimpleNamespace(method="POST", url=url + path, headers={}))
        handler = engine._engine.new_context.return_value.route.call_args.args[1]
        handler(route)
        route.abort.assert_called_once()
        route.continue_.assert_not_called()

    page.goto.side_effect = lambda *args, **kwargs: post("/startup-ping?run=1")

    def navigate(*args, **kwargs):
        navigation = Mock(request=SimpleNamespace(method="GET", url=url, frame=page.main_frame,
                                                 is_navigation_request=lambda: True))
        engine._engine.new_context.return_value.route.call_args.args[1](navigation)
        navigation.continue_.assert_called_once()

    page.click.side_effect = lambda target, **kwargs: (
        navigate() if target == "#open" else post("/reservations")
    )
    page.wait_for_timeout.side_effect = lambda ms: post("/loaded-ping") if ms == 100 else None
    with engine.open():
        post("/startup-ping?run=2")
        assert engine.startup_blocked_writes == ["POST /startup-ping"]
        assert engine.blocked_writes == []
        engine.perform(page, [{"click": "#open"}, {"wait": "0.1"}, {"click": "#save"}])
        assert engine.blocked_writes == ["POST /reservations"]
        assert engine.startup_blocked_writes == ["POST /startup-ping", "POST /loaded-ping"]

    with engine.open():
        assert engine.blocked_writes == []
        assert engine.startup_blocked_writes == ["POST /startup-ping", "POST /loaded-ping"]


def test_background_timers_do_not_invalidate_visible_help_but_action_timers_do(tmp_path):
    import pytest

    pytest.importorskip("playwright")
    from vitruvius_hoard.app_projects import AppProjects

    page = """
        <h1>Help and reservation</h1><button id="help">Show help</button>
        <button id="save">Save reservation</button><p id="note"></p>
        <script>
        const ping = (path) => fetch(path, {method: "POST"}).catch(() => {});
        setTimeout(() => ping("/startup-ping"), 2300);
        setTimeout(async () => {
          await Promise.resolve();
          await ping("/startup-after-await");
        }, 2300);
        async function postStartupStatus() {
          await new Promise(resolve => setTimeout(resolve, 2500));
          const status = new XMLHttpRequest();
          status.open("POST", "/startup-status");
          status.send();
        }
        setTimeout(() => postStartupStatus(), 0);
        document.querySelector("#help").onclick = () => {
          document.querySelector("#note").textContent = "Help is visible";
        };
        document.querySelector("#save").onclick = () => setTimeout(async () => {
          await Promise.resolve();
          await ping("/reservations");
        }, 50);
        </script>
    """
    projects = AppProjects(tmp_path, host_port=9)
    project = projects.create("Read-only preview")
    id = project["id"]
    projects.update(id, {"pages/index.html": page}, project["revision"])
    criteria = [
        Case(id="help", what="Show local help", origin="criterion", control="#help",
             acts=[{"click": "#help"}, {"wait": "3"}], expect={"want": "Help is visible"}),
        Case(id="save", what="Save through the preview", origin="criterion", control="#save",
             acts=[{"click": "#save"}, {"wait": "0.2"}], expect={"want": "Reservation saved"}),
    ]
    try:
        preview = projects.preview(id)
        result = check(tmp_path, criteria=criteria, url=preview["url"])
        cases = {row.case.what: row for row in result.results.values()}
        assert cases["Show local help"].outcome == "passed"
        assert cases["Save through the preview"].outcome == UNKNOWN
        assert "POST /reservations" in cases["Save through the preview"].detail
        assert set(result.startup_blocked_writes) == {
            "POST /startup-ping", "POST /startup-after-await", "POST /startup-status",
        }
    finally:
        projects.close()


def test_missing_second_click_is_unknown_and_preserves_first_press():
    case = Case(id="C007", what="Press Manage records twice",
                acts=[{"click": "Manage records"}, {"click": "Manage records"}],
                expect={"quiet": True})
    result = judge(case, {}, {}, [], ["click Manage records: Timeout 4000ms"], [], "",
                   answered_once=True)
    assert result.outcome == UNKNOWN
    assert "Timeout 4000ms" in result.detail
    assert "the first press: changed the page" in result.evidence


def test_in_progress_fill_names_the_target_without_the_entered_value():
    actions = []
    entered = []
    page = SimpleNamespace(fill=lambda target, value, **_: entered.append((target, value)))
    browser.perform(page, [{"fill": "#email=qa@example.invalid"}], on_act=actions.append)
    assert entered == [("#email", "qa@example.invalid")]
    assert actions == [{"verb": "fill", "target": "#email"}]



def test_automatic_label_click_reuses_only_a_current_native_obstruction(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("playwright")
    (tmp_path / "index.html").write_text("""
        <label style="position:relative; display:inline-block; cursor:pointer">
          <input id="option" type="radio" style="position:absolute; opacity:0; inset:0; width:100%; height:100%; margin:0">
          <span id="text">One option</span>
        </label>
    """, encoding="utf-8")
    acts = [{"click": "#text"}]
    automatic_labels = {"#text": {}}
    with Browser(tmp_path, "index.html") as engine, engine.open() as (page, *_):
        click = Mock(wraps=page.click)
        monkeypatch.setattr(page, "click", click)
        first, _ = browser.perform(page, acts, timeout=350, settle_ms=0, automatic_labels=automatic_labels)
        assert "Timeout" in first[0]
        repeat, _ = browser.perform(page, acts, timeout=350, settle_ms=0, automatic_labels=automatic_labels)
        assert "covered by its own input #option" in repeat[0]
        assert click.call_count == 1

        explicit, _ = browser.perform(page, acts, timeout=350, settle_ms=0)
        assert "Timeout" in explicit[0]
        assert click.call_count == 2

        page.locator("#option").evaluate("element => element.style.pointerEvents = 'none'")
        uncovered, _ = browser.perform(page, acts, timeout=1000, settle_ms=0, automatic_labels=automatic_labels)
        assert uncovered == []
        assert click.call_count == 3
        assert page.locator("#option").is_checked()

    result = check(tmp_path)
    repeated = next(row for row in result.results.values() if row.case.what == "click One option twice")
    assert repeated.outcome == UNKNOWN
    assert "covered by its own input #option" in repeated.detail


def test_automatic_label_remembers_interception_during_playwright_scroll(monkeypatch):
    import pytest

    playwright = pytest.importorskip("playwright.sync_api")
    cover = Mock(side_effect=["option", None, None])
    monkeypatch.setattr(browser, "_covering_label_input", cover)
    page = Mock(url="http://127.0.0.1/controls")
    page.click.side_effect = playwright.TimeoutError(
        'Page.click: Timeout 4000ms exceeded.\n  - <input id="option"/> intercepts pointer events')
    results = {}
    for _ in range(2):
        with pytest.raises(playwright.TimeoutError):
            browser._click(page, "#text", "", 4000, results)
    assert results == {(page.url, "#text"): "option"}
    assert page.click.call_count == 2


def test_navigation_link_is_pressed_once_and_missing_target_returns_immediately(tmp_path):
    import pytest
    from vitruvius_hoard.functional_check.surface import from_page, plan

    pytest.importorskip("playwright")
    (tmp_path / "index.html").write_text(
        '<h1>Home</h1><a id="away" href="destination.html">Continue</a>'
        '<button id="toggle">Toggle</button>', encoding="utf-8")
    (tmp_path / "destination.html").write_text(
        '<h1>Destination</h1><button id="next" onclick="this.textContent = \'Done\'">Next</button>',
        encoding="utf-8")
    with Browser(tmp_path, "index.html") as engine:
        with engine.open() as (page, *_):
            surface = from_page(SimpleNamespace(elements=browser.elements(page)))
            labels = {case.what for case in plan(surface)}
            assert "press Continue" in labels and "press Continue twice" not in labels
            assert "press Toggle twice" in labels
            could_not, disabled = engine.perform(page, [
                {"click": "#away"}, {"click": "#away"}, {"click": "#next"},
            ])
            assert could_not == ["click #away: target is absent after navigation"]
            assert disabled == []
            assert page.locator("#next").inner_text() == "Done"


def test_cases_reuse_context_but_clear_page_storage(tmp_path):
    import pytest

    pytest.importorskip("playwright")
    (tmp_path / "index.html").write_text("<button>Start</button>", encoding="utf-8")
    with Browser(tmp_path, "index.html") as engine:
        with engine.open() as (page, *_):
            context = page.context
            page.evaluate("""() => {
                localStorage.setItem('prior', 'local');
                sessionStorage.setItem('prior', 'session');
                document.cookie = 'prior=cookie; path=/';
            }""")
        with engine.open() as (page, *_):
            assert page.context is context
            assert page.evaluate("""() => [
                localStorage.getItem('prior'), sessionStorage.getItem('prior'), document.cookie,
            ]""") == [None, None, ""]
