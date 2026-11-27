import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from vitruvius_hoard import assay
from vitruvius_hoard.functional_check import browser
from vitruvius_hoard.functional_check.qa import UNKNOWN
from vitruvius_hoard.functional_check.run import Browser, check, judge
from vitruvius_hoard.functional_check.surface import Case


def test_timeout_retains_completed_criterion_and_blocking_action(tmp_path, monkeypatch):
    def time_out(command, **kwargs):
        progress = Path(command[command.index("--progress") + 1])
        progress.write_text(json.dumps({
            "planned": 3,
            "startup_blocked_writes": ["POST /startup-ping"],
            "cases": [{"id": "C001", "what": "Show validation", "outcome": "passed"}],
            "stopped_at": {"stage": "perform_action", "case_id": "C002",
                           "what": "Save a reservation", "action": {"verb": "click", "target": "#send"}},
        }), encoding="utf-8")
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(assay, "available", lambda: True)
    monkeypatch.setattr(assay.proc, "run", time_out)
    result = assay.run(tmp_path, html="<form></form>", timeout_s=15)
    assert result["timed_out"] is True
    assert result["works"] is False
    assert result["passed"] == 1 and result["failed"] == 0 and result["unchecked"] == 2
    assert result["stopped_at"]["action"] == {"verb": "click", "target": "#send"}
    assert result["cases_sample"][0]["what"] == "Show validation"
    assert result["startup_blocked_writes"] == ["POST /startup-ping"]


def test_read_only_preview_separates_startup_and_action_writes(tmp_path, monkeypatch):
    url = "http://127.0.0.1:56158"
    page = Mock()
    engine = Browser(tmp_path, "index.html", url=url)
    engine._engine = Mock()
    engine._engine.new_page.return_value = page
    monkeypatch.setattr(browser, "settle", lambda *args, **kwargs: None)
    monkeypatch.setattr(browser, "answer_dialogs", lambda page: None)

    def post(path):
        route = Mock(request=SimpleNamespace(method="POST", url=url + path, headers={}))
        handler = page.route.call_args.args[1]
        handler(route)
        route.abort.assert_called_once()
        route.continue_.assert_not_called()

    page.goto.side_effect = lambda *args, **kwargs: post("/startup-ping?run=1")

    def navigate(*args, **kwargs):
        navigation = Mock(request=SimpleNamespace(method="GET", url=url, frame=page.main_frame,
                                                 is_navigation_request=lambda: True))
        page.route.call_args.args[1](navigation)
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
        setTimeout(() => {
          const status = new XMLHttpRequest();
          status.open("POST", "/startup-status");
          status.send();
        }, 2500);
        document.querySelector("#help").onclick = () => {
          document.querySelector("#note").textContent = "Help is visible";
        };
        document.querySelector("#save").onclick = () => setTimeout(() => ping("/reservations"), 50);
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
        assert result.startup_blocked_writes == ["POST /startup-ping", "POST /startup-status"]
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
