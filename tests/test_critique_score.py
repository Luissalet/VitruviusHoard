from __future__ import annotations

import pytest

from vitruvius_hoard import critique
from vitruvius_hoard.lint import score_of


def _findings(*, errors=0, warnings=0, advisories=0):
    return [
        {"check_id": f"{tier}-{index}", "title": f"{tier} {index}", "area": "color",
         "severity": severity, "tier": tier}
        for severity, tier, count in (
            ("error", "floor", errors), ("warn", "reflex", warnings), ("info", "finish", advisories),
        )
        for index in range(count)
    ]


@pytest.mark.parametrize(("errors", "warnings", "advisories", "expected"), [
    pytest.param(2, 15, 0, 2.60, id="original-home"),
    pytest.param(0, 8, 1, 4.44, id="home-errors-fixed"),
    pytest.param(0, 6, 0, 5.26, id="contacts-with-warnings"),
])
def test_critique_separates_the_reported_benchmark_counts(monkeypatch, errors, warnings, advisories, expected):
    findings = _findings(errors=errors, warnings=warnings, advisories=advisories)
    monkeypatch.setattr(critique, "run_lint", lambda *args, **kwargs: {"findings": findings})
    result = critique.critique(probe={}, html="", use_vision=False)

    assert result["score"] == result["heuristic_score"] == expected
    assert result["gate"]["floor"] == errors
    assert result["gate"]["reflex_open"] == warnings
    assert result["gate"]["finish"] == advisories
    assert result["ship_ready"] is False
    assert f"heuristic score {expected}/10" in result["summary"]


@pytest.mark.parametrize("severity", ["info", "warn", "error"])
def test_removing_findings_improves_the_score_even_past_the_old_floor(severity):
    findings = [{"severity": severity}] * 40
    scores = [score_of(findings[:count]) for count in range(len(findings) + 1)]

    assert scores[0] == 10.0
    assert all(0.0 < worse < better for better, worse in zip(scores, scores[1:]))


def test_reducing_severity_improves_the_score_at_constant_finding_count():
    common = _findings(warnings=15)
    scores = [score_of([*common, {"severity": severity}]) for severity in ("error", "warn", "info")]

    assert scores[0] < scores[1] < scores[2] < score_of(common)


def test_waived_findings_have_no_weight():
    waived = [{"severity": "warn", "waived": True}] * 25
    open_findings = _findings(errors=2, warnings=1, advisories=1)

    assert score_of(waived) == 10.0
    assert score_of([*open_findings, *waived]) == score_of(open_findings)
