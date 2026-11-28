"""The Canvas route and launcher use the selected Faustus and rename an existing session."""
import asyncio
import base64
import os
from urllib.parse import parse_qs

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
import httpx
import pytest

from hoard_link import copilot as shared_copilot, where as shared_where
from vitruvius_hoard.hoard_link import copilot, where
from vitruvius_hoard.hoard_link.service import install_error_handlers


PC = "http://127.0.0.1:7000"
SPARK = "https://spark3.test.invalid"
HOST = "https://vitruvius.test.invalid"
SESSION = "session-fixture"
CONVERSATION = "/api/hoard-copilot/conversations/" + SESSION
RENAME = "/api/session/" + SESSION
HEADER = "X-Hoard-Copilot-Destination"

PANEL = """
customElements.define('faustus-chat', class extends HTMLElement {
  session = 'session-fixture';
  connectedCallback() { this.refreshConversations(); }
  async refreshConversations() {
    const response = await this.fetch(location.origin + '/api/hoard-copilot/conversations/' + this.session);
    if (response.ok) this.textContent = (await response.json()).name;
  }
  async loadHistory() {}
});
"""
PAGE = """
<!doctype html><html lang="es"><meta charset="utf-8"><body>
<button id="open">Abrir conversación</button><div id="slot" data-hoard-copilot-inline-slot></div>
<script>
  window.hoardCopilot = { context: () => ({ project: { external_project_id: 'fixture-project' } }) };
  document.querySelector('#open').onclick = event => window.dispatchEvent(new CustomEvent('hoard:copilot-open',
    { detail: { container: document.querySelector('#slot'), trigger: event.currentTarget } }));
</script>
<script type="module" src="/api/copilot/launcher.js"></script>
</body></html>
"""


def fake_app(monkeypatch, tmp_path, modules=(copilot, where), *, panel_js=PANEL):
    relay, placement = modules
    state = {"online": {PC, SPARK}, "name": "Título inicial", "rename_status": 200, "patches": [],
             "delays": {}, "probes": [], "cancelled": []}
    document = {"location": "sparks", "node": "Spark 3", "urls": {"faustus": SPARK}, "job": {"running": False}}
    monkeypatch.setattr(placement, "current", lambda hub=None: document)

    async def upstream(request):
        base = str(request.url).removesuffix(request.url.path)
        assert base in {PC, SPARK}
        assert request.headers["authorization"] == "Bearer fixture-token"
        path = request.url.path
        capabilities = request.method == "GET" and path == "/api/hoard-copilot/capabilities"
        if capabilities:
            state["probes"].append(base)
            try:
                await asyncio.sleep(state["delays"].get(base, 0))
            except asyncio.CancelledError:
                state["cancelled"].append(base)
                raise
        if base not in state["online"]:
            raise httpx.ConnectError("Offline", request=request)
        if capabilities:
            return httpx.Response(200, json={"contract_version": "1.0"})
        if request.method == "GET" and path == "/api/hoard-copilot/panel.js":
            return httpx.Response(200, text=panel_js, headers={"content-type": "application/javascript"})
        if request.method == "GET" and path == CONVERSATION:
            return httpx.Response(200, json={"session_id": SESSION, "name": state["name"]})
        if request.method == "PATCH" and path == RENAME:
            assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
            name = parse_qs(request.content.decode())["name"][0]
            state["patches"].append((base, name))
            if state["rename_status"] != 200:
                return httpx.Response(state["rename_status"])
            state["name"] = name
            return httpx.Response(200, json={"id": SESSION, "name": name})
        pytest.fail(f"Unexpected request to the fake Faustus: {request.method} {path}")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(upstream), **kwargs))
    app = FastAPI()
    install_error_handlers(app)
    relay.install_copilot(app, "vitruvius", tmp_path, faustus_urls=[PC], token="fixture-token", inject=False)

    @app.get("/")
    def page():
        return HTMLResponse(PAGE)

    return TestClient(app, base_url=HOST), state


@pytest.mark.parametrize("modules", [(copilot, where), (shared_copilot, shared_where)])
def test_destination_tracks_the_endpoint_that_answers(monkeypatch, tmp_path, modules):
    client, state = fake_app(monkeypatch, tmp_path, modules)
    assert client.get("/api/copilot/info").json()["destination"] == "pc"

    proxy = "/api/copilot/proxy"
    state["online"] = {SPARK}
    failed = client.post(proxy, json={"path": CONVERSATION})
    assert failed.status_code == 503 and failed.headers[HEADER] == "connection_lost"
    response = client.get("/api/copilot/info")
    assert response.json()["destination"] == "spark:3"
    assert response.json()["settings_url"] == SPARK + "/studio/settings"
    assert client.post(proxy, json={"path": CONVERSATION}).headers[HEADER] == "spark:3"

    state["online"] = set()
    unavailable = client.get("/api/copilot/info")
    assert unavailable.status_code == 503
    assert unavailable.headers[HEADER] == "unavailable"
    failed = client.post(proxy, json={"path": CONVERSATION})
    assert failed.status_code == 503 and failed.headers[HEADER] == "unavailable"


@pytest.mark.parametrize("modules", [(copilot, where), (shared_copilot, shared_where)])
def test_fast_destination_wins_and_is_preferred_on_recheck(monkeypatch, tmp_path, modules):
    client, state = fake_app(monkeypatch, tmp_path, modules)
    state["delays"][PC] = 3
    assert client.get("/api/copilot/info").json()["destination"] == "spark:3"
    assert state["probes"] == [PC, SPARK]
    assert state["cancelled"] == [PC]

    state["probes"].clear()
    state["delays"].clear()
    assert client.get("/api/copilot/info").json()["destination"] == "spark:3"
    assert state["probes"] == [SPARK]


def test_relay_passes_the_native_rename_form(monkeypatch, tmp_path):
    client, state = fake_app(monkeypatch, tmp_path)
    envelope = {"path": RENAME, "method": "PATCH", "content_type": "application/x-www-form-urlencoded",
                "raw_body": base64.b64encode(b"name=Apuntes+del+estudio").decode("ascii")}
    response = client.post("/api/copilot/proxy", json=envelope)
    assert response.json() == {"id": SESSION, "name": "Apuntes del estudio"}
    assert state["patches"] == [(PC, "Apuntes del estudio")]
    assert client.post("/api/copilot/proxy", json={"path": CONVERSATION}).json()["name"] == "Apuntes del estudio"


@pytest.mark.skipif(os.getenv("VITRUVIUS_BROWSER_TESTS") != "1", reason="Set VITRUVIUS_BROWSER_TESTS=1 for the Chrome test")
def test_inline_conversation_renames_and_handles_unavailable_faustus(monkeypatch, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    client, state = fake_app(monkeypatch, tmp_path)

    pending_info = []
    hold_info = True

    def respond(route):
        request = route.request
        if hold_info and request.url == HOST + "/api/copilot/info":
            pending_info.append(route)
            return
        if not request.url.startswith(HOST + "/"):
            return route.abort()
        response = client.request(request.method, request.url, content=request.post_data_buffer,
                                  headers=request.headers)
        return route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)

    with playwright.sync_playwright() as instance:
        browser = instance.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu", "--mute-audio"])
        try:
            page = browser.new_page(viewport={"width": 390, "height": 850})
            page.route("**/*", respond)
            state["online"] = set()
            page.goto(HOST)
            with page.expect_request(HOST + "/api/copilot/info"):
                page.get_by_role("button", name="Abrir conversación").click()
            playwright.expect(page.get_by_text("Buscando Faustus…", exact=True)).to_be_visible()
            assert len(pending_info) == 1
            hold_info = False
            respond(pending_info.pop())
            playwright.expect(page.get_by_role("alert")).to_contain_text("Ningún Faustus responde")
            state["online"] = {PC, SPARK}
            page.get_by_role("button", name="Reintentar").click()
            playwright.expect(page.get_by_text("Faustus · PC")).to_be_visible()
            chat = page.locator("faustus-chat")
            playwright.expect(chat).to_have_text("Título inicial")
            mounted = chat.element_handle()

            close = page.get_by_role("button", name="Cerrar Faustus")
            opener = page.get_by_role("button", name="Abrir conversación")
            close.click()
            state["online"].clear()
            with page.expect_response("**/api/copilot/info") as reopened:
                opener.click()
            assert reopened.value.status == 503
            playwright.expect(page.get_by_text("Ningún Faustus responde.", exact=True)).to_be_visible()

            close.click()
            state["online"] = {SPARK}
            opener.click()
            playwright.expect(page.get_by_text("Faustus · Spark 3")).to_be_visible()
            assert mounted.evaluate("(element) => element === document.querySelector('faustus-chat')")
            assert state["patches"] == []

            page.get_by_text("Renombrar conversación").click()
            page.get_by_label("Nuevo nombre").fill("Notas del encargo")
            state["rename_status"] = 404
            page.get_by_role("button", name="Guardar").click()
            playwright.expect(page.get_by_text("Este Faustus no permite renombrar conversaciones.")).to_be_visible()
            assert state["name"] == "Título inicial"

            state["rename_status"] = 200
            page.get_by_role("button", name="Guardar").click()
            playwright.expect(page.get_by_text("Nombre guardado.")).to_be_visible()
            playwright.expect(page.locator("faustus-chat")).to_have_text("Notas del encargo")
            assert state["patches"] == [(SPARK, "Notas del encargo")] * 2
        finally:
            browser.close()


STOP_PANEL = """
customElements.define('faustus-chat', class extends HTMLElement {
  session = 'session-fixture';
  connectedCallback() {
    const root = this.attachShadow({mode: 'open'});
    root.innerHTML = '<textarea aria-label="Mensaje"></textarea><button>Enviar</button><button>Detener</button>';
    const [input, send, stop] = root.children;
    send.onclick = async () => {
      input.disabled = true;
      const response = await this.fetch(location.origin + '/api/chat_stream', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message: input.value}),
      });
      this.dispatchEvent(new CustomEvent('faustus:turn-start', {detail: {sessionId: this.session}}));
      const text = await response.text();
      if (!text.includes('data: [DONE]')) return;
      input.disabled = false;
      this.dispatchEvent(new CustomEvent('faustus:turn-end', {detail: {
        sessionId: this.session, reason: text.includes('"type":"error"') ? 'error' : 'done',
      }}));
    };
    stop.onclick = async () => {
      // The embed leaves the observer running when the backend rejects a stop.
      try {
        await this.fetch(location.origin + '/api/chat/stop/' + this.session, {method: 'POST'});
      } catch {}
    };
  }
  async loadHistory() {}
});
"""

STOP_TRANSPORT = """
window.recovery = {turns: 0, cancelled: 0, stop: null, end: null};
const nativeFetch = window.fetch.bind(window);
window.fetch = (input, init) => {
  const route = new URL(typeof input === 'string' ? input : input.url, location.href);
  if (route.pathname !== '/api/copilot/proxy') return nativeFetch(input, init);
  const envelope = JSON.parse(init.body);
  if (envelope.path === '/api/chat_stream') {
    window.recovery.turns++;
    const stream = new ReadableStream({
      start(controller) {
        window.recovery.end = () => {
          controller.enqueue(new TextEncoder().encode('data: [DONE]\\n\\n'));
          controller.close();
        };
      },
      cancel() { window.recovery.cancelled++; },
    });
    return Promise.resolve(new Response(stream, {headers: {'Content-Type':'text/event-stream; charset=utf-8'}}));
  }
  if (envelope.path === '/api/chat/stop/session-fixture') {
    if (window.recovery.stop === 'offline') return Promise.reject(new TypeError('Failed to fetch'));
    if (window.recovery.stop === 'busy') {
      return Promise.resolve(Response.json({stopped:false, reason:'no_run_id_supplied'}));
    }
    if (window.recovery.stop === 'unavailable') {
      return Promise.resolve(Response.json({error:'Faustus copilot is unavailable on the configured endpoints'},
        {status:503, headers:{'X-Hoard-Copilot-Destination':'unavailable'}}));
    }
    window.recovery.end();
    return Promise.resolve(Response.json({stopped:true}));
  }
  return nativeFetch(input, init);
};
"""


@pytest.mark.skipif(os.getenv("VITRUVIUS_BROWSER_TESTS") != "1", reason="Set VITRUVIUS_BROWSER_TESTS=1 for the Chrome test")
@pytest.mark.parametrize("outcome", ["unavailable", "offline", "busy", "stopped"])
def test_failed_stop_releases_the_composer(monkeypatch, tmp_path, outcome):
    playwright = pytest.importorskip("playwright.sync_api")
    client, _ = fake_app(monkeypatch, tmp_path, panel_js=STOP_PANEL)

    def respond(route):
        request = route.request
        if not request.url.startswith(HOST + "/"):
            return route.abort()
        response = client.request(request.method, request.url, content=request.post_data_buffer, headers=request.headers)
        return route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)

    with playwright.sync_playwright() as instance:
        browser = instance.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu", "--mute-audio"])
        try:
            page = browser.new_page(service_workers="block")
            page.add_init_script(STOP_TRANSPORT)
            page.route("**/*", respond)
            page.goto(HOST)
            page.get_by_role("button", name="Abrir conversación").click()
            chat = page.locator("faustus-chat")
            composer = chat.get_by_role("textbox", name="Mensaje")
            composer.fill("Cambia el título")
            chat.get_by_role("button", name="Enviar").click()
            playwright.expect(composer).to_be_disabled()
            page.wait_for_function("window.recovery.turns === 1")
            page.evaluate("(value) => window.recovery.stop = value", outcome)
            chat.get_by_role("button", name="Detener").click()
            playwright.expect(composer).to_be_enabled(timeout=2500)
            assert chat.evaluate("element => element.session") == SESSION
            notice = page.get_by_text("No se pudo confirmar que el trabajo se haya detenido.", exact=False)
            if outcome == "stopped":
                playwright.expect(notice).to_have_count(0)
            else:
                playwright.expect(notice).to_be_visible()
                page.wait_for_function("window.recovery.cancelled === 1")
            composer.fill("Prueba siguiente")
            chat.get_by_role("button", name="Enviar").click()
            page.wait_for_function("window.recovery.turns === 2")
            playwright.expect(notice).not_to_be_visible()
        finally:
            browser.close()
