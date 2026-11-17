"""Interaction pack: keyboard, focus and ARIA. The static rules read the HTML text; the three browser rules read what ``keyboard.walk`` measured
in a real browser (a Tab walk through the page, a focus-ring comparison and a search for controls only a pointer can use).

Original implementations. The behaviours checked (everything reachable and operable from the keyboard, a visible focus indicator, a name for
every control, complete widget roles) are the common baseline of the WAI-ARIA authoring practices; thresholds were chosen here and checked
against fixtures in the tests. A browser rule returns nothing when the capture has no keyboard measurement, never a guess.
"""
from __future__ import annotations

import re

from .base import F, short
from .pagesrc import Node, Page
from .static_a import CHECKS, rule

NATIVE_INTERACTIVE = {"a", "button", "input", "select", "textarea", "summary", "details", "label", "option", "audio", "video"}
INTERACTIVE_ROLES = {"button", "link", "checkbox", "switch", "radio", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "option", "slider", "spinbutton",
                     "textbox", "searchbox", "combobox", "listbox", "treeitem", "gridcell", "scrollbar"}
NAMED_ROLES = INTERACTIVE_ROLES - {"option", "gridcell", "listbox", "scrollbar"}
_ARIA_REFS = ("aria-labelledby", "aria-describedby", "aria-controls", "aria-owns", "aria-activedescendant", "aria-errormessage", "aria-details", "aria-flowto")
_HIDDEN = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)


def _hidden(node: Node) -> bool:
    for n in [node, *node.ancestors()]:
        a = n.attrs
        if "hidden" in a or a.get("aria-hidden") == "true" or _HIDDEN.search(a.get("style", "")) or (n is node and a.get("type") == "hidden"):
            return True
    return False


def _role(node: Node) -> str:
    return (node.attrs.get("role") or "").split(" ")[0].lower()


def _labels(page: Page) -> dict[str, list[Node]]:
    out: dict[str, list[Node]] = {}
    for n in page.find("label"):
        target = n.attrs.get("for")
        if target:
            out.setdefault(target, []).append(n)
    return out


def _has_name(node: Node, page: Page, labels: dict[str, list[Node]]) -> bool:
    a = node.attrs
    if (a.get("aria-label") or "").strip() or (a.get("title") or "").strip():
        return True
    ref = (a.get("aria-labelledby") or "").split()
    if ref and any(n.id in ref and n.text().strip() for n in page.nodes):
        return True
    if node.text().strip():
        return True
    if any((d.attrs.get("alt") or "").strip() or (d.attrs.get("aria-label") or "").strip() for d in node.descendants() if d.tag in {"img", "svg", "span", "i"}):
        return True
    if node.tag == "input" and (a.get("type") or "text").lower() in {"submit", "button", "reset"}:
        return bool((a.get("value") or "").strip()) or (a.get("type") or "").lower() == "submit"
    if node.tag == "input" and (a.get("type") or "text").lower() == "image":
        return bool((a.get("alt") or "").strip())
    if node.id and labels.get(node.id) and any(label.text().strip() for label in labels[node.id]):
        return True
    if any(p.tag == "label" and p.text().strip() for p in node.ancestors()):
        return True
    return False  # a placeholder is not a name


@rule("interaction/click-on-static-element")
def click_on_static(page: Page, probe):
    out = []
    for n in page.nodes:
        if "onclick" not in n.attrs or n.tag in NATIVE_INTERACTIVE or _hidden(n):
            continue
        if _role(n) in INTERACTIVE_ROLES and n.attrs.get("tabindex", "").lstrip("-").isdigit() and n.attrs["tabindex"] != "-1":
            continue
        if any(p.tag in {"a", "button", "label"} for p in n.ancestors()):
            continue
        out.append(n)
    if not out:
        return []
    return [F("interaction/click-on-static-element",
              f"{len(out)} element(s) react to a click but are not controls: " + ", ".join(short(n.label(), 40) for n in out[:4]) + ".",
              [{"element": n.label(), "text": short(n.text(), 40)} for n in out[:6]],
              "Use a <button> (or an <a href>) so the keyboard, focus and the role come with it; if it must stay a custom element give it role, tabindex=\"0\" and Enter and Space handlers.")]


@rule("interaction/unnamed-control")
def unnamed_control(page: Page, probe):
    labels = _labels(page)
    out = []
    for n in page.nodes:
        if _hidden(n):
            continue
        native = n.tag in {"button", "select", "textarea", "summary"} or (n.tag == "a" and "href" in n.attrs) or (
            n.tag == "input" and (n.attrs.get("type") or "text").lower() not in {"hidden"})
        custom = _role(n) in NAMED_ROLES
        if not (native or custom):
            continue
        if not _has_name(n, page, labels):
            out.append(n)
    if not out:
        return []
    return [F("interaction/unnamed-control", f"{len(out)} control(s) have no accessible name: " + ", ".join(short(n.label(), 40) for n in out[:5]) + ".",
              [{"element": n.label(), "type": n.attrs.get("type", ""), "role": _role(n)} for n in out[:8]],
              "Give each one visible text, a <label for>, aria-label or aria-labelledby. An icon-only button needs aria-label; a placeholder is not a name.")]


@rule("interaction/positive-tabindex")
def positive_tabindex(page: Page, probe):
    bad = [n for n in page.nodes if re.fullmatch(r"[1-9]\d*", (n.attrs.get("tabindex") or "").strip())]
    if not bad:
        return []
    return [F("interaction/positive-tabindex", f"{len(bad)} element(s) use a tabindex above 0: " + ", ".join(short(n.label(), 40) for n in bad[:4]) + ".",
              [{"element": n.label(), "tabindex": n.attrs["tabindex"]} for n in bad[:6]],
              "Use tabindex=\"0\" or none and order the elements in the source the way the tab order should go.")]


@rule("interaction/dangling-aria-reference")
def dangling_aria(page: Page, probe):
    ids = {n.id for n in page.nodes if n.id}
    out = []
    for n in page.nodes:
        for attr in _ARIA_REFS:
            for ref in (n.attrs.get(attr) or "").split():
                if ref not in ids:
                    out.append({"element": n.label(), "attribute": attr, "missing_id": ref})
    for n in page.find("label"):
        target = n.attrs.get("for")
        if target and target not in ids:
            out.append({"element": n.label(), "attribute": "for", "missing_id": target})
    if not out:
        return []
    return [F("interaction/dangling-aria-reference", f"{len(out)} reference(s) point to an id that is not on the page: " + ", ".join(f"{o['attribute']}={o['missing_id']}" for o in out[:4]) + ".",
              out[:8], "Point it to an existing id, or remove the attribute: a broken reference gives the control no name or relation.")]


_WIDGETS = [
    ("dialog", lambda n: not ((n.attrs.get("aria-label") or "").strip() or (n.attrs.get("aria-labelledby") or "").strip()), "has no aria-label or aria-labelledby"),
    ("alertdialog", lambda n: not ((n.attrs.get("aria-label") or "").strip() or (n.attrs.get("aria-labelledby") or "").strip()), "has no aria-label or aria-labelledby"),
    ("tab", lambda n: "aria-selected" not in n.attrs, "has no aria-selected"),
    ("switch", lambda n: "aria-checked" not in n.attrs and n.tag != "input", "has no aria-checked"),
    ("checkbox", lambda n: "aria-checked" not in n.attrs and n.tag != "input", "has no aria-checked"),
    ("radio", lambda n: "aria-checked" not in n.attrs and n.tag != "input", "has no aria-checked"),
    ("slider", lambda n: "aria-valuenow" not in n.attrs and n.tag != "input", "has no aria-valuenow"),
    ("progressbar", lambda n: "aria-valuenow" not in n.attrs and n.tag != "progress" and "aria-label" not in n.attrs and "aria-labelledby" not in n.attrs, "has no aria-valuenow or name"),
    ("combobox", lambda n: "aria-expanded" not in n.attrs and n.tag not in {"input", "select"}, "has no aria-expanded"),
]


@rule("interaction/incomplete-aria-widget")
def incomplete_widget(page: Page, probe):
    out = []
    for n in page.nodes:
        role = _role(n)
        for wanted, missing, why in _WIDGETS:
            if role == wanted and missing(n) and not _hidden(n):
                out.append({"element": n.label(), "role": role, "problem": why})
    for n in page.nodes:
        if _role(n) == "tablist" and not any(_role(d) == "tab" for d in n.descendants()):
            out.append({"element": n.label(), "role": "tablist", "problem": "has no role=tab inside"})
        if _role(n) == "tab" and not any(_role(p) == "tablist" for p in n.ancestors()):
            out.append({"element": n.label(), "role": "tab", "problem": "is not inside role=tablist"})
    if not out:
        return []
    return [F("interaction/incomplete-aria-widget", f"{len(out)} ARIA widget(s) are missing what their role requires: " + "; ".join(f"{o['role']} {o['problem']}" for o in out[:4]) + ".",
              out[:8], "Complete the role's required attributes, or use the native element (<dialog>, <input type=checkbox>, <input type=range>, <progress>) that carries them.")]


@rule("interaction/duplicate-id")
def duplicate_id(page: Page, probe):
    seen: dict[str, int] = {}
    for n in page.nodes:
        if n.id:
            seen[n.id] = seen.get(n.id, 0) + 1
    dup = {k: v for k, v in seen.items() if v > 1}
    if not dup:
        return []
    return [F("interaction/duplicate-id", f"{len(dup)} id(s) repeat: " + ", ".join(f"#{k} x{v}" for k, v in list(dup.items())[:5]) + ".",
              [{"id": k, "count": v} for k, v in dup.items()][:8],
              "Make every id unique: labels and ARIA references resolve to the first match only.")]


@rule("interaction/link-without-destination")
def link_without_destination(page: Page, probe):
    out = []
    for n in page.find("a"):
        href = (n.attrs.get("href") or "").strip().lower()
        fake = ("href" not in n.attrs and "onclick" in n.attrs) or href.startswith("javascript:") or (href == "#" and "onclick" in n.attrs)
        if fake and _role(n) != "button" and not _hidden(n):
            out.append(n)
    if not out:
        return []
    return [F("interaction/link-without-destination", f"{len(out)} link(s) go nowhere and act as buttons: " + ", ".join(short(n.label() + ' "' + n.text() + '"', 40) for n in out[:4]) + ".",
              [{"element": n.label(), "href": n.attrs.get("href", None)} for n in out[:6]],
              "Use a <button type=\"button\"> for an action; keep <a href> for navigation.")]


# ── browser-measured rules (probe["keyboard"] from vitruvius_hoard.keyboard.walk) ───────────────

def _keyboard(probe) -> dict | None:
    data = (probe or {}).get("keyboard")
    return data if isinstance(data, dict) and not data.get("error") else None


def _browser(rule_id: str):
    def deco(fn):
        def run(probe, html):
            data = _keyboard(probe)
            return (fn(data) or []) if data else []
        run.__name__ = fn.__name__
        CHECKS[rule_id] = run
        return run
    return deco


@_browser("interaction/pointer-only-control")
def pointer_only(data):
    items = data.get("pointer_only") or []
    if not items:
        return []
    return [F("interaction/pointer-only-control", f"{len(items)} element(s) look clickable (pointer cursor) but the keyboard cannot reach them: "
              + ", ".join(short(i.get("label", ""), 40) for i in items[:4]) + ".", items[:8],
              "Make each a real <button> or <a href>, or give it role, tabindex=\"0\" and Enter/Space handlers.")]


@_browser("interaction/focus-ring-missing")
def focus_ring_missing(data):
    stops = [s for s in (data.get("stops") or []) if s.get("ring") is False and not s.get("offscreen")]
    if not stops:
        return []
    return [F("interaction/focus-ring-missing", f"{len(stops)} of {len(data.get('stops') or [])} tab stop(s) show no change when focused: "
              + ", ".join(short(s.get("label", ""), 40) for s in stops[:4]) + ".",
              [{"element": s.get("label"), "name": s.get("name")} for s in stops[:8]],
              "Add a :focus-visible style (outline 2-3 px with offset, or a ring that has 3:1 contrast against the background) instead of outline:none.")]


@_browser("interaction/keyboard-unreachable")
def keyboard_unreachable(data):
    if not data.get("complete"):
        return []
    items = data.get("unreached") or []
    if not items:
        return []
    return [F("interaction/keyboard-unreachable", f"{len(items)} visible control(s) were never reached by Tab: " + ", ".join(short(i.get("label", ""), 40) for i in items[:4]) + ".",
              items[:8], "Remove tabindex=\"-1\" from controls that must be operable, or give the same function to a control that is in the tab order.")]
