"""Differential observations of two explicitly configured local programs."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time

import psutil

from .inspection import digest
from .store import identifier


def validate_scenario(value):
    if not isinstance(value, dict):
        raise ValueError("A scenario is a JSON object")
    for field in ("reference", "candidate"):
        command = value.get(field)
        if not isinstance(command, list) or not command or any(not isinstance(arg, str) or not arg for arg in command):
            raise ValueError(field + " must be a nonempty array of command arguments")
    if value.get("mode", "text") not in {"text", "json"}:
        raise ValueError("Comparison mode is text or json")
    if not isinstance(value.get("stdin", ""), str):
        raise ValueError("stdin must be text")
    if value.get("timeout_seconds") is not None and float(value["timeout_seconds"]) <= 0:
        raise ValueError("An explicit timeout must be positive")
    if "expected_exit_code" in value and (not isinstance(value["expected_exit_code"], int) or isinstance(value["expected_exit_code"], bool)):
        raise ValueError("Expected exit code must be an integer")
    if value.get("cwd") and not Path(value["cwd"]).is_dir():
        raise ValueError("Working directory does not exist")


def observation_differences(reference, candidate, definition):
    differences = []
    if reference["timed_out"] or candidate["timed_out"]:
        differences.append("An explicitly configured timeout expired")
    for field in ("exit_code", "stderr"):
        if reference[field] != candidate[field]:
            differences.append(field + " differs")
    left, right = reference["stdout"], candidate["stdout"]
    if definition.get("mode", "text") == "json":
        try:
            left, right = json.loads(left), json.loads(right)
        except ValueError:
            differences.append("Output is not valid JSON")
    if left != right:
        differences.append("stdout differs")
    if "expected_stdout" in definition and left != definition["expected_stdout"]:
        differences.append("Reference output differs from the explicit expectation")
    if "expected_exit_code" in definition and reference["exit_code"] != definition["expected_exit_code"]:
        differences.append("Reference exit code differs from the explicit expectation")
    return differences


class Comparisons:
    def __init__(self, store):
        self.store = store
        self.pool = ThreadPoolExecutor(thread_name_prefix="theseus-comparison")
        self.lock = threading.Lock()
        self.cancelled = set()
        self.processes = {}
        self.frida_sessions = None

    def start(self, project_id, scenario_ids=None, context=None):
        scenarios = self.store.items("scenarios", project_id)
        if scenario_ids is not None:
            selected = set(scenario_ids)
            scenarios = [row for row in scenarios if row["id"] in selected]
            if {row["id"] for row in scenarios} != selected:
                raise ValueError("A selected scenario does not belong to this project")
        if not scenarios:
            raise ValueError("Add a comparison scenario first")
        snapshot = [{"id": r["id"], "name": r["name"], "definition": r["definition"]} for r in scenarios]
        fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        job_id = identifier()
        result = {"scenarios": snapshot, "definition_sha256": fingerprint, "cases": [], "passed": 0, "failed": 0}
        result["specification_sha256"] = hashlib.sha256(json.dumps(
            self.store.project(project_id)["specification"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if context:
            result["reconstruction"] = context
        self.store.save_job(project_id, job_id, "queued", result)
        self.pool.submit(self._run, project_id, job_id, result)
        return self.store.job(job_id)

    def cancel(self, job_id):
        job = self.store.job(job_id)
        if job["state"] not in {"queued", "running"}:
            return job
        with self.lock:
            self.cancelled.add(job_id)
            process = self.processes.get(job_id)
            if process is not None and process.poll() is None:
                self._terminate(process)
        if self.frida_sessions:
            self.frida_sessions.cancel(job_id)
        return self.store.job(job_id)

    @staticmethod
    def _terminate(process):
        """Stop the comparison's own process and its current descendants."""
        if isinstance(process, (list, tuple)):
            for member in process:
                Comparisons._terminate(member)
            return
        try:
            parent = psutil.Process(process.pid)
            targets = [*reversed(parent.children(recursive=True)), parent]
            if getattr(process, "_theseus_preserve_adb_server", False):
                def shared_adb_server(target):
                    try:
                        return Path(target.exe()).stem.lower() == "adb" and "fork-server" in target.cmdline() and "server" in target.cmdline()
                    except psutil.Error:
                        return False
                targets = [target for target in targets if not shared_adb_server(target)]
            for target in targets:
                try:
                    target.terminate()
                except psutil.Error:
                    pass
            _, remaining = psutil.wait_procs(targets, timeout=2)
            for target in remaining:
                try:
                    target.kill()
                except psutil.Error:
                    pass
        except psutil.Error:
            pass

    def _execute(self, job_id, command, definition):
        with self.lock:
            if job_id in self.cancelled:
                raise InterruptedError("Comparison cancelled")
        started = time.perf_counter()
        cwd = definition.get("cwd") or None
        executable = shutil.which(command[0]) or command[0]
        observed_files = {}
        for arg in [executable, *command[1:]]:
            path = Path(arg)
            if not path.is_absolute() and cwd:
                path = Path(cwd) / path
            try:
                if path.is_file():
                    observed_files[str(path.resolve())] = digest(path)
            except OSError:
                # A command argument may be source code or a long value,
                # rather than a valid filesystem name.
                continue
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace", shell=False)
        process._theseus_preserve_adb_server = bool(definition.get("preserve_adb_server"))
        with self.lock:
            self.processes[job_id] = process
            if job_id in self.cancelled:
                self._terminate(process)
        timed_out = False
        try:
            stdout, stderr = process.communicate(definition.get("stdin", ""), timeout=definition.get("timeout_seconds"))
        except subprocess.TimeoutExpired:
            timed_out = True
            self._terminate(process)
            stdout, stderr = process.communicate()
        finally:
            with self.lock:
                self.processes.pop(job_id, None)
        return {"argv": command, "exit_code": process.returncode, "stdout": stdout, "stderr": stderr,
                "duration_seconds": round(time.perf_counter() - started, 4), "timed_out": timed_out,
                "file_sha256": observed_files}

    def _run(self, project_id, job_id, result):
        try:
            self.store.save_job(project_id, job_id, "running", result)
            for scenario in result["scenarios"]:
                definition = scenario["definition"]
                with self.lock:
                    if job_id in self.cancelled:
                        raise InterruptedError("Comparison cancelled")
                result["phase"] = "reference"
                result["running_scenario"] = scenario["name"]
                self.store.save_job(project_id, job_id, "running", result)
                reference = self._execute(job_id, definition["reference"], definition)
                result["partial_case"] = {"scenario_id": scenario["id"], "reference": reference}
                result["phase"] = "candidate"
                self.store.save_job(project_id, job_id, "running", result)
                candidate = self._execute(job_id, definition["candidate"], definition)
                differences = observation_differences(reference, candidate, definition)
                case = {"scenario_id": scenario["id"], "name": scenario["name"], "passed": not differences,
                        "differences": differences, "reference": reference, "candidate": candidate}
                result["cases"].append(case)
                result.pop("partial_case", None)
                result["passed" if case["passed"] else "failed"] += 1
                self.store.save_job(project_id, job_id, "running", result)
            with self.lock:
                stopped = job_id in self.cancelled
            result.pop("phase", None)
            result.pop("running_scenario", None)
            self.store.save_job(project_id, job_id, "cancelled" if stopped else "finished", result)
        except InterruptedError as exc:
            result["message"] = str(exc)
            self.store.save_job(project_id, job_id, "cancelled", result)
        except Exception as exc:
            result["error"] = type(exc).__name__ + ": " + str(exc)
            self.store.save_job(project_id, job_id, "failed", result)
        finally:
            with self.lock:
                self.cancelled.discard(job_id)

    def shutdown(self):
        with self.lock:
            running = list(self.processes)
        if self.frida_sessions:
            with self.frida_sessions.lock:
                running += list(self.frida_sessions.cancellables)
        for job_id in running:
            self.cancel(job_id)
        self.pool.shutdown(wait=True, cancel_futures=True)
