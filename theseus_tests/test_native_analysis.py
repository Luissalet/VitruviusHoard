import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.native_analysis import engine
from theseus.store import Store


@pytest.fixture
def managed_fixture(tmp_path):
    compiler = shutil.which("csc") or str(Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe"))
    if not Path(compiler).is_file() or not engine()["available"]:
        pytest.skip("Requires native analysis build and a C# compiler")
    source = Path(__file__).parent / "fixtures" / "ManagedFixture.cs"
    target = tmp_path / "fixture.dll"
    subprocess.run([compiler, "/nologo", "/target:library", "/optimize+", "/debug-", "/codepage:65001",
                    "/out:" + str(target), str(source)], check=True, capture_output=True)
    return target


def wait(client, job):
    deadline = time.monotonic() + 20
    while job["state"] in {"queued", "running"}:
        assert time.monotonic() < deadline, job
        time.sleep(.05)
        response = client.get("/api/jobs/" + job["id"])
        response.raise_for_status()
        job = response.json()
    return job


def test_managed_analysis_native_api_and_tool_records(tmp_path, managed_fixture):
    original = managed_fixture.read_bytes()
    app = create_app(tmp_path / "data")
    with TestClient(app, base_url="http://127.0.0.1:5217") as client:
        client.get("/")
        project = client.post("/api/projects", json={"name": "Managed evidence"}).json()
        base = "/api/projects/" + project["id"]
        artifact = client.post(base + "/artifacts", json={"path": str(managed_fixture)}).json()
        catalog = client.post("/api/agent/call", json={"tool": "theseus_analysis_catalog"}).json()["result"]
        assert catalog["engine"]["available"]
        assert {row["name"] for row in catalog["operations"]} >= {"managed.artifact", "managed.members", "managed.native_boundaries"}
        jobs = {}
        for operation in ("managed.artifact", "managed.members", "managed.native_boundaries"):
            response = client.post("/api/agent/call", json={"tool": "theseus_analysis_start", "arguments": {
                "project_id": project["id"], "artifact_id": artifact["id"], "operation": operation}})
            response.raise_for_status()
            job = wait(client, response.json()["result"])
            assert job["state"] == "finished", job
            assert job["result"]["artifact_sha256"] == hashlib.sha256(original).hexdigest()
            assert not job["result"]["source_changed"]
            assert "methods" not in job["result"]  # Polling is a compact receipt.
            jobs[operation] = job
        members = jobs["managed.members"]
        path = "/api/jobs/" + members["id"] + "/records/methods"
        first = client.get(path, params={"limit": 2}).json()
        assert len(first["records"]) == 2 and first["has_more"]
        remaining = client.get(path, params={"offset": 2, "limit": 100}).json()
        assert {r["record_key"] for r in first["records"]}.isdisjoint(r["record_key"] for r in remaining["records"])
        methods = []
        for header in first["records"] + remaining["records"]:
            record = client.post("/api/agent/call", json={"tool": "theseus_analysis_record", "arguments": {
                "job_id": members["id"], "section": "methods", "record_key": header["record_key"]}}).json()["result"]
            assert record["artifact_sha256"] == artifact["sha256"]
            methods.append(record["record"])
        document = client.get("/api/jobs/" + members["id"] + "/analysis.json").json()
        assert document["result"]["methods"] == methods
        instructions = [instruction for method in methods for instruction in method.get("body", {}).get("instructions", [])]
        assert len(instructions) > 40
        assert any(row["opcode"] == "ldc.r8" and row["operand"] == "128" for row in instructions)
        assert any(row["opcode"] == "ret" for row in instructions)
        for row in instructions:
            raw = bytes.fromhex(row["bytes"])
            assert original[row["file_offset"]:row["file_offset"] + len(raw)] == raw
        assert any(method.get("body", {}).get("exception_regions") for method in methods)
        native = client.get("/api/jobs/" + jobs["managed.native_boundaries"]["id"] + "/analysis.json").json()
        assert any(row.get("import_name") == "GetTickCount" for rows in native["result"].values() if isinstance(rows, list) for row in rows if isinstance(row, dict))
        bad = client.post(base + "/artifacts/" + artifact["id"] + "/analyses",
                          json={"operation": "managed.members", "parameters": {"method_offset": -1}})
        assert bad.status_code == 400
        assert managed_fixture.read_bytes() == original


def test_retained_record_search_and_restart(tmp_path):
    store = Store(tmp_path)
    project = store.create_project("Index")
    store.save_job(project["id"], "retained", "finished", {"artifact_id": "original", "artifact_sha256": "source"})
    store.index_analysis("retained", {"methods": [{"token": "1", "name": "Árbol"}, {"token": "2", "name": "Birch"}]})
    reopened = Store(tmp_path)
    result = reopened.analysis_records("retained", "methods", "ÁRBOL")
    assert result["total"] == 1 and result["records"][0]["record_key"] == "1"
    assert reopened.analysis_record("retained", "methods", "1")["record"]["name"] == "Árbol"
    with pytest.raises(LookupError):
        reopened.analysis_record("retained", "methods", "missing")
