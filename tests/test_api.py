"""REST routes: one smoke test per route, plus the /api/agent/call auth check."""

import json


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "vitruvius-hoard"
    assert "hoard_link" in body


def test_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    assert "counts" in r.json()


def test_library_search_requires_query(client):
    assert client.get("/api/library/search").status_code == 400
    r = client.get("/api/library/search", params={"query": "contrast"})
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_library_brief(client):
    r = client.post("/api/library/brief", json={"subject": "a fintech app"})
    assert r.status_code == 200
    assert "palette" in r.json()


def test_library_rules(client):
    r = client.get("/api/library/rules")
    assert r.status_code == 200
    assert "rules" in r.json()


def test_catalog_routes(client):
    for path in ("styles", "palettes", "fonts"):
        r = client.get(f"/api/catalog/{path}")
        assert r.status_code == 200
        assert path in r.json()


def test_sources_get_and_post(client):
    r = client.get("/api/sources")
    assert r.status_code == 200
    before = len(r.json()["sources"])
    r2 = client.post("/api/sources", json={"url": "https://example.com/my-repo.git"})
    assert r2.status_code == 201
    r3 = client.get("/api/sources")
    assert len(r3.json()["sources"]) == before + 1


def test_sources_ingest_route(client):
    client.post("/api/sources", json={"id": "s1", "url": "/no/such/path", "kind": "local"})
    r = client.post("/api/sources/s1/ingest")
    assert r.status_code == 200


def test_sources_ingest_unknown_404(client):
    r = client.post("/api/sources/nope/ingest")
    assert r.status_code == 404


def test_renders_list_create_get_files(client):
    r = client.post("/api/renders", json={"html": "<html lang='en'><body>hi</body></html>"})
    assert r.status_code == 201
    render_id = r.json()["id"]
    r2 = client.get("/api/renders")
    assert r2.status_code == 200
    r3 = client.get(f"/api/renders/{render_id}")
    assert r3.status_code == 200
    name = r3.json()["files"][0]["path"].rsplit("/", 1)[-1]
    r4 = client.get(f"/api/renders/{render_id}/files/{name}")
    assert r4.status_code == 200


def test_renders_create_requires_html_or_url(client):
    r = client.post("/api/renders", json={})
    assert r.status_code == 400


def test_renders_get_unknown_404(client):
    assert client.get("/api/renders/nope").status_code == 404


def test_renders_files_traversal_blocked(client):
    r = client.post("/api/renders", json={"html": "<html></html>"})
    render_id = r.json()["id"]
    r2 = client.get(f"/api/renders/{render_id}/files/..%2F..%2Fetc%2Fpasswd")
    assert r2.status_code in (403, 404)


def test_renders_critique_route(client):
    r = client.post("/api/renders", json={"html": "<html></html>"})
    render_id = r.json()["id"]
    r2 = client.post(f"/api/renders/{render_id}/critique", json={"use_vision": True})
    assert r2.status_code == 200
    assert "score" in r2.json()


def test_lint_route(client):
    r = client.post("/api/lint", json={"html": "<html></html>"})
    assert r.status_code == 200
    assert "findings" in r.json()


def test_lint_route_requires_input(client):
    assert client.post("/api/lint", json={}).status_code == 400


def test_renders_compare_route(client):
    a = client.post("/api/renders", json={"html": "<html>a</html>", "widths": [1024]}).json()
    b = client.post("/api/renders", json={"html": "<html>b</html>", "widths": [1024]}).json()
    r = client.post("/api/renders/compare", json={"render_a": a["id"], "render_b": b["id"], "width": 1024})
    assert r.status_code == 200


def test_tokens_get_post_export_preview_playground_delete(client):
    r = client.post("/api/tokens", json={"name": "Demo", "base_color": "#3355ff"})
    assert r.status_code == 201
    tokens_id = r.json()["id"]
    assert client.get("/api/tokens").status_code == 200
    assert client.get(f"/api/tokens/{tokens_id}").status_code == 200
    assert client.get(f"/api/tokens/{tokens_id}/export", params={"format": "css"}).status_code == 200
    assert client.get(f"/api/tokens/{tokens_id}/playground").status_code == 200
    assert client.post(f"/api/tokens/{tokens_id}/preview", json={"dark": True}).status_code == 200
    assert client.delete(f"/api/tokens/{tokens_id}").status_code == 200
    assert client.get(f"/api/tokens/{tokens_id}").status_code == 404


def test_references_post_get_list_files_delete(client):
    r = client.post("/api/references", json={"html": "<html><title>Demo</title></html>", "video": False, "analyze": False})
    assert r.status_code == 201
    ref_id = r.json()["id"]
    assert client.get("/api/references").status_code == 200
    assert client.get(f"/api/references/{ref_id}").status_code == 200
    name = list(r.json()["files"].values())[0].rsplit("/", 1)[-1]
    key = list(r.json()["files"].keys())[0]
    path = r.json()["files"][key]
    rel = path.split(ref_id + "/", 1)[-1]
    r2 = client.get(f"/api/references/{ref_id}/files/{rel}")
    assert r2.status_code == 200
    assert client.delete(f"/api/references/{ref_id}").status_code == 200
    assert client.get(f"/api/references/{ref_id}").status_code == 404


def test_references_post_requires_input(client):
    assert client.post("/api/references", json={}).status_code == 400


def test_settings_get_and_put(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    r2 = client.put("/api/settings", json={"language": "es", "vision_enabled": False})
    assert r2.status_code == 200
    assert r2.json()["language"] == "es"


def test_agent_tools_route(client):
    r = client.get("/api/agent/tools")
    assert r.status_code == 200
    body = r.json()
    assert len(body["tools"]) == 25
    assert body["instructions"]


def test_agent_call_requires_auth(client):
    r = client.post("/api/agent/call", json={"name": "vitruvius_status", "arguments": {}})
    assert r.status_code == 401


def test_agent_call_with_valid_token(client):
    token = client.svc.token
    r = client.post("/api/agent/call", json={"name": "vitruvius_status", "arguments": {}},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["service"] == "vitruvius-hoard"


def test_agent_call_unknown_tool_404(client):
    token = client.svc.token
    r = client.post("/api/agent/call", json={"name": "nope"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_agent_call_bad_token_rejected(client):
    r = client.post("/api/agent/call", json={"name": "vitruvius_status"}, headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_agent_call_validation_error(client):
    token = client.svc.token
    r = client.post("/api/agent/call", json={"name": "design_search", "arguments": {}},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400


def test_manifest_and_sw_routes_exist(client):
    assert client.get("/manifest.webmanifest").status_code == 200
    assert client.get("/sw.js").status_code == 200


def test_spa_catch_all_serves_index(client):
    r = client.get("/some/unknown/route")
    assert r.status_code == 200
    assert "Vitruvius" in r.text


def test_spa_unknown_api_returns_404_json(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
