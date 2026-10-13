import pytest

from vitruvius_hoard.design_patterns import catalogue, generate


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
