import sys
import time

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.expressions import Expression, ExpressionError

NAMES = ("stdin", "stdout", "exit_code", "value")


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
        project = app.state.store.create_project("Rules")
        yield client, app, project["id"], tmp_path


def program(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return [sys.executable, str(path)]


def save(workspace, **body):
    client, _, pid, _ = workspace
    response = client.post("/api/projects/" + pid + "/rules", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def check(workspace, rule_id, **options):
    client, app, pid, _ = workspace
    job = client.post("/api/projects/" + pid + "/rules/checks", json={"rule_id": rule_id, **options}).json()
    done = wait(app.state.store, job["id"])
    assert done["state"] == "finished", done["result"].get("error")
    return done["result"]


DISCOUNT = ("import sys\nn=int(sys.stdin.read())\nprint(n*90//100 if n>=100 else n)\n")
EVIDENCE = [{"file": "billing.cbl", "lines": "120-134", "function": "APPLY-DISCOUNT", "note": "10 percent over 100"}]


def test_hypothesis_is_promoted_to_observed_only_by_executed_cases(workspace):
    ref = program(workspace[3], "ref.py", DISCOUNT)
    rule = save(workspace, statement="An order total never increases after the discount is applied.", title="No increase",
                evidence=EVIDENCE, check={"reference": {"argv": ref}, "predicate": "int(stdout) <= int(stdin)",
                                          "cases": [{"name": "small", "stdin": "50"}, {"name": "big", "stdin": "200"}],
                                          "generators": [{"kind": "integers", "count": 8, "seed": 3, "template": {"stdin": "{value}"}}]})
    assert rule["status"] == "hypothesis" and rule["history"][0]["reason"] == "proposed"
    result = check(workspace, rule["id"], )
    # negative generated integers are rejected by nothing here: -1 -> -1 holds, so all cases hold
    assert result["summary"]["verdict"] == "all_held"
    after = workspace[0].get("/api/projects/%s/rules/%s" % (workspace[2], rule["id"])).json()
    assert after["status"] == "observed"
    assert [h["to"] for h in after["history"]] == ["hypothesis", "observed"]
    assert after["examples"] and after["examples"][0]["source"] == "rules_check"
    assert "not proof" in result["scope"] or "not a proof" in result["scope"]


def test_contradicted_with_minimal_counterexample(workspace):
    ref = program(workspace[3], "ref.py", DISCOUNT)
    rule = save(workspace, statement="Every order of 100 or more is discounted below its total.",
                check={"reference": {"argv": ref}, "predicate": "int(stdout) < int(stdin)", "when": "int(stdin) >= 0",
                       "generators": [{"kind": "integers", "count": 30, "seed": 1, "template": {"stdin": "{value}"}}]})
    result = check(workspace, rule["id"], shrink_budget=200)
    summary = result["summary"]
    assert summary["verdict"] == "contradicted"
    assert summary["first_contradiction"]["observed"]["stdout"].strip() == summary["first_contradiction"]["observed"]["stdin"].strip()
    shrunk = summary["shrunk"]
    assert shrunk["reexecuted_and_confirmed"]
    assert abs(int(shrunk["minimal_value"])) <= abs(int(shrunk["original_value"]))
    assert 0 <= int(shrunk["minimal_value"]) < 100  # smallest value that still breaks "discounted below total"
    stored = workspace[0].get("/api/projects/%s/rules/%s" % (workspace[2], rule["id"])).json()
    assert stored["status"] == "contradicted"
    assert stored["counterexamples"][0]["source"] == "rules_check"
    assert stored["history"][-1]["to"] == "contradicted"
    # editing the check resets to hypothesis
    again = save(workspace, statement=stored["statement"], rule_id=rule["id"],
                 check={"reference": {"argv": ref}, "predicate": "int(stdout) <= int(stdin)", "cases": [{"stdin": "5"}]})
    assert again["status"] == "hypothesis" and again["history"][-1]["reason"].startswith("executable check changed")


def test_status_cannot_be_asserted_and_rules_without_check_cannot_run(workspace):
    client, _, pid, _ = workspace
    with pytest.raises(ValueError):
        workspace[1].state.rules.save(pid, "A rule", status="observed")
    rule = save(workspace, statement="No check here")
    with pytest.raises(ValueError):
        workspace[1].state.rules.start(pid, rule["id"])


def test_inconclusive_when_nothing_applies(workspace):
    ref = program(workspace[3], "ref.py", DISCOUNT)
    rule = save(workspace, statement="r", check={"reference": {"argv": ref}, "predicate": "True and stdout != ''",
                                                  "when": "int(stdin) > 1000", "cases": [{"stdin": "5"}]})
    result = check(workspace, rule["id"])
    assert result["summary"]["verdict"] == "inconclusive" and result["summary"]["skipped"] == 1
    assert workspace[0].get("/api/projects/%s/rules/%s" % (workspace[2], rule["id"])).json()["status"] == "hypothesis"


@pytest.mark.parametrize("source", [
    "stdin.upper",                       # attribute access
    "__import__('os').system('x')",      # call outside whitelist
    "open('f')",                         # unknown function
    "(lambda: 1)()",                     # lambda
    "[c for c in stdin]",                # comprehension
    "stdin.__class__",                   # dunder attribute
    "len(stdin, key=1)",                 # keyword argument
    "secret + 1",                        # unknown name
    "eval('1')",                         # eval
    "f'{stdin}'",                        # f-string
    "2 ** 100000 > 1",                   # parses, rejected at evaluation
])
def test_expression_sandbox_rejects_unsafe_code(source):
    with pytest.raises(ExpressionError):
        Expression(source, NAMES).evaluate({"stdin": "a", "stdout": "", "exit_code": 0, "value": ""})


def test_expression_language_supports_the_documented_operations():
    env = {"stdin": " 2.5 ", "stdout": "3\n", "exit_code": 0, "value": "x"}
    run = lambda s: Expression(s, NAMES).evaluate(env)
    assert run("round_half_up(strip(stdin)) == int(strip(stdout))")
    assert run("round_half_even(strip(stdin)) == 2")
    assert run("regex_match('[0-9]+', strip(stdout)) and exit_code == 0 and len(lines(stdout)) == 1")
    assert run("upper(strip(stdin)) == '2.5' if exit_code == 0 else False")
    assert run("number(stdin) * 2 == 5 and abs(-3) == 3 and 'x' in value")
    with pytest.raises(ExpressionError):
        run("int('abc')")  # data errors surface as expression errors


def test_invalid_predicate_is_rejected_when_saving(workspace):
    ref = program(workspace[3], "ref.py", DISCOUNT)
    response = workspace[0].post("/api/projects/%s/rules" % workspace[2], json={
        "statement": "s", "check": {"reference": {"argv": ref}, "predicate": "stdout.strip() == ''", "cases": [{"stdin": "1"}]}})
    assert response.status_code == 400 and "attribute" in response.text


def test_markdown_export(workspace):
    ref = program(workspace[3], "ref.py", DISCOUNT)
    ok = save(workspace, statement="A discounted total is never above the original.", title="No increase", evidence=EVIDENCE,
              check={"reference": {"argv": ref}, "predicate": "int(stdout) <= int(stdin)", "cases": [{"stdin": "150"}]})
    check(workspace, ok["id"])
    bad = save(workspace, statement="Every total is reduced.", evidence=[{"artifact": "legacy.exe", "function": "sub_401000"}],
               check={"reference": {"argv": ref}, "predicate": "int(stdout) < int(stdin)", "cases": [{"stdin": "7"}]})
    check(workspace, bad["id"])
    save(workspace, statement="Discount tiers are cumulative.", examples=["two orders of 100"])
    client, _, pid, _ = workspace
    markdown = client.post("/api/projects/%s/rules/export" % pid, json={}).json()
    text = markdown["markdown"]
    assert markdown["rules"] == 3
    assert "1 observed, 1 hypothesis, 1 contradicted" in text
    assert "**Status:** observed" in text and "**Status:** contradicted" in text and "**Status:** hypothesis" in text
    assert "billing.cbl function APPLY-DISCOUNT, lines 120-134" in text
    assert "legacy.exe" in text and "**Counterexample:**" in text and "input `7`" in text
    only = client.post("/api/projects/%s/rules/export" % pid, json={"statuses": ["observed"]}).json()
    assert only["rules"] == 1 and "Every total is reduced" not in only["markdown"]


def test_tools_registered_and_dispatched(workspace):
    from theseus.api import TOOLS
    names = {t["name"] for t in TOOLS}
    assert {"theseus_rules_save", "theseus_rules_read", "theseus_rules_check", "theseus_rules_export",
            "theseus_repro_create", "theseus_repro_verify"} <= names
