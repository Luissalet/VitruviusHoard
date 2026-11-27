"""Compact application receipts for agent tools."""

from hashlib import sha256


def source_summary(project, *, changed_path=None, edit=False):
    keys = ("id", "name", "template", "revision", "selected_revision", "updated_ts", "source_sha256",
            "preview", "preview_warning", "undo")
    summary = {key: project[key] for key in keys if key in project}
    files = project["files"]
    paths = [changed_path] if changed_path is not None else []
    if not edit:
        paths = sorted(files)
    entries = []
    for path in paths:
        content = files[path].encode("utf-8")
        entries.append({"path": path, "bytes": len(content), "sha256": sha256(content).hexdigest()})
    if edit:
        summary.update(changed=bool(entries), changed_files=entries)
    else:
        summary["file_manifest"] = entries
    return summary


def render_summary(render):
    keys = ("id", "url", "widths", "files", "app_project")
    summary = {key: render[key] for key in keys if key in render}
    lint = render["lint"]
    findings = lint["findings"]
    summary["lint"] = {
        "score": lint["score"],
        "count": len(findings),
        "counts": lint["counts"],
        "findings": [
            {key: finding[key] for key in ("check_id", "tier", "severity", "title", "detail", "fix") if key in finding}
            for finding in findings if finding.get("tier") in ("floor", "reflex")
        ],
    }
    if "error" in render["metrics"]:
        summary["error"] = render["metrics"]["error"]
        summary["hint"] = render["metrics"].get("hint")
    return summary
