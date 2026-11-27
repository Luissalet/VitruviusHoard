from __future__ import annotations

import json

import pytest

from vitruvius_hoard.app_materials import describe_materials
from vitruvius_hoard.app_projects import AppProjects

TOKEN_ID = "3c322d57931c"
EXAMPLES = [
    "book", "motion.long-durations", "kiln-ember", "showcase/rock",
    "slop/bounce-easing", "unslop/floating-loop",
]


def test_history_and_presence_resolve_catalogue_names_without_changing_saved_ids(tmp_path, monkeypatch):
    projects = AppProjects(tmp_path)
    active = []
    monkeypatch.setattr(projects.canvas, "prepare_edit", lambda *args, change, **kwargs: active.append(change))
    original = projects.create("Local history fixture")
    updated = projects.update(
        original["id"], {"pages/index.html": "<h1>Updated page</h1>"},
        original["revision"], actor={"id": "editor", "name": "Editor"}, examples=EXAMPLES, tokens_id=TOKEN_ID,
    )
    shown = updated["history"][-1]
    assert shown["examples"] == EXAMPLES and shown["tokens_id"] == TOKEN_ID
    assert shown["materials"] == active[0]["materials"]
    references = shown["materials"]["references"]
    assert [(r["kind"], r["en"]) for r in references] == [
        ("example", "Double-page book"), ("motion", "Long transition durations"),
        ("preset", "Kiln Ember"), ("example", "Product on rock"), ("tokens", "Palette and typography"),
    ]
    assert [r["es"] for r in references] == [
        "Libro a doble página", "Transiciones demasiado largas", "Kiln Ember",
        "Producto sobre roca", "Paleta y tipografía",
    ]
    warnings = shown["materials"]["warnings"]
    assert len(warnings) == 2 and all(item["kind"] == "lint" for item in warnings)
    assert all(item["es"] != item["en"] for item in warnings)
    serialized = json.dumps(shown["materials"])
    assert TOKEN_ID not in serialized and not any(item in serialized for item in EXAMPLES[1:])

    saved = tmp_path / "app-projects" / original["id"] / "project-index.json"
    raw = json.loads(saved.read_text(encoding="utf-8"))
    assert "materials" not in raw["history"][-1]
    older = AppProjects(tmp_path)
    assert older.get(original["id"])["history"][-1] == shown


@pytest.mark.parametrize("title", [None, TOKEN_ID, "System " + TOKEN_ID])
def test_unknown_references_and_opaque_token_titles_have_no_raw_ids(title):
    unknown = "77312d45c931"
    entry = {"examples": [unknown, "quality/unregistered", unknown], "tokens_id": TOKEN_ID}
    materials = describe_materials(entry, lambda _: title)
    assert materials["references"] == [
        {"kind": "example", "es": "Referencia sin nombre en el catálogo", "en": "Unnamed library reference"},
        {"kind": "tokens", "es": "Paleta y tipografía", "en": "Palette and typography"},
    ]
    assert materials["warnings"] == [
        {"kind": "lint", "es": "Aviso sin nombre en el catálogo", "en": "Unnamed lint finding"},
    ]


def test_saved_token_title_and_known_quality_rule():
    materials = describe_materials(
        {"examples": ["quality/gray-on-color"], "tokens_id": TOKEN_ID}, lambda _: "Reading room palette",
    )
    assert materials["references"] == [{"kind": "tokens", "es": "Reading room palette", "en": "Reading room palette"}]
    warning = materials["warnings"][0]
    assert warning["kind"] == "lint" and warning["es"] != warning["en"]
