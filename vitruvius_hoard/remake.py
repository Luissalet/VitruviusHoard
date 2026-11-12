"""Rehacer una web: from a reference page (a URL or a screenshot) to a project that matches it, round by round.

One background job per project (`RemakeRunner`):

1. Capture. The reference loads in the frozen browser of the parity check (`parity.FREEZE_JS`) at every width, twice, so the
   scoring has its noise mask. The first load at each width also keeps the page's layout (`OUTLINE_JS`: every visible text,
   image and box with its position, size, font, colours and selector), every stylesheet, image, font and plain video the page
   loaded, and at the first width a static snapshot of the rendered page (`SNAPSHOT_JS`). Pages behind a bot check and pages
   that show a sign-in or payment form are not remade.
2. First candidate. ``copy``: the rendered page itself, with its own CSS and files saved next to it, trackers and scripts
   removed (``keep_scripts`` keeps the original document and its scripts instead). ``rebuild``: the family's global model
   (through Faustus, as every other model call of Vitruvius) writes new hand-made HTML and CSS from the layout, the palette,
   the fonts, the downloaded images and pictures of the reference.
3. Score. The candidate is served from its folder and loaded the same frozen way; `parity.compare_widths_images` scores it
   against the cached reference loads screen by screen. Every round is kept as a normal parity run (Parity screen).
4. Repair. Files the candidate asked for and did not have are fetched first. Otherwise the first failing screen of each width
   goes to the model with the element-by-element differences (position, size, font, colour), the pictures of both screens and
   the current code; it answers with edits (copy mode: CSS rules appended last). A round that scores lower than the best one
   is undone. The loop stops when every screen passes, the rounds run out or several rounds bring nothing.
5. Deliver. ``site/`` always holds the best round: ``index.html`` and ``assets/``. ``assets.json`` says where every file came
   from and its licence, ``slots.json`` lists what still belongs to the original (texts, images, fonts, colours, links, forms),
   and the ZIP carries all of it with the per-round parity summary.
"""

from __future__ import annotations

import base64
import hashlib
import html as html_lib
import io
import json
import logging
import mimetypes
import posixpath
import re
import shutil
import threading
import time
import uuid
import zipfile
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import unquote, urljoin, urlsplit

from .hoard_link.atomic import write_json_atomic

log = logging.getLogger("vitruvius.remake")

MOUNT_ORIGIN = "https://remake.vitruvius.invalid"  # never resolves: the browser serves it from the project folder
DEFAULT_WIDTHS = [1440, 390]
MODES = ("copy", "rebuild")
MAX_ROUNDS = 20
STALE_ROUNDS = 3              # stop after this many rounds in a row without a better score
MAX_ASSET_BYTES = 20_000_000  # one file
MAX_TOTAL_BYTES = 200_000_000  # all files of one capture
MODEL_MAX_TOKENS = 32000
FIX_STYLE_ID = "vitruvius-remake-fixes"

TRACKERS = [
    "googletagmanager.com", "google-analytics.com", "analytics.google.com", "doubleclick.net", "googleadservices.com",
    "googlesyndication.com", "connect.facebook.net", "facebook.com/tr", "hotjar.com", "hotjar.io", "clarity.ms", "segment.com",
    "segment.io", "cdn.segment.com", "mixpanel.com", "amplitude.com", "heap.io", "heapanalytics.com", "fullstory.com",
    "snap.licdn.com", "px.ads.linkedin.com", "analytics.tiktok.com", "static.ads-twitter.com", "bat.bing.com",
    "consent.cookiebot.com", "consentcdn.cookiebot.com", "cdn.cookielaw.org", "onetrust.com", "plausible.io", "stats.wp.com",
    "pixel.wp.com", "js.hs-analytics.net", "js.hs-banner.com", "js.hsadspixel.net", "cdn.usefathom.com", "posthog.com",
    "sentry.io", "browser.sentry-cdn.com", "intercomcdn.com", "widget.intercom.io", "js.driftt.com", "static.zdassets.com",
    "vercel-insights.com", "va.vercel-scripts.com", "/_vercel/insights", "/_vercel/speed-insights",
]

_CHALLENGE = [re.compile(p, re.I) for p in (
    r"<title>\s*Just a moment\.\.\.\s*</title>", r"cf-browser-verification|challenge-platform|cf_chl_opt",
    r"<title>\s*Attention Required!", r"<title>\s*One moment, please\.\.\.\s*</title>", r"Vercel Security Checkpoint",
    r"<title>\s*Access denied\s*</title>", r"captcha-delivery\.com|geo\.captcha-delivery", r"px-captcha|perimeterx",
    r"Checking your browser before accessing", r"_Incapsula_Resource|incapsula", r"<title>\s*Verify you are human",
    r"sgcaptcha|sg-captcha")]

FREE_FONTS = re.compile(
    r"^(inter|roboto|open sans|lato|montserrat|poppins|source sans|source serif|source code|ibm plex|noto|work sans|dm sans|"
    r"dm serif|dm mono|manrope|space grotesk|space mono|raleway|nunito|rubik|karla|fira|jetbrains mono|playfair|merriweather|"
    r"lora|pt sans|pt serif|oswald|barlow|mulish|figtree|outfit|plus jakarta|urbanist|sora|lexend|archivo|public sans|"
    r"schibsted grotesk|fraunces|newsreader|geist|inter tight|libre|crimson|eb garamond|cormorant|bricolage|instrument|"
    r"onest|unbounded|syne|epilogue|be vietnam|red hat|overpass|heebo|assistant|cabin|quicksand|josefin|arimo|tinos|cousine|"
    r"ui-[a-z-]+|system-ui|-apple-system|blinkmacsystemfont|segoe ui|helvetica|arial|sans-serif|serif|monospace|georgia|times)", re.I)
SOCIAL = re.compile(r"(linkedin|instagram|twitter\.com|//x\.com|facebook|youtube|youtu\.be|tiktok|github|dribbble|behance|"
                    r"threads\.net|pinterest|vimeo|medium\.com|mastodon|bsky\.app|discord)", re.I)
BOOKING = re.compile(r"(calendly|cal\.com|savvycal|tidycal|meetings\.hubspot|zcal|acuityscheduling)", re.I)

EXT_FOR_TYPE = {
    "text/css": ".css", "text/javascript": ".js", "application/javascript": ".js", "application/x-javascript": ".js",
    "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "image/avif": ".avif",
    "image/svg+xml": ".svg", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico", "font/woff2": ".woff2",
    "font/woff": ".woff", "font/ttf": ".ttf", "font/otf": ".otf", "application/font-woff": ".woff",
    "application/font-woff2": ".woff2", "application/x-font-ttf": ".ttf", "video/mp4": ".mp4", "video/webm": ".webm",
    "application/json": ".json", "text/html": ".html",
}

# ---------------------------------------------------------------------------------------------------- in-page scripts

# The layout of the page as the model needs it: every visible text, image, media and coloured box, with position, size,
# font, colours and a short selector. Also the palette (weighted by text length and area), loaded fonts, links and forms.
OUTLINE_JS = r"""
() => {
  const MAX = 700;
  const hex = (c) => {
    const m = /rgba?\(([^)]+)\)/.exec(c || '');
    if (!m) return '';
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
    if (p.length > 3 && p[3] === 0) return '';
    let h = '#' + p.slice(0, 3).map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
    if (p.length > 3 && p[3] < 1) h += Math.round(p[3] * 255).toString(16).padStart(2, '0');
    return h;
  };
  const esc = (s) => (window.CSS && CSS.escape ? CSS.escape(s) : s.replace(/[^a-zA-Z0-9_-]/g, '\\$&'));
  const one = (el) => {
    if (el.id && !/^\d/.test(el.id) && el.id.length < 40) return '#' + esc(el.id);
    let s = el.tagName.toLowerCase();
    const cls = [...el.classList].filter((c) => c.length < 40 && !/^(is-|has-)?(active|visible|open|show|in-view|animated)$/.test(c)).slice(0, 2);
    if (cls.length) s += '.' + cls.map(esc).join('.');
    const parent = el.parentElement;
    if (parent) {
      const same = [...parent.children].filter((c) => c.tagName === el.tagName);
      if (same.length > 1) s += ':nth-of-type(' + (same.indexOf(el) + 1) + ')';
    }
    return s;
  };
  const sel = (el) => {
    const parts = [];
    let cur = el;
    while (cur && cur !== document.body && cur !== document.documentElement && parts.length < 4) {
      const p = one(cur);
      parts.unshift(p);
      if (p.startsWith('#')) break;
      cur = cur.parentElement;
    }
    return parts.join(' > ');
  };
  const direct = (el) => { let t = ''; for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent; return t.replace(/\s+/g, ' ').trim(); };
  const INLINE = new Set(['a', 'span', 'strong', 'em', 'b', 'i', 'small', 'code', 'label', 'sup', 'sub', 'u', 'mark', 'abbr', 'time', 'button']);
  const MEDIA = new Set(['img', 'svg', 'video', 'canvas', 'iframe', 'input', 'textarea', 'select', 'button', 'hr']);
  const LANDMARK = new Set(['header', 'nav', 'main', 'footer', 'section', 'article', 'aside', 'form']);
  const items = [];
  const sx = window.scrollX || 0, sy = window.scrollY || 0;
  const colours = new Map();
  const bump = (k, w) => { if (k) colours.set(k, (colours.get(k) || 0) + w); };
  const walk = (el, depth) => {
    if (items.length >= MAX) return;
    const tag = el.tagName.toLowerCase();
    if (['script', 'style', 'noscript', 'template', 'head', 'meta', 'link', 'title'].includes(tag)) return;
    let cs;
    try { cs = getComputedStyle(el); } catch (e) { return; }
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    const r = el.getBoundingClientRect();
    const text = direct(el);
    const bg = hex(cs.backgroundColor);
    const bi = cs.backgroundImage && cs.backgroundImage !== 'none' ? cs.backgroundImage : '';
    const bw = parseFloat(cs.borderTopWidth) || parseFloat(cs.borderBottomWidth) || parseFloat(cs.borderLeftWidth);
    const visible = r.width >= 1 && r.height >= 1 && parseFloat(cs.opacity) > 0;
    if (visible && (text || MEDIA.has(tag) || bg || bi || bw > 0 || /^h[1-6]$/.test(tag) || LANDMARK.has(tag))) {
      const it = { t: tag, s: sel(el), x: Math.round(r.left + sx), y: Math.round(r.top + sy), w: Math.round(r.width), h: Math.round(r.height), d: depth };
      if (text) {
        const full = (el.innerText || text).replace(/\s+/g, ' ').trim();
        it.tx = (INLINE.has(tag) || el.children.length === 0 ? full : text).slice(0, 160);
        it.f = cs.fontSize + ' ' + cs.fontWeight + ' ' + cs.fontFamily.split(',')[0].replace(/["']/g, '').trim() + (cs.fontStyle === 'italic' ? ' italic' : '');
        it.lh = cs.lineHeight;
        it.c = hex(cs.color);
        if (!['start', 'left'].includes(cs.textAlign)) it.ta = cs.textAlign;
        if (cs.letterSpacing !== 'normal' && cs.letterSpacing !== '0px') it.ls = cs.letterSpacing;
        if (cs.textTransform !== 'none') it.tt = cs.textTransform;
        bump(it.c, text.length);
      }
      if (bg) { it.bg = bg; bump(bg, (r.width * r.height) / 2000); }
      if (bi) it.bi = bi.slice(0, 240);
      if (bw > 0) it.bd = cs.borderTopWidth + ' ' + cs.borderTopStyle + ' ' + hex(cs.borderTopColor);
      if (parseFloat(cs.borderTopLeftRadius) > 0) it.br = cs.borderTopLeftRadius;
      if (cs.boxShadow && cs.boxShadow !== 'none') it.sh = cs.boxShadow.slice(0, 90);
      if (parseFloat(cs.opacity) < 1) it.op = cs.opacity;
      if (cs.filter && cs.filter !== 'none') it.fx = cs.filter.slice(0, 60);
      if (['flex', 'grid', 'inline-flex', 'inline-grid'].includes(cs.display)) it.ly = cs.display + (cs.flexDirection === 'column' ? ' column' : '') + (cs.gap && cs.gap !== 'normal' ? ' gap ' + cs.gap : '');
      if (['fixed', 'sticky', 'absolute'].includes(cs.position)) it.pos = cs.position;
      if (tag === 'img') { it.src = el.currentSrc || el.src; it.alt = el.alt || ''; it.nw = el.naturalWidth; it.nh = el.naturalHeight; if (cs.objectFit !== 'fill') it.fit = cs.objectFit; }
      if (tag === 'a') it.href = el.href;
      if (tag === 'video') { it.src = el.currentSrc || el.src; it.poster = el.poster || ''; }
      if (tag === 'iframe') it.src = el.src;
      items.push(it);
    }
    if (tag === 'svg') return;
    for (const c of el.children) walk(c, depth + 1);
  };
  if (document.body) walk(document.body, 0);
  const height = Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
  const pageBg = hex(getComputedStyle(document.body || document.documentElement).backgroundColor) || hex(getComputedStyle(document.documentElement).backgroundColor) || '#ffffff';
  const meta = {};
  for (const m of document.querySelectorAll('meta[name], meta[property]')) {
    const k = m.getAttribute('name') || m.getAttribute('property');
    if (/^(description|og:title|og:description|og:image|twitter:title|twitter:description|theme-color)$/i.test(k)) meta[k] = (m.content || '').slice(0, 300);
  }
  return {
    width: window.innerWidth, height, items, truncated: items.length >= MAX, page_bg: pageBg,
    palette: [...colours.entries()].sort((a, b) => b[1] - a[1]).slice(0, 16).map(([c, w]) => ({ c, w: Math.round(w) })),
    fonts: [...new Set([...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family.replace(/["']/g, '') + ' ' + f.weight + (f.style !== 'normal' ? ' ' + f.style : '')))].slice(0, 40),
    title: document.title, lang: document.documentElement.lang || '', meta,
    links: [...document.querySelectorAll('a[href]')].slice(0, 400).map((a) => ({ href: a.href, text: (a.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80), nav: !!a.closest('header, nav, [role=navigation]') })),
    forms: [...document.querySelectorAll('form')].slice(0, 20).map((f) => ({ action: f.getAttribute('action') || '', method: (f.getAttribute('method') || 'get').toLowerCase(), fields: [...f.querySelectorAll('input, textarea, select')].map((i) => i.getAttribute('type') || i.tagName.toLowerCase()).slice(0, 12) })),
  };
}
"""

# Sign-in and payment forms in view: a copy of such a page is a phishing kit, so it is not remade.
SENSITIVE_JS = r"""
() => {
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const password = [...document.querySelectorAll('input[type="password"]')].filter(visible).length;
  const card = [...document.querySelectorAll('input[autocomplete^="cc-"], input[name*="card" i], input[name*="cvc" i], input[name*="iban" i], iframe[src*="js.stripe.com"], iframe[src*="checkout"], iframe[name*="card" i]')].filter(visible).length;
  return { password, card };
}
"""

# A static picture of the rendered page: rules that live only in the CSSOM (CSS-in-JS, adopted sheets) written out as text,
# canvases turned into images, typed values kept, every address made absolute, the parity freeze style removed.
SNAPSHOT_JS = r"""
() => {
  const base = document.baseURI;
  const abs = (u) => { try { return new URL(u, base).href; } catch (e) { return u; } };
  const skip = (v) => !v || /^(data:|blob:|#|mailto:|tel:|javascript:|about:)/i.test(v.trim());
  const urls = (css) => css.replace(/url\(\s*(['"]?)([^'")]+)\1\s*\)/g, (m, q, u) => (skip(u) ? m : 'url("' + abs(u.trim()) + '")'));
  for (const s of [...document.querySelectorAll('style')]) {
    if (s.hasAttribute('data-parity-freeze')) { s.remove(); continue; }
    try {
      const rules = [...s.sheet.cssRules].map((r) => r.cssText).join('\n');
      if (rules.length > (s.textContent || '').trim().length + 20) s.textContent = rules;
    } catch (e) {}
    s.textContent = urls(s.textContent || '');
  }
  try {
    for (const sheet of document.adoptedStyleSheets || []) {
      const st = document.createElement('style');
      st.setAttribute('data-remake-adopted', '');
      st.textContent = urls([...sheet.cssRules].map((r) => r.cssText).join('\n'));
      document.head.appendChild(st);
    }
  } catch (e) {}
  for (const c of [...document.querySelectorAll('canvas')]) {
    try {
      const cs = getComputedStyle(c);
      const img = document.createElement('img');
      img.src = c.toDataURL('image/png');
      for (const a of ['id', 'class', 'style']) if (c.hasAttribute(a)) img.setAttribute(a, c.getAttribute(a));
      img.style.width = cs.width; img.style.height = cs.height; img.style.display = cs.display === 'inline' ? 'inline-block' : cs.display;
      img.alt = '';
      c.replaceWith(img);
    } catch (e) {}
  }
  for (const i of document.querySelectorAll('input, textarea')) {
    if (i.type !== 'password' && i.value) { if (i.tagName === 'TEXTAREA') i.textContent = i.value; else i.setAttribute('value', i.value); }
    if (i.checked) i.setAttribute('checked', '');
  }
  for (const el of document.querySelectorAll('[src], [href], [poster], [action], [srcset], [style], [data-src], [data-srcset], [data-bg]')) {
    for (const a of ['src', 'href', 'poster', 'action', 'data-src', 'data-bg']) {
      if (el.hasAttribute(a) && !skip(el.getAttribute(a))) el.setAttribute(a, abs(el.getAttribute(a).trim()));
    }
    for (const a of ['srcset', 'data-srcset']) {
      if (el.hasAttribute(a)) el.setAttribute(a, el.getAttribute(a).split(',').map((part) => { const bits = part.trim().split(/\s+/); if (bits[0] && !skip(bits[0])) bits[0] = abs(bits[0]); return bits.join(' '); }).join(', '));
    }
    if (el.hasAttribute('style')) el.setAttribute('style', urls(el.getAttribute('style')));
  }
  for (const b of [...document.querySelectorAll('base')]) b.remove();
  const doctype = document.doctype ? '<!DOCTYPE ' + document.doctype.name + '>' : '<!DOCTYPE html>';
  return { html: doctype + '\n' + document.documentElement.outerHTML, base };
}
"""


# ---------------------------------------------------------------------------------------------------- guards

def looks_like_bot_wall(status: int, html: str) -> bool:
    """A challenge page (Cloudflare, PerimeterX, Incapsula, Vercel checkpoint ...) instead of the site."""
    html = html or ""
    if status in (403, 429, 503) and any(r.search(html) for r in _CHALLENGE):
        return True
    return any(r.search(html[:20000]) for r in _CHALLENGE) and len(html) < 60000


def is_tracker(url: str) -> bool:
    return any(t in (url or "") for t in TRACKERS)


# ---------------------------------------------------------------------------------------------------- html clean-up

_SCRIPT_TAG = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.I | re.S)
_SRC_ATTR = re.compile(r"""\bsrc\s*=\s*["']([^"']+)["']""", re.I)
_LINK_TAG = re.compile(r"<link\b[^>]*>", re.I)


def _tracker_snippet(body: str) -> bool:
    b = body.strip()
    return len(b) < 6000 and bool(
        re.match(r"\(function\(w,d,s,l,i\)", b) or re.match(r"window\.dataLayer\s*=\s*window\.dataLayer\s*\|\|\s*\[\];[\s\S]{0,300}gtag\(", b)
        or re.match(r"!function\(f,b,e,v,n,t,s\)", b) or re.match(r"\(function\(h,o,t,j,a,r\)", b)
        or re.match(r"\(function\(c,l,a,r,i,t,y\)", b) or b.startswith("_linkedin_partner_id")
        or re.match(r"!function\(t,e\)\{var o,n,p,r;e\.__SV", b) or re.match(r"\(function\(e,t\)\{var r=e\.amplitude", b))


def strip_trackers(html: str) -> tuple[str, list[str]]:
    """Analytics, ad pixels, consent managers and chat widgets out of the page (tags and their inline snippets)."""
    removed: list[str] = []

    def script(m: re.Match) -> str:
        attrs, body = m.group(1), m.group(2)
        src = _SRC_ATTR.search(attrs)
        if src and is_tracker(src.group(1)):
            removed.append(src.group(1))
            return ""
        if not src and not re.search(r"type\s*=\s*[\"']?application/(ld\+)?json", attrs, re.I) and _tracker_snippet(body):
            removed.append("inline snippet")
            return ""
        return m.group(0)

    out = _SCRIPT_TAG.sub(script, html)
    out = re.sub(r"<noscript>\s*<iframe[^>]+googletagmanager[^>]*>\s*</iframe>\s*</noscript>", "", out, flags=re.I)

    def link(m: re.Match) -> str:
        href = re.search(r"""\bhref\s*=\s*["']([^"']+)["']""", m.group(0), re.I)
        if href and is_tracker(href.group(1)):
            removed.append(href.group(1))
            return ""
        return m.group(0)

    return _LINK_TAG.sub(link, out), removed


def strip_scripts(html: str) -> str:
    """Every script out (JSON-LD and other JSON data blocks stay), with the preloads that only feed scripts."""
    def script(m: re.Match) -> str:
        return m.group(0) if re.search(r"type\s*=\s*[\"']?application/(ld\+)?json", m.group(1), re.I) else ""

    out = _SCRIPT_TAG.sub(script, html)
    out = re.sub(r"<script\b[^>]*/>", "", out, flags=re.I)

    def link(m: re.Match) -> str:
        tag = m.group(0)
        if re.search(r"""rel\s*=\s*["']?modulepreload""", tag, re.I) or (re.search(r"""rel\s*=\s*["']?preload""", tag, re.I) and re.search(r"""\bas\s*=\s*["']?script""", tag, re.I)):
            return ""
        return tag

    return _LINK_TAG.sub(link, out)


def clean_html(html: str, *, keep_scripts: bool = False, source_url: str = "") -> tuple[str, list[str]]:
    """The page ready to be served from its own folder: trackers out (scripts too unless kept), subresource-integrity and CSP
    meta tags out (rewriting changes the bytes), the parity freeze style out, a noindex tag and a note of where it came from."""
    out, removed = strip_trackers(html)
    if not keep_scripts:
        out = strip_scripts(out)
    out = re.sub(r"""\s+integrity\s*=\s*(["'])[^"']*\1""", "", out, flags=re.I)
    out = re.sub(r"""<meta[^>]+http-equiv\s*=\s*["']?content-security-policy["']?[^>]*>""", "", out, flags=re.I)
    out = re.sub(r"<style[^>]*data-parity-freeze[^>]*>.*?</style>", "", out, flags=re.I | re.S)
    out = re.sub(r"<base\b[^>]*>", "", out, flags=re.I)
    if "name=\"robots\"" not in out:
        note = '<meta name="robots" content="noindex, nofollow">'
        out = re.sub(r"<head\b[^>]*>", lambda m: m.group(0) + note, out, count=1, flags=re.I) if re.search(r"<head\b", out, re.I) else note + out
    if source_url and "Rehecho por Vitruvius" not in out:
        comment = f"<!-- Rehecho por Vitruvius's Hoard a partir de {html_lib.escape(source_url)} -->\n"
        out = re.sub(r"^(\s*<!DOCTYPE[^>]*>\s*)", lambda m: m.group(1) + comment, out, count=1, flags=re.I) if re.match(r"\s*<!DOCTYPE", out, re.I) else comment + out
    return out, removed


def absolutize_markup(html: str, base: str) -> str:
    """Every address in markup (src, href, poster, srcset, style url()) made absolute against `base` (the original document)."""
    skip = re.compile(r"^(data:|blob:|#|mailto:|tel:|javascript:|about:)", re.I)

    def one(u: str) -> str:
        u = u.strip()
        if not u or skip.match(u):
            return u
        try:
            return urljoin(base, html_lib.unescape(u))
        except ValueError:
            return u

    def attr(m: re.Match) -> str:
        return f'{m.group(1)}={m.group(2)}{one(m.group(3))}{m.group(2)}'

    out = re.sub(r"""\b(src|href|poster|data-src|action)\s*=\s*(["'])([^"']*)\2""", attr, html, flags=re.I)

    def srcset(m: re.Match) -> str:
        parts = []
        for part in m.group(3).split(","):
            bits = part.strip().split()
            if bits:
                bits[0] = one(bits[0])
            parts.append(" ".join(bits))
        return f'{m.group(1)}={m.group(2)}{", ".join(parts)}{m.group(2)}'

    out = re.sub(r"""\b(srcset|data-srcset|imagesrcset)\s*=\s*(["'])([^"']*)\2""", srcset, out, flags=re.I)
    return absolutize_css(out, base)


def absolutize_css(css: str, base: str) -> str:
    def url(m: re.Match) -> str:
        raw = m.group(2).strip()
        if not raw or re.match(r"^(data:|#|about:)", raw, re.I):
            return m.group(0)
        return f'url("{urljoin(base, raw)}")'

    out = re.sub(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""", url, css)
    return re.sub(r"""@import\s+(["'])([^"']+)\1""", lambda m: f'@import "{urljoin(base, m.group(2))}"', out)


# ---------------------------------------------------------------------------------------------------- local files

def local_path(url: str, content_type: str = "", taken: Optional[dict[str, str]] = None) -> Optional[str]:
    """Where a downloaded file lives inside the project: ``assets/<host>/<path>`` (query strings become a short hash, a
    missing extension comes from the content type, ``..`` and odd characters never survive)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = re.sub(r"[^a-z0-9.-]", "_", parts.hostname.lower())
    path = unquote(parts.path or "/")
    segs = [re.sub(r"[<>:\"|*?\\\x00-\x1f]", "_", s)[:120] for s in path.split("/") if s and s not in (".", "..")]
    if not segs or path.endswith("/"):
        segs.append("index")
    name = segs[-1]
    stem, ext = posixpath.splitext(name)
    if not (ext and len(ext) <= 6 and re.fullmatch(r"\.[A-Za-z0-9]+", ext)):
        stem, ext = name, EXT_FOR_TYPE.get((content_type or "").split(";")[0].strip().lower(), ".bin")
    if parts.query:
        stem += "__" + hashlib.sha1(parts.query.encode("utf-8")).hexdigest()[:8]
    segs[-1] = stem + ext.lower()
    rel = "assets/" + host + "/" + "/".join(segs)
    if taken is not None:
        prior = taken.get(rel)
        if prior and prior != url:
            rel = rel[: -len(ext)] + "__" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:8] + ext.lower()
        taken[rel] = url
    return rel


def rewrite_urls(text: str, mapping: dict[str, str], from_dir: str = "") -> str:
    """Absolute addresses of downloaded files replaced by paths relative to `from_dir` (the folder of the file being written,
    relative to the site root). Plain, HTML-escaped and protocol-relative spellings are all replaced; longest first."""
    if not mapping or not text:
        return text
    forms: dict[str, str] = {}
    for url, rel in mapping.items():
        target = posixpath.relpath(rel, from_dir or ".")
        for form in {url, url.replace("&", "&amp;"), re.sub(r"^https?:", "", url)}:
            if len(form) > 8:
                forms.setdefault(form, target)
    keys = sorted(forms, key=len, reverse=True)
    pattern = re.compile("(" + "|".join(re.escape(k) for k in keys) + r")(?=[\s\"'()<>,;\\]|&quot;|$)")
    return pattern.sub(lambda m: forms[m.group(1)], text)


def font_faces(css: str) -> list[dict[str, Any]]:
    """@font-face blocks of a stylesheet whose addresses are already absolute: family, weight, style and sources."""
    faces = []
    for block in re.findall(r"@font-face\s*\{([^}]*)\}", css, re.I):
        family = re.search(r"font-family\s*:\s*([^;]+)", block, re.I)
        if not family:
            continue
        weight = re.search(r"font-weight\s*:\s*([^;]+)", block, re.I)
        style = re.search(r"font-style\s*:\s*([^;]+)", block, re.I)
        unicode_range = re.search(r"unicode-range\s*:\s*([^;]+)", block, re.I)
        srcs = re.findall(r"""url\(\s*["']?([^"')]+)["']?\s*\)(?:\s*format\(\s*["']?([^"')]+)["']?\s*\))?""", block, re.I)
        faces.append({"family": family.group(1).strip().strip("'\""), "weight": (weight.group(1).strip() if weight else "400"),
                      "style": (style.group(1).strip() if style else "normal"),
                      "unicode_range": unicode_range.group(1).strip() if unicode_range else "",
                      "src": [{"url": u.strip(), "format": f} for u, f in srcs]})
    return faces


def licence_for(url: str, kind: str, origin_host: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith("fonts.gstatic.com") or host.endswith("fonts.googleapis.com"):
        return "Google Fonts: licencia SIL Open Font License o Apache 2.0 (uso libre, conserva el aviso de la fuente)"
    bare = lambda h: h[4:] if h.startswith("www.") else h  # noqa: E731
    if bare(host) == bare(origin_host or ""):
        return "Pertenece al sitio original: cámbialo o pide permiso antes de publicarlo"
    return f"Servido por {host}: comprueba su licencia antes de publicarlo"


def asset_kind(content_type: str, resource_type: str, url: str) -> str:
    ct = (content_type or "").lower()
    path = urlsplit(url).path.lower()
    if "css" in ct or resource_type == "stylesheet" or path.endswith(".css"):
        return "styles"
    if "javascript" in ct or resource_type == "script" or re.search(r"\.m?js$", path):
        return "scripts"
    if "font" in ct or resource_type == "font" or re.search(r"\.(woff2?|ttf|otf|eot)$", path):
        return "fonts"
    if ct.startswith("image/") or resource_type == "image" or re.search(r"\.(png|jpe?g|gif|webp|avif|svg|ico)$", path):
        return "images"
    if ct.startswith(("video/", "audio/")) or resource_type == "media":
        return "media"
    return "other"


def build_assets(entries: list[dict[str, Any]], site_dir: Path, *, origin_host: str, keep_scripts: bool = False,
                 ledger: Optional[list[dict[str, Any]]] = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Copy the files the page loaded into ``site/assets``; stylesheets get their own addresses rewritten too.

    `entries` come from the browser: ``{url, content_type, resource_type, file, bytes}``. Returns the ledger (one row per
    file: original address, local path, kind, size, licence) and the address → local path mapping."""
    ledger = list(ledger or [])
    taken = {row["local"]: row["url"] for row in ledger if row.get("local")}
    mapping = {row["url"]: row["local"] for row in ledger if row.get("local")}
    pending_css: list[tuple[str, Path, str]] = []
    for entry in entries:
        url = entry.get("url") or ""
        if url in mapping or is_tracker(url) or not entry.get("file"):
            continue
        kind = asset_kind(entry.get("content_type", ""), entry.get("resource_type", ""), url)
        if kind == "scripts" and not keep_scripts:
            continue
        rel = local_path(url, entry.get("content_type", ""), taken)
        if not rel:
            continue
        target = site_dir / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry["file"], target)
        except OSError as error:
            ledger.append({"url": url, "local": None, "kind": kind, "status": "no se pudo guardar", "error": str(error)[:120]})
            continue
        mapping[url] = rel
        ledger.append({"url": url, "local": rel, "kind": kind, "content_type": entry.get("content_type", ""),
                       "bytes": target.stat().st_size, "licence": licence_for(url, kind, origin_host)})
        if kind == "styles":
            pending_css.append((url, target, rel))
    for url, target, rel in pending_css:
        try:
            css = target.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        css = rewrite_urls(absolutize_css(css, url), mapping, posixpath.dirname(rel))
        target.write_text(css, encoding="utf-8")
    return ledger, mapping


def fonts_css(site_dir: Path, ledger: list[dict[str, Any]], extra_css: str = "") -> tuple[str, list[dict[str, Any]]]:
    """One stylesheet with every @font-face of the original whose files were downloaded, pointing at the local copies
    (for the rebuild mode: the model links it and uses the families by name)."""
    mapping = {row["url"]: row["local"] for row in ledger if row.get("local")}
    blocks: list[str] = []
    families: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    sources = [extra_css]
    for row in ledger:
        if row.get("kind") == "styles" and row.get("local"):
            try:
                sources.append(absolutize_css((site_dir / row["local"]).read_text(encoding="utf-8", errors="replace"), row["url"]))
            except OSError:
                pass
    for css in sources:
        for face in font_faces(css or ""):
            local = []
            for src in face["src"]:
                url = src["url"]
                rel = mapping.get(url)
                if rel is None and url.startswith("assets/"):
                    rel = url
                if rel is None:
                    # already rewritten to a path relative to its stylesheet: find the file by name
                    name = posixpath.basename(urlsplit(url).path)
                    rel = next((r["local"] for r in ledger if r.get("local") and posixpath.basename(r["local"]) == name), None)
                if rel:
                    local.append((posixpath.relpath(rel, "assets"), src["format"]))
            key = (face["family"], face["weight"], face["style"], face["unicode_range"], tuple(local))
            if not local or key in seen:
                continue
            seen.add(key)
            src = ", ".join(f'url("{p}")' + (f' format("{f}")' if f else "") for p, f in local)
            blocks.append("@font-face{font-family:\"%s\";font-weight:%s;font-style:%s;font-display:block;src:%s;%s}" % (
                face["family"].replace('"', ""), face["weight"], face["style"], src,
                f"unicode-range:{face['unicode_range']};" if face["unicode_range"] else ""))
            families.append({"family": face["family"], "weight": face["weight"], "style": face["style"]})
    return "\n".join(blocks), families


def slots(outline: Optional[dict[str, Any]], ledger: list[dict[str, Any]], *, origin_host: str,
          page_url: str = "") -> dict[str, Any]:
    """What still belongs to the original, grouped as a checklist: texts, images, fonts, colours, links, forms."""
    outline = outline or {}
    items = outline.get("items") or []
    by_url = {row["url"]: row for row in ledger if row.get("local")}
    texts = [it for it in items if it.get("tx")]
    headings = [{"tag": it["t"], "text": it["tx"], "y": it["y"]} for it in texts if re.fullmatch(r"h[1-6]", it["t"])]
    images = []
    for it in items:
        if it["t"] == "img" and it.get("src"):
            row = by_url.get(it["src"])
            images.append({"src": it["src"], "local": row["local"] if row else None, "alt": it.get("alt", ""),
                           "natural": [it.get("nw"), it.get("nh")], "shown": [it["w"], it["h"]], "y": it["y"],
                           "licence": row["licence"] if row else licence_for(it["src"], "images", origin_host)})
    fonts = []
    google = any("fonts.gstatic.com" in row["url"] for row in ledger if row.get("kind") == "fonts")
    names = {re.sub(r"\s+(\d{3,4}(\s+\d{3,4})?|normal|bold)(\s+(italic|oblique).*)?$", "", str(f)).strip() for f in outline.get("fonts") or []}
    names |= {re.sub(r"\s+italic$", "", it["f"].split(" ", 2)[2]).strip() for it in texts if it.get("f") and it["f"].count(" ") >= 2}
    for name in sorted(n for n in names if n):
        free = bool(FREE_FONTS.match(name))
        fonts.append({"family": name, "free": free,
                      "note": "gratuita" + (" (Google Fonts)" if google else "") if free else "puede ser de pago: comprueba la licencia o cámbiala por una libre parecida"})
    host = lambda u: (urlsplit(u).hostname or "").lower()  # noqa: E731
    bare = lambda h: h[4:] if h.startswith("www.") else h  # noqa: E731
    links: dict[str, list[dict[str, str]]] = {"redes": [], "reservas": [], "correo": [], "telefono": [], "paginas_no_rehechas": [], "otros": []}
    seen = set()
    for link in outline.get("links") or []:
        href = link.get("href") or ""
        if href in seen or href.startswith("javascript:") or "#" == href[-1:]:
            continue
        seen.add(href)
        row = {"href": href, "text": link.get("text", "")}
        if href.startswith("mailto:"):
            links["correo"].append(row)
        elif href.startswith("tel:"):
            links["telefono"].append(row)
        elif SOCIAL.search(href):
            links["redes"].append(row)
        elif BOOKING.search(href):
            links["reservas"].append(row)
        elif bare(host(href)) == bare(origin_host) and href.split("#")[0].rstrip("/") != page_url.split("#")[0].rstrip("/"):
            links["paginas_no_rehechas"].append(row)
        else:
            links["otros"].append(row)
    words = sum(len(it["tx"].split()) for it in texts)
    out = {
        "textos": {"bloques": len(texts), "palabras": words, "titulares": headings[:40]},
        "imagenes": images[:200], "fuentes": fonts, "colores": outline.get("palette") or [],
        "enlaces": {k: v[:80] for k, v in links.items()}, "formularios": outline.get("forms") or [],
    }
    out["resumen"] = {"textos": len(texts), "imagenes": len(images), "fuentes": len(fonts),
                      "fuentes_a_revisar": sum(1 for f in fonts if not f["free"]), "colores": len(out["colores"]),
                      "enlaces_externos": sum(len(v) for k, v in links.items() if k != "paginas_no_rehechas"),
                      "paginas_no_rehechas": len(links["paginas_no_rehechas"]), "formularios": len(out["formularios"])}
    return out


# ---------------------------------------------------------------------------------------------------- layout as text

def _item_line(it: dict[str, Any], mapping: Optional[dict[str, str]] = None) -> str:
    bits = [f"{it['y']:>5} {it['x']:>4} {it['w']:>4}x{it['h']:<4} {it['t']}"]
    if it.get("s"):
        bits[0] += f" {it['s'][:90]}"
    style = []
    if it.get("f"):
        style.append(f"{it['f']}/{it.get('lh', '')}")
    for key, label in (("c", ""), ("bg", "bg "), ("bd", "border "), ("br", "radius "), ("ly", ""), ("pos", ""), ("ta", "align "),
                       ("ls", "spacing "), ("tt", ""), ("sh", "shadow "), ("fit", "fit "), ("op", "opacity "), ("fx", "filter ")):
        if it.get(key):
            style.append(f"{label}{it[key]}")
    if it.get("bi"):
        style.append("bg-image " + (rewrite_urls(it["bi"], mapping or {}) if mapping else it["bi"])[:140])
    if style:
        bits.append(" ".join(style))
    if it.get("src"):
        src = (mapping or {}).get(it["src"], it["src"])
        bits.append(f"src {src[:140]}" + (f" natural {it.get('nw')}x{it.get('nh')}" if it.get("nw") else "") + (f" alt \"{it.get('alt', '')[:60]}\"" if it.get("alt") else ""))
    if it.get("href") and not it.get("tx"):
        bits.append(f"href {it['href'][:80]}")
    if it.get("tx"):
        bits.append('"' + it["tx"][:160].replace('"', "'") + '"')
    return " | ".join(bits)


def outline_text(outline: Optional[dict[str, Any]], *, mapping: Optional[dict[str, str]] = None, limit: int = 260,
                 y_range: Optional[tuple[int, int]] = None, max_chars: int = 40000) -> str:
    """The layout as one line per element (y x wxh tag selector | font colours | text). Items with text, media or colour
    come first when the list has to be cut."""
    if not outline:
        return "(no layout)"
    items = outline.get("items") or []
    if y_range is not None:
        y0, y1 = y_range
        items = [it for it in items if it["y"] < y1 and it["y"] + it["h"] > y0]
    if len(items) > limit:
        ranked = sorted(range(len(items)), key=lambda i: (0 if (items[i].get("tx") or items[i]["t"] in ("img", "svg", "video", "button", "input")) else 1 if items[i].get("bg") or items[i].get("bi") else 2, items[i]["d"]))
        keep = set(ranked[:limit])
        items = [it for i, it in enumerate(items) if i in keep]
    lines, size = [], 0
    for it in items:
        line = _item_line(it, mapping)
        size += len(line) + 1
        if size > max_chars:
            lines.append("… (cut)")
            break
        lines.append(line)
    return "\n".join(lines)


def _key(it: dict[str, Any]) -> str:
    if it.get("tx"):
        return "t:" + re.sub(r"\s+", " ", it["tx"].lower())[:60]
    if it.get("src"):
        return "i:" + posixpath.basename(urlsplit(it["src"]).path).lower()
    return ""


def screen_diff(ref: Optional[dict[str, Any]], cand: Optional[dict[str, Any]], y0: int, y1: int, *,
                mapping: Optional[dict[str, str]] = None, limit: int = 45) -> list[str]:
    """Element-by-element differences in one screen: matched by text (or image file), the deltas of position, size, font and
    colours; reference elements the candidate lacks; candidate elements the reference does not have."""
    if not ref or not cand:
        return []
    ref_items = [it for it in ref.get("items") or [] if it["y"] < y1 and it["y"] + it["h"] > y0 and _key(it)]
    pool: dict[str, list[dict[str, Any]]] = {}
    for it in cand.get("items") or []:
        k = _key(it)
        if k:
            pool.setdefault(k, []).append(it)
    rows: list[tuple[float, str]] = []
    ref_keys = set()
    for it in ref_items:
        k = _key(it)
        ref_keys.add(k)
        options = pool.get(k) or []
        if not options:
            rows.append((10_000 + it["h"], "MISSING in candidate: " + _item_line(it, mapping)))
            continue
        other = min(options, key=lambda o: abs(o["y"] - it["y"]) + abs(o["x"] - it["x"]))
        options.remove(other)
        deltas = []
        weight = 0.0
        for name, key in (("x", "x"), ("y", "y"), ("width", "w"), ("height", "h")):
            d = other[key] - it[key]
            if abs(d) > 2:
                deltas.append(f"{name} {it[key]}→{other[key]} ({d:+d})")
                weight += abs(d)
        for name, key in (("font", "f"), ("line-height", "lh"), ("colour", "c"), ("background", "bg"), ("align", "ta"),
                          ("spacing", "ls"), ("radius", "br"), ("border", "bd"), ("opacity", "op"), ("filter", "fx")):
            if (it.get(key) or "") != (other.get(key) or ""):
                deltas.append(f"{name} {it.get(key) or '-'} → {other.get(key) or '-'}")
                weight += 25
        if deltas:
            label = (it.get("tx") or it.get("src") or "")[:70].replace('"', "'")
            rows.append((weight, f"DIFF {it['t']} \"{label}\" (ref selector {it.get('s', '')[:70]}; candidate selector {other.get('s', '')[:70]}): " + "; ".join(deltas)))
    for it in cand.get("items") or []:
        k = _key(it)
        if k and k not in ref_keys and it["y"] < y1 and it["y"] + it["h"] > y0 and not any(k == _key(r) for r in ref.get("items") or []):
            rows.append((5_000, "EXTRA in candidate (not in reference): " + _item_line(it, mapping)))
    rows.sort(key=lambda r: -r[0])
    return [r[1] for r in rows[:limit]]


def focus_screens(widths: list[dict[str, Any]], *, per_width: int = 1) -> list[dict[str, Any]]:
    """The screens to fix this round: the first failing screen of each width (a shift near the top makes every screen
    below it fail, so the top goes first)."""
    out = []
    for w in widths:
        failing = [s for s in w.get("screens") or [] if not s.get("passed")]
        for s in failing[:per_width]:
            out.append({"width": w["width"], "index": s["index"], "y": s["y"], "height": s["height"], "score": s.get("score"),
                        "viewport_height": w.get("viewport_height")})
        if not failing and not w.get("height_pass", True):
            last = (w.get("screens") or [{}])[-1]
            out.append({"width": w["width"], "index": last.get("index", 0), "y": last.get("y", 0), "height": last.get("height", 0),
                        "score": last.get("score"), "viewport_height": w.get("viewport_height")})
    return out


def round_score(widths: list[dict[str, Any]]) -> float:
    scores = [float(w.get("score") or 0.0) for w in widths]
    return round(sum(scores) / len(scores), 2) if scores else 0.0


# ---------------------------------------------------------------------------------------------------- prompts and answers

_RULES = (
    "Rules:\n"
    "- One complete HTML document with all CSS in a single <style> in <head>. No JavaScript, no frameworks, no CDNs and no "
    "external stylesheets except assets/fonts.css when it is listed.\n"
    "- Use the reference's exact texts in the same order, and its images by their local paths (assets/...). Never use a "
    "screenshot of the reference as an image.\n"
    "- Match every element's position, size, font (family, size, weight, line height), colours, backgrounds, borders, radii "
    "and spacing as the layout lists them (y x width x height in CSS px from the top-left corner of the page).\n"
    "- The widest width is the main layout; narrower ones go in @media (max-width: ...) rules. Total page heights must match.\n"
    "- Set the body margin explicitly; prefer normal flow (flex, grid) over absolute positions.\n"
)


def system_prompt(mode: str, widths: list[int], *, repair: bool) -> str:
    sizes = " and ".join(f"{w} px" for w in widths)
    if mode == "copy":
        return (f"You fix a static copy of a web page (its own HTML and CSS, scripts removed) so that it looks exactly like the "
                f"reference at {sizes} wide. You cannot edit the HTML: write CSS rules that are added after every other "
                "stylesheet of the page. Use the selectors given, with enough specificity (or !important) to win. Do not hide "
                "content and do not use pictures of the reference. Answer with one ```css block and nothing else.")
    head = (f"You rebuild an existing web page as new hand-written HTML and CSS that must look identical to the reference, "
            f"pixel for pixel, at {sizes} wide.\n" + _RULES)
    if not repair:
        return head + "Answer with the complete file in one ```html block and nothing else."
    return (head + "You receive the current file, its scores and the differences on the screens that fail. Fix those "
            "differences without breaking what already matches. Answer either with the complete corrected file in one "
            "```html block, or with edits, each one as:\n<<<<<<< SEARCH\n(exact lines of the current file)\n=======\n"
            "(their replacement)\n>>>>>>> REPLACE\nand nothing else.")


def extract_block(text: str, lang: str) -> Optional[str]:
    """The body of the first ```<lang> fenced block (or of the first fence of any language), else None."""
    text = text or ""
    m = re.search(r"```[ \t]*" + re.escape(lang) + r"[^\n]*\n(.*?)```", text, re.S | re.I)
    if not m:
        m = re.search(r"```[^\n]*\n(.*?)```", text, re.S)
    if not m and lang == "html":
        m2 = re.search(r"(<!DOCTYPE html.*?</html>|<html.*?</html>)", text, re.S | re.I)
        return m2.group(1).strip() if m2 else None
    return m.group(1).strip() if m else None


_EDIT = re.compile(r"<{5,9} ?SEARCH[^\n]*\n(.*?)\n?={5,9}[^\n]*\n(.*?)\n?>{5,9} ?REPLACE", re.S)


def apply_edits(current: str, answer: str) -> tuple[str, int, int]:
    """Apply SEARCH/REPLACE edits: exact match first, then line by line ignoring indentation. Returns (text, applied, failed)."""
    out, applied, failed = current, 0, 0
    for search, replace in _EDIT.findall(answer or ""):
        if search and search in out:
            out = out.replace(search, replace, 1)
            applied += 1
            continue
        want = [ln.strip() for ln in search.splitlines() if ln.strip()]
        lines = out.splitlines(keepends=True)
        hit = None
        if want:
            stripped = [ln.strip() for ln in lines]
            for i in range(len(lines)):
                j, k = i, 0
                while j < len(lines) and k < len(want):
                    if not stripped[j]:
                        j += 1
                        continue
                    if stripped[j] != want[k]:
                        break
                    j, k = j + 1, k + 1
                if k == len(want):
                    hit = (i, j)
                    break
        if hit is None:
            failed += 1
            continue
        out = "".join(lines[:hit[0]]) + replace + ("\n" if replace and not replace.endswith("\n") else "") + "".join(lines[hit[1]:])
        applied += 1
    return out, applied, failed


def has_edits(answer: str) -> bool:
    return bool(_EDIT.search(answer or ""))


def insert_fixes(html: str, css: str) -> str:
    """The copy mode's CSS fixes as the last style of the page (right before </body>, after every other stylesheet)."""
    html = re.sub(r"<style id=\"" + FIX_STYLE_ID + r"\">.*?</style>\s*", "", html, flags=re.S)
    if not css.strip():
        return html
    block = f'<style id="{FIX_STYLE_ID}">\n{css.strip()}\n</style>\n'
    if re.search(r"</body\s*>", html, re.I):
        return re.sub(r"</body\s*>", lambda m: block + m.group(0), html, count=1, flags=re.I)
    return html + block


def ensure_fonts_link(html: str) -> str:
    if "assets/fonts.css" in html:
        return html
    link = '<link rel="stylesheet" href="assets/fonts.css">'
    if re.search(r"<head\b[^>]*>", html, re.I):
        return re.sub(r"<head\b[^>]*>", lambda m: m.group(0) + link, html, count=1, flags=re.I)
    return link + html


def png_screen(path: Path, y: int, height: int, max_width: int = 900) -> Optional[bytes]:
    """One screen (rows y..y+height) of a full-page PNG, scaled down to `max_width`, as PNG bytes for the model."""
    try:
        from PIL import Image
        with Image.open(path) as image:
            box = image.convert("RGB").crop((0, max(0, y), image.width, min(image.height, y + height)))
        if box.height <= 0:
            return None
        if box.width > max_width:
            box = box.resize((max_width, max(1, round(box.height * max_width / box.width))))
        buf = io.BytesIO()
        box.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:  # noqa: BLE001 - a missing picture only means the model works from the text
        return None


def image_palette(path: Path, n: int = 10) -> list[dict[str, Any]]:
    try:
        from PIL import Image
        with Image.open(path) as image:
            small = image.convert("RGB").resize((160, max(1, round(160 * image.height / image.width))))
        quant = small.quantize(colors=n)
        pal = quant.getpalette() or []
        counts = sorted(quant.getcolors() or [], reverse=True)
        return [{"c": "#%02x%02x%02x" % tuple(pal[i * 3:i * 3 + 3]), "w": c} for c, i in counts]
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------------------------------- storage

def projects_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "remake"


def project_dir(data_dir: Path, project_id: str) -> Path:
    if not project_id or not re.fullmatch(r"[a-f0-9]{6,32}", project_id):
        raise LookupError(f"Unknown remake '{project_id}'.")
    return projects_dir(data_dir) / project_id


def load(data_dir: Path, project_id: str) -> dict[str, Any]:
    file = project_dir(data_dir, project_id) / "project.json"
    if not file.is_file():
        raise LookupError(f"Unknown remake '{project_id}'.")
    return json.loads(file.read_text(encoding="utf-8"))


def save(data_dir: Path, project: dict[str, Any]) -> None:
    project["updated_ts"] = time.time()
    folder = project_dir(data_dir, project["id"])
    folder.mkdir(parents=True, exist_ok=True)
    write_json_atomic(folder / "project.json", project)


def safe_file(base: Path, name: str) -> Path:
    base = base.resolve()
    target = (base / name).resolve()
    if base not in target.parents:
        raise PermissionError("path escapes the remake folder")
    return target


# ---------------------------------------------------------------------------------------------------- the job

class Cancelled(Exception):
    pass


def _host(url: str) -> str:
    return (urlsplit(url or "").hostname or "").lower()


def _read(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return default


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class RemakeRunner:
    """Owns the remake projects in ``data/design/remake/<id>/`` and runs each one in its own thread (model calls inside a
    pinned global-model job, browser work through the shared `BrowserWorker`)."""

    retry_pause = 1.0  # seconds per step of the 30-step wait before asking an unreachable model again (tests shorten it)

    def __init__(self, svc: Any):
        self.svc = svc
        self.data_dir = Path(svc.config.data_dir)
        self._threads: dict[str, threading.Thread] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._mark_interrupted()

    # ------------------------------------------------------------------ public
    def start(self, *, url: Optional[str] = None, image: Optional[str] = None, image_width: int = 1440, mode: str = "copy",
              widths: Optional[list[int]] = None, max_rounds: Optional[int] = None, pass_score: float = 98.0,
              tolerance: float = 0.10, keep_scripts: bool = False, note: str = "", label: str = "",
              wait_s: float = 0.0) -> dict[str, Any]:
        url = (url or "").strip() or None
        if bool(url) == bool(image):
            raise ValueError("Hace falta una URL o una captura de la página (solo una de las dos).")
        if mode not in MODES:
            raise ValueError("mode: 'copy' (copiar la página) o 'rebuild' (reconstruirla con el modelo)")
        if image:
            mode = "rebuild"
            if not 200 <= int(image_width) <= 3000:
                raise ValueError("image_width: entre 200 y 3000 px")
            widths = [int(image_width)]
        widths = [int(w) for w in (widths or DEFAULT_WIDTHS)]
        if not 1 <= len(widths) <= 3 or any(w < 200 or w > 3000 for w in widths):
            raise ValueError("widths: de 1 a 3 anchuras entre 200 y 3000 px")
        widths = sorted(dict.fromkeys(widths), reverse=True)
        rounds = int(max_rounds or (4 if mode == "copy" else 6))
        if not 1 <= rounds <= MAX_ROUNDS:
            raise ValueError(f"max_rounds: entre 1 y {MAX_ROUNDS}")
        if not 50 <= float(pass_score) <= 100:
            raise ValueError("pass_score: entre 50 y 100")
        if not 0 <= float(tolerance) <= 0.5:
            raise ValueError("tolerance: entre 0 y 0.5 (0.10 = 10 % por canal)")
        if url:
            if not re.match(r"^https?://", url, re.I):
                url = "https://" + url
            self.svc.check_url(url)
        project_id = uuid.uuid4().hex[:12]
        folder = project_dir(self.data_dir, project_id)
        (folder / "capture").mkdir(parents=True, exist_ok=True)
        (folder / "site").mkdir(parents=True, exist_ok=True)
        if image:
            self._save_reference_image(folder, image, widths[0])
        project = {
            "id": project_id, "created_ts": time.time(), "label": (label or "").strip()[:200],
            "source": {"kind": "image" if image else "url", "url": url, "width": widths[0] if image else None},
            "mode": mode, "widths": widths, "max_rounds": rounds, "pass_score": float(pass_score), "tolerance": float(tolerance),
            "keep_scripts": bool(keep_scripts) and mode == "copy", "note": (note or "").strip()[:2000],
            "status": "queued", "phase": "En cola", "captured": False, "rounds": [], "best_round": None, "best_score": None,
            "passed": False, "error": None, "reference": {}, "model": None, "missing": [], "unfetchable": [],
        }
        save(self.data_dir, project)
        self._launch(project_id, "start", rounds)
        return self._wait(project_id, wait_s)

    def continue_(self, project_id: str, *, rounds: int = 2, note: str = "", wait_s: float = 0.0) -> dict[str, Any]:
        project = load(self.data_dir, project_id)
        if self._running(project_id):
            raise ValueError("Este proyecto ya está trabajando: espera a que termine o páralo.")
        if not 1 <= int(rounds) <= MAX_ROUNDS:
            raise ValueError(f"rounds: entre 1 y {MAX_ROUNDS}")
        if note and note.strip():
            project["note"] = note.strip()[:2000]
        project.update(status="queued", phase="En cola", error=None)
        save(self.data_dir, project)
        self._launch(project_id, "start" if not project.get("captured") or not project.get("rounds") else "continue", int(rounds))
        return self._wait(project_id, wait_s)

    def stop(self, project_id: str) -> dict[str, Any]:
        load(self.data_dir, project_id)
        event = self._cancel.get(project_id)
        if event is not None:
            event.set()
        return self.get(project_id)

    def delete(self, project_id: str) -> dict[str, Any]:
        project = load(self.data_dir, project_id)
        event, thread = self._cancel.get(project_id), self._threads.get(project_id)
        if event is not None:
            event.set()
        if thread is not None and thread.is_alive():
            thread.join(120)
        from . import parity as parity_mod
        for rnd in project.get("rounds") or []:
            if rnd.get("parity_id"):
                try:
                    parity_mod.delete_run(self.data_dir, rnd["parity_id"])
                except LookupError:
                    pass
        shutil.rmtree(project_dir(self.data_dir, project_id), ignore_errors=True)
        return {"ok": True, "id": project_id}

    def get(self, project_id: str) -> dict[str, Any]:
        project = load(self.data_dir, project_id)
        folder = project_dir(self.data_dir, project_id)
        out = self._with_urls(project)
        out["running"] = self._running(project_id)
        out["slots"] = _read_json(folder / "slots.json", {})
        ledger = _read_json(folder / "assets.json", []) or []
        kinds: dict[str, int] = {}
        for row in ledger:
            if row.get("local"):
                kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
        out["assets"] = {"count": sum(kinds.values()), "by_kind": kinds, "bytes": sum(r.get("bytes") or 0 for r in ledger),
                         "files": [{k: r.get(k) for k in ("url", "local", "kind", "bytes", "licence")} for r in ledger if r.get("local")][:400]}
        out["files"] = self._site_files(folder)[:400]
        return out

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        base = projects_dir(self.data_dir)
        rows = []
        if base.is_dir():
            for folder in base.iterdir():
                project = _read_json(folder / "project.json")
                if not project:
                    continue
                rows.append({k: project.get(k) for k in ("id", "created_ts", "updated_ts", "label", "mode", "status", "phase", "best_score",
                                                         "passed", "widths", "error")}
                            | {"source": project["source"].get("url") or "captura", "rounds": len(project.get("rounds") or []),
                               "running": self._running(project["id"])})
        rows.sort(key=lambda r: r.get("created_ts") or 0, reverse=True)
        return rows[:max(1, int(limit))]

    def code(self, project_id: str, path: str = "index.html", max_chars: int = 200_000) -> dict[str, Any]:
        load(self.data_dir, project_id)
        folder = project_dir(self.data_dir, project_id)
        target = safe_file(folder / "site", path or "index.html")
        if not target.is_file():
            raise LookupError(f"No existe '{path}' en el proyecto.")
        text = target.read_bytes().decode("utf-8", errors="replace")
        return {"id": project_id, "path": path, "chars": len(text), "truncated": len(text) > max_chars, "text": text[:max_chars],
                "files": self._site_files(folder)[:400]}

    def site_file(self, project_id: str, name: str) -> Path:
        load(self.data_dir, project_id)
        return safe_file(project_dir(self.data_dir, project_id) / "site", name or "index.html")

    def zip_bytes(self, project_id: str) -> tuple[str, bytes]:
        project = load(self.data_dir, project_id)
        folder = project_dir(self.data_dir, project_id)
        ledger = _read_json(folder / "assets.json", []) or []
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in sorted((folder / "site").rglob("*")):
                if file.is_file():
                    zf.write(file, "site/" + file.relative_to(folder / "site").as_posix())
            for name in ("assets.json", "slots.json"):
                if (folder / name).is_file():
                    zf.write(folder / name, name)
            zf.writestr("paridad.json", json.dumps(self._rounds_summary(project), ensure_ascii=False, indent=1))
            zf.writestr("creditos.md", credits_markdown(project, ledger))
        name = re.sub(r"[^a-z0-9.-]+", "-", (_host(project["source"].get("url") or "") or "captura")) + f"-{project_id}.zip"
        return name, buf.getvalue()

    def report_html(self, project_id: str) -> str:
        return report_html(self._with_urls(load(self.data_dir, project_id)))

    def close(self) -> None:
        for event in list(self._cancel.values()):
            event.set()
        for thread in list(self._threads.values()):
            if thread.is_alive():
                thread.join(5)  # a job waiting on the model cannot be interrupted; the next start marks it interrupted

    # ------------------------------------------------------------------ thread plumbing
    def _running(self, project_id: str) -> bool:
        thread = self._threads.get(project_id)
        return bool(thread and thread.is_alive())

    def _launch(self, project_id: str, phase: str, budget: int) -> None:
        with self._lock:
            if self._running(project_id):
                raise ValueError("Este proyecto ya está trabajando.")
            self._cancel[project_id] = threading.Event()
            thread = threading.Thread(target=self._run, args=(project_id, phase, budget), name=f"vitruvius-remake-{project_id}", daemon=True)
            self._threads[project_id] = thread
            thread.start()

    def _wait(self, project_id: str, wait_s: float) -> dict[str, Any]:
        thread = self._threads.get(project_id)
        if thread is not None and wait_s and wait_s > 0:
            thread.join(float(wait_s))
        return self.get(project_id)

    def _mark_interrupted(self) -> None:
        base = projects_dir(self.data_dir)
        if not base.is_dir():
            return
        for folder in base.iterdir():
            project = _read_json(folder / "project.json")
            if project and project.get("status") in ("queued", "running"):
                project["status"] = "interrupted"
                project["phase"] = "Interrumpido: la aplicación se cerró mientras trabajaba. «Seguir corrigiendo» lo retoma."
                try:
                    save(self.data_dir, project)
                except (OSError, LookupError):
                    pass

    def _check(self, project: dict[str, Any]) -> None:
        event = self._cancel.get(project["id"])
        if event is not None and event.is_set():
            raise Cancelled()

    def _phase(self, project: dict[str, Any], text: str) -> None:
        project["phase"] = text
        save(self.data_dir, project)
        self._check(project)

    def _run(self, project_id: str, phase: str, budget: int) -> None:
        context: Any = nullcontext()
        try:
            from .software.global_models import global_job
            context = global_job()
        except Exception:  # noqa: BLE001 - without the global-model contract the model calls simply use the injected link
            pass
        with context:
            project = load(self.data_dir, project_id)
            project.update(status="running", error=None)
            save(self.data_dir, project)
            try:
                if phase == "start":
                    project.update(rounds=[], best_round=None, best_score=None, passed=False, missing=[], unfetchable=[], last_reverted=None)
                    self._capture(project)
                    self._first_round(project)
                    budget -= 1
                self._loop(project, budget)
                project["status"] = "done"
                best = project["rounds"][project["best_round"]] if project.get("best_round") is not None else None
                if project.get("passed"):
                    project["phase"] = f"Hecho: pasa la paridad en todas las anchuras (ronda {best['n']}, {best['score']} %)."
                elif best:
                    project["phase"] = (f"Terminado sin pasar: la mejor es la ronda {best['n']} con {best['score']} %. "
                                        "«Seguir corrigiendo» añade más rondas.") + (f" {project['stop_reason']}" if project.get("stop_reason") else "")
            except Cancelled:
                project["status"] = "stopped"
                project["phase"] = "Parado a petición. «Seguir corrigiendo» lo retoma desde la mejor ronda."
            except Exception as error:  # noqa: BLE001 - the project records why it stopped
                log.warning("remake %s failed", project_id, exc_info=True)
                project["status"] = "failed"
                project["error"] = str(error)[:600]
                project["phase"] = "Error: " + project["error"]
            finally:
                if project.get("best_round") is not None:
                    self._restore_best(project)
                shutil.rmtree(project_dir(self.data_dir, project_id) / "tmp", ignore_errors=True)
                save(self.data_dir, project)
                try:
                    self.svc._emit_event("vitruvius.remake.done", {"remake_id": project_id, "status": project["status"],
                                                                   "passed": project.get("passed"), "score": project.get("best_score")})
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------------------ capture
    def _save_reference_image(self, folder: Path, image: str, width: int) -> None:
        from PIL import Image
        raw = image.split(",", 1)[1] if image.strip().startswith("data:") else image
        try:
            data = base64.b64decode(raw, validate=False)
            with Image.open(io.BytesIO(data)) as pic:
                pic = pic.convert("RGB")
                if pic.width != width:
                    pic = pic.resize((width, max(1, round(pic.height * width / pic.width))))
                pic.save(folder / "capture" / f"reference-{width}-1.png")
        except Exception as error:  # noqa: BLE001
            shutil.rmtree(folder, ignore_errors=True)
            raise ValueError(f"La captura no es una imagen válida ({type(error).__name__}).") from error

    def _capture(self, project: dict[str, Any]) -> None:
        folder = project_dir(self.data_dir, project["id"])
        cap, site = folder / "capture", folder / "site"
        widths = project["widths"]
        if project["source"]["kind"] == "image":
            from PIL import Image
            path = cap / f"reference-{widths[0]}-1.png"
            with Image.open(path) as pic:
                height = pic.height
            project["reference"] = {"url": "", "title": "", "lang": "", "heights": {str(widths[0]): height}, "palette": image_palette(path),
                                    "loads": 1, "assets": 0}
            write_json_atomic(folder / "assets.json", [])
            write_json_atomic(folder / "slots.json", {})
            project["captured"] = True
            save(self.data_dir, project)
            return
        url = project["source"]["url"]
        self._phase(project, f"Capturando la referencia a {', '.join(str(w) for w in widths)} px (dos cargas por anchura) y sus recursos…")
        out = self.svc.browser.remake_capture(url=url, widths=widths, out_dir=cap, wait_ms=800)
        if "error" in out:
            if out.get("wall"):
                raise ValueError(f"{_host(url)} muestra una comprobación anti-robots a las visitas automáticas y Vitruvius no la sortea. "
                                 "Prueba con una captura de la página o con otra web.")
            raise ValueError("No se pudo capturar la referencia: " + str(out["error"]) + (f" ({out['hint']})" if out.get("hint") else ""))
        sensitive = out.get("sensitive") or {}
        if sensitive.get("password") or sensitive.get("card"):
            raise ValueError("La página muestra un formulario de " + ("inicio de sesión" if sensitive.get("password") else "pago")
                             + ": no se rehace, porque una copia así sirve para suplantarla. Elige una página pública de contenido.")
        heights: dict[str, int] = {}
        for c in out.get("captures") or []:
            if c.get("load") == 1:
                heights[str(c["width"])] = int(c.get("document_height") or 0)
        missing = [w for w in widths if not (cap / f"reference-{w}-1.png").is_file()]
        if missing:
            raise ValueError("No se pudo capturar la referencia a " + ", ".join(f"{w} px" for w in missing) + ": "
                             + "; ".join(out.get("errors") or []))
        outlines = out.get("outlines") or {}
        for w, outline in outlines.items():
            write_json_atomic(cap / f"outline-{w}.json", outline)
        final_url = out.get("final_url") or url
        origin = _host(final_url)
        self._phase(project, "Guardando el CSS, las imágenes y las fuentes de la referencia…")
        ledger, _mapping = build_assets(out.get("assets") or [], site, origin_host=origin, keep_scripts=project["keep_scripts"])
        write_json_atomic(folder / "assets.json", ledger)
        shutil.rmtree(cap / "raw", ignore_errors=True)
        snapshot = (out.get("snapshot") or {}).get("html") or ""
        (cap / "snapshot.html").write_text(snapshot, encoding="utf-8")
        (cap / "document.html").write_text(out.get("document_html") or "", encoding="utf-8")
        first = outlines.get(str(widths[0])) or {}
        project["reference"] = {
            "url": final_url, "title": first.get("title", ""), "lang": first.get("lang", ""), "heights": heights,
            "browser": out.get("browser"),
            "palette": first.get("palette") or [], "page_bg": first.get("page_bg"), "fonts": first.get("fonts") or [],
            "assets": sum(1 for r in ledger if r.get("local")), "bytes": sum(r.get("bytes") or 0 for r in ledger),
            "errors": (out.get("errors") or [])[:10], "loads": 2, "truncated_layout": bool(first.get("truncated")),
        }
        write_json_atomic(folder / "slots.json", slots(first, ledger, origin_host=origin, page_url=final_url))
        project["captured"] = True
        save(self.data_dir, project)

    def _ledger(self, project: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
        ledger = _read_json(project_dir(self.data_dir, project["id"]) / "assets.json", []) or []
        return ledger, {row["url"]: row["local"] for row in ledger if row.get("local")}

    def _outline(self, project: dict[str, Any], width: int, round_n: Optional[int] = None) -> Optional[dict[str, Any]]:
        folder = project_dir(self.data_dir, project["id"])
        path = folder / "capture" / f"outline-{width}.json" if round_n is None else folder / "rounds" / str(round_n) / f"outline-{width}.json"
        return _read_json(path)

    # ------------------------------------------------------------------ rounds
    def _first_round(self, project: dict[str, Any]) -> None:
        folder = project_dir(self.data_dir, project["id"])
        if project["mode"] == "copy":
            self._phase(project, "Montando la copia: el HTML de la página, su CSS y sus recursos…")
            ledger, mapping = self._ledger(project)
            cap = folder / "capture"
            final_url = project["reference"]["url"]
            raw = _read(cap / "document.html") if project["keep_scripts"] else ""
            raw = absolutize_markup(raw, final_url) if raw.strip() else _read(cap / "snapshot.html")
            html, removed = clean_html(raw, keep_scripts=project["keep_scripts"], source_url=final_url)
            html = rewrite_urls(html, mapping, "")
            project["reference"]["trackers_removed"] = removed[:50]
            note = "Copia de la página con su propio HTML, CSS y recursos" + (" (scripts conservados)" if project["keep_scripts"] else " (sin scripts)")
            self._write_site(project, html)
            self._score_round(project, 0, "copy", note, html)
            return
        self._phase(project, "El modelo escribe la primera versión de la página…")
        html, info = self._model_first(project)
        self._write_site(project, html)
        self._score_round(project, 0, "model", f"Primera versión escrita por el modelo ({info})", html)

    def _write_site(self, project: dict[str, Any], html: str) -> None:
        site = project_dir(self.data_dir, project["id"]) / "site"
        site.mkdir(parents=True, exist_ok=True)
        (site / "index.html").write_text(html, encoding="utf-8")

    def _restore_best(self, project: dict[str, Any]) -> None:
        folder = project_dir(self.data_dir, project["id"])
        best = folder / "rounds" / str(project["rounds"][project["best_round"]]["n"]) / "index.html"
        if best.is_file():
            shutil.copyfile(best, folder / "site" / "index.html")

    def _score_round(self, project: dict[str, Any], n: int, kind: str, note: str, html: str, *, fixes_css: Optional[str] = None,
                     extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        from PIL import Image
        from . import parity as parity_mod
        self._phase(project, f"Ronda {n}: midiendo la paridad pantalla a pantalla…")
        t0 = time.monotonic()
        folder = project_dir(self.data_dir, project["id"])
        round_dir = folder / "rounds" / str(n)
        round_dir.mkdir(parents=True, exist_ok=True)
        (round_dir / "index.html").write_text(html, encoding="utf-8")
        if fixes_css is not None:
            (round_dir / "fixes.css").write_text(fixes_css, encoding="utf-8")
        tmp = folder / "tmp" / f"round-{n}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        widths = project["widths"]
        out = self.svc.browser.parity_capture(url=MOUNT_ORIGIN + "/index.html", widths=widths, loads=1, out_dir=tmp, tag="candidate",
                                              wait_ms=600, mount={"origin": MOUNT_ORIGIN, "root": str(folder / "site")}, outline=True)
        if "error" in out:
            raise ValueError("No se pudo cargar la candidata: " + str(out["error"]) + (f" ({out['hint']})" if out.get("hint") else ""))
        run_id = uuid.uuid4().hex[:12]
        run_folder = parity_mod.run_dir(self.data_dir, run_id)
        run_folder.mkdir(parents=True, exist_ok=True)
        errors = list(out.get("errors") or [])
        results = []
        by_width = {c["width"]: c for c in out.get("captures") or [] if c.get("load", 1) == 1}
        cap = folder / "capture"
        for w in widths:
            shot = by_width.get(w)
            if not shot:
                errors.append(f"{w} px: no se pudo capturar la candidata")
                continue
            ref_paths = [p for p in (cap / f"reference-{w}-1.png", cap / f"reference-{w}-2.png") if p.is_file()]
            images = [Image.open(p) for p in ref_paths] + [Image.open(shot["path"])]
            try:
                for img in images:
                    img.load()
                entry = parity_mod.compare_widths_images(
                    images[:-1], images[-1], width=w, vh=parity_mod.viewport_height(w), max_screens=40, tolerance=project["tolerance"],
                    pass_score=project["pass_score"], height_tolerance=4, out_dir=run_folder,
                    ref_document_height=(project["reference"].get("heights") or {}).get(str(w)), cand_document_height=shot.get("document_height"))
            finally:
                for img in images:
                    img.close()
            shutil.copyfile(ref_paths[0], run_folder / f"reference-{w}.png")
            shutil.copyfile(shot["path"], run_folder / f"candidate-{w}.png")
            if shot.get("outline"):
                write_json_atomic(round_dir / f"outline-{w}.json", shot["outline"])
            results.append(entry)
        if not results:
            shutil.rmtree(run_folder, ignore_errors=True)
            raise ValueError("No se pudo medir ninguna anchura: " + "; ".join(errors))
        summary = parity_mod.summarize(results, errors)
        source_label = project["reference"].get("url") or "captura de la página"
        run = {"id": run_id, "created_ts": time.time(), "label": f"Rehacer · {_host(source_label) or 'captura'} · ronda {n}",
               "reference": {"kind": "remake", "label": source_label}, "candidate": {"kind": "remake", "label": f"ronda {n} del proyecto {project['id']}"},
               "params": {"widths": widths, "max_screens": 40, "tolerance": project["tolerance"], "pass_score": project["pass_score"], "height_tolerance": 4, "dark": False},
               "widths": results, "summary": summary, "passed": summary["passed"], "ms": round((time.monotonic() - t0) * 1000), "remake_id": project["id"]}
        parity_mod.save_run(self.data_dir, run)
        project["missing"] = [m for m in out.get("missing") or [] if m not in (project.get("unfetchable") or [])][:200]
        score = round_score(results)
        rnd = {"n": n, "kind": kind, "note": note, "parity_id": run_id, "score": score, "passed": summary["passed"],
               "widths": [{"width": r["width"], "score": r["score"], "min_screen": r["min_screen_score"], "passed": r["passed"],
                           "failing": r["failing_screens"], "screens": r["screens_checked"], "reference_height": r["reference_height"],
                           "candidate_height": r["candidate_height"], "height_pass": r["height_pass"]} for r in results],
               "failures": summary["failures"][:12], "missing": len(project["missing"]), "ms": round((time.monotonic() - t0) * 1000), "ts": time.time()}
        rnd.update(extra or {})
        best_i = project.get("best_round")
        best = project["rounds"][best_i] if best_i is not None else None
        kept = best is None or (rnd["passed"] and not best["passed"]) or (rnd["passed"] == best["passed"] and score > best["score"] + 0.005)
        rnd["kept"] = bool(kept)
        project["rounds"].append(rnd)
        if kept:
            project.update(best_round=len(project["rounds"]) - 1, best_score=score, passed=rnd["passed"], last_reverted=None)
        else:
            project["last_reverted"] = {"round": n, "from": best["score"], "to": score}
            self._restore_best(project)
        shutil.rmtree(tmp, ignore_errors=True)
        save(self.data_dir, project)
        return rnd

    def _failed_round(self, project: dict[str, Any], n: int, kind: str, error: str, note: str = "") -> dict[str, Any]:
        rnd = {"n": n, "kind": kind, "note": note or "Sin cambios", "error": error[:400], "parity_id": None, "score": None,
               "passed": False, "kept": False, "widths": [], "ts": time.time()}
        project["rounds"].append(rnd)
        save(self.data_dir, project)
        return rnd

    def _loop(self, project: dict[str, Any], budget: int) -> None:
        stale = 0
        model_errors = 0
        project["stop_reason"] = None
        for _ in range(max(0, int(budget))):
            self._check(project)
            if project.get("passed"):
                break
            n = len(project["rounds"])
            if project.get("missing") and project["source"]["kind"] == "url":
                rnd = self._fetch_round(project, n)
                if rnd is not None:
                    stale = 0 if rnd.get("kept") else stale + 1
                    continue
            before = project.get("best_score") or 0.0
            try:
                rnd = self._model_round(project, n)
                model_errors = 0
            except Cancelled:
                raise
            except Exception as error:  # noqa: BLE001 - one bad answer is a lost round, two in a row stop the job
                log.warning("remake model round failed", exc_info=True)
                rnd = self._failed_round(project, n, "model", f"{type(error).__name__}: {error}")
                model_errors += 1
                if model_errors >= 2:
                    project["stop_reason"] = "El modelo falló dos rondas seguidas: " + rnd["error"]
                    break
            improved = bool(rnd.get("kept")) and (project.get("best_score") or 0.0) > before
            stale = 0 if improved or project.get("passed") else stale + 1
            if stale >= STALE_ROUNDS:
                project["stop_reason"] = f"{STALE_ROUNDS} rondas seguidas sin mejorar."
                break

    def _fetch_round(self, project: dict[str, Any], n: int) -> Optional[dict[str, Any]]:
        """Files the candidate asked for and did not have: fetched from the original, one at a time, then scored again."""
        folder = project_dir(self.data_dir, project["id"])
        site = folder / "site"
        ledger, mapping = self._ledger(project)
        by_local = {row["local"]: row for row in ledger if row.get("local")}
        final_url = project["reference"].get("url") or project["source"].get("url") or ""
        wanted: dict[str, str] = {}
        for path in project.get("missing") or []:
            if path.startswith("assets/"):
                row = by_local.get(path)
                bits = path.split("/", 2)
                url = row["url"] if row else (f"https://{bits[1]}/{bits[2]}" if len(bits) == 3 else None)
            else:
                url = urljoin(final_url, "/" + path)  # every address of the copy is absolute or under assets/: the rest hang from the root
            if url:
                wanted[url] = path
        project["missing"] = []
        if not wanted:
            return None
        self._phase(project, f"Ronda {n}: descargando {len(wanted)} ficheros que la copia pedía y no tenía…")
        out = self.svc.browser.fetch_files(urls=list(wanted), out_dir=folder / "tmp" / "fetch")
        got = 0
        origin = _host(final_url)
        css_rows = []
        for entry in out.get("files") or []:
            rel = wanted.get(entry.get("url") or "")
            if not rel or not entry.get("file"):
                continue
            try:
                target = safe_file(site, rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(entry["file"], target)
            except (OSError, PermissionError):
                continue
            kind = asset_kind(entry.get("content_type", ""), "", entry["url"])
            row = {"url": entry["url"], "local": rel, "kind": kind, "content_type": entry.get("content_type", ""), "bytes": target.stat().st_size,
                   "licence": licence_for(entry["url"], kind, origin), "fetched_later": True}
            ledger.append(row)
            mapping[entry["url"]] = rel
            if kind == "styles":
                css_rows.append((row, target))
            got += 1
        for row, target in css_rows:
            css = target.read_bytes().decode("utf-8", errors="replace")
            target.write_text(rewrite_urls(absolutize_css(css, row["url"]), mapping, posixpath.dirname(row["local"])), encoding="utf-8")
        fetched = {e.get("url") for e in out.get("files") or []}
        project["unfetchable"] = sorted(set(project.get("unfetchable") or []) | {p for u, p in wanted.items() if u not in fetched})[:500]
        write_json_atomic(folder / "assets.json", ledger)
        if not got:
            save(self.data_dir, project)
            return None
        html = _read(site / "index.html")
        best = project["rounds"][project["best_round"]]
        fixes = _read(folder / "rounds" / str(best["n"]) / "fixes.css") if (folder / "rounds" / str(best["n"]) / "fixes.css").is_file() else None
        return self._score_round(project, n, "fetch", f"Descargados {got} de {len(wanted)} ficheros que faltaban", html, fixes_css=fixes)

    def _focus_label(self, focus: list[dict[str, Any]]) -> str:
        return " y ".join(f"pantalla {f['index'] + 1} a {f['width']} px" for f in focus) or "la página"

    def _model_round(self, project: dict[str, Any], n: int) -> dict[str, Any]:
        from . import parity as parity_mod
        folder = project_dir(self.data_dir, project["id"])
        best = project["rounds"][project["best_round"]]
        run = parity_mod.get_run(self.data_dir, best["parity_id"])
        focus = focus_screens(run["widths"])[:2]
        if not focus:
            return self._failed_round(project, n, "model", "No hay pantallas que corregir.")
        self._phase(project, f"Ronda {n}: el modelo corrige {self._focus_label(focus)}…")
        _ledger, mapping = self._ledger(project)
        sections, images = [], []
        vision = project.get("vision", True)
        for f in focus:
            w, y0 = f["width"], f["y"]
            y1 = y0 + (f["height"] or f.get("viewport_height") or 900)
            ref_o, cand_o = self._outline(project, w), self._outline(project, w, best["n"])
            diff = screen_diff(ref_o, cand_o, y0, y1, mapping=mapping)
            text = (f"SCREEN {f['index'] + 1} at {w} px wide (page rows {y0}..{y1}), {f['score']} % of its stable pixels match.\n"
                    "Differences, reference → candidate:\n" + ("\n".join(diff) if diff else "(no element-level difference found: compare the pictures)"))
            if ref_o:
                text += "\nReference layout in this screen (y x width x height tag selector | style | text):\n" + outline_text(ref_o, mapping=mapping, y_range=(y0, y1), limit=70, max_chars=9000)
            sections.append(text)
            if vision:
                for path in (folder / "capture" / f"reference-{w}-1.png", parity_mod.run_dir(self.data_dir, best["parity_id"]) / f"candidate-{w}.png"):
                    pic = png_screen(path, y0, y1 - y0)
                    if pic:
                        images.append(pic)
        header = [f"REFERENCE: {project['reference'].get('url') or 'the attached screenshot'}", f"ROUND {n}. Scores now:"]
        for w in best["widths"]:
            header.append(f"- {w['width']} px: {w['score']} % (lowest screen {w['min_screen']} %), failing screens {w['failing'] or 'none'}, "
                          f"page height reference {w['reference_height']} px vs candidate {w['candidate_height']} px")
        if project.get("note"):
            header.append("INSTRUCTIONS FROM THE USER: " + project["note"])
        if project.get("last_reverted"):
            lr = project["last_reverted"]
            header.append(f"Your previous answer lowered the score ({lr['from']} % → {lr['to']} %) and was undone: try a different fix.")
        if images:
            header.append("Pictures: for each screen, first the reference, then the current candidate.")
        user = "\n".join(header) + "\n\n" + "\n\n".join(sections)
        current = _read(folder / "rounds" / str(best["n"]) / "index.html")
        if project["mode"] == "copy":
            fixes = _read(folder / "rounds" / str(best["n"]) / "fixes.css")
            user += ("\n\nCSS fixes applied now (your answer replaces them, so keep the ones that still help):\n```css\n" + fixes + "\n```")
            answer = self._chat(project, system_prompt("copy", project["widths"], repair=True), user, images)
            css = extract_block(answer, "css")
            if not css or "{" not in css:
                return self._failed_round(project, n, "model", "El modelo no devolvió CSS utilizable.")
            html = insert_fixes(current, css)
            self._write_site(project, html)
            lines = len([ln for ln in css.splitlines() if ln.strip()])
            return self._score_round(project, n, "model", f"CSS de corrección del modelo para {self._focus_label(focus)} ({lines} líneas)", html,
                                     fixes_css=css, extra={"focus": focus})
        user += "\n\nCURRENT FILE (index.html):\n```html\n" + current[:90000] + "\n```"
        answer = self._chat(project, system_prompt("rebuild", project["widths"], repair=True), user, images)
        if has_edits(answer):
            html, applied, failed = apply_edits(current, answer)
            if not applied:
                return self._failed_round(project, n, "model", f"Ninguna de las {failed} ediciones del modelo encajaba con el fichero.")
            how = f"{applied} ediciones" + (f" ({failed} no encajaban)" if failed else "")
        else:
            html = extract_block(answer, "html")
            if not html or "<" not in html:
                return self._failed_round(project, n, "model", "El modelo no devolvió ni ediciones ni un HTML completo.")
            how = "fichero completo reescrito"
        html = self._finish_model_html(project, html)
        self._write_site(project, html)
        return self._score_round(project, n, "model", f"Correcciones del modelo en {self._focus_label(focus)}: {how}", html, extra={"focus": focus})

    def _finish_model_html(self, project: dict[str, Any], html: str) -> str:
        html = strip_scripts(html)
        if (project_dir(self.data_dir, project["id"]) / "site" / "assets" / "fonts.css").is_file():
            html = ensure_fonts_link(html)
        return html

    def _model_first(self, project: dict[str, Any]) -> tuple[str, str]:
        folder = project_dir(self.data_dir, project["id"])
        site, cap = folder / "site", folder / "capture"
        widths = project["widths"]
        ref = project["reference"]
        images: list[bytes] = []
        if project["source"]["kind"] == "image":
            from . import parity as parity_mod
            w = widths[0]
            h = ref["heights"][str(w)]
            vh = parity_mod.viewport_height(w)
            for y in range(0, min(h, vh * 6), vh):
                pic = png_screen(cap / f"reference-{w}-1.png", y, vh, max_width=1000)
                if pic:
                    images.append(pic)
            palette = ", ".join(p["c"] for p in ref.get("palette") or [])
            user = (f"The reference is the attached screenshot of a full page, {w} px wide and {h} px tall, cut into screens of {vh} px "
                    f"from the top ({len(images)} pictures, in order). Rebuild it at {w} px wide; the page must be {h} px tall.\n"
                    f"Main colours of the screenshot: {palette}.\nThere are no local files: draw images as CSS shapes or neutral "
                    "placeholders of the same size and colour, never as pictures of the reference.")
        else:
            ledger, mapping = self._ledger(project)
            inline_css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", _read(cap / "snapshot.html"), re.S | re.I))
            css, families = fonts_css(site, ledger, inline_css)
            fonts_line = "(none downloaded: use the closest system fonts)"
            if css:
                (site / "assets").mkdir(parents=True, exist_ok=True)
                (site / "assets" / "fonts.css").write_text(css, encoding="utf-8")
                fonts_line = "link assets/fonts.css, it declares: " + "; ".join(sorted({f"{f['family']} {f['weight']} {f['style']}" for f in families}))[:3000]
            pics = [f"{r['local']}" for r in ledger if r.get("kind") == "images" and r.get("local")]
            parts = [f"REFERENCE: {ref.get('url')}", f"Title: {ref.get('title', '')}", f"Language: {ref.get('lang') or 'unknown'}",
                     f"Page background: {ref.get('page_bg') or '#ffffff'}",
                     "Page heights: " + ", ".join(f"{w} px wide → {ref['heights'].get(str(w))} px tall" for w in widths),
                     "Palette (most used first): " + ", ".join(p["c"] for p in ref.get("palette") or []),
                     "FONTS: " + fonts_line,
                     "LOCAL IMAGES (use these paths): " + (", ".join(pics[:120]) if pics else "(none)")]
            for i, w in enumerate(widths):
                outline = self._outline(project, w)
                parts.append(f"\nLAYOUT AT {w} px (y x width x height tag selector | font/line-height colours | text):\n"
                             + outline_text(outline, mapping=mapping, limit=260 if i == 0 else 160, max_chars=40000 if i == 0 else 20000))
            user = "\n".join(parts)
            if project.get("note"):
                user += "\nINSTRUCTIONS FROM THE USER: " + project["note"]
            if project.get("vision", True):
                from . import parity as parity_mod
                for w in widths:
                    pic = png_screen(cap / f"reference-{w}-1.png", 0, parity_mod.viewport_height(w))
                    if pic:
                        images.append(pic)
                if images:
                    user += "\nPictures: the first screen of the reference at each width, widest first."
        answer = self._chat(project, system_prompt("rebuild", widths, repair=False), user, images)
        html = extract_block(answer, "html")
        if not html or "<" not in html:
            raise ValueError("El modelo no devolvió un HTML utilizable en la primera versión.")
        return self._finish_model_html(project, html), f"modelo {project.get('model') or 'global'}"

    def _chat(self, project: dict[str, Any], system: str, user: str, images: list[bytes]) -> str:
        link = getattr(self.svc, "link_sync", None)
        if link is None:
            raise ValueError("No hay modelo disponible: elige el modelo global de la familia en Faustus.")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        use_images = bool(images) and project.get("vision", True)
        phase = project.get("phase") or ""
        effort, shortened = "medium", False
        for attempt in range(9):
            if attempt:
                self._phase(project, phase + " (reintento)")
            try:
                result = link.chat(messages, images=images if use_images else None, effort=effort, max_tokens=MODEL_MAX_TOKENS, task="code")
            except Exception as error:  # noqa: BLE001
                if not shortened and re.search(r"did not complete|length|max_tokens", str(error), re.I):
                    # the answer ran out of room: think less and write tighter code
                    shortened, effort = True, "low"
                    messages = [messages[0], {"role": "user", "content": messages[1]["content"] + "\n\nYour previous answer ran out of room: "
                                              "think briefly, write compact CSS without comments and reuse classes."}]
                    continue
                if use_images and re.search(r"vision|image", str(error), re.I):
                    use_images = False
                    project["vision"] = False
                    continue
                if attempt < 8 and re.search(r"Connect|ReadError|RemoteProtocol|Timeout|503|502", f"{type(error).__name__} {error}"):
                    # Faustus or the model server restarting: wait (up to four minutes) and ask again instead of losing the round
                    self._phase(project, f"El modelo no responde ({type(error).__name__}); reintento {attempt + 1} de 8 en 30 s…")
                    for _ in range(30):
                        time.sleep(self.retry_pause)
                        self._check(project)
                    continue
                raise
            text = result.text if hasattr(result, "text") else (result.get("text") if isinstance(result, dict) else str(result))
            project["model"] = getattr(result, "model", None) or (result.get("model") if isinstance(result, dict) else None) or project.get("model")
            return text or ""
        return ""

    # ------------------------------------------------------------------ output
    def _site_files(self, folder: Path) -> list[dict[str, Any]]:
        site = folder / "site"
        if not site.is_dir():
            return []
        return [{"path": f.relative_to(site).as_posix(), "bytes": f.stat().st_size} for f in sorted(site.rglob("*")) if f.is_file()]

    @staticmethod
    def _rounds_summary(project: dict[str, Any]) -> dict[str, Any]:
        return {"source": project["source"], "mode": project["mode"], "widths": project["widths"], "pass_score": project["pass_score"],
                "tolerance": project["tolerance"], "passed": project.get("passed"), "best_round": project.get("best_round"),
                "best_score": project.get("best_score"), "model": project.get("model"),
                "rounds": [{k: r.get(k) for k in ("n", "kind", "note", "score", "passed", "kept", "widths", "failures", "error")} for r in project.get("rounds") or []]}

    @staticmethod
    def _with_urls(project: dict[str, Any]) -> dict[str, Any]:
        base = f"/api/remake/{project['id']}"
        out = dict(project)
        out.update(site_url=f"{base}/site/index.html", report_url=f"{base}/report", download_url=f"{base}/download", code_url=f"{base}/code")
        out["rounds"] = [dict(r, parity_report_url=f"/api/parity/{r['parity_id']}/report" if r.get("parity_id") else None) for r in project.get("rounds") or []]
        return out


def credits_markdown(project: dict[str, Any], ledger: list[dict[str, Any]]) -> str:
    source = project["source"].get("url") or "una captura de pantalla"
    lines = ["# Créditos y licencias", "",
             f"Proyecto rehecho por Vitruvius's Hoard a partir de {source} "
             f"({time.strftime('%d-%m-%Y', time.localtime(project.get('created_ts') or time.time()))}).",
             "Los textos, imágenes, logotipos y fuentes del original pertenecen a sus dueños: cámbialos o pide permiso antes de publicar.", "",
             "| Fichero | Origen | Licencia |", "| --- | --- | --- |"]
    for row in ledger:
        if row.get("local"):
            lines.append(f"| `{row['local']}` | {row['url']} | {row.get('licence', '')} |")
    return "\n".join(lines) + "\n"


def report_html(project: dict[str, Any]) -> str:
    esc = html_lib.escape
    rows = []
    for r in project.get("rounds") or []:
        widths = " · ".join(f"{w['width']} px {w['score']} %" + (" ✓" if w["passed"] else "") for w in r.get("widths") or []) or esc(r.get("error") or "")
        link = f'<a href="../../parity/{esc(r["parity_id"])}/report">comparar</a>' if r.get("parity_id") else ""
        best = " (mejor)" if project.get("best_round") is not None and project["rounds"][project["best_round"]]["n"] == r["n"] else ""
        rows.append(f"<tr><td>{r['n']}{best}</td><td>{esc(r.get('note') or '')}</td><td>{widths}</td><td>{'sí' if r.get('passed') else 'no'}</td>"
                    f"<td>{'sí' if r.get('kept') else 'no'}</td><td>{link}</td></tr>")
    verdict = esc(project.get("phase") or "")
    return ("<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Rehacer {esc(project['id'])}</title><style>body{{font:14px/1.5 system-ui,sans-serif;margin:0;background:#f6f7f9;color:#14171c}}"
            "main{max-width:1100px;margin:0 auto;padding:16px}table{width:100%;border-collapse:collapse;background:#fff}"
            "td,th{border-bottom:1px solid #d9dde4;padding:6px 8px;text-align:left;vertical-align:top}"
            "@media (prefers-color-scheme:dark){body{background:#0f1218;color:#e8ebf0}table{background:#171b23}td,th{border-color:#2a303b}a{color:#7f95ff}}"
            "</style></head><body><main>"
            f"<h1>Rehacer · {esc(project['source'].get('url') or 'captura')}</h1><p>{verdict}</p>"
            f"<p>Modo: {'copia de la página' if project['mode'] == 'copy' else 'reconstrucción con el modelo'} · anchuras {', '.join(str(w) for w in project['widths'])} px"
            f" · pasa con {project['pass_score']} % · <a href=\"site/index.html\">abrir el resultado</a> · <a href=\"download\">descargar ZIP</a></p>"
            "<table><thead><tr><th>Ronda</th><th>Qué se hizo</th><th>Paridad</th><th>Pasa</th><th>Conservada</th><th></th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></main></body></html>")
