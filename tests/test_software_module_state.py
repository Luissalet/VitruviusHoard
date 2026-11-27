import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

from vitruvius_hoard.software.runtime import Module, NativeError, Runtime


@pytest.fixture
def module_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("VITRUVIUS_PROFILE_DIR", str(tmp_path))
    monkeypatch.setattr(Module, "create", lambda self: FastAPI())
    return tmp_path / "software-modules.json"


@asynccontextmanager
async def running_runtime():
    runtime = Runtime()
    await runtime.restore()
    try:
        yield runtime
    finally:
        await runtime.close()


def states(runtime):
    return {entry["module"]: entry for entry in runtime.status()["modules"]}


@pytest.mark.asyncio
async def test_explicit_state_and_undo_survive_runtime_restart(module_profile):
    async with running_runtime() as runtime:
        assert all(not row["enabled"] for row in states(runtime).values())
        assert not module_profile.exists()
        design, _, _ = await asyncio.gather(
            runtime.set_module("design", True, True),
            runtime.set_module("babel", True),
            runtime.set_module("theseus", True),
        )
        assert design["previous"] == {"enabled": False, "automatic": False}
        await runtime.set_module("theseus", False, True)

    async with running_runtime() as restarted:
        current = states(restarted)
        assert [(row["enabled"], row["automatic"]) for row in current.values()] == [
            (True, True), (True, False), (False, True)
        ]
        reverted = await restarted.set_module("design", **design["previous"])
        assert reverted["previous"] == {"enabled": True, "automatic": True}

    async with running_runtime() as restarted_again:
        assert states(restarted_again)["design"]["state"] == "off"


@pytest.mark.asyncio
@pytest.mark.parametrize("contents", [
    b"{broken", b"\xff", b"[]", b'{"version":0,"modules":{"design":{"enabled":true}}}',
    b'{"version":1,"modules":{"design":{"enabled":"true","automatic":false}}}',
])
async def test_unusable_saved_state_keeps_host_available(module_profile, contents):
    module_profile.write_bytes(contents)
    async with running_runtime() as runtime:
        assert all(row["state"] == "off" for row in states(runtime).values())
        assert module_profile.read_bytes() == contents
        await runtime.set_module("babel", True)
    assert json.loads(module_profile.read_text())["modules"]["babel"]["enabled"] is True


@pytest.mark.asyncio
async def test_failure_is_reported_and_other_modules_restore(module_profile, monkeypatch):
    module_profile.write_text(json.dumps({"version": 1, "modules": {
        "design": {"enabled": True, "automatic": False},
        "babel": {"enabled": True, "automatic": False},
        "theseus": {"enabled": True, "automatic": "invalid"},
    }}))
    create = Module.create

    def start(self):
        if self.name == "design":
            raise RuntimeError("Native design configuration unavailable")
        return create(self)

    monkeypatch.setattr(Module, "create", start)
    async with running_runtime() as runtime:
        current = states(runtime)
        assert current["design"]["state"] == "error"
        assert current["design"]["enabled"] is False
        assert current["design"]["error"] == "Native design configuration unavailable"
        assert current["babel"]["state"] == "on"
        assert current["theseus"]["state"] == "off"
        cleared = await runtime.set_module("design", False)
        assert cleared["state"] == "off"
        assert cleared["previous"] == {"enabled": True, "automatic": False}
        assert "error" not in cleared


@pytest.mark.asyncio
async def test_failed_save_leaves_running_state_intact(module_profile, monkeypatch):
    async with running_runtime() as runtime:
        await runtime.set_module("babel", True)
        saved = module_profile.read_bytes()

        def fail(*args, **kwargs):
            raise PermissionError("Profile is read-only")

        monkeypatch.setattr("vitruvius_hoard.software.runtime.write_json_atomic", fail)
        with pytest.raises(NativeError, match="Profile is read-only"):
            await runtime.set_module("babel", False)
        assert states(runtime)["babel"]["state"] == "on"
        assert module_profile.read_bytes() == saved


@pytest.mark.asyncio
async def test_host_controls_use_saved_module_settings(module_profile, monkeypatch):
    from vitruvius_hoard.software.host import create_app

    module_profile.write_text('{"version":1,"modules":{}}', encoding="utf-8")

    monkeypatch.setenv("VITRUVIUS_TOKEN_FILE", str(module_profile.with_name("mcp-token")))
    app = create_app()
    async with app.router.lifespan_context(app):
        changed = await app.state.execute("software_module_set", {"module": "design", "enabled": True})
        assert changed["previous"] == {"enabled": False, "automatic": False}

    restarted = create_app()
    async with restarted.router.lifespan_context(restarted):
        result = await restarted.state.execute("software_modules", {})
        design = next(module for module in result["modules"] if module["module"] == "design")
        assert design["state"] == "on"
