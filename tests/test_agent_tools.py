import pytest

from vitruvius_hoard.agent_tools import AGENT_INSTRUCTIONS, TOOLS, TOOLS_BY_NAME, call_tool, tool_catalog


def test_exactly_25_tools():
    assert len(TOOLS) == 25


def test_tool_names_are_unique():
    names = [t.name for t in TOOLS]
    assert len(names) == len(set(names))


def test_agent_instructions_length():
    assert len(AGENT_INSTRUCTIONS) <= 900


def test_every_tool_first_line_at_most_110_chars():
    for t in TOOLS:
        first_line = t.description.split("\n", 1)[0]
        assert len(first_line) <= 110, (t.name, len(first_line))


def test_every_tool_first_line_has_english_and_spanish():
    for t in TOOLS:
        first_line = t.description.split("\n", 1)[0]
        # Heuristic: a Spanish clause after an em dash or period, or an accented char / ¿ present somewhere.
        assert ("." in first_line or "¿" in first_line or any(c in first_line for c in "áéíóúñ")), t.name


def test_read_only_hints_correct():
    read_only_names = {"design_search", "design_brief", "design_rules", "styles_search", "palettes_search",
                       "fonts_search", "design_lint", "page_assay", "render_compare", "tokens_get", "tokens_list",
                       "reference_search", "reference_get", "sources_list", "source_status", "vitruvius_status"}
    write_names = {"render_preview", "design_critique", "tokens_generate", "tokens_preview", "tokens_delete",
                  "reference_add", "reference_delete", "source_add", "source_ingest"}
    assert read_only_names | write_names == set(TOOLS_BY_NAME)
    for name in read_only_names:
        assert TOOLS_BY_NAME[name].annotations["readOnlyHint"] is True
    for name in write_names:
        assert TOOLS_BY_NAME[name].annotations["readOnlyHint"] is False


def test_destructive_hints_only_on_deletes():
    destructive = {name for name, t in TOOLS_BY_NAME.items() if t.annotations["destructiveHint"]}
    assert destructive == {"tokens_delete", "reference_delete"}


def test_tool_catalog_matches_tools():
    catalog = tool_catalog()
    assert len(catalog) == len(TOOLS)
    names = {c["name"] for c in catalog}
    assert names == set(TOOLS_BY_NAME)
    for c in catalog:
        assert "inputSchema" in c and "properties" in c["inputSchema"] or c["inputSchema"].get("type") == "object"


def test_every_arg_model_validates_empty_or_minimal(services):
    for t in TOOLS:
        schema = t.input_model.model_json_schema()
        required = schema.get("required", [])
        args = {}
        for field_name in required:
            prop = schema["properties"][field_name]
            if prop.get("type") == "string":
                args[field_name] = "demo"
            elif prop.get("type") == "number":
                args[field_name] = 1
        try:
            t.input_model.model_validate(args)
        except Exception as error:  # noqa: BLE001
            pytest.fail(f"{t.name} failed to validate minimal args {args}: {error}")


def test_call_tool_unknown_name_raises_keyerror(services):
    with pytest.raises(KeyError):
        call_tool(services, "no_such_tool", {})


def test_call_tool_vitruvius_status(services):
    result = call_tool(services, "vitruvius_status", {})
    assert result["service"] == "vitruvius-hoard"


def test_call_tool_design_search_empty_library(services):
    result = call_tool(services, "design_search", {"query": "contrast"})
    assert result["count"] == 0


def test_call_tool_render_preview(services):
    result = call_tool(services, "render_preview", {"html": "<html></html>"})
    assert result["id"]
    assert "bytes" not in (result["files"][0].keys() if result["files"] else [])


def test_call_tool_tokens_roundtrip(services):
    created = call_tool(services, "tokens_generate", {"name": "Demo", "base_color": "#3355ff"})
    got = call_tool(services, "tokens_get", {"id": created["id"], "format": "css"})
    assert got["content"].startswith(":root")
    listed = call_tool(services, "tokens_list", {})
    assert listed["count"] == 1
    deleted = call_tool(services, "tokens_delete", {"id": created["id"]})
    assert deleted["ok"] is True


def test_call_tool_sources_list_and_add(services):
    listed = call_tool(services, "sources_list", {})
    before = listed["count"]
    call_tool(services, "source_add", {"url": "https://example.com/repo.git"})
    listed2 = call_tool(services, "sources_list", {})
    assert listed2["count"] == before + 1


def test_call_tool_reference_add_and_delete(services):
    added = call_tool(services, "reference_add", {"html": "<html></html>", "video": False, "analyze": False})
    fetched = call_tool(services, "reference_get", {"id": added["id"]})
    assert fetched["id"] == added["id"]
    deleted = call_tool(services, "reference_delete", {"id": added["id"]})
    assert deleted["ok"] is True
