"""The ``unslop`` pack: sign -> fix rules measured on the rendered page (computed styles) plus two read from the source.

Original implementations. The list of signs and the fix each one asks for follow ``references/signs.md`` of *unslop* by
Damir Sokolovsky (@heydamir, https://github.com/heydamir/unslop, CC BY 4.0); the wording here is ours. Signs that an
earlier pack already measures are not duplicated: ``SIGN_COVERAGE`` names the rule that answers each of them.

Every browser rule runs at every captured width (the slop audit renders eight, 320 to 1920) and reports the widths where
it fired; evidence carries ``boxes`` ([x, y, w, h] in page pixels at ``box_width``) so a screen can mark the spot.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Callable

from .base import F, shadow_layers, short, uniq
from .dom_rules import CHECKS as DOM_CHECKS, Ctx, drule
from .domtree import Dom, El
from .pagesrc import Page, colors_in, hsl_of, parse_color
from .static_a import CHECKS as STATIC_CHECKS, rule as srule

MAX_BOXES = 12


def box(e: El) -> list[int]:
    return [int(e.x), int(e.y), int(e.w), int(e.h)]


REFERENCE_WIDTH = 1440


def across(cx: Ctx, fn: Callable[[Dom], list]) -> tuple[list, list[int], int]:
    """Run ``fn`` at every width. Returns (the hits at the fired width nearest 1440, widths that fired, that width)."""
    by: dict[int, list] = {}
    for d in cx.all:
        hits = fn(d) or []
        if hits:
            by[d.width] = hits
    if not by:
        return [], [], 0
    at = min(by, key=lambda w: (abs(w - REFERENCE_WIDTH), -w))
    return by[at], sorted(by), at


def emit(rule_id: str, cx: Ctx, fn: Callable[[Dom], list], detail: Callable[[list], str], label: Callable[[object], str] = None):
    """The common shape: hits are El or (El, note) pairs; evidence lists them with boxes and the widths."""
    hits, widths, at = across(cx, fn)
    if not hits:
        return None
    els = [h[0] if isinstance(h, tuple) else h for h in hits]
    notes = [(h[1] if isinstance(h, tuple) else "") for h in hits]
    items = uniq([(label(h) if label else (e.snippet(36) + (f" ({n})" if n else ""))) for h, e, n in zip(hits, els, notes)])
    return [F(rule_id, detail(hits) + (f" Seen at {', '.join(map(str, widths))}px." if len(cx.all) > 1 else ""),
              {"items": items[:10], "widths": widths, "box_width": at, "boxes": [box(e) for e in els[:MAX_BOXES]]})]


def _saturated(c, s_min: float = 0.45, l_lo: float = 0.22, l_hi: float = 0.82) -> bool:
    if not c or c[3] < 0.12:
        return False
    _, s, l = hsl_of(c)
    return s >= s_min and l_lo <= l <= l_hi


def _visible(e: El) -> bool:
    return e.w > 0 and e.h > 0 and (e.st("op") is None or float(e.st("op")) >= 0.3) and e.st("vis") != "hidden"


def _texty(d: Dom, n: int = 1) -> list[El]:
    return [e for e in d.text_els() if e.tl >= n and _visible(e)]


_HEADS = ("h1", "h2", "h3", "h4", "h5", "h6")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-⛿✨⭐✅❌❤⏰-⏺\U0001F004\U0001F0CF]")
_SPARKLE = re.compile("[✨\U0001F31F\U0001F4AB]")


# ---------------------------------------------------------------------------- surfaces and colour

@drule("unslop/gradient-text-measured")
def gradient_text_measured(cx: Ctx):
    def fn(d: Dom):
        return [e for e in d.els if "text" in str(e.st("bg_clip") or "") and e.gradient and e.deep_text_len() > 0]
    return emit("unslop/gradient-text-measured", cx, fn, lambda h: f"{len(h)} element(s) paint their text with a gradient (background-clip: text).")


@drule("unslop/saturated-shadow")
def saturated_shadow(cx: Ctx):
    def fn(d: Dom):
        hits = []
        for e in d.els:
            if not _visible(e):
                continue
            for key in ("sh", "tsh"):
                for layer in shadow_layers(e.st(key) or ""):
                    if layer["blur"] >= 6 and not layer["inset"] and _saturated(layer["color"], 0.45, 0.2, 0.85):
                        hits.append((e, f"{'text-' if key == 'tsh' else ''}shadow {layer['blur']:g}px"))
                        break
                else:
                    continue
                break
        return hits
    return emit("unslop/saturated-shadow", cx, fn, lambda h: f"{len(h)} element(s) cast a coloured, blurred shadow or glow.")


def _gradient_hues(value: str) -> list[float]:
    return [hsl_of(c)[0] for c in colors_in(value or "") if _saturated(c, 0.3, 0.15, 0.9)]


@drule("unslop/purple-gradient-hero")
def purple_gradient_hero(cx: Ctx):
    def fn(d: Dom):
        hits = []
        for e in d.els:
            if not e.gradient or e.y > d.vh * 0.6 or e.w < d.width * 0.6 or e.h < 200:
                continue
            hues = _gradient_hues(e.st("bgi"))
            purple = [h for h in hues if 245 <= h <= 335]
            blue = [h for h in hues if 190 <= h < 245]
            if purple and (len(purple) >= 2 or blue):
                hits.append((e, "hues " + ", ".join(f"{h:.0f}" for h in hues[:4])))
        return hits[:3]
    return emit("unslop/purple-gradient-hero", cx, fn, lambda h: "The first screen sits on a purple / violet / blue-to-pink gradient.")


@drule("unslop/neon-border")
def neon_border(cx: Ctx):
    def fn(d: Dom):
        hits = []
        for e in d.els:
            if e.w < 80 or e.h < 24 or not _visible(e) or e.tag in ("input", "textarea", "select", "hr"):
                continue
            cols = e.s.get("bc") or []
            for k, width in enumerate(e.borders):
                if width >= 1 and k < len(cols) and _saturated(parse_color(cols[k]), 0.7, 0.4, 0.75):
                    hits.append(e)
                    break
        return hits if len(hits) >= 3 else []
    return emit("unslop/neon-border", cx, fn, lambda h: f"{len(h)} boxes are outlined in a saturated, bright border.")


@drule("unslop/many-text-tints")
def many_text_tints(cx: Ctx):
    def fn(d: Dom):
        tints: dict[tuple, El] = {}
        for e in _texty(d, 3):
            c = e.ink
            if not c or c[3] < 0.3 or hsl_of(c)[1] > 0.18:
                continue
            key = tuple(int(round(v / 6)) for v in c[:3])
            if not any(sum(abs(a - b) for a, b in zip(key, k)) <= 1 for k in tints):
                tints[key] = e
        return list(tints.values()) if len(tints) > 5 else []
    return emit("unslop/many-text-tints", cx, fn, lambda h: f"Text is set in {len(h)} different greys; three text roles would do.",
                label=lambda e: f"{e.snippet(24)} {e.st('color')}")


# ---------------------------------------------------------------------------- type

@drule("unslop/heavy-headings")
def heavy_headings(cx: Ctx):
    def fn(d: Dom):
        heads = [e for e in d.headings(1, 2, 3) if _visible(e)]
        heavy = [e for e in heads if e.fw >= 800]
        return heavy if len(heavy) >= 2 and len(heavy) * 2 >= len(heads) else []
    return emit("unslop/heavy-headings", cx, fn, lambda h: f"{len(h)} headings are set at weight 800-900.")


@drule("unslop/too-many-sizes")
def too_many_sizes(cx: Ctx):
    def fn(d: Dom):
        by: dict[int, El] = {}
        for e in _texty(d):
            by.setdefault(int(round(e.fs)), e)
        return [(by[k], f"{k}px") for k in sorted(by)] if len(by) > 8 else []
    return emit("unslop/too-many-sizes", cx, fn, lambda h: f"{len(h)} different font sizes: " + ", ".join(n for _, n in h) + ".")


@drule("unslop/tracked-caps-measured")
def tracked_caps_measured(cx: Ctx):
    def fn(d: Dom):
        hits = []
        for e in _texty(d):
            letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", e.text)
            caps = e.st("tt") == "uppercase" or (len(letters) >= 3 and letters.isupper())
            if e.tl <= 40 and e.fs <= 15 and caps and e.ls_em >= 0.05:
                hits.append((e, f"{e.ls_em:.2f}em"))
        return hits if len(hits) >= 2 else []
    return emit("unslop/tracked-caps-measured", cx, fn, lambda h: f"{len(h)} small labels are uppercase and letter-spaced.")


@drule("unslop/small-negative-tracking")
def small_negative_tracking(cx: Ctx):
    def fn(d: Dom):
        hits = [(e, f"{e.ls_em:.3f}em at {e.fs:g}px") for e in _texty(d, 3) if e.fs < 16 and e.ls_em < -0.01]
        return hits if len(hits) >= 3 else []
    return emit("unslop/small-negative-tracking", cx, fn, lambda h: f"{len(h)} pieces of small text are tracked tighter than zero.")


# The faces a page ends up in when nobody chose one: browser and framework defaults and the two or three template favourites.
_DEFAULT_SANS = {"inter", "inter var", "inter tight", "roboto", "arial", "helvetica", "helvetica neue", "system-ui", "-apple-system",
                 "blinkmacsystemfont", "segoe ui", "ui-sans-serif", "sans-serif", "open sans", "poppins", "dm sans", "geist", "geist sans",
                 "plus jakarta sans"}


@drule("unslop/single-default-sans")
def single_default_sans(cx: Ctx):
    def fn(d: Dom):
        weight: Counter = Counter()
        first: dict[str, El] = {}
        for e in _texty(d):
            weight[e.ff] += e.tl
            first.setdefault(e.ff, e)
        total = sum(weight.values())
        if total < 200 or not weight:
            return []
        fam, n = weight.most_common(1)[0]
        display = {e.ff for e in d.headings(1, 2, 3) if e.ff}
        return [(first[fam], fam)] if fam in _DEFAULT_SANS and n >= 0.95 * total and display <= {fam} else []
    return emit("unslop/single-default-sans", cx, fn, lambda h: f"Every line is set in {h[0][1].title()}: one default sans, no display face.",
                label=lambda h: h[1])


# ---------------------------------------------------------------------------- icons

@drule("unslop/emoji-in-ui")
def emoji_in_ui(cx: Ctx):
    def fn(d: Dom):
        hits = []
        for e in _texty(d):
            if not _EMOJI.search(e.text):
                continue
            ui = e.tag in ("a", "button", "label", "summary", *_HEADS) or e.in_tag("nav", "header", "button", "a") or e.tl <= 24 or e.has_box
            if ui:
                hits.append((e, "sparkle" if _SPARKLE.search(e.text) else "emoji"))
        return hits
    return emit("unslop/emoji-in-ui", cx, fn, lambda h: f"{len(h)} labels, links or headings use emoji as icons"
                + (" (including the sparkle)." if any(n == "sparkle" for _, n in h) else "."))


# ---------------------------------------------------------------------------- spacing

def _spacing_values(d: Dom) -> list[tuple[float, El]]:
    out = []
    for e in d.els:
        if not _visible(e):
            continue
        vals = list(e.pad) + [e.st("gap") or 0]
        if e.tag not in (*_HEADS, "p", "ul", "ol", "body", "html", "blockquote", "figure", "dl", "dd"):
            vals += [abs(v) for v in (e.s.get("mar") or [])]
        out += [(float(v), e) for v in vals if v and float(v) >= 3]
    return out


@drule("unslop/off-grid-spacing")
def off_grid_spacing(cx: Ctx):
    def fn(d: Dom):
        vals = _spacing_values(d)
        if len(vals) < 12:
            return []
        off = [(v, e) for v, e in vals if abs(v / 4 - round(v / 4)) * 4 > 0.6]
        distinct = Counter(round(v, 1) for v, _ in off)
        if len(off) < 0.25 * len(vals) or len(distinct) < 3:
            return []
        seen, hits = set(), []
        for v, e in off:
            if e.i not in seen:
                seen.add(e.i)
                hits.append((e, f"{v:g}px"))
        return hits
    return emit("unslop/off-grid-spacing", cx, fn, lambda h: f"{len(h)} elements use paddings, gaps or margins off the 4px grid ("
                + ", ".join(sorted({n for _, n in h}, key=lambda s: float(s[:-2])))[:120] + ").")


def _rows(d: Dom, min_n: int = 3) -> list[list[El]]:
    """Sibling cards that share a parent and a top edge: the rows of a card grid."""
    groups: dict[tuple, list[El]] = {}
    for e in d.els:
        if e.parent is not None and e.is_card and _visible(e):
            groups.setdefault((e.parent.i, round(e.y / 6)), []).append(e)
    return [g for g in groups.values() if len(g) >= min_n]


@drule("unslop/uniform-card-grid")
def uniform_card_grid(cx: Ctx):
    def fn(d: Dom):
        hits = []
        for row in _rows(d):
            same = [e for e in row if abs(e.w - row[0].w) <= 3 and abs(e.h - row[0].h) <= 6]
            if len(same) >= 3 and len(same) == len(row):
                hits += [(e, f"{e.w}x{e.h}") for e in row]
        return hits
    return emit("unslop/uniform-card-grid", cx, fn, lambda h: f"A row of {len(h)} identical cards (same width and height).")


@drule("unslop/uneven-sibling-padding")
def uneven_sibling_padding(cx: Ctx):
    def fn(d: Dom):
        hits = []
        for row in _rows(d, 2):
            pads = [e.pad for e in row]
            if any(max(p[k] for p in pads) - min(p[k] for p in pads) > 8 for k in range(4)):
                hits += [(e, "/".join(f"{v:g}" for v in e.pad)) for e in row]
        return hits
    return emit("unslop/uneven-sibling-padding", cx, fn, lambda h: f"Cards in one row are padded differently ({len(h)} cards).")


# ---------------------------------------------------------------------------- copy

_GREETING = re.compile(r"^\W*(welcome|hello|hi|hey|good (morning|afternoon|evening)|bienvenid[oa]s?|hola|buen(os|as) (d[ií]as|tardes|noches))\b", re.I)
_PROOF = re.compile(r"\b\d[\d,.]*\s*[kKmM]?\+\s*(happy\s+|satisfied\s+)?(users|customers|teams|developers|companies|creators|clientes|usuarios|equipos|empresas)\b"
                    r"|\btrusted by (over |more than )?\d|\bloved by \d|★{5}|⭐{5}|\b[45][.,]\d\s*/\s*5\b|\brated \d", re.I)


@drule("unslop/greeting-headline")
def greeting_headline(cx: Ctx):
    def fn(d: Dom):
        heads = [e for e in d.headings(1, 2) if _visible(e)][:2]
        return [e for e in heads if _GREETING.search(e.text or e.snippet(60))][:1]
    return emit("unslop/greeting-headline", cx, fn, lambda h: "The headline greets the visitor instead of naming the page.")


@drule("unslop/exclamation-copy")
def exclamation_copy(cx: Ctx):
    def fn(d: Dom):
        hits = [e for e in _texty(d, 3) if e.tag in (*_HEADS, "button", "a", "label", "p", "span", "li") and re.search(r"!\s*$|!\s+[A-Z]", e.text)]
        return hits if len(hits) >= 2 or any(e.tag in _HEADS for e in hits) else []
    return emit("unslop/exclamation-copy", cx, fn, lambda h: f"{len(h)} lines end with an exclamation mark.")


@drule("unslop/label-trailing-period")
def label_trailing_period(cx: Ctx):
    def fn(d: Dom):
        return [e for e in _texty(d, 2) if (e.tag in ("button", "label", "th", "summary") or (e.tag == "a" and e.has_box))
                and len(e.text) <= 30 and len(e.text.split()) <= 4 and e.text.endswith(".") and not e.text.endswith("..")]
    return emit("unslop/label-trailing-period", cx, fn, lambda h: f"{len(h)} button or label texts end with a full stop.")


@drule("unslop/unsourced-proof")
def unsourced_proof(cx: Ctx):
    def fn(d: Dom):
        return [e for e in _texty(d, 4) if _PROOF.search(e.text)]
    return emit("unslop/unsourced-proof", cx, fn, lambda h: f"{len(h)} claim(s) of users, ratings or trust with no source on the page.")


# ---------------------------------------------------------------------------- components

_BADGE = re.compile(r"^\W*(pro|new|beta|hot|ai|alpha|preview|nuevo|nueva|free|popular)\W*$", re.I)


@drule("unslop/stacked-badges")
def stacked_badges(cx: Ctx):
    def fn(d: Dom):
        hits = [e for e in _texty(d) if e.tl <= 10 and _BADGE.match(e.text) and (e.has_box or (e.parent is not None and e.parent.has_box and e.parent.h <= 32))]
        return hits if len(hits) >= 2 else []
    return emit("unslop/stacked-badges", cx, fn, lambda h: f"{len(h)} 'Pro / New / Beta' style badges.")


@drule("unslop/pill-everything")
def pill_everything(cx: Ctx):
    def fn(d: Dom):
        boxed = [e for e in d.els if e.has_box and e.h >= 32 and e.w >= 48 and _visible(e) and e.tag not in ("body", "html")]
        pills = [e for e in boxed if e.radius >= e.h / 2 - 1]
        big = [e for e in pills if e.h >= 56 and e.tag not in ("button", "a", "input")]
        return pills if len(pills) >= 5 and len(pills) >= 0.6 * len(boxed) and big else []
    return emit("unslop/pill-everything", cx, fn, lambda h: f"{len(h)} boxes, panels included, are fully rounded pills.")


# ---------------------------------------------------------------------------- layout and heroes

def _button_like(e: El) -> bool:
    return (e.tag == "button" or (e.tag == "a" and (e.bg is not None or e.gradient or any(b >= 1 for b in e.borders)))) and 28 <= e.h <= 80 and e.w <= 420


@drule("unslop/too-many-ctas")
def too_many_ctas(cx: Ctx):
    def fn(d: Dom):
        hero = [e for e in d.els if _button_like(e) and _visible(e) and e.y < d.vh and not e.in_tag("nav", "header", "form")]
        return hero if len(hero) >= 3 else []
    return emit("unslop/too-many-ctas", cx, fn, lambda h: f"The first screen offers {len(h)} buttons.")


@drule("unslop/centered-hero-stack")
def centered_hero_stack(cx: Ctx):
    def fn(d: Dom):
        h1 = next((e for e in d.headings(1) if _visible(e) and e.y < d.vh), None)
        if h1 is None or h1.st("ta") != "center" or d.width < 900:
            return []
        lede = [e for e in d.tags("p") if e.y < d.vh and e.y > h1.y and e.st("ta") == "center" and e.tl >= 30]
        acts = [e for e in d.els if _button_like(e) and h1.y < e.y < d.vh and abs(e.cx - d.width / 2) < d.width * 0.25]
        return [h1, *lede[:1], *acts[:2]] if lede and acts else []
    return emit("unslop/centered-hero-stack", cx, fn, lambda h: "Headline, lede and actions are stacked on one centred axis.")


# ---------------------------------------------------------------------------- motion (read from the source)

def _classes(page: Page) -> list[tuple[str, str]]:
    return [(n.label(), n.attrs["class"]) for n in page.nodes if n.attrs.get("class")]


@srule("unslop/hover-scale")
def hover_scale(page: Page, probe):
    hits = []
    for sel, prop, val in page.all_declarations():
        if ":hover" in sel and prop in ("transform", "scale"):
            m = re.search(r"scale\(\s*([\d.]+)|^\s*([\d.]+)\s*$", val)
            k = float((m.group(1) or m.group(2))) if m else 1.0
            if k >= 1.03:
                hits.append(f"{sel}: {short(val, 40)}")
    for label, cls in _classes(page):
        if re.search(r"\bhover:scale-1(0[3-9]|[1-9]\d)\b", cls):
            hits.append(f"{label}: hover:scale")
    hits = uniq(hits)
    if hits:
        return [F("unslop/hover-scale", f"{len(hits)} element(s) grow on hover.", {"items": hits[:10]})]


_FLOAT_NAME = re.compile(r"float|levitat|hover|drift|bob|parallax|orbit", re.I)


@srule("unslop/floating-loop")
def floating_loop(page: Page, probe):
    hits = []
    for sel, prop, val in page.all_declarations():
        if prop == "animation" and "infinite" in val.lower():
            for name in re.split(r"[\s,]+", val):
                frames = page.keyframes.get(name) or []
                body = " ".join(" ".join(f"{k}:{v}" for k, v in decls.items()) for _, decls in frames)
                if _FLOAT_NAME.search(name) or re.search(r"translate(Y|3d)?\(", body):
                    hits.append(f"{sel}: animation {name}")
                    break
        if prop == "background-attachment" and "fixed" in val:
            hits.append(f"{sel}: background-attachment fixed")
    for label, cls in _classes(page):
        if re.search(r"\b(animate-float\w*|parallax\w*|animate-bounce-slow)\b", cls):
            hits.append(f"{label}: {cls[:40]}")
    for n in page.nodes:
        if any(k.startswith("data-parallax") or k.startswith("data-rellax") for k in n.attrs):
            hits.append(f"{n.label()}: data-parallax")
    hits = uniq(hits)
    if hits:
        return [F("unslop/floating-loop", f"{len(hits)} element(s) float in a loop or move with the scroll.", {"items": hits[:10]})]


# Each sign of the unslop list -> the rule(s) that answer it here ("judged" = left to the vision model / the clean review).
SIGN_COVERAGE: dict[str, tuple[str, ...]] = {
    "purple-pink gradient surfaces": ("slop/ai-color-palette", "color.purple-blue-gradient", "unslop/purple-gradient-hero"),
    "gradient text": ("slop/gradient-text", "unslop/gradient-text-measured"),
    "coloured glows and shadows": ("slop/dark-glow", "unslop/saturated-shadow"),
    "radial washes and blobs": ("slop/radial-halo", "slop/radial-spotlight-glow"),
    "neon borders": ("unslop/neon-border",),
    "many text tints": ("unslop/many-text-tints",),
    "everything highlighted": ("visual/accent-footprint",),
    "heavy headings": ("unslop/heavy-headings",),
    "wide-tracked uppercase labels": ("slop/tracked-caps-label", "unslop/tracked-caps-measured"),
    "too many sizes and weights": ("unslop/too-many-sizes", "craft/font-weights", "type.scale-flat"),
    "mixed number formats": ("craft/tabular-figures",),
    "negative tracking on small text": ("unslop/small-negative-tracking", "slop/extreme-negative-tracking"),
    "italic for emphasis": ("slop/italic-word-in-heading", "slop/accented-word"),
    "emoji as icons": ("unslop/emoji-in-ui", "content.emoji-icons"),
    "icons of mixed size and colour": ("slop/two-icon-libraries",),
    "arbitrary pixel values": ("unslop/off-grid-spacing", "ds/spacing"),
    "inconsistent gaps": ("slop/monotonous-spacing", "craft/section-gaps"),
    "groups closer to neighbours than to their own items": ("quality/heading-rhythm",),
    "uneven padding across sibling cards": ("unslop/uneven-sibling-padding",),
    "greeting headlines": ("unslop/greeting-headline",),
    "exclamation marks": ("unslop/exclamation-copy",),
    "hype vocabulary": ("slop/marketing-buzzword", "slop/copy-tells"),
    "trailing periods on labels": ("unslop/label-trailing-period",),
    "obviously fake data": ("slop/copy-tells", "content.placeholder-copy"),
    "glowing pills and stacked badges": ("unslop/stacked-badges", "unslop/saturated-shadow"),
    "pills on every element": ("unslop/pill-everything",),
    "identical cards in a row": ("unslop/uniform-card-grid", "layout.hero-three-cards"),
    "pill badges above headlines": ("slop/hero-eyebrow-chip",),
    "centred stacks of everything": ("unslop/centered-hero-stack", "visual/hero-shape"),
    "three or more buttons": ("unslop/too-many-ctas",),
    "unsourced social proof": ("unslop/unsourced-proof", "visual/invented-proof"),
    "parallax and floating loops": ("unslop/floating-loop",),
    "glossy orbs, robots, brains": ("visual/glow-and-wash", "visual/drawn-illustration"),
    "pulsing elements that are not live": ("slop/pulsing-dot",),
    "transition-all and scale-on-hover": ("craft/transition-all", "unslop/hover-scale"),
    "bouncy springs": ("slop/bounce-easing",),
    "animating layout properties": ("craft/transition-layout-props",),
    "template look (default grey, default sans, stock colour)": ("unslop/single-default-sans", "slop/stock-swatch", "font.generic-only"),
}


def implemented() -> list[str]:
    """The unslop rule ids that have a check here."""
    return sorted(k for k in (*DOM_CHECKS, *STATIC_CHECKS) if k.startswith("unslop/"))
