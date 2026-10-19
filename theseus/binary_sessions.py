"""Persistent native analysis projects, served by our incorporated engine script."""
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from jsonschema import validate

from .binary_analysis import engines
from .byte_oracle import compare as compare_byte_evidence
from .inspection import digest
from .store import identifier

SCRIPTS = Path(__file__).resolve().parents[1] / "software_native" / "engine" / "bridge" / "ghidra"
DOCUMENT = {"document": None}
ADDRESS_METHODS = {"address_name", "list_names", "list_strings", "resolve_containing_procedure",
                   "inspect_native_instruction", "resolve_native_call_targets", "xrefs", "address_to_file_offset"}
PROCEDURE_METHODS = {"procedure_address", "procedure_assembly", "procedure_callees", "procedure_callers",
                     "procedure_info", "procedure_pseudo_code", "read_function_instructions", "procedure_references",
                     "read_function_byte_evidence"}
MUTATIONS = {"annotate_native_function", "set_address_name", "set_addresses_names",
             "set_comment", "set_inline_comment", "set_bookmark", "unset_bookmark", "goto_address", "next_address", "prev_address"}
METHODS = {
    "ping": {}, "read_binary_inventory_summary": {}, "inspect_native_load_image": {}, "list_documents": {},
    **{name: {**DOCUMENT, "address": None} for name in ADDRESS_METHODS},
    **{name: {**DOCUMENT, "procedure": ""} for name in PROCEDURE_METHODS},
    "list_procedures": DOCUMENT, "list_segments": DOCUMENT,
    "read_bytes": {**DOCUMENT, "address": "", "length": 256},
    "search_bytes": {**DOCUMENT, "pattern": "", "limit": 1000},
    "search_procedures": {**DOCUMENT, "pattern": "", "mode": "literal", "case_sensitive": False},
    "search_strings": {**DOCUMENT, "pattern": "", "mode": "literal", "case_sensitive": False},
    "inspect_native_data_type": {**DOCUMENT, "type": None, "address": None},
    "analyze_function": {"procedure": ""},
    "set_address_name": {**DOCUMENT, "address": "", "name": ""},
    "set_addresses_names": {**DOCUMENT, "names": {}},
    "annotate_native_function": {"procedure": ""},
    "current_document": {}, "current_address": DOCUMENT, "current_procedure": DOCUMENT,
    "goto_address": {**DOCUMENT, "address": ""},
    "next_address": {**DOCUMENT, "address": None}, "prev_address": {**DOCUMENT, "address": None},
    "comment": {**DOCUMENT, "address": ""}, "inline_comment": {**DOCUMENT, "address": ""},
    "set_comment": {**DOCUMENT, "address": "", "text": ""},
    "set_inline_comment": {**DOCUMENT, "address": "", "text": ""},
    "list_bookmarks": {**DOCUMENT, "type": None, "category": None},
    "set_bookmark": {**DOCUMENT, "address": "", "type": "Note", "category": "Theseus", "text": ""},
    "unset_bookmark": {**DOCUMENT, "address": "", "type": "Note", "category": "Theseus"},
    "get_call_graph": {}, "trace_call_path": {"from_procedure": "", "to_procedure": "", "max_depth": None},
    "batch_decompile": {"procedures": []}, "inspect_native_api": {"procedure": ""},
    "trace_native_values": {"procedure": "", "query": {}},
}


def catalog():
    return {"engine": engines(), "operations": [
        {"name": name, "parameters": defaults, "writes_analysis_project": name in MUTATIONS}
        for name, defaults in sorted(METHODS.items())],
        "instructions": "Open an artifact or its retained analysis project first. Calls return background jobs and persist individually readable records. Addresses use 0x-prefixed hexadecimal; procedure selectors accept an exact address or name. Null document selects the session program. Annotations change the retained analysis database, never source bytes. Search byte results include cursors; limit is caller-selected, not a total coverage claim."}


class Runtime:
    def __init__(self, process, token):
        self.process = process
        self.token = token
        self.lock = threading.Lock()
        self.socket = None
        self.stream = None
        self.sequence = 0

    def request(self, method, parameters):
        self.sequence += 1
        request = {"id": self.sequence, "token": self.token, "method": method, "params": parameters}
        self.stream.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        self.stream.flush()
        line = self.stream.readline()
        if not line:
            raise OSError("The native binary engine closed its connection")
        result = json.loads(line)
        if result.get("id") != self.sequence:
            raise ValueError("Native engine response does not match its request")
        return result

    def disconnect(self):
        if self.stream:
            self.stream.close()
        if self.socket:
            self.socket.close()


class BinarySessions:
    def __init__(self, manager):
        self.manager = manager
        self.store = manager.store
        self.runtimes = {}
        self.lock = threading.Lock()
        self.starting = set()

    def read(self, session_id):
        job = self.store.job(session_id)
        if job["result"].get("kind") != "binary_session":
            raise ValueError("This job is not a native binary session")
        runtime = self.runtimes.get(session_id)
        result = job["result"]
        lost = runtime is None or runtime.process.poll() is not None
        if result["session_state"] in {"open", "starting", "closing"} and lost and session_id not in self.starting:
            result["session_state"] = "interrupted"
            result["error"] = "The session engine is no longer attached; reopen its retained project"
            job = self.store.save_job(job["project_id"], session_id, "interrupted", result)
        return job

    def list(self, project_id):
        return {"sessions": [self.read(row["id"]) for row in self.store.items("jobs", project_id)
                             if row["result"].get("kind") == "binary_session"]}

    def open(self, project_id, artifact_id, options=None):
        options = json.loads(json.dumps(options or {}))
        try:
            validate(options, {"type": "object", "additionalProperties": False, "properties": {
                **{key: {"type": "string"} for key in ("analysis_job_id", "language_id", "compiler_spec_id", "base_address")},
                "raw": {"type": "boolean"}}})
        except Exception as exc:
            raise ValueError("Invalid native binary session options: " + str(exc)) from exc
        if options.get("raw") and not options.get("analysis_job_id") and (
                not options.get("language_id") or not options.get("base_address")):
            raise ValueError("Raw imports require explicit language_id and base_address")
        artifact = self.store.artifact(project_id, artifact_id)
        configured = engines()
        if not configured["available"]:
            raise ValueError("Install local Ghidra and its supported JDK")
        session_id = identifier()
        folder = self.store.directory / "binary-sessions" / session_id
        folder.mkdir(parents=True)
        project_directory = folder / "project"
        project_directory.mkdir()
        source_sha = None
        reuse = options.get("analysis_job_id")
        if reuse:
            previous = self.store.job(reuse)
            if previous["result"].get("evidence_import"):
                raise ValueError("Imported evidence excludes native Ghidra projects; open the original artifact instead")
            if previous["project_id"] != project_id or previous["result"].get("artifact_id") != artifact_id:
                raise ValueError("The retained analysis must belong to this artifact")
            if previous["result"].get("kind") not in {"binary_analysis", "binary_session"}:
                raise ValueError("Select a retained Ghidra analysis project")
            source_sha = previous["result"]["artifact_sha256"]
            project_directory = Path(previous["result"]["project_directory"])
            # A former live session stores its native project in this subfolder.
            if previous["result"].get("kind") == "binary_session":
                previous = self.read(reuse)
                if previous["result"]["session_state"] in {"open", "starting", "closing"}:
                    raise ValueError("Close the previous session before reopening its project")
            if not (project_directory / "inspection.gpr").is_file():
                raise ValueError("The retained native project is unavailable")
        else:
            source_sha = digest(artifact["path"])
        properties = Path(configured["ghidra_home"]) / "Ghidra/application.properties"
        version = re.search(r"^application.version=(.+)$", properties.read_text(), re.M).group(1).strip()
        profile = {"engine": "Theseus native binary engine", "version": version, "options": options}
        profile_sha = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
        result = {"kind": "binary_session", "session_state": "starting", "artifact_id": artifact_id,
                  "artifact_name": artifact["name"], "artifact_sha256": source_sha,
                  "recorded_artifact_sha256": artifact["sha256"], "profile": profile, "profile_sha256": profile_sha,
                  "project_directory": str(project_directory), "folder": str(folder), "engine": configured,
                  "revision": 0, "cases": [], "passed": 0, "failed": 0}
        self.store.save_job(project_id, session_id, "queued", result)
        self.starting.add(session_id)
        self.manager.pool.submit(self._open, project_id, session_id, artifact, options, result)
        return self.store.job(session_id)

    def _open(self, project_id, session_id, artifact, options, result):
        folder = Path(result["folder"])
        endpoint = folder / "endpoint.json"
        descriptor = folder / "engine-session.json"
        token = secrets.token_urlsafe(40)
        descriptor.write_text(json.dumps({"transport": "authenticated-loopback-tcp", "endpoint_path": str(endpoint),
            "token": token, "run_id": session_id, "target_sha256": result["artifact_sha256"],
            "provider_version": result["profile"]["version"], "profile_digest": result["profile_sha256"]}), encoding="utf-8")
        for name in ("home", "settings", "cache"):
            (folder / name).mkdir()
        configured = result["engine"]
        command = [configured["java_executable"], "-Djava.system.class.loader=ghidra.GhidraClassLoader",
            "-Dfile.encoding=UTF8", "-Duser.country=US", "-Duser.language=en", "-Djava.awt.headless=true",
            "-Duser.home=" + str(folder / "home"), "-Dapplication.settingsdir=" + str(folder / "settings"),
            "-Dapplication.cachedir=" + str(folder / "cache"), "-cp", configured["utility_jar"],
            "ghidra.Ghidra", "ghidra.app.util.headless.AnalyzeHeadless", result["project_directory"], "inspection"]
        base_command = list(command)
        import_command = None
        if options.get("analysis_job_id"):
            command += ["-process", artifact["name"], "-noanalysis"]
        else:
            command += ["-import", artifact["path"]]
            if options.get("language_id"):
                command += ["-processor", options["language_id"]]
            if options.get("compiler_spec_id"):
                command += ["-cspec", options["compiler_spec_id"]]
            if options.get("raw"):
                command += ["-loader", "BinaryLoader", "-loader-baseAddr", options["base_address"],
                            "-preScript", "TheseusGhidraPrepareRaw.java", options["language_id"], options["base_address"]]
            # A freshly imported Program has a temporary DomainFile until the
            # headless import completes. Persist it before serving mutations.
            import_command = command + ["-scriptPath", str(SCRIPTS)]
            command = base_command + ["-process", artifact["name"], "-noanalysis"]
        command += ["-scriptPath", str(SCRIPTS), "-postScript", "TheseusGhidraBridge.java", str(descriptor)]
        runtime = None
        try:
            self._active(session_id)
            if import_command:
                result["phase"] = "importing"
                self.store.save_job(project_id, session_id, "running", result)
                execution = self.manager._execute(session_id, import_command, {})
                result["import_execution"] = execution
                for stream in ("stdout", "stderr"):
                    (folder / ("import." + stream + ".log")).write_text(execution[stream], encoding="utf-8")
                self._active(session_id)
                if execution["exit_code"] != 0 or not (Path(result["project_directory"]) / "inspection.gpr").is_file():
                    raise OSError("Native binary import did not create a saved project; inspect the import diagnostic")
            result["phase"] = "opening"
            with (folder / "engine.stdout.log").open("wb") as stdout, (folder / "engine.stderr.log").open("wb") as stderr:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            runtime = Runtime(process, token)
            with self.lock:
                self.runtimes[session_id] = runtime
            with self.manager.lock:
                self.manager.processes[session_id] = process
            result["pid"] = process.pid
            result["command"] = command
            self.store.save_job(project_id, session_id, "running", result)
            while not endpoint.is_file():
                self._active(session_id)
                if process.poll() is not None:
                    raise OSError("Native engine exited before becoming ready; inspect its retained logs")
                time.sleep(.1)
            # Java publishes the endpoint after closing its writer on Windows.
            while True:
                try:
                    address = json.loads(endpoint.read_text(encoding="utf-8"))
                    break
                except (PermissionError, json.JSONDecodeError):
                    self._active(session_id)
                    time.sleep(.02)
            if address["host"] != "127.0.0.1":
                raise ValueError("Native engine published a non-local endpoint")
            runtime.socket = socket.create_connection((address["host"], address["port"]))
            runtime.stream = runtime.socket.makefile("rwb")
            reply = runtime.request("ping", {})
            if not reply["ok"]:
                raise ValueError(str(reply.get("error")))
            result.update(session_state="open", info=reply["result"])
            result.pop("phase", None)
            self.store.save_job(project_id, session_id, "finished", result)
        except Exception as exc:
            if runtime:
                runtime.disconnect()
                if runtime.process.poll() is None:
                    self.manager._terminate(runtime.process)
            self._failed(project_id, session_id, result, type(exc).__name__ + ": " + str(exc))
        finally:
            self.starting.discard(session_id)

    def _failed(self, project_id, session_id, result, error):
        with self.manager.lock:
            stopped = session_id in self.manager.cancelled
            self.manager.cancelled.discard(session_id)
        result.update(session_state="interrupted" if stopped else "failed", error=error)
        self.store.save_job(project_id, session_id, "cancelled" if stopped else "failed", result)

    def _active(self, job_id):
        with self.manager.lock:
            if job_id in self.manager.cancelled:
                raise InterruptedError("Native engine work cancelled")

    def call(self, session_id, operation, parameters=None):
        with self.lock:
            return self._queue_call(session_id, operation, parameters)

    def _queue_call(self, session_id, operation, parameters):
        session = self.read(session_id)
        if session["result"]["session_state"] != "open" or session_id not in self.runtimes:
            raise ValueError("The native binary session is not open")
        if operation != "shutdown" and operation not in METHODS:
            raise ValueError("Unknown native binary operation; discover the session catalogue first")
        parameters = json.loads(json.dumps(parameters or {}))
        parameters = {**METHODS.get(operation, {}), **parameters}
        job_id = identifier()
        result = {"kind": "native_analysis", "operation": "binary." + operation, "title": "Binario · " + operation,
                  "artifact_id": session["result"]["artifact_id"], "artifact_name": session["result"]["artifact_name"],
                  "artifact_sha256": session["result"]["artifact_sha256"], "session_id": session_id,
                  "parameters": parameters, "cases": [], "passed": 0, "failed": 0}
        self.store.save_job(session["project_id"], job_id, "queued", result)
        if operation == "shutdown":
            session["result"]["session_state"] = "closing"
            self.store.save_job(session["project_id"], session_id, "finished", session["result"])
        self.manager.pool.submit(self._call, session, job_id, operation, parameters, result)
        return self.store.job(job_id)

    def _call(self, session, job_id, operation, parameters, result):
        session_id = session["id"]
        runtime = self.runtimes[session_id]
        folder = self.store.directory / "analyses" / job_id
        folder.mkdir(parents=True)
        try:
            with runtime.lock:
                self._active(job_id)
                with self.manager.lock:
                    self.manager.processes[job_id] = runtime.process
                self.store.save_job(session["project_id"], job_id, "running", result)
                response = self._compose_value_trace(runtime, session, job_id, folder, parameters) if operation == "trace_native_values" else runtime.request(operation, parameters)
                result["engine_response"] = {key: value for key, value in response.items() if key != "result"}
                if not response["ok"]:
                    raise ValueError(str(response.get("error")))
                source = response["result"]
                document = {"operation": result["operation"], "artifact_sha256": result["artifact_sha256"],
                            "engine": "Theseus native binary engine", "session_id": session_id, "result": source}
                target = folder / "analysis.json"
                target.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
                result.update(analysis_file=str(target), analysis_sha256=digest(target))
                records = source if isinstance(source, dict) else {"records": source}
                result["sections"] = self.store.index_analysis(job_id, records)
                result["analysis_revision"] = self.store.job(session_id)["result"]["revision"]
                if operation in MUTATIONS:
                    current = self.store.job(session_id)
                    current["result"]["revision"] += 1
                    result["analysis_revision"] = current["result"]["revision"]
                    self.store.save_job(session["project_id"], session_id, "finished", current["result"])
                if operation == "shutdown":
                    runtime.disconnect()
                    runtime.process.wait()
                    current = self.store.job(session_id)
                    current["result"].update(session_state="closed", exit_code=runtime.process.returncode)
                    self.store.save_job(session["project_id"], session_id, "finished", current["result"])
                self._active(job_id)
                self.store.save_job(session["project_id"], job_id, "finished", result)
        except InterruptedError:
            self.store.save_job(session["project_id"], job_id, "cancelled", result)
        except Exception as exc:
            result["error"] = type(exc).__name__ + ": " + str(exc)
            with self.manager.lock:
                stopped = job_id in self.manager.cancelled
            self.store.save_job(session["project_id"], job_id, "cancelled" if stopped else "failed", result)
        finally:
            with self.manager.lock:
                self.manager.processes.pop(job_id, None)
                self.manager.cancelled.discard(job_id)
            self.read(session_id)

    def _compose_value_trace(self, runtime, session, job_id, folder, parameters):
        node = shutil.which("node")
        entry = SCRIPTS.parents[1] / "dist" / "session-flow.js"
        if not node or not entry.is_file():
            raise ValueError("Build the native Node analysis core before tracing values")
        artifact = self.store.artifact(session["project_id"], session["result"]["artifact_id"])
        format_name = artifact["inspection"]["format"]
        target = {"path": artifact["path"], "sha256": session["result"]["artifact_sha256"],
                  "format": format_name if format_name in {"pe", "elf", "mach-o"} else "unknown"}
        request = folder / "session-flow-request.json"
        request.write_text(json.dumps({"target": target, "version": session["result"]["profile"]["version"],
                                       "parameters": parameters}), encoding="utf8")
        diagnostics = folder / "session-flow-stderr.log"
        with diagnostics.open("w", encoding="utf8") as stderr:
            process = subprocess.Popen([node, str(entry), str(request)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=stderr, text=True, encoding="utf8", shell=False)
            value = None
            try:
                with self.manager.lock:
                    self.manager.processes[job_id] = [runtime.process, process]
                self._active(job_id)
                for line in process.stdout:
                    self._active(job_id)
                    message = json.loads(line)
                    if message["kind"] == "result":
                        value = message["value"]
                    elif message["kind"] == "observation-request":
                        method = message["operation"]
                        response = runtime.request(method, {**METHODS[method], **message["parameters"]})
                        process.stdin.write(json.dumps(response, ensure_ascii=False)+"\n")
                        process.stdin.flush()
                    else:
                        raise ValueError("Unknown native composition message")
                process.wait()
                self._active(job_id)
                if process.returncode or value is None:
                    raise ValueError("Native value trace failed: "+diagnostics.read_text(encoding="utf8"))
                return {"ok": True, "result": value}
            finally:
                if process.poll() is None:
                    self.manager._terminate(process)
                process.wait()
                process.stdin.close()
                process.stdout.close()
                with self.manager.lock:
                    self.manager.processes[job_id] = runtime.process

    def compare(self, reference_session_id, candidate_session_id, reference_procedure, candidate_procedure):
        with self.lock:
            reference = self.read(reference_session_id)
            candidate = self.read(candidate_session_id)
            if reference["project_id"] != candidate["project_id"]:
                raise ValueError("Both native sessions must belong to the same investigation project")
            for session in (reference, candidate):
                if session["result"]["session_state"] != "open":
                    raise ValueError("Both native sessions must be open")
            job_id = identifier()
            result = {"kind": "native_analysis", "operation": "binary.compare", "title": "Comparación de bytes y datos",
                "artifact_id": reference["result"]["artifact_id"], "artifact_name": reference["result"]["artifact_name"],
                "artifact_sha256": reference["result"]["artifact_sha256"], "session_id": reference_session_id,
                "candidate_session_id": candidate_session_id,
                "candidate_artifact_id": candidate["result"]["artifact_id"],
                "candidate_artifact_sha256": candidate["result"]["artifact_sha256"],
                "parameters": {"reference_procedure": reference_procedure, "candidate_procedure": candidate_procedure},
                "cases": [], "passed": 0, "failed": 0}
            self.store.save_job(reference["project_id"], job_id, "queued", result)
            self.manager.pool.submit(self._compare, reference, candidate, job_id, result)
            return self.store.job(job_id)

    def _compare(self, reference, candidate, job_id, result):
        project_id = reference["project_id"]
        try:
            self._active(job_id)
            self.store.save_job(project_id, job_id, "running", result)
            snapshots = []
            for side, session in (("reference", reference), ("candidate", candidate)):
                runtime = self.runtimes[session["id"]]
                with runtime.lock:
                    self._active(job_id)
                    with self.manager.lock:
                        self.manager.processes[job_id] = runtime.process
                    response = runtime.request("read_function_byte_evidence", {
                        "document": None, "procedure": result["parameters"][side + "_procedure"]})
                    if not response["ok"]:
                        raise ValueError(side + ": " + str(response.get("error")))
                    snapshot = response["result"]
                    snapshot["artifact_sha256"] = session["result"]["artifact_sha256"]
                    snapshot["analysis_revision"] = self.store.job(session["id"])["result"]["revision"]
                    snapshots.append(snapshot)
            document = {"operation": result["operation"], "artifact_sha256": result["artifact_sha256"],
                        **compare_byte_evidence(*snapshots), "reference": snapshots[0], "candidate": snapshots[1]}
            folder = self.store.directory / "analyses" / job_id
            folder.mkdir(parents=True)
            target = folder / "analysis.json"
            target.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            result.update(analysis_file=str(target), analysis_sha256=digest(target), comparison_status=document["status"],
                          sections=self.store.index_analysis(job_id, document))
            self._active(job_id)
            self.store.save_job(project_id, job_id, "finished", result)
        except Exception as exc:
            result["error"] = type(exc).__name__ + ": " + str(exc)
            with self.manager.lock:
                stopped = job_id in self.manager.cancelled
            self.store.save_job(project_id, job_id, "cancelled" if stopped else "failed", result)
        finally:
            with self.manager.lock:
                self.manager.processes.pop(job_id, None)
                self.manager.cancelled.discard(job_id)
            for session in (reference, candidate):
                self.read(session["id"])

    def shutdown(self):
        for session_id, runtime in list(self.runtimes.items()):
            if runtime.process.poll() is None:
                if runtime.stream is None:
                    self.manager.cancel(session_id)
                    continue
                with runtime.lock:
                    try:
                        runtime.request("shutdown", {})
                    except (OSError, ValueError):
                        pass
                    finally:
                        runtime.disconnect()
                runtime.process.wait()
