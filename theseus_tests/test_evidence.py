import base64
import hashlib
import json
import sqlite3
import sys
import time

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.store import identifier
from theseus.workflow import fingerprint


def wait(store, key):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = store.job(key)
        if job["state"] not in {"queued", "running"}:
            assert job["state"] == "finished", job
            return job
        time.sleep(.01)
    raise AssertionError("Local receipt did not finish")


@pytest.fixture
def evidence(tmp_path):
    app = create_app(tmp_path / "source")
    with TestClient(app, base_url="http://127.0.0.1:5217") as client:
        client.get("/")
        store, flow = app.state.store, app.state.workflow
        pid = store.create_project("Límite documentado")["id"]
        path = tmp_path / "original.txt"
        path.write_text("Observed constant: 128", encoding="utf-8")
        artifact = store.add_artifact(pid, path)
        finding = store.add_finding(pid, artifact["id"], "byte 19", "Constant is 128",
                                    source_refs=[{"artifact_id": artifact["id"], "sha256": artifact["sha256"]}])
        store.update_project(pid, specification="Print 128 followed by a newline")
        command = [sys.executable, "-c", "print(128)"]
        case = store.save_scenario(pid, "Output", {"reference": command, "candidate": command,
                                                  "expected_stdout": "128\n"})
        claim = flow.save_claim(pid, "obligation", "Output constant", scenario_ids=[case["id"]], finding_ids=[finding["id"]])
        unknown = flow.save_claim(pid, "unknown", "Other inputs?", depends_on=[claim["id"]],
                                  resolution="Outside the specified scope", finding_ids=[finding["id"]])
        handoff = flow.handoff(pid, str(tmp_path), [finding["id"]])
        wait(store, flow.verify(pid, handoff["id"])["id"])
        wait(store, flow.selftest(pid, [{"name": "wrong constant", "candidate": [sys.executable, "-c", "print(256)"]}])["id"])
        assert flow.read(pid)["complete"]
        # Synthetic retained JSON exercises transport, not engine correctness.
        key = identifier()
        folder = store.directory / "analyses" / key
        folder.mkdir(parents=True)
        raw = '{\n "functions": [{"name":"árbol", "address":"0x100", "bytes":[128,0]}]\n}\n'.encode()
        target = folder / "analysis.json"
        target.write_bytes(raw)
        store.save_job(pid, key, "finished", {"kind": "native_analysis", "operation": "fixture",
            "artifact_id": artifact["id"], "artifact_sha256": artifact["sha256"],
            "analysis_file": str(target), "analysis_sha256": hashlib.sha256(raw).hexdigest()})
        store.index_analysis(key, json.loads(raw))
        bundle = app.state.evidence.export(pid)
        yield app, client, bundle, path, key, raw


def test_cross_store_roundtrip_retains_records_contracts_but_not_current_proof(evidence, tmp_path):
    app, client, bundle, original, analysis_id, raw = evidence
    destination = create_app(tmp_path / "destination")
    with TestClient(destination, base_url="http://127.0.0.1:5217") as reader:
        reader.get("/")
        # The destination has no source artifacts; import must not read them or run
        # any command, including commands valid only on the exporting machine.
        original.unlink()
        def forbidden(*args, **kwargs):
            raise AssertionError("Import attempted program execution")
        destination.state.comparisons._execute = forbidden
        result = reader.post("/api/agent/call", json={"tool": "theseus_evidence_import", "arguments": {"bundle": bundle, "name": "Transferred"}})
        assert result.status_code == 200, result.text
        receipt = result.json()["result"]
        pid, mapping = receipt["project"]["id"], receipt["id_map"]
        assert pid != bundle["payload"]["project"]["id"]
        assert receipt["project"]["name"] == "Transferred"
        read = reader.get(f"/api/projects/{pid}").json()
        assert len(read["artifacts"]) == 1 and len(read["jobs"]) == 3
        assert all(job["state"] == "imported" for job in read["jobs"])
        assert not read["workflow"]["complete"]
        assert read["workflow"]["claims"][0]["status"] == "unknown"
        assert read["workflow"]["claims"][1]["depends_on"] == [read["workflow"]["claims"][0]["id"]]
        assert read["findings"][0]["source_refs"][0]["artifact_id"] == read["artifacts"][0]["id"]
        saved = read["workflow"]["handoffs"][0]
        assert saved["builder"] == bundle["payload"]["handoffs"][0]["builder"]
        assert fingerprint(saved["builder"]) == saved["sha256"]
        assert saved["reader_evidence"][0]["id"] == read["findings"][0]["id"]
        assert not saved["claims_changed"]
        imported_id = mapping[analysis_id]
        assert reader.get(f"/api/jobs/{imported_id}/analysis.json").content == raw
        records = destination.state.store.analysis_records(imported_id, "functions", "árbol")
        assert records["total"] == 1 and records["sources"][0]["artifact_id"] == read["artifacts"][0]["id"]
        record = destination.state.store.analysis_record(imported_id, "functions", "0x100")
        assert record["record"]["bytes"] == [128, 0]
        assert reader.get(receipt["original_bundle"]).json() == bundle
        assert reader.get(receipt["id_map_url"]).json()["id_map"] == mapping
        reexport = reader.get(f"/api/projects/{pid}/evidence").json()
        assert base64.b64decode(reexport["payload"]["analysis_documents"][imported_id]["base64"]) == raw
        # Reimporting never overwrites either existing project.
        again = reader.post("/api/evidence/import", json={"bundle": reexport}).json()
        assert again["project"]["id"] != pid
        assert len(destination.state.store.projects()) == 2
        assert app.state.workflow.read(bundle["payload"]["project"]["id"])["complete"]


@pytest.mark.parametrize("corruption", ["payload", "document", "foreign", "missing", "duplicate", "cycle", "field"])
def test_invalid_bundles_leave_no_partial_project_or_files(evidence, tmp_path, corruption):
    _, _, bundle, _, analysis_id, _ = evidence
    destination = create_app(tmp_path / "destination")
    damaged = json.loads(json.dumps(bundle))
    payload = damaged["payload"]
    if corruption == "payload":
        payload["project"]["name"] = "Modified without new digest"
    elif corruption == "document":
        payload["analysis_documents"][analysis_id]["base64"] = base64.b64encode(b'{}').decode()
    elif corruption == "foreign":
        payload["findings"][0]["project_id"] = "other-project"
    elif corruption == "missing":
        payload["claims"][0]["scenario_ids"] = ["missing-scenario"]
    elif corruption == "duplicate":
        payload["artifacts"].append(payload["artifacts"][0])
    elif corruption == "cycle":
        payload["claims"][0]["depends_on"] = [payload["claims"][1]["id"]]
    else:
        del payload["jobs"][0]["created_at"]
    if corruption != "payload":
        damaged["manifest"]["sha256"] = fingerprint(payload)
    with TestClient(destination, base_url="http://127.0.0.1:5217") as reader:
        reader.get("/")
        result = reader.post("/api/evidence/import", json={"bundle": damaged})
        assert result.status_code == 400, result.text
        assert destination.state.store.projects() == []
        assert not (destination.state.store.directory / "imports").exists()
        assert not (destination.state.store.directory / "analyses").exists()


def test_changed_retained_document_is_declared_unavailable_not_exported(evidence):
    app, _, bundle, _, analysis_id, _ = evidence
    job = app.state.store.job(analysis_id)
    from pathlib import Path
    Path(job["result"]["analysis_file"]).write_text('{}')
    exported = app.state.evidence.export(bundle["payload"]["project"]["id"])
    assert not exported["payload"]["analysis_documents"]
    assert exported["manifest"]["unavailable_analyses"][0]["job_id"] == analysis_id
    assert exported["payload"]["analysis_records"]  # retained index still available


def test_database_failure_rolls_back_new_project_and_own_files(evidence, tmp_path):
    _, _, bundle, _, _, _ = evidence
    app = create_app(tmp_path / "destination")
    existing = app.state.store.create_project("Keep me")
    sentinel = app.state.store.directory / "analyses" / "untouched"
    sentinel.mkdir(parents=True)
    (sentinel / "proof.txt").write_text("existing")
    with app.state.store.db() as db:
        db.execute("CREATE TRIGGER reject_evidence BEFORE INSERT ON findings BEGIN SELECT RAISE(ABORT, 'test rollback'); END")
    with pytest.raises(sqlite3.IntegrityError):
        app.state.evidence.load(bundle)
    assert [row["id"] for row in app.state.store.projects()] == [existing["id"]]
    assert (sentinel / "proof.txt").read_text() == "existing"
    assert list((app.state.store.directory / "analyses").iterdir()) == [sentinel]
    assert not list((app.state.store.directory / "imports").iterdir())
