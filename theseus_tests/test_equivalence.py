import json
from pathlib import Path
import sys
import time

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app

ROUND_REF = "import sys\nprint(round(float(sys.stdin.read())))\n"
ROUND_CAND = "import sys,math\nprint(int(math.floor(float(sys.stdin.read())+0.5)))\n"


def wait(store, job_id, seconds=60):
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
        project = app.state.store.create_project("Equivalence")
        yield client, app, project["id"], tmp_path


def program(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return [sys.executable, str(path)]


def run(workspace, suite, **options):
    client, app, pid, _ = workspace
    job = client.post("/api/projects/" + pid + "/equivalence/runs", json={"suite": suite, **options}).json()
    done = wait(app.state.store, job["id"])
    assert done["state"] == "finished", done["result"].get("error")
    return done["result"]


def suite_of(tmp_path, ref, cand, cases, **extra):
    return {"reference": {"argv": program(tmp_path, "ref.py", ref)}, "candidate": {"argv": program(tmp_path, "cand.py", cand)},
            "cases": cases, **extra}


def case(result, name):
    return next(c for c in result["cases"] if c["name"] == name)


def test_rounding_change_is_detected_with_first_disagreement(workspace):
    suite = suite_of(workspace[3], ROUND_REF, ROUND_CAND, [
        {"name": "plain", "stdin": "2.7"}, {"name": "tie", "stdin": "2.5"}, {"name": "tie2", "stdin": "0.5"}], )
    result = run(workspace, suite, strength=False)
    assert case(result, "plain")["verdict"] == "equivalent"
    tie = case(result, "tie")
    assert tie["verdict"] == "different"
    first = tie["first_disagreement"]
    assert (first["step"], first["channel"]) == (1, "stdout")
    assert "-2" in first["diff"] and "+3" in first["diff"]
    assert tie["reference"]["steps"][0]["stdout_sha256"] != tie["candidate"]["steps"][0]["stdout_sha256"]
    assert result["summary"]["verdict"] == "different" and result["summary"]["first_disagreement"]["case"] == "tie"
    assert "not whole-program" in result["scope"]


def test_ordering_change_and_opt_in_sort_normaliser(workspace):
    ref = "print('\\n'.join(sorted(['b','a','c'])))\n"
    cand = "print('\\n'.join(['b','a','c']))\n"
    base = suite_of(workspace[3], ref, cand, [{"name": "order"}])
    assert run(workspace, base, strength=False)["cases"][0]["verdict"] == "different"
    sorted_suite = {**base, "normalisers": ["sort_lines"]}
    result = run(workspace, sorted_suite, strength=False)
    entry = result["cases"][0]
    assert entry["verdict"] == "equivalent"
    assert entry["normalisers"][0]["name"] == "sort_lines"
    assert entry["equal_only_after_normalisation"] == [{"step": 1, "channel": "stdout"}]


def test_numeric_tolerance_and_ignore_regex_are_recorded(workspace):
    ref = "print('t=123 value 1.0000')\n"
    cand = "print('t=999 value 1.0004')\n"
    suite = suite_of(workspace[3], ref, cand, [{"name": "n"}], normalisers=[
        {"name": "ignore_regex", "pattern": r"t=\d+"}, {"name": "numeric_tolerance", "abs": 0.001}])
    result = run(workspace, suite, strength=False)
    assert result["cases"][0]["verdict"] == "equivalent"
    assert [n["name"] for n in result["cases"][0]["normalisers"]] == ["ignore_regex", "numeric_tolerance"]
    with pytest.raises(ValueError):
        from theseus.equivalence import validate_suite
        validate_suite({**suite, "normalisers": ["nonsense"]})


def test_error_exit_and_message_change(workspace):
    ref = "import sys\nsys.stderr.write('bad input\\n')\nsys.exit(2)\n"
    cand = "import sys\nsys.stderr.write('invalid input\\n')\nsys.exit(1)\n"
    suite = suite_of(workspace[3], ref, cand, [{"name": "err"}])
    entries = run(workspace, suite, strength=False)["cases"][0]["disagreements"]
    assert [(d["channel"]) for d in entries] == ["exit_code", "stderr"]
    assert entries[0]["reference"] == 2 and entries[0]["candidate"] == 1
    relaxed = run(workspace, {**suite, "channels": ["exit_code", "stdout"]}, strength=False)["cases"][0]["disagreements"]
    assert [d["channel"] for d in relaxed] == ["exit_code"]


def test_side_effects_files_and_database(workspace):
    ref = ("import sqlite3\nc=sqlite3.connect('app.db')\nc.execute(\"INSERT INTO t(id,v) VALUES (2,'x')\")\nc.commit()\n"
           "open('out.txt','w').write('same')\n")
    cand = ("import sqlite3\nc=sqlite3.connect('app.db')\nc.execute(\"INSERT INTO t(id,v) VALUES (2,'y')\")\nc.commit()\n"
            "open('out.txt','w').write('same')\nopen('extra.log','w').write('side')\n")
    seed = "CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT); INSERT INTO t VALUES (1,'a');"
    suite = suite_of(workspace[3], ref, cand, [{"name": "db", "db": {"path": "app.db", "seed_sql": seed}}])
    found = run(workspace, suite, strength=False)["cases"][0]["disagreements"]
    by = {(d["channel"], d["path"]): d for d in found}
    assert by[("files", "extra.log")]["kind"] == "effect"
    row = by[("db", "t")]
    assert row["kind"] == "row_changed" and row["key"] == [2] and row["columns"] == ["v"]
    assert ("files", "out.txt") not in by


def test_database_row_order_is_ignored_unless_ordered(workspace):
    ref = "import sqlite3\nc=sqlite3.connect('o.db')\nc.execute('CREATE TABLE t(v TEXT)')\nc.executemany('INSERT INTO t VALUES (?)',[('a',),('b',)])\nc.commit()\n"
    cand = ref.replace("[('a',),('b',)]", "[('b',),('a',)]")
    base = suite_of(workspace[3], ref, cand, [{"name": "o", "db": {"path": "o.db"}}])
    assert run(workspace, base, strength=False)["cases"][0]["verdict"] == "equivalent"
    ordered = run(workspace, {**base, "ordered_tables": ["t"]}, strength=False)["cases"][0]
    assert ordered["verdict"] == "different" and ordered["first_disagreement"]["kind"] == "row_order"


STATE_REF = ("import sys,os\nn=int(open('n').read()) if os.path.exists('n') else 0\nn+=1\nopen('n','w').write(str(n))\nprint(n)\n")
STATE_CAND = ("import sys,os\nn=int(open('n').read()) if os.path.exists('n') else 0\nn+=1 if n<1 else 2\nopen('n','w').write(str(n))\nprint(n)\n")


def test_sequence_diverges_on_second_step(workspace):
    suite = suite_of(workspace[3], STATE_REF, STATE_CAND, [{"name": "seq", "steps": [{}, {}, {}]}])
    entry = run(workspace, suite, strength=False)["cases"][0]
    first = entry["first_disagreement"]
    assert first["step"] == 2 and first["channel"] == "stdout"
    assert entry["reference"]["steps"][0]["stdout"] == entry["candidate"]["steps"][0]["stdout"]
    # steps share one sandbox but runs never share state
    again = run(workspace, suite, strength=False)["cases"][0]
    assert again["reference"]["steps"][0]["stdout"] == "1\n"


def test_authorized_deviation_is_reported_not_ignored(workspace):
    ref = "print('Total: 5')\n"
    cand = "print('Total = 5')\n"
    deviation = {"case": "fmt*", "channel": "stdout", "expected": "uses '=' instead of ':'", "reason": "approved style change",
                 "expected_candidate": {"equals": "Total = 5\n"}}
    suite = suite_of(workspace[3], ref, cand, [{"name": "fmt-a"}], authorized_deviations=[deviation])
    result = run(workspace, suite, strength=False)
    entry = result["cases"][0]
    assert entry["verdict"] == "authorized_deviation"
    assert entry["disagreements"][0]["status"] == "authorized_deviation"
    assert entry["disagreements"][0]["authorization"]["reason"] == "approved style change"
    assert result["summary"]["verdict"] == "authorized_deviation_only" and result["summary"]["authorized_deviations"] == 1
    # candidate that no longer matches the authorized behaviour is a real disagreement
    drifted = {**suite, "candidate": {"argv": program(workspace[3], "drift.py", "print('Total - 5')\n")}}
    entry = run(workspace, drifted, strength=False)["cases"][0]
    assert entry["verdict"] == "different" and "authorization_violated" in entry["disagreements"][0]


def test_constant_candidate_is_rejected_and_weak_suite_flagged(workspace):
    ref = "import sys\nprint(sys.stdin.read().upper())\n"
    strong = suite_of(workspace[3], ref, ref, [{"name": "a", "stdin": "abc"}, {"name": "b", "stdin": "xyz"}])
    result = run(workspace, strong)
    assert result["summary"]["verdict"] == "agrees_on_listed_cases" and result["strength"]["weak"] is False
    assert all(m["rejected"] for m in result["strength"]["mutants"])
    weak = suite_of(workspace[3], "print('same')\n", "print('same')\n", [{"name": "only"}, {"name": "again", "stdin": "q"}])
    result = run(workspace, weak)
    assert result["strength"]["weak"] is True and result["summary"]["weak_suite"] is True
    assert "cannot distinguish a constant program" in result["strength"]["message"]


def test_generated_cases_are_seeded_and_failures_shrink_by_rerunning(workspace):
    generator = {"kind": "decimals", "count": 30, "seed": 7, "template": {"stdin": "{value}"}}
    suite = suite_of(workspace[3], ROUND_REF, ROUND_CAND, [], generators=[generator])
    first = run(workspace, suite, strength=False)
    second = run(workspace, suite, strength=False)
    assert [c["generated"]["value"] for c in first["cases"]] == [c["generated"]["value"] for c in second["cases"]]
    failing = [c for c in first["cases"] if c["verdict"] == "different"]
    assert failing and all("shrunk" in c for c in failing)
    for c in failing:
        info = c["shrunk"]
        assert info["reexecuted_and_confirmed"] and len(info["minimal_value"]) <= len(info["original_value"])
        assert all(step["confirmed_by_rerun"] for step in info["steps"])
    smallest = min((c["shrunk"]["minimal_value"] for c in failing), key=len)
    assert len(smallest) <= 3
    # the minimal input genuinely disagrees when run directly
    ref = suite["reference"]["argv"]; cand = suite["candidate"]["argv"]
    import subprocess
    out = [subprocess.run(a, input=smallest, capture_output=True, text=True).stdout for a in (ref, cand)]
    assert out[0] != out[1]


def test_generator_grammar_covers_boundaries_unicode_and_permutations():
    from theseus.equivalence import generate_values, shrink_candidates
    ints = generate_values({"kind": "integers", "count": 25, "seed": 1})
    assert {"0", "-1", str(2 ** 31 - 1), str(2 ** 63)} <= set(ints)
    dec = generate_values({"kind": "decimals", "count": 16, "seed": 1})
    assert "2.675" in dec and "0.5" in dec
    strings = generate_values({"kind": "strings", "count": 20, "seed": 3})
    assert "" in strings and any(any(ord(ch) > 127 for ch in s) for s in strings)
    perms = generate_values({"kind": "permutations", "count": 6, "seed": 2, "items": ["a", "b", "c"], "separator": ","})
    assert len(set(perms)) == len(perms) and all(sorted(p.split(",")) == ["a", "b", "c"] for p in perms)
    assert "" in shrink_candidates("strings", "abc") and "a,b" in shrink_candidates("permutations", "c,a,b")


def test_ordering_permutation_generator_finds_order_dependence(workspace):
    ref = "import sys\nprint(','.join(sorted(sys.stdin.read().strip().split(','))))\n"
    cand = "import sys\nprint(sys.stdin.read().strip())\n"
    suite = suite_of(workspace[3], ref, cand, [], generators=[{"kind": "permutations", "count": 4, "seed": 5,
                      "items": ["b", "a", "c"], "template": {"stdin": "{value}"}}])
    result = run(workspace, suite, strength=False)
    assert any(c["verdict"] == "different" for c in result["cases"])
    assert any(c["verdict"] == "equivalent" for c in result["cases"])  # sorted permutation agrees


def test_input_files_and_unicode_round_trip(workspace):
    script = "import sys\nprint(open(sys.argv[1],encoding='utf-8').read().upper())\n"
    suite = suite_of(workspace[3], script, script, [{"name": "u", "args": ["in.txt"], "files": {"in.txt": "\u00e9\u65e5\U0001f600"}}])
    entry = run(workspace, suite, strength=False)["cases"][0]
    assert entry["verdict"] == "equivalent" and "\u00e9".upper() in entry["reference"]["steps"][0]["stdout"]


def test_suite_validation_rejects_escapes_and_bad_shapes():
    from theseus.equivalence import validate_suite
    ok = {"reference": {"argv": ["x"]}, "candidate": {"argv": ["y"]}}
    with pytest.raises(ValueError):
        validate_suite({**ok, "cases": [{"files": {"../evil": "x"}}]})
    with pytest.raises(ValueError):
        validate_suite({**ok, "cases": [{"name": "a", "stdin": "x", "steps": [{}]}]})
    with pytest.raises(ValueError):
        validate_suite({**ok})
    with pytest.raises(ValueError):
        validate_suite({**ok, "cases": [{}], "authorized_deviations": [{"channel": "stdout"}]})


def test_tools_save_read_run_and_evidence_round_trip(workspace):
    client, app, pid, tmp = workspace
    suite = suite_of(tmp, ROUND_REF, ROUND_CAND, [{"name": "tie", "stdin": "2.5"}])
    def call(tool, **args):
        reply = client.post("/api/agent/call", json={"tool": tool, "arguments": {"project_id": pid, **args}})
        assert reply.status_code == 200, reply.text
        return reply.json()["result"]
    saved = call("theseus_equivalence_suite_save", name="rounding", suite=suite)
    assert saved["revision"] == 1
    assert call("theseus_equivalence_suite_save", name="rounding", suite=suite, suite_id=saved["id"])["revision"] == 2
    assert call("theseus_equivalence_suite_read")["suites"][0]["cases"] == 1
    assert call("theseus_equivalence_suite_read", suite_id=saved["id"])["suite"]["cases"][0]["name"] == "tie"
    job = call("theseus_equivalence_run", suite_id=saved["id"], strength=False)
    done = wait(app.state.store, job["id"])
    assert done["result"]["kind"] == "equivalence_run" and done["result"]["summary"]["verdict"] == "different"
    assert done["result"]["suite_revision"] == 2
    bundle = client.post("/api/agent/call", json={"tool": "theseus_evidence_export", "arguments": {"project_id": pid}}).json()["result"]
    exported = [j for j in bundle["payload"]["jobs"] if j["result"].get("kind") == "equivalence_run"]
    assert exported and exported[0]["result"]["cases"][0]["disagreements"]
    imported = client.post("/api/agent/call", json={"tool": "theseus_evidence_import", "arguments": {"bundle": bundle, "name": "copy"}})
    assert imported.status_code == 200, imported.text
    missing = client.get("/api/projects/" + pid + "/equivalence/suites/nope")
    assert missing.status_code == 404
