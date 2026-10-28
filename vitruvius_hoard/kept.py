"""``--before`` / ``--kept``: what a redesign must not lose.

Before a redesign the page's links, form fields, event handlers and titles are saved (``snapshot``). After it, ``compare`` against
the saved snapshot fails when any of them is missing. Static and deterministic: it reads the page source with the same parser the
static design rules use, never the model.
"""

from __future__ import annotations

import re
from typing import Any

from .rules.pagesrc import Page

CATEGORIES = ("links", "fields", "handlers", "titles")
_ON = re.compile(r"^on[a-z]+$")
_LISTENER = re.compile(
    r"(?:getElementById\(\s*['\"]([\w-]+)['\"]\s*\)|querySelector(?:All)?\(\s*['\"]([^'\"]{1,80})['\"]\s*\)|(\$|jQuery)\(\s*['\"]([^'\"]{1,80})['\"]\s*\))"
    r"\s*(?:\.\w+\([^)]*\)\s*)*\.(?:addEventListener\(\s*['\"](\w+)['\"]|on\(\s*['\"](\w+)['\"]|(onclick|onchange|oninput|onsubmit|onkeydown|onkeyup)\s*=)")
_DELEGATED = re.compile(r"document\.addEventListener\(\s*['\"](\w+)['\"]")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _label(node) -> str:
    n = node.label()
    return n


def snapshot(html: str) -> dict[str, Any]:
    page = Page(html or "")
    links, seen = [], set()
    for a in page.find("a"):
        href = (a.attrs.get("href") or "").strip()
        if not href or href.lower().startswith("javascript:"):
            continue
        key = href
        if key in seen:
            continue
        seen.add(key)
        links.append({"href": href, "text": _norm(a.text())[:80]})
    fields = []
    labels = {}
    for lab in page.find("label"):
        target = lab.attrs.get("for")
        if target:
            labels[target] = _norm(lab.text())[:60]
    for n in page.find_any(("input", "textarea", "select")):
        typ = (n.attrs.get("type") or ("text" if n.tag == "input" else n.tag)).lower()
        if typ in ("hidden", "submit", "button", "reset", "image"):
            if typ == "hidden" and n.attrs.get("name"):
                pass
            else:
                continue
        key = n.attrs.get("name") or n.attrs.get("id") or labels.get(n.attrs.get("id", ""), "") or n.attrs.get("placeholder") or ""
        if not key:
            continue
        fields.append({"key": key, "tag": n.tag, "type": typ, "label": labels.get(n.attrs.get("id", ""), "") or _norm(n.attrs.get("placeholder", ""))})
    handlers, hseen = [], set()

    def add(target: str, event: str) -> None:
        k = f"{target}:{event}"
        if k not in hseen:
            hseen.add(k)
            handlers.append({"target": target, "event": event})
    for n in page.nodes:
        for attr in n.attrs:
            if _ON.match(attr):
                add(n.attrs.get("id") and "#" + n.attrs["id"] or (n.attrs.get("name") or n.tag), attr[2:])
        if n.tag == "form":
            action = (n.attrs.get("action") or "").strip()
            if action:
                add("form:" + action, "submit")
    for script in page.find("script"):
        code = "".join(t for _, t in script.chunks)
        for m in _LISTENER.finditer(code):
            target = ("#" + m.group(1)) if m.group(1) else (m.group(2) or m.group(4) or "")
            event = m.group(5) or m.group(6) or (m.group(7) or "")[2:]
            if target and event:
                add(target, event)
        for m in _DELEGATED.finditer(code):
            add("document", m.group(1))
    titles = {"title": _norm(next((t.own_text() for t in page.find("title")), "")),
              "headings": [h for h in dict.fromkeys(_norm(n.text()) for n in page.find_any(("h1", "h2", "h3")) if n.text()) if h][:60]}
    return {"links": links[:300], "fields": fields[:200], "handlers": handlers[:300], "titles": titles,
            "counts": {"links": len(links), "fields": len(fields), "handlers": len(handlers), "headings": len(titles["headings"])}}


def compare(before: dict[str, Any], html: str) -> dict[str, Any]:
    """What the saved snapshot had that the page now lacks. ``ok`` only when nothing is missing."""
    now = snapshot(html)
    have_hrefs = {l["href"] for l in now["links"]}
    have_fields = {f["key"] for f in now["fields"]}
    have_handlers = {f"{h['target']}:{h['event']}" for h in now["handlers"]}
    missing = {
        "links": [l for l in before.get("links", []) if l["href"] not in have_hrefs],
        "fields": [f for f in before.get("fields", []) if f["key"] not in have_fields],
        "handlers": [h for h in before.get("handlers", []) if f"{h['target']}:{h['event']}" not in have_handlers],
        "titles": [],
    }
    bt = before.get("titles") or {}
    if bt.get("title") and now["titles"]["title"] != bt["title"] and not now["titles"]["title"]:
        missing["titles"].append({"kind": "title", "text": bt["title"]})
    have_heads = set(now["titles"]["headings"])
    missing["titles"].extend({"kind": "heading", "text": h} for h in bt.get("headings", []) if h not in have_heads)
    added = {"links": len(now["links"]) - len(before.get("links", [])), "fields": len(now["fields"]) - len(before.get("fields", [])),
             "handlers": len(now["handlers"]) - len(before.get("handlers", []))}
    total = sum(len(v) for v in missing.values())
    return {"ok": total == 0, "missing": {k: v[:40] for k, v in missing.items()}, "missing_count": {k: len(v) for k, v in missing.items()},
            "total_missing": total, "kept": {k: len(before.get(k, [])) - len(missing[k]) for k in ("links", "fields", "handlers")},
            "now": now["counts"], "delta": added}
