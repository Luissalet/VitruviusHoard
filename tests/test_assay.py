"""page_assay: the assay CLI wrapper, with the subprocess faked."""
import json

import pytest

from vitruvius_hoard import assay


RUN = {
    "planned": 3, "passed": 2, "failed": 1, "works": False,
    "surface": [{"kind": "button", "selector": "#inc", "label": "+1", "enabled": True}],
    "cases": [
        {"id": "C001", "what": "open the page", "outcome": "passed", "detail": "", "measured": "", "acts": []},
        {"id": "C002", "what": "press +1", "outcome": "passed", "detail": "", "measured": "changed", "acts": [{"click": "#inc"}]},
        {"id": "F001", "what": "nothing shows undefined", "outcome": "failed", "detail": "showing `undefined`", "measured": "", "acts": []},
    ],
}


def fake_runner(payload=RUN, code=1, err=""):
    calls = []

    def runner(cmd, timeout_s):
        calls.append((cmd, timeout_s))
        return code, json.dumps(payload) if payload is not None else "", err
    runner.calls = calls
    return runner


def test_reduce_run_keeps_failing_cases_and_surface():
    r = assay.reduce_run(RUN)
    assert r["works"] is False and r["failed"] == 1 and r["passed"] == 2
    assert r["failing"][0]["id"] == "F001" and "undefined" in r["failing"][0]["detail"]
    assert r["surface"][0]["label"] == "+1"
    assert len(r["cases_sample"]) == 3


def test_run_writes_html_and_calls_cli(tmp_path):
    runner = fake_runner()
    r = assay.run(tmp_path, html="<html><body><button>Go</button></body></html>", runner=runner)
    assert r["failed"] == 1 and r["id"] and r["exit_code"] == 1
    cmd, timeout = runner.calls[0]
    assert cmd[-1] == "--json" and "-e" in cmd and "index.html" in cmd
    folder = tmp_path / "assay" / r["id"]
    assert (folder / "index.html").read_text(encoding="utf-8").startswith("<html>")
    assert timeout == assay.DEFAULT_TIMEOUT_S


def test_run_accepts_a_local_page_and_a_folder(tmp_path):
    page = tmp_path / "site" / "app.html"
    page.parent.mkdir()
    page.write_text("<html></html>", encoding="utf-8")
    runner = fake_runner()
    r = assay.run(tmp_path, path=str(page), runner=runner)
    assert r["entry"] == "app.html" and r["folder"] == str(page.parent)
    r = assay.run(tmp_path, path=str(page.parent), runner=runner)
    assert r["entry"] == "index.html"
    with pytest.raises(ValueError):
        assay.run(tmp_path, path=str(tmp_path / "missing.html"), runner=runner)


def test_run_reports_non_json_and_non_page_outputs(tmp_path):
    r = assay.run(tmp_path, html="<p>x</p>", runner=fake_runner(payload=None, code=2, err="boom\nnot a page"))
    assert r["error"] == "assay gave no JSON" and "not a page" in r["hint"]
    r = assay.run(tmp_path, html="<p>x</p>", runner=fake_runner(payload={"nope": 1}, code=2))
    assert r["error"] == "assay could not check this page"


def test_run_without_assay_installed_says_how_to_install(tmp_path, monkeypatch):
    monkeypatch.setattr(assay, "available", lambda: False)
    r = assay.run(tmp_path, html="<p>x</p>")
    assert r["error"] == "assay is not installed" and "assay-ui" in r["hint"]


def test_page_assay_tool_and_route(client):
    client.svc.assay_runner = fake_runner()
    r = client.post("/api/assay", json={"html": "<html><body>hi</body></html>"})
    assert r.status_code == 200 and r.json()["failed"] == 1
    r = client.post("/api/assay", json={})
    assert r.status_code == 400
    r = client.post("/api/assay", json={"render_id": "nope"})
    assert r.status_code == 404


def test_page_assay_reuses_a_render_source(client):
    client.svc.assay_runner = fake_runner()
    render = client.svc.render(html="<html><body><button>Go</button></body></html>", widths=[390])
    r = client.post("/api/assay", json={"render_id": render["id"]})
    assert r.status_code == 200 and r.json()["entry"] == "source.html"
