import json

import pytest

from vitruvius_hoard.agent_tools import tool_catalog
from vitruvius_hoard.app_projects import AppProjects
from vitruvius_hoard.software.host import catalog
from vitruvius_hoard.transfer_assistant import ENTRY, FORM_ENTRY


SCHEMA = {"type": "object", "properties": {"seats": {"type": "integer", "title": "Plazas"}},
          "required": ["seats"]}


def test_one_revision_adds_an_undoable_voice_assistant_without_changing_the_form(tmp_path):
    projects = AppProjects(tmp_path)
    initial = projects.create("Reservations")
    page = "pages/index.html"
    source = '<h1>Reservas</h1><form id="booking"><input name="seats" required></form>'
    original = projects.update(initial["id"], {page: source, ENTRY: "// existing transfer assistant"},
                               initial["revision"])
    arguments = {"id": original["id"], "page": page, "form_selector": "#booking", "schema": SCHEMA}
    added = projects.add_voice_assistant(**arguments, expected_revision=original["revision"])
    updated = projects.get(original["id"])
    assert updated["files"][page].startswith(source)
    assert FORM_ENTRY in updated["files"]
    assert updated["files"][ENTRY] == original["files"][ENTRY]
    assert updated["files"]["layout.html"] == original["files"]["layout.html"]
    assert added["undo"]["tool"] == "app_project_undo"

    retry = projects.add_voice_assistant(**arguments, expected_revision=original["revision"])
    assert retry == {**{name: value for name, value in added.items() if name != "undo"}, "changed": False}
    restored = projects.undo(**added["undo"]["arguments"])
    assert restored["files"] == original["files"]


def test_form_assistant_is_in_the_cold_mcp_catalog():
    name = "app_project_add_voice_assistant"
    frozen = next(tool for tool in catalog() if tool["name"] == name)
    native = next(tool for tool in tool_catalog() if tool["name"] == name)
    assert frozen == native
    assert not frozen["annotations"]["readOnlyHint"]
    assert "schema" in frozen["inputSchema"]["required"]


@pytest.mark.parametrize("schema", [
    {"type": "string"},
    {"type": "object", "properties": {"seats": {"type": "guess"}}},
    {**SCHEMA, "required": ["other"]},
])
def test_invalid_field_schema_does_not_create_a_revision(tmp_path, schema):
    projects = AppProjects(tmp_path)
    original = projects.create("Reservations")
    with pytest.raises(ValueError, match="[Ss]chema|required"):
        projects.add_voice_assistant(original["id"], original["revision"], "pages/index.html", "form", schema)
    assert projects.get(original["id"])["revision"] == original["revision"]
