import json
from pathlib import Path
import sys
import time

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app


def wait(store, job_id):
    deadline = time.monotonic() + 20
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
        store = app.state.store
        project = store.create_project("Boundary rule")
        reader, builder = tmp_path / "reader", tmp_path / "builder"
        reader.mkdir(); builder.mkdir()
        reference, candidate = reader / "reference.py", builder / "candidate.py"
        source = "import sys\nn=int(sys.stdin.read())\nprint(n+128 if 0<=n<10 else -1)\n"
        reference.write_text(source)
        candidate.write_text(source)
        artifact = store.add_artifact(project["id"], str(reference))
        finding = store.add_finding(project["id"], artifact["id"], "lines 2-3", "For 0 through 9 return input plus 128; otherwise -1")
        store.update_project(project["id"], specification="Integer stdin. Return n+128 for 0<=n<10, otherwise -1, followed by a newline.")
        yield client, app, project["id"], reference, candidate, finding


def scenario(store, project_id, reference, candidate, number, scenario_id=""):
    return store.save_scenario(project_id, str(number), {
        "reference": [sys.executable, str(reference)], "candidate": [sys.executable, str(candidate)],
        "stdin": str(number), "expected_stdout": str(number+128 if 0 <= number < 10 else -1) + "\n"}, scenario_id)


def test_complete_reader_builder_oracle_retry_with_open_question_and_stale_code(workspace):
    client, app, pid, reference, candidate, finding = workspace
    store, flow = app.state.store, app.state.workflow
    cases = [scenario(store, pid, reference, candidate, n) for n in (-1, 0, 9, 10)]
    unknown = flow.save_claim(pid, "unknown", "Are decimal strings accepted?")
    obligation = flow.save_claim(pid, "obligation", "Integer boundaries", scenario_ids=[row["id"] for row in cases], owner="builder")
    handoff = flow.handoff(pid, str(candidate.parent), [finding["id"]])
    builder_doc = flow.read_handoff(pid, handoff["id"], True)
    assert str(reference) not in json.dumps(builder_doc)
    assert "reader_evidence" not in builder_doc and "observation" not in json.dumps(builder_doc)
    before = reference.read_bytes()
    candidate.write_text("import sys\nn=int(sys.stdin.read())\nprint(n+256 if 0<=n<10 else -1)\n")
    wrong = wait(store, flow.verify(pid, handoff["id"])["id"])
    assert wrong["result"]["failed"] == 2
    assert flow.read(pid)["claims"][1]["status"] == "different"
    candidate.write_bytes(before)
    assert flow.read(pid)["claims"][1]["status"] == "unknown"  # previous binary identity is stale
    good = wait(store, flow.verify(pid, handoff["id"])["id"])
    assert good["result"]["passed"] == 4
    assert good["result"]["reconstruction"]["handoff_sha256"] == handoff["sha256"]
    assert not flow.read(pid)["complete"]  # untested oracle and unresolved question
    variants = []
    for name, body in [("constant", "n+256 if 0<=n<10 else -1"),
                       ("branch", "-1 if 0<=n<10 else n+128"),
                       ("boundary", "n+128 if 0<=n<=10 else -1")]:
        path = candidate.parent / (name + ".py")
        path.write_text("import sys\nn=int(sys.stdin.read())\nprint(" + body + ")\n")
        variants.append({"name": name, "candidate": [sys.executable, str(path)]})
    sensitivity = wait(store, flow.selftest(pid, variants)["id"])
    assert sensitivity["state"] == "finished", sensitivity
    assert sensitivity["result"]["detected"] == ["constant", "branch", "boundary"]
    assert sensitivity["result"]["sensitive"]
    read = flow.read(pid)
    assert read["claims"][1]["complete"] and not read["complete"]
    flow.save_claim(pid, "unknown", unknown["statement"], claim_id=unknown["id"],
                    resolution="Decimal strings remain outside the integer contract.", finding_ids=[finding["id"]])
    assert flow.read(pid)["complete"]
    store.update_project(pid, specification="Newer contract with decimal inputs")
    retry = wait(store, flow.verify(pid, handoff["id"])["id"])
    assert retry["result"]["reconstruction"]["specification_changed"]
    assert flow.read_handoff(pid, handoff["id"], True) == builder_doc
    assert flow.read(pid)["handoffs"][0]["specification_changed"]
    assert reference.read_bytes() == before
    exported = client.get(f"/api/projects/{pid}/export").json()
    assert exported["workflow"]["claims"][0]["resolution"]


def test_weak_oracle_survives_and_new_boundary_invalidates_old_evidence(workspace):
    client, app, pid, reference, candidate, finding = workspace
    flow, store = app.state.workflow, app.state.store
    case = scenario(store, pid, reference, candidate, 0)
    mutant = candidate.parent / "upper.py"
    mutant.write_text("import sys\nn=int(sys.stdin.read())\nprint(n+128 if 0<=n<=10 else -1)")
    variants = [{"name": "upper boundary", "candidate": [sys.executable, str(mutant)]}]
    flow.save_claim(pid, "obligation", "Boundary", scenario_ids=[case["id"]])
    wait(store, app.state.comparisons.start(pid)["id"])
    job = wait(store, flow.selftest(pid, variants)["id"])
    assert job["result"]["survived"] == ["upper boundary"]
    assert flow.read(pid)["claims"][0]["status"] == "verified"
    assert not flow.read(pid)["complete"]
    scenario(store, pid, reference, candidate, 10, case["id"])
    assert flow.read(pid)["claims"][0]["status"] == "unknown"
    checked = wait(store, flow.selftest(pid, variants)["id"])
    assert checked["result"]["sensitive"]
    assert not flow.read(pid)["complete"]  # no candidate comparison for revised input
    wait(store, app.state.comparisons.start(pid)["id"])
    assert flow.read(pid)["complete"]
    reference.write_text("print(777)")
    assert not flow.read(pid)["complete"]


def test_api_mcp_surface_foreign_dependencies_invalid_reference_and_persistence(workspace):
    client, app, pid, reference, candidate, finding = workspace
    flow, store = app.state.workflow, app.state.store
    case = scenario(store, pid, reference, candidate, 0)
    def call(tool, **arguments):
        response = client.post("/api/agent/call", json={"tool": tool, "arguments": {"project_id": pid, **arguments}})
        assert response.status_code == 200, response.text
        return response.json()["result"]
    claim = call("theseus_claim_save", kind="obligation", statement="Original boundary", scenario_ids=[case["id"]])
    dependent = flow.save_claim(pid, "unknown", "Depends", depends_on=[claim["id"]])
    with pytest.raises(ValueError, match="cycle"):
        flow.save_claim(pid, "obligation", "Cycle", claim_id=claim["id"], depends_on=[dependent["id"]])
    foreign = store.create_project("Foreign")
    with pytest.raises(ValueError, match="foreign"):
        flow.save_claim(foreign["id"], "unknown", "Foreign", finding_ids=[finding["id"]])
    receipt = call("theseus_handoff_create", builder_directory=str(candidate.parent))
    assert call("theseus_handoff_read", handoff_id=receipt["id"], builder_only=True)["specification"]
    reference.write_text("print(999)")
    failed = call("theseus_oracle_selftest", variants=[{"name": "wrong", "candidate": [sys.executable, str(candidate)]}])
    failed = wait(store, failed["id"])
    assert failed["state"] == "failed" and "Reference fails" in failed["result"]["error"]
    assert not call("theseus_workflow_read")["complete"]
    from theseus.comparison import Comparisons
    from theseus.store import Store
    from theseus.workflow import Workflow
    manager = Comparisons(Store(store.directory))
    try:
        restored = Workflow(manager)
        assert len(restored.read(pid)["claims"]) == 2
        assert restored.read_handoff(pid, receipt["id"]) == receipt
    finally:
        manager.shutdown()


def test_broken_mutant_is_invalid_instead_of_detecting_a_defect(workspace):
    client, app, pid, reference, candidate, finding = workspace
    scenario(app.state.store, pid, reference, candidate, 0)
    broken = [sys.executable, "-c", "this is not Python syntax !!!"]
    job = wait(app.state.store, app.state.workflow.selftest(pid, [{"name": "broken", "candidate": broken}])["id"])
    assert job["result"]["invalid"] == ["broken"]
    assert not job["result"]["sensitive"]


def test_newer_surviving_mutant_supersedes_an_earlier_sensitive_suite(workspace):
    client, app, pid, reference, candidate, finding = workspace
    flow, store = app.state.workflow, app.state.store
    case = scenario(store, pid, reference, candidate, 0)
    flow.save_claim(pid, "obligation", "Integer rule", scenario_ids=[case["id"]])
    wait(store, app.state.comparisons.start(pid)["id"])
    constant = candidate.parent / "constant.py"
    constant.write_text("print(256)")
    wait(store, flow.selftest(pid, [{"name": "constant", "candidate": [sys.executable, str(constant)]}])["id"])
    assert flow.read(pid)["complete"]
    boundary = candidate.parent / "boundary.py"
    boundary.write_text("import sys\nn=int(sys.stdin.read())\nprint(n+128 if 0<=n<=10 else -1)")
    weak = wait(store, flow.selftest(pid, [{"name": "boundary", "candidate": [sys.executable, str(boundary)]}])["id"])
    assert weak["result"]["survived"] == ["boundary"]
    assert not flow.read(pid)["complete"]
