import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import sys
import time
import zipfile

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.comparison import Comparisons
from theseus.inspection import inspect_file, excerpt
from theseus.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


def program(text):
    return [sys.executable, "-c", text]


def wait(store, job_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = store.job(job_id)
        if job["state"] not in {"queued", "running"}:
            return job
        time.sleep(.02)
    raise AssertionError("Comparison did not reach a terminal state")


def test_python_observations_do_not_execute_source(tmp_path):
    marker = tmp_path / "must-not-exist"
    path = tmp_path / "árbol.py"
    path.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\ndef double(n):\n return n * 2\n", encoding="utf-8")
    result = inspect_file(path)
    assert not marker.exists()
    assert result["format"] == "python"
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["symbols"][0]["name"] == "double"
    assert result["symbols"][0]["line"] == 3


def test_har_is_read_without_requesting_its_urls(tmp_path):
    path = tmp_path / "capture.har"
    path.write_text(json.dumps({"log": {"entries": [{"request": {"method": "POST", "url": "http://127.0.0.1:1/not-requested", "postData": {"text": "input"}}, "response": {"status": 201, "content": {"text": "saved"}}}]}}))
    result = inspect_file(path)
    assert result["format"] == "har"
    assert result["requests"][0]["location"] == "log.entries[0]"
    assert result["requests"][0]["response_body"]["text"] == "saved"


def test_source_map_retains_embedded_source(tmp_path):
    path = tmp_path / "app.js.map"
    path.write_text(json.dumps({"version": 3, "sources": ["original.ts"], "names": ["save"], "mappings": "AAAA", "sourcesContent": ["function save() {}"]}))
    result = inspect_file(path)
    assert result["format"] == "source-map"
    assert result["sources_content"] == ["function save() {}"]


def test_zip_member_can_be_read_without_extracting_paths(store, tmp_path):
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../outside.py", "print('árbol')")
    project = store.create_project("Archive")
    artifact = store.add_artifact(project["id"], source)
    read = excerpt(artifact, member="../outside.py")
    assert "árbol" in read["text"]
    assert not (tmp_path / "outside.py").exists()


def test_asar_pickle_header_uses_the_documented_payload_offset(store, tmp_path):
    payload = b"module.exports = 73129;\n"
    header = json.dumps({"files": {"lib": {"files": {"index.js": {"offset": "0", "size": len(payload)}}}}}).encode()
    padded = (len(header) + 3) // 4 * 4
    archive = struct.pack("<4I", 4, padded + 8, padded + 4, len(header)) + header + b"\0" * (padded - len(header)) + payload
    source = tmp_path / "app.asar"
    source.write_bytes(archive)
    project = store.create_project("Electron")
    artifact = store.add_artifact(project["id"], source)
    assert artifact["inspection"]["members"][0]["offset"] == 16 + padded
    assert excerpt(artifact, member="lib/index.js")["text"] == payload.decode()


def test_sqlite_inspection_preserves_the_original(store, tmp_path):
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items(name TEXT)")
        db.execute("INSERT INTO items VALUES ('original')")
    before = path.read_bytes()
    project = store.create_project("Database")
    result = store.add_artifact(project["id"], path)
    assert result["inspection"]["format"] == "sqlite"
    assert result["inspection"]["observations"][0]["name"] == "items"
    assert path.read_bytes() == before


@pytest.mark.skipif(sys.platform != "win32", reason="Uses the installed Windows Python PE")
def test_real_pe_headers_and_imports_are_inspected():
    result = inspect_file(sys.executable)
    assert result["format"] == "pe"
    assert result["headers"]["entry_rva"] > 0
    assert result["sections"] and result["imports"]


def test_finding_keeps_original_hash_when_source_changes(store, tmp_path):
    source = tmp_path / "original.txt"
    source.write_text("first")
    project = store.create_project("Evidence", "What changed?")
    artifact = store.add_artifact(project["id"], source)
    finding = store.add_finding(project["id"], artifact["id"], "bytes 0–5", "first", "Initial version")
    assert finding["source_sha256"] == artifact["sha256"]
    source.write_text("second")
    assert excerpt(artifact)["source_changed"] is True
    assert excerpt(artifact)["current_sha256"] != artifact["sha256"]
    current = store.add_finding(project["id"], artifact["id"], "bytes 0–6", "second",
                                source_sha256=excerpt(artifact)["current_sha256"])
    assert current["source_sha256"] != finding["source_sha256"]
    assert store.artifact(project["id"], artifact["id"])["sha256"] == artifact["sha256"]
    store.update_project(project["id"], specification="See finding " + finding["id"])
    exported = store.export(project["id"])
    assert exported["findings"][0]["observation"] == "first"
    assert exported["artifacts"][0]["sha256"] == artifact["sha256"]


def test_artifact_finding_cannot_attach_to_another_project(store, tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("evidence")
    one, two = store.create_project("One"), store.create_project("Two")
    artifact = store.add_artifact(one["id"], source)
    with pytest.raises(LookupError):
        store.add_finding(two["id"], artifact["id"], "0", "evidence")


def test_json_comparison_is_reproducible_and_revision_does_not_rewrite_receipt(store):
    project = store.create_project("Compare")
    definition = {"reference": program("print('{\"a\":1,\"b\":2}')"),
                  "candidate": program("print('{\"b\":2,\"a\":1}')"), "mode": "json"}
    scenario = store.save_scenario(project["id"], "Key order", definition)
    comparisons = Comparisons(store)
    try:
        job = wait(store, comparisons.start(project["id"])["id"])
        assert job["state"] == "finished" and job["result"]["passed"] == 1
        frozen = job["result"]["definition_sha256"]
        store.save_scenario(project["id"], "Text now", {**definition, "mode": "text"}, scenario["id"])
        revised = wait(store, comparisons.start(project["id"])["id"])
        assert revised["result"]["failed"] == 1
        assert revised["result"]["definition_sha256"] != frozen
        assert store.job(job["id"])["result"]["definition_sha256"] == frozen
    finally:
        comparisons.shutdown()


def test_error_and_exit_differences_are_not_reported_as_equal(store):
    project = store.create_project("Exit")
    store.save_scenario(project["id"], "Exit differs", {
        "reference": program("import sys; print('same'); sys.exit(2)"),
        "candidate": program("print('same')")})
    comparisons = Comparisons(store)
    try:
        job = wait(store, comparisons.start(project["id"])["id"])
        assert job["result"]["failed"] == 1
        assert "exit_code differs" in job["result"]["cases"][0]["differences"]
    finally:
        comparisons.shutdown()


def test_failed_candidate_preserves_the_completed_reference(store):
    project = store.create_project("Partial")
    store.save_scenario(project["id"], "Missing candidate", {
        "reference": program("print('keep this observation')"),
        "candidate": ["missing-local-executable-73129.exe"]})
    comparisons = Comparisons(store)
    try:
        job = wait(store, comparisons.start(project["id"])["id"])
        assert job["state"] == "failed"
        assert job["result"]["partial_case"]["reference"]["stdout"] == "keep this observation\n"
    finally:
        comparisons.shutdown()


def test_cancelling_a_running_comparison_reaches_cancelled(store):
    project = store.create_project("Cancel")
    store.save_scenario(project["id"], "Wait", {"reference": program("import time; time.sleep(60)"), "candidate": program("print('done')")})
    comparisons = Comparisons(store)
    try:
        job = comparisons.start(project["id"])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not comparisons.processes:
            time.sleep(.02)
        comparisons.cancel(job["id"])
        assert wait(store, job["id"])["state"] == "cancelled"
    finally:
        comparisons.shutdown()


def test_restart_retains_partial_results_and_does_not_rerun_jobs(store):
    project = store.create_project("Recovery")
    store.save_job(project["id"], "interrupted-fixture", "running", {"partial_case": {"stdout": "already observed"}})
    reopened = Store(store.directory)
    result = reopened.job("interrupted-fixture")
    assert result["state"] == "interrupted"
    assert result["result"]["partial_case"]["stdout"] == "already observed"


def test_http_and_family_tools_share_the_same_project_and_specification(tmp_path):
    app = create_app(tmp_path / "api", port=64179)
    with TestClient(app, base_url="http://127.0.0.1:64179") as client:
        client.get("/")
        created = client.post("/api/projects", json={"name": "Native", "question": "Behavior?"})
        assert created.status_code == 200, created.text
        project = created.json()
        result = client.post("/api/agent/call", json={"tool": "theseus_specification_write", "arguments": {"project_id": project["id"], "content": "Local specification"}})
        assert result.status_code == 200, result.text
        read = client.get("/api/projects/" + project["id"]).json()
        assert read["project"]["specification"] == "Local specification"
        invalid = client.post("/api/agent/call", json={"tool": "theseus_project_update", "arguments": {"project_id": project["id"], "archived": "wrong type"}})
        assert invalid.status_code == 400
        assert client.post("/api/projects/" + project["id"] + "/artifacts", json={}).status_code == 422
        tools = client.get("/api/agent/tools").json()["tools"]
        assert len(tools) == 39
        assert any(tool['name'] == 'theseus_client_inspect' for tool in tools)
        assert {row["name"] for row in tools} >= {"theseus_binary_analysis", "theseus_analysis_start", "theseus_analysis_record", "theseus_runtime_catalog", "theseus_runtime_start"}
