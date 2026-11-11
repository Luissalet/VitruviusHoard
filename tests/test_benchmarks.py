from contextlib import contextmanager
import json
import threading
import time
from pathlib import Path
import pytest
from conftest import make_services, _fake_parity_page
from vitruvius_hoard.benchmarks import corpus, references, runtime
from vitruvius_hoard.benchmarks.runner import Benchmarks


@pytest.fixture
def svc(tmp_path, monkeypatch):
    s = make_services(tmp_path)
    s.browser.parity_hook = lambda tag, w, load, html, url: (
        _fake_parity_page(w, "reference", 1, False) if tag == "candidate" else None
    )
    monkeypatch.setattr(
        references,
        "prepare",
        lambda *a: (tmp_path, {"sha256": "fixture", "files": 1, "bytes": 4}),
    )

    @contextmanager
    def running(*a):
        yield "https://example.com/"

    monkeypatch.setattr(references, "running", running)
    monkeypatch.setattr(runtime, "running", running)
    monkeypatch.setattr(runtime, "prepare", lambda *args: {"kind": "test"})
    yield s
    s.stop()


def finish(s, r):
    s.benchmarks.thread.join(15)
    assert not s.benchmarks.thread.is_alive()
    return s.benchmarks.get(r["id"])


def test_catalog_is_pinned_and_complete():
    m = corpus.catalog()
    assert len(m["cases"]) == 70
    assert sum(r["official_cases"] for r in m["cases"]) == 46916
    assert len(m["manifest_sha256"]) == 64
    assert len(corpus.implementation()) == 64
    assert len(set(r["id"] for r in m["cases"])) == 70


def test_normal_remake_retains_version_scores_and_evidence(svc):
    r = finish(svc, svc.benchmarks.start(version="baseline", cases=["medium"]))
    assert r["status"] == "done" and r["summary"]["complete"]
    assert r["summary"]["coverage_percent"] == 100
    row = r["cases"][0]
    assert row["status"] == "measured" and row["score"] == 100
    assert row["rounds"] and row["artifacts"]
    assert row["artifacts"][0]["sha256"]
    assert svc.remake.get(row["remake_id"])["label"] == "baseline / medium"
    assert r["official_reward"] is None
    assert r["metric"] == "vitruvius-stable-pixels/1"


@pytest.mark.parametrize(
    "kw",
    [
        {"version": " "},
        {"cases": ["missing"]},
        {"cases": ["medium", "medium"]},
        {"widths": [1]},
        {"max_rounds": 21},
        {"mode": "unknown"},
        {"pass_score": 101},
    ],
)
def test_inputs_fail_before_start(svc, kw):
    with pytest.raises(ValueError):
        svc.benchmarks.start(**({"version": "v1", "cases": ["medium"]} | kw))
    assert svc.benchmarks.thread is None


def test_failed_case_does_not_inflate_mean_or_coverage(svc, monkeypatch):
    original = references.prepare

    def prepare(base, catalog, case, cancel):
        if case == "33":
            raise OSError("download unavailable")
        return original(base, catalog, case, cancel)

    monkeypatch.setattr(references, "prepare", prepare)
    r = finish(svc, svc.benchmarks.start(version="v1", cases=["medium", "33"]))
    assert r["status"] == "done"
    assert r["summary"] == {
        "selected": 2,
        "measured": 1,
        "failed": 1,
        "passed": 1,
        "coverage_percent": 50,
        "mean_score": 100,
        "complete": False,
    }
    assert r["cases"][1]["error"] == "download unavailable"


def test_comparison_requires_same_settings_and_reference(svc):
    a = finish(svc, svc.benchmarks.start(version="a", cases=["medium"]))
    b = finish(svc, svc.benchmarks.start(version="b", cases=["medium"]))
    delta = svc.benchmarks.compare(a["id"], b["id"])
    assert (
        delta["comparable"]
        and delta["mean_delta"] == 0
        and delta["paired_measured"] == 1
    )
    c = finish(svc, svc.benchmarks.start(version="c", cases=["medium"], widths=[390]))
    delta = svc.benchmarks.compare(a["id"], c["id"])
    assert (
        not delta["comparable"] and delta["mean_delta"] is None and not delta["cases"]
    )
    b["cases"][0]["reference"]["sha256"] = "changed"
    svc.benchmarks._save(b)
    assert not svc.benchmarks.compare(a["id"], b["id"])["comparable"]


def test_restart_resume_and_implementation_change(svc, monkeypatch):
    monkeypatch.setattr(svc.benchmarks, "_launch", lambda _: None)
    r = svc.benchmarks.start(version="v1", cases=["medium"])
    owner = Benchmarks(svc)
    assert owner.get(r["id"])["status"] == "interrupted"
    monkeypatch.setattr(owner, "_launch", lambda _: None)
    assert owner.resume(r["id"])["status"] == "queued"
    monkeypatch.setattr(corpus, "implementation", lambda: "changed")
    with pytest.raises(ValueError, match="Implementation changed"):
        owner.resume(r["id"])
    assert owner.get(r["id"])["implementation_sha256"] == r["implementation_sha256"]


def test_stop_joins_reference_and_preserves_pending(svc, monkeypatch):
    entered = threading.Event()
    closed = threading.Event()

    @contextmanager
    def running(source, state, log, cancel):
        entered.set()
        try:
            cancel.wait(10)
            raise references.Cancelled()
            yield
        finally:
            closed.set()

    monkeypatch.setattr(references, "running", running)
    monkeypatch.setattr(runtime, "running", running)
    r = svc.benchmarks.start(version="v1", cases=["medium", "33"])
    assert entered.wait(5)
    with pytest.raises(ValueError, match="already running"):
        svc.benchmarks.start(version="concurrent")
    svc.benchmarks.stop(r["id"])
    r = finish(svc, r)
    assert closed.is_set() and r["status"] == "stopped"
    assert [x["status"] for x in r["cases"]] == ["interrupted", "pending"]
    assert r["summary"]["mean_score"] is None


def test_hash_checks_and_reference_entry(svc, tmp_path):
    import hashlib

    p = tmp_path / "a"
    p.write_bytes(b"content")
    row = {"oid": hashlib.sha1(b"blob 7\0content").hexdigest()}
    assert references.file_hash(p, row)
    p.write_bytes(b"changed")
    assert not references.file_hash(p, row)
    (tmp_path / "harbor_entry.py").write_text("print(1)")
    assert references.command(tmp_path)[-1] == str(tmp_path / "harbor_entry.py")


def test_tools_and_rest_share_manager(svc):
    from fastapi.testclient import TestClient
    from vitruvius_hoard.main import create_app
    from vitruvius_hoard.agent_tools import call_tool

    app = create_app(services=svc)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert (
            c.get("/api/benchmarks/catalog").json()["manifest_sha256"]
            == corpus.catalog()["manifest_sha256"]
        )
        response = c.post(
            "/api/benchmarks/runs", json={"version": "rest", "cases": ["medium"]}
        )
        assert response.status_code == 201
        r = finish(svc, response.json())
        result = call_tool(svc, "benchmark_get", {"id": r["id"]})
        assert result["version"] == "rest"
        out = c.get("/api/benchmarks/runs/" + r["id"] + "/export")
        assert out.json()["cases"] == r["cases"]
        assert c.get("/api/benchmarks/runs/../../secret").status_code != 200
