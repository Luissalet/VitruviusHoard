"""Mine "Do/Don't/Avoid/Never/Always" bullet lines from AGENTS.md-style docs into `rules`."""

from __future__ import annotations

import re
from typing import Any

_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")

_SEVERITY_KEYWORDS = [
    ("never", "error"), ("don't", "warn"), ("do not", "warn"), ("avoid", "warn"),
    ("always", "info"), ("prefer", "info"), ("do", "info"),
]

_AREA_KEYWORDS = {
    "typography": ["font", "type", "typograph", "line-height", "line height", "readable", "heading", "letter-spacing", "tracking", "serif", "weight"],
    "color": ["color", "colour", "contrast", "palette", "gradient"],
    "layout": ["layout", "grid", "max-width", "responsive", "viewport", "breakpoint", "overflow", "spacing", "whitespace", "white space", "margin", "padding", "hierarchy", "shadow", "border", "radius", "align", "section", "hero", "card"],
    "motion": ["animation", "motion", "transition", "easing", "reduced motion", "duration"],
    "a11y": ["accessib", "a11y", "alt text", "focus", "aria", "tap target", "wcag", "screen reader"],
    "forms": ["form", "input", "label", "validation", "placeholder", "button", "checkbox", "select", "toggle"],
    "performance": ["performance", "lazy", "bundle", "cls", "lcp", "load time", "image size"],
    "content": ["copy", "content", "lorem", "placeholder text", "microcopy", "icon", "emoji", "headline", "tagline", "wording", "word"],
}

_CHECK_ID_HINTS = [
    ("lorem ipsum", "content.lorem-ipsum"),
    ("reduced motion", "motion.no-reduced-motion"),
    ("linear easing", "motion.linear-easing"),
    ("focus", "a11y.no-focus-visible"),
    ("alt text", "a11y.missing-alt"),
    ("tap target", "a11y.small-targets"),
    ("44px", "a11y.small-targets"),
    ("heading order", "a11y.heading-order"),
    ("viewport", "viewport.missing"),
    ("max-width", "layout.no-max-width"),
    ("gradient", "color.purple-blue-gradient"),
    ("contrast", "color.low-contrast"),
    ("emoji", "content.emoji-icons"),
    ("color-scheme", "dark.no-scheme"),
    ("dom size", "perf.dom-size"),
    ("image", "perf.images-unsized"),
]


def _guess_area(text: str) -> str | None:
    """The design area a line talks about, or None when it is not about design at all."""
    low = text.lower()
    for area, keywords in _AREA_KEYWORDS.items():
        if any(k in low for k in keywords):
            return area
    return None


_STRONG_RE = re.compile(r"^(?:\*\*)?(?:never|always|avoid|don't|do not|do:|don't:|prefer|use|no )", re.IGNORECASE)
_NOISE_RE = re.compile(r"(issue #\d+|--[a-z-]+|\bnpm\b|\bnpx\b|\bcli\b|\bpull request|\bPR\b|\bcommit|\brelease|changelog|\bv\d+\.\d+|\[[A-Z][a-z]+ name\]|\[exact value\]|TODO)")


def _guess_severity(text: str) -> str:
    low = text.lower()
    for kw, sev in _SEVERITY_KEYWORDS:
        if low.startswith(kw) or f" {kw} " in low:
            return sev
    return "info"


def _guess_check_id(text: str) -> str | None:
    low = text.lower()
    for hint, check_id in _CHECK_ID_HINTS:
        if hint in low:
            return check_id
    return None


def mine_rules(text: str, source_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        m = _BULLET_RE.match(line)
        if not m:
            continue
        content = m.group(1).strip()
        if len(content) < 8 or len(content) > 600:
            continue
        low = content.lower()
        if not any(kw in low for kw, _ in _SEVERITY_KEYWORDS):
            continue
        if len(content) < 18 or _NOISE_RE.search(content) or content.count("`") > 4:
            continue
        area = _guess_area(content)
        if area is None:
            continue
        # A design rule reads as an instruction: it starts with the verb or carries a
        # strong "never/always/avoid" marker; plain sentences that merely mention
        # "do" are not rules.
        stripped = content.lstrip("*_ ")
        if not (_STRONG_RE.match(stripped) or re.search(r"\b(never|always|avoid|don't|do not)\b", low)):
            continue
        title = re.sub(r"[*_`]", "", content.split(".")[0])[:120].strip().rstrip(":")
        out.append({
            "source_id": source_id,
            "area": area,
            "severity": _guess_severity(content),
            "title": title or content[:120],
            "text": content,
            "check_id": _guess_check_id(content),
        })
    return out
