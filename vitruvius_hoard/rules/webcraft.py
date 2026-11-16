"""Web-craft pack: older patterns with a native replacement, flat page surfaces and the generic dashboard. HTML and CSS text only; original code.

The legacy check reuses the rules of ``vitruvius_hoard.webguide.legacy``; every finding cites the guide that holds the native alternative.
The dashboard checks apply only to a page that looks like a dashboard (sidebar or navigation plus several metric cards, or the word in its title).
"""
from __future__ import annotations

import re

from .base import F, short
from .pagesrc import Page, px
from .static_a import rule

_STAT = re.compile(r"(?:^|[\s_-])(stat|stats|kpi|metric|metrics|tile|widget|card)(?:$|[\s_-])", re.I)


def _cards(page: Page) -> list:
    return [n for n in page.nodes if n.tag in {"div", "section", "article", "li"} and _STAT.search(n.attrs.get("class", "") or "")]


def is_dashboard(page: Page) -> bool:
    title = " ".join(n.text() for n in page.find("title")).lower()
    classes = " ".join(n.attrs.get("class", "") for n in page.nodes[:40]).lower()
    named = bool(re.search(r"dashboard|panel de control|cuadro de mando|analytics|admin", title + " " + classes))
    has_nav = any(n.tag in {"aside", "nav"} for n in page.nodes)
    return (named and len(_cards(page)) >= 2) or (has_nav and len(_cards(page)) >= 3)


@rule("webcraft/legacy-pattern")
def legacy_pattern(page: Page, probe):
    from ..webguide import legacy
    text = page.html + "\n" + str((probe or {}).get("css_text") or "")
    out = []
    for item in legacy.scan_text(text, "page", "html"):
        lines = ", ".join(str(loc["line"]) for loc in item["locations"][:4])
        out.append(F("webcraft/legacy-pattern",
                     f"{item['count']} use(s) of an older pattern ({item['rule'].replace('-', ' ')}; line {lines}). {item['native']} Keep it only if: {item['keep_when']}",
                     {"rule": item["rule"], "guide": item["guide"], "cite": item["cite"], "count": item["count"], "lines": [loc["line"] for loc in item["locations"]]},
                     f"{item['native']} Read the guide with web_guide_read ('{item['guide']}'). {item['cite']}",
                     f"Older pattern: {item['rule'].replace('-', ' ')}"))
    return out


_MATERIAL_TAGS = {"img", "video", "canvas", "picture", "svg", "iframe"}


@rule("webcraft/flat-hero-surface")
def flat_hero_surface(page: Page, probe):
    if len(page.text) < 200 or not any(n.tag in {"h1", "h2"} for n in page.nodes) or is_dashboard(page):
        return []
    if any(n.tag in _MATERIAL_TAGS for n in page.nodes):
        return []
    for _, prop, val in page.all_declarations():
        v = val.lower()
        if prop in {"background-image", "mask", "-webkit-mask", "filter", "backdrop-filter", "-webkit-backdrop-filter"} and v not in {"none", ""}:
            return []
        if prop == "background" and ("gradient" in v or "url(" in v):
            return []
        if prop in {"box-shadow"} and v not in {"none", ""}:
            return []
    return [F("webcraft/flat-hero-surface", "Every surface on the page is a flat colour: no image, gradient, texture, shadow or filter anywhere.",
              None, "Give the top of the page a material (craft_search: grain, thermal gradient, blueprint grid, contour lines) or a real photograph.")]


def _sizes(page: Page) -> list[float]:
    out = []
    for _, prop, val in page.all_declarations():
        if prop == "font-size":
            n = px(val)
            if n:
                out.append(round(n, 1))
    return out


@rule("webcraft/dashboard-type-scale")
def dashboard_type_scale(page: Page, probe):
    if not is_dashboard(page):
        return []
    sizes = sorted(set(_sizes(page)))
    near = [(a, b) for a, b in zip(sizes, sizes[1:]) if b - a <= 2]
    if len(sizes) > 7 or len(near) >= 3:
        return [F("webcraft/dashboard-type-scale", f"{len(sizes)} distinct font sizes ({', '.join(f'{s:g}' for s in sizes[:12])} px), {len(near)} pair(s) within 2 px: no type scale was chosen.",
                  {"sizes": sizes, "near_pairs": near[:6]})]
    return []


@rule("webcraft/dashboard-card-styles")
def dashboard_card_styles(page: Page, probe):
    if not is_dashboard(page):
        return []
    combos: dict[tuple, list[str]] = {}
    for r in page.rules:
        if not re.search(r"card|tile|stat|kpi|metric|widget|panel", r.selector, re.I):
            continue
        d = r.decls
        look = (d.get("border-radius", ""), d.get("border", d.get("border-color", "")), d.get("box-shadow", ""))
        if any(look):
            combos.setdefault(look, []).append(r.selector)
    if len(combos) > 2:
        return [F("webcraft/dashboard-card-styles", f"{len(combos)} different card looks (radius, border, shadow): " + "; ".join(short(" ".join(v), 40) for v in list(combos.values())[:4]) + ".",
                  [{"selectors": v, "look": list(k)} for k, v in list(combos.items())[:5]])]
    return []


@rule("webcraft/dashboard-welcome-banner")
def dashboard_welcome(page: Page, probe):
    if not is_dashboard(page):
        return []
    pattern = re.compile(r"welcome back|good (?:morning|afternoon|evening)|bienvenid[oa]s? de nuevo|buenos d[ií]as|buenas (?:tardes|noches)|hola de nuevo", re.I)
    hits = [n.text() for n in page.nodes if n.tag in {"h1", "h2", "h3", "p"} and pattern.search(n.text()) and len(n.text()) < 80]
    if hits:
        return [F("webcraft/dashboard-welcome-banner", f"A greeting leads the page: «{short(hits[0], 60)}».", hits[:3])]
    return []


@rule("webcraft/dashboard-actions-below")
def dashboard_actions(page: Page, probe):
    if not is_dashboard(page):
        return []
    buttons = [n for n in page.nodes if n.tag == "button" or (n.tag == "a" and re.search(r"\bbtn|button\b", n.attrs.get("class", ""), re.I))]
    cards = _cards(page)
    if len(buttons) < 1 or not cards:
        return []
    first_card = min(n.idx for n in cards)
    if min(b.idx for b in buttons) > first_card:
        return [F("webcraft/dashboard-actions-below", "The first button comes after the first card: the page's actions are below its content.", None)]
    return []


@rule("webcraft/dashboard-command-palette")
def dashboard_palette(page: Page, probe):
    if not is_dashboard(page):
        return []
    links = [n for n in page.nodes if n.tag == "a" and any(p.tag in {"nav", "aside"} for p in _parents(n))]
    if len(links) < 6:
        return []
    source = page.html.lower()
    if any(token in source for token in ("<dialog", "cmdk", "command-palette", "aria-keyshortcuts", "ctrl+k", "ctrl k", "⌘k", "⌘ k", "metakey", "role=\"combobox\"", "role='combobox'")):
        return []
    return [F("webcraft/dashboard-command-palette", f"{len(links)} navigation links and no command palette or search shortcut.", None)]


def _parents(node):
    while node.parent is not None:
        node = node.parent
        yield node
