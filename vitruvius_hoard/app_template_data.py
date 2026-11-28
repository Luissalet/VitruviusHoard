"""Edit the literal project data used by the template renderer."""
from __future__ import annotations

import json

from .app_project_results import source_summary
from .app_source_map import _ATTRIBUTE, _HTML, _MARKER, _TAG_NAME
from .hoard_link.agentkit import AppError

_TEXT_ATTRIBUTES = {"title", "alt", "aria-label", "aria-description", "placeholder"}


def _copy_spans(source):
    parsed = _HTML(source)
    spans = [(start, end) for start, end in parsed.text if "<" not in source[start:end]]
    for tag in parsed.tags:
        if tag.name in {"title", "textarea"}:
            spans.extend((start, end) for start, end in tag.text if "<" not in source[start:end])
        attrs = dict(tag.attrs)
        meta_description = (tag.name == "meta" and (attrs.get("name") or "").lower() == "description"
                            and "http-equiv" not in attrs)
        for token in _ATTRIBUTE.finditer(tag.raw, _TAG_NAME.match(tag.raw).end()):
            name = token["name"].lower()
            if name in _TEXT_ATTRIBUTES or (name == "content" and meta_description):
                # Escaped text can contain spaces. A bare attribute would still split there.
                start, end = token.span("double" if token["double"] is not None else "single")
                if start >= 0:
                    spans.append((tag.start + start, tag.start + end))
    return spans


def _validate_text_uses(files, changed):
    for path, source in files.items():
        if path != "layout.html" and not (path.startswith("pages/") and path.endswith(".html")):
            continue
        tokens = [token for token in _MARKER.finditer(source) if token[1] in changed]
        if not tokens:
            continue
        spans = _copy_spans(source)
        if any(not any(start <= token.start() and token.end() <= end for start, end in spans) for token in tokens):
            raise AppError("invalid_template_use",
                           f"Project copy needs a text context. / Usa los textos de plantilla en un contexto textual: {path}",
                           status=400, details={"path": path})


def template_data_changes(files, fields):
    path = "project.json"
    spec = json.loads(files[path])
    patch = {key: value for key, value in fields.items() if spec.get(key, "") != value}
    if not patch:
        return {}
    _validate_text_uses(files, patch)
    return {path: json.dumps({**spec, **patch}, ensure_ascii=False, indent=2) + "\n"}


def edit_project_template_data(projects, project_id, expected_revision, fields, *, actor, author):
    """Save a single reversible revision of project.json."""
    with projects.lock:
        current = projects.get(project_id)
        if current["revision"] != expected_revision:
            raise AppError("conflict", "Read the current project revision. / Lee la revisión actual del proyecto.",
                           status=409, details={"revision": current["revision"]})
        changes = template_data_changes(current["files"], fields)
        if not changes:
            return source_summary(current, changed_paths=[])
        saved = projects.update(project_id, changes, expected_revision, actor=actor, author=author)
        return source_summary(saved, changed_paths=list(changes))
