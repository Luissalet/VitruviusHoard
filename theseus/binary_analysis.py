"""Local free disassembly engine; project/evidence/workflow belong to Theseus."""
import json
import os
from pathlib import Path
import re

from .inspection import digest
from .store import identifier


def engines():
    ghidra = os.getenv("THESEUS_GHIDRA_HOME", "")
    java = os.getenv("THESEUS_JAVA_HOME", "")
    if not ghidra:
        roots = sorted(Path("D:/LocalAI/tools/ghidra").glob("ghidra_*_PUBLIC"), key=_version)
        ghidra = str(roots[-1]) if roots else ""
    if not java:
        roots = sorted(Path("D:/LocalAI/tools/jdk21").glob("jdk-*"), key=_version)
        java = str(roots[-1]) if roots else os.getenv("JAVA_HOME", "")
    utility = Path(ghidra) / "Ghidra/Framework/Utility/lib/Utility.jar"
    executable = Path(java) / "bin" / ("java.exe" if os.name == "nt" else "java")
    return {"ghidra_home": ghidra, "java_home": java,
            "available": bool(ghidra and java and utility.is_file() and executable.is_file()),
            "utility_jar": str(utility), "java_executable": str(executable),
            "external_api_required": False}


def _version(path):
    return tuple(int(part) for part in re.findall(r"\d+", path.name))


def start(manager, project_id, artifact_id):
    artifact = manager.store.artifact(project_id, artifact_id)
    engine = engines()
    if not engine["available"]:
        raise ValueError("Install local Ghidra and a compatible JDK, then set THESEUS_GHIDRA_HOME and THESEUS_JAVA_HOME")
    current_sha256 = digest(artifact["path"])
    job_id = identifier()
    folder = manager.store.directory / "analyses" / job_id
    folder.mkdir(parents=True)
    result = {"kind": "binary_analysis", "artifact_id": artifact_id, "artifact_name": artifact["name"],
              "artifact_sha256": current_sha256, "recorded_artifact_sha256": artifact["sha256"],
              "source_changed": current_sha256 != artifact["sha256"], "engine": engine,
              "project_directory": str(folder), "cases": [], "passed": 0, "failed": 0}
    manager.store.save_job(project_id, job_id, "queued", result)
    manager.pool.submit(_run, manager, project_id, job_id, artifact, folder, result)
    return manager.store.job(job_id)


def _run(manager, project_id, job_id, artifact, folder, result):
    engine = result["engine"]
    output = folder / "functions.json"
    scripts = Path(__file__).parent / "ghidra_scripts"
    for name in ("home", "settings", "cache"):
        (folder / name).mkdir()
    command = [engine["java_executable"], "-Djava.system.class.loader=ghidra.GhidraClassLoader",
               "-Dfile.encoding=UTF8", "-Duser.country=US", "-Duser.language=en", "-Djava.awt.headless=true",
               "-Duser.home=" + str(folder / "home"),
               "-Dapplication.settingsdir=" + str(folder / "settings"),
               "-Dapplication.cachedir=" + str(folder / "cache"),
               "-cp", engine["utility_jar"], "ghidra.Ghidra", "ghidra.app.util.headless.AnalyzeHeadless",
               str(folder), "inspection", "-import", artifact["path"],
               "-scriptPath", str(scripts), "-postScript", "TheseusExport.java", str(output)]
    try:
        manager.store.save_job(project_id, job_id, "running", result)
        execution = manager._execute(job_id, command, {})
        result["execution"] = execution
        with manager.lock:
            stopped = job_id in manager.cancelled
        if stopped:
            state = "cancelled"
        elif execution["exit_code"] != 0 or not output.is_file():
            state = "failed"
            result["error"] = "The local engine did not produce a function export; inspect its stdout/stderr"
        else:
            result["analysis"] = json.loads(output.read_text(encoding="utf-8"))
            result["export_sha256"] = digest(output)
            result["source_changed_during_analysis"] = digest(artifact["path"]) != result["artifact_sha256"]
            state = "finished"
        manager.store.save_job(project_id, job_id, state, result)
    except InterruptedError:
        manager.store.save_job(project_id, job_id, "cancelled", result)
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
        manager.store.save_job(project_id, job_id, "failed", result)
    finally:
        with manager.lock:
            manager.cancelled.discard(job_id)


def read_function(store, job_id, address):
    job = store.job(job_id)
    functions = job["result"].get("analysis", {}).get("functions", [])
    function = next((row for row in functions if row["address"] == address), None)
    if function is None:
        raise LookupError("Function not found in this analysis")
    callers = [{"name": row["name"], "address": row["address"]} for row in functions
               if any(call["address"] == address for call in row.get("calls", []))]
    return {"job_id": job_id, "artifact_sha256": job["result"]["artifact_sha256"],
            "engine": job["result"]["analysis"]["engine"], "certainty": "engine_inferred",
            "function": function, "callers": callers}
