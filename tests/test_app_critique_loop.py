from pathlib import Path

import pytest

from vitruvius_hoard.app_projects import AppProjects
from vitruvius_hoard.hoard_link.agentkit import AppError
from vitruvius_hoard.lint import score_of


def finding(criterion, severity, detail=""):
    return {"check_id": criterion, "severity": severity, "title": criterion, "detail": detail}


def record(apps, project, findings):
    receipt = apps.prepare_critique_round(project["id"], project["revision"], None)
    report = {"score": score_of(findings), "findings": findings}
    return apps.record_critique_round(project["id"], project["revision"], receipt, report, "capture")


def edit(apps, project, text):
    html = f"<h1>{text}</h1>"
    return apps.update(project["id"], {"pages/index.html": html}, project["revision"])


def test_lamp_sequence_reverts_to_round_two_and_retains_each_rejected_source(tmp_path: Path):
    apps = AppProjects(tmp_path)
    initial = apps.create("Lamp")
    small = finding("a11y.small-targets", "warn", "Brand tap target below 44px.")
    thin = finding("craft/thin-section", "warn")
    scale = finding("ds/scale", "info")
    wrapped = finding("craft/button-wrap", "error", "Brand label measured as wrapped.")
    rough = [small, thin, scale, finding("slop/tracked-caps-label", "error")]
    rough += [finding(f"warning-{i}", "warn") for i in range(6)]
    rough += [finding(f"info-{i}", "info") for i in range(5)]
    first = record(apps, initial, rough)
    assert first["best"]["score"] == 3.45

    second = edit(apps, initial, "Version two")
    kept = record(apps, second, [small, thin, scale])
    assert kept["best"]["score"] == 7.41
    best_timestamp = apps.get(initial["id"])["updated_ts"]
    assert kept["undo"]["arguments"]["expected_updated_ts"] == best_timestamp

    for number in (3, 4):
        candidate = edit(apps, apps.get(initial["id"]), f"Version {number}")
        result = record(apps, candidate, [thin, wrapped, scale])
        latest = result["latest"]
        assert result["best"]["revision"] == result["revision"] == second["revision"]
        assert latest["decision"] == "restored"
        assert latest["number"] == number and latest["score"] == 6.25 and latest["score_delta"] == -1.16
        assert latest["revision"] == candidate["revision"]
        assert latest["changed_files"] == ["pages/index.html"]
        assert latest["regressions"][0]["after"] == [wrapped]
        assert latest["improvements"][0]["before"] == [small]
        assert apps.get(initial["id"])["files"] == second["files"]
        assert apps.get(initial["id"], candidate["revision"])["files"] == candidate["files"]

    restarted = AppProjects(tmp_path)
    history = restarted.critique_loop(initial["id"])
    assert [row["score"] for row in history["rounds"]] == [3.45, 7.41, 6.25, 6.25]
    assert "critique_loop" not in restarted.get(initial["id"])
    assert "critique_loop" not in restarted.list()[0]
    undone = restarted.undo_critique_round(**result["undo"]["arguments"])
    assert len(undone["rounds"]) == 3 and undone["revision"] == candidate["revision"]
    assert undone["best"]["revision"] == second["revision"]


def test_tie_keeps_active_candidate_and_original_best(tmp_path):
    apps = AppProjects(tmp_path)
    first = apps.create("Tie")
    record(apps, first, [])
    candidate = edit(apps, first, "Equal score")
    result = record(apps, candidate, [])
    assert result["latest"]["decision"] == "tie"
    assert result["revision"] == candidate["revision"]
    assert result["best"]["revision"] == first["revision"]
    assert apps.get(first["id"])["updated_ts"] == candidate["updated_ts"]


def test_source_and_round_compare_and_swap_prevent_stale_writes(tmp_path):
    apps = AppProjects(tmp_path)
    first = apps.create("Concurrent")
    id, old = first["id"], first["revision"]
    receipt = apps.prepare_critique_round(id, old, None)
    candidate = edit(apps, first, "Newer source")
    with pytest.raises(AppError, match="changed"):
        apps.record_critique_round(id, old, receipt, {"score": 4, "findings": []}, "stale")
    assert apps.critique_loop(id)["rounds"] == []
    assert apps.get(id)["revision"] == candidate["revision"]
    receipt = apps.prepare_critique_round(id, candidate["revision"], "system-one")
    result = apps.record_critique_round(id, candidate["revision"], receipt, {"score": 8, "findings": []}, "capture")
    with pytest.raises(AppError, match="changed"):
        apps.record_critique_round(id, candidate["revision"], receipt, {"score": 8, "findings": []}, "duplicate")
    with pytest.raises(AppError, match="same design system"):
        apps.prepare_critique_round(id, candidate["revision"], "system-two")
    latest = edit(apps, candidate, "Third source")
    with pytest.raises(AppError, match="changed"):
        apps.undo_critique_round(**result["undo"]["arguments"])
    assert apps.get(id)["revision"] == latest["revision"]



def test_critique_and_single_step_undo_preserve_each_others_history(tmp_path):
    apps = AppProjects(tmp_path)
    initial = apps.create("Combined history")
    project_id = initial["id"]
    record(apps, initial, [])
    rejected = edit(apps, initial, "Rejected")
    result = record(apps, rejected, [finding("craft/button-wrap", "error")])
    restored = apps.get(project_id)
    assert restored["revision"] == initial["revision"]
    assert restored["history"][-1]["action"] == "critique-restore"
    assert restored["history"][-1]["files"] == ["pages/index.html"]
    assert restored["history"][-1]["author"] == {"kind": "system"}
    round_undo = apps.undo_critique_round(**result["undo"]["arguments"])
    reopened = apps.get(project_id)
    assert reopened["revision"] == rejected["revision"] == round_undo["revision"]
    assert reopened["history"][-1]["action"] == "critique-undo"
    project = apps.update(project_id, {"assets/extra.css": "body { color: black; }"}, reopened["revision"])
    edit_entry = next(row for row in project["history"] if row["action"] == "edit"
                      and row["revision"] == rejected["revision"])
    undone = apps.undo_change(project_id, edit_entry["id"], project["revision"], project["updated_ts"])
    assert undone["files"]["pages/index.html"] == initial["files"]["pages/index.html"]
    assert undone["files"]["assets/extra.css"] == project["files"]["assets/extra.css"]
    assert undone["history"][-1]["action"] == "undo-change"
    assert apps.critique_loop(project_id)["best"]["revision"] == initial["revision"]
    restored_revision = apps.undo(project_id, undone["revision"], undone["updated_ts"], rejected["revision"])
    assert restored_revision["history"][-1]["action"] == "undo"
    assert len(apps.critique_loop(project_id)["rounds"]) == 1
