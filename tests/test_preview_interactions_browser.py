"""Regression coverage for the preview bridge and the real Chromium Tab walk."""
import os
from pathlib import Path

import pytest

from vitruvius_hoard.keyboard import walk
from vitruvius_hoard.hoard_link.app_bridge import BRIDGE_JS


pytestmark = pytest.mark.skipif(os.environ.get("VITRUVIUS_BROWSER_TESTS") != "1",
                                reason="Set VITRUVIUS_BROWSER_TESTS=1 to run the Chrome regression tests")

ORIGIN = "https://preview.interactions.invalid"
SCRIPT = Path(__file__).resolve().parents[1] / "vitruvius_hoard" / "preview_scripts" / "preview-refresh.js"


@pytest.fixture
def page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as instance:
        browser = instance.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu", "--use-angle=swiftshader"])
        try:
            yield browser.new_page(viewport={"width": 390, "height": 850})
        finally:
            browser.close()


def preview_frame(page, *, tail=""):
    view = {"revision": "before", "template": "Antes", "extra": "", "tail": tail}
    script = SCRIPT.read_text(encoding="utf-8")

    def route(request):
        url = request.request.url
        if url == ORIGIN + "/":
            return request.fulfill(content_type="text/html", body='<iframe src="/preview"></iframe>')
        if url == ORIGIN + "/assistant.css":
            return request.fulfill(content_type="text/css", body="main { color: rgb(25, 65, 105) }")
        if url == ORIGIN + "/assistant.js":
            return request.fulfill(content_type="application/javascript",
                                   body="window.assistantStarts = (window.assistantStarts || 0) + 1")
        if url != ORIGIN + "/preview":
            return request.abort()
        body = f"""<!doctype html><meta name="vitruvius-preview-revision" content="{view['revision']}">
          <main id="schedule" data-vsrc="pages/index.html:1:1">
            <template id="entry" data-vsrc="pages/index.html:2:1"><p>{view['template']}</p>
              <script>window.inertScriptRan = true;</script>
            </template>
            <section id="first" data-vsrc="pages/index.html:5:1">Programa</section>
            <input id="draft" aria-label="Borrador" data-vsrc="pages/index.html:7:1">
            {view['extra']}
          </main>{view['tail']}<script>{script}</script>"""
        return request.fulfill(content_type="text/html", body=body, headers={"X-Vitruvius-Revision": view["revision"]})

    page.route("**/*", route)
    page.goto(ORIGIN + "/", wait_until="load")
    iframe = page.locator("iframe").element_handle()
    frame = iframe.content_frame()
    frame.locator("#schedule").wait_for()
    frame.evaluate("() => window.documentStamp = 'original'")

    def message(type_, **kwargs):
        return page.evaluate("""message => new Promise((resolve, reject) => {
          const frame = document.querySelector('iframe').contentWindow;
          const timer = setTimeout(() => reject(new Error(message.type)), 6000);
          function receive(event) {
            if (event.source !== frame || event.data?.type !== message.type + '/result') return;
            clearTimeout(timer);
            window.removeEventListener('message', receive);
            resolve(event.data.result);
          }
          window.addEventListener('message', receive);
          frame.postMessage(message, location.origin);
        })""", {"type": type_, "hoardDock": 1, "request": "test", **kwargs})

    assert message("canvas/state")["route"] == "/preview"

    def refresh(previous, next_, **values):
        view.update(values, revision=next_)
        return message("canvas/refresh", mode="html", change={
            "previous_revision": previous, "revision": next_, "files": ["pages/index.html"],
        })

    return frame, refresh


def test_section_appended_beside_template_preserves_the_document(page):
    frame, refresh = preview_frame(page)
    result = refresh("before", "after", extra='<section id="booking" data-vsrc="pages/index.html:6:1">Reserva</section>')
    assert result["applied"]
    assert frame.locator("#booking").inner_text() == "Reserva"
    assert frame.evaluate("window.documentStamp") == "original"
    assert frame.evaluate("Boolean(window.inertScriptRan)") is False
    assert frame.locator('meta[name="vitruvius-preview-revision"]').get_attribute("content") == "after"


def test_template_contents_are_refreshed_and_stay_inert(page):
    frame, refresh = preview_frame(page)
    frame.locator("#draft").fill("Pendiente")
    result = refresh("before", "after", template="Después")
    assert result["applied"]
    assert frame.locator("#entry").evaluate("template => template.content.querySelector('p').textContent") == "Después"
    assert frame.locator("#draft").input_value() == "Pendiente"
    assert frame.evaluate("window.documentStamp") == "original"
    assert frame.evaluate("Boolean(window.inertScriptRan)") is False

    blocked = refresh("after", "script", extra='<script data-vsrc="pages/index.html:6:1">window.activeScriptRan = true</script>')
    assert not blocked["applied"]
    assert frame.evaluate("Boolean(window.activeScriptRan)") is False


def test_section_before_assistant_assets_refreshes_without_document_loads(page):
    def assistant_block(line, *, href="/assistant.css", src="/assistant.js", style="main { margin: 1rem }"):
        return f"""
          <link id="assistant-sheet" rel="stylesheet" href="{href}" data-vsrc="pages/index.html:{line}:1">
          <span hidden data-voice-assistant data-vsrc="pages/index.html:{line + 1}:1"></span>
          <script id="assistant-module" type="module" src="{src}" data-vsrc="pages/index.html:{line + 2}:1"></script>
          <style id="assistant-style" data-vsrc="pages/index.html:{line + 3}:1">{style}</style>"""

    frame, refresh = preview_frame(page, tail=assistant_block(10))
    full_document_loads = []
    page.on("framenavigated", lambda loaded: full_document_loads.append(loaded.url))
    selector = "#assistant-sheet, #assistant-module, #assistant-style"
    frame.evaluate("selector => { window.assistantAssets = [...document.querySelectorAll(selector)] }", selector)
    assert frame.evaluate("window.assistantStarts") == 1

    section = '<section id="booking" data-vsrc="pages/index.html:8:1">Reserva</section>'
    result = refresh("before", "after", extra=section, tail=assistant_block(11))
    assert result["applied"]
    assert frame.locator("#booking").inner_text() == "Reserva"
    assert frame.evaluate("window.documentStamp") == "original"
    assert len(full_document_loads) == 0
    assert frame.locator(selector).evaluate_all(
        "(nodes) => nodes.every((node, index) => node === window.assistantAssets[index])"
    )
    assert frame.evaluate("window.assistantStarts") == 1
    assert frame.locator("#assistant-sheet").get_attribute("data-vsrc") == "pages/index.html:11:1"
    assert frame.locator("#assistant-module").get_attribute("data-vsrc") == "pages/index.html:13:1"
    assert frame.locator("#assistant-style").get_attribute("data-vsrc") == "pages/index.html:14:1"
    assert frame.locator('meta[name="vitruvius-preview-revision"]').get_attribute("content") == "after"

    for change in ({"href": "/other.css"}, {"src": "/other.js"}, {"style": "main { margin: 2rem }"}):
        blocked = refresh("after", "asset-change", extra=section, tail=assistant_block(12, **change))
        assert not blocked["applied"]
        assert frame.locator("#assistant-sheet").get_attribute("data-vsrc") == "pages/index.html:11:1"
        assert frame.locator('meta[name="vitruvius-preview-revision"]').get_attribute("content") == "after"


def test_date_focus_segments_do_not_end_the_tab_walk(page):
    page.set_content("""<!doctype html><html lang="es"><style>
      :focus-visible {outline: 4px solid #365993}
      </style><form>
      <label>Concierto <input id="concierto"></label>
      <label>Fecha <input id="fecha" type="date"></label>
      <label>Plazas <input id="plazas" type="number"></label>
      <label>Grupo <input id="grupo"></label>
      <button id="pedir">Pedir reserva</button>
      </form></html>""")
    result = walk(page)
    assert result["complete"] and result["unreached"] == []
    assert [s["label"] for s in result["stops"]] == [
        "input#concierto", "input#fecha", "input#plazas", "input#grupo", "button#pedir",
    ]
    assert all(s["ring"] for s in result["stops"])

def test_identically_named_date_fields_remain_distinct_when_focus_wraps(page):
    page.set_content("""<!doctype html><form>
      <input type="date" aria-label="Fecha" name="salida">
      <input type="date" aria-label="Fecha" name="regreso">
      <button id="pedir">Pedir reserva</button>
      </form><script>
        document.querySelector('button').addEventListener('keydown', event => {
          if (event.key !== 'Tab') return;
          event.preventDefault();
          document.querySelector('input').focus();
        });
      </script>""")
    result = walk(page)
    assert result["complete"] and result["unreached"] == []
    assert [(stop["label"], stop["name"], stop["mark"]) for stop in result["stops"]] == [
        ("input", "Fecha", "1"),
        ("input", "Fecha", "2"),
        ("button#pedir", "Pedir reserva", "3"),
    ]


def test_highlight_finds_svg_and_figure_by_accessible_name(page):
    title = "Lámpara Lumbre: globo de vidrio sobre pie de latón"
    preview = f"""<!doctype html><meta charset="utf-8"><main>
      <figure aria-label="Producto principal">
        <svg role="img" aria-labelledby="piece-title" aria-label="Fallback" width="100" height="80">
          <title id="piece-title">{title}</title><circle cx="40" cy="40" r="30"/>
        </svg>
      </figure>
      <svg width="80" height="60"><title>Detalle del latón</title><rect width="40" height="40"/></svg>
      <svg hidden style="display:none" width="80" height="60"><title>{title}</title></svg>
    </main><script>{BRIDGE_JS}</script>"""

    def route(request):
        if request.request.url == ORIGIN + "/":
            return request.fulfill(content_type="text/html", body='<iframe src="/preview" width="370" height="640"></iframe>')
        if request.request.url == ORIGIN + "/preview":
            return request.fulfill(content_type="text/html; charset=utf-8", body=preview)
        return request.abort()

    page.emulate_media(reduced_motion="reduce")
    page.route("**/*", route)
    page.goto(ORIGIN + "/", wait_until="load")

    def highlight(label):
        return page.evaluate("""label => new Promise((resolve, reject) => {
          const frame = document.querySelector("iframe").contentWindow;
          const timer = setTimeout(() => reject(new Error(label)), 6000);
          function receive(event) {
            if (event.source !== frame || event.data?.type !== "dock/result" || event.data.id !== "highlight") return;
            clearTimeout(timer);
            window.removeEventListener("message", receive);
            resolve(event.data);
          }
          window.addEventListener("message", receive);
          frame.postMessage({hoardDock: 1, type: "dock/hello", host: "faustus"}, location.origin);
          frame.postMessage({hoardDock: 1, type: "dock/call", id: "highlight", tool: "app_highlight",
            args: {label, note: "Pieza de la página"}}, location.origin);
        })""", label)

    for name in (title, "Detalle del latón", "Producto principal"):
        reply = highlight(name)
        assert reply["ok"], (name, reply.get("error"))
        assert reply["result"]["highlighted"] == name
