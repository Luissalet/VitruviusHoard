"""The Playwright worker: one background thread owning a sync Playwright
instance, fed through a queue.Queue, one page at a time. Launches lazily on
the first job. Jobs never block the asyncio event loop — callers submit a
job and wait on a threading.Event-backed future with a timeout.

Tests never touch this module's real browser: they inject a ``FakeBrowser``
(same public interface: ``capture`` and ``probe``) through ``Services``.

Which browser to start (`hoard_link.web.browser`: system Chrome / Edge, Playwright's Chromium wherever it was installed),
which URLs may be opened (`hoard_link.web.safety`: public hosts only; every redirect and every sub-request the page makes is
checked too) and how the scroll video is encoded (`hoard_link.media`) are the shared Hoard Link pieces.
"""

from __future__ import annotations

import logging
import os
import queue
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from .hoard_link.media import bins as media_bins
from .hoard_link.media.ffmpeg import FFmpeg
from .hoard_link.web import browser as web_browser
from .hoard_link.web import safety

log = logging.getLogger("vitruvius.browser")

# The probe JS: must never throw. Every metric is wrapped in try/catch and
# missing/failed metrics are simply omitted or null.
PROBE_JS = r"""
() => {
  const out = {};
  const safe = (key, fn) => { try { out[key] = fn(); } catch (e) { out[key] = null; out[key + "_error"] = String(e && e.message || e); } };

  safe("page_meta", () => {
    const meta = (name) => { const el = document.querySelector(`meta[name="${name}"], meta[property="${name}"]`); return el ? (el.getAttribute("content") || "") : ""; };
    return { title: document.title || "", description: meta("description") || meta("og:description"), og_title: meta("og:title"), og_image: meta("og:image"), lang: document.documentElement.lang || "" };
  });

  safe("viewport_meta", () => {
    const m = document.querySelector('meta[name="viewport"]');
    return m ? m.getAttribute("content") : null;
  });
  safe("lang", () => document.documentElement.lang || null);

  safe("fonts", () => {
    const families = new Set();
    try { document.fonts.forEach(f => families.add(f.family)); } catch (e) {}
    const pick = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      return getComputedStyle(el).fontFamily;
    };
    return { loaded: Array.from(families), h1: pick("h1"), h2: pick("h2"), p: pick("p"), button: pick("button") };
  });

  safe("colors", () => {
    const seen = new Map();
    const all = Array.from(document.querySelectorAll("*")).slice(0, 2000);
    const sized = all.map(el => {
      const r = el.getBoundingClientRect();
      return { el, area: r.width * r.height };
    }).sort((a, b) => b.area - a.area).slice(0, 300);
    for (const { el } of sized) {
      const cs = getComputedStyle(el);
      const key = cs.color + "|" + cs.backgroundColor;
      if (!seen.has(key)) seen.set(key, { color: cs.color, background: cs.backgroundColor, count: 0 });
      seen.get(key).count += 1;
    }
    return Array.from(seen.values()).slice(0, 40);
  });

  safe("heading_order", () => {
    const heads = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6"));
    return heads.map(h => parseInt(h.tagName[1], 10));
  });

  safe("images_without_alt", () => {
    return Array.from(document.querySelectorAll("img")).filter(img => !img.hasAttribute("alt")).length;
  });

  safe("small_tap_targets", () => {
    const targets = Array.from(document.querySelectorAll("button,a"));
    let count = 0;
    for (const t of targets) {
      const r = t.getBoundingClientRect();
      if (r.width > 0 && r.height > 0 && (r.width < 44 || r.height < 44)) count += 1;
    }
    return count;
  });

  safe("contrast_pairs", () => {
    const nodes = [];
    const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode()) && nodes.length < 400) {
      if (n.textContent && n.textContent.trim().length > 1) nodes.push(n.parentElement);
    }
    const pairs = [];
    const firstStop = (img) => { const m = (img || "").match(/rgba?\([^)]*\)/); return m ? m[0] : null; };
    const effectiveBg = (el) => {
      // Walk up until a non-transparent background (or the first stop of a gradient).
      let node = el;
      while (node && node !== document.documentElement) {
        const cs = getComputedStyle(node);
        const bg = cs.backgroundColor || "";
        const m = bg.match(/rgba?\(([^)]*)\)/);
        if (m) { const parts = m[1].split(",").map(Number); if (parts.length < 4 || parts[3] > 0.05) return bg; }
        const stop = firstStop(cs.backgroundImage);
        if (stop) return stop;
        node = node.parentElement;
      }
      const root = getComputedStyle(document.documentElement).backgroundColor;
      return (/rgba\(.*, ?0\)/.test(root) || root === "transparent") ? "rgb(255, 255, 255)" : root;
    };
    const seen = new Set();
    for (const el of nodes) {
      if (!el || seen.has(el)) continue;
      seen.add(el);
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none" || parseFloat(cs.fontSize) < 6) continue;
      pairs.push({ color: cs.color, background: effectiveBg(el), text: (el.textContent || "").trim().slice(0, 40), size: parseFloat(cs.fontSize), weight: cs.fontWeight });
    }
    return pairs.slice(0, 200);
  });

  safe("reduced_motion_css_present", () => {
    for (const sheet of document.styleSheets) {
      try {
        for (const rule of sheet.cssRules || []) {
          if (rule.media && rule.media.mediaText && rule.media.mediaText.includes("prefers-reduced-motion")) return true;
        }
      } catch (e) { /* cross-origin sheet */ }
    }
    return false;
  });

  safe("color_scheme_present", () => {
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) return true;
    for (const sheet of document.styleSheets) {
      try {
        for (const rule of sheet.cssRules || []) {
          if (rule.style && rule.style.getPropertyValue && rule.style.getPropertyValue("color-scheme")) return true;
          if (rule.media && rule.media.mediaText && rule.media.mediaText.includes("prefers-color-scheme")) return true;
        }
      } catch (e) {}
    }
    return false;
  });

  safe("animations_count", () => {
    let count = 0;
    for (const el of document.querySelectorAll("*")) {
      try { count += el.getAnimations().length; } catch (e) {}
    }
    return count;
  });

  safe("scroll_driven_count", () => {
    let count = 0;
    for (const el of document.querySelectorAll("*")) {
      const cs = getComputedStyle(el);
      if (cs.animationTimeline && cs.animationTimeline !== "auto") count += 1;
    }
    return count;
  });

  safe("external_libs", () => {
    const w = window;
    const libs = [];
    if (w.gsap) libs.push("gsap");
    if (w.Motion || w.framerMotion) libs.push("framer-motion");
    if (w.Lenis) libs.push("lenis");
    if (w.THREE) libs.push("three");
    if (w.Swiper) libs.push("swiper");
    if (w.lottie) libs.push("lottie");
    if (w.anime) libs.push("anime");
    if (w.AOS) libs.push("aos");
    if (w.LocomotiveScroll) libs.push("locomotive-scroll");
    return libs;
  });

  safe("dom_size", () => document.querySelectorAll("*").length);

  safe("font_sizes", () => {
    const sizes = new Set();
    for (const sel of ["h1", "h2", "h3", "h4", "p", "span", "a", "button"]) {
      for (const el of Array.from(document.querySelectorAll(sel)).slice(0, 20)) {
        sizes.add(getComputedStyle(el).fontSize);
      }
    }
    return Array.from(sizes);
  });

  safe("long_paragraphs", () => {
    let count = 0;
    for (const p of Array.from(document.querySelectorAll("p")).slice(0, 100)) {
      const r = p.getBoundingClientRect();
      const fs = parseFloat(getComputedStyle(p).fontSize) || 16;
      if (r.width > 0 && r.width / (fs * 0.5) > 90) count += 1;
    }
    return count;
  });

  safe("long_transition_count", () => {
    let count = 0;
    for (const el of Array.from(document.querySelectorAll("*")).slice(0, 1000)) {
      const cs = getComputedStyle(el);
      const durations = (cs.transitionDuration || "").split(",").map(s => parseFloat(s) || 0);
      if (durations.some(d => d > 0.8)) count += 1;
    }
    return count;
  });

  safe("linear_easing_count", () => {
    let count = 0;
    for (const el of Array.from(document.querySelectorAll("*")).slice(0, 1000)) {
      const cs = getComputedStyle(el);
      if ((cs.transitionTimingFunction || "").includes("linear") || (cs.animationTimingFunction || "").includes("linear")) count += 1;
    }
    return count;
  });

  safe("generic_defaults", () => {
    const fontsUsed = new Set();
    try { document.fonts.forEach(f => fontsUsed.add(f.family.replace(/["']/g, ""))); } catch (e) {}
    // The first family actually resolved for the text that matters.
    for (const sel of ["h1", "h2", "h3", "p", "a", "button", "li", "body"]) {
      const el = document.querySelector(sel);
      if (!el) continue;
      const fam = (getComputedStyle(el).fontFamily || "").split(",")[0].replace(/["']/g, "").trim();
      if (fam) fontsUsed.add(fam);
    }
    const GENERIC = ["inter", "roboto", "arial", "helvetica", "helvetica neue", "-apple-system", "system-ui", "segoe ui", "sans-serif", "blinkmacsystemfont", "ui-sans-serif", "times new roman", "serif"];
    const onlyGeneric = fontsUsed.size > 0 && Array.from(fontsUsed).every(f => GENERIC.includes(f.toLowerCase()));
    const buttons = Array.from(document.querySelectorAll("button, .btn, [class*=button], a[class*=cta], [role=button]")).slice(0, 30);
    let purpleBlueGradient = false;
    const hueOf = (rgb) => {
      const m = rgb.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/); if (!m) return null;
      const r = +m[1] / 255, g = +m[2] / 255, b = +m[3] / 255, max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
      if (d < 0.08) return null;
      let h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
      h = Math.round(h * 60); return h < 0 ? h + 360 : h;
    };
    for (const b of buttons) {
      const bg = getComputedStyle(b).backgroundImage || "";
      if (!bg.includes("gradient")) continue;
      const hues = (bg.match(/rgba?\([^)]*\)/g) || []).map(hueOf).filter(h => h !== null);
      // purple/violet (250-300) meeting blue (200-250) = the stock gradient
      if (hues.some(h => h >= 250 && h <= 300) && hues.some(h => h >= 195 && h < 250)) { purpleBlueGradient = true; break; }
    }
    const emojiIcons = /\p{Extended_Pictographic}/u.test((document.body && document.body.innerText || "").slice(0, 4000));
    const sections = document.querySelectorAll("section, main > div").length;
    return { fonts_only_generic: onlyGeneric, purple_blue_gradient_buttons: purpleBlueGradient, emoji_icons: emojiIcons, section_count: sections };
  });

  return out;
}
"""

# Layout measured at one viewport width (run after each resize): real sideways scroll with the elements that stick
# out, text cut by its own box (a line crossing the clipping edge, or whole lines hidden right below it; an ellipsis
# or line-clamp marks it as intended) and the visible ink of two text elements covering each other.
LAYOUT_JS = r"""
() => {
  const W = window.innerWidth;
  const sx = window.scrollX, sy = window.scrollY;
  const doc = document.documentElement;
  const out = {width: W, page_width: doc.scrollWidth, overflow_px: Math.max(0, doc.scrollWidth - W),
               overflowing: [], clipped: [], overlaps: []};
  const label = (el) => {
    let s = el.localName;
    if (el.id) s += '#' + el.id;
    const c = (typeof el.className === 'string' ? el.className : '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
    if (c.length) s += '.' + c.join('.');
    return s;
  };
  const words = (el) => (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60);
  const shown = (cs) => cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity || '1') > 0.05;
  const all = document.body ? Array.from(document.body.querySelectorAll('*')).slice(0, 5000) : [];
  const styles = new Map();
  const st = (el) => { let cs = styles.get(el); if (!cs) { cs = getComputedStyle(el); styles.set(el, cs); } return cs; };
  const hiddenByAncestor = (el) => { for (let p = el; p; p = p.parentElement) { const cs = st(p); if (!shown(cs)) return true; } return false; };
  const textRects = (el, deep) => {
    const rects = [];
    const range = document.createRange();
    const nodes = deep ? (() => { const a = []; const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let n; while ((n = w.nextNode())) a.push(n); return a; })()
                       : Array.from(el.childNodes).filter(n => n.nodeType === 3);
    for (const n of nodes) {
      if (!n.textContent.trim() || !n.parentElement || !shown(st(n.parentElement))) continue;
      range.selectNodeContents(n);
      for (const q of range.getClientRects()) if (q.width > 0.5 && q.height > 0.5) rects.push(q);
    }
    return rects;
  };

  // 1. Real sideways scroll: the innermost elements that stick out past the viewport, outside any scrolling or clipping box.
  if (out.overflow_px > 2) {
    const clippedX = (el) => { for (let p = el.parentElement; p && p !== document.body && p !== doc; p = p.parentElement) { if (st(p).overflowX !== 'visible') return true; } return false; };
    const off = [];
    for (const el of all) {
      const cs = st(el);
      if (!shown(cs) || cs.position === 'fixed') continue;
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1 || r.right <= W + 2) continue;
      if (clippedX(el)) continue;
      off.push({el, r});
    }
    const inner = off.filter(a => !off.some(b => b !== a && a.el.contains(b.el)));
    inner.sort((a, b) => b.r.right - a.r.right);
    out.overflowing = inner.slice(0, 6).map(({el, r}) => ({el: label(el), text: words(el), width: Math.round(r.width),
      right: Math.round(r.right + sx), by: Math.round(r.right - W)}));
  }

  // 2. Text cut by its own box: a line crossing the clipping edge, or whole lines hidden right below it.
  for (const el of all) {
    if (out.clipped.length >= 12) break;
    const cs = st(el);
    const clipX = cs.overflowX === 'hidden' || cs.overflowX === 'clip';
    const clipY = cs.overflowY === 'hidden' || cs.overflowY === 'clip';
    if ((!clipX && !clipY) || hiddenByAncestor(el)) continue;
    const box = el.getBoundingClientRect();
    if (box.width < 4 || box.height < 4) continue;
    const rects = textRects(el, true);
    if (!rects.length) continue;
    let crossX = 0, crossY = 0, below = 0;
    for (const q of rects) {
      const inX = q.right > box.left && q.left < box.right;
      if (clipY && inX && q.top < box.bottom - 1 && q.bottom > box.bottom + 1) crossY++;
      if (clipY && inX && q.top >= box.bottom - 1 && q.top < box.bottom + 4 * Math.max(q.height, 8)) below++;
      if (clipX && q.top < box.bottom && q.bottom > box.top && q.left < box.right - 1 && q.right > box.right + 1) crossX++;
    }
    if (!crossX && !crossY && !below) continue;
    const intended = cs.textOverflow === 'ellipsis' || (cs.webkitLineClamp && cs.webkitLineClamp !== 'none');
    out.clipped.push({el: label(el), text: words(el), axis: crossX ? (crossY || below ? 'both' : 'x') : 'y',
      lines_cut: crossX + crossY, lines_hidden: below, hidden_px: Math.round(crossX ? el.scrollWidth - el.clientWidth : el.scrollHeight - el.clientHeight),
      intended: !!intended});
  }

  // 3. Text over text: the visible ink of two separate text elements covering each other (ink cut by a clipping
  // ancestor does not count: it is not on screen).
  const clipCache = new Map();
  const clipOf = (el) => {
    if (!el || el === doc) return {l: -Infinity, t: -Infinity, r: Infinity, b: Infinity};
    if (clipCache.has(el)) return clipCache.get(el);
    const up = clipOf(el.parentElement);
    const cs = st(el);
    let c = up;
    if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') {
      const r = el.getBoundingClientRect();
      c = {l: cs.overflowX !== 'visible' ? Math.max(up.l, r.left) : up.l, r: cs.overflowX !== 'visible' ? Math.min(up.r, r.right) : up.r,
           t: cs.overflowY !== 'visible' ? Math.max(up.t, r.top) : up.t, b: cs.overflowY !== 'visible' ? Math.min(up.b, r.bottom) : up.b};
    }
    clipCache.set(el, c);
    return c;
  };
  const leaves = [];
  for (const el of all) {
    if (leaves.length >= 500) break;
    const cs = st(el);
    if (!shown(cs)) continue;
    const c = clipOf(el);
    const rects = textRects(el, false).map(q => ({left: Math.max(q.left, c.l), right: Math.min(q.right, c.r), top: Math.max(q.top, c.t), bottom: Math.min(q.bottom, c.b)}))
      .filter(q => q.right - q.left > 0.5 && q.bottom - q.top > 0.5).map(q => ({...q, width: q.right - q.left, height: q.bottom - q.top}));
    if (!rects.length) continue;
    let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
    for (const q of rects) { l = Math.min(l, q.left); t = Math.min(t, q.top); r = Math.max(r, q.right); b = Math.max(b, q.bottom); }
    if (r - l < 2 || b - t < 2 || hiddenByAncestor(el)) continue;
    leaves.push({el, rects, l, t, r, b});
  }
  const inkOverlap = (A, B) => {
    let area = 0;
    for (const p of A.rects) for (const q of B.rects) {
      const w = Math.min(p.right, q.right) - Math.max(p.left, q.left), h = Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top);
      if (w > 0 && h > 0) area += w * h;
    }
    return area;
  };
  const inkArea = (A) => A.rects.reduce((s, q) => s + q.width * q.height, 0);
  for (let i = 0; i < leaves.length && out.overlaps.length < 10; i++) {
    for (let j = i + 1; j < leaves.length && out.overlaps.length < 10; j++) {
      const A = leaves[i], B = leaves[j];
      if (A.r <= B.l || B.r <= A.l || A.b <= B.t || B.b <= A.t) continue;
      if (A.el.contains(B.el) || B.el.contains(A.el)) continue;
      const shared = inkOverlap(A, B);
      const share = shared / Math.max(1, Math.min(inkArea(A), inkArea(B)));
      if (share < 0.2) continue;
      out.overlaps.push({a: label(A.el), a_text: words(A.el), b: label(B.el), b_text: words(B.el), share: Math.round(share * 100),
        at: [Math.round(Math.max(A.l, B.l) + sx), Math.round(Math.max(A.t, B.t) + sy)]});
    }
  }
  return out;
}
"""


# A compact snapshot of the rendered DOM at one viewport width, for the render-time design rules: every visible element
# (capped) with its box in page coordinates and the handful of computed styles those rules read. Defaults are left out
# to keep it small. The rules read it in Python (``rules/dom.py``); nothing is judged here.
DOM_JS = r"""
() => {
  const CAP = 520;
  const W = window.innerWidth, H = window.innerHeight, sx = window.scrollX, sy = window.scrollY;
  const doc = document.documentElement;
  const out = {width: W, height: H, page_height: doc.scrollHeight, page_width: doc.scrollWidth, els: [], truncated: false};
  const body = document.body;
  if (!body) return out;
  const n = (v) => { const f = parseFloat(v); return isNaN(f) ? 0 : Math.round(f * 100) / 100; };
  const SKIP = new Set(['SCRIPT','STYLE','LINK','META','NOSCRIPT','TEMPLATE','HEAD','TITLE','BR','SOURCE','TRACK','WBR']);
  const SVG_INNER = (el) => el.namespaceURI === 'http://www.w3.org/2000/svg' && el.localName !== 'svg';
  const all = Array.from(body.querySelectorAll('*')).slice(0, 6000);
  const index = new Map(), refs = [];
  const put = (o, k, v, def) => { if (v !== def && v !== undefined && v !== null && v !== '') o[k] = v; };
  const first4 = (cs, a, b, c, d) => [n(cs[a]), n(cs[b]), n(cs[c]), n(cs[d])];
  const own = (el) => { let t = ''; for (const c of el.childNodes) if (c.nodeType === 3) t += c.textContent; return t.replace(/\s+/g, ' ').trim(); };
  const lineCount = (el) => {
    try {
      const range = document.createRange(); range.selectNodeContents(el);
      const tops = new Set(); for (const q of range.getClientRects()) if (q.width > 1 && q.height > 1) tops.add(Math.round(q.top / 4));
      return tops.size;
    } catch (e) { return 0; }
  };
  const lastLine = (el) => {
    try {
      const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let node, last = null;
      while ((node = w.nextNode())) if (node.textContent.trim()) last = node;
      if (!last) return null;
      const range = document.createRange(); range.selectNodeContents(last);
      const rects = Array.from(range.getClientRects()).filter(q => q.width > 1 && q.height > 1);
      if (!rects.length) return null;
      const bottom = Math.max(...rects.map(q => q.bottom));
      const lastRects = rects.filter(q => q.bottom > bottom - 2);
      const left = Math.min(...lastRects.map(q => q.left)), right = Math.max(...lastRects.map(q => q.right));
      return {w: Math.round(right - left), words: 0};
    } catch (e) { return null; }
  };
  for (const el of all) {
    if (out.els.length >= CAP) { out.truncated = true; break; }
    if (SKIP.has(el.tagName) || SVG_INNER(el)) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none') continue;
    const r = el.getBoundingClientRect();
    const text = own(el);
    const hasBox = r.width >= 1 && r.height >= 1;
    if (!hasBox && !text) continue;
    const rec = {i: out.els.length, tag: el.localName};
    let p = el.parentElement; while (p && !index.has(p)) p = p.parentElement;
    rec.p = p ? index.get(p) : -1;
    const cls = (typeof el.className === 'string' ? el.className : '').trim();
    put(rec, 'c', cls.slice(0, 80), '');
    put(rec, 'id', el.id, '');
    rec.r = [Math.round(r.left + sx), Math.round(r.top + sy), Math.round(r.width), Math.round(r.height)];
    put(rec, 't', text.slice(0, 120), '');
    if (text) rec.tl = text.length;
    const s = {};
    put(s, 'color', cs.color, '');
    put(s, 'bg', cs.backgroundColor, 'rgba(0, 0, 0, 0)');
    put(s, 'bgi', cs.backgroundImage.slice(0, 200), 'none');
    s.fs = n(cs.fontSize); s.fw = cs.fontWeight;
    s.ff = (cs.fontFamily || '').split(',')[0].replace(/["']/g, '').trim();
    if (cs.lineHeight !== 'normal') s.lh = n(cs.lineHeight);
    if (cs.letterSpacing !== 'normal') s.ls = n(cs.letterSpacing);
    put(s, 'tt', cs.textTransform, 'none');
    put(s, 'fst', cs.fontStyle, 'normal');
    put(s, 'ta', cs.textAlign, 'start');
    put(s, 'disp', cs.display, 'block');
    put(s, 'pos', cs.position, 'static');
    put(s, 'op', n(cs.opacity), 1);
    put(s, 'vis', cs.visibility, 'visible');
    put(s, 'ovx', cs.overflowX, 'visible'); put(s, 'ovy', cs.overflowY, 'visible');
    put(s, 'cp', cs.clipPath, 'none');
    put(s, 'sh', cs.boxShadow.slice(0, 200), 'none');
    put(s, 'tsh', cs.textShadow.slice(0, 120), 'none');
    put(s, 'bf', cs.backdropFilter, 'none'); put(s, 'flt', cs.filter, 'none');
    put(s, 'tw', cs.textWrap, 'wrap'); put(s, 'fvn', cs.fontVariantNumeric, 'normal');
    put(s, 'ws', cs.whiteSpace, 'normal'); put(s, 'to', cs.textOverflow, 'clip');
    put(s, 'lc', cs.webkitLineClamp, 'none');
    put(s, 'bg_clip', cs.webkitBackgroundClip || cs.backgroundClip, 'border-box');
    const tl = n(cs.borderTopLeftRadius), tr = n(cs.borderTopRightRadius), bl = n(cs.borderBottomLeftRadius), br = n(cs.borderBottomRightRadius);
    if (tl || tr || bl || br) s.rad = [tl, tr, br, bl];
    const bw = first4(cs, 'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth');
    if (bw.some(v => v > 0)) {
      s.bw = bw;
      s.bc = [cs.borderTopColor, cs.borderRightColor, cs.borderBottomColor, cs.borderLeftColor];
      s.bst = [cs.borderTopStyle, cs.borderRightStyle, cs.borderBottomStyle, cs.borderLeftStyle];
    }
    const pad = first4(cs, 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft');
    if (pad.some(v => v > 0)) s.pad = pad;
    const mar = first4(cs, 'marginTop', 'marginRight', 'marginBottom', 'marginLeft');
    if (mar.some(v => v !== 0)) s.mar = mar;
    if (cs.display.includes('grid')) s.gtc = cs.gridTemplateColumns.slice(0, 80);
    if (cs.display.includes('flex')) { s.fd = cs.flexDirection; s.fwrap = cs.flexWrap; }
    put(s, 'gap', n(cs.rowGap) || n(cs.columnGap) || 0, 0);
    rec.s = s;
    // direct element children that carry boxes
    rec.n = el.children.length;
    if (el.localName === 'img') {
      rec.img = {nw: el.naturalWidth, nh: el.naturalHeight, ok: el.complete && el.naturalWidth > 0, done: el.complete, src: (el.currentSrc || el.getAttribute('src') || '').slice(0, 120),
                 alt: el.hasAttribute('alt') ? el.getAttribute('alt') : null};
    }
    if (el.localName === 'svg') rec.svg = {shapes: el.querySelectorAll('path,circle,rect,ellipse,polygon,line,polyline').length};
    if (el.localName === 'a' || el.localName === 'button') { rec.act = true; const href = el.getAttribute('href'); if (href) rec.href = href.slice(0, 120); }
    if (el.localName === 'input' || el.localName === 'textarea' || el.localName === 'select') rec.ctl = el.getAttribute('type') || el.localName;
    if (text && /^h[1-6]$|^p$|^li$|^a$|^button$|^label$|^span$|^div$/.test(el.localName) && r.width > 8) {
      const lines = lineCount(el);
      if (lines) rec.ln = lines;
      if (lines >= 2 && r.width > 8) { const ll = lastLine(el); if (ll) rec.last = ll.w; }
    }
    out.els.push(rec);
    index.set(el, rec.i); refs.push(el);
  }
  // Text in the first screen with something opaque painted over its centre (elementFromPoint ignores pointer-events:none
  // layers, so a decorative overlay does not count).
  out.occluded = [];
  try {
    for (const rec of out.els) {
      if (out.occluded.length >= 8) break;
      if (!rec.t || rec.tl < 3 || rec.r[1] > H || rec.r[1] + rec.r[3] < 0 || rec.s.op < 0.5 || rec.s.vis === 'hidden') continue;
      const cx = Math.round(rec.r[0] - sx + Math.min(rec.r[2], 40) / 2 + 2), cy = Math.round(rec.r[1] - sy + Math.min(rec.r[3], 24) / 2);
      if (cx < 0 || cy < 0 || cx >= W || cy >= H) continue;
      const top = document.elementFromPoint(cx, cy);
      const mine = refs[rec.i];
      if (!top || !mine || top === mine || mine.contains(top) || top.contains(mine) || top === body || top === doc) continue;
      const tcs = getComputedStyle(top);
      const m = (tcs.backgroundColor.match(/rgba?\(([^)]*)\)/) || [null, ''])[1].split(',').map(Number);
      const opaque = ['IMG', 'VIDEO', 'CANVAS', 'PICTURE'].includes(top.tagName) || (m.length >= 3 && (m.length < 4 || m[3] > 0.9));
      if (!opaque || parseFloat(tcs.opacity) < 0.9) continue;
      out.occluded.push({el: rec.tag + ': ' + rec.t.slice(0, 40), by: top.localName + ((typeof top.className === 'string' && top.className) ? '.' + top.className.trim().split(/\s+/)[0] : '')});
    }
  } catch (e) {}
  return out;
}
"""


SOURCE_CAP = 400_000

# The text of every readable stylesheet, for static rules on a captured URL (cross-origin sheets are skipped).
CSS_TEXT_JS = r"""
() => {
  const out = [];
  for (const sheet of document.styleSheets) {
    try { out.push(Array.from(sheet.cssRules).map(r => r.cssText).join("\n")); } catch (e) {}
  }
  return out.join("\n");
}
"""


def _sync_playwright_available() -> bool:
    return web_browser.playwright_installed()


def launch_attempts() -> list[tuple[str, dict[str, Any]]]:
    """Every way to start a browser, best first: the family's channel order (system Chrome / Edge, Playwright's Chromium), then any
    Chromium found in a Playwright browsers folder and any system browser found on disk (`hoard_link.web.browser`)."""
    attempts: list[tuple[str, dict[str, Any]]] = []
    for channel in web_browser.channel_order():
        attempts.append((channel or "chromium", {"channel": channel} if channel else {}))
    exe = web_browser.find_chromium()
    if exe:
        attempts.append((f"chromium ({Path(exe).parent.parent.name})", {"executable_path": exe}))
    for path in web_browser.system_browsers():
        attempts.append((Path(path).name, {"executable_path": path}))
    return attempts


def launch_args() -> list[str]:
    """Chromium refuses to run as root (containers) without `--no-sandbox`."""
    return ["--no-sandbox"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []


def ffmpeg_path() -> Optional[str]:
    tool = media_bins.find("ffmpeg")
    return tool.path if tool else None


VITALS_MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36")
VITALS_INIT = """
(() => {
  const v = window.__vit = {lcp: 0, fcp: 0, shifts: [], longtasks: [], events: {}};
  const watch = (type, cb, extra) => { try { new PerformanceObserver(l => l.getEntries().forEach(cb)).observe(Object.assign({type, buffered: true}, extra || {})); } catch (e) {} };
  watch('largest-contentful-paint', e => { v.lcp = e.startTime; });
  watch('paint', e => { if (e.name === 'first-contentful-paint') v.fcp = e.startTime; });
  watch('layout-shift', e => { if (!e.hadRecentInput) v.shifts.push([e.startTime, e.value]); });
  watch('longtask', e => { v.longtasks.push([e.startTime, e.duration]); });
  watch('event', e => { if (e.interactionId) v.events[e.interactionId] = Math.max(v.events[e.interactionId] || 0, e.duration); }, {durationThreshold: 16});
})();
"""
VITALS_SPOT = """
() => {
  const w = innerWidth, h = innerHeight;
  for (let y = Math.round(h * 0.4); y < h; y += 24) for (let x = 6; x < w; x += 40) {
    const el = document.elementFromPoint(x, y);
    if (el && !el.closest('a,button,input,select,textarea,summary,label,[onclick],[role=button]')) return [x, y];
  }
  return null;
}
"""
VITALS_COLLECT = """
() => {
  const v = window.__vit || {lcp: 0, fcp: 0, shifts: [], longtasks: [], events: {}};
  const nav = performance.getEntriesByType('navigation')[0];
  let cls = 0, win = 0, start = 0, last = 0;
  for (const [t, val] of v.shifts) {
    if (t - last > 1000 || t - start > 5000) { win = 0; start = t; }
    win += val; last = t; cls = Math.max(cls, win);
  }
  let tbt = 0;
  for (const [t, d] of v.longtasks) if (t >= v.fcp && d > 50) tbt += d - 50;
  const inp = Object.values(v.events);
  const res = performance.getEntriesByType('resource');
  const bytes = res.reduce((n, r) => n + (r.transferSize || r.encodedBodySize || 0), 0) + (nav ? (nav.transferSize || 0) : 0);
  return {lcp_ms: Math.round(v.lcp) || null, fcp_ms: Math.round(v.fcp) || null, cls: Math.round(cls * 1000) / 1000,
          ttfb_ms: nav ? Math.round(nav.responseStart) : null, tbt_ms: Math.round(tbt), inp_ms: inp.length ? Math.round(Math.max(...inp)) : null,
          transfer_bytes: bytes, requests: res.length + 1, text_chars: (document.body ? document.body.innerText.length : 0)};
}
"""


class Job:
    def __init__(self, kind: str, payload: dict[str, Any]):
        self.kind = kind
        self.payload = payload
        self.event = threading.Event()
        self.result: Any = None
        self.error: Optional[str] = None


class BrowserWorker:
    """One thread, one Playwright instance, one queue. `p.chromium.launch()`
    then channels "msedge"/"chrome" on failure. Every job returns a dict;
    on unrecoverable failure to get any browser, every job returns
    ``{"error": "no browser", "hint": ...}`` instead of raising.
    """

    def __init__(self, data_dir: Path, timeout_s: float = 45.0, *, profile: str = safety.PUBLIC, resolver: Any = None):
        self.data_dir = Path(data_dir)
        self.timeout_s = timeout_s
        self.profile = profile  # which hosts a page may reach (`hoard_link.web.safety`): public ones unless the operator opted in
        self.resolver = resolver  # tests only: a fake DNS
        self.launched_with: Optional[str] = None
        self._queue: "queue.Queue[Job]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._pw = None
        self._browser = None
        self._launch_error: Optional[str] = None
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="vitruvius-browser", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(Job("_stop", {}))
        if self._thread is not None:
            self._thread.join()

    def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        if not _sync_playwright_available():
            self._launch_error = "playwright is not installed"
            return None
        from playwright.sync_api import sync_playwright

        if self._pw is None:
            self._pw = sync_playwright().start()
        for name, extra in launch_attempts():
            try:
                self._browser = self._pw.chromium.launch(args=launch_args(), **extra)
                self.launched_with = name
                self._launch_error = None
                return self._browser
            except Exception as error:  # noqa: BLE001
                self._launch_error = str(error).strip().splitlines()[0][:200] if str(error).strip() else type(error).__name__
                log.info("browser launch failed (%s): %s", name, self._launch_error)
        return None

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self._queue.get()
            if job.kind == "_stop":
                break
            try:
                job.result = self._handle(job)
            except Exception as error:  # noqa: BLE001
                job.error = str(error)
            finally:
                job.event.set()
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:  # noqa: BLE001
                pass
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass

    # -- what a page may reach ---------------------------------------------
    def url_problem(self, url: Optional[str]) -> Optional[str]:
        """Why `url` may not be opened (private or loopback host, credentials in the URL, metadata address ...), or None.
        A host that does not resolve passes: the browser reports its own DNS error."""
        if not url:
            return None
        problem = safety.check_url(url, self.profile, self.resolver)
        if problem and problem.startswith(safety.UNRESOLVABLE_PREFIX):
            return None
        return problem

    def _guard(self, context: Any) -> None:
        """Refuse every request of the page (redirects, scripts, images, frames) that goes to a host the policy forbids; the
        verdict per host is kept for the capture."""
        verdicts: dict[str, Optional[str]] = {}

        def handler(route: Any) -> None:
            url = route.request.url
            if url.split(":", 1)[0].lower() not in ("http", "https", "ws", "wss"):
                route.continue_()  # data:, blob:, about:, file: are not network requests
                return
            key = url.split("/")[2].lower() if url.count("/") >= 2 else url.lower()
            if key not in verdicts:
                verdicts[key] = self.url_problem(url.replace("wss:", "https:", 1).replace("ws:", "http:", 1))
            if verdicts[key]:
                log.info("browser request refused: %s (%s)", url[:120], verdicts[key])
                route.abort("blockedbyclient")
            else:
                route.continue_()

        context.route("**/*", handler)

    def _submit(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.start()
        job = Job(kind, payload)
        self._queue.put(job)
        timeout = (max(self.timeout_s, 600) if kind == "remake_capture" else max(self.timeout_s, 300) if kind in ("motion", "parity", "fetch")
                   else (max(self.timeout_s, 150) if kind == "vitals" else self.timeout_s))
        if not job.event.wait(timeout):
            return {"error": "timeout", "hint": f"render job exceeded {self.timeout_s}s"}
        if job.error:
            return {"error": job.error}
        return job.result

    def _handle(self, job: Job) -> dict[str, Any]:
        browser = self._ensure_browser()
        if browser is None:
            return {"error": "no browser", "hint": "python -m playwright install chromium"}
        if job.kind == "capture":
            return self._capture(browser, job.payload)
        if job.kind == "motion":
            from .motion import Composition, export_frames
            audio = job.payload.get("audio")
            return export_frames(browser, Composition.model_validate(job.payload["composition"]), Path(job.payload["out_dir"]), Path(audio) if audio else None)
        if job.kind == "vitals":
            return self._vitals(browser, job.payload)
        if job.kind == "parity":
            return self._parity(browser, job.payload)
        if job.kind == "remake_capture":
            return self._remake_capture(browser, job.payload)
        if job.kind == "fetch":
            return self._fetch(browser, job.payload)
        return {"error": f"unknown job kind {job.kind}"}

    # -- a folder served as a web site (remake candidates) ------------------------
    @staticmethod
    def _mount(context: Any, mount: Optional[dict[str, Any]], missing: list[str]) -> None:
        """Answer every request to `mount["origin"]` from the files under `mount["root"]` (registered after the guard, so it
        runs first); paths that are not there answer 404 and are listed in `missing`."""
        if not mount:
            return
        import mimetypes
        from urllib.parse import unquote, urlsplit
        root = Path(mount["root"]).resolve()
        origin = str(mount["origin"]).rstrip("/")

        def serve(route: Any) -> None:
            path = unquote(urlsplit(route.request.url).path).lstrip("/") or "index.html"
            target = (root / path).resolve()
            if (root in target.parents) and target.is_file():
                kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                if kind.startswith("text/") or kind in ("application/javascript", "image/svg+xml"):
                    kind += "; charset=utf-8"
                route.fulfill(path=str(target), content_type=kind, headers={"Cache-Control": "no-store"})
                return
            if path not in missing and len(missing) < 500:
                missing.append(path)
            route.fulfill(status=404, body="", content_type="text/plain")

        context.route(origin + "/**", serve)

    # -- remake: the reference, frozen, with its layout, snapshot and files -----------
    def _remake_capture(self, browser, payload: dict[str, Any]) -> dict[str, Any]:
        """Load the reference `loads` times at each width in the frozen browser of the parity check and save one full-page
        PNG per load (`reference-<width>-<load>.png`). The first load of each width also returns the layout (`remake.OUTLINE_JS`)
        and saves every stylesheet, image, font, script and plain video the page loaded into `raw/`; the first load of the
        first width also returns the static snapshot of the rendered page, the original document and the sign-in/payment check."""
        from . import parity, remake
        url = payload.get("url")
        problem = self.url_problem(url)
        if problem:
            return {"error": "This URL cannot be opened.", "hint": problem}
        out_dir = Path(payload["out_dir"])
        raw_dir = out_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        wait_ms = int(payload.get("wait_ms", 800))
        cap = parity.MAX_PAGE_HEIGHT
        result: dict[str, Any] = {"captures": [], "outlines": {}, "assets": [], "errors": []}
        saved: dict[str, dict[str, Any]] = {}
        total = 0
        keep_types = ("stylesheet", "image", "font", "media", "script", "other")
        for index, width in enumerate(payload["widths"]):
            vh = parity.viewport_height(int(width))
            for load in range(1, int(payload.get("loads", 2)) + 1):
                context = browser.new_context(viewport={"width": int(width), "height": vh}, device_scale_factor=1, color_scheme="light",
                                              reduced_motion="reduce", locale="es-ES", timezone_id="UTC")
                self._guard(context)
                from .showcase.library import mount as mount_showcase
                mount_showcase(context, url)
                context.add_init_script(parity.FREEZE_JS)
                page = context.new_page()
                responses: list[Any] = []
                if load == 1:
                    page.on("response", lambda r: responses.append(r) if len(responses) < 3000 else None)
                try:
                    try:
                        response = page.goto(url, wait_until="networkidle", timeout=25000)
                    except Exception:  # noqa: BLE001
                        response = page.goto(url, wait_until="load", timeout=30000)
                    if index == 0 and load == 1:
                        status = response.status if response else 0
                        if remake.looks_like_bot_wall(status, page.content()):
                            return {"error": "bot check", "wall": True, "hint": f"{url} answers with a bot check"}
                        result["status"] = status
                        result["final_url"] = page.url
                        try:
                            result["document_html"] = response.text() if response else ""
                        except Exception:  # noqa: BLE001
                            result["document_html"] = ""
                    page.wait_for_timeout(wait_ms)
                    height = int(page.evaluate(parity.SETTLE_JS))
                    path = out_dir / f"reference-{width}-{load}.png"
                    shot = {"full_page": True, "animations": "disabled", "caret": "hide", "path": str(path)}
                    if height > cap:
                        shot["clip"] = {"x": 0, "y": 0, "width": int(width), "height": cap}
                    page.screenshot(**shot)
                    result["captures"].append({"width": int(width), "load": load, "path": str(path), "document_height": height})
                    if load != 1:
                        continue
                    result["outlines"][str(width)] = page.evaluate(remake.OUTLINE_JS)
                    if index == 0:
                        result["sensitive"] = page.evaluate(remake.SENSITIVE_JS)
                        result["snapshot"] = page.evaluate(remake.SNAPSHOT_JS)  # changes the page: last
                    for r in responses:
                        try:
                            rurl = r.url
                            if rurl in saved or not rurl.startswith(("http://", "https://")) or not 200 <= r.status < 300 or r.status == 206:
                                continue
                            rtype = r.request.resource_type
                            if rtype not in keep_types or remake.is_tracker(rurl):
                                continue
                            headers = r.headers
                            ctype = (headers.get("content-type") or "").split(";")[0].strip().lower()
                            if rtype == "other" and not ctype.startswith(("image/", "font/", "text/css", "application/font")):
                                continue
                            length = int(headers.get("content-length") or 0)
                            if length > remake.MAX_ASSET_BYTES or total > remake.MAX_TOTAL_BYTES:
                                continue
                            body = r.body()
                            if len(body) > remake.MAX_ASSET_BYTES:
                                continue
                            file = raw_dir / f"{len(saved):05d}.bin"
                            file.write_bytes(body)
                            total += len(body)
                            saved[rurl] = {"url": rurl, "content_type": ctype, "resource_type": rtype, "file": str(file), "bytes": len(body)}
                        except Exception:  # noqa: BLE001 - a response without a body (redirect, aborted) is skipped
                            continue
                except Exception as error:  # noqa: BLE001
                    result["errors"].append(f"{width} px, carga {load}: {str(error).strip().splitlines()[0][:200] if str(error).strip() else type(error).__name__}")
                finally:
                    context.close()
        result["assets"] = list(saved.values())
        return result

    def _fetch(self, browser, payload: dict[str, Any]) -> dict[str, Any]:
        """Download files one at a time (a short pause between them), each address checked like a page request."""
        out_dir = Path(payload["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        context = browser.new_context()
        files, errors = [], []
        try:
            for i, url in enumerate(payload.get("urls") or []):
                problem = self.url_problem(url)
                if problem:
                    errors.append(f"{url}: {problem}")
                    continue
                try:
                    r = context.request.get(url, timeout=20000, max_redirects=5)
                    if not r.ok:
                        errors.append(f"{url}: {r.status}")
                        continue
                    body = r.body()
                    if len(body) > 20_000_000:
                        continue
                    file = out_dir / f"{i:05d}.bin"
                    file.write_bytes(body)
                    files.append({"url": url, "file": str(file), "content_type": (r.headers.get("content-type") or "").split(";")[0].strip().lower(),
                                  "bytes": len(body)})
                except Exception as error:  # noqa: BLE001
                    errors.append(f"{url}: {str(error).strip().splitlines()[0][:160] if str(error).strip() else type(error).__name__}")
                time.sleep(0.3)
        finally:
            context.close()
        return {"files": files, "errors": errors}

    # -- visual parity: frozen full-page captures ------------------------------
    def _parity(self, browser, payload: dict[str, Any]) -> dict[str, Any]:
        """Load one page `loads` times at each width in a frozen browser (fixed clock, seeded random numbers, no transitions or
        animations, videos on frame 0), force lazy content by scrolling to the bottom and back, and save one full-page PNG per
        load and width as `<tag>-<width>-<load>.png`. Reports the document height seen at each capture."""
        from . import parity
        html: Optional[str] = payload.get("html")
        url: Optional[str] = payload.get("url")
        mount = payload.get("mount")
        served = bool(mount and url and url.startswith(str(mount["origin"]).rstrip("/") + "/"))
        problem = self.url_problem(url) if html is None and not served else None
        if problem:
            return {"error": "This URL cannot be opened.", "hint": problem}
        out_dir = Path(payload["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        tag = payload.get("tag", "page")
        wait_ms = int(payload.get("wait_ms", 600))
        cap = int(payload.get("max_height", parity.MAX_PAGE_HEIGHT))
        captures: list[dict[str, Any]] = []
        errors: list[str] = []
        missing: list[str] = []
        outline_js = None
        if payload.get("outline"):
            from .remake import OUTLINE_JS as outline_js
        for width in payload["widths"]:
            vh = int(payload.get("viewport_heights", {}).get(str(width)) or parity.viewport_height(width))
            for load in range(1, int(payload.get("loads", 1)) + 1):
                context = browser.new_context(viewport={"width": int(width), "height": vh}, device_scale_factor=1,
                                              color_scheme="dark" if payload.get("dark") else "light", reduced_motion="reduce",
                                              locale="es-ES", timezone_id="UTC")
                self._guard(context)
                self._mount(context, mount, missing)
                from .showcase.library import mount as mount_showcase
                mount_showcase(context, url)
                context.add_init_script(parity.FREEZE_JS)
                page = context.new_page()
                try:
                    if html is not None:
                        page.set_content(html, wait_until="load")
                    else:
                        try:
                            page.goto(url, wait_until="networkidle", timeout=20000)
                        except Exception:  # noqa: BLE001
                            page.goto(url, wait_until="load", timeout=25000)
                    page.wait_for_timeout(wait_ms)
                    height = int(page.evaluate(parity.SETTLE_JS))
                    path = out_dir / f"{tag}-{width}-{load}.png"
                    shot = {"full_page": True, "animations": "disabled", "caret": "hide", "path": str(path)}
                    if height > cap:
                        shot["clip"] = {"x": 0, "y": 0, "width": int(width), "height": cap}
                    page.screenshot(**shot)
                    row = {"width": int(width), "load": load, "path": str(path), "document_height": height}
                    if outline_js and load == 1:
                        try:
                            row["outline"] = page.evaluate(outline_js)
                        except Exception:  # noqa: BLE001 - the score stands without the layout
                            pass
                    captures.append(row)
                except Exception as error:  # noqa: BLE001
                    errors.append(f"{width} px, carga {load}: {str(error).strip().splitlines()[0][:200] if str(error).strip() else type(error).__name__}")
                finally:
                    context.close()
        out = {"captures": captures, "errors": errors}
        if mount:
            out["missing"] = missing
        return out

    # -- Core Web Vitals (lab) -----------------------------------------------
    def _vitals(self, browser, payload: dict[str, Any]) -> dict[str, Any]:
        """Load `url` once in a real page and read LCP, CLS, FCP, TTFB, TBT and an INP estimate from the performance observers.
        Lab data: one load on this machine, optionally with the CPU and network slowed down (`throttle`). INP comes from three
        synthetic interactions (a click on an empty spot and two Tab presses), so it is an estimate, not field INP."""
        url = payload.get("url")
        problem = self.url_problem(url)
        if problem:
            return {"error": "This URL cannot be opened.", "hint": problem}
        mobile = payload.get("profile", "mobile") != "desktop"
        throttle = bool(payload.get("throttle", True))
        options: dict[str, Any] = ({"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True,
                                    "user_agent": VITALS_MOBILE_UA} if mobile else {"viewport": {"width": 1350, "height": 940}})
        context = browser.new_context(**options)
        self._guard(context)
        context.add_init_script(VITALS_INIT)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)[:200]) if len(errors) < 10 else None)
        conditions = {"label": "móvil" if mobile else "escritorio", "viewport": f"{options['viewport']['width']}x{options['viewport']['height']}",
                      "cpu_slowdown": 1, "network": "sin limitar"}
        try:
            if throttle:
                try:
                    cdp = context.new_cdp_session(page)
                    rate = 4 if mobile else 2
                    cdp.send("Emulation.setCPUThrottlingRate", {"rate": rate})
                    cdp.send("Network.enable")
                    cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 150, "downloadThroughput": 1_600_000 / 8, "uploadThroughput": 750_000 / 8})
                    conditions.update(cpu_slowdown=rate, network="1,6 Mbit/s con 150 ms de latencia")
                    conditions["label"] += " con CPU " + str(rate) + "× más lenta y red 4G lenta"
                except Exception:  # noqa: BLE001 - throttling is best effort; the conditions say what was applied
                    pass
            try:
                page.goto(url, wait_until="load", timeout=60000)
            except Exception as error:  # noqa: BLE001
                return {"error": "page did not load", "hint": str(error).strip().splitlines()[0][:200] if str(error).strip() else type(error).__name__}
            page.wait_for_timeout(2500)
            try:
                spot = page.evaluate(VITALS_SPOT)
                if spot:
                    page.mouse.click(spot[0], spot[1])
                page.keyboard.press("Tab")
                page.keyboard.press("Tab")
                page.wait_for_timeout(600)
            except Exception:  # noqa: BLE001 - no interaction: INP stays unmeasured
                pass
            data = page.evaluate(VITALS_COLLECT)
            rendered_html = page.content()[:1_500_000]
        finally:
            context.close()
        metrics = {k: data.get(k) for k in ("lcp_ms", "cls", "fcp_ms", "ttfb_ms", "tbt_ms", "inp_ms", "transfer_bytes", "requests")}
        return {"profile": "mobile" if mobile else "desktop", "conditions": conditions, "metrics": metrics, "js_errors": errors,
                "rendered_text_chars": data.get("text_chars", 0),
                "rendered_html": rendered_html,
                "note": "Medida de laboratorio: una carga en este equipo. INP se estima con tres interacciones sintéticas."}

    # -- capture ---------------------------------------------------------
    def _capture(self, browser, payload: dict[str, Any]) -> dict[str, Any]:
        html: Optional[str] = payload.get("html")
        url: Optional[str] = payload.get("url")
        widths: list[int] = payload.get("widths") or [390, 1024, 1440]
        full_page: bool = payload.get("full_page", True)
        dark: bool = payload.get("dark", False)
        wait_ms: int = payload.get("wait_ms", 800)
        record: bool = payload.get("record", False)
        out_dir: Path = Path(payload["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)

        problem = self.url_problem(url) if html is None else None
        if problem:
            return {"error": "This URL cannot be opened.", "hint": problem}
        context = browser.new_context(color_scheme="dark" if dark else "light")
        self._guard(context)
        page = context.new_page()
        script_errors: list[str] = []
        page.on("pageerror", lambda error: script_errors.append(str(error)[:300]) if len(script_errors) < 10 else None)
        try:
            if html is not None:
                page.set_content(html, wait_until="load")
            elif url:
                try:
                    page.goto(url, wait_until="networkidle", timeout=15000)
                except Exception:  # noqa: BLE001
                    page.goto(url, wait_until="load", timeout=20000)
            else:
                return {"error": "no html or url given"}
            page.wait_for_timeout(wait_ms)

            files = []
            layout: dict[str, Any] = {}
            dom: dict[str, Any] = {}
            for w in widths:
                page.set_viewport_size({"width": w, "height": 900})
                try:
                    page.wait_for_timeout(120)
                    layout[str(w)] = page.evaluate(LAYOUT_JS)
                except Exception as error:  # noqa: BLE001 - a page that breaks the probe still gets its screenshots
                    layout[str(w)] = {"error": str(error)[:200]}
                try:
                    dom[str(w)] = page.evaluate(DOM_JS)
                except Exception as error:  # noqa: BLE001 - the snapshot is optional; the rules that need it skip
                    dom[str(w)] = {"error": str(error)[:200]}
                path = out_dir / f"{w}.png"
                if full_page:
                    # Cap full-page height at 6000px via a clip.
                    dims = page.evaluate("() => ({w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight})")
                    h = min(int(dims.get("h", 900)), 6000)
                    page.screenshot(path=str(path), full_page=True, clip={"x": 0, "y": 0, "width": w, "height": h})
                    saved_h = h
                else:
                    page.screenshot(path=str(path))
                    saved_h = 900
                files.append({"width": w, "path": str(path), "full_page": full_page, "w": w, "h": saved_h})

            probe = {}
            try:
                probe = page.evaluate(PROBE_JS)
            except Exception as error:  # noqa: BLE001
                probe = {"error": str(error)}
            if layout:
                probe["layout"] = layout
            if dom:
                probe["dom"] = dom
            probe["script_errors"] = script_errors
            if url:
                # a captured URL has no source HTML on our side: hand the rules the serialised page and its stylesheets
                try:
                    probe["html_text"] = page.content()[:SOURCE_CAP]
                    probe["css_text"] = (page.evaluate(CSS_TEXT_JS) or "")[:SOURCE_CAP]
                except Exception:  # noqa: BLE001
                    pass

            video_path = None
            poster_path = None
            if record and ffmpeg_path():
                video_path, poster_path = self._record_video(browser, html, url, dark, out_dir)

            return {"files": files, "probe": probe, "video": video_path, "poster": poster_path}
        finally:
            context.close()

    def _record_video(self, browser, html, url, dark, out_dir: Path):
        video_dir = tempfile.mkdtemp(prefix="vitruvius-video-")
        context = browser.new_context(
            record_video_dir=video_dir, record_video_size={"width": 1440, "height": 900},
            viewport={"width": 1440, "height": 900}, color_scheme="dark" if dark else "light",
        )
        self._guard(context)
        page = context.new_page()
        try:
            if html is not None:
                page.set_content(html, wait_until="load")
            elif url:
                try:
                    page.goto(url, wait_until="networkidle", timeout=15000)
                except Exception:  # noqa: BLE001
                    page.goto(url, wait_until="load", timeout=20000)
            page.wait_for_timeout(300)
            poster = out_dir / "poster.png"
            page.screenshot(path=str(poster))
            height = page.evaluate("() => document.documentElement.scrollHeight")
            steps = 30
            for i in range(steps + 1):
                y = int(height * i / steps)
                page.evaluate(f"window.scrollTo(0, {y})")
                page.wait_for_timeout(int(5000 / steps))
            for i in range(steps, -1, -1):
                y = int(height * i / steps)
                page.evaluate(f"window.scrollTo(0, {y})")
                page.wait_for_timeout(int(1000 / steps))
        finally:
            page_video = page.video
            context.close()
        try:
            webm_path = Path(page_video.path()) if page_video else None
        except Exception:  # noqa: BLE001
            webm_path = None
        if webm_path is None or not webm_path.exists():
            return None, str(poster)
        mp4_path = out_dir / "scroll.mp4"
        try:
            FFmpeg().run(["-i", webm_path, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4_path], timeout=60)
            return str(mp4_path), str(poster)
        except Exception:  # noqa: BLE001
            dest = out_dir / "scroll.webm"
            try:
                shutil.copy(webm_path, dest)
                return str(dest), str(poster)
            except Exception:  # noqa: BLE001
                return None, str(poster)

    # -- public API --------------------------------------------------------
    def capture(self, *, html: Optional[str] = None, url: Optional[str] = None, widths: Optional[list[int]] = None,
                full_page: bool = True, dark: bool = False, wait_ms: int = 800, record: bool = False,
                out_dir: Optional[Path] = None) -> dict[str, Any]:
        out_dir = out_dir or (self.data_dir / "renders" / uuid.uuid4().hex)
        return self._submit("capture", {
            "html": html, "url": url, "widths": widths or [390, 1024, 1440], "full_page": full_page,
            "dark": dark, "wait_ms": wait_ms, "record": record, "out_dir": str(out_dir),
        })

    def parity_capture(self, *, html: Optional[str] = None, url: Optional[str] = None, widths: list[int], loads: int = 1,
                       out_dir: Path, tag: str = "page", dark: bool = False, wait_ms: int = 600, mount: Optional[dict[str, Any]] = None,
                       outline: bool = False) -> dict[str, Any]:
        """Frozen full-page captures of one page for the visual-parity comparison (`vitruvius_hoard.parity`). `mount`
        ({origin, root}) serves a local folder at that origin; `outline` also returns the layout of the first load."""
        return self._submit("parity", {"html": html, "url": url, "widths": widths, "loads": loads, "out_dir": str(out_dir),
                                       "tag": tag, "dark": dark, "wait_ms": wait_ms, "mount": mount, "outline": outline})

    def remake_capture(self, *, url: str, widths: list[int], out_dir: Path, wait_ms: int = 800, loads: int = 2) -> dict[str, Any]:
        """The reference of a remake: frozen captures, layout, snapshot and the files it loaded (`vitruvius_hoard.remake`)."""
        return self._submit("remake_capture", {"url": url, "widths": widths, "out_dir": str(out_dir), "wait_ms": wait_ms, "loads": loads})

    def fetch_files(self, *, urls: list[str], out_dir: Path) -> dict[str, Any]:
        """Download these files one by one into `out_dir`."""
        return self._submit("fetch", {"urls": list(urls), "out_dir": str(out_dir)})

    def status(self) -> dict[str, Any]:
        ok = self._browser is not None
        return {"ok": ok, "error": None if ok else self._launch_error, "playwright_installed": _sync_playwright_available()}
