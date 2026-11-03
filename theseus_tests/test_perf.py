import json
from pathlib import Path
import sys
import time

from fastapi.testclient import TestClient
import pytest

from theseus import perf
from theseus.api import TOOLS, create_app

SLOW_DB = '''import sqlite3

def load():
    conn = sqlite3.connect(":memory:")
    conn.execute("create table t(id integer, k integer)")
    conn.executemany("insert into t values (?, ?)", [(i, i % 40) for i in range(5000)])
    return conn


def count_pairs(conn):
    return conn.execute("select count(*) from t a join t b on a.k + 0 = b.k + 0 where a.id < 600").fetchone()[0]


print(count_pairs(load()))
'''
FIXED_DB = SLOW_DB.replace("a.k + 0 = b.k + 0", "a.k = b.k", 1)
WRONG_DB = '''import sqlite3

def load():
    conn = sqlite3.connect(":memory:")
    conn.execute("create table t(id integer, k integer)")
    conn.executemany("insert into t values (?, ?)", [(i, i % 40) for i in range(5000)])
    return conn


def count_pairs(conn):
    return conn.execute("select count(*) from t where id < 600").fetchone()[0]


print(count_pairs(load()))
'''
JSON_SLOW = '''import json


def build():
    return {"rows": [{"id": i, "name": "n%d" % i, "tags": ["a", "b", i]} for i in range(2500)]}


def export(data):
    text = ""
    for _ in range(6):
        text = json.dumps(data, indent=2)
    return text


print(len(export(build())))
'''
MODEL = '''def predict(n):
    total = 0
    for i in range(n):
        total += (i * i) % 7
    return total


def prepare():
    return [str(i) for i in range(2000)]


prepare()
print(predict(400000))
'''
SERVER = '''import json, os, sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

conn = sqlite3.connect(":memory:", check_same_thread=False)
conn.execute("create table t(id integer, k integer)")
conn.executemany("insert into t values (?, ?)", [(i, i % 40) for i in range(5000)])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        n = conn.execute("select count(*) from t a join t b on a.k + 0 = b.k + 0 where a.id < 300").fetchone()[0]
        body = json.dumps({"n": n}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
'''


def wait(store, job_id, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        job = store.job(job_id)
        if job["state"] not in {"queued", "running"}:
            return job
        time.sleep(.05)
    raise AssertionError("Job did not terminate")


@pytest.fixture
def workspace(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app, base_url="http://127.0.0.1:5217") as client:
        client.get("/")
        project = app.state.store.create_project("Perf")
        yield client, app, project["id"], tmp_path


def script(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return {"argv": [sys.executable, str(path)], "timeout_seconds": 60}


def start(workspace, route, body):
    client, app, pid, _ = workspace
    started = client.post(f"/api/projects/{pid}/perf/{route}", json=body)
    assert started.status_code == 200, started.text
    done = wait(app.state.store, started.json()["id"])
    assert done["state"] == "finished", done["result"].get("error")
    return done["result"]


def test_statistics_are_exact_and_sound():
    low = perf.mann_whitney([1, 2, 3, 4], [5, 6, 7, 8])
    assert low["method"].startswith("exact") and abs(low["p_value"] - 2 / 70) < 1e-9
    assert perf.mann_whitney([1, 2, 3], [1, 2, 3])["p_value"] == 1.0
    same = perf.compare_samples([1.0, 1.1, 0.9, 1.05], [1.0, 1.05, 0.95, 1.1])
    assert not same["significant"]
    fast = perf.compare_samples([1.0, 1.1, 0.9, 1.05, 1.02], [0.5, 0.55, 0.45, 0.52, 0.51])
    assert fast["significant"] and fast["direction"] == "faster" and fast["ci95"][1] < 0
    assert perf.percentile([1, 2, 3, 4, 5], .9) == pytest.approx(4.6)


def test_diagnosis_names_the_database_first(workspace):
    result = start(workspace, "profile", {"command": script(workspace[3], "slow_db.py", SLOW_DB), "runs": 4, "warmup": 1})
    profile = result["profile"]
    assert profile["primary_category"] == "database" and profile["ranked"][0] == "database"
    share = profile["categories"]["database"]["share"]
    assert share["median"] > .6 and share["p90"] >= share["median"] and share["n"] == 4
    top = profile["hotspots"][0]
    assert top["category"] == "database" and "execute" in top["function"]
    assert top["call_lines"][0] == "slow_db.py:11"
    assert result["diagnosis"].startswith("Most time goes to database")
    assert result["wall_seconds"]["n"] == 4 and result["determinism"]["distinct_outputs"] == 1
    assert "not wall-clock" in result["scope"]


def test_serialization_and_model_attribution(workspace):
    tmp = workspace[3]
    ser = start(workspace, "profile", {"command": script(tmp, "export.py", JSON_SLOW), "runs": 3, "warmup": 0})
    assert ser["profile"]["primary_category"] == "serialization"
    assert ser["profile"]["hotspots"][0]["location"].startswith("<stdlib>/json/encoder.py:")
    model = start(workspace, "profile", {"command": script(tmp, "model.py", MODEL), "runs": 3, "warmup": 0,
                                        "model_functions": ["predict", "*.infer"]})
    assert model["profile"]["primary_category"] == "model"
    assert model["profile"]["hotspots"][0]["location"] == "model.py:1"
    plain = start(workspace, "profile", {"command": script(tmp, "model2.py", MODEL), "runs": 3, "warmup": 0})
    assert plain["profile"]["primary_category"] == "cpu_user"


def test_fixed_version_is_significantly_faster_with_identical_output(workspace):
    tmp = workspace[3]
    result = start(workspace, "compare", {"before": script(tmp, "slow.py", SLOW_DB), "after": script(tmp, "fixed.py", FIXED_DB),
                                          "runs": 5, "warmup": 1})
    assert result["verdict"]["status"] == "faster" and result["verdict"]["outputs_identical"] is True
    total = result["total"]
    assert total["significant"] and total["change"] < -.3 and total["p_value"] < .05 and total["ci95"][1] < 0
    assert total["speedup"] > 1.4
    assert result["categories"]["database"]["significant"] and result["categories"]["database"]["change"] < -.5
    assert result["equivalence"]["identical"] and "equivalence runner" in result["equivalence"]["method"]
    assert result["before_report"]["profile"]["primary_category"] == "database"


def test_faster_but_wrong_is_reported_as_failed(workspace):
    tmp = workspace[3]
    result = start(workspace, "compare", {"before": script(tmp, "slow.py", SLOW_DB), "after": script(tmp, "wrong.py", WRONG_DB),
                                          "runs": 5, "warmup": 1})
    assert result["total"]["direction"] == "faster"
    verdict = result["verdict"]
    assert verdict["status"] == "failed" and verdict["outputs_identical"] is False
    assert "outputs differ" in verdict["reason"]
    first = result["equivalence"]["cases"][0]["first_disagreement"]
    assert first["channel"] == "stdout"


def test_compare_two_source_directories_with_placeholder(workspace):
    tmp = workspace[3]
    for name, source in (("v1", SLOW_DB), ("v2", FIXED_DB)):
        (tmp / name).mkdir()
        (tmp / name / "main.py").write_text(source, encoding="utf-8")
        (tmp / name / ".git").mkdir()
    spec = lambda name: {"argv": [sys.executable, "{src}/main.py"], "source_dir": str(tmp / name), "timeout_seconds": 60}
    result = start(workspace, "compare", {"before": spec("v1"), "after": spec("v2"), "runs": 4, "warmup": 0})
    assert result["verdict"]["outputs_identical"] is True and result["total"]["median_after"] < result["total"]["median_before"]
    assert result["before_report"]["profile"]["hotspots"][0]["location"] == "(C function)"
    assert result["before_report"]["profile"]["hotspots"][0]["call_lines"][0].startswith("main.py:")


def test_http_request_against_started_server(workspace):
    tmp = workspace[3]
    command = script(tmp, "server.py", SERVER)
    result = start(workspace, "profile", {"command": command, "runs": 4, "warmup": 1,
                                         "http": {"request": {"path": "/"}, "ready_timeout_seconds": 30}})
    assert result["profile"]["primary_category"] == "database"
    assert {"connect", "wait_first_byte", "download", "wall"} <= set(result["segments"])
    assert result["wall_seconds"]["n"] == 4 and result["determinism"]["distinct_outputs"] == 1
    assert "waiting_excluded" in result["profile"]


def test_requires_enough_runs_and_a_catalogue_entry(workspace):
    client, app, pid, tmp = workspace
    bad = client.post(f"/api/projects/{pid}/perf/profile", json={"command": script(tmp, "x.py", "print(1)"), "runs": 2})
    assert bad.status_code >= 400
    names = {t["name"] for t in TOOLS}
    assert {"theseus_perf_profile", "theseus_perf_compare"} <= names


def test_http_comparison_of_two_servers(workspace):
    tmp = workspace[3]
    fixed = SERVER.replace("a.k + 0 = b.k + 0", "a.k = b.k")
    result = start(workspace, "compare", {"before": script(tmp, "s1.py", SERVER), "after": script(tmp, "s2.py", fixed),
                                          "runs": 5, "warmup": 1, "http": {"request": {"path": "/"}}})
    assert result["verdict"]["status"] == "faster" and result["equivalence"]["identical"]
    assert result["equivalence"]["method"] == "http status and body hash"
    assert result["categories"]["database"]["significant"] and result["categories"]["database"]["change"] < -.5
