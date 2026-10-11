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
            self._thread.join(timeout=5)

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
        timeout = max(self.timeout_s, 300) if kind == "motion" else self.timeout_s
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
            return export_frames(browser, Composition.model_validate(job.payload["composition"]), Path(job.payload["out_dir"]))
        return {"error": f"unknown job kind {job.kind}"}

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
            for w in widths:
                page.set_viewport_size({"width": w, "height": 900})
                try:
                    page.wait_for_timeout(120)
                    layout[str(w)] = page.evaluate(LAYOUT_JS)
                except Exception as error:  # noqa: BLE001 - a page that breaks the probe still gets its screenshots
                    layout[str(w)] = {"error": str(error)[:200]}
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

    def status(self) -> dict[str, Any]:
        ok = self._browser is not None
        return {"ok": ok, "error": None if ok else self._launch_error, "playwright_installed": _sync_playwright_available()}
