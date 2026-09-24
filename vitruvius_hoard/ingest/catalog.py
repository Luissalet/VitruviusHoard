"""CSV/JSON catalog parsers: robust to unknown columns (keep `raw`).

Produces rows shaped for the `styles`, `palettes` and `font_pairings` tables.
Column names are matched case-insensitively and loosely (several aliases per
field) so the parsers survive schema drift in the upstream repos.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any


def _get(row: dict[str, Any], *names: str) -> str:
    lower = {k.lower().strip(): v for k, v in row.items() if k}
    for name in names:
        v = lower.get(name.lower())
        if v not in (None, ""):
            return str(v)
    return ""


def _list_field(value: str) -> list[str]:
    if not value:
        return []
    for sep in (";", "|", ","):
        if sep in value:
            return [p.strip() for p in value.split(sep) if p.strip()]
    return [value.strip()]


_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def _hexes(text: str) -> list[str]:
    """Every hex colour mentioned in a free-text colour description, in order, unique."""
    out: list[str] = []
    for m in _HEX_RE.findall(text or ""):
        m = m.lower()
        if m not in out:
            out.append(m)
    return out


def read_csv_rows(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    return [dict(r) for r in reader]


def read_json_rows(text: str) -> list[dict[str, Any]]:
    data = json.loads(text)
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("items", "styles", "palettes", "fonts", "rows", "data"):
            if isinstance(data.get(key), list):
                return [r for r in data[key] if isinstance(r, dict)]
        return [data]
    return []


def parse_styles(rows: list[dict[str, Any]], source_id: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        name = _get(row, "name", "style", "style_name", "style category")
        if not name:
            continue
        slug = _get(row, "slug", "id") or name.lower().replace(" ", "-")
        out.append({
            "source_id": source_id,
            "name": name,
            "slug": slug,
            "description": _get(row, "description", "desc", "summary", "ai prompt keywords", "type"),
            "keywords": _list_field(_get(row, "keywords", "tags", "css/technical keywords")),
            "colors": _hexes(_get(row, "colors", "palette", "primary colors") + " " + _get(row, "secondary colors"))
                      or _list_field(_get(row, "colors", "palette", "primary colors")),
            "typography": {"heading": _get(row, "heading_font", "font_heading"),
                          "body": _get(row, "body_font", "font_body")},
            "effects": _list_field(_get(row, "effects", "motion", "effects & animation")),
            "best_for": _list_field(_get(row, "best_for", "best for", "use_for", "when_to_use")),
            "avoid": _list_field(_get(row, "avoid", "dont", "do_not", "do not use for")),
            "css_hints": _get(row, "css_hints", "css", "notes", "implementation checklist", "design system variables"),
            "raw": row,
        })
    return out


def parse_palettes(rows: list[dict[str, Any]], source_id: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        name = _get(row, "name", "palette", "palette_name", "product type")
        if not name:
            continue
        colors = []
        raw_colors = _get(row, "colors", "hexes", "swatches")
        for hx in _list_field(raw_colors):
            hx = hx.strip()
            if hx:
                colors.append({"role": "", "hex": hx if hx.startswith("#") else f"#{hx}"})
        # Also accept role=hex columns like primary/secondary/accent/neutral.
        for role in ("primary", "on primary", "secondary", "on secondary", "accent", "on accent", "neutral", "background", "foreground", "surface", "card", "muted", "border", "destructive", "ring"):
            v = _get(row, role)
            if v:
                colors.append({"role": role, "hex": v if v.startswith("#") else f"#{v}"})
        out.append({
            "source_id": source_id,
            "name": name,
            "product_type": _get(row, "product_type", "product type", "type", "category"),
            "colors": colors,
            "notes": ((_get(row, "font pairing name") + " — ") if _get(row, "font pairing name") else "") + (_get(row, "notes", "description") or ("Best for: " + _get(row, "best for"))),
        })
    return out


def parse_font_pairings(rows: list[dict[str, Any]], source_id: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        heading = _get(row, "heading", "heading_font", "heading font", "display", "title_font")
        body = _get(row, "body", "body_font", "body font", "text_font")
        if not heading and not body:
            continue
        out.append({
            "source_id": source_id,
            "heading": heading,
            "body": body,
            "mono": _get(row, "mono", "mono_font", "code_font"),
            "category": _get(row, "category", "type"),
            "mood": _get(row, "mood", "vibe", "mood/style keywords"),
            "name": _get(row, "font pairing name", "name"),
            "google_fonts_url": _get(row, "google_fonts_url", "google fonts url", "url", "link"),
            "notes": ((_get(row, "font pairing name") + " — ") if _get(row, "font pairing name") else "") + (_get(row, "notes", "description") or ("Best for: " + _get(row, "best for"))),
        })
    return out


def rows_to_chunks(rows: list[dict[str, Any]], title: str, max_rows: int = 400) -> list[dict[str, Any]]:
    """Any tabular catalog (motion, UX guidelines, landing patterns, charts, stacks) → one
    searchable chunk per row: "Column: value" lines, heading = the row's name-ish field."""
    out = []
    for i, row in enumerate(rows[:max_rows]):
        lines = []
        head = ""
        for k, v in row.items():
            if not k or v in (None, ""):
                continue
            k = str(k).strip()
            if k.lower() in ("no", "id"):
                continue
            v = str(v).strip()
            if not head and k.lower() not in ("category", "platform", "type"):
                head = v[:80]
            lines.append(f"{k}: {v}")
        if not lines:
            continue
        out.append({"heading": f"{title} › {head}" if head else title, "ordinal": i, "text": "\n".join(lines)[:1500], "tokens": 0})
    return out


def rows_to_rules(rows: list[dict[str, Any]], source_id: str) -> list[dict[str, Any]]:
    """UX-guideline style tables (Category/Issue/Do/Don't/Severity) → rules rows."""
    out = []
    for row in rows:
        issue = _get(row, "issue", "rule", "title", "name")
        do = _get(row, "do")
        dont = _get(row, "don't", "dont", "do not")
        if not issue or not (do or dont):
            continue
        cat = _get(row, "category", "area").lower()
        area = "layout"
        for key, val in (("typ", "typography"), ("font", "typography"), ("color", "color"), ("colour", "color"), ("motion", "motion"), ("anim", "motion"), ("access", "a11y"), ("a11y", "a11y"), ("form", "forms"), ("perf", "performance"), ("content", "content"), ("copy", "content"), ("nav", "layout"), ("layout", "layout"), ("responsive", "layout")):
            if key in cat:
                area = val
                break
        sev = _get(row, "severity").lower()
        severity = "error" if sev.startswith("high") or sev.startswith("crit") else ("warn" if sev.startswith("med") else "info")
        text = " ".join(p for p in (_get(row, "description"), f"Do: {do}" if do else "", f"Don't: {dont}" if dont else "") if p)
        out.append({"source_id": source_id, "area": area, "severity": severity, "title": f"{issue} ({_get(row, 'platform') or cat})".strip(), "text": text[:1200], "check_id": None})
    return out
