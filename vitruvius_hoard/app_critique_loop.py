"""Score comparisons for the retained application critique loop."""
from collections import defaultdict
from uuid import uuid4

from .i18n import localize_findings
from .lint import score_of


WIDTHS = (390, 834, 1440)


def empty_loop():
    return {"tokens_id": None, "rounds": [], "best_round": None}


def _group(findings):
    groups = defaultdict(list)
    for finding in findings:
        if not finding.get("waived"):
            key = finding.get("check_id") or f"{finding.get('area', 'design')}: {finding.get('title', '')}"
            groups[key].append(finding)
    return groups


def compare_findings(previous, current):
    before, after = _group(previous), _group(current)
    worse, better = [], []
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key, []), after.get(key, [])
        change = score_of(new) - score_of(old)
        if change:
            (worse if change < 0 else better).append({"criterion": key, "before": old, "after": new})
    return worse, better


def add_round(loop, project, baseline, report, render_id, tokens_id):
    findings = [{key: item[key] for key in ("check_id", "area", "severity", "title", "detail", "evidence", "waived")
                 if key in item} for item in report["findings"]]
    best_index = loop["best_round"]
    best = loop["rounds"][best_index] if best_index is not None else None
    score = report["score"]
    decision = "best" if best is None or score > best["score"] else "restored" if score < best["score"] else "tie"
    regressions, improvements, changed = [], [], []
    if best is not None:
        regressions, improvements = compare_findings(best["findings"], findings)
        before, after = baseline["files"], project["files"]
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
    entry = {
        "id": uuid4().hex, "number": len(loop["rounds"]) + 1, "revision": project["revision"],
        "source_sha256": project["source_sha256"], "render_id": render_id, "score": score,
        "decision": decision, "active_revision": best["revision"] if decision == "restored" else project["revision"],
        "compared_to": best["revision"] if best else None, "previous_best_score": best["score"] if best else None,
        "score_delta": round(score - best["score"], 2) if best else None,
        "changed_files": changed, "regressions": regressions, "improvements": improvements, "findings": findings,
    }
    if decision == "best":
        best_index = len(loop["rounds"])
    return {"tokens_id": tokens_id, "rounds": [*loop["rounds"], entry], "best_round": best_index}, entry


def remove_round(loop):
    rounds = loop["rounds"][:-1]
    if not rounds:
        return empty_loop()
    best = max(range(len(rounds)), key=lambda index: rounds[index]["score"])
    return {**loop, "rounds": rounds, "best_round": best}


def loop_view(project_id, revision, loop, lang):
    rounds, best = loop["rounds"], loop["best_round"]
    summaries = [{key: entry[key] for key in ("id", "number", "revision", "score", "decision", "render_id",
                                             "active_revision", "score_delta")} for entry in rounds]
    latest = None
    if rounds:
        latest = {**rounds[-1], "findings": localize_findings(rounds[-1]["findings"], lang)}
        for category in ("regressions", "improvements"):
            latest[category] = [
                {**change, "before": localize_findings(change["before"], lang),
                 "after": localize_findings(change["after"], lang)} for change in latest[category]
            ]
    return {"id": project_id, "revision": revision, "widths": list(WIDTHS), "tokens_id": loop["tokens_id"],
            "best": summaries[best] if best is not None else None, "latest": latest, "rounds": summaries}
