import os

import pytest

from vitruvius_hoard.hoard_link.app_bridge import BRIDGE_JS


def test_preview_cursor_presence_expires_and_respects_reduced_motion():
    if os.environ.get("VITRUVIUS_BROWSER_TESTS") != "1":
        pytest.skip("Set VITRUVIUS_BROWSER_TESTS=1 to run Chrome cursor checks")
    from playwright.sync_api import expect, sync_playwright

    point = """([id, presence]) =>
        window.HoardApp.pointTo(document.getElementById('field'), {id}, {presence})"""
    prepare_html = '<div style="height: 900px"></div><input id="field">'

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": 390, "height": 640})
            page.clock.install()
            page.set_content(prepare_html)
            page.add_script_tag(content=BRIDGE_JS)
            actor = page.locator('.cursor[data-actor="assistant"]')
            other = page.locator('.cursor[data-actor="other"]')
            page.evaluate(point, ["other", False])
            page.evaluate(point, ["assistant", True])
            expect(actor).to_be_visible()
            page.clock.fast_forward(4100)
            expect(actor).to_have_count(0)
            expect(other).to_be_visible()
            page.evaluate(point, ["assistant", True])
            expect(actor).to_be_visible()
            page.evaluate("window.HoardApp.clearPoint({id: 'assistant'})")
            expect(actor).to_have_count(0)
            expect(other).to_be_visible()
            page.close()

            page = browser.new_page(viewport={"width": 390, "height": 640}, reduced_motion="reduce")
            page.set_content(prepare_html)
            page.add_script_tag(content=BRIDGE_JS)
            field = page.locator("#field")
            expect(field).not_to_be_in_viewport()
            page.evaluate(point, ["assistant", True])
            expect(field).to_be_in_viewport()
            expect(page.locator(".cursor")).to_have_count(0)
        finally:
            browser.close()
