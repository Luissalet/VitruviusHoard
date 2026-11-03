import sys
import time

from fastapi.testclient import TestClient
import pytest

from theseus import strategies
from theseus.api import create_app


def wait(store, job_id, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        job = store.job(job_id)
        if job["state"] not in {"queued", "running"}:
            return job
        time.sleep(.02)
    raise AssertionError("Job did not terminate")


@pytest.fixture
def workspace(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app, base_url="http://127.0.0.1:5217") as client:
        client.get("/")
        project = app.state.store.create_project("Properties")
        yield client, app, project["id"], tmp_path


def script(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return str(path)


def run(workspace, suite, **options):
    client, app, pid, _ = workspace
    response = client.post("/api/projects/" + pid + "/properties/runs", json={"suite": suite, **options})
    assert response.status_code == 200, response.text
    done = wait(app.state.store, response.json()["id"])
    assert done["state"] == "finished", done["result"].get("error")
    return done["result"]


ENTITIES = {"kind": "lists", "min_size": 0, "max_size": 5, "of": {"kind": "dicts", "fields": {
    "id": {"kind": "integers", "min": 0, "max": 99}, "name": {"kind": "text", "max_len": 5, "alphabet": "abc"},
    "tags": {"kind": "lists", "max_size": 3, "of": {"kind": "text", "min_len": 1, "max_len": 3, "alphabet": "xyz"}}}}}

# export serialises entities as JSON lines; import reads them back. The seeded defect: tags are dropped on export.
STORE_IN = ("import sys, json\nmode = sys.argv[1]\nBUG = %s\n"
            "raw = sys.stdin.read()\n"
            "if mode == 'export':\n"
            "    data = json.loads(raw)\n"
            "    for e in data:\n"
            "        e = dict(e)\n"
            "        if BUG and e.get('tags'): e.pop('tags')\n"
            "        print(json.dumps(e))\n"
            "else:\n"
            "    print(json.dumps([json.loads(l) for l in raw.splitlines()]))\n")


def roundtrip_suite(tmp_path, bug):
    path = script(tmp_path, "store%s.py" % bug, STORE_IN % bug)
    return {"target": {"argv": [sys.executable, path, "export"], "decode": "text"}, "input": ENTITIES, "runs": 10, "seed": 4,
            "properties": [{"kind": "roundtrip", "name": "export-import preserves entities",
                            "then": {"argv": [sys.executable, path, "import"]}}]}


def test_round_trip_bug_is_caught_and_shrunk_to_one_entity_with_one_tag(workspace):
    result = run(workspace, roundtrip_suite(workspace[3], True))
    assert result["summary"]["verdict"] == "counterexample_found"
    prop = result["properties"][0]
    assert prop["status"] == "violated"
    cx = prop["counterexample"]
    assert cx["reexecuted_and_confirmed"] and cx["reruns"] > 0
    minimal = cx["minimal"]
    assert len(minimal) == 1 and len(minimal[0]["tags"]) == 1 and len(minimal[0]["tags"][0]) == 1
    assert minimal[0]["id"] == 0 and minimal[0]["name"] == ""
    assert cx["observed"]["output"] != minimal


def test_round_trip_without_the_bug_holds_on_all_runs(workspace):
    result = run(workspace, roundtrip_suite(workspace[3], False))
    prop = result["properties"][0]
    assert prop["status"] == "held" and prop["runs"] == 10
    assert result["summary"]["verdict"] == "no_counterexample_found"
    assert "not a proof" in result["summary"]["note"]


def test_idempotence_bug_is_caught(workspace):
    tmp = workspace[3]
    path = script(tmp, "norm.py", "import sys, json\nx = json.loads(sys.stdin.read())\n"
                  "print(json.dumps(x.replace('aa', 'a')))\n")
    suite = {"target": {"argv": [sys.executable, path]}, "input": {"kind": "text", "max_len": 8, "alphabet": "ab"},
             "runs": 12, "seed": 2, "properties": [{"kind": "idempotent", "name": "collapse twice"}]}
    result = run(workspace, suite)
    prop = result["properties"][0]
    assert prop["status"] == "violated", prop
    cx = prop["counterexample"]
    assert cx["reexecuted_and_confirmed"] and cx["minimal"] == "aaa"
    assert cx["observed"]["first"] != cx["observed"]["output"]


def test_metamorphic_invariant_and_callable_target(workspace):
    tmp = workspace[3]
    (tmp / "calc.py").write_text("def total(xs):\n    return sum(xs) if len(xs) < 4 else sum(sorted(xs)[:-1]) + max(xs)\n"
                                 "def buggy(xs):\n    return sum(xs[:3])\n", encoding="utf-8")
    base = {"input": {"kind": "lists", "min_size": 4, "max_size": 6, "of": {"kind": "integers", "min": 0, "max": 9}}, "runs": 5, "seed": 5}
    good = run(workspace, {**base, "target": {"callable": "calc:total", "path": str(tmp)},
                           "properties": [{"kind": "metamorphic", "transform": "sorted(input)", "name": "order is irrelevant"},
                                          {"kind": "invariant", "expr": "output >= 0 and output == sum(input)", "name": "sum"}]})
    assert good["summary"]["verdict"] == "no_counterexample_found", good["summary"]
    bad = run(workspace, {**base, "target": {"callable": "calc:buggy", "path": str(tmp)},
                          "properties": [{"kind": "metamorphic", "transform": "sorted(input)", "name": "order is irrelevant"}]})
    prop = bad["properties"][0]
    assert prop["status"] == "violated" and len(prop["counterexample"]["minimal"]) <= 4


def test_crash_is_a_failure_and_when_filters_inputs(workspace):
    tmp = workspace[3]
    path = script(tmp, "div.py", "import sys, json\nn = json.loads(sys.stdin.read())\nprint(json.dumps(100 // n))\n")
    suite = {"target": {"argv": [sys.executable, path]}, "input": {"kind": "integers", "min": -5, "max": 5}, "runs": 30,
             "properties": [{"kind": "invariant", "expr": "output <= 100", "name": "crash on zero"},
                            {"kind": "invariant", "when": "input != 0", "expr": "output <= 100", "name": "filtered"}]}
    result = run(workspace, suite)
    crash, filtered = result["properties"]
    assert crash["status"] == "crash" and crash["counterexample"]["minimal"] == 0
    assert filtered["status"] == "held" and filtered["skipped"] >= 0


def test_self_comparison_oracles_are_warned_about(workspace):
    tmp = workspace[3]
    path = script(tmp, "dbl.py", "import sys, json\nprint(json.dumps(json.loads(sys.stdin.read()) * 2))\n")
    copy = script(tmp, "copy_of_dbl.py", "import sys, json\nprint(json.dumps(json.loads(sys.stdin.read()) * 2))\n")
    suite = {"target": {"argv": [sys.executable, path]}, "input": {"kind": "integers"}, "runs": 2, "properties": [
        {"kind": "model", "name": "reference is a copy", "reference": {"argv": [sys.executable, copy]}},
        {"kind": "metamorphic", "name": "identity", "transform": "input"},
        {"kind": "invariant", "name": "tautology", "expr": "output == output"},
        {"kind": "invariant", "name": "real", "expr": "output == input * 2"}]}
    result = run(workspace, suite)
    by_name = {p["name"]: p for p in result["properties"]}
    for name in ("reference is a copy", "identity", "tautology"):
        assert by_name[name]["warnings"], name
        assert by_name[name]["warnings"][0]["code"] in {"self_comparison", "tautology"}
    assert not by_name["real"]["warnings"]
    assert set(result["summary"]["self_comparison_warnings"]) == {"reference is a copy", "identity", "tautology"}
    assert "little evidence" in result["summary"]["note"]


def test_model_property_with_an_independent_reference_catches_a_defect(workspace):
    tmp = workspace[3]
    ref = script(tmp, "ref.py", "import sys, json\nprint(json.dumps(sorted(json.loads(sys.stdin.read()))))\n")
    impl = script(tmp, "impl.py", "import sys, json\nprint(json.dumps(sorted(set(json.loads(sys.stdin.read())))))\n")
    suite = {"target": {"argv": [sys.executable, impl]}, "input": {"kind": "lists", "max_size": 5, "of": {"kind": "integers", "min": 0, "max": 3}},
             "runs": 12, "seed": 1, "properties": [{"kind": "model", "reference": {"argv": [sys.executable, ref]}}]}
    prop = run(workspace, suite)["properties"][0]
    assert prop["status"] == "violated" and prop["counterexample"]["minimal"] in ([0, 0], [1, 1], [2, 2], [3, 3])
    assert not prop["warnings"]


# --------------------------------------------------------------- stateful

EDITOR = ("import sys, json, os\n"
          "BUG = %s\n"
          "cmd = sys.argv[1]\n"
          "state = json.load(open('state.json')) if os.path.exists('state.json') else {'doc': '', 'hist': []}\n"
          "if cmd == 'save':\n"
          "    state['hist'].append(state['doc']); state['doc'] = sys.argv[2]\n"
          "elif cmd == 'undo':\n"
          "    if state['hist']:\n"
          "        state['doc'] = state['hist'][0 if (BUG and len(state['hist']) >= 2) else -1]\n"
          "        state['hist'] = state['hist'][:-1]\n"
          "elif cmd == 'reload':\n"
          "    pass\n"
          "json.dump(state, open('state.json', 'w'))\n"
          "print(state['doc'])\n")


def editor_suite(tmp_path, bug, runs=25):
    path = script(tmp_path, "editor%s.py" % bug, EDITOR % bug)
    return {"stateful": [{
        "name": "editor", "program": {"argv": [sys.executable, path]}, "init": {"doc": "", "hist": []},
        "runs": runs, "max_length": 5, "seed": 3,
        "commands": [
            {"name": "save", "args": ["save", "{text}"], "params": {"text": {"kind": "text", "min_len": 1, "max_len": 3, "alphabet": "abc"}},
             "update": {"hist": "hist + [doc]", "doc": "text"}, "post": [{"name": "shows saved text", "expr": "rstrip(stdout) == doc"}]},
            {"name": "undo", "args": ["undo"], "pre": "len(hist) > 0", "update": {"doc": "hist[-1]", "hist": "hist[:-1]"},
             "post": [{"name": "undo restores the previous document", "expr": "rstrip(stdout) == doc"}]},
            {"name": "reload", "args": ["reload"], "post": [{"name": "reload keeps the document", "expr": "rstrip(stdout) == doc"}]}]}]}


def test_stateful_undo_bug_is_found_and_shrunk_to_three_commands(workspace):
    result = run(workspace, editor_suite(workspace[3], True), shrink_budget=40)
    record = result["stateful"][0]
    assert result["summary"]["verdict"] == "counterexample_found" and record["status"] == "violated"
    cx = record["counterexample"]
    assert cx["commands"] <= 3 and len(cx["minimal"]) <= 3
    assert [s["command"] for s in cx["minimal"]] == ["save", "save", "undo"]
    assert cx["failure"]["property"] == "undo restores the previous document"
    assert cx["reexecuted_and_confirmed"] and cx["reruns"] > 0
    assert len(cx["original"]) >= len(cx["minimal"])
    assert all(len(s["params"]["text"]) == 1 for s in cx["minimal"] if s["command"] == "save")


def test_stateful_sequences_of_a_correct_program_hold(workspace):
    result = run(workspace, editor_suite(workspace[3], False, runs=5))
    record = result["stateful"][0]
    assert record["status"] == "held" and record["runs"] >= 4
    assert result["summary"]["verdict"] == "no_counterexample_found"


def test_suite_validation_and_strategies(workspace):
    client, app, pid, tmp = workspace
    base = "/api/projects/" + pid + "/properties/runs"
    for suite in ({"properties": [{"kind": "invariant", "expr": "open(1)"}], "target": {"argv": ["x"]}, "input": {"kind": "integers"}},
                  {"properties": [{"kind": "roundtrip"}], "target": {"argv": ["x"]}, "input": {"kind": "integers"}},
                  {"stateful": [{"program": {"callable": "a:b"}, "commands": [{"name": "c"}]}]},
                  {"properties": [{"kind": "invariant", "expr": "True"}], "target": {"argv": ["x"]}},
                  {}):
        assert client.post(base, json={"suite": suite}).status_code >= 400
    import random
    s = strategies.validate({"kind": "one_of", "options": [{"kind": "integers", "min": 0, "max": 5},
                                                            {"kind": "tuples", "items": [{"kind": "text", "max_len": 3}, {"kind": "booleans"}]}]})
    a = [strategies.generate(s, random.Random(7), .5) for _ in range(3)]
    b = [strategies.generate(s, random.Random(7), .5) for _ in range(3)]
    assert a == b and all(strategies.conforms(s, v) for v in a)
    assert next(strategies.shrink({"kind": "integers", "min": 0, "max": 9}, 7)) == 0
