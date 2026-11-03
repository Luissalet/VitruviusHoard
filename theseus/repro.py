"""Reproducible failure diagnosis: reproduce, minimise, bundle and verify.

Reuses the equivalence runner (fresh sandbox per execution). A failure signature
(exit code / stderr regex / output predicate) is the fixed point: every
delta-debugging step re-executes the program and is accepted only when the same
signature is still observed, so a different failure is never mistaken for the
original one.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys

from .equivalence import Equivalence, _command, _relative, validate_case, _clip
from .expressions import Expression, ExpressionError
from .store import identifier, now

FORMAT = "theseus-repro/1"
SIGNATURE_NAMES = ("stdin", "exit_code", "stdout", "stderr", "output_files", "timed_out")
SCOPE = ("The failure was reproduced and minimised only in fresh sandboxes on this machine and environment; "
         "a smaller input that keeps the same signature is not a root-cause proof.")
RELEVANT_ENV = ("LANG", "LC_ALL", "TZ", "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONHASHSEED", "NODE_ENV")
LIMIT_BYTES = 2_000_000


class BudgetExceeded(Exception):
    pass


def _sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8", "replace")).hexdigest()


# ------------------------------------------------------------------ signature

def validate_signature(value):
    if not isinstance(value, dict) or not value or set(value) - {"exit_code", "stderr_regex", "stdout_regex", "timed_out", "predicate"}:
        raise ValueError("signature is {exit_code, stderr_regex, stdout_regex, timed_out, predicate} with at least one part")
    out = {}
    if "exit_code" in value:
        code = value["exit_code"]
        if code != "nonzero" and (isinstance(code, bool) or not isinstance(code, int)):
            raise ValueError("signature.exit_code is an integer or 'nonzero'")
        out["exit_code"] = code
    for key in ("stderr_regex", "stdout_regex"):
        if key in value:
            re.compile(str(value[key]))
            out[key] = str(value[key])
    if "timed_out" in value:
        out["timed_out"] = bool(value["timed_out"])
    if "predicate" in value:
        try:
            Expression(str(value["predicate"]), SIGNATURE_NAMES)
        except ExpressionError as exc:
            raise ValueError("signature predicate rejected: " + str(exc)) from exc
        out["predicate"] = str(value["predicate"]).strip()
    return out


def matches(signature, run):
    """True when the observed run shows exactly the failure the signature describes."""
    if "timed_out" in signature and signature["timed_out"] != run["timed_out"]:
        return False
    if run["timed_out"] and not signature.get("timed_out"):
        return False
    code = signature.get("exit_code")
    if code == "nonzero" and run["exit_code"] in (0, None):
        return False
    if isinstance(code, int) and code != run["exit_code"]:
        return False
    if "stderr_regex" in signature and not re.search(signature["stderr_regex"], run["stderr"], re.M):
        return False
    if "stdout_regex" in signature and not re.search(signature["stdout_regex"], run["stdout"], re.M):
        return False
    if "predicate" in signature:
        try:
            return bool(Expression(signature["predicate"], SIGNATURE_NAMES).evaluate(_vars(run)))
        except ExpressionError:
            return False
    return True


def _vars(run):
    return {"stdin": run.get("stdin", ""), "exit_code": run["exit_code"], "stdout": run["stdout"], "stderr": run["stderr"],
            "output_files": run.get("output_files", {}), "timed_out": run["timed_out"]}


def derive_signature(run, expected_predicate=None):
    if run["timed_out"]:
        return {"timed_out": True}
    if run["exit_code"] not in (0, None):
        signature = {"exit_code": run["exit_code"]}
        last = next((l.strip() for l in reversed(run["stderr"].splitlines()) if l.strip()), "")
        named = re.match(r"^([A-Za-z_][\w.]*)(?::|$)", last)
        if named:
            signature["stderr_regex"] = "^" + re.escape(named.group(1)) + r"(?::|$)"
        elif last:
            signature["stderr_regex"] = re.escape(last[:200])
        return signature
    if expected_predicate:
        try:
            if not Expression(expected_predicate, SIGNATURE_NAMES).evaluate(_vars(run)):
                return {"predicate": "not (%s)" % expected_predicate}
        except ExpressionError as exc:
            raise ValueError("expected_predicate failed on the observed output: " + str(exc)) from exc
    return None


# ----------------------------------------------------------------- minimiser

def ddmin(items, test, tick):
    """Classic delta debugging over a list: smallest sublist for which test() still holds."""
    n = 2
    while len(items) >= 2:
        size = max(1, len(items) // n)
        chunks = [items[i:i + size] for i in range(0, len(items), size)]
        reduced = False
        for i, chunk in enumerate(chunks):
            if len(chunks) > 2 and test(chunk):
                items, n, reduced = chunk, 2, True
                break
        if not reduced:
            for i in range(len(chunks)):
                complement = [x for j, c in enumerate(chunks) if j != i for x in c]
                if complement and test(complement):
                    items, n, reduced = complement, max(n - 1, 2), True
                    break
        if not reduced:
            if n >= len(items):
                break
            n = min(len(items), n * 2)
    if len(items) == 1 and test([]):
        return []
    return items


class Repro:
    def __init__(self, manager, equivalence=None):
        self.manager, self.store = manager, manager.store
        self.equivalence = equivalence or Equivalence(manager)

    # ---- execution of one state
    def _run(self, job_id, command, state, budget):
        key = _sha(json.dumps([state["stdin"], {k: _sha(v) for k, v in sorted(state["files"].items())},
                               sorted(state["env"].items())], ensure_ascii=False))
        if key in budget["cache"]:
            return budget["cache"][key]
        if budget["runs"] >= budget["max"]:
            raise BudgetExceeded()
        budget["runs"] += 1
        case = validate_case({"stdin": state["stdin"], "files": {p: {"base64": base64.b64encode(b).decode("ascii")}
                                                                  for p, b in state["files"].items()}})
        cmd = {**command, "env": {**command["env"], **state["env"]}}
        observation = self.equivalence.observe(job_id, cmd, case, {"ignore_paths": []})
        step = observation["steps"][0]
        run = {"exit_code": step["exit_code"], "timed_out": step["timed_out"], "stdout": step["stdout"],
               "stderr": step["stderr"], "stdin": state["stdin"],
               "output_files": {p: f["text"] for p, f in step["files"].items() if f["text"] is not None}}
        budget["cache"][key] = run
        return run

    # ---- create
    def start(self, project_id, report, max_runs=300, output_dir=""):
        self.store.project(project_id)
        spec = self.validate_report(report)
        if not isinstance(max_runs, int) or isinstance(max_runs, bool) or not 1 <= max_runs <= 2000:
            raise ValueError("max_runs is an integer from 1 to 2000")
        job_id = identifier()
        directory = Path(output_dir) if output_dir else self.store.directory / "repro" / job_id
        result = {"kind": "repro_create", "scope": SCOPE, "report": {k: v for k, v in report.items()},
                  "max_runs": max_runs, "bundle_dir": str(directory.resolve()), "summary": {}}
        self.store.save_job(project_id, job_id, "queued", result)
        self.manager.pool.submit(self._create, project_id, job_id, result, spec, max_runs, directory)
        return self.store.job(job_id)

    @staticmethod
    def validate_report(report):
        if not isinstance(report, dict):
            raise ValueError("A failure report is an object")
        allowed = {"command", "stdin", "files", "env", "description", "expected_predicate", "signature"}
        if set(report) - allowed:
            raise ValueError("Report has unknown fields: " + ", ".join(sorted(set(report) - allowed)))
        command = _command(report.get("command"), "command")
        stdin = report.get("stdin", "")
        if not isinstance(stdin, str):
            raise ValueError("stdin must be text")
        files = {}
        for path, content in (report.get("files") or {}).items():
            _relative(path, "input file")
            if isinstance(content, str):
                files[path.replace("\\", "/")] = content.encode("utf-8")
            elif isinstance(content, dict) and set(content) == {"base64"}:
                files[path.replace("\\", "/")] = base64.b64decode(content["base64"], validate=True)
            else:
                raise ValueError("input file content is text or {\"base64\": ...}")
        env = report.get("env", {})
        if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
            raise ValueError("env must map text to text")
        total = len(stdin.encode("utf-8")) + sum(len(b) for b in files.values())
        if total > LIMIT_BYTES:
            raise ValueError("inputs are larger than %d bytes" % LIMIT_BYTES)
        expected = report.get("expected_predicate")
        if expected is not None:
            try:
                Expression(str(expected), SIGNATURE_NAMES)
            except ExpressionError as exc:
                raise ValueError("expected_predicate rejected: " + str(exc)) from exc
        signature = validate_signature(report["signature"]) if report.get("signature") else None
        return {"command": command, "stdin": stdin, "files": files, "env": dict(env), "expected_predicate": expected,
                "description": str(report.get("description", "")), "signature": signature}

    def _create(self, project_id, job_id, result, spec, max_runs, directory):
        try:
            self.store.save_job(project_id, job_id, "running", result)
            command = spec["command"]
            state = {"stdin": spec["stdin"], "files": dict(spec["files"]), "env": dict(spec["env"])}
            budget = {"runs": 0, "max": max_runs, "cache": {}}
            first = self._run(job_id, command, state, budget)
            signature = spec["signature"] or derive_signature(first, spec["expected_predicate"])
            result["initial"] = {"exit_code": first["exit_code"], "timed_out": first["timed_out"],
                                 "stdout": _clip(first["stdout"]), "stderr": _clip(first["stderr"])}
            if signature is None:
                result["summary"] = {"status": "not_reproduced", "message": "The program did not fail with the given inputs: no non-zero exit, timeout or violated expected_predicate was observed."}
                self.store.save_job(project_id, job_id, "finished", result)
                return
            result["signature"] = signature
            result["signature_derived"] = spec["signature"] is None
            if not matches(signature, first):
                result["summary"] = {"status": "not_reproduced", "message": "The given signature was not observed on the first execution."}
                self.store.save_job(project_id, job_id, "finished", result)
                return
            budget["cache"].clear()
            second = self._run(job_id, command, state, budget)
            if not matches(signature, second):
                result["summary"] = {"status": "flaky", "message": "The failure appeared on the first execution but not on the confirmation run; nothing was minimised."}
                self.store.save_job(project_id, job_id, "finished", result)
                return

            trail = []
            def accepted(stage, before, after):
                trail.append({"stage": stage, "before": before, "after": after, "runs_so_far": budget["runs"]})

            def holds(candidate):
                return matches(signature, self._run(job_id, command, candidate, budget))

            exhausted = False
            try:
                self._minimise(state, holds, accepted)
            except BudgetExceeded:
                exhausted = True
            confirmations = [matches(signature, self._fresh(job_id, command, state, budget)) for _ in range(2)]
            if not all(confirmations):
                raise RuntimeError("The minimised input no longer shows the signature; refusing to write a bundle")
            fingerprint = self.fingerprint(command, state)
            manifest = self.write_bundle(directory, command, state, signature, spec["description"], spec["expected_predicate"],
                                         fingerprint, trail)
            original = len(spec["stdin"].encode("utf-8")) + sum(len(b) for b in spec["files"].values())
            reduced = len(state["stdin"].encode("utf-8")) + sum(len(b) for b in state["files"].values())
            result["summary"] = {
                "status": "reproduced_and_minimised", "executions": budget["runs"], "budget_exhausted": exhausted,
                "original_bytes": original, "minimal_bytes": reduced, "files_before": len(spec["files"]), "files_after": len(state["files"]),
                "env_before": sorted(spec["env"]), "env_after": sorted(state["env"]),
                "minimal_stdin": state["stdin"] if len(state["stdin"]) <= 2000 else state["stdin"][:2000] + "...[truncated]",
                "confirmed_on_minimal": True, "manifest_sha256": manifest["manifest_sha256"],
                "note": "Every accepted reduction was re-executed and kept the same failure signature; the minimum is local."}
            result["steps"] = trail
            result["environment"] = fingerprint
            result["bundle"] = {"directory": str(Path(directory).resolve()), "files": manifest["files"]}
            self.store.save_job(project_id, job_id, "finished", result)
        except InterruptedError as exc:
            result["message"] = str(exc)
            self.store.save_job(project_id, job_id, "cancelled", result)
        except Exception as exc:
            result["error"] = type(exc).__name__ + ": " + str(exc)
            self.store.save_job(project_id, job_id, "failed", result)
        finally:
            with self.manager.lock:
                self.manager.cancelled.discard(job_id)

    def _fresh(self, job_id, command, state, budget):
        """Execute again, bypassing the cache and the minimisation budget (final confirmation)."""
        saved = budget["max"]
        budget["cache"].clear()
        budget["max"] = budget["runs"] + 1
        try:
            return self._run(job_id, command, state, budget)
        finally:
            budget["max"] = saved

    def _minimise(self, state, holds, accepted):
        def attempt(stage, before, after, **change):
            candidate = {**state, **change}
            if holds(candidate):
                state.update(change)
                accepted(stage, before, after)
                return True
            return False
        # environment variables
        keys = sorted(state["env"])
        if keys:
            kept = ddmin(keys, lambda subset: holds({**state, "env": {k: state["env"][k] for k in subset}}), None)
            if kept != keys:
                state["env"] = {k: state["env"][k] for k in kept}
                accepted("env", len(keys), len(kept))
        # whole input files
        names = sorted(state["files"])
        if names:
            kept = ddmin(names, lambda subset: holds({**state, "files": {k: state["files"][k] for k in subset}}), None)
            if kept != names:
                state["files"] = {k: state["files"][k] for k in kept}
                accepted("files", len(names), len(kept))
        # stdin lines then characters
        lines = state["stdin"].splitlines(keepends=True)
        if len(lines) > 1:
            kept = ddmin(lines, lambda subset: holds({**state, "stdin": "".join(subset)}), None)
            if kept != lines:
                state["stdin"] = "".join(kept)
                accepted("stdin_lines", len(lines), len(kept))
        # file lines
        for name in sorted(state["files"]):
            data = state["files"][name]
            parts = data.split(b"\n")
            parts = [p + b"\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
            if len(parts) > 1:
                kept = ddmin(parts, lambda subset, n=name: holds({**state, "files": {**state["files"], n: b"".join(subset)}}), None)
                if kept != parts:
                    state["files"] = {**state["files"], name: b"".join(kept)}
                    accepted("file_lines:" + name, len(parts), len(kept))
        # characters / bytes
        chars = list(state["stdin"])
        if len(chars) > 1:
            kept = ddmin(chars, lambda subset: holds({**state, "stdin": "".join(subset)}), None)
            if kept != chars:
                state["stdin"] = "".join(kept)
                accepted("stdin_characters", len(chars), len(kept))
        for name in sorted(state["files"]):
            octets = [bytes([b]) for b in state["files"][name]]
            if len(octets) > 1:
                kept = ddmin(octets, lambda subset, n=name: holds({**state, "files": {**state["files"], n: b"".join(subset)}}), None)
                if kept != octets:
                    state["files"] = {**state["files"], name: b"".join(kept)}
                    accepted("file_bytes:" + name, len(octets), len(kept))

    # ---- environment fingerprint
    @staticmethod
    def fingerprint(command, state):
        node = None
        if shutil.which("node"):
            try:
                node = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5).stdout.strip() or None
            except (OSError, subprocess.SubprocessError):
                node = None
        program_files = {}
        for arg in command["argv"]:
            path = shutil.which(arg) if arg == command["argv"][0] else None
            path = path or arg
            try:
                if Path(path).is_file():
                    program_files[str(Path(path).resolve())] = _sha(Path(path).read_bytes())
            except OSError:
                continue
        env = {k: os.environ[k] for k in RELEVANT_ENV if k in os.environ}
        env.update({**command["env"], **state["env"]})
        return {"python": sys.version.split()[0], "python_executable": sys.executable, "node": node,
                "os": platform.platform(), "machine": platform.machine(), "relevant_env": env,
                "input_sha256": {"<stdin>": _sha(state["stdin"]), **{p: _sha(b) for p, b in sorted(state["files"].items())}},
                "program_files_sha256": program_files}

    # ---- bundle
    @staticmethod
    def _posix_arg(arg):
        if "{sandbox}" not in arg:
            return shlex.quote(arg)
        escaped = re.sub(r'([\\"$`])', r"\\\1", arg).replace("{sandbox}", "${WORK}")
        return '"' + escaped + '"'

    @staticmethod
    def _win_arg(arg):
        return subprocess.list2cmdline([arg]).replace("{sandbox}", "%WORK%")

    def write_bundle(self, directory, command, state, signature, description, expected_predicate, fingerprint, trail):
        root = Path(directory)
        if root.exists() and any(root.iterdir()):
            raise ValueError("bundle directory exists and is not empty: " + str(root))
        (root / "inputs" / "files").mkdir(parents=True, exist_ok=True)
        (root / "inputs" / "stdin.txt").write_bytes(state["stdin"].encode("utf-8"))
        for rel, data in state["files"].items():
            target = root / "inputs" / "files" / _relative(rel, "input file")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        env = {**command["env"], **state["env"]}
        posix_cmd = " ".join(self._posix_arg(a) for a in command["argv"])
        win_cmd = " ".join(self._win_arg(a) for a in command["argv"])
        posix = ["#!/bin/sh", "# Reproduces the recorded failure. Optional arguments replace the recorded command, e.g.: ./run.sh python3 fixed.py",
                 'BUNDLE="$(cd "$(dirname "$0")" && pwd)"', 'WORK="$(mktemp -d)"',
                 'if [ -d "$BUNDLE/inputs/files" ]; then cp -R "$BUNDLE/inputs/files/." "$WORK/"; fi',
                 'export THESEUS_SANDBOX="$WORK" PYTHONIOENCODING=utf-8 PYTHONUTF8=1']
        posix += ["export %s=%s" % (k, shlex.quote(v)) for k, v in sorted(env.items())]
        posix += ['cd "$WORK" || exit 99', 'if [ "$#" -gt 0 ]; then "$@" < "$BUNDLE/inputs/stdin.txt"; else',
                  "  %s < \"$BUNDLE/inputs/stdin.txt\"; fi" % posix_cmd,
                  "RC=$?", 'echo "exit code: $RC"', 'cd "$BUNDLE"; rm -rf "$WORK"', "exit $RC", ""]
        windows = ["@echo off", "rem Reproduces the recorded failure. Optional arguments replace the recorded command.",
                   "setlocal", 'set "BUNDLE=%~dp0"', 'set "WORK=%TEMP%\\repro-%RANDOM%%RANDOM%"', 'mkdir "%WORK%"',
                   'if exist "%BUNDLE%inputs\\files" xcopy /E /I /Q /Y "%BUNDLE%inputs\\files" "%WORK%" >nul',
                   'set "THESEUS_SANDBOX=%WORK%"', 'set "PYTHONIOENCODING=utf-8"', 'set "PYTHONUTF8=1"']
        windows += ['set "%s=%s"' % (k, v.replace("%", "%%")) for k, v in sorted(env.items())]
        windows += ['cd /d "%WORK%"', 'if "%~1"=="" goto recorded', '%* < "%BUNDLE%inputs\\stdin.txt"', "goto done", ":recorded",
                    '%s < "%%BUNDLE%%inputs\\stdin.txt"' % win_cmd, ":done", "set RC=%ERRORLEVEL%", "echo exit code: %RC%",
                    'cd /d "%BUNDLE%"', 'rmdir /S /Q "%WORK%"', "exit /b %RC%", ""]
        (root / "run.sh").write_bytes("\n".join(posix).encode("utf-8"))
        (root / "run.cmd").write_bytes("\r\n".join(windows).encode("utf-8"))
        try:
            (root / "run.sh").chmod(0o755)
        except OSError:
            pass
        (root / "expected_signature.json").write_text(json.dumps(signature, indent=2), encoding="utf-8")
        (root / "environment.json").write_text(json.dumps(fingerprint, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest = {"format": FORMAT, "created_at": now(), "description": description, "expected_predicate": expected_predicate,
                    "command": {"argv": command["argv"], "cwd": command["cwd"], "env": env,
                               "timeout_seconds": command["timeout_seconds"]},
                    "signature": signature, "inputs": {"stdin": "inputs/stdin.txt",
                                                       "files": sorted(state["files"])},
                    "environment": fingerprint, "minimisation": trail, "scope": SCOPE}
        body = json.dumps(manifest, indent=2, ensure_ascii=False)
        manifest["manifest_sha256"] = _sha(body)
        (root / "repro.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        (root / "README.txt").write_text(
            "Reproduction bundle (%s).\nRun run.sh (POSIX) or run.cmd (Windows); extra arguments replace the recorded command.\n"
            "Expected failure signature: see expected_signature.json. Environment recorded in environment.json.\n" % FORMAT, encoding="utf-8")
        files = sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file())
        return {"manifest_sha256": manifest["manifest_sha256"], "files": files}

    # ---- verify
    def verify(self, project_id, bundle_dir="", repro_id="", argv=None, attempts=1, timeout_seconds=None):
        self.store.project(project_id)
        if bool(bundle_dir) == bool(repro_id):
            raise ValueError("Give either bundle_dir or repro_id")
        if repro_id:
            job = self.store.job(repro_id)
            bundle_dir = job["result"].get("bundle", {}).get("directory") if job["project_id"] == project_id else None
            if not bundle_dir:
                raise LookupError("That repro job has no bundle in this project")
        root = Path(bundle_dir)
        try:
            manifest = json.loads((root / "repro.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Not a repro bundle: " + str(exc)) from exc
        if manifest.get("format") != FORMAT:
            raise ValueError("Unsupported bundle format")
        if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 10:
            raise ValueError("attempts is an integer from 1 to 10")
        state = {"stdin": (root / manifest["inputs"]["stdin"]).read_bytes().decode("utf-8"),
                 "files": {rel: (root / "inputs" / "files" / rel).read_bytes() for rel in manifest["inputs"]["files"]}, "env": {}}
        recorded = manifest["environment"]["input_sha256"]
        changed = [k for k, v in {"<stdin>": _sha(state["stdin"]), **{p: _sha(b) for p, b in state["files"].items()}}.items()
                   if recorded.get(k) != v]
        if changed:
            raise ValueError("Bundle inputs were modified after creation: " + ", ".join(changed))
        recorded_command = manifest["command"]
        if argv is not None and (not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a for a in argv)):
            raise ValueError("argv is a nonempty array of text")
        command = _command({"argv": argv or recorded_command["argv"], "cwd": recorded_command.get("cwd"),
                            "env": recorded_command["env"],
                            "timeout_seconds": timeout_seconds or recorded_command["timeout_seconds"]}, "command")
        job_id = identifier()
        budget = {"runs": 0, "max": attempts, "cache": {}}
        signature = manifest["signature"]
        runs = []
        try:
            for _ in range(attempts):
                budget["cache"].clear()
                run = self._run(job_id, command, state, budget)
                runs.append({"reproduced": matches(signature, run), "exit_code": run["exit_code"], "timed_out": run["timed_out"],
                             "stdout": _clip(run["stdout"]), "stderr": _clip(run["stderr"])})
        finally:
            with self.manager.lock:
                self.manager.cancelled.discard(job_id)
        reproduced = sum(1 for r in runs if r["reproduced"])
        now_env = self.fingerprint(command, state)
        was = manifest["environment"]
        differences = {k: {"recorded": was.get(k), "now": now_env.get(k)} for k in ("python", "node", "os", "machine")
                       if was.get(k) != now_env.get(k)}
        verdict = "reproduces" if reproduced else "no_longer_reproduces"
        result = {"kind": "repro_verify", "bundle_dir": str(root.resolve()), "manifest_sha256": manifest.get("manifest_sha256"),
                  "program": command["argv"], "program_overridden": argv is not None, "signature": signature,
                  "summary": {"verdict": verdict, "attempts": attempts, "reproduced": reproduced,
                              "still_fails_differently": bool(not reproduced and any(r["exit_code"] not in (0, None) or r["timed_out"] for r in runs)),
                              "environment_differences": differences,
                              "note": "no_longer_reproduces means the recorded signature was not observed with the bundled inputs on this run; it does not prove the defect is fixed for other inputs. " + SCOPE},
                  "runs": runs}
        return self.store.save_job(project_id, job_id, "finished", result)
