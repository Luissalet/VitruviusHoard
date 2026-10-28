"""Render rules: what a real browser measured (box geometry and computed styles from ``browser.DOM_JS``).

Original implementations. The ideas follow the generic-interface tells catalogued by the Apache-2.0 impeccable detector and
the MIT hallmark render gates (see NOTICE); thresholds were chosen here and checked against fixtures in the tests.
A rule returns nothing when the capture has no snapshot (a text-only lint), never a guess.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Callable, Optional

from .base import F, short, uniq
from .domtree import Dom, El, doms
from .pagesrc import hue_gap, hsl_of, is_chromatic, spread

CHECKS: dict[str, Callable] = {}


@dataclass
class Ctx:
    probe: dict
    all: list[Dom]

    @property
    def wide(self) -> Optional[Dom]:
        return self.all[0] if self.all else None

    @property
    def narrow(self) -> Optional[Dom]:
        return self.all[-1] if len(self.all) > 1 else None

    @property
    def desktop(self) -> Optional[Dom]:
        """The widest capture when it is a desktop width (>= 1200), else None."""
        w = self.wide
        return w if w and w.width >= 1200 else None


def drule(rule_id: str):
    def deco(fn):
        def run(probe, html):
            d = doms(probe or {})
            if not d and rule_id != "quality/script-error":
                return []
            return fn(Ctx(probe or {}, d)) or []
        run.__name__ = fn.__name__
        CHECKS[rule_id] = run
        return run
    return deco


def _accent_side(e: El) -> list[tuple[str, float]]:
    """Sides (top/right/bottom/left) carrying a thick chromatic border while the others are thin."""
    from .pagesrc import parse_color
    bw = e.borders
    cols = e.s.get("bc") or []
    names = ("top", "right", "bottom", "left")
    out = []
    for k in range(4):
        if bw[k] >= 3 and k < len(cols):
            c = parse_color(cols[k])
            if c and is_chromatic(c, 40) and all(bw[j] <= 1.5 for j in range(4) if j != k):
                out.append((names[k], bw[k]))
    return out


# ---------------------------------------------------------------------------
# slop
# ---------------------------------------------------------------------------

@drule("slop/side-tab")
def side_tab(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.els:
        if e.w < 120 or e.h < 28 or e.tag in ("blockquote", "hr", "body", "html") or e.deep_text_len() < 12:
            continue
        for side, width in _accent_side(e):
            if side in ("left", "right"):
                hits.append(f"{e.label()} {side} {width:g}px" + (f", radius {e.radius:g}px" if e.radius >= 8 else ""))
    hits = uniq(hits)
    if hits:
        return [F("slop/side-tab", f"{len(hits)} block(s) with one thick coloured side border.", hits[:8])]


@drule("slop/border-accent-on-rounded")
def border_accent_rounded(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.els:
        if e.w < 120 or e.h < 28 or e.radius < 8 or e.deep_text_len() < 12:
            continue
        for side, width in _accent_side(e):
            if side in ("top", "bottom"):
                hits.append(f"{e.label()} {side} {width:g}px, radius {e.radius:g}px")
    hits = uniq(hits)
    if hits:
        return [F("slop/border-accent-on-rounded", f"{len(hits)} rounded block(s) with a thick accent border on one edge.", hits[:8])]


_OVERUSED = {"inter", "roboto", "open sans", "montserrat", "fraunces", "geist", "plus jakarta sans", "space grotesk", "poppins", "dm sans",
             "lato", "nunito", "raleway", "playfair display", "instrument serif", "manrope", "outfit", "sora", "work sans", "ibm plex sans",
             "inter tight", "geist sans", "source sans pro", "source sans 3"}


@drule("slop/overused-font")
def overused_font(cx: Ctx):
    d = cx.wide
    heads = d.headings(1, 2)
    body = [e for e in d.tags("p", "li") if e.tl >= 40]

    def fam(els: list[El]) -> str:
        counts: dict[str, int] = {}
        for e in els:
            counts[e.ff] = counts.get(e.ff, 0) + 1
        return max(counts.items(), key=lambda kv: kv[1])[0] if counts else ""
    hf, bf = fam(heads), fam(body)
    named = [(role, f) for role, f in (("heading", hf), ("body", bf)) if f in _OVERUSED]
    if named:
        return [F("slop/overused-font", "The " + " and ".join(f"{role} face is {f.title()}" for role, f in named) + ".", {role: f for role, f in named})]


_SERIF = re.compile(r"serif|georgia|times|garamond|cormorant|playfair|fraunces|lora|merriweather|newsreader|baskerville|bodoni|didot|spectral|crimson|gloock|libre caslon|source serif|dm serif|instrument serif|young serif|literata|cardo|tiempos|canela", re.I)


@drule("slop/italic-serif-display")
def italic_serif_display(cx: Ctx):
    d = cx.wide
    hits = []
    for h in d.headings(1):
        pool = [h, *h.descendants()]
        for e in pool:
            if e.st("fst") in ("italic", "oblique") and e.fs >= 36 and e.ff and (_SERIF.search(e.ff) and "sans" not in e.ff) and (e.text or e.tl):
                hits.append(f"{h.label()}: {short(e.text or h.text, 40)} ({e.ff}, {e.fs:g}px)")
                break
    if hits:
        return [F("slop/italic-serif-display", "The hero heading sets italic serif at display size.", hits[:3])]


def _small_label(e: El, head: El) -> bool:
    if not e.tl or e.tl > 48 or e.children and any(c.tl for c in e.children if c.tag in ("p", "h1", "h2", "h3")):
        return False
    small = e.fs <= 14.5 or e.fs <= head.fs * 0.5
    tracked = e.st("tt") == "uppercase" or e.ls_em >= 0.06
    chip = e.radius >= 10 and e.has_box
    accent = bool(e.ink and is_chromatic(e.ink, 50) and e.fw >= 600)
    return small and (tracked or chip or accent)


def _label_above(d: Dom, head: El) -> Optional[El]:
    best = None
    for e in d.els:
        if e is head or e.tl == 0 or e.bottom > head.y + 2 or head.y - e.bottom > 64:
            continue
        if abs(e.x - head.x) > max(40, head.w * 0.5) and abs(e.cx - head.cx) > 40:
            continue
        if e.right < head.x or e.x > head.right:
            continue
        if e.tag in ("h1", "h2", "h3", "h4", "p") and e.fs > 16:
            continue
        if _small_label(e, head) and (best is None or e.bottom > best.bottom):
            best = e
    return best


@drule("slop/hero-eyebrow-chip")
def hero_eyebrow_chip(cx: Ctx):
    d = cx.wide
    h1s = [h for h in d.headings(1) if d.first_screen(h)]
    if not h1s:
        return []
    h1 = max(h1s, key=lambda h: h.fs)
    lab = _label_above(d, h1)
    if lab is not None and (lab.st("tt") == "uppercase" or lab.ls_em >= 0.06 or lab.radius >= 10 or lab.fw >= 600):
        return [F("slop/hero-eyebrow-chip", f"A small label sits above the hero headline: {short(lab.text, 40)}.", {"label": lab.snippet(), "heading": h1.snippet()})]


@drule("slop/kicker-above-heading")
def kicker_above(cx: Ctx):
    d = cx.wide
    hits = []
    for h in d.headings(1, 2, 3):
        if h.deep_text_len() < 12:
            continue
        lab = _label_above(d, h)
        if lab is not None and not re.fullmatch(r"\s*\d{1,2}\b.*", lab.text or ""):
            hits.append(f"{short(lab.text, 28)} / {short(h.text or '', 28)}")
    if len(hits) >= 2:
        return [F("slop/kicker-above-heading", f"{len(hits)} headings announced by a small label above them.", hits[:6])]


_NUMBERED = re.compile(r"^(?:no\.?\s*)?0?\d{1,2}\s*(?:[/.\-–—·:)]\s*\S.{0,28})?$", re.I)


@drule("slop/numbered-section-labels")
def numbered_labels(cx: Ctx):
    d = cx.wide
    hits = []
    for h in d.headings(1, 2, 3):
        for e in d.els:
            if e.tl and e.tl <= 40 and e.fs <= 18 and e.bottom <= h.y + 2 and h.y - e.bottom <= 80 and _NUMBERED.match(e.text or "") and abs(e.x - h.x) < 80:
                hits.append(short(e.text, 30))
                break
    if len(hits) >= 2:
        return [F("slop/numbered-section-labels", f"{len(hits)} section headings preceded by a small number label.", hits[:8])]


@drule("slop/oversized-h1")
def oversized_h1(cx: Ctx):
    hits = []
    for d in cx.all:
        for h in d.headings(1):
            if not d.first_screen(h):
                continue
            if d.width >= 1000 and (h.h > d.vh * 0.58 or h.fs > 150):
                hits.append(f"{d.width}px: {h.fs:g}px type, {h.h}px tall of {d.vh}px")
            elif d.width < 700 and h.d.get("ln", 0) >= 6:
                hits.append(f"{d.width}px: {h.d.get('ln')} lines")
    if hits:
        return [F("slop/oversized-h1", "The hero headline crowds the first screen.", uniq(hits)[:4])]


@drule("slop/extreme-negative-tracking")
def extreme_tracking(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.text_els():
        em = e.ls_em
        limit = -0.09 if e.fs >= 40 else -0.07
        if em < limit and e.tl >= 3:
            hits.append(f"{e.snippet(28)} {em:.3f}em")
    if hits:
        return [F("slop/extreme-negative-tracking", f"{len(hits)} text element(s) tracked tighter than the letters can bear.", hits[:6])]


@drule("slop/empty-picture")
def empty_picture(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.els:
        if e.w < 300 or e.h < 200 or e.w * e.h < 80000 or not e.gradient or e.tag in ("body", "html", "main"):
            continue
        if e.h >= d.page_height * 0.9 or e.deep_text_len() > 0:
            continue
        if any(c.tag in ("img", "video", "svg", "canvas", "picture", "iframe") for c in e.descendants()):
            continue
        hits.append(f"{e.label()} {e.w}x{e.h}")
    if hits:
        return [F("slop/empty-picture", f"{len(hits)} large block(s) showing only a gradient.", hits[:5])]


@drule("slop/counting-device")
def counting_device(cx: Ctx):
    d = cx.wide
    seen = set()
    for e in d.els:
        if e.i in seen or len(e.children) < 24:
            continue
        kids = [c for c in e.children if c.tl == 0 and not c.children and 0 < c.w <= 48 and 0 < c.h <= 64]
        by: dict[tuple, int] = {}
        for c in kids:
            by[(c.tag, c.w // 2, c.h // 2)] = by.get((c.tag, c.w // 2, c.h // 2), 0) + 1
        if by and max(by.values()) >= 24:
            seen.add(e.i)
            return [F("slop/counting-device", f"{max(by.values())} identical marks standing for a quantity in {e.label()}.", e.label())]


@drule("slop/photo-wall")
def photo_wall(cx: Ctx):
    d = cx.wide
    below = [e for e in d.tags("img", "picture", "video") if e.y >= d.vh and e.w >= 80]
    area = sum(e.w * e.h for e in below)
    room = max(1, d.page_width * max(1, d.page_height - d.vh))
    if len(below) >= 4 and area / room > 0.34:
        return [F("slop/photo-wall", f"Photographs cover {round(100 * area / room)}% of the page below the hero ({len(below)} images).", {"images": len(below), "share": round(area / room, 2)})]


@drule("slop/stock-close")
def stock_close(cx: Ctx):
    d = cx.wide
    secs = d.sections()
    footer = next((e for e in d.els if e.tag == "footer" and e.w >= d.width * 0.8), None)
    if len(secs) < 3:
        return []
    cands = [s for s in secs if s.tag != "footer" and (footer is None or s.bottom <= footer.y + 4)]
    if not cands:
        return []
    last = cands[-1]
    has_email = any(c.d.get("ctl") == "email" for c in last.descendants())
    if not has_email:
        return []
    h1 = next((h.text for h in d.headings(1) if h.text), "")
    if re.search(r"newsletter|subscri|waitlist|mailing|boletín|suscr|lista de espera|notify|beta|early access|acceso anticipado", h1, re.I):
        return []
    return [F("slop/stock-close", "The last section is an e-mail sign-up on a page that is not about a mailing list.", last.label())]


# ---------------------------------------------------------------------------
# slop: the feature-card template
# ---------------------------------------------------------------------------

@drule("slop/nested-cards")
def nested_cards(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.els:
        if not e.is_card or not (e.s.get("sh") or any(b > 0 for b in e.borders)):
            continue
        for inner in e.descendants():
            if inner.is_card and (inner.s.get("sh") or any(b > 0 for b in inner.borders)) and inner.w <= e.w - 8 and inner.w >= 100 and inner.h >= 50 \
                    and inner.tag not in ("button", "a", "input", "select", "textarea") and inner.deep_text_len() > 0:
                hits.append(f"{inner.label()} in {e.label()}")
                break
    hits = uniq(hits)
    if hits:
        return [F("slop/nested-cards", f"{len(hits)} card(s) inside another card.", hits[:6])]


@drule("slop/icon-tile-stack")
def icon_tile_stack(cx: Ctx):
    d = cx.wide
    hits = []
    for t in d.els:
        if not (32 <= t.w <= 128 and 32 <= t.h <= 128 and 0.7 <= t.w / t.h <= 1.4 and t.radius >= 6 and (t.bg or t.gradient)):
            continue
        marks = [c for c in t.descendants() if c.tag in ("svg", "img", "i")] or ([t] if 0 < t.tl <= 3 else [])
        if not marks and not (t.tl and t.tl <= 3):
            continue
        parent = t.parent
        if not parent:
            continue
        below = [h for h in parent.descendants() if h is not t and h.y >= t.bottom - 2 and h.y - t.bottom <= 56 and abs(h.x - t.x) <= 24
                 and (h.tag in ("h2", "h3", "h4", "h5", "strong") or h.fw >= 600) and h.tl > 0]
        if below:
            hits.append(f"{t.label()} {t.w}x{t.h} at {t.x},{t.y} over {short(below[0].text, 24)}")
    if len(hits) >= 3:
        return [F("slop/icon-tile-stack", f"{len(hits)} tinted icon tiles stacked above headings.", hits[:6])]


# ---------------------------------------------------------------------------
# quality
# ---------------------------------------------------------------------------

_PLACEHOLDER_HOSTS = re.compile(r"placehold\.(?:co|it)|via\.placeholder|picsum\.photos|placekitten|dummyimage|lorempixel|fakeimg|placeimg|loremflickr|source\.unsplash\.com", re.I)


@drule("quality/broken-image")
def broken_image(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.tags("img"):
        info = e.d.get("img") or {}
        src = info.get("src") or ""
        if not src:
            hits.append(f"{e.label()}: no src")
        elif _PLACEHOLDER_HOSTS.search(src):
            hits.append(f"{e.label()}: placeholder service")
        elif info.get("done") and not info.get("ok") and not src.startswith("data:image/svg"):
            hits.append(f"{e.label()}: did not load ({short(src, 50)})")
    hits = uniq(hits)
    if hits:
        return [F("quality/broken-image", f"{len(hits)} image(s) did not load or stand in for a picture.", hits[:6])]


@drule("quality/script-error")
def script_error(cx: Ctx):
    errs = [str(x) for x in (cx.probe.get("script_errors") or []) if x]
    if errs:
        return [F("quality/script-error", f"{len(errs)} uncaught error(s) while the page loaded.", [short(x, 140) for x in errs[:4]])]


_HIDDEN_OK = re.compile(r"tooltip|modal|dropdown|menu|popover|overlay|drawer|sr-only|visually-hidden|screen-reader|skip|toast|hidden|collapse|accordion|tab-?panel|carousel|slide|cursor|loader|spinner|preloader|splash|lightbox|dialog", re.I)


@drule("quality/content-hidden-at-rest")
def hidden_at_rest(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.els:
        if e.w < 40 or e.h < 10 or not d.first_screen(e):
            continue
        invisible = (e.st("op", 1) < 0.05) or e.st("vis") == "hidden"
        if not invisible or e.deep_text_len() < 12 or e.tag in ("option", "dialog", "details", "summary", "template"):
            continue
        chain = [e, *e.ancestors()]
        if any(_HIDDEN_OK.search(a.cls or "") for a in chain) or any(a.tag in ("dialog", "nav", "details") for a in chain):
            continue
        if any(a.st("op", 1) < 0.05 and a is not e for a in e.ancestors()):
            continue
        hits.append(f"{e.snippet(36)} ({'opacity 0' if e.st('op', 1) < 0.05 else 'visibility hidden'})")
    hits = uniq(hits)
    if hits:
        return [F("quality/content-hidden-at-rest", f"{len(hits)} text block(s) in the first screen painted invisible once the page settled.", hits[:6])]


@drule("quality/edge-flush-cards")
def edge_flush_cards(cx: Ctx):
    hits = []
    for d in cx.all:
        for e in d.els:
            if e.st("ovx") not in ("auto", "scroll") or len(e.children) < 3:
                continue
            kids = [c for c in e.children if c.w > 60 and c.h > 40]
            if len(kids) < 3 or max(c.right for c in kids) <= e.right + 2:
                continue  # not actually scrolling
            first = min(kids, key=lambda c: c.x)
            cards = sum(1 for c in kids if c.is_card)
            flush_view = first.x <= 1
            flush_scroller = first.x - e.x < 1 and e.pad[3] == 0 and e.has_box
            if cards >= 2 and (flush_view or flush_scroller):
                hits.append(f"{d.width}px: {e.label()} ({len(kids)} cards)")
    if hits:
        return [F("quality/edge-flush-cards", "Cards in a scrolling row touch the edge with no padding.", uniq(hits)[:4])]


@drule("quality/text-occlusion")
def text_occlusion(cx: Ctx):
    hits = []
    for d in cx.all:
        for o in d.occluded:
            hits.append(f"{d.width}px: {o.get('el')} under {o.get('by')}")
    if hits:
        return [F("quality/text-occlusion", f"{len(hits)} line(s) of text covered by an opaque element in the first screen.", uniq(hits)[:6])]


@drule("quality/first-viewport-column-overflow")
def column_overflow(cx: Ctx):
    d = cx.desktop
    if not d:
        return []
    hits = []
    for p in d.els:
        if p.y >= d.vh or len(p.children) < 2 or p.w < d.width * 0.6:
            continue
        cols = [c for c in p.children if c.w >= 160 and c.h >= 80]
        if len(cols) < 2:
            continue
        top = min(c.y for c in cols)
        row = [c for c in cols if abs(c.y - top) <= 24]
        if len(row) < 2 or len({c.x // 40 for c in row}) < len(row):
            continue
        tall, short_ = max(row, key=lambda c: c.bottom), min(row, key=lambda c: c.bottom)
        if tall.bottom > d.vh + 300 and short_.bottom <= d.vh and tall.h >= short_.h * 2:
            hits.append(f"{p.label()}: {tall.label()} runs to {tall.bottom}px, {short_.label()} ends at {short_.bottom}px")
    if hits:
        return [F("quality/first-viewport-column-overflow", "Side-by-side columns where one runs far past the fold and its neighbour ends early.", hits[:3])]


@drule("quality/gray-on-color")
def gray_on_color(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.text_els():
        ink = e.ink
        if not ink or ink[3] < 0.5 or spread(ink) > 22 or not (0.2 < hsl_of(ink)[2] < 0.8) or e.fs < 11:
            continue
        bg = e.eff_bg()
        h, s, l = hsl_of(bg)
        if spread(bg) >= 70 and s >= 0.45 and 0.15 < l < 0.85:
            hits.append(f"{e.snippet(30)} on rgb({int(bg[0])},{int(bg[1])},{int(bg[2])})")
    hits = uniq(hits)
    if hits:
        return [F("quality/gray-on-color", f"{len(hits)} gray text run(s) on a saturated surface.", hits[:6])]


_NO_PAD = {"td", "th", "tr", "li", "option", "table", "tbody", "thead", "body", "html", "label"}


@drule("quality/cramped-padding")
def cramped_padding(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.els:
        if e.tl < 2 or e.tag in _NO_PAD or e.st("disp") in ("inline", "contents") or e.w < 24 or not e.has_box:
            continue
        if e.bg is None and not any(b > 0 for b in e.borders):
            continue
        need = max(8, 0.5 * e.fs)
        bw = e.borders
        left, right = e.pad[3] + bw[3], e.pad[1] + bw[1]
        if min(left, right) < need - 0.5 and e.w < d.width * 0.9:
            hits.append(f"{e.snippet(24)} pad {left:g}/{right:g}px < {need:g}px")
    hits = uniq(hits)
    if hits:
        return [F("quality/cramped-padding", f"{len(hits)} filled or bordered box(es) with text closer than max(8px, 0.5em) to the side.", hits[:6])]




@drule("quality/body-text-viewport-edge")
def viewport_edge(cx: Ctx):
    d = cx.narrow or (cx.wide if cx.wide and cx.wide.width <= 500 else None)
    if not d or d.width > 500:
        return []
    hits = []
    for e in d.tags("p", "li", "blockquote", "dd"):
        if e.tl >= 30 and (e.x < 8 or e.right > d.width - 8) and e.w > 40 and not e.has_box:
            hits.append(f"{e.snippet(30)} at {e.x}px, ends {d.width - e.right}px from the edge")
    if hits:
        return [F("quality/body-text-viewport-edge", f"{len(hits)} paragraph(s) within 8px of the screen edge at {d.width}px.", hits[:5])]


def _running(e: El) -> bool:
    return e.tl >= 50 and e.tag in ("p", "li", "div", "span", "dd", "blockquote", "td", "article") and e.d.get("ln", 0) >= 2


@drule("quality/tight-leading")
def tight_leading(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.text_els():
        if _running(e) and e.lh and e.fs <= 26 and e.lh / e.fs < 1.3 - 1e-6:
            hits.append(f"{e.snippet(28)} line-height {e.lh / e.fs:.2f}")
    if hits:
        return [F("quality/tight-leading", f"{len(hits)} block(s) of running text leaded under 1.3.", uniq(hits)[:6])]


@drule("quality/heading-rhythm")
def heading_rhythm(cx: Ctx):
    d = cx.wide
    hits = []
    for h in d.headings(2, 3, 4):
        p = h.parent
        if not p:
            continue
        sib = p.children
        k = sib.index(h)
        if k == 0 or k == len(sib) - 1:
            continue
        prev, nxt = sib[k - 1], sib[k + 1]
        above, below = h.y - prev.bottom, nxt.y - h.bottom
        if prev.deep_text_len() and nxt.deep_text_len() and below >= 8 and 0 <= above < below - 3 and prev.h < 400:
            hits.append(f"{h.snippet(28)} {above}px above, {below}px below")
    if len(hits) >= 2 or (hits and len(d.headings(2, 3, 4)) <= 3):
        return [F("quality/heading-rhythm", f"{len(hits)} heading(s) nearer what precedes them than what they head.", hits[:5])]


@drule("quality/straggler")
def straggler(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.tags("p", "li", "blockquote", "dd"):
        last = e.d.get("last")
        if e.tl >= 60 and e.d.get("ln", 0) >= 3 and last is not None and 0 < last <= e.fs * 3.2 and e.st("tw") not in ("balance", "pretty"):
            hits.append(f"{e.snippet(28)} last line {last}px")
    if hits:
        return [F("quality/straggler", f"{len(hits)} paragraph(s) end on a single short word.", hits[:6])]


@drule("quality/unbalanced-heading")
def unbalanced_heading(cx: Ctx):
    d = cx.wide
    hits = []
    for h in d.headings(1, 2, 3):
        last, ln = h.d.get("last"), h.d.get("ln", 0)
        if 2 <= ln <= 3 and last is not None and last < h.w * 0.2 and h.st("tw") not in ("balance", "pretty") and h.tl >= 16:
            hits.append(f"{h.snippet(32)} last line {last}px of {h.w}px")
    if hits:
        return [F("quality/unbalanced-heading", f"{len(hits)} heading(s) leave a stub on the last line.", hits[:5])]


@drule("quality/tiny-text")
def tiny_text(cx: Ctx):
    hits = []
    for d in cx.all[:1]:
        for e in d.text_els():
            if e.tl >= 20 and e.fs < 12 and e.tag not in ("sup", "sub", "small", "label", "button", "a") and e.st("tt") != "uppercase":
                hits.append(f"{e.snippet(28)} {e.fs:g}px")
    if hits:
        return [F("quality/tiny-text", f"{len(hits)} run(s) of text under 12px.", uniq(hits)[:6])]


@drule("quality/undersized-ui-text")
def undersized_ui_text(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.els:
        if (e.tag in ("button", "a", "label", "input", "select") or e.d.get("act") or e.d.get("ctl")) and e.tl and e.fs < 11:
            hits.append(f"{e.snippet(24)} {e.fs:g}px")
    if hits:
        return [F("quality/undersized-ui-text", f"{len(hits)} control(s) with text under 11px.", uniq(hits)[:6])]


@drule("quality/all-caps-body")
def all_caps_body(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.text_els():
        letters = re.sub(r"[^A-Za-zÁÉÍÓÚÑÜáéíóúñü]", "", e.text or "")
        caps = e.st("tt") == "uppercase" or (len(letters) >= 40 and letters.isupper())
        if caps and e.tl >= 70 and e.d.get("ln", 0) >= 2 and e.tag not in ("h1", "h2", "h3", "h4", "button", "a", "th"):
            hits.append(e.snippet(30))
    if hits:
        return [F("quality/all-caps-body", f"{len(hits)} block(s) of running text set in capitals.", hits[:5])]


@drule("quality/wide-tracking")
def wide_tracking(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.text_els():
        if _running(e) and e.ls_em > 0.05 and e.st("tt") != "uppercase":
            hits.append(f"{e.snippet(28)} {e.ls_em:.2f}em")
    if hits:
        return [F("quality/wide-tracking", f"{len(hits)} block(s) of running text tracked past 0.05em.", hits[:6])]


@drule("quality/repeated-container-text")
def repeated_text(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.els:
        if e.tag in ("ul", "ol", "table", "tbody", "nav", "select", "datalist", "svg"):
            continue
        texts = [re.sub(r"\s+", " ", c.text.strip().lower()) for c in e.children if c.tl >= 10 and c.text]
        if any(a.tag in ("ul", "ol") for a in [e, *e.ancestors()]):
            continue
        dup = [t for t in set(texts) if texts.count(t) >= 2]
        if dup:
            hits.append(f"{e.label()}: “{short(dup[0], 40)}”")
    hits = uniq(hits)
    if hits:
        return [F("quality/repeated-container-text", f"{len(hits)} container(s) saying the same line twice.", hits[:5])]


@drule("quality/clipped-overflow-container")
def clipped_overflow(cx: Ctx):
    d = cx.wide
    hits = []
    for e in d.els:
        if e.st("pos") != "absolute" or not e.parent or e.w < 4 or e.h < 4:
            continue
        p = e.parent
        if p.st("ovx", "visible") == "visible" and p.st("ovy", "visible") == "visible":
            continue
        if p.w >= d.width * 0.9 and p.h >= 300:
            continue  # a full-bleed stage: its decoration is meant to bleed
        cut = (e.x < p.x - 1 or e.right > p.right + 1 or e.y < p.y - 1 or e.bottom > p.bottom + 1)
        if cut and (e.tl or e.w <= 160):
            hits.append(f"{e.snippet(24)} in {p.label()}")
    hits = uniq(hits)
    if hits:
        return [F("quality/clipped-overflow-container", f"{len(hits)} positioned child(ren) cut by the overflow of their parent.", hits[:6])]


# ---------------------------------------------------------------------------
# craft
# ---------------------------------------------------------------------------

def _content_gap(a: El, b: El) -> int:
    """The visual gap between two stacked bands: what separates their content (their padding and the space between them)."""
    return (b.y + b.pad[0]) - (a.bottom - a.pad[2])


@drule("craft/section-gaps")
def section_gaps(cx: Ctx):
    d = cx.desktop
    if not d:
        return []
    secs = [s for s in d.sections() if s.tag != "footer"]
    if len(secs) < 3:
        return []
    gaps = [_content_gap(a, b) for a, b in zip(secs, secs[1:]) if b.y >= a.bottom - 2]
    if len(gaps) < 2:
        return []
    out = []
    low = [g for g in gaps if g < 120]
    if len(low) > len(gaps) / 2:
        out.append(f"{len(low)} of {len(gaps)} gaps under 120px (median {int(statistics.median(gaps))}px)")
    if len(gaps) >= 4 and max(gaps) - min(gaps) <= 1:
        out.append(f"every gap is {gaps[0]}px")
    if out:
        return [F("craft/section-gaps", "; ".join(out) + " at " + str(d.width) + "px.", gaps[:10])]


def _has_visual(s: El) -> bool:
    return any((c.tag in ("img", "video", "canvas", "picture", "iframe") or (c.tag == "svg" and c.w >= 120 and c.h >= 80)) and c.w >= 150 and c.h >= 80 for c in s.descendants())


def _has_set(s: El) -> bool:
    for p in [s, *s.descendants()]:
        kids = [c for c in p.children if c.deep_text_len() > 0 and c.w >= 100 and c.h >= 40]
        if len(kids) >= 3 and len({c.y // 30 for c in kids}) <= 2:
            return True  # a row of three (or more) peers
        if len(kids) >= 3 and len({c.x // 30 for c in kids}) <= 1 and sum(1 for c in kids if c.tag in ("li", "tr", "details", "article", "div")) >= 3:
            return True  # a list of rows
    return False


def _has_statement(s: El) -> bool:
    return any(e.fs >= 30 and e.tl >= 40 for e in s.descendants()) or (s.tl >= 40 and s.fs >= 30)


@drule("craft/thin-section")
def thin_section(cx: Ctx):
    d = cx.desktop or cx.wide
    secs = [s for s in d.sections() if s.tag != "footer"]
    if len(secs) < 3:
        return []
    hits = []
    for s in secs[1:]:
        if s.deep_text_len() == 0 and not _has_visual(s):
            continue
        if not (_has_visual(s) or _has_set(s) or _has_statement(s)):
            hits.append(f"{s.snippet(36)} {s.h}px tall")
    if hits:
        return [F("craft/thin-section", f"{len(hits)} section(s) below the hero with no mass.", hits[:5])]


@drule("craft/small-section-heads")
def small_section_heads(cx: Ctx):
    d = cx.desktop
    if not d:
        return []
    sizes = []
    for s in d.sections()[1:]:
        hs = [h for h in s.descendants() if h.tag in ("h1", "h2", "h3") and h.tl]
        if hs:
            sizes.append(max(h.fs for h in hs[:2]))
    if len(sizes) >= 3 and statistics.median(sizes) < 40:
        return [F("craft/small-section-heads", f"The median section heading is {statistics.median(sizes):g}px at {d.width}px.", sizes[:8])]


@drule("craft/dead-band")
def dead_band(cx: Ctx):
    d = cx.desktop
    if not d:
        return []
    secs = d.sections()
    if not secs:
        return []
    hero = secs[0]
    if hero.bottom < d.vh - 20:
        return []
    inner = [e for e in hero.descendants() if (e.tl or e.tag in ("img", "svg", "video", "canvas", "button", "a")) and e.h > 0 and e.y < d.vh * 1.5 and e.bottom <= hero.bottom]
    if not inner:
        return []
    low = max(e.bottom for e in inner)
    if low < d.vh and d.vh - low > 160 and hero.bottom >= d.vh:
        return [F("craft/dead-band", f"{d.vh - low}px of nothing between the hero's lowest content ({low}px) and the fold ({d.vh}px).", {"lowest": low, "fold": d.vh})]


@drule("craft/screen-budget")
def screen_budget(cx: Ctx):
    d = cx.desktop
    if not d:
        return []
    out = []
    spans = [(e.y, e.d.get("tl", 0)) for e in d.els if e.tl and e.text]
    words = [(y, len(re.findall(r"\S+", t))) for y, t in ((e.y, e.text) for e in d.els if e.tl and e.text)]
    worst, at = 0, 0
    for start in range(0, max(1, d.page_height - 400), 150):
        total = sum(n for y, n in words if start <= y < start + 900)
        if total > worst:
            worst, at = total, start
    if worst > 100:
        out.append(f"{worst} words in the 900px window at {at}px")
    secs = d.sections()
    if secs:
        hero = secs[0]
        acts = [e for e in hero.descendants() if e.tag in ("button", "a") and (e.bg or e.has_box) and e.h >= 28]
        stop = min((e.y for e in acts), default=hero.bottom)
        blocks = [e for e in hero.descendants() if e.tl >= 25 and e.bottom <= stop + 1 and e.tag in ("h1", "h2", "p", "div", "span")]
        if len(blocks) > 2:
            out.append(f"{len(blocks)} text blocks before the hero's actions")
    if out:
        return [F("craft/screen-budget", "; ".join(out) + ".", out)]


@drule("craft/button-wrap")
def button_wrap(cx: Ctx):
    hits = []
    for d in cx.all:
        for e in d.els:
            if not e.tl or e.d.get("ln", 0) < 2 or e.tl > 40:
                continue
            is_button = e.tag == "button" or (e.tag == "a" and e.has_box and e.h < 90) or e.d.get("ctl") in ("submit", "button")
            is_nav = e.tag == "a" and e.in_tag("nav", "header") and d.width >= 1000
            if is_button or is_nav:
                hits.append(f"{d.width}px: {e.snippet(28)}")
    hits = uniq(hits)
    if hits:
        return [F("craft/button-wrap", f"{len(hits)} button or nav label(s) wrap onto two lines.", hits[:6])]


@drule("craft/font-weights")
def font_weights(cx: Ctx):
    d = cx.wide
    counts: dict[int, int] = {}
    for e in d.text_els():
        if e.tl >= 3:
            counts[e.fw] = counts.get(e.fw, 0) + 1
    used = sorted(w for w, c in counts.items() if c >= 2)
    if len(used) > 3:
        return [F("craft/font-weights", f"{len(used)} font weights in use: {', '.join(map(str, used))}.", used)]


@drule("craft/orphan-grid-item")
def orphan_grid_item(cx: Ctx):
    hits = []
    for d in cx.all:
        for p in d.els:
            if len(p.children) < 4 or not (str(p.st("disp", "")).endswith("grid") or p.st("fwrap") == "wrap"):
                continue
            kids = [c for c in p.children if c.w > 40 and c.h > 30]
            if len(kids) < 4:
                continue
            rows: dict[int, list[El]] = {}
            for c in kids:
                rows.setdefault(round(c.y / 20), []).append(c)
            ordered = [rows[k] for k in sorted(rows)]
            if len(ordered) >= 2 and len(ordered[-1]) == 1 and len(ordered[-2]) >= 3 and len(ordered[0]) >= 3:
                hits.append(f"{d.width}px: {p.label()} {'+'.join(str(len(r)) for r in ordered)}")
    if hits:
        return [F("craft/orphan-grid-item", "A grid leaves one item alone under a fuller row.", uniq(hits)[:4])]


@drule("craft/hero-fold")
def hero_fold(cx: Ctx):
    d = cx.desktop
    if not d or d.vh < 600:
        return []
    h1s = d.headings(1)
    if not h1s:
        return []
    h1 = h1s[0]
    out = []
    if h1.y + h1.h * 0.5 > d.vh:
        out.append(f"the headline starts at {h1.y}px, below the {d.vh}px fold")
    secs = d.sections()
    if secs:
        acts = [e for e in secs[0].descendants() if e.tag in ("button", "a") and (e.bg or e.has_box) and e.h >= 28]
        if acts and min(e.y for e in acts) > d.vh:
            out.append(f"the primary action is at {min(e.y for e in acts)}px")
    if out:
        return [F("craft/hero-fold", "At " + f"{d.width}x{d.vh}: " + "; ".join(out) + ".", out)]


# ---------------------------------------------------------------------------
# design-system: the page against a tokens_get system
# ---------------------------------------------------------------------------

GENERIC_FAMILIES = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif", "ui-monospace", "ui-rounded",
                    "-apple-system", "blinkmacsystemfont", "emoji", "math", "fangsong", "inherit", "initial"}


def _flat_colors(value, out: list) -> None:
    from .pagesrc import parse_color
    if isinstance(value, dict):
        for v in value.values():
            _flat_colors(v, out)
    elif isinstance(value, str):
        c = parse_color(value)
        if c and c[3] > 0.5:
            out.append(c)


def _lab(c) -> tuple[float, float, float]:
    from .pagesrc import oklch_of
    import math
    L, ch, h = oklch_of(c)
    return L, ch * math.cos(math.radians(h)), ch * math.sin(math.radians(h))


def _dist(a, b) -> float:
    la, lb = _lab(a), _lab(b)
    return sum((x - y) ** 2 for x, y in zip(la, lb)) ** 0.5


def _px_of(value: str) -> Optional[float]:
    from .pagesrc import px
    return px(value)


def _clamp_at(value: str, vw: float) -> Optional[float]:
    m = re.match(r"clamp\(\s*([\d.]+)rem\s*,\s*([-\d.]+)rem\s*\+\s*([-\d.]+)vw\s*,\s*([\d.]+)rem\s*\)", value or "")
    if m:
        lo, base, slope, hi = (float(x) for x in m.groups())
        return max(lo, min(hi, base + slope * vw / 100)) * 16
    return _px_of(value)


def _tokens(cx: Ctx) -> Optional[dict]:
    t = cx.probe.get("design_system")
    if isinstance(t, dict) and isinstance(t.get("tokens"), dict):
        t = t["tokens"]
    return t if isinstance(t, dict) and t.get("color") else None


def _family_names(stack: str) -> list[str]:
    return [f.strip().strip("'\"").lower() for f in (stack or "").split(",") if f.strip()]


@drule("ds/font")
def ds_font(cx: Ctx):
    t = _tokens(cx)
    if not t:
        return []
    typo = t.get("typography") or {}
    allowed = set()
    for k in ("heading", "body", "mono"):
        allowed.update(_family_names(typo.get(k, "")))
    allowed |= GENERIC_FAMILIES
    counts: dict[str, int] = {}
    for e in cx.wide.text_els():
        if e.tl >= 3:
            counts[e.ff] = counts.get(e.ff, 0) + 1
    off = {f: n for f, n in counts.items() if f and f not in allowed and n >= 2}
    if off:
        return [F("ds/font", f"{len(off)} font family(ies) outside the system {t.get('name', '')!r}: {', '.join(sorted(off))}.",
                  {"off_system": off, "system": sorted(allowed - GENERIC_FAMILIES)})]


@drule("ds/color")
def ds_color(cx: Ctx):
    t = _tokens(cx)
    if not t:
        return []
    palette: list = []
    _flat_colors(t.get("color"), palette)
    for extra in ((255.0, 255.0, 255.0, 1.0), (0.0, 0.0, 0.0, 1.0)):
        palette.append(extra)
    from .pagesrc import parse_color, to_hex
    used: dict[str, int] = {}
    for e in cx.wide.els:
        for src in (e.ink if e.tl else None, e.bg, *(parse_color(c) for c in (e.s.get("bc") or [])[:1])):
            if src and src[3] > 0.5 and (spread(src) >= 18 or e.tl):
                used[to_hex(src)] = used.get(to_hex(src), 0) + 1
    off = []
    for hexv, n in used.items():
        c = parse_color(hexv)
        if n >= 2 and min(_dist(c, p) for p in palette) > 0.09:
            off.append((hexv, n))
    chromatic_off = [(h, n) for h, n in off if spread(parse_color(h)) >= 30]
    if len(chromatic_off) >= 2 or len(off) >= 4:
        return [F("ds/color", f"{len(off)} colour(s) far from every colour of the system {t.get('name', '')!r}.", [f"{h} x{n}" for h, n in sorted(off, key=lambda x: -x[1])[:8]])]


@drule("ds/radius")
def ds_radius(cx: Ctx):
    t = _tokens(cx)
    if not t:
        return []
    scale = {_px_of(str(v)) for v in (t.get("radius") or {}).values()} - {None}
    scale.add(0.0)
    d = cx.wide
    used: dict[float, int] = {}
    for e in d.els:
        r = e.radius
        if r <= 0 or e.w < 12 or e.h < 12:
            continue
        if r >= 999 or (abs(e.w - e.h) <= 2 and r >= min(e.w, e.h) / 2 - 1) or r >= min(e.w, e.h) / 2 - 0.5:
            continue  # a pill or a circle is the pill token whatever its size
        used[r] = used.get(r, 0) + 1
    off = {r: n for r, n in used.items() if all(abs(r - s) > 1.01 for s in scale)}
    if len(off) >= 2 or sum(off.values()) >= 4:
        return [F("ds/radius", f"{len(off)} corner radius(es) off the system scale ({', '.join(f'{s:g}px' for s in sorted(scale))}).",
                  {f"{r:g}px": n for r, n in sorted(off.items())})]


@drule("ds/scale")
def ds_scale(cx: Ctx):
    t = _tokens(cx)
    if not t:
        return []
    steps_def = (t.get("typography") or {}).get("scale") or {}
    d = cx.wide
    steps = sorted({round(v, 1) for v in (_clamp_at(s, d.width) for s in steps_def.values()) if v})
    if not steps:
        return []
    used: dict[float, int] = {}
    for e in d.text_els():
        if e.tl >= 3:
            used[round(e.fs, 1)] = used.get(round(e.fs, 1), 0) + 1
    off = {s: n for s, n in used.items() if all(abs(s - st) > 1.0 for st in steps)}
    if len(off) >= 3 or sum(off.values()) >= 8:
        return [F("ds/scale", f"{len(off)} font size(s) off the system type scale at {d.width}px ({', '.join(f'{s:g}' for s in steps)}).",
                  {f"{s:g}px": n for s, n in sorted(off.items())})]


@drule("ds/spacing")
def ds_spacing(cx: Ctx):
    t = _tokens(cx)
    if not t:
        return []
    scale = {v for v in (_px_of(str(x)) for x in (t.get("spacing") or {}).values()) if v is not None}
    scale.add(0.0)
    if len(scale) < 4:
        return []
    d = cx.wide
    used: dict[float, int] = {}
    for e in d.els:
        for v in [*e.pad, e.st("gap", 0)]:
            v = abs(float(v or 0))
            if 0 < v < 400:
                used[round(v, 1)] = used.get(round(v, 1), 0) + 1
    off = {v: n for v, n in used.items() if all(abs(v - s) > 1.01 for s in scale)}
    if used and len(off) >= 4 and sum(off.values()) / sum(used.values()) > 0.25:
        return [F("ds/spacing", f"{len(off)} padding/gap value(s) off the system spacing scale.", {f"{v:g}px": n for v, n in sorted(off.items())[:10]})]
