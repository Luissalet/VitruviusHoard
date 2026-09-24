"""The Playwright worker: one background thread owning a sync Playwright
instance, fed through a queue.Queue, one page at a time. Launches lazily on
the first job. Jobs never block the asyncio event loop — callers submit a
job and wait on a threading.Event-backed future with a timeout.

Tests never touch this module's real browser: they inject a ``FakeBrowser``
(same public interface: ``capture`` and ``probe``) through ``Services``.
"""

from __future__ import annotations

import base64
import json
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

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


def _sync_playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:
        return False


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

    def __init__(self, data_dir: Path, timeout_s: float = 45.0):
        self.data_dir = Path(data_dir)
        self.timeout_s = timeout_s
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
        for attempt in (
            lambda: self._pw.chromium.launch(),
            lambda: self._pw.chromium.launch(channel="msedge"),
            lambda: self._pw.chromium.launch(channel="chrome"),
        ):
            try:
                self._browser = attempt()
                return self._browser
            except Exception as error:  # noqa: BLE001
                self._launch_error = str(error)
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

    def _submit(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.start()
        job = Job(kind, payload)
        self._queue.put(job)
        if not job.event.wait(self.timeout_s):
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

        context = browser.new_context(color_scheme="dark" if dark else "light")
        page = context.new_page()
        try:
            if html is not None:
                base_url = payload.get("base_url")
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
            for w in widths:
                page.set_viewport_size({"width": w, "height": 900})
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

            video_path = None
            poster_path = None
            if record and shutil.which("ffmpeg"):
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
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(webm_path), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4_path)],
                capture_output=True, timeout=60, check=True,
            )
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
