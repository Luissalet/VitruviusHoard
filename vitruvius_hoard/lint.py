"""Deterministic design checks over a probe() dict + raw HTML — no model.

``run_lint(probe, html) -> {"findings": [...], "score": float, "counts": {...}}``.
Each check is ``(probe: dict, html: str) -> list[Finding]``, registered in
``CHECKS``. Every check catches its own errors so one bad probe never sinks
the rest.
"""

from __future__ import annotations

import re
from typing import Any, Callable

Finding = dict[str, Any]
CheckFn = Callable[[dict, str], list[Finding]]

_SEVERITY_WEIGHT = {"info": 0.5, "warn": 1.5, "error": 3.0}

_RGB_RE = re.compile(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s]+([\d.]+))?\s*\)")


def _parse_rgb(value: str | None) -> tuple[int, int, int] | None:
    """Parses "rgb(r,g,b)"/"rgba(r,g,b,a)"; a fully transparent colour (a=0, e.g. an
    unset background) is treated as absent rather than as opaque black."""
    if not value:
        return None
    m = _RGB_RE.search(value)
    if not m:
        return None
    if m.group(4) is not None and float(m.group(4)) <= 0.01:
        return None
    return tuple(int(float(x)) for x in m.groups()[:3])  # type: ignore[return-value]


def _to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, c)) for c in rgb))


def _finding(check_id: str, area: str, severity: str, title: str, detail: str, evidence: Any = None,
             fix: str = "", rule_cite: str | None = None) -> Finding:
    f: Finding = {"check_id": check_id, "area": area, "severity": severity, "title": title, "detail": detail,
                 "evidence": evidence, "fix": fix}
    if rule_cite:
        f["rule_cite"] = rule_cite
    return f


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


def check_font_generic_only(probe: dict, html: str) -> list[Finding]:
    gd = probe.get("generic_defaults") or {}
    if gd.get("fonts_only_generic"):
        return [_finding("font.generic-only", "typography", "warn", "Only default system fonts",
                         "The page only uses Inter/Roboto/Arial/-apple-system, the default the model reaches for.",
                         gd, "Pick a distinctive heading font paired with a readable body font.")]
    return []


def check_font_too_many_families(probe: dict, html: str) -> list[Finding]:
    loaded = ((probe.get("fonts") or {}).get("loaded")) or []
    if len(loaded) > 4:
        return [_finding("font.too-many-families", "typography", "warn", "Too many font families",
                         f"{len(loaded)} font families loaded.", loaded,
                         "Keep to at most one heading font, one body font and one mono font.")]
    return []


def check_color_low_contrast(probe: dict, html: str) -> list[Finding]:
    from .tokens import contrast_ratio

    pairs = probe.get("contrast_pairs") or []
    worst = []
    for pair in pairs:
        fg = _parse_rgb(pair.get("color"))
        bg = _parse_rgb(pair.get("background"))
        if not fg or not bg:
            continue
        try:
            ratio = contrast_ratio(_to_hex(fg), _to_hex(bg))
        except Exception:  # noqa: BLE001
            continue
        size = float(pair.get("size") or 16)
        weight = int(str(pair.get("weight") or "400").replace("bold", "700").replace("normal", "400") or 400)
        large = size >= 24 or (size >= 18.66 and weight >= 700)
        threshold = 3.0 if large else 4.5
        if ratio < threshold:
            worst.append({"text": pair.get("text"), "ratio": round(ratio, 2), "required": threshold})
    if worst:
        worst.sort(key=lambda w: w["ratio"])
        return [_finding("color.low-contrast", "color", "error", "Low text contrast",
                         f"{len(worst)} text/background pair(s) below WCAG AA (4.5:1).", worst[:20],
                         "Increase contrast between text and its background to at least 4.5:1.")]
    return []


def _colors_flat(probe: dict) -> list[tuple[int, int, int]]:
    out = []
    for c in probe.get("colors") or []:
        for key in ("color", "background"):
            rgb = _parse_rgb(c.get(key))
            if rgb:
                out.append(rgb)
    return out


def _is_near_black(rgb):
    return max(rgb) < 30


def _is_acid_green(rgb):
    r, g, b = rgb
    return g > 200 and r < 100 and b < 100


def _is_cream(rgb):
    r, g, b = rgb
    # A warm off-white: clearly tinted (not plain white), red-leaning, not yellow.
    return r > 235 and g > 220 and 175 < b < 232 and 12 <= (r - b) < 70 and abs(r - g) < 25


def _is_terracotta(rgb):
    r, g, b = rgb
    return 150 <= r <= 215 and 55 <= g <= 115 and 35 <= b <= 95


def _is_grayscale(rgb):
    return (max(rgb) - min(rgb)) <= 8


def _is_indigo_blue(rgb):
    r, g, b = rgb
    return b > r and b > g and b > 120 and r < 140


def check_color_generic_ai_palette_1(probe: dict, html: str) -> list[Finding]:
    colors = _colors_flat(probe)
    if any(_is_near_black(c) for c in colors) and any(_is_acid_green(c) for c in colors):
        return [_finding("color.generic-ai-palette-1", "color", "warn", "Generic AI palette: near-black + acid green",
                         "Near-black text/background combined with an acid-green accent is a common model default.",
                         None, "Choose a palette derived from the brief's hue instead of a stock dark+neon combo.")]
    return []


def _backgrounds(probe: dict) -> list[tuple[int, int, int]]:
    out = []
    for c in probe.get("colors") or []:
        rgb = _parse_rgb(c.get("background"))
        if rgb:
            out.append(rgb)
    return out


def _serif_heading(probe: dict) -> bool:
    fam = (((probe.get("fonts") or {}).get("h1")) or "").lower()
    parts = [p.strip().strip("'\"") for p in fam.split(",")]
    return "serif" in parts or any(
        name in fam for name in ("playfair", "fraunces", "georgia", "garamond", "lora", "merriweather", "cormorant", "libre baskerville", "dm serif", "instrument serif"))


def check_color_generic_ai_palette_2(probe: dict, html: str) -> list[Finding]:
    colors = _colors_flat(probe)
    if any(_is_cream(c) for c in _backgrounds(probe)) and any(_is_terracotta(c) for c in colors) and _serif_heading(probe):
        return [_finding("color.generic-ai-palette-2", "color", "warn", "Generic AI palette: cream + terracotta + serif",
                         "Cream background with a terracotta accent is a common generic 'editorial' default.",
                         None, "Vary the palette; do not default to cream+terracotta unless the brief asks for it.")]
    return []


def check_color_generic_ai_palette_3(probe: dict, html: str) -> list[Finding]:
    colors = _colors_flat(probe)
    gray = [c for c in colors if _is_grayscale(c)]
    indigo = [c for c in colors if _is_indigo_blue(c)]
    non_gray = [c for c in colors if not _is_grayscale(c)]
    if len(gray) >= 3 and indigo and len(non_gray) <= 2:
        return [_finding("color.generic-ai-palette-3", "color", "warn", "Generic AI palette: gray + one indigo accent",
                         "Grayscale UI with a single indigo/blue accent is the default 'SaaS starter' look.",
                         None, "Use a palette generated from the brief's hue across the whole ramp, not just an accent.")]
    return []


def check_color_purple_blue_gradient(probe: dict, html: str) -> list[Finding]:
    gd = probe.get("generic_defaults") or {}
    if gd.get("purple_blue_gradient_buttons"):
        return [_finding("color.purple-blue-gradient", "color", "warn", "Purple-to-blue gradient buttons",
                         "Buttons use a purple-to-blue gradient, a very common generic default.", gd,
                         "Use a flat brand colour or a gradient derived from the generated ramp instead.")]
    return []


def check_layout_hero_three_cards(probe: dict, html: str) -> list[Finding]:
    card_count = len(re.findall(r'class="[^"]*\bcard\b', html, re.IGNORECASE))
    has_hero = bool(re.search(r'\bhero\b', html, re.IGNORECASE))
    if has_hero and card_count == 3:
        return [_finding("layout.hero-three-cards", "layout", "info", "Hero + exactly three cards",
                         "The page follows the generic 'hero section then three feature cards' shape.", None,
                         "Vary section counts and layout rhythm instead of the default hero+3-cards template.")]
    return []


def check_layout_no_max_width(probe: dict, html: str) -> list[Finding]:
    if "max-width" not in html and "max_width" not in html:
        return [_finding("layout.no-max-width", "layout", "warn", "No max-width constraint found",
                         "The document never sets a max-width, so text can stretch full width on large screens.", None,
                         "Constrain the main content column with a max-width (e.g. 72ch or a fixed px value).")]
    return []


def check_layout_horizontal_overflow(probe: dict, html: str) -> list[Finding]:
    wide = re.search(r'width:\s*(\d{4,})px', html)
    if wide and int(wide.group(1)) >= 1600 and "overflow-x" not in html:
        return [_finding("layout.horizontal-overflow", "layout", "error", "Possible horizontal overflow",
                         f"A fixed width of {wide.group(1)}px was found with no overflow-x handling.", wide.group(0),
                         "Use relative widths (%, vw, max-width) or add overflow-x handling.")]
    return []


def check_type_scale_flat(probe: dict, html: str) -> list[Finding]:
    sizes = set((probe.get("font_sizes")) or [])
    if len(sizes) > 0 and len(sizes) <= 2:
        return [_finding("type.scale-flat", "typography", "warn", "Flat type scale",
                         f"Only {len(sizes)} distinct font size(s) in use.", sorted(sizes),
                         "Use a proper type scale: distinct sizes for h1, h2, body and small text.")]
    return []


def check_type_line_length(probe: dict, html: str) -> list[Finding]:
    long_paragraphs = probe.get("long_paragraphs") or 0
    if long_paragraphs > 0:
        return [_finding("type.line-length", "typography", "warn", "Lines too long to read comfortably",
                         f"{long_paragraphs} paragraph(s) exceed ~90 characters per line.", long_paragraphs,
                         "Constrain paragraph width (max-width: 65-75ch) for readability.")]
    return []


def check_motion_no_reduced_motion(probe: dict, html: str) -> list[Finding]:
    if not probe.get("reduced_motion_css_present"):
        return [_finding("motion.no-reduced-motion", "motion", "warn", "No prefers-reduced-motion support",
                         "The page never checks prefers-reduced-motion.", None,
                         "Add an @media (prefers-reduced-motion: reduce) block that disables non-essential motion.")]
    return []


def check_motion_everything_animates(probe: dict, html: str) -> list[Finding]:
    count = probe.get("animations_count") or 0
    if count > 12:
        return [_finding("motion.everything-animates", "motion", "warn", "Too many concurrent animations",
                         f"{count} animations running on load.", count,
                         "Reduce simultaneous animations; stagger or trigger on interaction/scroll instead.")]
    return []


def check_motion_long_durations(probe: dict, html: str) -> list[Finding]:
    count = probe.get("long_transition_count") or 0
    if count > 0:
        return [_finding("motion.long-durations", "motion", "info", "Long transition durations",
                         f"{count} element(s) have transitions longer than 800ms.", count,
                         "Keep UI transitions under ~300ms; reserve longer durations for large, rare motions.")]
    return []


def check_motion_linear_easing(probe: dict, html: str) -> list[Finding]:
    count = probe.get("linear_easing_count") or 0
    if count > 0:
        return [_finding("motion.linear-easing", "motion", "info", "Linear easing in use",
                         f"{count} element(s) use linear easing.", count,
                         "Use an eased curve (standard/emphasized/decelerate) instead of linear for UI motion.")]
    return []


def check_a11y_missing_alt(probe: dict, html: str) -> list[Finding]:
    n = probe.get("images_without_alt") or 0
    if n > 0:
        return [_finding("a11y.missing-alt", "a11y", "error", "Images missing alt text",
                         f"{n} image(s) have no alt attribute.", n,
                         "Add descriptive alt text to every meaningful image (alt=\"\" for decorative ones).")]
    return []


def check_a11y_small_targets(probe: dict, html: str) -> list[Finding]:
    n = probe.get("small_tap_targets") or 0
    if n > 0:
        return [_finding("a11y.small-targets", "a11y", "warn", "Tap targets smaller than 44px",
                         f"{n} button(s)/link(s) are smaller than 44x44px.", n,
                         "Make interactive targets at least 44x44px, especially on mobile.")]
    return []


def check_a11y_heading_order(probe: dict, html: str) -> list[Finding]:
    order = probe.get("heading_order") or []
    issues = []
    if order.count(1) > 1:
        issues.append("more than one <h1>")
    for a, b in zip(order, order[1:]):
        if b - a > 1:
            issues.append(f"skip from h{a} to h{b}")
    if issues:
        return [_finding("a11y.heading-order", "a11y", "warn", "Heading order issues",
                         "; ".join(issues), order, "Use one <h1> and do not skip heading levels.")]
    return []


def check_a11y_no_lang(probe: dict, html: str) -> list[Finding]:
    if not probe.get("lang"):
        return [_finding("a11y.no-lang", "a11y", "warn", "Document language not set",
                         "<html> has no lang attribute.", None, 'Add lang="en" (or the right code) to <html>.')]
    return []


def check_a11y_no_focus_visible(probe: dict, html: str) -> list[Finding]:
    has_outline_none = bool(re.search(r'outline\s*:\s*none', html, re.IGNORECASE))
    has_focus_visible = ":focus-visible" in html
    if has_outline_none and not has_focus_visible:
        return [_finding("a11y.no-focus-visible", "a11y", "error", "Focus outline removed without replacement",
                         "outline: none is used without a :focus-visible style.", None,
                         "Keep or replace the focus ring with a visible :focus-visible style.")]
    return []


def check_content_lorem_ipsum(probe: dict, html: str) -> list[Finding]:
    if re.search(r'lorem ipsum', html, re.IGNORECASE):
        return [_finding("content.lorem-ipsum", "content", "error", "Lorem ipsum placeholder text",
                         "The page still contains Lorem ipsum text.", None, "Replace with real or realistic copy.")]
    return []


def check_content_emoji_icons(probe: dict, html: str) -> list[Finding]:
    gd = probe.get("generic_defaults") or {}
    if gd.get("emoji_icons"):
        return [_finding("content.emoji-icons", "content", "info", "Emoji used as icons",
                         "Emoji characters are used in place of a real icon set.", None,
                         "Use a proper icon set (SVG) instead of emoji for UI icons.")]
    return []


def check_content_placeholder_copy(probe: dict, html: str) -> list[Finding]:
    if re.search(r'your company|placeholder text|lorem\b', html, re.IGNORECASE):
        return [_finding("content.placeholder-copy", "content", "warn", "Placeholder copy left in",
                         "Generic placeholder copy (e.g. 'Your Company') was found.", None,
                         "Replace placeholder copy with content specific to the brief.")]
    return []


def check_perf_dom_size(probe: dict, html: str) -> list[Finding]:
    n = probe.get("dom_size") or 0
    if n > 1500:
        return [_finding("perf.dom-size", "perf", "warn", "Large DOM",
                         f"{n} DOM nodes.", n, "Simplify markup; large DOMs slow style/layout and CPU-bound devices.")]
    return []


def check_perf_images_unsized(probe: dict, html: str) -> list[Finding]:
    imgs = re.findall(r'<img\b[^>]*>', html, re.IGNORECASE)
    unsized = [i for i in imgs if not (re.search(r'\bwidth=', i, re.IGNORECASE) and re.search(r'\bheight=', i, re.IGNORECASE))]
    if unsized:
        return [_finding("perf.images-unsized", "perf", "warn", "Images without explicit dimensions",
                         f"{len(unsized)} <img> without width/height attributes.", len(unsized),
                         "Set width/height (or aspect-ratio) on images to avoid layout shift.")]
    return []


def check_perf_large_transfer(probe: dict, html: str) -> list[Finding]:
    total = probe.get("total_transfer_bytes")
    if isinstance(total, (int, float)) and total > 3_000_000:
        return [_finding("perf.large-transfer", "perf", "warn", "Large page weight",
                         f"~{int(total / 1_000_000)} MB transferred.", total,
                         "Compress images and defer non-critical scripts to cut page weight.")]
    return []


def check_viewport_missing(probe: dict, html: str) -> list[Finding]:
    if not probe.get("viewport_meta"):
        return [_finding("viewport.missing", "layout", "error", "Missing viewport meta tag",
                         "No <meta name=\"viewport\"> found.", None,
                         'Add <meta name="viewport" content="width=device-width, initial-scale=1">.')]
    return []


def check_dark_no_scheme(probe: dict, html: str) -> list[Finding]:
    if not probe.get("color_scheme_present"):
        return [_finding("dark.no-scheme", "color", "info", "No color-scheme declared",
                         "Neither color-scheme nor prefers-color-scheme is used.", None,
                         "Declare color-scheme and support prefers-color-scheme for light/dark.")]
    return []


CHECKS: list[CheckFn] = [
    check_font_generic_only,
    check_font_too_many_families,
    check_color_low_contrast,
    check_color_generic_ai_palette_1,
    check_color_generic_ai_palette_2,
    check_color_generic_ai_palette_3,
    check_color_purple_blue_gradient,
    check_layout_hero_three_cards,
    check_layout_no_max_width,
    check_layout_horizontal_overflow,
    check_type_scale_flat,
    check_type_line_length,
    check_motion_no_reduced_motion,
    check_motion_everything_animates,
    check_motion_long_durations,
    check_motion_linear_easing,
    check_a11y_missing_alt,
    check_a11y_small_targets,
    check_a11y_heading_order,
    check_a11y_no_lang,
    check_a11y_no_focus_visible,
    check_content_lorem_ipsum,
    check_content_emoji_icons,
    check_content_placeholder_copy,
    check_perf_dom_size,
    check_perf_images_unsized,
    check_perf_large_transfer,
    check_viewport_missing,
    check_dark_no_scheme,
]

CHECK_IDS = [
    "font.generic-only", "font.too-many-families", "color.low-contrast", "color.generic-ai-palette-1",
    "color.generic-ai-palette-2", "color.generic-ai-palette-3", "color.purple-blue-gradient",
    "layout.hero-three-cards", "layout.no-max-width", "layout.horizontal-overflow", "type.scale-flat",
    "type.line-length", "motion.no-reduced-motion", "motion.everything-animates", "motion.long-durations",
    "motion.linear-easing", "a11y.missing-alt", "a11y.small-targets", "a11y.heading-order", "a11y.no-lang",
    "a11y.no-focus-visible", "content.lorem-ipsum", "content.emoji-icons", "content.placeholder-copy",
    "perf.dom-size", "perf.images-unsized", "perf.large-transfer", "viewport.missing", "dark.no-scheme",
]


def run_lint(probe: dict, html: str) -> dict[str, Any]:
    probe = probe or {}
    html = html or ""
    findings: list[Finding] = []
    for check in CHECKS:
        try:
            findings.extend(check(probe, html) or [])
        except Exception as error:  # noqa: BLE001 — one bad check must not sink the rest
            findings.append(_finding(getattr(check, "__name__", "unknown"), "internal", "info",
                                     "Check failed", str(error)))
    counts: dict[str, int] = {"info": 0, "warn": 0, "error": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    penalty = sum(_SEVERITY_WEIGHT.get(f["severity"], 1.0) for f in findings)
    score = max(0.0, 10.0 - penalty)
    return {"findings": findings, "score": round(score, 2), "counts": counts}
