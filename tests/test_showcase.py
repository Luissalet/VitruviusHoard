"""Library discovery, shipped exports and the actual Rehacer dispatch contract."""
import asyncio
import hashlib
import io
import json
import re
import zipfile
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from vitruvius_hoard.showcase import library
from vitruvius_hoard.showcase.tools import execute


def test_reference_recipe_pairs_are_complete_and_searchable():
    rows = library.search()["recipes"]
    assert {row["id"] for row in rows} == {"book", "glitch", "gallery", "city", "rock"}
    for row in rows:
        recipe = library.read(row["id"])
        assert set(recipe["decisions"]) == {"light", "rhythm", "typography", "interaction", "why"}
        assert len(recipe["checkpoints"]) >= 3
        assert recipe["sources"][0]["frame_seconds"] > 0
        assert recipe["skill"].startswith("---\nname: showcase-" + row["id"])
        assert "?" not in recipe["title"]
        assert "__ID__" not in library.page(row["id"])
    assert library.search("algo cinematográfico")["recipes"][0]["id"] == "rock"
    assert library.search("portrait")["recipes"][0]["id"] == "glitch"
    assert library.search("GALERÍA")["recipes"][0]["id"] == "gallery"
    assert library.search("nonexistentxyz")["recipes"] == []


@pytest.mark.parametrize("recipe_id", ["book", "glitch", "gallery", "city", "rock"])
def test_export_has_every_local_resource_and_license(recipe_id):
    with zipfile.ZipFile(io.BytesIO(library.archive(recipe_id))) as archive:
        names = set(archive.namelist())
        assert f"{recipe_id}/index.html" in names
        assert {f"{id}/index.html" for id in ("book", "glitch", "gallery", "city", "rock")} <= names
        assert 'href="../index.html"' in archive.read(f"{recipe_id}/index.html").decode()
        assert {"scene.js", "book.js", "reference.css", "recipe.json", "SKILL.md", "START.txt"} <= names
        assert {"assets/three.module.js", "assets/LICENSE-three.txt", "assets/portrait.jpg",
                "assets/InstrumentSerif.ttf", "assets/OFL-InstrumentSerif.txt", "assets/Barlow.ttf", "assets/OFL-Barlow.txt"} <= names
        assert not any("at-" in name for name in names)
        provenance = json.loads(archive.read("assets/provenance.json"))
        for asset in provenance["assets"]:
            assert hashlib.sha256(archive.read("assets/" + asset["file"])).hexdigest() == asset["sha256"]
        assert "http.server" in archive.read("START.txt").decode()


@pytest.mark.parametrize("path", ["../library.py", "assets/../../library.py", "assets/../library.py", "missing/index.html", "recipes.json"])
def test_resources_are_shipped_assets_only(path):
    with pytest.raises(LookupError):
        library.resource(path)


def test_source_returns_the_real_entry_and_shared_code():
    source = library.source("gallery")
    assert source["text"] == library.page("gallery")
    assert hashlib.sha256(source["text"].encode()).hexdigest() == source["sha256"]
    assert "Raycaster" in library.source("gallery", "scene.js")["text"]
    with pytest.raises(ValueError):
        library.source("gallery", "assets/portrait.jpg")


def test_cold_host_routes_and_tools_need_no_design(tmp_path, monkeypatch):
    monkeypatch.setenv("VITRUVIUS_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("HOARD_EVENTS", "0")
    from vitruvius_hoard.software.host import create_app
    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1:5191") as client:
        token = (tmp_path / "mcp-token").read_text().strip()
        headers = {"Authorization": "Bearer " + token}
        catalogue = client.get("/api/agent/tools").json()["tools"]
        assert {row["name"] for row in catalogue if row["name"].startswith("showcase_")} == {
            "showcase_recipes", "showcase_recipe", "showcase_source", "showcase_remake"}
        assert client.get("/showcase/").status_code == 200
        for recipe in library.search()["recipes"]:
            assert client.get(recipe["reference_url"]).status_code == 200
            assert client.get(recipe["download_url"]).headers["content-type"] == "application/zip"
        assert client.get("/api/showcase/missing").status_code == 404
        result = client.post("/api/agent/call", headers=headers, json={"name": "showcase_recipe", "arguments": {"id": "rock"}})
        assert result.status_code == 200
        assert result.json()["remake_arguments"]["max_rounds"] == 1
        result = client.post("/api/agent/call", headers=headers, json={"name": "showcase_remake", "arguments": {"id": "rock"}})
        assert result.status_code == 400
        assert "Enable module explicitly" in result.json()["error"]
        assert all(row["state"] == "off" for row in client.get("/api/health").json()["modules"])
        assert not (tmp_path / "design").exists()


def test_remake_dispatch_keeps_recipe_and_existing_runner_contract():
    class Runtime:
        call = AsyncMock(return_value={"id": "retained-run", "status": "queued"})
    runtime = Runtime()
    result = asyncio.run(execute(runtime, "showcase_remake", {"id": "city"}))
    name, arguments = runtime.call.call_args.args
    assert name == "remake_start"
    assert arguments["url"] == library.ORIGIN + "/city/index.html?still=1"
    assert arguments["note"] == library.read("city")["prompt"]
    assert arguments["widths"] == [1440, 390]
    assert arguments["mode"] == "copy" and arguments["max_rounds"] == 1
    assert result["recipe_id"] == "city" and result["remake"]["id"] == "retained-run"
    asyncio.run(execute(runtime, "showcase_remake", {"id": "city", "mode": "rebuild"}))
    assert runtime.call.call_args.args[1]["max_rounds"] == 6


def test_virtual_origin_serves_exact_library_only():
    class Context:
        def route(self, pattern, handler):
            self.pattern, self.handler = pattern, handler
    class Route:
        def __init__(self, url):
            self.request = type("Request", (), {"url": url})()
        def fulfill(self, **kwargs):
            self.response = kwargs
    context = Context()
    library.mount(context, "https://other.invalid/book/index.html")
    assert not hasattr(context, "handler")
    library.mount(context, library.ORIGIN + "/book/index.html")
    route = Route(library.ORIGIN + "/book/index.html?still=1")
    context.handler(route)
    assert b'data-recipe="book"' in route.response["body"]
    route = Route(library.ORIGIN + "/library.py")
    context.handler(route)
    assert route.response["status"] == 404
