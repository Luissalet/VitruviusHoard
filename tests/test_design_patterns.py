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
