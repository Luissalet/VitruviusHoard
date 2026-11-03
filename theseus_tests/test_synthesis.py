import sys
import time

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.expressions import Expression


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
        project = app.state.store.create_project("Synthesis")
        yield client, app, project["id"], tmp_path


def program(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return [sys.executable, str(path)]


def synthesize(workspace, **body):
    client, app, pid, _ = workspace
    response = client.post("/api/projects/" + pid + "/synthesis/runs", json=body)
    assert response.status_code == 200, response.text
    done = wait(app.state.store, response.json()["id"])
    assert done["state"] == "finished", done["result"].get("error")
    return done["result"]


VAT = ("import sys\nfrom decimal import Decimal, ROUND_HALF_UP\n"
       "x = Decimal(sys.stdin.read().strip())\n"
       "print((x * Decimal('1.21')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))\n")
VAT_EXAMPLES = [{"x": 10, "output": 12.1}, {"x": 0.5, "output": 0.61}, {"x": 33.3, "output": 40.29},
                {"x": 7, "output": 8.47}, {"x": 100, "output": 121}, {"x": 2.5, "output": 3.03}]


def test_round_half_up_rule_is_recovered_and_validated_against_the_reference(workspace):
    ref = program(workspace[3], "vat.py", VAT)
    result = synthesize(workspace, examples=VAT_EXAMPLES, reference={"argv": ref}, seed=3,
                        domain={"x": {"kind": "decimals", "min": 0, "max": 500, "places": 1}}, samples=25)
    summary = result["summary"]
    assert summary["status"] == "validated_against_reference", summary
    expr = Expression(summary["expression"], ("x",))
    assert "round_half_up" in summary["expression"] and "1.21" in summary["expression"]
    assert expr.evaluate({"x": 0.5}) == 0.61 and expr.evaluate({"x": 1.5}) == 1.82
    assert summary["validation"]["reference_runs"] >= 25 and summary["validation"]["inputs_checked"] >= 25
    assert len(summary["examples_used"]) >= 6
    assert "evidence" in summary["note"]


def test_piecewise_rule_is_recovered(workspace):
    examples = [{"x": v, "output": o} for v, o in [(50, 50), (99, 99), (101, 90.9), (150, 135), (300, 270), (10, 10), (200, 180)]]
    ref = program(workspace[3], "disc.py", "import sys\nx=float(sys.stdin.read())\nprint(x*0.9 if x>100 else x)\n")
    result = synthesize(workspace, examples=examples, reference={"argv": ref},
                        domain={"x": {"kind": "decimals", "min": 0, "max": 400, "places": 1}}, samples=20)["summary"]
    assert result["status"] == "validated_against_reference", result
    expr = Expression(result["expression"], ("x",))
    assert expr.evaluate({"x": 100}) == 100 and abs(expr.evaluate({"x": 100.5}) - 90.45) < 1e-9
    assert " if " in result["expression"]


def test_cegis_turns_a_disagreement_into_a_new_example(workspace):
    # The examples never reach the threshold; the reference changes behaviour above 1000.
    ref = program(workspace[3], "cap.py", "import sys\nx=int(sys.stdin.read())\nprint(x*2 if x<=1000 else 2000)\n")
    examples = [{"x": v, "output": v * 2} for v in (1, 5, 20, 40)]
    result = synthesize(workspace, examples=examples, reference={"argv": ref}, seed=2,
                        domain={"x": {"kind": "integers", "min": 0, "max": 3000}}, samples=14, max_rounds=10,
                        time_budget_seconds=90)["summary"]
    assert result["examples_added_by_validation"], "the reference must have contradicted the first candidate"
    assert result["validation"]["rounds"] >= 2
    assert result["status"] == "validated_against_reference", result
    expr = Expression(result["expression"], ("x",))
    assert expr.evaluate({"x": 2500}) == 2000 and expr.evaluate({"x": 300}) == 600


def test_rejected_outputs_exclude_consistent_but_wrong_expressions(workspace):
    result = synthesize(workspace, examples=[{"x": 2, "output": 4}, {"x": 3, "output": 6}, {"x": 5, "output": 10}],
                        rejected=[{"input": {"x": 4}, "output": 16}])["summary"]
    assert result["status"] == "consistent_with_examples"
    assert Expression(result["expression"], ("x",)).evaluate({"x": 4}) == 8
    assert result["rejected_outputs"]


def test_impossible_case_returns_closest_candidates_with_counterexamples(workspace):
    examples = [{"x": v, "output": o} for v, o in [(1, 7), (2, 3), (3, 11), (4, 2), (5, 13), (6, 5)]]
    result = synthesize(workspace, examples=examples, max_size=5, time_budget_seconds=10)["summary"]
    assert result["status"] in {"no_expression_found", "budget_exhausted"}
    assert result["expression"] is None
    assert result["closest_candidates"]
    best = result["closest_candidates"][0]
    assert best["matches"] < best["of"] and best["counterexamples"]
    assert {"input", "expected", "got"} <= set(best["counterexamples"][0])


def test_string_rule_and_callable_reference(workspace):
    mod = workspace[3] / "refmod.py"
    mod.write_text("def clean(s):\n    return s.strip().lower()\n", encoding="utf-8")
    examples = [{"s": "  Ab ", "output": "ab"}, {"s": "XY", "output": "xy"}, {"s": " q", "output": "q"}]
    result = synthesize(workspace, examples=examples, reference={"callable": "refmod:clean", "path": str(workspace[3])},
                        domain={"s": {"kind": "text", "max_len": 6, "alphabet": "aBc  "}}, samples=20)["summary"]
    assert result["status"] == "validated_against_reference", result
    assert Expression(result["expression"], ("s",)).evaluate({"s": " ZzZ  "}) == "zzz"


def test_synthesised_expression_is_saved_as_a_hypothesis_rule_until_checked(workspace):
    client, app, pid, tmp = workspace
    ref = program(tmp, "vat.py", VAT)
    result = synthesize(workspace, examples=VAT_EXAMPLES, reference={"argv": ref}, seed=3,
                        domain={"x": {"kind": "decimals", "min": 0, "max": 500, "places": 1}}, samples=15,
                        save_rule={"statement": "Prices carry 21 percent VAT rounded half up to cents.",
                                   "evidence": [{"file": "billing.cbl", "function": "ADD-VAT"}]})
    saved = result["rule"]
    assert saved["status"] == "hypothesis" and saved["has_check"]
    rule = client.get("/api/projects/%s/rules/%s" % (pid, saved["rule_id"])).json()
    assert rule["status"] == "hypothesis" and "synthesized" in rule["tags"]
    assert rule["check"]["predicate"].startswith("abs(number(stdout)")
    job = client.post("/api/projects/%s/rules/checks" % pid, json={"rule_id": saved["rule_id"]}).json()
    done = wait(app.state.store, job["id"])
    assert done["state"] == "finished"
    assert done["result"]["summary"]["verdict"] == "all_held", done["result"]["summary"]
    assert client.get("/api/projects/%s/rules/%s" % (pid, saved["rule_id"])).json()["status"] == "observed"


def test_validation_of_inputs_and_tool_registration(workspace):
    client, app, pid, _ = workspace
    bad = client.post("/api/projects/%s/synthesis/runs" % pid, json={"examples": [{"x": 1}]})
    assert bad.status_code >= 400
    bad = client.post("/api/projects/%s/synthesis/runs" % pid, json={"examples": [{"len": 1, "output": 2}]})
    assert bad.status_code >= 400
    from theseus.api import TOOLS
    assert {"theseus_synthesize", "theseus_property_run"} <= {t["name"] for t in TOOLS}
