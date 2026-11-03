"""Language of the design rules, the slop audit and the direction brief ("es" | "en").

English is the source: rules, audits on disk and the lint all stay English. ``localize_finding`` / ``localize_audit`` render a
copy in Spanish (Spain) from the translation table in ``i18n_es`` (keyed by rule id), so a stored audit can be re-read in
either language without running anything again.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Optional

from . import i18n_es as es

LANGS = ("es", "en")
DEFAULT_LANG = "es"


def norm_lang(lang: Optional[str] = None, accept_language: Optional[str] = None, default: str = DEFAULT_LANG) -> str:
    """An explicit ``lang`` wins, then the first supported tag of an Accept-Language header, then ``default`` (es)."""
    for cand in (lang,):
        c = (cand or "").strip().lower()[:2]
        if c in LANGS:
            return c
    for part in (accept_language or "").split(","):
        c = part.split(";")[0].strip().lower()[:2]
        if c in LANGS:
            return c
    return default if default in LANGS else DEFAULT_LANG


def rule_texts(rule_id: str, lang: str) -> Optional[dict[str, str]]:
    """{name, description, fix} of a rule in ``lang`` (None for English or an id without a Spanish row)."""
    if lang != "es":
        return None
    row = es.RULES_ES.get(rule_id)
    return {"name": row[0], "description": row[1], "fix": row[2]} if row else None


_SEEN = re.compile(r"\s*Seen at ([0-9, ]+)px\.\s*$")
_LEAD = re.compile(r"^\s*(\d+)\b")


def _detail_es(detail: str, texts: dict[str, str]) -> str:
    """The measured sentence is built in code from English fragments, so in Spanish it becomes the rule's own description
    plus the counts and widths the measurement found (those are numbers, not words)."""
    text = texts["description"]
    m = _LEAD.match(detail or "")
    if m:
        text += f" Detectados: {m.group(1)}."
    seen = _SEEN.search(detail or "")
    if seen:
        text += f" Visto a {seen.group(1).strip()} px."
    return text


def localize_finding(f: dict, lang: str) -> dict:
    """A copy of a finding with title, detail and fix in ``lang`` (unchanged for English or an unknown rule)."""
    if lang != "es":
        return f
    texts = rule_texts(f.get("check_id") or "", lang)
    if not texts:
        return f
    g = dict(f)
    g["title"], g["fix"] = texts["name"], texts["fix"]
    g["detail"] = _detail_es(f.get("detail") or "", texts)
    return g


def localize_findings(findings: list[dict], lang: str) -> list[dict]:
    return [localize_finding(f, lang) for f in findings]


def localize_audit(audit: dict, lang: str) -> dict:
    """The stored (English) audit rendered in ``lang``: findings, the fix plan, the credit line."""
    from . import slop_audit
    lang = norm_lang(lang)
    out = copy.deepcopy(audit)
    out["lang"] = lang
    if lang == "es":
        out["findings"] = localize_findings(out.get("findings") or [], lang)
        out["plan"] = slop_audit.plan(out["findings"], out.get("mode") or "none", lang)
        out["credit"] = es.CREDIT_ES
    else:
        out["plan"] = slop_audit.plan(out.get("findings") or [], out.get("mode") or "none", "en")
        out["credit"] = es.CREDIT_EN
    return out


def localize_rule_row(row: dict, lang: str) -> dict:
    texts = rule_texts(row.get("id") or "", lang)
    if not texts:
        return row
    return {**row, "name": texts["name"], "description": texts["description"], "fix": texts["fix"]}


def mode_name(mode: str, lang: str) -> str:
    return es.MODE_NAMES_ES.get(mode, mode) if lang == "es" else mode


def pass_title(name: str, lang: str, english: dict[str, str]) -> str:
    return es.PASS_TITLES_ES.get(name, english.get(name, name)) if lang == "es" else english.get(name, name)
