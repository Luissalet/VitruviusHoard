"""Property and business-sequence tests (proposal 08).

A property suite names a target program (argv command or a Python callable ``module:function`` run in a subprocess),
a seeded input strategy and properties written in the safe expression language: invariants, round trips,
idempotence, metamorphic relations and reference-model comparisons. Stateful suites run random command sequences
against the real program in one sandbox (state lives in the program's files or SQLite database) and check
preconditions, a model updated by expressions and postconditions. Failures are shrunk by re-executing every
candidate and keeping the same violated property. Execution reuses the equivalence runner; there is no second
executor or expression evaluator.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import sys

from . import strategies
from .equivalence import Equivalence, LIMIT_STEPS, _clip, _command, validate_case
from .expressions import Expression, ExpressionError
from .store import identifier

SCOPE = ("No counterexample found means the properties held on the generated inputs and sequences that were executed "
         "in fresh sandboxes, with the seed and run counts shown. It is evidence, not a proof of correctness, and "
         "says nothing about Theseus completion.")
KINDS = ("invariant", "roundtrip", "idempotent", "metamorphic", "model")
ENCODE, DECODE = ("json", "text", "lines"), ("json", "text", "lines")
PSEUDO = {"ignore_paths": []}
LIMIT_RUNS, LIMIT_SEQ = 500, 30
RUNNER = ("import sys,json,importlib\n"
          "if sys.argv[2]: sys.path.insert(0, sys.argv[2])\n"
          "m,f=sys.argv[1].split(':',1)\n"
          "fn=getattr(importlib.import_module(m),f)\n"
          "print(json.dumps(fn(json.loads(sys.stdin.read())),ensure_ascii=False,default=str))\n")
NAMES = {
    "invariant": ("input", "output", "exit_code", "stdout", "stderr"),
    "roundtrip": ("input", "first", "output", "exit_code", "stdout", "stderr"),
    "idempotent": ("input", "first", "output", "exit_code", "stdout", "stderr"),
    "metamorphic": ("input", "output", "follow_input", "follow_output", "exit_code", "stdout", "stderr"),
    "model": ("input", "output", "expected", "exit_code", "stdout", "stderr"),
}
DEFAULT_EXPR = {"roundtrip": "output == input", "idempotent": "output == first",
                "metamorphic": "follow_output == output", "model": "output == expected"}


# ------------------------------------------------------------------ program specs

def program(value, where):
    """Normalise a program spec: ``{argv...}`` or ``{callable, path}`` plus encode/decode."""
    if not isinstance(value, dict):
        raise ValueError(where + " must be an object")
    value = dict(value)
    encode, decode = value.pop("encode", None), value.pop("decode", None)
    extra_args = value.pop("args", [])
    callable_name = None
    if not isinstance(extra_args, list) or any(not isinstance(a, str) for a in extra_args):
        raise ValueError(where + ".args must be an array of text")
    if "callable" in value:
        callable_name, path = value.pop("callable"), value.pop("path", "")
        target = callable_name
        if not isinstance(target, str) or target.count(":") != 1 or not all(target.split(":")):
            raise ValueError(where + ".callable is 'module:function'")
        if not isinstance(path, str):
            raise ValueError(where + ".path must be text")
        command = _command({**value, "argv": [sys.executable, "-c", RUNNER, target, os.path.abspath(path) if path else ""]}, where)
        encode, decode = "json", "json"
    else:
        command = _command(value, where)
    encode, decode = encode or "json", decode or "json"
    if encode not in ENCODE or decode not in DECODE:
        raise ValueError(where + ": encode and decode are " + ", ".join(ENCODE))
    return {"command": command, "args": extra_args, "encode": encode, "decode": decode,
            "callable": callable_name}


def encode_value(value, mode):
    if mode == "json":
        return json.dumps(value, ensure_ascii=False)
    if mode == "lines":
        return "\n".join(str(v) for v in value) if isinstance(value, list) else str(value)
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def decode_text(text, mode):
    if mode == "json":
        return json.loads(text)
    if mode == "lines":
        return text.splitlines()
    return text.rstrip("\n")


def _fingerprint(spec):
    """Argv with script files replaced by their content hash, so a renamed copy is recognised."""
    out = []
    for arg in spec["command"]["argv"] + spec["args"]:
        try:
            path = Path(arg)
            out.append("file:" + hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else arg)
        except (OSError, ValueError):
            out.append(arg)
    return out


# ------------------------------------------------------------------ validation

def _expr(source, names, where):
    try:
        return Expression(str(source), names)
    except ExpressionError as exc:
        raise ValueError(where + " rejected: " + str(exc)) from exc


def validate_property(value, index, default_input):
    if not isinstance(value, dict) or value.get("kind") not in KINDS:
        raise ValueError("property %d: kind is one of %s" % (index + 1, ", ".join(KINDS)))
    kind = value["kind"]
    name = str(value.get("name") or "%s-%d" % (kind, index + 1))
    where = "property " + name
    allowed = {"kind", "name", "when", "expr", "input"} | {"roundtrip": {"then"}, "idempotent": {"then"},
                                                           "metamorphic": {"transform"}, "model": {"reference"},
                                                           "invariant": set()}[kind]
    if set(value) - allowed:
        raise ValueError(where + " has unknown fields: " + ", ".join(sorted(set(value) - allowed)))
    source = value.get("expr") or DEFAULT_EXPR.get(kind)
    if not source:
        raise ValueError(where + " needs an expr")
    prop = {"kind": kind, "name": name, "expr": str(source).strip(),
            "input": strategies.validate(value["input"], where + ".input") if value.get("input") else default_input}
    _expr(prop["expr"], NAMES[kind], where + " expr")
    if value.get("when"):
        prop["when"] = str(value["when"]).strip()
        _expr(prop["when"], ("input",), where + " when")
    if kind == "roundtrip":
        if value.get("then") in (None, "target"):
            raise ValueError(where + ".then is the import/second program (an object); round trips need two steps")
        prop["then"] = program(value["then"], where + ".then")
    if kind == "idempotent":
        prop["then"] = None if value.get("then") in (None, "target") else program(value["then"], where + ".then")
    if kind == "metamorphic":
        if not value.get("transform"):
            raise ValueError(where + " needs a transform expression over input (for example sorted(input))")
        prop["transform"] = str(value["transform"]).strip()
        _expr(prop["transform"], ("input",), where + " transform")
    if kind == "model":
        if not value.get("reference"):
            raise ValueError(where + " needs a reference program")
        prop["reference"] = program(value["reference"], where + ".reference")
    return prop


def validate_stateful(value, index):
    if not isinstance(value, dict) or set(value) - {"name", "program", "init", "files", "db", "commands", "runs",
                                                      "max_length", "seed"}:
        raise ValueError("stateful %d is {name, program, init, files, db, commands, runs, max_length, seed}" % (index + 1))
    name = str(value.get("name") or "sequence-%d" % (index + 1))
    where = "stateful " + name
    spec = program(value.get("program"), where + ".program")
    init = value.get("init", {})
    if not isinstance(init, dict) or any(not str(k).isidentifier() for k in init):
        raise ValueError(where + ".init maps variable names to JSON values")
    json.dumps(init)
    base = validate_case({"name": "seq", "files": value.get("files"), "db": value.get("db"), "stdin": ""})
    model = tuple(init)
    commands, seen = [], set()
    for i, cmd in enumerate(value.get("commands") or []):
        if not isinstance(cmd, dict) or set(cmd) - {"name", "args", "stdin", "params", "pre", "update", "post"}:
            raise ValueError("%s command %d is {name, args, stdin, params, pre, update, post}" % (where, i + 1))
        cname = str(cmd.get("name") or "")
        if not cname or cname in seen:
            raise ValueError(where + ": every command needs a unique name")
        seen.add(cname)
        params = {str(k): strategies.validate(v, "%s %s.%s" % (where, cname, k)) for k, v in (cmd.get("params") or {}).items()}
        if any(not k.isidentifier() or k in model for k in params):
            raise ValueError("%s %s: parameter names must be identifiers distinct from model variables" % (where, cname))
        args = cmd.get("args", [])
        if not isinstance(args, list) or any(not isinstance(a, str) for a in args) or not isinstance(cmd.get("stdin", ""), str):
            raise ValueError("%s %s: args is an array of text and stdin is text" % (where, cname))
        scope = model + tuple(params)
        update = cmd.get("update", {})
        if not isinstance(update, dict) or set(update) - set(model):
            raise ValueError("%s %s: update assigns existing model variables" % (where, cname))
        post = []
        for j, p in enumerate(cmd.get("post", [])):
            entry = p if isinstance(p, dict) else {"expr": p}
            pname = str(entry.get("name") or "post-%d" % (j + 1))
            post.append({"name": pname, "expr": str(entry.get("expr", "")).strip()})
        post_names = model + tuple("old_" + m for m in model) + tuple(params) + ("exit_code", "stdout", "stderr", "output_files", "index")
        for p in post:
            _expr(p["expr"], post_names, "%s %s post %s" % (where, cname, p["name"]))
        if cmd.get("pre"):
            _expr(cmd["pre"], scope, "%s %s pre" % (where, cname))
        for var, source in update.items():
            _expr(source, scope, "%s %s update %s" % (where, cname, var))
        commands.append({"name": cname, "args": list(args), "stdin": cmd.get("stdin", ""), "params": params,
                         "pre": str(cmd["pre"]).strip() if cmd.get("pre") else None,
                         "update": {k: str(v).strip() for k, v in update.items()}, "post": post})
    if not commands:
        raise ValueError(where + " needs commands")
    runs, length = value.get("runs", 30), value.get("max_length", 8)
    for label, number, limit in (("runs", runs, LIMIT_RUNS), ("max_length", length, LIMIT_SEQ)):
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= limit:
            raise ValueError("%s.%s is an integer from 1 to %d" % (where, label, limit))
    if spec.get("callable"):
        raise ValueError(where + ": stateful suites run an argv program; a callable has no persistent state")
    return {"name": name, "program": spec, "init": copy.deepcopy(init), "case": {"files": base["files"], "db": base["db"]},
            "commands": commands, "runs": runs, "max_length": length, "seed": value.get("seed", 1)}


def validate_suite(value):
    if not isinstance(value, dict) or set(value) - {"target", "input", "properties", "stateful", "runs", "seed", "max_size"}:
        raise ValueError("suite is {target, input, properties, stateful, runs, seed, max_size}")
    runs = value.get("runs", 30)
    if isinstance(runs, bool) or not isinstance(runs, int) or not 1 <= runs <= LIMIT_RUNS:
        raise ValueError("runs is an integer from 1 to %d" % LIMIT_RUNS)
    seed = value.get("seed", 1)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    suite = {"runs": runs, "seed": seed, "properties": [], "stateful": []}
    default_input = strategies.validate(value["input"], "input") if value.get("input") else None
    props = value.get("properties") or []
    if props:
        if not value.get("target"):
            raise ValueError("properties need a target program")
        suite["target"] = program(value["target"], "target")
    for i, p in enumerate(props):
        built = validate_property(p, i, default_input)
        if built["input"] is None:
            raise ValueError("property %s needs an input strategy (suite input or its own)" % built["name"])
        suite["properties"].append(built)
    for i, s in enumerate(value.get("stateful") or []):
        suite["stateful"].append(validate_stateful(s, i))
    if not suite["properties"] and not suite["stateful"]:
        raise ValueError("A suite needs properties or stateful sequences")
    names = [p["name"] for p in suite["properties"]] + [s["name"] for s in suite["stateful"]]
    if len(names) != len(set(names)):
        raise ValueError("Property and sequence names must be unique")
    return suite


def warnings_for(suite, prop):
    """Static warnings for oracles that only compare the program with itself."""
    found = []
    target = suite.get("target")
    if prop["kind"] == "model" and target and _fingerprint(prop["reference"]) == _fingerprint(target):
        found.append({"code": "self_comparison", "message": "The reference program is the program under test (same command "
                      "or identical script bytes), so the property only compares the program with itself and cannot "
                      "catch a defect it shares with the reference."})
    if prop["kind"] == "metamorphic" and prop["transform"].replace(" ", "") == "input":
        found.append({"code": "self_comparison", "message": "The transform is the identity: the program is compared with "
                      "itself on the same input."})
    if prop["kind"] == "roundtrip" and target and _fingerprint(prop["then"]) == _fingerprint(target):
        found.append({"code": "self_comparison", "message": "The second step is the same program and arguments as the first; "
                      "a defect that is symmetric in both steps would cancel out."})
    import ast
    try:
        tree = ast.parse(prop["expr"], mode="eval").body
        if isinstance(tree, ast.Compare) and len(tree.ops) == 1 and ast.dump(tree.left) == ast.dump(tree.comparators[0]):
            found.append({"code": "tautology", "message": "Both sides of the comparison are the same expression; it can never fail."})
    except SyntaxError:
        pass
    return found


# ------------------------------------------------------------------ engine

class Properties:
    def __init__(self, manager, equivalence=None):
        self.manager, self.store = manager, manager.store
        self.equivalence = equivalence or Equivalence(manager)

    # ---- public
    def start(self, project_id, suite, shrink=True, shrink_budget=100):
        self.store.project(project_id)
        suite = validate_suite(suite)
        if not isinstance(shrink_budget, int) or isinstance(shrink_budget, bool) or not 1 <= shrink_budget <= 1000:
            raise ValueError("shrink_budget is an integer from 1 to 1000")
        job_id = identifier()
        result = {"kind": "property_run", "scope": SCOPE, "suite": suite,
                  "options": {"shrink": bool(shrink), "shrink_budget": shrink_budget}, "properties": [], "stateful": [],
                  "summary": {}}
        self.store.save_job(project_id, job_id, "queued", result)
        self.manager.pool.submit(self._run, project_id, job_id, result, suite)
        return self.store.job(job_id)

    def _run(self, project_id, job_id, result, suite):
        try:
            self.store.save_job(project_id, job_id, "running", result)
            options = result["options"]
            for prop in suite["properties"]:
                result["properties"].append(self._property(job_id, suite, prop, options))
                self.store.save_job(project_id, job_id, "running", result)
            for seq in suite["stateful"]:
                result["stateful"].append(self._stateful(job_id, seq, options))
                self.store.save_job(project_id, job_id, "running", result)
            statuses = [r["status"] for r in result["properties"] + result["stateful"]]
            if any(s in {"violated", "crash"} for s in statuses):
                verdict = "counterexample_found"
            elif any(s in {"error", "inconclusive"} for s in statuses):
                verdict = "inconclusive"
            else:
                verdict = "no_counterexample_found"
            warned = [r["name"] for r in result["properties"] if r["warnings"]]
            result["summary"] = {
                "verdict": verdict, "properties": len(result["properties"]), "sequences": len(result["stateful"]),
                "violated": [r["name"] for r in result["properties"] + result["stateful"] if r["status"] in {"violated", "crash"}],
                "self_comparison_warnings": warned,
                "note": {"counterexample_found": "At least one property failed; the minimal re-executed case is under counterexample.",
                         "inconclusive": "Some properties were skipped, errored or timed out; nothing was concluded for them.",
                         "no_counterexample_found": "No counterexample within the executed runs. " + SCOPE}[verdict]
                + (" Properties with self-comparison warnings carry little evidence: " + ", ".join(warned) if warned else "")}
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

    # ---- program execution
    def _call(self, job_id, spec, text):
        case = validate_case({"stdin": text, "args": spec["args"]})
        return self.equivalence.observe(job_id, spec["command"], case, PSEUDO)["steps"][0]

    def _decode(self, spec, run, label):
        if run["timed_out"]:
            return None, {"where": label, "detail": "timed out"}
        if run["exit_code"] != 0:
            return None, {"where": label, "detail": "exit code %s: %s" % (run["exit_code"], _clip(run["stderr"])[-300:].strip())}
        try:
            return decode_text(run["stdout"], spec["decode"]), None
        except ValueError as exc:
            return None, {"where": label, "detail": "output is not valid %s: %s" % (spec["decode"], exc)}

    # ---- properties
    def _evaluate(self, job_id, suite, prop, value):
        """Run one input through one property. Returns {status, where, detail, observed}."""
        names = NAMES[prop["kind"]]
        try:
            if prop.get("when") and not Expression(prop["when"], ("input",)).evaluate({"input": value}):
                return {"status": "skipped"}
        except ExpressionError as exc:
            return {"status": "error", "where": "when", "detail": str(exc)}
        target = suite["target"]
        first = self._call(job_id, target, encode_value(value, target["encode"]))
        output, problem = self._decode(target, first, "target")
        if problem:
            return {"status": "crash", **problem, "observed": {"stderr": _clip(first["stderr"])}}
        env = {"input": value, "output": output, "exit_code": first["exit_code"], "stdout": first["stdout"], "stderr": first["stderr"]}
        observed = {"output": output}
        kind = prop["kind"]
        if kind in {"roundtrip", "idempotent"}:
            then = prop["then"] or target
            second = self._call(job_id, then, first["stdout"])
            final, problem = self._decode(then, second, "then")
            if problem:
                return {"status": "crash", **problem, "observed": {"first": output, "stderr": _clip(second["stderr"])}}
            env.update({"first": output, "output": final, "exit_code": second["exit_code"], "stdout": second["stdout"],
                        "stderr": second["stderr"]})
            observed = {"first": output, "output": final}
        elif kind == "metamorphic":
            try:
                follow = Expression(prop["transform"], ("input",)).evaluate({"input": value})
            except ExpressionError as exc:
                return {"status": "error", "where": "transform", "detail": str(exc)}
            run = self._call(job_id, target, encode_value(follow, target["encode"]))
            follow_out, problem = self._decode(target, run, "target(transformed)")
            if problem:
                return {"status": "crash", **problem, "observed": {"follow_input": follow}}
            env.update({"follow_input": follow, "follow_output": follow_out})
            observed = {"output": output, "follow_input": follow, "follow_output": follow_out}
        elif kind == "model":
            ref = prop["reference"]
            run = self._call(job_id, ref, encode_value(value, ref["encode"]))
            expected, problem = self._decode(ref, run, "reference")
            if problem:
                return {"status": "error", **problem}
            env["expected"] = expected
            observed = {"output": output, "expected": expected}
        try:
            holds = bool(Expression(prop["expr"], names).evaluate(env))
        except ExpressionError as exc:
            return {"status": "error", "where": "expr", "detail": str(exc), "observed": observed}
        return {"status": "held" if holds else "violated", "where": "expr", "observed": observed}

    def _property(self, job_id, suite, prop, options):
        rng = random.Random("%s:%s" % (suite["seed"], prop["name"]))
        record = {"name": prop["name"], "kind": prop["kind"], "expr": prop["expr"], "warnings": warnings_for(suite, prop),
                  "runs": 0, "held": 0, "skipped": 0, "status": "inconclusive", "counterexample": None, "errors": []}
        for i in range(suite["runs"]):
            self.equivalence._check(job_id)
            value = strategies.generate(prop["input"], rng, (i + 1) / suite["runs"])
            outcome = self._evaluate(job_id, suite, prop, value)
            status = outcome["status"]
            if status == "skipped":
                record["skipped"] += 1
            elif status == "held":
                record["runs"] += 1; record["held"] += 1
            elif status == "error":
                record["errors"].append({"input": value, **{k: outcome[k] for k in ("where", "detail")}})
                break
            else:
                record["runs"] += 1
                record["status"] = status
                record["counterexample"] = self._shrink_property(job_id, suite, prop, value, outcome, options)
                return record
        if record["errors"]:
            record["status"] = "error"
        elif record["held"]:
            record["status"] = "held"
        return record

    def _shrink_property(self, job_id, suite, prop, value, outcome, options):
        current, last, runs, seen = value, outcome, 0, {json.dumps(value, sort_keys=True)}
        budget = options["shrink_budget"]
        progress = options["shrink"]
        while progress and runs < budget:
            progress = False
            for candidate in strategies.shrink(prop["input"], current):
                key = json.dumps(candidate, sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                if runs >= budget:
                    break
                runs += 1
                got = self._evaluate(job_id, suite, prop, candidate)
                if got["status"] == outcome["status"] and got.get("where") == outcome.get("where"):
                    current, last, progress = candidate, got, True
                    break
        confirm = self._evaluate(job_id, suite, prop, current)
        return {"original": value, "minimal": current, "reruns": runs, "budget_exhausted": runs >= budget and options["shrink"],
                "reexecuted_and_confirmed": confirm["status"] == outcome["status"] and confirm.get("where") == outcome.get("where"),
                "failure": outcome["status"], "where": last.get("where"), "detail": last.get("detail"),
                "observed": confirm.get("observed") or last.get("observed"),
                "note": "Every accepted reduction re-ran the program and still violated the same property; the minimum is local."}

    # ---- stateful sequences
    @staticmethod
    def _fill(text, params):
        for key, val in params.items():
            text = text.replace("{" + key + "}", val if isinstance(val, str) else json.dumps(val, ensure_ascii=False))
        return text

    @staticmethod
    def _step_model(cmd, model, params):
        """Apply the precondition and update. Returns the new model or None when not applicable."""
        env = {**model, **params}
        names = tuple(env)
        try:
            if cmd["pre"] and not Expression(cmd["pre"], names).evaluate(env):
                return None
            new = dict(model)
            for var, source in cmd["update"].items():
                new[var] = Expression(source, names).evaluate(env)
            return new
        except ExpressionError:
            return None

    def _replay(self, seq_spec, sequence):
        """Models after each step, or None when a precondition fails."""
        model, models = copy.deepcopy(seq_spec["init"]), []
        by_name = {c["name"]: c for c in seq_spec["commands"]}
        for step in sequence:
            new = self._step_model(by_name[step["command"]], model, step["params"])
            if new is None:
                return None
            models.append((model, new))
            model = new
        return models

    def _execute_sequence(self, job_id, seq_spec, sequence):
        """Run a sequence once; return the first violation or None, plus per-step observations."""
        models = self._replay(seq_spec, sequence)
        if models is None:
            return "invalid", None
        by_name = {c["name"]: c for c in seq_spec["commands"]}
        steps = [{"args": [self._fill(a, s["params"]) for a in by_name[s["command"]]["args"]],
                  "stdin": self._fill(by_name[s["command"]]["stdin"], s["params"])} for s in sequence]
        case = validate_case({"name": "sequence", "files": seq_spec["case"]["files"], "db": seq_spec["case"]["db"], "steps": steps})
        spec = seq_spec["program"]
        observed = self.equivalence.observe(job_id, {**spec["command"], "argv": spec["command"]["argv"] + spec["args"]}, case, PSEUDO)["steps"]
        for i, (step, (old, new), run) in enumerate(zip(sequence, models, observed)):
            cmd = by_name[step["command"]]
            if run["timed_out"]:
                return {"index": i, "command": cmd["name"], "property": "timeout", "detail": "timed out",
                        "observed": {"stderr": _clip(run["stderr"])}}, observed
            env = {**new, **{"old_" + k: v for k, v in old.items()}, **step["params"], "exit_code": run["exit_code"],
                   "stdout": run["stdout"], "stderr": run["stderr"], "index": i,
                   "output_files": {p: f["text"] for p, f in run["files"].items() if f["text"] is not None}}
            for post in cmd["post"]:
                try:
                    ok = bool(Expression(post["expr"], tuple(env)).evaluate(env))
                except ExpressionError as exc:
                    return {"index": i, "command": cmd["name"], "property": post["name"], "detail": "expression error: " + str(exc),
                            "observed": {"stdout": _clip(run["stdout"])}, "error": True}, observed
                if not ok:
                    return {"index": i, "command": cmd["name"], "property": post["name"], "expr": post["expr"],
                            "detail": "postcondition false", "observed": {"exit_code": run["exit_code"], "stdout": _clip(run["stdout"]),
                                                                          "stderr": _clip(run["stderr"]), "model": new}}, observed
        return None, observed

    def _generate_sequence(self, seq_spec, rng, size):
        model, sequence = copy.deepcopy(seq_spec["init"]), []
        limit = max(1, int(seq_spec["max_length"] * size + .5))
        for _ in range(rng.randint(1, limit)):
            options = []
            for cmd in seq_spec["commands"]:
                params = {k: strategies.generate(s, rng, size) for k, s in cmd["params"].items()}
                new = self._step_model(cmd, model, params)
                if new is not None:
                    options.append((cmd, params, new))
            if options:
                cmd, params, model = rng.choice(options)
                sequence.append({"command": cmd["name"], "params": params})
            else:
                break
        return sequence

    @staticmethod
    def _signature(found):
        return (found["command"], found["property"]) if found else None

    def _stateful(self, job_id, seq_spec, options):
        rng = random.Random("%s:%s" % (seq_spec["seed"], seq_spec["name"]))
        record = {"name": seq_spec["name"], "kind": "stateful", "warnings": [], "runs": 0, "status": "inconclusive",
                  "counterexample": None, "errors": [], "commands": [c["name"] for c in seq_spec["commands"]]}
        executed = 0
        for i in range(seq_spec["runs"]):
            self.equivalence._check(job_id)
            sequence = self._generate_sequence(seq_spec, rng, .4 + .6 * (i + 1) / seq_spec["runs"])
            if not sequence:
                continue
            found, _ = self._execute_sequence(job_id, seq_spec, sequence)
            executed += 1
            record["runs"] = executed
            if found and found.get("error"):
                record["status"] = "error"; record["errors"].append(found)
                return record
            if found:
                record["status"] = "crash" if found["property"] == "timeout" else "violated"
                record["counterexample"] = self._shrink_sequence(job_id, seq_spec, sequence, found, options)
                return record
        record["status"] = "held" if executed else "inconclusive"
        return record

    def _render(self, seq_spec, sequence):
        by_name = {c["name"]: c for c in seq_spec["commands"]}
        return [{"command": s["command"], "params": s["params"],
                 "argv": [self._fill(a, s["params"]) for a in by_name[s["command"]]["args"]],
                 "stdin": self._fill(by_name[s["command"]]["stdin"], s["params"])} for s in sequence]

    def _shrink_sequence(self, job_id, seq_spec, sequence, found, options):
        target, budget, runs = self._signature(found), options["shrink_budget"], 0
        current, last = sequence[:found["index"] + 1], found
        seen = set()

        def attempt(candidate):
            nonlocal runs
            key = json.dumps(candidate, sort_keys=True)
            if key in seen or not candidate:
                return None
            seen.add(key)
            if self._replay(seq_spec, candidate) is None:
                return None
            runs += 1
            got, _ = self._execute_sequence(job_id, seq_spec, candidate)
            return got if got and not got.get("error") and self._signature(got) == target else None
        # Truncation to the failing step must itself be confirmed by a re-execution.
        verified = attempt(current)
        if verified:
            last = verified
            current = current[:verified["index"] + 1]
        else:
            current, last = sequence, found
        progress = options["shrink"]
        while progress and runs < budget:
            progress = False
            n = len(current)
            chunks = sorted({max(1, n // 2), max(1, n // 4), 1}, reverse=True)
            candidates = []
            for size in chunks:
                for start in range(0, n, size):
                    candidates.append(current[:start] + current[start + size:])
            for i, step in enumerate(current):
                for key, strategy in next(c for c in seq_spec["commands"] if c["name"] == step["command"])["params"].items():
                    for smaller in strategies.shrink(strategy, step["params"][key]):
                        candidates.append(current[:i] + [{**step, "params": {**step["params"], key: smaller}}] + current[i + 1:])
            for candidate in candidates:
                if runs >= budget:
                    break
                got = attempt(candidate)
                if got:
                    current, last, progress = candidate[:got["index"] + 1], got, True
                    break
        confirm, _ = self._execute_sequence(job_id, seq_spec, current)
        return {"original": self._render(seq_spec, sequence), "minimal": self._render(seq_spec, current),
                "commands": len(current), "reruns": runs, "budget_exhausted": runs >= budget and options["shrink"],
                "reexecuted_and_confirmed": bool(confirm) and self._signature(confirm) == target,
                "failure": {k: last[k] for k in ("index", "command", "property", "detail") if k in last},
                "observed": (confirm or last).get("observed"),
                "note": "Every accepted reduction re-executed the whole sequence in a fresh sandbox and violated the same "
                        "postcondition of the same command; the minimum is local."}
