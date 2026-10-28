"""Static rules, part two: copy, type and craft gates. HTML and CSS text only; original implementations (see NOTICE)."""

from __future__ import annotations

import re
from typing import Callable

from .base import F, short, uniq
from .pagesrc import Page, has_source, hsl_of, colors_in, page_of, parse_color, parse_decls, prose, px
from .static_a import CHECKS, rule  # the registry of implementations is shared

HEADINGS = {"h1", "h2", "h3"}


def _heads(page: Page) -> list:
    return [n for n in page.nodes if n.tag in HEADINGS and n.text()]


# ---------------------------------------------------------------------------
# copy
# ---------------------------------------------------------------------------

def count_em_dashes(text: str) -> int:
    count = 0
    for run in re.findall(r"—+", text):
        count += 1 if len(run) == 2 else len(run)
    count += len(re.findall(r"(?<![-\w])--(?=\S)(?!-)", text))
    count += len(re.findall(r"(?<=\w)---(?=\w)", text))
    return count


@rule("slop/em-dash-overuse")
def em_dash_overuse(page: Page, probe):
    text = prose(page)
    n = count_em_dashes(text)
    if n >= 8 and len(text) <= n * 500:
        return [F("slop/em-dash-overuse", f"{n} em dashes in {len(text)} characters of copy.", n)]


_BUZZ = [
    r"\bseamless(?:ly)?\b", r"\brobust\b", r"\bempower(?:s|ing)?\b", r"\bsupercharge[sd]?\b", r"\bunleash(?:es|ed)?\b",
    r"\bunlock (?:the )?(?:power|potential|your)\b", r"\beffortless(?:ly)?\b", r"\bnext[- ]generation\b", r"\bworld[- ]class\b",
    r"\bbest[- ]in[- ]class\b", r"\bindustry[- ]leading\b", r"\bmission[- ]critical\b", r"\bfuture[- ]proof\b", r"\bcutting[- ]edge\b",
    r"\bgame[- ]chang(?:er|ing)\b", r"\brevolutioni[sz]e\b", r"\bleverage the power\b", r"\bharness the power\b",
    r"\bstreamline your\b", r"\btransform your business\b", r"\benterprise[- ]grade\b", r"\bdrive (?:growth|engagement|results)\b",
    r"\bsin fisuras\b", r"\bde vanguardia\b", r"\bl[ií]der del sector\b", r"\bsoluci[oó]n integral\b", r"\bllev(?:a|ar) (?:tu|su) \w+ al siguiente nivel\b",
    r"\bpotencia tu\b", r"\brevolucion(?:a|ar|ario|aria)\b", r"\bde clase mundial\b", r"\bsin esfuerzo\b", r"\bdesbloquea\b",
]
_BUZZ_RE = re.compile("|".join(_BUZZ), re.I)


@rule("slop/marketing-buzzword")
def marketing_buzzword(page: Page, probe):
    text = prose(page)
    hits = [m.group(0).lower() for m in _BUZZ_RE.finditer(text)]
    in_head = any(_BUZZ_RE.search(h.text()) for h in page.find("h1"))
    if len(hits) >= 2 or (hits and in_head):
        return [F("slop/marketing-buzzword", f"{len(hits)} buzzword phrase(s): {', '.join(sorted(set(hits))[:6])}.", sorted(set(hits))[:10])]


_NOT_A = re.compile(r"\bNot an? [a-z][^.!?]{1,40}[.!]\s+[A-Z][^.!?]{1,60}[.!]|\bNo es (?:un|una|solo|sólo|tan solo)\b[^.!?]{1,40}[.!]\s+Es [^.!?]{1,60}[.!]|\bNo (?:se trata de|hablamos de) [^.!?]{1,40}[.!]\s+(?:Se trata de|Hablamos de) [^.!?]{1,60}[.!]")
_REBUTTAL = re.compile(r"\b[A-Z][^.!?]{4,80}[.!]\s+(?:No|Just|Solo|Sólo|Sin)\s+[a-zA-Z][^.!?]{2,60}[.!]")


@rule("slop/aphoristic-cadence")
def aphoristic_cadence(page: Page, probe):
    text = prose(page)
    hits = [m.group(0) for m in _NOT_A.finditer(text)] + [m.group(0) for m in _REBUTTAL.finditer(text)]
    hits = uniq(hits)
    if len(hits) >= 3:
        return [F("slop/aphoristic-cadence", f"{len(hits)} rebuttal-cadence constructions.", [short(h, 90) for h in hits[:5]])]


_THEATER_HEADS = ("accessibility|accountability|agile|alignment|compliance|diversity|engagement|governance|growth|hiring|hygiene|innovation|"
                  "inclusion|kindness|leadership|metrics|privacy|process|productivity|quality|safety|security|strategy|sustainability|transparency|trust|wellness")
_THEATER = re.compile(rf"\b(?:{_THEATER_HEADS}) theat(?:er|re)\b|\bteatro (?:de(?:l| la)?|del) (?:seguridad|cumplimiento|innovaci[oó]n|productividad|calidad|crecimiento|transparencia|privacidad|sostenibilidad)\b", re.I)


@rule("slop/theater-slop-phrase")
def theater_phrase(page: Page, probe):
    hits = uniq([m.group(0).lower() for m in _THEATER.finditer(prose(page))])
    if hits:
        return [F("slop/theater-slop-phrase", f"'X theater' framing: {', '.join(hits[:4])}.", hits[:6])]


_STOCK_ACTIONS = {"learn more", "get started", "book a demo", "request a demo", "start free trial", "saber más", "más información", "empieza ahora",
                  "empezar ahora", "solicitar demo", "reserva una demo", "comienza ahora", "ver más"}
_FILLER = re.compile(r"\bBuilt for the modern\b|\bIn today'?s (?:fast[- ]paced|digital|ever[- ]changing|competitive|modern)\b|\bIn an era of\b|\bIn a world where\b|"
                     r"\bEn el (?:mundo|entorno) (?:actual|digital|de hoy)\b|\bEn la era (?:digital|actual)\b|\bquietly trusted by\b|\bPensado para el equipo moderno\b", re.I)
_PLACEHOLDER_NAMES = re.compile(r"\b(?:Jane|John) (?:Doe|Smith)\b|\bAcme(?: Inc| Corp)?\b|\bNexus\b|\bSarah Chen\b|\bMarcus Johnson\b|\bEmily Rodriguez\b|\bAlex Rivera\b|\bMaya Patel\b|\bJuan P[eé]rez\b", re.I)


@rule("slop/copy-tells")
def copy_tells(page: Page, probe):
    text = prose(page)
    ev = {}
    names = uniq([m.group(0) for m in _PLACEHOLDER_NAMES.finditer(text)])
    if names:
        ev["placeholder_names"] = names[:5]
    filler = uniq([m.group(0) for m in _FILLER.finditer(text)])
    if filler:
        ev["filler_openers"] = filler[:5]
    actions = [n.text().lower().strip(" →>") for n in page.nodes if n.tag in ("a", "button") and n.text()]
    stock = uniq([a for a in actions if a in _STOCK_ACTIONS])
    if len(stock) >= 2:
        ev["stock_actions"] = stock[:5]
    if ev:
        return [F("slop/copy-tells", "Copy that reads as written for no one in particular: " + "; ".join(f"{k.replace('_', ' ')}: {', '.join(v)}" for k, v in ev.items()) + ".", ev)]


@rule("slop/template-punctuation")
def template_punctuation(page: Page, probe):
    hits = []
    for n in page.nodes:
        own = n.own_text()
        if not own or n.tag in ("script", "style", "code", "pre"):
            continue
        if len(re.findall(r"\s[·•]\s", own)) >= 3:
            hits.append("dots: " + short(own, 60))
        if n.tag in ("a", "button") and re.search(r"(?:\s|^)[→➔➜⟶»]\s*$|\s->\s*$|\s→$", n.text()):
            hits.append("arrow: " + short(n.text(), 40))
        if re.match(r"^[●•◉○]\s+\S", own) and len(own) <= 40 and n.tag not in ("li",):
            hits.append("status dot: " + short(own, 40))
    hits = uniq(hits)
    if hits:
        return [F("slop/template-punctuation", f"{len(hits)} template punctuation habit(s).", hits[:8])]


_FACT = re.compile(r"(?:[€$£]\s?\d[\d.,]*|\d[\d.,]*\s?(?:€|EUR|USD|\$|£)|\b\d{1,2}[:.]\d{2}\s?(?:am|pm|h)?\b)", re.I)


@rule("slop/echo")
def echo(page: Page, probe):
    body = next((n for n in page.nodes if n.tag == "body"), page.root)
    holder = body
    kids = [c for c in holder.children if c.tag not in ("script", "style")]
    if len(kids) == 1 and kids[0].tag in ("main", "div") and len(kids[0].children) >= 3:
        holder = kids[0]
    blocks = [c for c in holder.children if c.tag not in ("script", "style", "link", "meta") and c.text()]
    if len(blocks) < 4:
        return []
    count: dict[str, int] = {}
    in_table: set[str] = set()
    for b in blocks:
        text = b.text()
        for t in b.descendants():
            if t.tag in ("table", "tbody", "tr", "td"):
                for m in _FACT.finditer(t.text()):
                    in_table.add(m.group(0).strip())
        for fact in set(m.group(0).strip() for m in _FACT.finditer(text)):
            count[fact] = count.get(fact, 0) + 1
    repeated = [f"{k} (x{v})" for k, v in count.items() if v >= 4 and k not in in_table]
    if repeated:
        return [F("slop/echo", f"One fact printed in four or more sections: {', '.join(repeated[:4])}.", repeated[:6])]


_SUCCESS = re.compile(r"(?:thanks|thank you|you'?re on the list|message sent|\bsent\b|reserved|subscribed|gracias|enviado|mensaje enviado|te avisaremos|¡?listo)", re.I)


@rule("slop/fake-send")
def fake_send(page: Page, probe):
    forms = page.find("form")
    if not forms:
        return []
    scripts = ["".join(t for _, t in s.chunks) for s in page.find("script")]
    prevents = [s for s in scripts if "preventDefault" in s]
    if not prevents:
        return []
    real = any(re.search(r"fetch\(|XMLHttpRequest|axios|\.post\(|sendBeacon|\$\.ajax|supabase|formspree", s) for s in prevents)
    unwired = [f for f in forms if (f.attrs.get("action", "") in ("", "#") and "data-endpoint" not in f.attrs) or ("data-endpoint" in f.attrs and not f.attrs["data-endpoint"].strip())]
    if not unwired or real:
        return []
    said = [s for s in prevents if _SUCCESS.search(s)] or ([True] if any(_SUCCESS.search(n.text()) for n in page.nodes if n.tag in ("div", "p", "span") and (n.attrs.get("hidden") is not None or re.search(r"success|thanks|sent|confirm", n.attrs.get("class", ""), re.I))) else [])
    if said:
        return [F("slop/fake-send", f"{len(unwired)} form(s) report success with no request behind them.", [f.label() for f in unwired[:4]])]


# ---------------------------------------------------------------------------
# type
# ---------------------------------------------------------------------------

def _inline_wrapped(h) -> list:
    out = []
    for c in h.children:
        if c.tag in ("span", "em", "mark", "strong", "b", "i", "u") and c.text():
            out.append(c)
    return out


@rule("slop/accented-word")
def accented_word(page: Page, probe):
    hits = []
    for h in _heads(page):
        total = len(h.text().split())
        if total < 3:
            continue
        for c in _inline_wrapped(h):
            words = c.text().split()
            if 1 <= len(words) <= 2 and len(words) < total:
                d = page.declared(c)
                styled = any(k in d for k in ("color", "font-weight", "background", "background-image", "text-decoration", "border-bottom", "font-style")) or c.tag in ("mark", "u") or bool(re.search(r"text-(?:\w+)-\d{2,3}|font-(?:bold|semibold)|bg-clip", c.attrs.get("class", "")))
                if styled:
                    hits.append(f"{h.tag}: …{short(c.text(), 24)}…")
    hits = uniq(hits)
    if hits:
        return [F("slop/accented-word", f"{len(hits)} heading(s) with one word set apart.", hits[:6])]


@rule("slop/italic-word-in-heading")
def italic_word(page: Page, probe):
    hits = []
    for h in _heads(page):
        total = len(h.text().split())
        for c in h.children:
            italic = c.tag in ("em", "i") or "italic" in page.declared(c).get("font-style", "") or "italic" in c.attrs.get("class", "")
            if italic and 1 <= len(c.text().split()) <= 1 and total >= 3 and c.text():
                hits.append(f"{h.tag}: {short(h.text(), 50)}")
    hits = uniq(hits)
    if hits:
        return [F("slop/italic-word-in-heading", f"{len(hits)} heading(s) with a single italic word.", hits[:6])]


_MONO = re.compile(r"mono|courier|consolas|menlo|jetbrains|fira code|source code|sf mono|plex mono|space mono|ui-monospace|dm mono|geist mono", re.I)
_LABELISH = re.compile(r"label|caption|eyebrow|kicker|meta|tag|badge|chip|small|\bth\b|date|overline|breadcrumb|nav|pill|subtitle|byline", re.I)
_CODEISH = re.compile(r"\bcode\b|\bpre\b|\bkbd\b|\bsamp\b|terminal|console|snippet|token|hljs|\.mono-?(?:code|block)|figure|metric|stat", re.I)


@rule("slop/mono-costume")
def mono_costume(page: Page, probe):
    body_ff = ""
    for r in page.rules:
        if r.selector.strip().lower() in ("body", "html", ":root"):
            body_ff = r.decls.get("font-family", body_ff)
    if _MONO.search(body_ff):
        return []
    for r in page.rules:
        if r.selector.strip().lower() in ("h1", "h2", ".display", ".hero h1", "h1, h2") and _MONO.search(r.decls.get("font-family", "")):
            return []
    hits = []
    for r in page.rules:
        ff = r.decls.get("font-family", "")
        if ff and _MONO.search(ff) and _LABELISH.search(r.selector) and not _CODEISH.search(r.selector):
            hits.append(r.selector)
    hits = uniq(hits)
    if hits:
        return [F("slop/mono-costume", f"{len(hits)} label/meta selector(s) set in monospace without code or data.", hits[:8])]


def _em(value: str):
    v = value.strip().lower()
    m = re.fullmatch(r"(-?[\d.]+)(em|rem)", v)
    if m:
        return float(m.group(1))
    p = px(v)
    return None if p is None else p / 16.0


_CAPS_SEL = re.compile(r"label|eyebrow|kicker|caption|\btag\b|chip|badge|meta|\bth\b|nav|overline|pill|breadcrumb|\bsmall\b|\.tag|\.pill|\.chip", re.I)
_BRANDISH = re.compile(r"logo|brand|wordmark|masthead", re.I)


@rule("slop/tracked-caps-label")
def tracked_caps(page: Page, probe):
    hits = []
    for r in page.rules:
        if not _CAPS_SEL.search(r.selector) or _BRANDISH.search(r.selector):
            continue
        d = r.decls
        caps = "uppercase" in d.get("text-transform", "") or "small-caps" in d.get("font-variant", "") or "small-caps" in d.get("font-variant-caps", "")
        ls = _em(d.get("letter-spacing", "")) if d.get("letter-spacing") else None
        fs = px(d.get("font-size"))
        small = fs is None or fs <= 15
        if small and (caps or (ls is not None and ls > 0.03)) and (caps and (ls is None or ls > 0.03) or (ls is not None and ls > 0.03)):
            hits.append(r.selector)
    for label, cls in [(n.label(), n.attrs.get("class", "")) for n in page.nodes if n.attrs.get("class")]:
        if re.search(r"\buppercase\b", cls) and re.search(r"\btracking-(?:wide|wider|widest)\b", cls) and re.search(r"\btext-(?:xs|sm)\b", cls):
            hits.append(label)
    hits = uniq(hits)
    if hits:
        return [F("slop/tracked-caps-label", f"{len(hits)} small uppercase / letter-spaced label style(s).", hits[:8])]


@rule("slop/monotonous-spacing")
def monotonous_spacing(page: Page, probe):
    vals = []
    for sel, prop, val in page.all_declarations():
        if re.fullmatch(r"(?:padding|margin)(?:-(?:top|right|bottom|left|inline|block)(?:-(?:start|end))?)?|gap|row-gap|column-gap", prop):
            for tok in re.findall(r"-?[\d.]+(?:px|rem)\b", val):
                v = px(tok)
                if v and 0 < v < 200:
                    vals.append(v)
    for n in page.nodes:
        for m in re.finditer(r"\b(?:p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|gap)-(\d+)\b", n.attrs.get("class", "")):
            vals.append(int(m.group(1)) * 4.0)
    if len(vals) < 10:
        return []
    rounded = [round(v / 4) * 4 for v in vals]
    counts: dict[float, int] = {}
    for v in rounded:
        counts[v] = counts.get(v, 0) + 1
    dominant, c = max(counts.items(), key=lambda kv: kv[1])
    unique = [v for v in counts if v > 0]
    if dominant != 0 and c / len(rounded) > 0.6 and len(unique) <= 3:
        return [F("slop/monotonous-spacing", f"~{dominant:g}px used {c}/{len(rounded)} times ({round(100 * c / len(rounded))}%).", {"dominant": dominant, "share": round(c / len(rounded), 2)})]


# ---------------------------------------------------------------------------
# craft gates
# ---------------------------------------------------------------------------

_HERO_SEL = re.compile(r"hero|banner|landing|intro|cover|splash|masthead|jumbotron|\.first|above-the-fold", re.I)


@rule("craft/hero-vh")
def hero_vh(page: Page, probe):
    hits = []
    for r in page.rules:
        for prop in ("height", "min-height", "max-height"):
            v = r.decls.get(prop, "")
            m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)vh\s*", v)
            if m and float(m.group(1)) >= 70 and _HERO_SEL.search(r.selector):
                hits.append(f"{r.selector}: {prop}: {v.strip()}")
    for n in page.nodes:
        st = n.attrs.get("style", "")
        if re.search(r"(?:min-)?height\s*:\s*(?:[789]\d|100)vh", st) and _HERO_SEL.search(n.label()):
            hits.append("inline:" + n.label())
        if re.search(r"\b(?:min-)?h-screen\b", n.attrs.get("class", "")) and _HERO_SEL.search(n.label()):
            hits.append(n.label() + " (h-screen)")
    hits = uniq(hits)
    if hits:
        return [F("craft/hero-vh", f"{len(hits)} hero/full-screen block(s) sized in vh.", hits[:6])]


_LAYOUT_PROPS = ("width", "height", "top", "left", "right", "bottom")


@rule("craft/transition-all")
def transition_all(page: Page, probe):
    hits = []
    for sel, prop, val in page.all_declarations():
        if prop in ("transition", "transition-property"):
            names = [re.split(r"\s+", part.strip())[0].lower() for part in val.split(",") if part.strip()] if prop == "transition" else [x.strip().lower() for x in val.split(",")]
            if "all" in names:
                hits.append(f"{sel}: transition all")
            elif any(n in _LAYOUT_PROPS for n in names):
                hits.append(f"{sel}: transition {','.join(n for n in names if n in _LAYOUT_PROPS)}")
    for name, frames in page.keyframes.items():
        for _, decls in frames:
            if any(k in decls for k in _LAYOUT_PROPS):
                hits.append(f"@keyframes {name}: animates {','.join(k for k in _LAYOUT_PROPS if k in decls)}")
                break
    for label, cls in [(n.label(), n.attrs.get("class", "")) for n in page.nodes if n.attrs.get("class")]:
        if re.search(r"\btransition-all\b", cls):
            hits.append(f"{label}: transition-all")
    hits = uniq(hits)
    if hits:
        return [F("craft/transition-all", f"{len(hits)} transition(s) on all properties or on layout properties.", hits[:8])]


@rule("craft/transition-layout-props")
def transition_layout(page: Page, probe):
    hits = []
    for sel, prop, val in page.all_declarations():
        if prop in ("transition", "transition-property"):
            names = [re.split(r"\s+", part.strip())[0].lower() for part in val.split(",") if part.strip()] if prop == "transition" else [x.strip().lower() for x in val.split(",")]
            if any(n.startswith(("margin", "padding")) for n in names):
                hits.append(sel)
    hits = uniq(hits)
    if hits:
        return [F("craft/transition-layout-props", f"{len(hits)} transition(s) on margin or padding.", hits[:8])]


@rule("craft/video-autoplay")
def video_autoplay(page: Page, probe):
    bad = [v for v in page.find("video") if "autoplay" in v.attrs and "muted" not in v.attrs]
    if bad:
        return [F("craft/video-autoplay", f"{len(bad)} <video autoplay> without muted.", [b.label() for b in bad[:4]])]


@rule("craft/decorative-svg-unlabeled")
def decorative_svg(page: Page, probe):
    bad = []
    for svg in page.find("svg"):
        a = svg.attrs
        if a.get("aria-hidden") == "true" or a.get("aria-label") or a.get("aria-labelledby") or a.get("role") in ("presentation", "none"):
            continue
        if any(d.tag == "title" and d.text() for d in svg.descendants()):
            continue
        bad.append(svg)
    if bad:
        return [F("craft/decorative-svg-unlabeled", f"{len(bad)} inline <svg> with neither aria-hidden nor a label.", [b.label() for b in bad[:6]])]


@rule("craft/grid-bare-fr")
def grid_bare_fr(page: Page, probe):
    if not (page.find("img") or page.find("video") or page.find("picture")):
        return []
    hits = []
    for r in page.rules:
        v = r.decls.get("grid-template-columns", "")
        if v and re.search(r"(?<![\w(,-])\d*\.?\d*fr\b", re.sub(r"minmax\([^)]*\)", "", v)):
            hits.append(f"{r.selector}: {v[:50]}")
    hits = uniq(hits)
    if hits:
        return [F("craft/grid-bare-fr", f"{len(hits)} grid(s) on bare fr tracks on a page with images.", hits[:6])]


@rule("craft/double-sticky")
def double_sticky(page: Page, probe):
    sel = []
    for r in page.rules:
        d = r.decls
        if d.get("position") == "sticky" and d.get("top", "").strip() in ("0", "0px"):
            sel.append(r.selector)
    for n in page.nodes:
        if re.search(r"\bsticky\b", n.attrs.get("class", "")) and re.search(r"\btop-0\b", n.attrs.get("class", "")):
            sel.append(n.label())
    sel = uniq(sel)
    if len(sel) >= 2:
        return [F("craft/double-sticky", f"{len(sel)} elements are sticky at top: 0.", sel[:6])]


@rule("craft/reveal-without-fallback")
def reveal_fallback(page: Page, probe):
    if "@starting-style" in page.css:
        return []
    used = set()
    for n in page.nodes:
        used.update(n.classes)
    hits = []
    for r in page.rules:
        d = r.decls
        hides = d.get("opacity", "").strip() == "0" or d.get("visibility", "").strip() == "hidden"
        if not hides or "animation" in d:
            continue
        sel = r.selector
        if re.search(r"(^|[\s>])(?:html)?\.js\b|\.js-|\.has-js|:not\(\.no-js\)", sel):
            continue
        names = re.findall(r"\.([\w-]+)", sel)
        if any(re.search(r"reveal|fade|aos|appear|scroll|animate|hidden-until|will-|in-view|inview|slide", c, re.I) for c in names) and any(c in used for c in names):
            if not re.search(r":hover|:focus|\.(?:open|show|visible|active|is-)", sel):
                hits.append(sel)
    hits = uniq(hits)
    if hits:
        return [F("craft/reveal-without-fallback", f"{len(hits)} reveal class(es) hide content until a script runs.", hits[:6])]


def _lh(value: str):
    v = value.strip().lower()
    if re.fullmatch(r"[\d.]+", v):
        return float(v)
    m = re.fullmatch(r"([\d.]+)(em|%)", v)
    if m:
        return float(m.group(1)) / (100 if m.group(2) == "%" else 1)
    return None


@rule("craft/uppercase-display-leading")
def uppercase_leading(page: Page, probe):
    hits = []
    for h in _heads(page):
        tt = page.style(h, "text-transform") or ""
        lh = page.style(h, "line-height")
        lv = _lh(lh) if lh else None
        if "uppercase" in tt and lv is not None and lv < 1.0 and len(h.text()) > 12:
            hits.append(f"{h.tag}: line-height {lh}")
    hits = uniq(hits)
    if hits:
        return [F("craft/uppercase-display-leading", f"{len(hits)} uppercase heading(s) leaded under 1.0.", hits[:6])]


@rule("craft/title-meta")
def title_meta(page: Page, probe):
    if not (page.find("html") or page.find("head")):
        return []
    missing = []
    title = next((n for n in page.find("title")), None)
    if not title or not title.own_text():
        missing.append("title")
    if not any(n.tag == "meta" and n.attrs.get("name", "").lower() == "description" and n.attrs.get("content", "").strip() for n in page.nodes):
        missing.append("meta description")
    if missing:
        return [F("craft/title-meta", "Missing " + " and ".join(missing) + ".", missing)]


@rule("craft/straight-quotes")
def straight_quotes(page: Page, probe):
    text = prose(page)
    n = len(re.findall(r"(?:(?<=\s)|^)\"[^\"\n]{2,}\"", text)) + len(re.findall(r"\w'\w", text))
    if n >= 3:
        return [F("craft/straight-quotes", f"{n} straight quote mark(s) in running text.", n)]


@rule("craft/three-dots")
def three_dots(page: Page, probe):
    n = len(re.findall(r"\.\.\.", prose(page)))
    if n >= 2:
        return [F("craft/three-dots", f"{n} '...' typed instead of an ellipsis.", n)]


@rule("craft/no-text-balance")
def no_text_balance(page: Page, probe):
    if re.search(r"text-wrap\s*:\s*(?:balance|pretty)|\btext-balance\b|\btext-pretty\b", page.css + page.html):
        return []
    big = []
    for h in page.find_any(("h1", "h2")):
        fs = px(page.style(h, "font-size"))
        if fs and fs >= 32:
            big.append(h)
        elif not fs and "clamp(" in (page.style(h, "font-size") or ""):
            big.append(h)
    if big:
        return [F("craft/no-text-balance", f"{len(big)} display heading(s) set without text-wrap: balance.", [b.label() for b in big[:4]])]


@rule("craft/tabular-figures")
def tabular_figures(page: Page, probe):
    if re.search(r"tabular-nums|tabular-figures|\btabular-nums\b", page.css + page.html):
        return []
    figs = []
    for n in page.nodes:
        t = n.own_text()
        if t and len(t) <= 14 and re.fullmatch(r"[\s\d.,%€$£+kKmMxX×/-]+", t):
            fs = px(page.style(n, "font-size")) or 0
            if fs >= 32 or re.search(r"stat|metric|kpi|counter|figure|number", n.attrs.get("class", ""), re.I):
                figs.append(n)
    cells = [c for c in page.find_any(("td",)) if re.fullmatch(r"[\s\d.,%€$£+-]+", c.text() or "x")]
    if len(figs) >= 2 or len(cells) >= 6:
        return [F("craft/tabular-figures", "Large figures or number columns without tabular numerals.", {"figures": len(figs), "cells": len(cells)})]
