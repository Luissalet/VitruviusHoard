"""Resolve captured project source through the normal page checker."""

import json
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from vitruvius_hoard import assay
from vitruvius_hoard.agent_tools import call_tool


def test_confined_checker_opens_the_captured_revision(services, monkeypatch):
    projects = services.app_projects
    old = call_tool(services, "app_project_create", {
        "name": "Render to check", "template": "static-page",
        "files": {"pages/index.html": "<h1>Captured heading</h1><button>Check me</button>"},
    })
    project_id = old["id"]
    capture = call_tool(services, "app_project_render", {"id": project_id, "widths": [390]})
    assert not (services.config.renders_dir / capture["id"] / "source.html").exists()
    current = projects.update(project_id, {"pages/index.html": "<h1>Current heading</h1>"}, old["revision"])
    live = projects.preview(project_id, current["revision"])
    opener = build_opener(ProxyHandler({}))

    def page(url):
        with opener.open(url, timeout=5) as response:
            return response.read().decode("utf-8")

    def browser_check(cmd, timeout):
        assert 0 < timeout <= assay.DEFAULT_TIMEOUT_S
        internal_url = cmd[cmd.index("--url") + 1]
        assert internal_url != live["url"]
        assert "Captured heading" in page(internal_url)
        assert "Current heading" in page(live["url"])
        checked = {"id": "button", "what": "Check me is present", "outcome": "passed"}
        return 0, json.dumps({"works": True, "cases": [checked]}), ""

    def confined_page_check(render_id):
        # The check sees only a render identifier, as it does for a confined agent.
        return call_tool(services, "page_check", {"render_id": render_id})

    services.assay_runner = browser_check
    result = confined_page_check(capture["id"])
    assert result["works"] and result["passed"] == 1 and result["cases_sample"][0]["id"] == "button"
    assert projects.status(project_id) == live

    blocked = {"id": "save", "what": "Save the draft"}
    unchecked = {"id": "refresh", "what": "Reload the draft"}
    detail = "The preview blocked POST /drafts"

    def time_out(cmd, *, timeout, cwd, output):
        assert "Captured heading" in page(cmd[cmd.index("--url") + 1])
        Path(cmd[cmd.index("--progress") + 1]).write_text(json.dumps({
            "planned": 2, "plan": [blocked, unchecked],
            "stopped_at": {"stage": "case", "case_id": "refresh"},
            "cases": [{**blocked, "outcome": "blocked", "detail": detail}],
        }), encoding="utf-8")
        return 124, "", ""

    services.assay_runner = None
    monkeypatch.setattr(assay, "available", lambda: True)
    monkeypatch.setattr(assay, "_run_worker", time_out)
    partial = confined_page_check(capture["id"])
    assert partial["timed_out"] and not partial["works"]
    assert partial["blocked"] == 1 and partial["blocked_cases"] == [{**blocked, "detail": detail}]
    assert partial["unchecked"] == 1 and partial["unchecked_cases"] == [unchecked]
    assert partial["stopped_at"]["case_id"] == "refresh"
    assert projects.status(project_id) == live


def test_page_check_reports_missing_capture_revision_and_preserves_plain_url_behavior(client):
    services = client.svc
    project = call_tool(services, "app_project_create", {"name": "Unavailable capture", "template": "static-page"})
    capture = call_tool(services, "app_project_render", {"id": project["id"], "widths": [390]})
    services.app_projects.stop(project["id"])
    snapshot = services.app_projects.root / project["id"] / "revisions" / project["revision"] / "snapshot.json"
    snapshot.unlink()
    response = client.post("/api/page-check", json={"render_id": capture["id"]})
    assert response.status_code == 404
    assert response.json()["error"] == (
        f"Render '{capture['id']}' refers to unavailable project '{project['id']}' revision '{project['revision']}'."
    )

    ordinary = services.render(url="https://example.com", widths=[390], _browser=services.browser)
    response = client.post("/api/page-check", json={"render_id": ordinary["id"]})
    assert response.status_code == 404
    assert response.json()["error"] == f"Render '{ordinary['id']}' has no saved source (URL renders keep none)."
