"""Editable, bilingual reservation pages with a static publication contract."""

from html import escape
import json
from pathlib import Path
import re

from .tokens import best_on_color


TEMPLATE = {
    "id": "booking", "name": "Booking", "name_es": "Reservas", "accent": "#18364d",
    "fields": [{"name": "name", "label": "Name", "type": "text"}],
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _localized(value, name, optional=False):
    if isinstance(value, str):
        value = {"es": value, "en": value}
    if not isinstance(value, dict) or any(not isinstance(value.get(lang), str) for lang in ("es", "en")):
        raise ValueError(f"{name} needs text or an es/en text pair")
    if not optional and any(not value[lang].strip() for lang in ("es", "en")):
        raise ValueError(f"{name} must have text in both languages")
    return {lang: value[lang].strip() for lang in ("es", "en")}


def site_files(spec, accent, items, lang, description):
    if not items or len(items) > 100:
        raise ValueError("Booking needs one to 100 items")
    catalogue = []
    seen = set()
    for row in items:
        ident = row.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", ident) or ident in seen:
            raise ValueError("Each booking item needs a unique lowercase id")
        seen.add(ident)
        catalogue.append({"id": ident, "title": _localized(row.get("title"), "Item title"),
                          "category": _localized(row.get("category"), "Item category"),
                          "description": _localized(row.get("description", ""), "Item description", optional=True)})
    site = {"lang": lang, "description": _localized(description, "Description", optional=True), "items": catalogue}
    fields = {"item": catalogue[0]["id"], "date": "2035-06-15",
              "name": "Synthetic booking", "email": "booking@example.invalid"}
    contract = {"version": 1, "form": {"path": "/api/forms", "schema": "submissions",
                                      "fields": fields, "marker_field": "name"}}
    directory = Path(__file__).with_name("booking_assets")
    html = (directory / "index.html").read_text(encoding="utf-8")
    data = _json(site).replace("<", "\\u003c")
    replacements = {"__LANG__": lang, "__SITE_DATA__": data, "__TITLE__": escape(spec["name"]),
                    "__DESCRIPTION__": escape(site["description"][lang] or spec["name"])}
    html = re.sub("|".join(replacements), lambda match: replacements[match[0]], html)
    css = (directory / "booking.css").read_text(encoding="utf-8")
    css = css.replace("__ACCENT__", accent).replace("__ON_ACCENT__", best_on_color(accent, ("#ffffff", "#000000")))
    return {"public/index.html": html, "public/assets/booking.css": css,
            "public/assets/booking.js": (directory / "booking.js").read_text(encoding="utf-8"),
            "website.json": _json(contract)}
