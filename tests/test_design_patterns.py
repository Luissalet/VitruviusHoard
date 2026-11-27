import os

import pytest

from vitruvius_hoard.design_patterns import catalogue, generate, recommend


@pytest.mark.parametrize("pattern", [item["id"] for item in catalogue()])
def test_literal_text_and_complete_source(pattern):
    payload = '</script><script>window.injected=true</script> á 👩‍🚀 & "'
    result = generate(pattern, payload)
    assert payload not in result["html"]
    assert result["parameters"]["text"] == payload
    assert '<meta name="viewport"' in result["html"]
    assert 'src="http' not in result["html"]


def test_catalogue_is_not_mutable_and_invalid_input():
    catalogue()[0]["tags"].append("modified")
    assert "modified" not in catalogue()[0]["tags"]
    with pytest.raises(ValueError):
        generate("unknown")
    with pytest.raises(ValueError):
        generate("editorial", accent="red; background: url(x)")


def test_form_pattern_packages_a_reusable_localized_recipe():
    result = generate("form-controls")
    assert result["parameters"]["lang"] == "es-ES"
    assert '<html lang="es-ES">' in result["html"] and "Reserva de sala" in result["html"]
    recipe = result["recipe"]
    assert set(recipe) == {"markup", "css", "script"}
    assert 'type="date"' in recipe["markup"] and 'type="time"' in recipe["markup"]
    assert "var(--color-surface" in recipe["css"] and "FormData" not in recipe["script"]
    assert "Room booking" in generate("form-controls", lang="en-US")["html"]
    with pytest.raises(ValueError):
        generate("form-controls", lang='en"><script>')


def test_form_recommendation_handles_fragments_and_ignores_hidden_templates():
    for source in ('<form><input></form>', '<select name="station"></select>',
                   '<section role="form"><label>A<input type="text"></label></section>'):
        assert [item["id"] for item in recommend(source)] == ["form-controls"]
    assert recommend("<template><form></form></template>") == []
    assert recommend("<form hidden><select></select></form>") == []
    assert recommend("<script>const code = '<form>';</script>") == []
    assert recommend("<form></form>", has_form=False) == []



def test_temporal_fields_emit_one_canonical_change_on_confirmation():
    if os.environ.get("VITRUVIUS_BROWSER_TESTS") != "1":
        pytest.skip("Set VITRUVIUS_BROWSER_TESTS=1 to run the real browser flow")
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
        try:
            page = browser.new_page(viewport={"width": 834, "height": 900}, locale="en-US")
            page.route("**/*", lambda route: route.abort())
            page.set_content(generate("form-controls")["html"])
            date = page.get_by_role("textbox", name="Fecha")
            time = page.get_by_role("textbox", name="Hora")
            expect(date).to_have_value("30/11/2026")
            page.get_by_label("Sala").select_option("library")
            page.locator("form").evaluate("""form => {
              window.commits = [];
              form.addEventListener("change", event => window.commits.push([event.target.name, event.target.value]));
            }""")

            date.fill("31/02/2027")
            date.press("Tab")
            assert page.evaluate("window.commits") == []
            date.fill("31/12/2026")
            assert page.evaluate("window.commits") == []
            date.press("Tab")
            expected = [["date", "2026-12-31"]]
            assert page.evaluate("window.commits") == expected
            date.focus()
            date.press("Tab")
            assert page.evaluate("window.commits") == expected

            page.locator('input[type=date][name=date]').evaluate("""field => {
              field.value = "2027-01-15";
              field.dispatchEvent(new Event("change", { bubbles: true }));
            }""")
            expected.append(["date", "2027-01-15"])
            expect(date).to_have_value("15/01/2027")
            assert page.evaluate("window.commits") == expected

            time.fill("2030")
            time.press("Enter")
            expected.append(["time", "20:30"])
            assert page.evaluate("window.commits") == expected
            assert page.locator("form").evaluate("form => new FormData(form).get('time')") == "20:30"

            page.get_by_role("button", name="Restablecer").click()
            expect(date).to_have_value("30/11/2026")
            date.fill("15/01/2027")
            date.press("Tab")
            assert page.evaluate("window.commits") == [*expected, ["date", "2027-01-15"]]
        finally:
            browser.close()
