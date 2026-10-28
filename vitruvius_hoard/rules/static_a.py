"""Static rules, part one: colour, effects, motion and imagery. They read the page's HTML and CSS text only.

Original implementations. The ideas follow the generic-interface tells catalogued by the Apache-2.0 impeccable detector
and the MIT hallmark gate list (see NOTICE); thresholds were chosen here and checked against fixtures in the tests.
"""

from __future__ import annotations

import re
from typing import Callable

from .base import F, gradients_in, shadow_layers, short, uniq
from .pagesrc import (Page, colors_in, has_source, hsl_of, is_chromatic, page_of, parse_color, parse_decls, prose, px,
                      spread)

CHECKS: dict[str, Callable] = {}


def rule(rule_id: str):
    def deco(fn):
        def run(probe, html):
            if not has_source(probe, html):
                return []
            return fn(page_of(probe, html), probe) or []
        run.__name__ = fn.__name__
        CHECKS[rule_id] = run
        return run
    return deco


def page_background(page: Page):
    """The colour painted behind the page: body / html / :root background, a token it points at, or a wrapper."""
    for sel in ("body", "html", ":root", "main", ".page", ".app", "#app", "#root", ".wrapper"):
        for r in page.rules:
            if r.selector.strip().lower() == sel and not (r.media and "prefers-color-scheme" in r.media):
                v = r.decls.get("background-color") or r.decls.get("background")
                if v:
                    v = page.resolve(v)
                    if "gradient" in v:
                        continue
                    cols = colors_in(v)
                    if cols and cols[0][3] > 0.5:
                        return cols[0]
    for n in page.find("body")[:1]:
        v = parse_decls(n.attrs.get("style", ""))
        for prop, val in v:
            if prop in ("background", "background-color"):
                cols = colors_in(page.resolve(val))
                if cols:
                    return cols[0]
    return None


def is_dark_page(page: Page) -> bool:
    bg = page_background(page)
    return bool(bg and hsl_of(bg)[2] < 0.25)


def _class_blob(page: Page) -> list[tuple[str, str]]:
    return [(n.label(), n.attrs["class"]) for n in page.nodes if n.attrs.get("class")]


# ---------------------------------------------------------------------------
# colour
# ---------------------------------------------------------------------------

@rule("slop/gradient-text")
def gradient_text(page: Page, probe):
    hits = []
    for r in page.rules:
        d = r.decls
        clip = (d.get("background-clip", "") + " " + d.get("-webkit-background-clip", "")).lower()
        bg = d.get("background", "") + d.get("background-image", "")
        if "text" in clip and "gradient" in bg.lower():
            hits.append(r.selector)
    for n in page.nodes:
        st = n.attrs.get("style", "")
        if st and re.search(r"background-clip\s*:\s*text", st, re.I) and "gradient" in st.lower():
            hits.append("inline:" + n.label())
        cls = n.attrs.get("class", "")
        if "bg-clip-text" in cls and re.search(r"bg-gradient|bg-linear|\bfrom-|\bvia-|\bto-", cls):
            hits.append(n.label())
    # a class that only sets the gradient and another that clips it, on the same element
    for n in page.nodes:
        if n.tag in ("h1", "h2", "h3", "span", "p", "strong", "em", "a") and n.attrs.get("class"):
            d = page.declared(n)
            clip = (d.get("background-clip", "") + d.get("-webkit-background-clip", "")).lower()
            if "text" in clip and "gradient" in (d.get("background", "") + d.get("background-image", "")).lower():
                hits.append(n.label())
    hits = uniq(hits)
    if hits:
        return [F("slop/gradient-text", f"{len(hits)} element(s) fill their text with a gradient.", hits[:8])]


_PURPLE = (258, 320)


def _purple_stop(c) -> bool:
    h, s, l = hsl_of(c)
    return c[3] >= 0.3 and s >= 0.3 and 0.15 <= l <= 0.85 and _PURPLE[0] <= h <= _PURPLE[1]


@rule("slop/ai-color-palette")
def ai_color_palette(page: Page, probe):
    hits = []
    for sel, prop, val in page.all_declarations():
        if "gradient" not in val.lower():
            continue
        if prop not in ("background", "background-image", "border-image", "mask-image", "-webkit-mask-image"):
            continue
        for kind, body in gradients_in(val):
            cols = colors_in(body)
            if any(_purple_stop(c) for c in cols):
                hits.append(f"{sel}: {kind.replace('-gradient', '')} with a purple stop")
    for label, cls in _class_blob(page):
        if re.search(r"\bbg-(?:gradient|linear)", cls) and re.search(r"\b(?:from|via|to)-(?:purple|violet|fuchsia|indigo)-\d{2,3}", cls):
            hits.append(f"{label}: tailwind gradient through purple")
    neon = False
    purple_anywhere = bool(hits)
    if is_dark_page(page):
        for sel, prop, val in page.all_declarations():
            if prop in ("color", "-webkit-text-fill-color"):
                for c in colors_in(val):
                    h, s, l = hsl_of(c)
                    if 170 <= h <= 200 and s >= 0.7 and l >= 0.5:
                        neon = True
            if prop in ("background", "background-color", "border-color", "color"):
                if any(_purple_stop(c) or (300 <= hsl_of(c)[0] <= 340 and hsl_of(c)[1] >= 0.5) for c in colors_in(val)):
                    purple_anywhere = True
    if neon and purple_anywhere:
        hits.append("neon cyan ink on a dark ground with a second tell hue")
    hits = uniq(hits)
    if hits:
        return [F("slop/ai-color-palette", f"{len(hits)} use(s) of the stock generated-interface palette.", hits[:8])]


@rule("slop/cream-palette")
def cream_palette(page: Page, probe):
    bg = page_background(page)
    if not bg:
        return []
    h, s, l = hsl_of(bg)
    if 0.88 <= l <= 0.985 and 25 <= h <= 75 and s >= 0.18 and 6 <= spread(bg) <= 60:
        from .pagesrc import to_hex
        return [F("slop/cream-palette", f"The page background {to_hex(bg)} is a warm cream/beige.", {"background": to_hex(bg)})]


@rule("slop/stock-swatch")
def stock_swatch(page: Page, probe):
    # Tailwind v3 default palette values designers meet on every generated page
    stock = {"#6366f1": "indigo-500", "#4f46e5": "indigo-600", "#8b5cf6": "violet-500", "#7c3aed": "violet-600",
             "#a855f7": "purple-500", "#9333ea": "purple-600", "#0f172a": "slate-900", "#1e293b": "slate-800",
             "#3b82f6": "blue-500", "#2563eb": "blue-600", "#ec4899": "pink-500", "#06b6d4": "cyan-500",
             "#10b981": "emerald-500", "#f59e0b": "amber-500", "#ef4444": "red-500", "#64748b": "slate-500",
             "#f8fafc": "slate-50", "#f1f5f9": "slate-100", "#e2e8f0": "slate-200", "#334155": "slate-700"}
    found = {}
    for sel, prop, val in page.all_declarations():
        for m in re.finditer(r"#[0-9a-fA-F]{6}\b", val):
            name = stock.get(m.group(0).lower())
            if name:
                found.setdefault(name, sel)
    classes = " ".join(c for _, c in _class_blob(page))
    tw = sorted(set(re.findall(r"\b(?:bg|text|border|from|to|via|ring)-(?:indigo|violet|purple)-(?:400|500|600|700)\b", classes)))
    if len(found) >= 3 or (len(found) >= 2 and any(k.startswith(("indigo", "violet", "purple")) for k in found)) or len(tw) >= 2:
        return [F("slop/stock-swatch", "A framework's default palette values are used as the page's colours.",
                  {"hex": sorted(found), "utilities": tw[:8]})]


@rule("slop/pure-black-white")
def pure_black_white(page: Page, probe):
    hits = []
    for r in page.rules:
        if re.fullmatch(r"(?::root|html|body|\*)(?:\s*[.#][\w-]+)?", r.selector.strip()) and any(p.startswith("--") for p, _ in r.pairs) and not any(not p.startswith("--") for p, _ in r.pairs):
            continue  # the token block itself may hold anything
        for prop, val in r.pairs:
            if prop.startswith("--"):
                continue
            for m in re.finditer(r"(?<![\w-])(#000(?:000)?(?![0-9a-f])|#fff(?:fff)?(?![0-9a-f])|rgb\(\s*0\s*,\s*0\s*,\s*0\s*\)|rgb\(\s*255\s*,\s*255\s*,\s*255\s*\)|oklch\(\s*(?:0|100)%)", val, re.I):
                hits.append(f"{r.selector}: {prop}: {m.group(0)}")
    hits = uniq(hits)
    if hits:
        return [F("slop/pure-black-white", f"{len(hits)} pure black or white literal(s) outside the token block.", hits[:8])]


@rule("craft/zero-chroma-neutrals")
def zero_chroma_neutrals(page: Page, probe):
    colours = []
    for sel, prop, val in page.all_declarations():
        if prop in ("color", "background", "background-color", "border-color", "--bg", "--text") or prop.startswith("--"):
            for c in colors_in(val):
                if c[3] > 0.5:
                    colours.append(c)
    if len(colours) < 4:
        return []
    chromatic = [c for c in colours if spread(c) >= 40]
    grays = [c for c in colours if spread(c) <= 3 and 8 < c[0] < 247]
    if chromatic and len(grays) >= 3:
        return [F("craft/zero-chroma-neutrals", f"{len(grays)} pure-gray neutral(s) on a page with an accent colour.", len(grays))]


# ---------------------------------------------------------------------------
# effects
# ---------------------------------------------------------------------------

@rule("slop/dark-glow")
def dark_glow(page: Page, probe):
    dark = is_dark_page(page)
    hits = []
    for sel, prop, val in page.all_declarations():
        layers = []
        if prop in ("box-shadow", "text-shadow"):
            layers = shadow_layers(val)
        elif prop in ("filter", "-webkit-filter", "backdrop-filter") and "drop-shadow" in val:
            for m in re.finditer(r"drop-shadow\(([^)]*(?:\([^)]*\)[^)]*)*)\)", val):
                layers += shadow_layers(m.group(1))
        for L in layers:
            c = L["color"]
            if L["inset"] or not is_chromatic(c) or c[3] < 0.2 or L["blur"] < 8:
                continue
            halo = abs(L["x"]) <= 1 and abs(L["y"]) <= 1
            if halo or (dark and L["blur"] >= 12):
                hits.append(f"{sel}: {prop} {L['x']:g}px {L['y']:g}px {L['blur']:g}px chromatic")
    for label, cls in _class_blob(page):
        if dark and re.search(r"\bshadow-(?:purple|violet|indigo|blue|cyan|sky|pink|fuchsia|emerald|green|teal)-\d{2,3}(?:/\d+)?\b", cls):
            hits.append(f"{label}: coloured tailwind shadow")
    hits = uniq(hits)
    if hits:
        return [F("slop/dark-glow", f"{len(hits)} coloured glow shadow(s).", hits[:8])]


@rule("slop/radial-halo")
def radial_halo(page: Page, probe):
    hits = []
    for r in page.rules:
        d = r.decls
        filt = d.get("filter", "")
        m = re.search(r"blur\(\s*([\d.]+)px", filt)
        if not m or float(m.group(1)) < 40:
            continue
        pos = d.get("position", "")
        bgv = (d.get("background", "") + " " + d.get("background-color", "") + " " + d.get("background-image", ""))
        if pos in ("absolute", "fixed") and (any(is_chromatic(c) for c in colors_in(bgv)) or "gradient" in bgv):
            hits.append(f"{r.selector}: blur({m.group(1)}px) blob")
    for label, cls in _class_blob(page):
        if re.search(r"\babsolute\b", cls) and re.search(r"\bblur-(?:2xl|3xl)\b|\bblur-\[(?:[4-9]\d|\d{3,})px\]", cls) and re.search(r"\bbg-", cls):
            hits.append(f"{label}: tailwind blurred blob")
    hits = uniq(hits)
    if hits:
        return [F("slop/radial-halo", f"{len(hits)} blurred colour blob(s) behind the content.", hits[:8])]


@rule("slop/radial-spotlight-glow")
def radial_spotlight(page: Page, probe):
    hits = []
    for sel, prop, val in page.all_declarations():
        if not prop.startswith("background") or "radial-gradient" not in val.lower():
            continue
        for kind, body in gradients_in(val):
            if kind != "radial-gradient":
                continue
            cols = colors_in(body)
            chromatic = [c for c in cols if is_chromatic(c, 50)]
            faded = "transparent" in body.lower() or any(c[3] <= 0.6 for c in cols)
            if chromatic and faded:
                hits.append(f"{sel}: radial wash")
    hits = uniq(hits)
    if hits:
        return [F("slop/radial-spotlight-glow", f"{len(hits)} chromatic radial spotlight(s) fading to transparent.", hits[:8])]


@rule("slop/gpt-thin-border-wide-shadow")
def thin_border_wide_shadow(page: Page, probe):
    hits = []
    for r in page.rules:
        d = r.decls
        border = d.get("border", "") + " " + d.get("border-width", "")
        if not re.search(r"(?<![\d.])1px", border) or "none" in border:
            continue
        for L in shadow_layers(d.get("box-shadow", "")):
            if not L["inset"] and L["blur"] >= 24:
                hits.append(f"{r.selector}: 1px border + {L['blur']:g}px shadow")
                break
    if hits:
        return [F("slop/gpt-thin-border-wide-shadow", f"{len(hits)} surface(s) pair a hairline border with a wide soft shadow.", uniq(hits)[:8])]


@rule("quality/hard-offset-shadow")
def hard_offset_shadow(page: Page, probe):
    if re.search(r'data-vitruvius-ignore="[^"]*hard-offset-shadow', page.html):
        return []
    hits = []
    for sel, prop, val in page.all_declarations():
        if prop != "box-shadow":
            continue
        for L in shadow_layers(val):
            if not L["inset"] and L["blur"] == 0 and (abs(L["x"]) >= 4 or abs(L["y"]) >= 4) and L["color"][3] >= 0.3:
                hits.append(f"{sel}: {L['x']:g}px {L['y']:g}px 0")
                break
    hits = uniq(hits)
    if hits:
        return [F("quality/hard-offset-shadow", f"{len(hits)} hard offset shadow(s); fine for a neobrutalist direction, check it is intended.", hits[:8])]


@rule("slop/repeating-stripes-gradient")
def repeating_stripes(page: Page, probe):
    hits = []
    for sel, prop, val in page.all_declarations():
        if prop.startswith("background") and re.search(r"repeating-(?:linear|radial)-gradient", val, re.I):
            hits.append(sel)
    hits = uniq(hits)
    if hits:
        return [F("slop/repeating-stripes-gradient", f"{len(hits)} repeating-gradient pattern(s) used as texture.", hits[:8])]


@rule("slop/codex-grid-background")
def grid_background(page: Page, probe):
    hits = []
    for sel, prop, val in page.all_declarations():
        if not prop.startswith("background"):
            continue
        grads = [b for k, b in gradients_in(val) if k == "linear-gradient"]
        lines = [b for b in grads if re.search(r"(?<![\d.])1px", b) and "transparent" in b.lower()]
        if len(lines) >= 2:
            hits.append(sel)
    hits = uniq(hits)
    if hits:
        return [F("slop/codex-grid-background", f"{len(hits)} decorative grid-line background(s).", hits[:8])]


@rule("quality/organic-clip-path")
def organic_clip_path(page: Page, probe):
    hits = []
    for sel, prop, val in page.all_declarations():
        if prop not in ("clip-path", "-webkit-clip-path", "shape-outside"):
            continue
        low = val.lower()
        if low.startswith("polygon("):
            pts = [p for p in low[low.index("(") + 1: low.rindex(")")].split(",") if p.strip()]
            if len(pts) >= 9:
                hits.append(f"{sel}: polygon with {len(pts)} points")
        elif low.startswith("path(") and re.search(r"[cCqQsSaA]\s*-?\d", val):
            hits.append(f"{sel}: curved path()")
    hits = uniq(hits)
    if hits:
        return [F("quality/organic-clip-path", f"{len(hits)} clip-path(s) drawing an organic contour.", hits[:8])]


@rule("quality/buried-raster")
def buried_raster(page: Page, probe):
    hits = []
    for r in page.rules:
        d = r.decls
        bg = d.get("background", "") + " " + d.get("background-image", "")
        if "url(" in bg and "gradient" in bg.lower():
            layers = [l for l in re.split(r",(?![^(]*\))", bg)]
            first_url = next((i for i, l in enumerate(layers) if "url(" in l), None)
            washes = [l for i, l in enumerate(layers) if "gradient" in l.lower() and first_url is not None and i < first_url]
            for w in washes:
                cols = colors_in(w)
                if cols and all(c[3] >= 0.9 for c in cols):
                    hits.append(f"{r.selector}: opaque gradient over an image")
        op = d.get("opacity")
        if op and ("img" in r.selector.lower() or "url(" in bg):
            try:
                if 0 < float(op) < 0.08:
                    hits.append(f"{r.selector}: opacity {op}")
            except ValueError:
                pass
    hits = uniq(hits)
    if hits:
        return [F("quality/buried-raster", f"{len(hits)} image(s) buried under a wash or near-zero opacity.", hits[:8])]


@rule("quality/justified-text")
def justified_text(page: Page, probe):
    hits = [f"{sel}" for sel, prop, val in page.all_declarations() if prop == "text-align" and val.strip().lower().startswith("justify")]
    for n in page.nodes:
        if re.search(r"\btext-justify\b", n.attrs.get("class", "")):
            hits.append(n.label())
    hits = uniq(hits)
    if hits:
        return [F("quality/justified-text", f"{len(hits)} justified block(s).", hits[:8])]


# ---------------------------------------------------------------------------
# motion
# ---------------------------------------------------------------------------

_BOUNCE_NAME = re.compile(r"bounce|elastic|wobble|jiggle|spring", re.I)


def _anim_names(value: str) -> list[str]:
    return [t for t in re.split(r"[\s,]+", value) if t and not re.fullmatch(r"[\d.]+m?s|infinite|linear|ease[\w-]*|forwards|backwards|both|alternate\S*|normal|reverse|paused|running|none|steps\([^)]*\)|cubic-bezier\([^)]*\)", t, re.I)]


@rule("slop/bounce-easing")
def bounce_easing(page: Page, probe):
    hits = []
    for sel, prop, val in page.all_declarations():
        if prop in ("transition", "transition-timing-function", "animation", "animation-timing-function"):
            for m in re.finditer(r"cubic-bezier\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)", val):
                y1, y2 = float(m.group(2)), float(m.group(4))
                if y1 < -0.1 or y1 > 1.1 or y2 < -0.1 or y2 > 1.1:
                    hits.append(f"{sel}: {m.group(0)}")
        if prop in ("animation", "animation-name"):
            for name in _anim_names(val):
                if _BOUNCE_NAME.search(name):
                    hits.append(f"{sel}: animation {name}")
    for label, cls in _class_blob(page):
        if re.search(r"\banimate-bounce\b", cls):
            hits.append(f"{label}: animate-bounce")
    hits = uniq(hits)
    if hits:
        return [F("slop/bounce-easing", f"{len(hits)} bounce/overshoot motion(s).", hits[:8])]


def _dot_like(decls: dict[str, str], selector: str, cls: str = "") -> bool:
    w = px(decls.get("width")) or px(decls.get("height"))
    small = w is not None and 0 < w <= 16
    rad = decls.get("border-radius", "")
    round_ = "50%" in rad or "9999" in rad or "999px" in rad or (px(rad) is not None and w is not None and px(rad) >= w / 2)
    named = bool(re.search(r"dot|status|indicator|live|badge|pulse", selector, re.I))
    tw = bool(re.search(r"\b(?:w|h|size)-(?:1|1\.5|2|2\.5|3|3\.5|4)\b", cls)) and "rounded-full" in cls
    return (small and round_) or tw or (round_ and named and (small or w is None))


@rule("slop/pulsing-dot")
def pulsing_dot(page: Page, probe):
    hits = []
    pulse_names = {n for n in page.keyframes if re.search(r"pulse|ping|blink|beat|throb|glow", n, re.I)}
    for r in page.rules:
        names = _anim_names(r.decls.get("animation", "") + " " + r.decls.get("animation-name", ""))
        if any(n in pulse_names for n in names) and _dot_like(r.decls, r.selector):
            hits.append(r.selector)
    for n in page.nodes:
        cls = n.attrs.get("class", "")
        if re.search(r"\banimate-(?:ping|pulse)\b", cls) and _dot_like({}, n.label(), cls):
            hits.append(n.label())
        elif n.classes and any(c in pulse_names or re.search(r"pulse|ping", c) for c in n.classes):
            d = page.declared(n)
            if _dot_like(d, n.label(), cls):
                hits.append(n.label())
    hits = uniq(hits)
    if hits:
        return [F("slop/pulsing-dot", f"{len(hits)} small pulsing status dot(s).", hits[:8])]


@rule("slop/blinking-cursor")
def blinking_cursor(page: Page, probe):
    blink = set()
    for name, frames in page.keyframes.items():
        ops = {f.get("opacity") for _, f in frames if "opacity" in f}
        if re.search(r"blink|caret|cursor", name, re.I) or (ops >= {"0", "1"} and len(frames) <= 4):
            if re.search(r"blink|caret|cursor|typing|type", name, re.I) or "steps" in page.css:
                blink.add(name)
    hits = []
    for r in page.rules:
        names = _anim_names(r.decls.get("animation", "") + " " + r.decls.get("animation-name", ""))
        for n in names:
            if n in blink or re.search(r"blink|caret", n, re.I):
                if not re.search(r"^(input|textarea)\b|::?placeholder", r.selector, re.I):
                    hits.append(r.selector)
    for n in page.nodes:
        if n.tag in ("input", "textarea"):
            continue
        cls = " ".join(n.classes).lower()
        if re.search(r"blink|typing-cursor|type-cursor|caret", cls) and not n.attrs.get("contenteditable"):
            hits.append(n.label())
    hits = uniq(hits)
    if hits:
        return [F("slop/blinking-cursor", f"{len(hits)} decorative blinking cursor(s).", hits[:8])]


@rule("slop/marquee")
def marquee(page: Page, probe):
    hits = [f"<{n.tag}>" for n in page.nodes if n.tag == "marquee"]
    runner = set()
    for name, frames in page.keyframes.items():
        blob = " ".join(f.get("transform", "") for _, f in frames)
        m = re.findall(r"translate(?:X|3d)?\(\s*-(\d+(?:\.\d+)?)%", blob)
        if (m and max(float(x) for x in m) >= 33) or re.search(r"marquee|ticker", name, re.I):
            runner.add(name)
    for r in page.rules:
        a = r.decls.get("animation", "") + " " + r.decls.get("animation-name", "")
        if any(n in runner for n in _anim_names(a)) and re.search(r"infinite", r.decls.get("animation", "") + r.decls.get("animation-iteration-count", ""), re.I):
            hits.append(r.selector)
    for label, cls in _class_blob(page):
        if re.search(r"\banimate-marquee\b|\bmarquee\b", cls):
            hits.append(label)
    hits = uniq(hits)
    if hits:
        return [F("slop/marquee", f"{len(hits)} auto-scrolling band(s).", hits[:8])]


# ---------------------------------------------------------------------------
# imagery
# ---------------------------------------------------------------------------

@rule("slop/shape-assembled-illustration")
def shape_illustration(page: Page, probe):
    hits = []
    for svg in page.find("svg"):
        label = (svg.attrs.get("class", "") + " " + svg.attrs.get("aria-label", "") + " " + svg.id).lower()
        if re.search(r"chart|graph|diagram|map|logo|icon|plot|spark|gauge|flow", label):
            continue
        w = px(svg.attrs.get("width")) or 0
        m = re.match(r"\s*[-\d.]+[ ,]+[-\d.]+[ ,]+([\d.]+)[ ,]+([\d.]+)", svg.attrs.get("viewBox", svg.attrs.get("viewbox", "")))
        if m:
            w = max(w, float(m.group(1)))
        if w < 200:
            continue
        shapes = [d for d in svg.descendants() if d.tag in ("circle", "ellipse", "rect", "path", "polygon", "polyline")]
        if len(shapes) < 12 or any(d.tag in ("text", "image", "foreignobject") for d in svg.descendants()):
            continue
        fills = {d.attrs.get("fill", "") for d in shapes if d.attrs.get("fill")}
        if len(fills) >= 3:
            hits.append(f"svg {int(w)}px, {len(shapes)} shapes, {len(fills)} fills")
    if hits:
        return [F("slop/shape-assembled-illustration", f"{len(hits)} large SVG scene(s) built from primitive shapes.", hits[:6])]


_ICON_LIBS = {
    "font-awesome": r"\bfa[srbl]?\s+fa-|\bfa-(?:solid|regular|brands)\b|font-?awesome",
    "bootstrap-icons": r"\bbi\s+bi-|bootstrap-icons",
    "material-icons": r"material-(?:icons|symbols)",
    "phosphor": r"\bph(?:-bold|-fill|-light|-thin)?\s+ph-|phosphor",
    "remix-icon": r"\bri-[\w-]+-(?:line|fill)\b|remixicon",
    "lucide": r"\blucide\b|data-lucide",
    "feather": r"\bfeather\b|data-feather",
    "ionicons": r"<ion-icon|ionicons",
    "tabler": r"\bti\s+ti-|tabler-icons",
    "heroicons": r"heroicons",
}


@rule("slop/two-icon-libraries")
def two_icon_libraries(page: Page, probe):
    blob = page.html + " " + page.css
    found = [k for k, rx in _ICON_LIBS.items() if re.search(rx, blob, re.I)]
    if len(found) >= 2:
        return [F("slop/two-icon-libraries", f"{len(found)} icon libraries on one page: {', '.join(found)}.", found)]


@rule("slop/fake-browser-bar")
def fake_browser_bar(page: Page, probe):
    hits = []
    for n in page.nodes:
        label = (n.attrs.get("class", "") + " " + n.id).lower()
        if re.search(r"traffic[-_ ]?light|window-dots|mac-dots|browser-(?:bar|chrome|header)|window-(?:bar|controls)|titlebar|title-bar|url-bar|address-bar", label):
            hits.append(n.label())
    # three small coloured circles side by side: red, yellow, green
    for n in page.nodes:
        kids = [c for c in n.children if c.tag in ("span", "div", "i")]
        if len(kids) == 3:
            cols = []
            for k in kids:
                d = page.declared(k)
                bg = colors_in(d.get("background", "") + " " + d.get("background-color", ""))
                cols.append(bg[0] if bg else None)
            if all(cols):
                hs = [hsl_of(c)[0] for c in cols]
                if hs[0] < 20 or hs[0] > 340:
                    if 30 <= hs[1] <= 65 and 85 <= hs[2] <= 160 and all(is_chromatic(c) for c in cols):
                        hits.append(n.label() + " (red/yellow/green dots)")
    hits = uniq(hits)
    if hits:
        return [F("slop/fake-browser-bar", f"{len(hits)} hand-drawn browser or window bar(s).", hits[:6])]


@rule("slop/wireframe-page")
def wireframe_page(page: Page, probe):
    slots = [n for n in page.nodes if "data-slot" in n.attrs]
    empty = [n for n in slots if not [d for d in n.descendants() if d.tag in ("img", "video", "picture", "canvas", "svg", "iframe")] and not n.text()]
    if len(empty) > 5:
        return [F("slop/wireframe-page", f"{len(empty)} empty image slots on one page.", len(empty))]
    # four or more empty slots sharing a parent
    by_parent: dict[int, int] = {}
    for n in empty:
        by_parent[id(n.parent)] = by_parent.get(id(n.parent), 0) + 1
    if by_parent and max(by_parent.values()) >= 4:
        return [F("slop/wireframe-page", "Four or more empty image slots in one row.", max(by_parent.values()))]
