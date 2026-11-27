import json
from types import SimpleNamespace

import pytest

from vitruvius_hoard.software.host import catalog, create_app
from vitruvius_hoard.software.library_setup import SOURCE


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("VITRUVIUS_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("VITRUVIUS_TOKEN_FILE", str(tmp_path / "mcp-token"))
    monkeypatch.setenv("VITRUVIUS_PORT", "56149")
    monkeypatch.setenv("VITRUVIUS_EMBED", "none")
    monkeypatch.setenv("HOARD_EVENTS", "0")

    async def close_link():
        return None

    monkeypatch.setattr("vitruvius_hoard.software.global_models.GlobalLink",
                        lambda config: SimpleNamespace(sync=None, aclose=close_link))
    return tmp_path


def modules(status):
    return {item["module"]: item for item in status["modules"]}


@pytest.mark.asyncio
async def test_new_profile_prepares_searchable_library_and_respects_off_at_restart(profile):
    app = create_app()
    async with app.router.lifespan_context(app):
        execute = app.state.execute
        snapshot = await execute("software_modules", {})
        assert modules(snapshot)["design"]["enabled"]
        assert all(not item["automatic"] for item in modules(snapshot).values())
        assert not modules(snapshot)["babel"]["enabled"]
        assert not modules(snapshot)["theseus"]["enabled"]

        prepared = snapshot["library"]
        assert prepared["ok"], prepared["errors"]
        available = prepared["available"]
        assert available["presets"] == available["styles"] == available["palettes"] > 100
        assert available["font_pairings"] > 10 and available["chunks"] > 200
        assert available["recipes"] == available["references"] == 5
        assert available["patterns"] == 8 and available["motion_examples"] == 3
        results = await execute("design_search", {"query": "muelle amortiguado", "mode": "bm25", "source": SOURCE})
        assert results["items"], results

        repeated = await execute("design_library_prepare", {})
        assert repeated["available"] == available
        assert repeated["added"] == {"catalogue": False, "motion_examples": 0, "references": 0}
        assert repeated["undo"] is None
        await execute("software_module_set", {"module": "design", "enabled": False})

    restarted = create_app()
    async with restarted.router.lifespan_context(restarted):
        snapshot = await restarted.state.execute("software_modules", {})
        assert not modules(snapshot)["design"]["enabled"]
        assert snapshot["library"]["available"] == available


@pytest.mark.asyncio
async def test_explicit_preparation_undo_keeps_existing_sources_and_edited_example(profile):
    (profile / "software-modules.json").write_text(json.dumps(
        {"version": 1, "modules": {"design": {"enabled": False, "automatic": True}}}
    ), encoding="utf-8")
    app = create_app()
    async with app.router.lifespan_context(app):
        execute = app.state.execute
        assert not modules(await execute("software_modules", {}))["design"]["enabled"]
        prepared = await execute("design_library_prepare", {})
        assert prepared["ok"] and prepared["added"]["references"] == 5
        assert not prepared["module"]["automatic"]

        id = prepared["motion"]["caption"]
        saved = await execute("motion_get", {"id": id})
        updated = {**saved["composition"], "title": "Custom caption"}
        await execute("motion_save", {"id": id, "expected_revision": 1, "composition": updated})
        await execute("source_add", {"id": "my-notes", "kind": "url", "url": "https://example.invalid/notes"})
        await execute("design_library_prepare", {})  # The previous token remains valid on a no-op.

        undo = prepared["undo"]
        result = await execute(undo["tool"], undo["arguments"])
        assert result["removed"] == {"catalogue": True, "motion_examples": 2, "references": 5}
        assert result["retained"] == [id]
        assert result["module_restored"] and result["module"]["automatic"] and not result["module"]["enabled"]

        await execute("software_module_set", {"module": "design", "enabled": True})
        source_list = await execute("sources_list", {})
        source_ids = {item["id"] for item in source_list["sources"]}
        assert "my-notes" in source_ids and SOURCE not in source_ids
        assert (await execute("motion_get", {"id": id}))["composition"]["title"] == "Custom caption"
        assert not (await execute("reference_collections", {}))["collections"]


@pytest.mark.asyncio
@pytest.mark.parametrize("disabled", [False, True])
async def test_interrupted_first_start_can_resume(profile, monkeypatch, disabled):
    from vitruvius_hoard.software import library_setup

    def interrupted(*args):
        raise OSError("first start interrupted before preparing data")

    first = create_app()
    with monkeypatch.context() as patch:
        patch.setattr(library_setup, "prepare", interrupted)
        async with first.router.lifespan_context(first):
            execute = first.state.execute
            status = await execute("software_modules", {})
            assert modules(status)["design"]["enabled"]
            assert not status["library"]["ok"]
            if disabled:
                await execute("software_module_set", {"module": "design", "enabled": False})

    restarted = create_app()
    async with restarted.router.lifespan_context(restarted):
        execute = restarted.state.execute
        status = await execute("software_modules", {})
        if disabled:
            assert not modules(status)["design"]["enabled"]
            assert "library" not in status
            status = {"library": await execute("design_library_prepare", {})}
        else:
            assert modules(status)["design"]["enabled"]
        assert status["library"]["ok"]
        assert status["library"]["available"]["references"] == 5
        saved = json.loads((profile / "library-preparation.json").read_text(encoding="utf-8"))
        assert "first_start_pending" not in saved



def test_preparation_tool_descriptions_are_brief():
    controls = [row for row in catalog() if row["name"] in {"design_library_prepare", "design_library_undo"}]
    assert len(controls) == 2
    assert all(len(row["description"].splitlines()[0]) <= 110 for row in controls)
