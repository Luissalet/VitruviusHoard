import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from vitruvius_hoard import assay
from vitruvius_hoard.functional_check import browser
from vitruvius_hoard.functional_check.qa import UNKNOWN
from vitruvius_hoard.functional_check.run import judge
from vitruvius_hoard.functional_check.surface import Case


def test_timeout_retains_completed_criterion_and_blocking_action(tmp_path, monkeypatch):
    def time_out(command, **kwargs):
        progress = Path(command[command.index("--progress") + 1])
        progress.write_text(json.dumps({
            "planned": 3,
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
