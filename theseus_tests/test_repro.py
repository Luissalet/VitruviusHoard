import json
import os
from pathlib import Path
import subprocess
import sys
import time

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app

CRASH = ("import sys\nfor line in sys.stdin:\n    if line.strip() == 'BOOM':\n        raise ValueError('bad record')\n"
         "    if line.strip() == 'OTHER':\n        raise KeyError('other')\nprint('ok')\n")
FIXED = "import sys\nfor line in sys.stdin:\n    pass\nprint('fixed')\n"


def wait(store, job_id, seconds=120):
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
        project = app.state.store.create_project("Repro")
        yield client, app, project["id"], tmp_path


def program(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return [sys.executable, str(path)]


def create(workspace, report, **options):
    client, app, pid, _ = workspace
    job = client.post("/api/projects/%s/repro" % pid, json={"report": report, **options}).json()
    done = wait(app.state.store, job["id"])
    assert done["state"] == "finished", done["result"].get("error")
    return done["result"], job["id"]


def verify(workspace, **body):
    client, _, pid, _ = workspace
    response = client.post("/api/projects/%s/repro/verify" % pid, json=body)
    assert response.status_code == 200, response.text
    return response.json()["result"]


def lines(n, boom_at=137):
    return "".join(("BOOM\n" if i == boom_at else "record %d\n" % i) for i in range(n))


def test_crash_on_one_line_is_minimised_from_200_lines_and_bundle_runs(workspace):
    tmp = workspace[3]
    argv = program(tmp, "app.py", CRASH)
    result, job_id = create(workspace, {"command": {"argv": argv}, "stdin": lines(200), "env": {"UNUSED_FLAG": "1", "KEEP": "x"},
                                        "files": {"extra/notes.txt": "irrelevant", "data.csv": "a,b\n1,2\n"},
                                        "description": "Crash while importing a batch"})
    summary = result["summary"]
    assert summary["status"] == "reproduced_and_minimised"
    assert result["signature"]["exit_code"] == 1 and "ValueError" in result["signature"]["stderr_regex"]
    assert summary["minimal_stdin"].strip() == "BOOM"
    assert summary["files_after"] == 0 and summary["env_after"] == []
    assert summary["executions"] < 200 and summary["confirmed_on_minimal"]
    bundle = Path(result["bundle"]["directory"])
    for name in ("repro.json", "run.sh", "run.cmd", "expected_signature.json", "environment.json", "inputs/stdin.txt"):
        assert (bundle / name).is_file(), name
    manifest = json.loads((bundle / "repro.json").read_text(encoding="utf-8"))
    assert manifest["environment"]["python"] == sys.version.split()[0]
    assert "os" in manifest["environment"] and "input_sha256" in manifest["environment"]
    cmd = (bundle / "run.cmd").read_bytes().decode("utf-8")
    assert "xcopy" in cmd and "\r\n" in cmd and "stdin.txt" in cmd
    if os.name != "nt" and (Path("/bin/sh").exists()):
        done = subprocess.run(["/bin/sh", str(bundle / "run.sh")], capture_output=True, text=True, timeout=60)
        assert done.returncode == 1 and "ValueError" in done.stderr and "exit code: 1" in done.stdout
        fixed = program(tmp, "fixed.py", FIXED)
        ok = subprocess.run(["/bin/sh", str(bundle / "run.sh"), *fixed], capture_output=True, text=True, timeout=60)
        assert ok.returncode == 0 and "fixed" in ok.stdout
    assert verify(workspace, repro_id=job_id)["summary"]["verdict"] == "reproduces"


def test_minimisation_keeps_the_same_signature_not_another_error(workspace):
    tmp = workspace[3]
    argv = program(tmp, "app.py", CRASH)
    # Both BOOM (ValueError) and OTHER (KeyError) crash; the reported failure is the first one in the input.
    stdin = "a\nBOOM\nb\nOTHER\nc\n"
    result, _ = create(workspace, {"command": {"argv": argv}, "stdin": stdin})
    assert "ValueError" in result["signature"]["stderr_regex"]
    assert result["summary"]["minimal_stdin"].strip() == "BOOM"
    # An explicit signature for the second error ignores the first one and ends up on its own line.
    other, _ = create(workspace, {"command": {"argv": argv}, "stdin": "OTHER\nx\n",
                                  "signature": {"exit_code": 1, "stderr_regex": "KeyError"}})
    assert other["summary"]["minimal_stdin"].strip() == "OTHER"
    # A signature that the initial run does not show is not reproduced.
    missing, _ = create(workspace, {"command": {"argv": argv}, "stdin": "OTHER\n", "signature": {"stderr_regex": "ValueError"}})
    assert missing["summary"]["status"] == "not_reproduced"


def test_inputs_files_and_env_that_matter_are_kept(workspace):
    tmp = workspace[3]
    source = ("import os,sys\nneed=open('cfg.ini').read()\nif os.environ.get('MODE')=='strict' and 'bad=1' in need:\n"
              "    sys.stderr.write('ConfigError: bad\\n'); sys.exit(3)\nprint('fine')\n")
    result, _ = create(workspace, {"command": {"argv": program(tmp, "cfg.py", source)},
                                   "files": {"cfg.ini": "a=1\nbad=1\nz=2\n", "other.txt": "zzz"},
                                   "env": {"MODE": "strict", "NOISE": "1"}})
    summary = result["summary"]
    assert summary["status"] == "reproduced_and_minimised" and result["signature"]["exit_code"] == 3
    assert summary["env_after"] == ["MODE"] and summary["files_after"] == 1
    manifest = json.loads((Path(result["bundle"]["directory"]) / "repro.json").read_text(encoding="utf-8"))
    assert manifest["inputs"]["files"] == ["cfg.ini"]
    assert (Path(result["bundle"]["directory"]) / "inputs" / "files" / "cfg.ini").read_text(encoding="utf-8").strip() == "bad=1"


def test_output_predicate_failure_and_no_failure(workspace):
    tmp = workspace[3]
    argv = program(tmp, "sum.py", "import sys\nxs=[int(l) for l in sys.stdin.read().split()]\nprint(sum(xs) if len(xs)<3 else sum(xs)-1)\n")
    result, _ = create(workspace, {"command": {"argv": argv}, "stdin": "5\n6\n7\n8\n",
                                   "expected_predicate": "int(stdout) == 26"})
    assert result["summary"]["status"] == "reproduced_and_minimised"
    assert result["signature"]["predicate"] == "not (int(stdout) == 26)"
    healthy, _ = create(workspace, {"command": {"argv": argv}, "stdin": "1\n", "expected_predicate": "int(stdout) == 1"})
    assert healthy["summary"]["status"] == "not_reproduced"


def test_verify_against_fixed_program_says_no_longer_reproduces(workspace):
    tmp = workspace[3]
    result, job_id = create(workspace, {"command": {"argv": program(tmp, "app.py", CRASH)}, "stdin": lines(40, 7)})
    bundle = result["bundle"]["directory"]
    fixed = program(tmp, "fixed.py", FIXED)
    fixed_run = verify(workspace, bundle_dir=bundle, argv=fixed)
    assert fixed_run["summary"]["verdict"] == "no_longer_reproduces" and fixed_run["program_overridden"]
    assert fixed_run["summary"]["still_fails_differently"] is False
    still = verify(workspace, bundle_dir=bundle, attempts=2)
    assert still["summary"]["verdict"] == "reproduces" and still["summary"]["reproduced"] == 2
    different = verify(workspace, bundle_dir=bundle, argv=program(tmp, "other.py", "import sys\nsys.exit(5)\n"))
    assert different["summary"]["verdict"] == "no_longer_reproduces" and different["summary"]["still_fails_differently"]
    # tampered inputs are refused
    (Path(bundle) / "inputs" / "stdin.txt").write_text("changed", encoding="utf-8")
    response = workspace[0].post("/api/projects/%s/repro/verify" % workspace[2], json={"bundle_dir": bundle})
    assert response.status_code == 400 and "modified" in response.text


def test_flaky_failure_is_not_minimised(workspace):
    tmp = workspace[3]
    marker = tmp / "count.txt"
    source = ("import sys,pathlib\np=pathlib.Path(%r)\nn=int(p.read_text()) if p.exists() else 0\np.write_text(str(n+1))\n"
              "sys.exit(1 if n==0 else 0)\n" % str(marker))
    result, _ = create(workspace, {"command": {"argv": program(tmp, "flaky.py", source)}, "stdin": "x\n"})
    assert result["summary"]["status"] == "flaky" and "bundle" not in result


def test_signature_predicate_is_sandboxed(workspace):
    argv = program(workspace[3], "app.py", CRASH)
    response = workspace[0].post("/api/projects/%s/repro" % workspace[2], json={
        "report": {"command": {"argv": argv}, "signature": {"predicate": "stdout.__class__ == 1"}}})
    assert response.status_code == 400
