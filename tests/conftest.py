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
               data_dir_configured=True, autostart=False)
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
