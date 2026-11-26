"""The banking example in a browser: a confirmation runs exactly the reviewed transfer and expires on edits.

The example runs on the project runtime. The shared transfer assistant is replaced by a stand-in module that lets the
test play its draft, readiness and confirmation through the same options the real panel uses."""
import json
import shutil
import threading
from pathlib import Path

import pytest

from vitruvius_hoard import app_runtime

EXAMPLE = Path(__file__).resolve().parents[1] / "docs" / "examples" / "app-projects" / "personal-banking"

STAND_IN = """
export function mountTransferAssistant(root, options) {
  root.dataset.transferPhase = 'collecting';
  const panel = {options, draft: null,
    async ready(slots) { panel.draft = slots; options.onDraft?.({slots, phase: 'ready', candidates: [], next: null}); root.dataset.transferPhase = 'ready'; },
    async submit(text) {
      if (text !== 'confirmo' || root.dataset.transferPhase !== 'ready') return false;
      // Like the panel, a confirmation turn reports the draft again before executing it.
      options.onDraft?.({slots: panel.draft, phase: 'executing', candidates: [], next: null});
      try { await options.execute({...panel.draft}, 'panel-key'); root.dataset.transferPhase = 'complete'; }
      catch (error) { root.dataset.transferPhase = 'ready'; panel.rejected = error.code; }
      return true;
    }};
  window.standInPanel = panel;
  return panel;
}
"""


@pytest.fixture
def bank(tmp_path):
    pytest.importorskip("playwright")
    root = tmp_path / "app"
    shutil.copytree(EXAMPLE, root)
    (root / "assets" / "transfer-assistant").mkdir()
    (root / "assets" / "transfer-assistant" / "assistant.js").write_text(STAND_IN, encoding="utf-8")
    server = app_runtime.make_server(root, tmp_path / "app.db")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def page(bank):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = None
        for options in ({}, {"channel": "chrome"}):
            try:
                browser = playwright.chromium.launch(headless=True, **options)
                break
            except Exception:  # bundled browser or installed channel missing
                continue
        if browser is None:
            pytest.skip("no headless browser")
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        posts = []
        page.on("request", lambda r: posts.append(json.loads(r.post_data or "{}")) if r.method == "POST" and "/api/actions/transferir" in r.url else None)
        page.goto(bank + "/transferir")
        page.wait_for_function("() => window.teselaTransfer && window.standInPanel")
        page.posts = posts
        yield page
        browser.close()


def balances(page):
    rows = page.evaluate("async () => (await (await fetch('/api/collections/cuentas')).json()).records")
    return {row["id"]: row["saldo_cent"] for row in rows}


def read_by_panel(page):
    page.evaluate("""async () => {
      window.teselaTransfer.set({contacto: 'maria-ortega', importe: '12,50', concepto: 'entradas de cine', origen: 'cuenta-diaria'});
      await window.standInPanel.ready({source: 'cuenta-diaria', recipient: {id: 'maria-ortega', name: 'María Ortega Ruiz'}, amountCents: 1250, concept: 'entradas de cine'});
      window.teselaTransfer.review({focus: false, via: 'voz'});
    }""")


def test_form_confirmation_sends_the_reviewed_destination_not_the_read_one(page):
    read_by_panel(page)
    before = balances(page)
    page.click("#transfer-back")
    page.check("#modo-propia", force=True)
    page.select_option("#destino", "cuenta-ahorro")
    page.click("#transfer-review")
    page.click("#transfer-confirm")
    page.wait_for_selector("#receipt-ref")
    assert [{k: v for k, v in post.items() if k != "fecha"} for post in page.posts] == [
        {"origen": "cuenta-diaria", "importe_cent": 1250, "concepto": "entradas de cine", "destino": "cuenta-ahorro"}]
    after = balances(page)
    assert after["cuenta-ahorro"] - before["cuenta-ahorro"] == 1250
    assert after["cuenta-diaria"] - before["cuenta-diaria"] == -1250


def test_panel_cannot_confirm_a_draft_the_form_changed(page):
    read_by_panel(page)
    before = balances(page)
    page.click("#transfer-back")
    page.check("#modo-propia", force=True)
    page.evaluate("() => window.standInPanel.submit('confirmo')")
    assert page.evaluate("() => window.standInPanel.rejected") == "draft_changed"
    assert page.posts == [] and balances(page) == before


def test_a_review_expires_when_a_field_is_edited(page):
    page.select_option("#contacto", "lucia-ferrer")
    page.fill("#importe", "20")
    page.fill("#concepto", "Cena")
    page.click("#transfer-review")
    page.click("#transfer-back")
    page.fill("#importe", "30")
    assert page.evaluate("async () => (await window.teselaTransfer.confirm()).ok") is False
    assert page.posts == []
    page.click("#transfer-review")
    page.click("#transfer-confirm")
    page.wait_for_selector("#receipt-ref")
    assert [post["importe_cent"] for post in page.posts] == [3000]


def test_matching_read_draft_confirms_through_the_panel(page):
    read_by_panel(page)
    page.click("#transfer-confirm")
    page.wait_for_selector("#receipt-ref")
    assert [post.get("contacto") for post in page.posts] == ["maria-ortega"]
    page.wait_for_function("() => document.getElementById('voz-asistente').dataset.transferPhase === 'complete'")


def test_a_correction_while_ready_updates_the_form_summary(page):
    read_by_panel(page)
    page.wait_for_function("() => document.getElementById('transfer-summary').innerText.includes('12,50')")
    page.wait_for_timeout(1500)  # the review scheduled when the panel became ready has run
    page.evaluate("""async () => {
      // The panel fills its slots in place, without leaving the confirmation step.
      for (const [id, value] of [['contacto', 'lucia-ferrer'], ['importe', '60,00']]) {
        const field = document.getElementById(id);
        field.value = value;
        field.dispatchEvent(new Event('input', {bubbles: true}));
        field.dispatchEvent(new Event('change', {bubbles: true}));
      }
      await window.standInPanel.ready({source: 'cuenta-diaria', recipient: {id: 'lucia-ferrer', name: 'Lucía Ferrer Soler'}, amountCents: 6000, concept: 'entradas de cine'});
    }""")
    page.wait_for_function("() => document.getElementById('transfer-form').dataset.step === 'confirmar' && document.getElementById('transfer-summary').innerText.includes('60,00')")
    assert "Lucía Ferrer Soler" in page.inner_text("#transfer-summary")
    page.click("#transfer-confirm")
    page.wait_for_selector("#receipt-ref")
    assert [(post.get("contacto"), post["importe_cent"]) for post in page.posts] == [("lucia-ferrer", 6000)]
