"""Readable catalogue labels for the references saved with a canvas step."""

from __future__ import annotations

import re
from functools import cache, lru_cache

from .i18n import rule_texts
from .lint import ensure_rules
from .rules.registry import get_rule

_LINT_PACKS = ("slop/", "unslop/", "quality/")
_OPAQUE = re.compile(r"\b[0-9a-f]{10,}\b|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)


def _label(kind, es, en):
    return {"kind": kind, "es": es, "en": en}


@cache
def _showcase_titles():
    from .showcase import library
    return {row["id"]: (row["title"], row["title_en"]) for row in library._rows()}


@lru_cache(maxsize=128)
def _craft_title(reference):
    from . import craft
    kind, _, item = reference.removeprefix("craft/").partition("/")
    if kind not in craft.KINDS or not item:
        return None
    try:
        record = craft.read(kind, item)
    except (LookupError, ValueError):
        return None
    en = record.get("title") or record.get("label") or record.get("name")
    return (record.get("title_es") or en, en) if en else None


def _reference(value):
    reference = value.strip().removeprefix("[vitruvius: ").removesuffix("]")
    rule = get_rule(reference)
    if reference.startswith(_LINT_PACKS) or rule and rule.pack in {"slop", "unslop", "quality"}:
        if rule is None:
            return _label("lint", "Aviso sin nombre en el catálogo", "Unnamed lint finding")
        kind = "lint"
    elif rule:
        kind = "motion" if rule.scope == "motion" else "rule"
    else:
        kind = None
    if rule:
        es = rule_texts(rule.id, "es") or {}
        return _label(kind, es.get("name") or rule.name, rule.name)

    for prefix in ("showcase/", "recipe/"):
        reference = reference.removeprefix(prefix)
    title = _showcase_titles().get(reference)
    if not title and reference.startswith("craft/"):
        title = _craft_title(reference)
    if title:
        return _label("example", *title)

    if not _OPAQUE.search(reference):
        from . import presets
        preset = presets.get(reference.removeprefix("preset/"))
        if preset:
            return _label("preset", preset["title"], preset["title"])
    return _label("example", "Referencia sin nombre en el catálogo", "Unnamed library reference")


def describe_materials(entry, token_name):
    """Keep the raw references in the API and resolve display names separately."""
    ensure_rules()
    references, warnings = [], []
    for value in dict.fromkeys(entry.get("examples") or ()):
        if not value.strip():
            continue
        label = _reference(value)
        (warnings if label["kind"] == "lint" else references).append(label)

    token_id = entry.get("tokens_id")
    if token_id:
        name = (token_name(token_id) or "").strip()
        if not name or name == token_id or _OPAQUE.search(name):
            references.append(_label("tokens", "Paleta y tipografía", "Palette and typography"))
        else:
            references.append(_label("tokens", name, name))
    return {"references": references, "warnings": warnings}
