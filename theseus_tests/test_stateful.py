import json
import os
from pathlib import Path
import subprocess
import sys
import time

from fastapi.testclient import TestClient
import pytest

from theseus import stateful_core as core, strategies
from theseus.api import TOOLS, create_app
from stateful_fixture import quotes_recipe, service, target

SEED = 7


def wait(store, job_id, seconds=300):
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
        project = app.state.store.create_project("Quotes")
        yield client, app, project["id"], tmp_path


def call(client, tool_name, **arguments):
    response = client.post("/api/agent/call", json={"tool": tool_name, "arguments": arguments})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def run(workspace, **body):
    client, app, pid, _ = workspace
    response = client.post("/api/projects/%s/stateful/runs" % pid, json=body)
    assert response.status_code == 200, response.text
    done = wait(app.state.store, response.json()["id"])
    assert done["state"] == "finished", done["result"].get("error")
    return done


def first_failure(workspace, version="v1", **overrides):
    return run(workspace, recipe=quotes_recipe(version, **overrides))


def test_seeded_run_finds_and_reduces_a_failure_that_still_fails(workspace):
    done = first_failure(workspace)
    result = done["result"]
    assert result["summary"]["verdict"] == "counterexample_found"
    example = result["counterexample"]
    assert example["reexecuted_and_confirmed"] is True
    assert example["minimal_length"] < example["original_length"]
    assert example["minimal_length"] <= 6
    action, kind, name = example["signature"]
    assert kind in {"postcondition", "invariant"}
    assert (action, name) in {("remove_line", "total after edit"), ("retry_confirm", "same charge on retry"),
                              ("remove_line", "stored total"), ("retry_confirm", "one charge per confirmation")}
    # the minimal sequence still fails with the same signature on a fresh process
    recipe = core.validate_recipe(result["recipe"], strategies.validate)
    again = core.run_sequence(recipe, example["minimal"])
    assert again["outcome"] == "failed" and again["signature"] == example["signature"]
    # every operand of the violated oracle is explained with observed values
    violation = example["violations"][0]
    assert violation["observed"]["operands"] and all("value" in p for p in violation["observed"]["operands"])
    assert example["explanation"].startswith("Step ")
    # coverage reports executed and never-executed actions and transitions
    coverage = result["coverage"]
    assert {row["action"] for row in coverage["actions"]} == {a["name"] for a in result["recipe"]["actions"]}
    assert any(row["executed"] for row in coverage["actions"])
    assert "transitions_not_observed" in coverage and coverage["transitions_declared"] == 6 + 36


def test_seed_reproduces_the_same_original_sequence_and_signature(workspace):
    first = first_failure(workspace)["result"]["counterexample"]
    again = run(workspace, recipe=quotes_recipe("v1"), seed=first["reproduce"]["seed"], runs=1, shrink=False)["result"]
    assert again["counterexample"]["original"] == first["original"]
    assert again["counterexample"]["signature"] == first["signature"]


def test_fixed_version_passes_every_run(workspace):
    result = run(workspace, recipe=quotes_recipe("v2"), runs=12)["result"]
    assert result["summary"]["verdict"] == "no_counterexample_found"
    assert result["summary"]["outcomes"]["passed"] == 12
    assert result["counterexample"] is None
    assert "not a proof" in result["scope"]


def test_setup_failure_is_inconclusive_not_a_pass(workspace):
    broken = quotes_recipe("v2", target={"argv": ["{python}", "-c", "import sys; sys.exit(3)"], "ready": "/health",
                                         "ready_timeout_seconds": 5})
    result = run(workspace, recipe=broken)["result"]
    assert result["summary"]["verdict"] == "inconclusive"
    assert result["runs"][0]["outcome"] == "inconclusive" and "exited with code 3" in result["runs"][0]["reason"]
    # a setup request that the service refuses also makes the chain inconclusive
    refused = quotes_recipe("v2", setup=[{"name": "seed quote", "request": {"method": "POST", "path": "/quotes", "body": {}},
                                          "expect_status": 201}])
    result = run(workspace, recipe=refused, runs=2)["result"]
    assert result["summary"]["verdict"] == "inconclusive"
    assert "answered HTTP 422" in result["runs"][0]["reason"]


def test_replay_against_fixed_version_rebinds_ids_and_does_not_reproduce(workspace):
    client, app, pid, _ = workspace
    done = first_failure(workspace)
    example = done["result"]["counterexample"]
    buggy = call(client, "theseus_stateful_replay", project_id=pid, job_id=done["id"])["result"]
    assert buggy["reproduces_original_signature"] is True
    fixed = call(client, "theseus_stateful_replay", project_id=pid, job_id=done["id"], target=target("v2"))["result"]
    assert fixed["result"]["outcome"] == "passed"
    assert fixed["reproduces_original_signature"] is False
    seen_before = set(example["ids_observed"]) | set(buggy["ids_observed"][0])
    seen_fixed = set(fixed["ids_observed"][0])
    assert seen_fixed and not (seen_fixed & seen_before)
    paths = [s["lanes"]["target"]["request"]["path"] for s in fixed["result"]["trace"]]
    assert not any(old in path for old in seen_before for path in paths)


def test_http_errors_and_sqlite_effects_are_reported_separately(workspace):
    recipe = core.validate_recipe(quotes_recipe("v1"), strategies.validate)
    sequence = [{"action": "create_quote", "params": {"customer": "Imprenta Sol"}, "picks": {}},
                {"action": "add_line", "params": {"qty": 1, "unit": 500}, "picks": {}},
                {"action": "confirm", "params": {"new_key": "00000000"}, "picks": {}},
                {"action": "retry_confirm", "params": {}, "picks": {}}]
    result = core.run_sequence(recipe, sequence)
    step = result["trace"][-1]
    assert {v["evidence"] for v in step["violations"]} == {"http", "sqlite"}
    effects = step["lanes"]["target"]["effects"]["sqlite"]
    assert effects["charges"]["added"] == 1 and effects["charges"]["sample"]["added"][0]["idempotency_key"] == "00000000"
    # an HTTP status the action does not accept is its own kind, with status and body preserved
    fixed = core.validate_recipe(quotes_recipe("v2"), strategies.validate)
    result = core.run_sequence(fixed, [{"action": "create_quote", "params": {"customer": ""}, "picks": {}}])
    assert result["failure"]["kind"] == "http_status" and result["failure"]["observed"]["status"] == 422
    assert "customer is required" in result["failure"]["observed"]["body"]
    # a precondition that does not hold makes the candidate invalid, not failed
    assert core.run_sequence(recipe, sequence[1:])["outcome"] == "invalid"


def test_file_effects_and_reference_relations(workspace, tmp_path):
    script = tmp_path / "files_service.py"
    script.write_text(
        "import json, os, sys\nfrom http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "DOUBLE = sys.argv[1] == 'double'\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def log_message(self, *a): pass\n"
        "    def do_POST(self):\n"
        "        n = len(os.listdir('out'))\n"
        "        for i in range(2 if DOUBLE else 1): open('out/%d-%d.txt' % (n, i), 'w').write('x')\n"
        "        data = json.dumps({'files': len(os.listdir('out'))}).encode()\n"
        "        self.send_response(201); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)\n"
        "os.makedirs('out', exist_ok=True)\n"
        "HTTPServer(('127.0.0.1', int(os.environ['PORT'])), H).serve_forever()\n", encoding="utf-8")
    recipe = {"name": "files", "target": {"argv": ["{python}", str(script), "double"]},
              "reference": {"argv": ["{python}", str(script), "single"]},
              "watch": {"files": ["out/*"]}, "model": {"written": 0},
              "actions": [{"name": "write", "request": {"method": "POST", "path": "/w"}, "expect_status": 201,
                           "update": {"written": "written + 1"},
                           "agree": [{"name": "same count as reference", "expr": "body['files'] == ref_body['files']"}]}]}
    result = core.run_sequence(core.validate_recipe(recipe, strategies.validate), [{"action": "write", "params": {}, "picks": {}}])
    assert result["failure"]["kind"] == "reference" and result["failure"]["evidence"] == "reference"
    effects = result["trace"][0]["lanes"]["target"]["effects"]["files"]
    assert sorted(effects) == ["out/0-0.txt", "out/0-1.txt"] and all(e["op"] == "created" for e in effects.values())
    assert list(result["trace"][0]["lanes"]["reference"]["effects"]["files"]) == ["out/0-0.txt"]


def test_export_runs_with_pytest_failing_on_buggy_and_passing_on_fixed(workspace, tmp_path):
    client, app, pid, _ = workspace
    done = first_failure(workspace)
    out = tmp_path / "receiver"
    exported = call(client, "theseus_stateful_export", project_id=pid, job_id=done["id"], output_dir=str(out))
    names = {f["name"] for f in exported["files"]}
    assert {"theseus_stateful_adapter.py", "theseus_expressions.py", "regression.json", exported["test"]} <= names
    adapter = (out / "theseus_stateful_adapter.py").read_text(encoding="utf-8")
    assert "import theseus" not in adapter.replace("import theseus_expressions", "")
    # the receiver runs it in an isolated interpreter (-I: no Theseus on the path, no user site), no network needed
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "THESEUS_TARGET_ARGV", "THESEUS_TARGET_URL")}
    command = [sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", exported["test"]]
    buggy = subprocess.run(command, cwd=out, env=env, capture_output=True, text=True, timeout=300)
    assert buggy.returncode == 1, buggy.stdout + buggy.stderr
    assert "original failure signature" in buggy.stdout
    fixed_env = {**env, "THESEUS_TARGET_ARGV": json.dumps(["{python}", service("v2"), "--db", "{sandbox}/quotes.db", "--port", "{port}"])}
    fixed = subprocess.run(command, cwd=out, env=fixed_env, capture_output=True, text=True, timeout=300)
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "1 passed" in fixed.stdout


def test_recipes_are_stored_validated_and_exposed_as_tools(workspace):
    client, app, pid, _ = workspace
    saved = call(client, "theseus_stateful_recipe_save", project_id=pid, recipe=quotes_recipe("v2"), name="Presupuestos")
    assert saved["revision"] == 1 and saved["name"] == "Presupuestos"
    again = call(client, "theseus_stateful_recipe_save", project_id=pid, recipe=quotes_recipe("v2", runs=3), recipe_id=saved["id"])
    assert again["revision"] == 2
    listed = call(client, "theseus_stateful_recipe_read", project_id=pid)["recipes"]
    assert listed[0]["actions"][0] == "create_quote"
    job = call(client, "theseus_stateful_run", project_id=pid, recipe_id=saved["id"], runs=2)
    assert wait(app.state.store, job["id"])["result"]["summary"]["verdict"] == "no_counterexample_found"
    for broken, message in (({**quotes_recipe("v2"), "model": {"status": 1}}, "may not be named"),
                            (quotes_recipe("v2", queries={"x": "DELETE FROM quotes"}), "single SELECT"),
                            ({**quotes_recipe("v2"), "actions": [{"name": "a", "request": {"path": "/q/{nope}"}}]}, "{nope}"),
                            ({**quotes_recipe("v2"), "actions": [{"name": "a", "pre": "__import__('os')", "request": {}}]}, "rejected")):
        response = client.post("/api/projects/%s/stateful/recipes" % pid, json={"recipe": broken})
        assert response.status_code == 400 and message in response.text, response.text
    names = {t["name"] for t in TOOLS}
    assert {"theseus_stateful_recipe_save", "theseus_stateful_recipe_read", "theseus_stateful_run",
            "theseus_stateful_replay", "theseus_stateful_export"} <= names


def test_sql_queries_are_read_only(tmp_path):
    db = tmp_path / "x.db"
    import sqlite3
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        c.execute("INSERT INTO t VALUES (1, 'a')")
    state = core.sqlite_state(db, None, {"n": "SELECT COUNT(*) FROM t"})
    assert state["queries"]["n"] == [[1]]
    with pytest.raises(sqlite3.DatabaseError):
        core.sqlite_state(db, None, {"w": "WITH x AS (SELECT 1) SELECT * FROM x; DELETE FROM t"})
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1


def test_messages_exist_in_english_and_spanish_with_the_same_placeholders():
    import string
    from theseus import stateful  # noqa: F401  (registers the orchestration messages)
    for key, (en, es) in core.MESSAGES.items():
        assert en and es, key
        fields = lambda text: sorted(f for _, f, _, _ in string.Formatter().parse(text) if f)
        assert fields(en) == fields(es), key


def test_spanish_texts_keep_machine_fields_and_raw_stderr(workspace):
    client, app, pid, _ = workspace
    stderr = "Boom: port busy (raw stderr, not translated)"
    broken = quotes_recipe("v2", target={"argv": ["{python}", "-c", "import sys; print(%r, file=sys.stderr); sys.exit(3)" % stderr],
                                         "ready": "/health", "ready_timeout_seconds": 5})
    for lang, framing, note in (("es", "el destino terminó con código 3 antes de estar listo", "no se ha concluido nada"),
                                ("en", "target exited with code 3 before becoming ready", "nothing was concluded")):
        result = run(workspace, recipe=broken, lang=lang)["result"]
        assert result["summary"]["verdict"] == "inconclusive" and result["runs"][0]["outcome"] == "inconclusive"
        assert framing in result["runs"][0]["reason"] and stderr in result["runs"][0]["reason"]
        assert note in result["summary"]["note"] and result["lang"] == lang
    es_run = run(workspace, recipe=quotes_recipe("v2"), runs=1, lang="es")["result"]
    assert es_run["scope"].startswith("Sólo se ejecutaron") and "transiciones" in es_run["coverage"]["note"]
    assert es_run["summary"]["verdict"] == "no_counterexample_found"
    # a failing sequence: Spanish framing, unchanged kinds, evidence and signature
    recipe = core.validate_recipe(quotes_recipe("v1"), strategies.validate)
    sequence = [{"action": "create_quote", "params": {"customer": "Imprenta Sol"}, "picks": {}},
                {"action": "add_line", "params": {"qty": 1, "unit": 500}, "picks": {}},
                {"action": "confirm", "params": {"new_key": "00000000"}, "picks": {}},
                {"action": "retry_confirm", "params": {}, "picks": {}}]
    with core.language("es"):
        failed = core.run_sequence(recipe, sequence)
        text = core.describe(failed)
        refused = core.run_sequence(recipe, [{"action": "create_quote", "params": {"customer": ""}, "picks": {}}])
    assert failed["signature"] == ["retry_confirm", "postcondition", "same charge on retry"]
    assert text.startswith("El paso 4 (retry_confirm) falló: postcondition same charge on retry, con evidencia http.")
    assert refused["failure"]["kind"] == "http_status" and "no es un estado aceptado" in refused["failure"]["detail"]
    assert core.describe(failed).startswith("Step 4 (retry_confirm) failed")  # outside the block: English again


def test_lang_parameter_on_tools_and_rest(workspace):
    client, app, pid, _ = workspace
    for tool_name in ("theseus_stateful_recipe_save", "theseus_stateful_recipe_read", "theseus_stateful_run",
                      "theseus_stateful_replay", "theseus_stateful_export"):
        schema = next(t for t in TOOLS if t["name"] == tool_name)["inputSchema"]
        assert schema["properties"]["lang"]["enum"] == ["en", "es"] and "lang" not in schema["required"]
    bad = quotes_recipe("v2", queries={"x": "DELETE FROM quotes"})
    es = client.post("/api/projects/%s/stateful/recipes" % pid, json={"recipe": bad, "lang": "es"})
    assert es.status_code == 400 and "debe ser una única sentencia SELECT" in es.text
    en = client.post("/api/agent/call", json={"tool": "theseus_stateful_recipe_save", "arguments": {"project_id": pid, "recipe": bad}})
    assert en.status_code == 400 and "must be a single SELECT statement" in en.text
    missing = client.get("/api/projects/%s/stateful/recipes/nope?lang=es" % pid)
    assert missing.status_code == 404 and "No se encuentra la receta" in missing.text
    assert client.get("/api/projects/%s/stateful/recipes?lang=fr" % pid).status_code == 422
    done = first_failure(workspace)
    replay = call(client, "theseus_stateful_replay", project_id=pid, job_id=done["id"], target=target("v2"), lang="es")["result"]
    assert replay["note"].startswith("Los identificadores") and replay["explanation"].startswith("Se ejecutaron los")
    assert replay["result"]["outcome"] == "passed" and replay["lang"] == "es"
    exported = call(client, "theseus_stateful_export", project_id=pid, job_id=done["id"], lang="es")
    assert exported["note"].startswith("Sólo biblioteca estándar") and "elige otra versión" in exported["override"]
    adapter = next(f["text"] for f in exported["files"] if f["name"] == "theseus_stateful_adapter.py")
    assert "import contextvars" in adapter and "\nimport theseus" not in adapter
