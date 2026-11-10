from __future__ import annotations

import json
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent
for entry in (str(ROOT), str(ROOT / "tests")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

warnings.filterwarnings("ignore", category=DeprecationWarning)

from vitruvius_hoard.config import Config  # noqa: E402
from vitruvius_hoard.main import create_app  # noqa: E402
from vitruvius_hoard.services import Services  # noqa: E402

T0 = 1_790_000_000.0


def _make_png_bytes() -> bytes:
    import io

    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), (120, 140, 255)).save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001 — Pillow should always be present, but degrade gracefully
        return b"\x89PNG\r\n\x1a\n"


_PNG_1x1 = _make_png_bytes()


def make_config(tmp_path: Path, **overrides) -> Config:
    base = dict(data_dir=tmp_path / "data", port=0, port_strict=False, render_timeout_s=5.0,
               data_dir_configured=True, autostart=False, embed_backend="none")  # never reach a hub that may be running on this machine
    base.update(overrides)
    return Config(**base)


def default_probe(**overrides) -> dict[str, Any]:
    probe = {
        "viewport_meta": "width=device-width, initial-scale=1",
        "lang": "en",
        "fonts": {"loaded": ["Inter"], "h1": "Inter", "h2": "Inter", "p": "Inter", "button": "Inter"},
        "colors": [{"color": "rgb(20,20,20)", "background": "rgb(255,255,255)", "count": 10}],
        "heading_order": [1, 2, 3],
        "images_without_alt": 0,
        "small_tap_targets": 0,
        "contrast_pairs": [{"color": "rgb(20,20,20)", "background": "rgb(255,255,255)", "text": "hello"}],
        "reduced_motion_css_present": True,
        "color_scheme_present": True,
        "animations_count": 2,
        "scroll_driven_count": 0,
        "external_libs": [],
        "dom_size": 200,
        "font_sizes": ["16px", "24px", "40px"],
        "long_paragraphs": 0,
        "long_transition_count": 0,
        "linear_easing_count": 0,
        "generic_defaults": {"fonts_only_generic": False, "purple_blue_gradient_buttons": False,
                            "emoji_icons": False, "section_count": 4},
    }
    probe.update(overrides)
    return probe


class FakeBrowser:
    """Returns synthetic probe dicts and writes 1x1 PNGs instead of using a real browser."""

    def __init__(self, probe_overrides: Optional[dict] = None, fail: bool = False):
        self.probe_overrides = probe_overrides or {}
        self.fail = fail
        self.calls: list[dict] = []

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def status(self) -> dict:
        return {"ok": not self.fail, "error": None if not self.fail else "no browser", "playwright_installed": True}

    def capture(self, *, html=None, url=None, widths=None, full_page=True, dark=False, wait_ms=800, record=False,
               out_dir=None) -> dict:
        self.calls.append({"html": html, "url": url, "widths": widths, "dark": dark, "record": record})
        if self.fail:
            return {"error": "no browser", "hint": "python -m playwright install chromium"}
        widths = widths or [390, 1024, 1440]
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for w in widths:
            path = out_dir / f"{w}.png"
            path.write_bytes(_PNG_1x1)
            files.append({"width": w, "path": str(path), "full_page": full_page, "w": w, "h": 900})
        probe = default_probe(**self.probe_overrides)
        result = {"files": files, "probe": probe, "video": None, "poster": None}
        if record:
            poster = out_dir / "poster.png"
            poster.write_bytes(_PNG_1x1)
            video = out_dir / "scroll.mp4"
            video.write_bytes(b"fake-mp4")
            result["poster"] = str(poster)
            result["video"] = str(video)
        return result

    # `parity_hook(tag, width, load, html, url)` may return a PIL image to use instead of the synthetic page;
    # `parity_noise` makes the second load of every page differ in a small block.
    parity_hook = None
    parity_noise = False

    def parity_capture(self, *, html=None, url=None, widths, loads=1, out_dir, tag="page", dark=False, wait_ms=600, mount=None,
                       outline=False) -> dict:
        if mount:  # a remake candidate: the page is the index.html of the mounted folder
            html = (Path(mount["root"]) / "index.html").read_text(encoding="utf-8")
        self.calls.append({"parity": tag, "html": html, "url": url, "widths": widths, "loads": loads, "mount": mount})
        if self.fail:
            return {"error": "no browser", "hint": "python -m playwright install chromium"}
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        captures = []
        for w in widths:
            for load in range(1, loads + 1):
                image = self.parity_hook(tag, w, load, html, url) if self.parity_hook else None
                if image is None:
                    image = _fake_parity_page(w, html or url or "", load, self.parity_noise)
                path = out_dir / f"{tag}-{w}-{load}.png"
                image.save(path)
                row = {"width": w, "load": load, "path": str(path), "document_height": image.height}
                if outline and load == 1:
                    row["outline"] = self.remake_outline_hook(html, w) if self.remake_outline_hook else _fake_outline(w)
                captures.append(row)
        out = {"captures": captures, "errors": []}
        if mount:
            out["missing"] = list(self.remake_missing)
            self.remake_missing = []
        return out

    # Remake ("Rehacer"): the reference capture returns `remake_snapshot` with `remake_assets` (url, type, resource type, bytes);
    # the reference pictures are `_fake_parity_page(w, "reference", load)`, so a candidate the parity_hook draws the same way
    # matches. `remake_extra` is merged into the result (wall, sensitive ...); `remake_missing` is what the next candidate asks
    # for and lacks; `fetch_bodies` answers fetch_files.
    remake_snapshot = ('<!DOCTYPE html><html lang="es"><head><title>Sitio</title><link rel="stylesheet" href="https://site.test/css/a.css">'
                       '<script src="https://www.googletagmanager.com/gtag/js?id=G-1"></script><script>window.app=1</script></head>'
                       '<body><h1>Hola mundo</h1><img src="https://site.test/img/x.png" alt="x"></body></html>')
    remake_assets = [("https://site.test/css/a.css", "text/css", "stylesheet",
                      b"@font-face{font-family:Acme;src:url(../fonts/acme.woff2) format('woff2')}body{background:url(../img/bg.png)}"),
                     ("https://site.test/img/x.png", "image/png", "image", b"\x89PNG-x"),
                     ("https://site.test/img/bg.png", "image/png", "image", b"\x89PNG-bg"),
                     ("https://site.test/fonts/acme.woff2", "font/woff2", "font", b"wOF2-acme"),
                     ("https://site.test/js/app.js", "text/javascript", "script", b"console.log(1)")]
    remake_extra: dict = {}
    remake_missing: list = []
    remake_outline_hook = None
    fetch_bodies: dict = {}

    def remake_capture(self, *, url, widths, out_dir, wait_ms=800, loads=2) -> dict:
        self.calls.append({"remake_capture": url, "widths": widths, "loads": loads})
        if self.fail:
            return {"error": "no browser", "hint": "python -m playwright install chromium"}
        out_dir = Path(out_dir)
        raw = out_dir / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        captures = []
        for w in widths:
            for load in range(1, loads + 1):
                image = _fake_parity_page(w, "reference", load, self.parity_noise)
                path = out_dir / f"reference-{w}-{load}.png"
                image.save(path)
                captures.append({"width": w, "load": load, "path": str(path), "document_height": image.height})
        assets = []
        for i, (aurl, ctype, rtype, body) in enumerate(self.remake_assets):
            file = raw / f"{i:05d}.bin"
            file.write_bytes(body)
            assets.append({"url": aurl, "content_type": ctype, "resource_type": rtype, "file": str(file), "bytes": len(body)})
        out = {"captures": captures, "outlines": {str(w): _fake_outline(w) for w in widths}, "assets": assets,
               "snapshot": {"html": self.remake_snapshot, "base": url}, "document_html": self.remake_snapshot, "final_url": url,
               "status": 200, "sensitive": {"password": 0, "card": 0}, "errors": []}
        out.update(self.remake_extra)
        return out

    def fetch_files(self, *, urls, out_dir) -> dict:
        self.calls.append({"fetch": list(urls)})
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for i, u in enumerate(urls):
            if u in self.fetch_bodies:
                ctype, body = self.fetch_bodies[u]
                file = out_dir / f"{i:05d}.bin"
                file.write_bytes(body)
                files.append({"url": u, "file": str(file), "content_type": ctype, "bytes": len(body)})
        return {"files": files, "errors": []}


def _fake_outline(width: int) -> dict:
    return {"width": width, "height": 300, "title": "Sitio", "lang": "es", "page_bg": "#ffffff",
            "palette": [{"c": "#111111", "w": 50}, {"c": "#ffffff", "w": 40}], "fonts": ["Acme 400"],
            "items": [{"t": "h1", "s": "h1", "x": 10, "y": 20, "w": width - 20, "h": 40, "d": 1, "tx": "Hola mundo", "f": "32px 700 Acme",
                       "lh": "40px", "c": "#111111"},
                      {"t": "img", "s": "img", "x": 10, "y": 80, "w": 200, "h": 100, "d": 1, "src": "https://site.test/img/x.png", "alt": "x",
                       "nw": 400, "nh": 200}],
            "links": [{"href": "https://twitter.com/site", "text": "X", "nav": False}, {"href": "https://site.test/precios", "text": "Precios", "nav": True},
                      {"href": "mailto:hola@site.test", "text": "Correo", "nav": False}],
            "forms": [{"action": "/contacto", "method": "post", "fields": ["email", "textarea"]}]}


def _fake_parity_page(width: int, key: str, load: int, noise: bool):
    """A synthetic full-page capture: colour derived from the page (same page, same picture), 300 px tall."""
    import hashlib
    from PIL import Image, ImageDraw
    digest = hashlib.md5(key.encode("utf-8")).digest()
    image = Image.new("RGB", (width, 300), (digest[0], digest[1], digest[2]))
    if noise and load == 2:
        ImageDraw.Draw(image).rectangle((5, 5, 30, 30), fill=(0, 0, 0))
    return image


@dataclass
class FakeChatResult:
    text: str = '{"score": 8, "findings": [], "summary": "Looks solid.", "direction": "Keep the palette bold."}'
    model: str = "fake-vision-model"


class FakeLink:
    """A sync-shaped stand-in for hoard_link.Link.sync — no network, deterministic."""

    def __init__(self, chat_text: Optional[str] = None, available: bool = True):
        self.chat_text = chat_text
        self.available = available
        self.chat_calls: list[Any] = []

    def chat(self, messages, images=None, **kwargs):
        self.chat_calls.append((messages, images))
        text = self.chat_text if self.chat_text is not None else FakeChatResult().text
        return FakeChatResult(text=text)

    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def status(self):
        cap = {"state": "resolved" if self.available else "unavailable", "provider": "fake", "model": "fake-model"}
        unavailable = {"state": "unavailable", "reason": "no model configured"}
        return {c: (cap if self.available else unavailable) for c in ("llm", "vision", "embeddings")}

    def close(self):
        pass


def make_services(tmp_path: Path, *, probe_overrides=None, browser_fail=False, link=None, **config_overrides) -> Services:
    config = make_config(tmp_path, **config_overrides)
    browser = FakeBrowser(probe_overrides=probe_overrides, fail=browser_fail)
    link = link if link is not None else FakeLink()
    return Services(config, browser=browser, link=link, autostart_ingest=False)


@pytest.fixture
def services(tmp_path):
    svc = make_services(tmp_path)
    svc.start()
    yield svc
    svc.stop()


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient

    svc = make_services(tmp_path)
    app = create_app(svc.config, svc)
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        test_client.svc = svc
        yield test_client


@pytest.fixture(autouse=True)
def no_live_transport(monkeypatch):
    import httpx
    async def async_block(self,request):
        raise AssertionError('Live HTTP is disabled in synthetic tests: '+str(request.url))
    def block(self,request):
        raise AssertionError('Live HTTP is disabled in synthetic tests: '+str(request.url))
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',block)
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',async_block)
