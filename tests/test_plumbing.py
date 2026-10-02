"""What the shared plumbing fixes in this app: a stable token, a second start that does not disturb the first, an agent
answer that is capped (except the payload tools), a no-cache single-page app, a transaction that cannot leak the lock and
settings that read both the old and the new storage format."""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from conftest import make_config, make_services

from vitruvius_hoard import agent_tools
from vitruvius_hoard.db import Database
from vitruvius_hoard.hoard_link.agentkit import Tool, ann

ROOT = Path(__file__).resolve().parent.parent


def test_token_survives_a_restart(tmp_path):
    first = make_services(tmp_path)
    token = first.token
    first.stop()
    second = make_services(tmp_path)
    try:
        assert second.token == token and (tmp_path / "data" / "mcp-token").read_text().strip() == token
    finally:
        second.stop()


def test_a_corrupt_token_file_is_replaced(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "mcp-token").write_text("x", encoding="utf-8")
    svc = make_services(tmp_path)
    try:
        assert len(svc.token) >= 32
    finally:
        svc.stop()


def test_an_old_64_hex_token_file_is_still_accepted(tmp_path):
    (tmp_path / "data").mkdir()
    old = "ab" * 32
    (tmp_path / "data" / "mcp-token").write_text(old, encoding="utf-8")
    svc = make_services(tmp_path)
    try:
        assert svc.token == old
    finally:
        svc.stop()


def test_health_keeps_its_fields_and_the_url_file_is_written(client):
    body = client.get("/api/health").json()
    assert body["service"] == "vitruvius-hoard" and body["version"]
    for key in ("dataDirConfigured", "browser", "ffmpeg", "git", "counts", "hoard_link"):
        assert key in body, key
    assert (client.svc.config.data_dir / "url").read_text().startswith("http://127.0.0.1:")


def test_a_second_start_reports_the_running_app_and_leaves_the_token_alone(tmp_path):
    from vitruvius_hoard.hoard_link.net import free_port

    port = free_port()
    env = {**os.environ, "VITRUVIUS_DATA_DIR": str(tmp_path / "data"), "VITRUVIUS_PORT": str(port), "VITRUVIUS_AUTOSTART": "0",
           "VITRUVIUS_EMBED": "none", "PYTHONUNBUFFERED": "1"}
    first = subprocess.Popen([sys.executable, "-m", "vitruvius_hoard"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        token_file = tmp_path / "data" / "mcp-token"
        before = token_file.read_text()
        second = subprocess.run([sys.executable, "-m", "vitruvius_hoard"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        assert second.returncode == 0 and "already running" in second.stdout
        assert token_file.read_text() == before
        auth = {"Authorization": f"Bearer {before.strip()}"}
        assert httpx.post(f"http://127.0.0.1:{port}/api/agent/call", json={"name": "sources_list"}, headers=auth).status_code == 200
    finally:
        first.terminate()
        try:
            first.wait(10)
        except subprocess.TimeoutExpired:
            first.kill()


def test_errors_keep_their_statuses_and_gain_a_code(client):
    auth = {"Authorization": f"Bearer {client.svc.token}"}
    missing = client.post("/api/agent/call", json={"name": "tokens_get", "arguments": {"id": "nope"}}, headers=auth)
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"
    bad = client.post("/api/agent/call", json={"name": "design_search", "arguments": {"query": "x", "limit": "many"}}, headers=auth)
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_arguments" and bad.json()["issues"]
    unknown = client.post("/api/agent/call", json={"name": "nope"}, headers=auth)
    assert unknown.status_code == 404 and unknown.json()["code"] == "unknown_tool"
    assert client.post("/api/agent/call", json={"name": "sources_list"}, headers={"Authorization": "bearer " + client.svc.token}).status_code == 200
    assert client.post("/api/agent/call", json={"name": "sources_list"}, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_listings_are_capped_but_the_payload_tools_are_not(client, monkeypatch):
    from pydantic import BaseModel

    class NoArgs(BaseModel):
        pass

    big = "x" * 60_000
    monkeypatch.setitem(agent_tools.TOOLS_BY_NAME, "design_rules", Tool("design_rules", "d", NoArgs, ann(True), lambda s, a: {"rules": [{"t": big}, {"t": big}, {"t": big}]}))
    monkeypatch.setitem(agent_tools.TOOLS_BY_NAME, "tokens_get", Tool("tokens_get", "d", NoArgs, ann(True), lambda s, a: {"content": big}))
    auth = {"Authorization": f"Bearer {client.svc.token}"}
    listing = client.post("/api/agent/call", json={"name": "design_rules"}, headers=auth).json()
    assert "truncated" in listing and len(listing["rules"]) < 3
    payload = client.post("/api/agent/call", json={"name": "tokens_get"}, headers=auth).json()
    assert payload["content"] == big and "truncated" not in payload


def test_render_images_are_never_cut(client, monkeypatch):
    from pydantic import BaseModel

    class Args(BaseModel):
        include_images: bool = False

    big = "y" * 60_000
    monkeypatch.setitem(agent_tools.TOOLS_BY_NAME, "render_preview", Tool("render_preview", "d", Args, ann(False), lambda s, a: {"files": [{"bytes": big}, {"bytes": big}]}))
    auth = {"Authorization": f"Bearer {client.svc.token}"}
    with_images = client.post("/api/agent/call", json={"name": "render_preview", "arguments": {"include_images": True}}, headers=auth).json()
    assert [f["bytes"] for f in with_images["files"]] == [big, big]
    without = client.post("/api/agent/call", json={"name": "render_preview"}, headers=auth).json()
    assert "truncated" in without


def test_the_built_client_is_never_served_stale(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import vitruvius_hoard.main as main

    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><script src='/assets/app-abcdef12.js'></script>", encoding="utf-8")
    (static / "assets" / "app-abcdef12.js").write_text("export {}", encoding="utf-8")
    monkeypatch.setattr(main, "STATIC_DIR", static)
    with TestClient(main.create_app(make_config(tmp_path)), base_url="http://127.0.0.1") as client:
        index = client.get("/")
        assert index.status_code == 200 and index.headers["cache-control"] == "no-cache"
        asset = client.get("/assets/app-abcdef12.js")
        assert "immutable" in asset.headers["cache-control"] and asset.headers["content-type"].startswith("text/javascript")
        assert client.get("/assets/old-deadbeef.js").status_code == 404          # not an HTML page served as a script
        assert client.get("/api/nothing").json()["code"] == "not_found"
        assert client.get("/references/42").status_code == 200                       # client-side route: index.html


def test_a_failed_begin_does_not_leave_the_lock_held(tmp_path):
    """The old transaction took the lock and then ran BEGIN: one `database is locked` hung every other thread."""
    import sqlite3

    db = Database(tmp_path / "x.db", busy_timeout_ms=50)
    other = sqlite3.connect(str(tmp_path / "x.db"), isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    with pytest.raises(sqlite3.OperationalError):
        with db.transaction():
            pass
    other.execute("ROLLBACK")
    other.close()
    done = []
    worker = threading.Thread(target=lambda: done.append(db.query("SELECT 1")))
    worker.start()
    worker.join(5)
    assert done and not worker.is_alive()
    db.close()


def test_settings_round_trip_and_read_the_values_the_old_code_stored(tmp_path):
    svc = make_services(tmp_path)
    try:
        assert svc.get_settings()["widths"] == [390, 1024, 1440] and svc.get_settings()["vision_enabled"] is True
        # what the previous version wrote: "1"/"0" flags, a JSON text for the widths, a bare word for the language
        svc.db.execute("INSERT INTO settings(key, value) VALUES ('vision_enabled', '0'), ('video_enabled', '1'), ('widths', '[320, 800]'), ('language', 'es')")
        got = svc.get_settings()
        assert got["vision_enabled"] is False and got["video_enabled"] is True and got["widths"] == [320, 800] and got["language"] == "es"
        out = svc.update_settings({"vision_enabled": True, "widths": [375, 1280], "video_enabled": False, "language": "en"})
        assert out["vision_enabled"] is True and out["widths"] == [375, 1280] and out["video_enabled"] is False and out["language"] == "en"
    finally:
        svc.stop()


def test_backend_json_is_written_atomically_and_readable(tmp_path):
    svc = make_services(tmp_path)
    try:
        svc.update_settings({"backend": {"vision": {"model": "x"}}})
        assert svc.get_settings()["backend"] == {"vision": {"model": "x"}}
        assert not list(svc.config.data_dir.glob("*.tmp"))
    finally:
        svc.stop()
