"""Stateful sequence testing of a real HTTP service: generate, detect, reduce, replay and export.

The executor lives in ``stateful_core`` (standard library only) so that an exported regression runs the very same
code. This module adds what needs Theseus: seeded generation with the shared strategies, reduction with the shared
delta-debugging minimiser (``repro.ddmin``) plus parameter shrinking, observed coverage, recipe storage, background
jobs, replay against another target version and the pytest export.

Scope: only the generated and executed sequences were observed. No counterexample is evidence on those runs, never a
proof of correctness. A chain whose preparation failed (start, reset, setup, reference divergence) is inconclusive.
Oracles are the recipe's: invariants, postconditions, relations with an authorised reference or between steps.
Nothing is inferred from endpoint names, and a drafted oracle is a proposal until it is executed here.
"""
import hashlib
import json
from pathlib import Path
import random
import re

from . import strategies
from . import stateful_core as core
from .equivalence import Equivalence
from .repro import BudgetExceeded, ddmin
from .store import identifier, now

SCOPE = ("Only the generated sequences listed here were executed against fresh target processes. No counterexample "
         "found is evidence on those runs, not a proof of correctness; coverage shows what never ran. A chain whose "
         "preparation failed is inconclusive, not a pass.")
EXPORT_FORMAT = "theseus-stateful-export/1"


def validate(recipe):
    try:
        return core.validate_recipe(recipe, strategies.validate)
    except core.RecipeError as exc:
        raise ValueError(str(exc)) from exc


def _key(sequence):
    return json.dumps(sequence, sort_keys=True, ensure_ascii=False)


class Coverage:
    """Observed action and transition coverage across executed generated runs."""

    def __init__(self, recipe):
        names = [a["name"] for a in recipe["actions"]]
        self.names = names
        self.actions = {n: {"considered": 0, "enabled": 0, "executed": 0, "statuses": {}, "failed": 0} for n in names}
        self.transitions = {}

    def considered(self, name, enabled):
        self.actions[name]["considered"] += 1
        self.actions[name]["enabled"] += int(enabled)

    def executed(self, previous, record):
        row = self.actions[record["action"]]
        row["executed"] += 1
        status = (record["lanes"].get("target", {}).get("response") or {}).get("status")
        key = str(status) if status is not None else "no response"
        row["statuses"][key] = row["statuses"].get(key, 0) + 1
        if record["outcome"] == "failed":
            row["failed"] += 1
        edge = (previous or "(start)") + " -> " + record["action"]
        self.transitions[edge] = self.transitions.get(edge, 0) + 1

    def report(self):
        declared = ["(start) -> " + b for b in self.names] + [a + " -> " + b for a in self.names for b in self.names]
        return {"actions": [{"action": n, **v} for n, v in self.actions.items()],
                "never_executed": [n for n, v in self.actions.items() if not v["executed"]],
                "never_enabled": [n for n, v in self.actions.items() if not v["enabled"]],
                "transitions_observed": dict(sorted(self.transitions.items())),
                "transitions_declared": len(declared),
                "transitions_not_observed": [e for e in declared if e not in self.transitions],
                "note": "Transitions not observed include pairs that the preconditions may make impossible; they are "
                        "listed as not executed, not as defects."}


class Stateful:
    def __init__(self, manager, equivalence=None):
        self.manager, self.store = manager, manager.store
        self.equivalence = equivalence or Equivalence(manager)
        with self.store.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS stateful_recipes (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL, recipe TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL
            );
            """)

    # ---- recipes
    def save_recipe(self, project_id, recipe, name="", recipe_id=""):
        self.store.project(project_id)
        normalised = validate(recipe)
        key = recipe_id or identifier()
        with self.store.db() as db:
            previous = db.execute("SELECT project_id,revision FROM stateful_recipes WHERE id=?", (key,)).fetchone()
            if previous is not None and previous[0] != project_id:
                raise ValueError("Recipe belongs to another project")
            revision = (previous[1] if previous else 0) + 1
            db.execute("INSERT OR REPLACE INTO stateful_recipes VALUES (?,?,?,?,?,?)",
                       (key, project_id, (name or normalised["name"]).strip() or "Stateful recipe",
                        json.dumps(recipe, ensure_ascii=False), revision, now()))
        return self.read_recipe(project_id, key)

    def read_recipe(self, project_id, recipe_id=""):
        self.store.project(project_id)
        with self.store.db() as db:
            if recipe_id:
                row = db.execute("SELECT * FROM stateful_recipes WHERE id=? AND project_id=?", (recipe_id, project_id)).fetchone()
                if row is None:
                    raise LookupError("Recipe not found in this project")
                return {"id": row["id"], "name": row["name"], "revision": row["revision"], "updated_at": row["updated_at"],
                        "recipe": json.loads(row["recipe"])}
            rows = db.execute("SELECT * FROM stateful_recipes WHERE project_id=? ORDER BY rowid", (project_id,)).fetchall()
        return {"recipes": [{"id": r["id"], "name": r["name"], "revision": r["revision"], "updated_at": r["updated_at"],
                             "actions": [a.get("name") for a in json.loads(r["recipe"]).get("actions", [])]} for r in rows]}

    # ---- runs
    def start(self, project_id, recipe_id="", recipe=None, runs=None, max_length=None, seed=None, shrink=True,
              shrink_budget=200):
        self.store.project(project_id)
        if bool(recipe_id) == bool(recipe):
            raise ValueError("Give either recipe_id or an inline recipe")
        revision = None
        if recipe_id:
            saved = self.read_recipe(project_id, recipe_id)
            recipe, revision = saved["recipe"], saved["revision"]
        overrides = {k: v for k, v in (("runs", runs), ("max_length", max_length), ("seed", seed)) if v is not None}
        source = {**recipe, **overrides}
        normalised = validate(source)
        if isinstance(shrink_budget, bool) or not isinstance(shrink_budget, int) or not 1 <= shrink_budget <= 2000:
            raise ValueError("shrink_budget is an integer from 1 to 2000")
        job_id = identifier()
        result = {"kind": "stateful_run", "scope": SCOPE, "recipe_id": recipe_id or None, "recipe_revision": revision,
                  "recipe": source, "recipe_sha256": hashlib.sha256(_key(source).encode()).hexdigest(),
                  "options": {"runs": normalised["runs"], "max_length": normalised["max_length"], "seed": normalised["seed"],
                              "shrink": bool(shrink), "shrink_budget": shrink_budget},
                  "runs": [], "counterexample": None, "coverage": None, "summary": {}, "warnings": []}
        for label in ("target", "reference"):
            spec = normalised[label]
            if spec and "base_url" in spec and not spec["reset"]:
                result["warnings"].append("%s is a base_url without a reset request: state is shared between runs, so a "
                                          "failure may depend on earlier runs." % label)
        self.store.save_job(project_id, job_id, "queued", result)
        self.manager.pool.submit(self._run, project_id, job_id, result, normalised)
        return self.store.job(job_id)

    def _generate_and_run(self, job_id, recipe, rng, coverage):
        """Online generation: each step is chosen among actions whose precondition holds on the live model."""
        length = rng.randint(max(1, recipe["max_length"] // 2), recipe["max_length"])
        sequence = []
        with core.Session(recipe) as session:
            try:
                session.start()
            except core.SetupFailure as exc:
                return sequence, {"outcome": "inconclusive", "reason": "setup: " + str(exc), "trace": [], "steps_run": 0}
            previous = None
            for i in range(length):
                self.equivalence._check(job_id)
                options = []
                for action in recipe["actions"]:
                    step = {"action": action["name"],
                            "params": {k: strategies.generate(s, rng, .3 + .7 * (i + 1) / length) for k, s in action["params"].items()},
                            "picks": {}}
                    for name, var in action["pick"].items():
                        values = session.main.model.get(var)
                        step["picks"][name] = rng.randrange(len(values)) if isinstance(values, list) and values else -1
                    ok = session.enabled(step)
                    coverage.considered(action["name"], ok)
                    if ok:
                        options.append(step)
                if not options:
                    break
                step = rng.choice(options)
                sequence.append(step)
                record = session.execute(step, i)
                session.trace.append(record)
                coverage.executed(previous, record)
                previous = step["action"]
                if record["outcome"] != "ok":
                    result = {"outcome": record["outcome"], "trace": session.trace, "steps_run": i + 1, "at": i,
                              "ids": session.ids}
                    if record["outcome"] == "failed":
                        result["failure"] = {"index": i, "action": record["action"], **record["violations"][0]}
                        result["violations"] = record["violations"]
                        result["signature"] = core.signature(result["failure"])
                    else:
                        result["reason"] = record.get("detail") or json.dumps(record.get("errors"), ensure_ascii=False)
                        result["errors"] = record.get("errors", [])
                    return sequence, result
            return sequence, {"outcome": "passed", "trace": session.trace, "steps_run": len(sequence), "ids": session.ids}

    def _run(self, project_id, job_id, result, recipe):
        try:
            self.store.save_job(project_id, job_id, "running", result)
            coverage = Coverage(recipe)
            counts = {"passed": 0, "failed": 0, "inconclusive": 0, "error": 0, "invalid": 0}
            for i in range(recipe["runs"]):
                self.equivalence._check(job_id)
                run_seed = recipe["seed"] + i
                rng = random.Random(run_seed)
                sequence, outcome = self._generate_and_run(job_id, recipe, rng, coverage)
                counts[outcome["outcome"]] = counts.get(outcome["outcome"], 0) + 1
                result["runs"].append({"run": i, "seed": run_seed, "steps": len(sequence), "outcome": outcome["outcome"],
                                       **({"reason": outcome["reason"]} if outcome.get("reason") else {}),
                                       **({"signature": outcome["signature"]} if outcome.get("signature") else {})})
                result["coverage"] = coverage.report()
                self.store.save_job(project_id, job_id, "running", result)
                if outcome["outcome"] == "inconclusive" and not sequence:
                    break  # the target cannot be prepared; further runs would only repeat the setup failure
                if outcome["outcome"] == "error":
                    result["error_detail"] = outcome.get("errors")
                    break
                if outcome["outcome"] == "failed":
                    result["counterexample"] = self._reduce(job_id, recipe, sequence, outcome, run_seed, result["options"])
                    break
            if result["counterexample"]:
                verdict = "counterexample_found"
            elif counts["error"] or (counts["inconclusive"] and not counts["passed"]):
                verdict = "inconclusive"
            else:
                verdict = "no_counterexample_found"
            cov = result["coverage"] or Coverage(recipe).report()
            result["summary"] = {
                "verdict": verdict, "runs_executed": len(result["runs"]), "outcomes": counts,
                "never_executed_actions": cov["never_executed"],
                "note": {"counterexample_found": "A generated sequence broke a declared oracle; the reduced sequence below was "
                                                 "re-executed on fresh processes and keeps the same failure signature.",
                         "inconclusive": "The target could not be prepared or an oracle could not be evaluated; nothing was concluded.",
                         "no_counterexample_found": "No declared oracle failed on the executed runs. " + SCOPE}[verdict]}
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

    # ---- reduction
    def _reduce(self, job_id, recipe, sequence, outcome, run_seed, options):
        target = outcome["signature"]
        budget = {"runs": 0, "max": options["shrink_budget"]}
        cache, trail = {}, []

        def execute(candidate):
            key = _key(candidate)
            if key not in cache:
                if budget["runs"] >= budget["max"]:
                    raise BudgetExceeded()
                self.equivalence._check(job_id)
                budget["runs"] += 1
                got = core.run_sequence(recipe, candidate)
                cache[key] = {k: got.get(k) for k in ("outcome", "signature", "at", "reason")}
            return cache[key]

        def holds(candidate):
            if not candidate:
                return False
            got = execute(candidate)
            return got["outcome"] == "failed" and got["signature"] == target

        current = sequence[:outcome["at"] + 1]
        exhausted = False
        try:
            by_name = {a["name"]: a for a in recipe["actions"]}
            changed = options["shrink"]
            while changed:
                changed = False
                before = len(current)
                current = ddmin(current, holds, None)
                current = current[:execute(current)["at"] + 1]
                if len(current) < before:
                    changed = True
                    trail.append({"stage": "steps (ddmin)", "before": before, "after": len(current), "runs_so_far": budget["runs"]})
                progress = True
                while progress:
                    progress = False
                    for i, step in enumerate(current):
                        action = by_name[step["action"]]
                        changes = [("params", k, c) for k, s in action["params"].items() for c in strategies.shrink(s, step["params"][k])]
                        changes += [("picks", k, j) for k, v in step["picks"].items() for j in range(0, v)]
                        for field, k, value in changes:
                            candidate = current[:i] + [{**step, field: {**step[field], k: value}}] + current[i + 1:]
                            if holds(candidate):
                                trail.append({"stage": "%s.%s of step %d" % (field, k, i + 1), "before": step[field][k],
                                              "after": value, "runs_so_far": budget["runs"]})
                                current = candidate
                                progress = changed = True
                                break
                        if progress:
                            break
        except BudgetExceeded:
            exhausted = True
        confirmations = [core.run_sequence(recipe, current) for _ in range(2)]
        confirmed = all(c["outcome"] == "failed" and c["signature"] == target for c in confirmations)
        final = confirmations[0]
        return {"seed": run_seed, "reproduce": {"seed": run_seed, "runs": 1,
                                                "note": "Running the same recipe with this seed and runs=1 regenerates the original sequence."},
                "signature": target, "original": sequence[:outcome["at"] + 1], "original_length": outcome["at"] + 1,
                "minimal": current, "minimal_length": len(current), "reductions": trail, "reruns": budget["runs"],
                "budget_exhausted": exhausted, "reexecuted_and_confirmed": confirmed,
                "failure": final.get("failure"), "violations": final.get("violations"), "trace": final.get("trace"),
                "explanation": core.describe(final), "ids_observed": final.get("ids", []),
                "note": "Each accepted reduction restarted the target, re-bound identifiers from its own responses, kept every "
                        "precondition valid and reproduced the same (action, kind, oracle) signature; the minimum is local."}

    # ---- replay
    def _counterexample(self, project_id, job_id):
        job = self.store.job(job_id)
        if job["project_id"] != project_id:
            raise LookupError("Job not found in this project")
        if job["result"].get("kind") != "stateful_run":
            raise ValueError("job_id is not a stateful run")
        return job

    def replay(self, project_id, job_id="", sequence=None, which="minimal", target=None, reference=None, recipe=None,
               attempts=1):
        self.store.project(project_id)
        if which not in ("minimal", "original"):
            raise ValueError("which is minimal or original")
        if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 10:
            raise ValueError("attempts is an integer from 1 to 10")
        source = None
        if job_id:
            job = self._counterexample(project_id, job_id)
            source = job["result"]["recipe"]
            if sequence is None:
                example = job["result"].get("counterexample")
                if not example:
                    raise ValueError("That run found no counterexample; pass a sequence explicitly")
                sequence = example[which]
        if recipe is not None:
            source = recipe
        if source is None or sequence is None:
            raise ValueError("Give job_id, or recipe with sequence")
        normalised = validate(source)
        tgt = core.validate_target(target, "target") if target else None
        ref = core.validate_target(reference, "reference") if reference else None
        if not isinstance(sequence, list) or any(not isinstance(s, dict) or "action" not in s for s in sequence):
            raise ValueError("sequence is a list of {action, params, picks}")
        runs = [core.run_sequence(normalised, sequence, tgt, ref) for _ in range(attempts)]
        outcomes = [r["outcome"] for r in runs]
        replay_id = identifier()
        result = {"kind": "stateful_replay", "scope": SCOPE, "source_job_id": job_id or None, "which": which,
                  "target": tgt or normalised["target"], "sequence": sequence, "attempts": attempts, "outcomes": outcomes,
                  "stable": len(set(outcomes)) == 1, "result": runs[0], "explanation": core.describe(runs[0]),
                  "ids_observed": [r.get("ids", []) for r in runs],
                  "note": "Identifiers were re-bound from this target's own responses; none were carried over from earlier runs."}
        if job_id:
            original = (self.store.job(job_id)["result"].get("counterexample") or {})
            if original.get("signature"):
                result["reproduces_original_signature"] = runs[0].get("signature") == original["signature"]
        self.store.save_job(project_id, replay_id, "finished", result)
        return self.store.job(replay_id)

    # ---- export
    def export(self, project_id, job_id, which="minimal", output_dir=""):
        job = self._counterexample(project_id, job_id)
        example = job["result"].get("counterexample")
        if not example:
            raise ValueError("That run found no counterexample to export")
        if which not in ("minimal", "original"):
            raise ValueError("which is minimal or original")
        recipe = job["result"]["recipe"]
        validate(recipe)
        name = re.sub(r"[^a-z0-9_]+", "_", str(recipe.get("name") or "stateful").lower()).strip("_") or "stateful"
        directory = Path(output_dir) if output_dir else self.store.directory / "stateful" / job_id / "export"
        directory.mkdir(parents=True, exist_ok=True)
        here = Path(__file__).resolve().parent
        document = {"format": EXPORT_FORMAT, "source_job_id": job_id, "which": which, "recipe": recipe,
                    "sequence": example[which], "signature": example["signature"], "seed": example["seed"],
                    "explanation": example["explanation"]}
        files = {
            "theseus_stateful_adapter.py": (here / "stateful_core.py").read_text(encoding="utf-8"),
            "theseus_expressions.py": (here / "expressions.py").read_text(encoding="utf-8"),
            "regression.json": json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            "test_%s_regression.py" % name: TEST_TEMPLATE.replace("__NAME__", name),
            "README.txt": README_TEMPLATE.replace("__NAME__", name).replace("__SIGNATURE__", json.dumps(example["signature"])),
        }
        written = []
        for filename, text in files.items():
            path = directory / filename
            path.write_text(text, encoding="utf-8", newline="\n")
            written.append({"name": filename, "path": str(path.resolve()), "sha256": hashlib.sha256(text.encode()).hexdigest(),
                            "text": text})
        return {"directory": str(directory.resolve()), "files": written, "test": "test_%s_regression.py" % name,
                "command": "python -m pytest -q test_%s_regression.py" % name,
                "override": "THESEUS_TARGET_ARGV='[\"{python}\", \"/path/to/fixed_service.py\", ...]' selects another version; "
                            "THESEUS_TARGET_URL=http://host:port targets a running service instead.",
                "note": "Standard library only (urllib/http.client, sqlite3, subprocess) plus pytest; no Theseus, network or model needed."}


TEST_TEMPLATE = '''"""Regression for a stateful failure found and reduced by Theseus (__NAME__).

Replays the reduced sequence of HTTP requests against a freshly started target and checks every oracle of the recipe.
It fails while the defect is present and passes once it is fixed. Identifiers are re-bound from the target's own
responses on every run. Requirements: Python 3.9+ and pytest; nothing else.

Select the version under test with THESEUS_TARGET_ARGV (a JSON array; {python}, {sandbox} and {port} are filled in)
or THESEUS_TARGET_URL (a running service; its state is not reset unless the recipe declares a reset request).
"""
import json
import os
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import theseus_stateful_adapter as adapter  # noqa: E402

DOCUMENT = json.loads((HERE / "regression.json").read_text(encoding="utf-8"))


def _target(recipe):
    if os.environ.get("THESEUS_TARGET_URL"):
        return adapter.validate_target({"base_url": os.environ["THESEUS_TARGET_URL"]})
    if os.environ.get("THESEUS_TARGET_ARGV"):
        return adapter.validate_target({**DOCUMENT["recipe"]["target"], "argv": json.loads(os.environ["THESEUS_TARGET_ARGV"])})
    return None


def test_reduced_sequence_keeps_every_oracle():
    recipe = adapter.validate_recipe(DOCUMENT["recipe"])
    result = adapter.run_sequence(recipe, DOCUMENT["sequence"], _target(recipe))
    if result["outcome"] == "inconclusive":
        pytest.skip("inconclusive, the chain could not be prepared: " + result.get("reason", ""))
    assert result["outcome"] != "invalid", "a precondition no longer holds on this target: " + result.get("reason", "")
    assert result["outcome"] != "error", adapter.describe(result)
    assert result["outcome"] == "passed", (
        "original failure signature " + json.dumps(DOCUMENT["signature"]) + "\\n" + adapter.describe(result))
'''

README_TEMPLATE = """Stateful regression (__NAME__)
================================

Files
  test___NAME___regression.py   pytest test that replays the reduced sequence and checks the recipe's oracles
  regression.json               recipe (target, model, actions, oracles), reduced symbolic sequence, signature
  theseus_stateful_adapter.py   executor: starts the target on a free port in a fresh sandbox, sends the
                                requests, re-binds identifiers, snapshots SQLite/files, evaluates the oracles
  theseus_expressions.py        safe expression evaluator used by the oracles (ast whitelist, no eval)

Run
  python -m pytest -q test___NAME___regression.py

Original failure signature (action, kind, oracle): __SIGNATURE__
The test fails while that defect (or another oracle violation) is present and passes when every oracle holds.
An inconclusive start (target did not come up, setup failed) is reported as a skip, never as a pass.
"""
