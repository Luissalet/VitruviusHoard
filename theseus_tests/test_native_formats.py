import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

from fastapi.testclient import TestClient
import pytest

from native_fixtures import dart_elf, electron_image, evm_bytecode, go_image, keyed_archive, macho_image, nib_archive, rust_image
from theseus.api import create_app
from theseus.native_analysis import ENGINE, engine
from test_native_analysis import wait


def inspect(tmp_path, operation, content, parameters=None, expected_state="finished"):
    if not engine()["available"]:
        pytest.skip("Build the native analysis core first")
    source = tmp_path / "input.bin"
    source.write_bytes(content)
    app = create_app(tmp_path / "data")
    with TestClient(app, base_url="http://127.0.0.1:5217") as client:
        client.get("/")
        project = client.post("/api/projects", json={"name": operation}).json()
        base = "/api/projects/" + project["id"]
        artifact = client.post(base + "/artifacts", json={"path": str(source)}).json()
        response = client.post(base + "/artifacts/" + artifact["id"] + "/analyses", json={"operation": operation, "parameters": parameters or {}})
        response.raise_for_status()
        job = wait(client, response.json())
        assert source.read_bytes() == content
        assert job["state"] == expected_state, job
        if expected_state != "finished":
            return job
        assert job["result"]["artifact_sha256"] == hashlib.sha256(content).hexdigest()
        document = client.get("/api/jobs/" + job["id"] + "/analysis.json").json()
        assert document["artifact_sha256"] == artifact["sha256"]
        return document["result"]


def test_go_modules_keep_exact_build_locations(tmp_path):
    content = go_image()
    result = inspect(tmp_path, "go.build", content)
    assert result["build_info"]["go_version"] == "go1.fixture"
    assert result["build_info"]["header_offset"] == 512
    assert result["module"]["complete"], result
    assert result["module"]["path"] == "fixture.local/gauge"
    location = result["build_info"]["version_location"]
    assert content[location["offset"]:location["offset"] + location["bytes"]] == b"go1.fixture"


def test_rust_auditable_graph_and_original_offsets(tmp_path):
    result = inspect(tmp_path, "rust.dependencies", rust_image())
    metadata = result["auditable_metadata"]
    assert [row["name"] for row in metadata["packages"]] == ["gauge", "units"]
    assert metadata["dependency_edges"] == [{"from_index": 0, "to_index": 1}]
    assert metadata["file_offset"] == 512 and metadata["root_package_index"] == 0


def test_electron_fuses_use_original_bytes(tmp_path):
    result = inspect(tmp_path, "electron.fuses", electron_image())
    assert result["format"] == "pe"
    assert result["slices"] and "RunAsNode" in json.dumps(result)
    assert "disabled" in json.dumps(result) and "enabled" in json.dumps(result)


def test_macho_load_commands_on_windows(tmp_path):
    result = inspect(tmp_path, "apple.macho", macho_image())
    assert result["status"] == "parsed", result
    assert len(result["slices"]) == 1
    assert "@loader_path/Frameworks" in json.dumps(result)
    assert "@rpath/Fixture.dylib" in json.dumps(result)


@pytest.mark.parametrize("binary", [True, False])
def test_keyed_archive_keeps_shared_cyclic_identity(tmp_path, binary):
    result = inspect(tmp_path, "apple.keyed_archive", keyed_archive(binary))
    assert result["archive_format"] == ("binary-plist" if binary else "xml-plist")
    assert any(row["class_name"] == "GaugeView" for row in result["objects"])
    assert "Año" in json.dumps(result, ensure_ascii=False)
    assert any(row["source"] == 1 and row["target"] == 1 for row in result["references"])


def test_compiled_nib_objects_and_outlet_reference(tmp_path):
    result = inspect(tmp_path, "apple.nib", nib_archive())
    assert result["object_count"] == 2 and result["connection_object_count"] == 1
    assert result["objects"][1]["values"]["destination"] == {"$nib_object_ref": 0}


@pytest.mark.parametrize("encoding", ["raw", "hex"])
def test_local_evm_selector_disassembly_and_compiler_metadata(tmp_path, encoding):
    content = evm_bytecode()
    carrier = content if encoding == "raw" else ("0x" + content.hex() + "\n").encode()
    result = inspect(tmp_path, "evm.interface", carrier, {"encoding": encoding})
    assert any(row["selector"] == "deadbeef" for row in result["functions"])
    assert result["instructions"] and result["controlFlowGraph"]["blocks"]
    assert result["solidity_metadata"]["compiler_version"]["value"] == "0.8.1"
    assert result["bytecode_sha256"] == hashlib.sha256(content).hexdigest()


def test_wasm_static_interface_and_preserved_definitions(tmp_path):
    if not engine()["available"]:
        pytest.skip("Build the native analysis core first")
    output = tmp_path / "fixture.wasm"
    script = "import wabtFactory from 'wabt'; import {writeFileSync} from 'node:fs'; const wabt=await wabtFactory(); const m=wabt.parseWat('fixture.wat','(module (import \"env\" \"record\" (func $record (param i32))) (func $double (export \"double\") (param $n i32) (result i32) local.get $n i32.const 2 i32.mul) (memory (export \"memory\") 1))'); writeFileSync(process.argv[1],Buffer.from(m.toBinary({write_debug_names:true}).buffer));m.destroy();"
    subprocess.run([engine()["node"], "--input-type=module", "-e", script, str(output)], cwd=ENGINE, check=True, capture_output=True)
    result = inspect(tmp_path, "wasm.artifact", output.read_bytes())
    assert "i32.mul" in result["wat"]
    assert any("double" in row["definition"] for row in result["definitions"])
    assert '"record"' in " ".join(result["imports"])
    assert any(row.get("name") == "double" for row in result["interface_entries"]), result["interface_entries"]


def test_dart_elf_build_id_symbols_and_snapshot_header(tmp_path):
    result=inspect(tmp_path,"flutter.elf",dart_elf())
    assert result['build_ids']==[b'gauge779'.hex()]
    assert len(result['symbols'])==2
    assert len(result['snapshots'])==2
    assert all(row['complete'] and row['kind']==3 and row['hash']=='1234567890abcdef1234567890abcdef' for row in result['snapshots'])


@pytest.mark.parametrize("operation,content,parameters,diagnostic", [
    ("rust.dependencies",rust_image(trailing=True),{},"bytes after the zlib stream"),
    ("evm.interface",b"0x012",{"encoding":"hex"},"complete hexadecimal byte pairs"),
    ("apple.nib",b"NIBArchive",{},"magic or header is invalid"),
])
def test_malformed_formats_keep_failed_receipt(tmp_path,operation,content,parameters,diagnostic):
    job=inspect(tmp_path,operation,content,parameters,expected_state="failed")
    assert diagnostic in job['result']['execution']['stderr']
