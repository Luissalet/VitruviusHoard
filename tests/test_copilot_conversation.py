"""The Canvas route and launcher use the selected Faustus and rename an existing session."""
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


def fake_app(monkeypatch, tmp_path, modules=(copilot, where)):
    relay, placement = modules
    state = {"online": {PC, SPARK}, "name": "Título inicial", "rename_status": 200, "patches": []}
    document = {"location": "sparks", "node": "Spark 3", "urls": {"faustus": SPARK}, "job": {"running": False}}
    monkeypatch.setattr(placement, "current", lambda hub=None: document)

    def upstream(request):
        base = str(request.url).removesuffix(request.url.path)
        assert base in {PC, SPARK}
        assert request.headers["authorization"] == "Bearer fixture-token"
        if base not in state["online"]:
            raise httpx.ConnectError("Offline", request=request)
        path = request.url.path
        if request.method == "GET" and path == "/api/hoard-copilot/capabilities":
            return httpx.Response(200, json={"contract_version": "1.0"})
        if request.method == "GET" and path == "/api/hoard-copilot/panel.js":
            return httpx.Response(200, text=PANEL, headers={"content-type": "application/javascript"})
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
    assert client.post(proxy, json={"path": CONVERSATION}).status_code == 503
    unavailable = client.get("/api/copilot/info")
    assert unavailable.status_code == 503
    assert unavailable.headers[HEADER] == "unavailable"


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

    def respond(route):
        request = route.request
        if not request.url.startswith(HOST + "/"):
            return route.abort()
        response = client.request(request.method, request.url, content=request.post_data_buffer,
                                  headers=request.headers)
        return route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)

    with playwright.sync_playwright() as instance:
        browser = instance.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
        try:
            page = browser.new_page(viewport={"width": 390, "height": 850})
            page.route("**/*", respond)
            state["online"] = set()
            page.goto(HOST)
            page.get_by_role("button", name="Abrir conversación").click()
            playwright.expect(page.get_by_role("alert")).to_contain_text("Ningún Faustus responde")
            state["online"] = {SPARK}
            page.get_by_role("button", name="Reintentar").click()
            playwright.expect(page.get_by_text("Faustus · Spark 3")).to_be_visible()
            playwright.expect(page.locator("faustus-chat")).to_have_text("Título inicial")

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
