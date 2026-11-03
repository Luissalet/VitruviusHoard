"""Legacy rules bank: business rules extracted from a legacy program, with executable checks.

A rule is a statement in the user's vocabulary plus evidence in the code. Status is
set only by running the reference program (``rules_check``): ``hypothesis`` until
every applicable case holds (``observed``) or one case breaks the predicate
(``contradicted``). ``observed`` means "held on the listed and generated cases",
never "proved". Reuses the equivalence runner for sandboxed execution, generators
and shrinking.
"""
import hashlib
import json
import re

from .equivalence import (Equivalence, _command, _clip, _substitute, expand_generators, shrink_candidates,
                          validate_case, validate_suite)
from .expressions import Expression, ExpressionError
from .store import identifier, now

STATUSES = ("hypothesis", "observed", "contradicted")
PREDICATE_NAMES = ("stdin", "args", "files", "exit_code", "stdout", "stderr", "output_files", "steps", "value", "index")
SCOPE = ("'observed' means the predicate held on every applicable listed and generated case run against the "
         "reference program in fresh sandboxes. It is evidence, not a proof; a rule without a check stays a hypothesis.")
AUTO = "rules_check"
LIMIT_KEEP = 20


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _evidence(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("evidence is an array of {artifact, file, lines, function, note}")
    out = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {"artifact", "file", "lines", "function", "note"}:
            raise ValueError("evidence entries are {artifact, file, lines, function, note}")
        if not any(str(item.get(k, "")).strip() for k in ("artifact", "file", "function")):
            raise ValueError("evidence needs an artifact, file or function reference")
        lines = item.get("lines")
        if lines is not None and not (isinstance(lines, str) and re.fullmatch(r"\d+(-\d+)?", lines.strip())):
            if not (isinstance(lines, list) and len(lines) == 2 and all(isinstance(n, int) and n > 0 for n in lines)):
                raise ValueError("evidence lines is 'N', 'N-M' or [N, M]")
        out.append({k: item[k] for k in item if item[k] not in (None, "")})
    return out


def _samples(value, what):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(v, (str, dict)) for v in value):
        raise ValueError(what + " is an array of text or objects")
    return list(value)


def validate_check(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"reference", "predicate", "when", "cases", "generators"}:
        raise ValueError("check is {reference, predicate, when, cases, generators}")
    names = PREDICATE_NAMES
    try:
        Expression(str(value.get("predicate", "")), names)
        if value.get("when") is not None:
            Expression(str(value["when"]), names)
    except ExpressionError as exc:
        raise ValueError("predicate rejected: " + str(exc)) from exc
    reference = _command(value.get("reference"), "reference")
    # Reuse suite validation for cases and generators (candidate is unused).
    suite = validate_suite({"reference": reference, "candidate": reference, "cases": value.get("cases", []),
                            "generators": value.get("generators", [])})
    return {"reference": reference, "predicate": str(value["predicate"]).strip(),
            **({"when": str(value["when"]).strip()} if value.get("when") else {}),
            "cases": suite["cases"], "generators": suite["generators"]}


def _variables(case, step_observations, generated=None):
    steps = [{"args": s_in["args"], "stdin": s_in["stdin"], "exit_code": s_out["exit_code"],
              "stdout": s_out["stdout"], "stderr": s_out["stderr"]}
             for s_in, s_out in zip(case["steps"], step_observations)]
    last_in, last_out = case["steps"][-1], step_observations[-1]
    files = {k: (v if isinstance(v, str) else "") for k, v in {**case["files"], **last_in["files"]}.items()}
    outputs = {p: f["text"] for p, f in last_out["files"].items() if f["text"] is not None}
    return {"stdin": last_in["stdin"], "args": last_in["args"], "files": files, "exit_code": last_out["exit_code"],
            "stdout": last_out["stdout"], "stderr": last_out["stderr"], "output_files": outputs, "steps": steps,
            "value": generated["value"] if generated else "", "index": generated["index"] if generated else 0}


class Rules:
    def __init__(self, manager, equivalence=None):
        self.manager, self.store = manager, manager.store
        self.equivalence = equivalence or Equivalence(manager)
        with self.store.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS theseus_rules (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                rule TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL
            );
            """)

    # ---- storage
    def _load(self, project_id, rule_id):
        with self.store.db() as db:
            row = db.execute("SELECT * FROM theseus_rules WHERE id=? AND project_id=?", (rule_id, project_id)).fetchone()
        if row is None:
            raise LookupError("Rule not found in this project")
        return {**json.loads(row["rule"]), "revision": row["revision"], "updated_at": row["updated_at"]}

    def _store(self, project_id, rule):
        stamp = now()
        with self.store.db() as db:
            previous = db.execute("SELECT project_id,revision FROM theseus_rules WHERE id=?", (rule["id"],)).fetchone()
            if previous is not None and previous[0] != project_id:
                raise ValueError("Rule belongs to another project")
            revision = (previous[1] if previous else 0) + 1
            body = {k: v for k, v in rule.items() if k not in {"revision", "updated_at"}}
            db.execute("INSERT OR REPLACE INTO theseus_rules VALUES (?,?,?,?,?)",
                       (rule["id"], project_id, json.dumps(body, ensure_ascii=False), revision, stamp))
        return self._load(project_id, rule["id"])

    # ---- public
    def save(self, project_id, statement, rule_id="", evidence=None, examples=None, counterexamples=None,
             check=None, status=None, tags=None, title=""):
        self.store.project(project_id)
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError("A rule needs a business statement")
        if status not in (None, "hypothesis"):
            raise ValueError("status is set by rules_check (hypothesis, observed or contradicted); save only proposes hypotheses")
        check = validate_check(check)
        old = self._load(project_id, rule_id) if rule_id else None
        key = rule_id or identifier()
        history = list(old["history"]) if old else []
        auto_examples = [e for e in (old["examples"] if old else []) if isinstance(e, dict) and e.get("source") == AUTO]
        auto_counter = [e for e in (old["counterexamples"] if old else []) if isinstance(e, dict) and e.get("source") == AUTO]
        state = old["status"] if old else "hypothesis"
        check_hash = _sha(check) if check else None
        if old is None:
            history.append({"at": now(), "from": None, "to": "hypothesis", "reason": "proposed"})
        elif old.get("check_sha256") != check_hash and state != "hypothesis":
            history.append({"at": now(), "from": state, "to": "hypothesis", "reason": "executable check changed; earlier results no longer apply"})
            state = "hypothesis"
        rule = {"id": key, "title": str(title).strip(), "statement": statement.strip(), "status": state,
                "evidence": _evidence(evidence), "examples": _samples(examples, "examples") + auto_examples,
                "counterexamples": _samples(counterexamples, "counterexamples") + auto_counter,
                "check": check, "check_sha256": check_hash, "tags": [str(t) for t in (tags or [])],
                "history": history, "last_check": old.get("last_check") if old and old.get("check_sha256") == check_hash else None}
        return self._store(project_id, rule)

    def read(self, project_id, rule_id=""):
        self.store.project(project_id)
        if rule_id:
            return self._load(project_id, rule_id)
        with self.store.db() as db:
            rows = db.execute("SELECT id FROM theseus_rules WHERE project_id=? ORDER BY rowid", (project_id,)).fetchall()
        rules = [self._load(project_id, r["id"]) for r in rows]
        counts = {s: sum(1 for r in rules if r["status"] == s) for s in STATUSES}
        return {"rules": [{"id": r["id"], "title": r["title"], "statement": r["statement"], "status": r["status"],
                           "has_check": r["check"] is not None, "revision": r["revision"]} for r in rules],
                "counts": counts, "scope": SCOPE}

    def delete(self, project_id, rule_id):
        self._load(project_id, rule_id)
        with self.store.db() as db:
            db.execute("DELETE FROM theseus_rules WHERE id=? AND project_id=?", (rule_id, project_id))
        return {"deleted": rule_id}

    # ---- check
    def start(self, project_id, rule_id, shrink=True, shrink_budget=100):
        rule = self._load(project_id, rule_id)
        if not rule["check"]:
            raise ValueError("This rule has no executable check; it stays a hypothesis until one is added")
        if not isinstance(shrink_budget, int) or isinstance(shrink_budget, bool) or not 1 <= shrink_budget <= 1000:
            raise ValueError("shrink_budget is an integer from 1 to 1000")
        job_id = identifier()
        result = {"kind": "rules_check", "rule_id": rule_id, "rule_revision": rule["revision"], "scope": SCOPE,
                  "options": {"shrink": bool(shrink), "shrink_budget": shrink_budget}, "summary": {}}
        self.store.save_job(project_id, job_id, "queued", result)
        self.manager.pool.submit(self._run, project_id, job_id, result, rule)
        return self.store.job(job_id)

    def _evaluate(self, job_id, check, case, pseudo, predicates):
        observation = self.equivalence.observe(job_id, check["reference"], case, pseudo)
        timed_out = [i + 1 for i, s in enumerate(observation["steps"]) if s["timed_out"]]
        base = {"case": case["name"], "generated": case.get("generated")}
        if timed_out:
            return {**base, "outcome": "invalid", "detail": "reference timed out on step(s) %s" % timed_out}
        variables = _variables(case, observation["steps"], case.get("generated"))
        summary = {"stdin": _clip(variables["stdin"]), "args": variables["args"], "exit_code": variables["exit_code"],
                  "stdout": _clip(variables["stdout"]), "stderr": _clip(variables["stderr"])}
        try:
            when, predicate = predicates
            if when is not None and not when.evaluate(variables):
                return {**base, "outcome": "skipped", "observed": summary}
            holds = bool(predicate.evaluate(variables))
        except ExpressionError as exc:
            return {**base, "outcome": "error", "detail": str(exc), "observed": summary}
        return {**base, "outcome": "held" if holds else "broken", "observed": summary}

    def _shrink(self, job_id, check, case, pseudo, predicates, budget):
        generated = case["generated"]
        generator = check["generators"][generated["generator"]]
        kind, separator = generated["kind"], generator.get("separator", ",")

        def build(value):
            built = validate_case({**_substitute(generator["template"], value, generated["index"]), "name": case["name"]})
            built["generated"] = {**generated, "value": value}
            return built
        current, runs, last = generated["value"], 0, None
        progress = True
        while progress and runs < budget:
            progress = False
            for value in shrink_candidates(kind, current, separator):
                if runs >= budget:
                    break
                runs += 1
                outcome = self._evaluate(job_id, check, build(value), pseudo, predicates)
                if outcome["outcome"] == "broken":
                    current, last, progress = value, outcome, True
                    break
        if last is None:
            last = self._evaluate(job_id, check, build(current), pseudo, predicates)
        return {"original_value": generated["value"], "minimal_value": current, "reruns": runs,
                "budget_exhausted": runs >= budget, "reexecuted_and_confirmed": last["outcome"] == "broken",
                "observed": last.get("observed"),
                "note": "Each accepted reduction re-ran the reference program and still broke the predicate; the minimum is local."}

    def _run(self, project_id, job_id, result, rule):
        try:
            self.store.save_job(project_id, job_id, "running", result)
            check, options = rule["check"], result["options"]
            predicates = (Expression(check["when"], PREDICATE_NAMES) if check.get("when") else None,
                          Expression(check["predicate"], PREDICATE_NAMES))
            pseudo = {"ignore_paths": []}
            cases = [*check["cases"], *expand_generators({"generators": check["generators"]})]
            held, skipped, errors, invalid, broken = [], [], [], [], []
            first = None
            for case in cases:
                self.equivalence._check(job_id)
                outcome = self._evaluate(job_id, check, case, pseudo, predicates)
                kind = outcome["outcome"]
                {"held": held, "skipped": skipped, "error": errors, "invalid": invalid, "broken": broken}[kind].append(outcome)
                if kind == "broken" and first is None:
                    first = outcome
                    break
            shrunk = None
            if first is not None and options["shrink"] and first.get("generated"):
                case = next(c for c in cases if c["name"] == first["case"])
                shrunk = self._shrink(job_id, check, case, pseudo, predicates, options["shrink_budget"])
            applicable = len(held) + len(broken)
            if broken:
                verdict = "contradicted"
            elif errors or invalid:
                verdict = "inconclusive"
            elif applicable == 0:
                verdict = "inconclusive"
            else:
                verdict = "all_held"
            result["summary"] = {
                "verdict": verdict, "cases": len(cases), "held": len(held), "skipped": len(skipped),
                "errors": len(errors), "invalid": len(invalid), "stopped_at_first_contradiction": bool(broken),
                "first_contradiction": first, "shrunk": shrunk,
                "errors_detail": [{"case": e["case"], "detail": e["detail"]} for e in errors[:5]],
                "invalid_detail": [{"case": e["case"], "detail": e["detail"]} for e in invalid[:5]],
                "note": {"all_held": "Promoted to observed: every applicable case held. " + SCOPE,
                         "contradicted": "A case broke the predicate; the counterexample is recorded on the rule.",
                         "inconclusive": "No status change: cases were skipped, errored, invalid or none applied."}[verdict]}
            result["rule_after"] = self._apply(project_id, rule["id"], rule["revision"], job_id, verdict, held, first, shrunk, result)
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

    def _apply(self, project_id, rule_id, revision, job_id, verdict, held, first, shrunk, result):
        rule = self._load(project_id, rule_id)
        if rule["revision"] != revision:
            return {"status": rule["status"], "note": "Rule changed while the check ran; status left untouched"}
        previous = rule["status"]
        target = {"all_held": "observed", "contradicted": "contradicted"}.get(verdict, previous)
        rule["last_check"] = {"at": now(), "job_id": job_id, "verdict": verdict, "cases": result["summary"]["cases"],
                              "held": result["summary"]["held"]}
        if target != previous:
            rule["history"].append({"at": now(), "from": previous, "to": target, "job_id": job_id,
                                    "reason": "check: %d case(s) held" % len(held) if target == "observed"
                                    else "check: counterexample in case %s" % first["case"]})
        rule["status"] = target
        rule["examples"] = [e for e in rule["examples"] if not (isinstance(e, dict) and e.get("source") == AUTO)]
        rule["counterexamples"] = [e for e in rule["counterexamples"] if not (isinstance(e, dict) and e.get("source") == AUTO)]
        if verdict == "all_held":
            rule["examples"] += [{"source": AUTO, "case": h["case"], "input": h["observed"]["stdin"], "args": h["observed"]["args"],
                                  "output": h["observed"]["stdout"]} for h in held[:3]]
        if verdict == "contradicted":
            minimal = shrunk and shrunk["minimal_value"]
            observed = (shrunk or {}).get("observed") or first["observed"]
            rule["counterexamples"].append({"source": AUTO, "case": first["case"], "input": observed["stdin"],
                                            "args": observed["args"], "output": observed["stdout"],
                                            "exit_code": observed["exit_code"], "minimal_value": minimal, "job_id": job_id})
        stored = self._store(project_id, rule)
        return {"status": stored["status"], "revision": stored["revision"]}

    # ---- export
    def export(self, project_id, rule_ids=None, statuses=None, title="Business rules of the legacy program"):
        self.store.project(project_id)
        if statuses is not None and set(statuses) - set(STATUSES):
            raise ValueError("statuses are " + ", ".join(STATUSES))
        listing = self.read(project_id)["rules"]
        rules = [self._load(project_id, r["id"]) for r in listing]
        if rule_ids:
            rules = [r for r in rules if r["id"] in set(rule_ids)]
        if statuses:
            rules = [r for r in rules if r["status"] in set(statuses)]
        return {"markdown": render_markdown(rules, title), "rules": len(rules)}


def _inline(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return "`" + text.replace("`", "'").replace("\n", "\\n") + "`" if text else "(empty)"


def _evidence_line(e):
    parts = [e.get(k) for k in ("artifact", "file") if e.get(k)]
    where = " / ".join(parts)
    if e.get("function"):
        where += (" " if where else "") + "function " + e["function"]
    lines = e.get("lines")
    if lines:
        where += ", lines " + (lines if isinstance(lines, str) else "%d-%d" % tuple(lines))
    return where + (" - " + e["note"] if e.get("note") else "")


def _sample(item):
    if isinstance(item, str):
        return item
    bits = []
    for key, label in (("case", "case"), ("input", "input"), ("args", "args"), ("output", "output"), ("exit_code", "exit"),
                       ("minimal_value", "smallest failing value"), ("note", "note")):
        if item.get(key) not in (None, "", []):
            bits.append("%s %s" % (label, _inline(item[key])))
    return "; ".join(bits) or json.dumps(item, ensure_ascii=False)


def render_markdown(rules, title="Business rules of the legacy program"):
    counts = {s: sum(1 for r in rules if r["status"] == s) for s in STATUSES}
    out = ["# " + title, "",
           "%d rule(s): %d observed, %d hypothesis, %d contradicted." % (len(rules), counts["observed"], counts["hypothesis"], counts["contradicted"]), "",
           "Status meaning: **hypothesis** = proposed, not confirmed by executions; **observed** = held on every applicable "
           "case executed against the legacy program (evidence, not proof); **contradicted** = a counterexample was found.", ""]
    for n, r in enumerate(rules, 1):
        out += ["## %d. %s" % (n, r["title"] or r["statement"][:70]), "", "**Rule:** " + r["statement"], "",
                "**Status:** " + r["status"] + (" (last checked %s)" % r["last_check"]["at"] if r.get("last_check") else ""), ""]
        out.append("**Evidence in the code:**")
        out += ["- " + _evidence_line(e) for e in r["evidence"]] or ["- none recorded"]
        out += ["", "**Examples where it holds:**"]
        out += ["- " + _sample(e) for e in r["examples"]] or ["- none recorded"]
        out += ["", "**Counterexample:**"]
        out += ["- " + _sample(e) for e in r["counterexamples"]] or ["- none found" if r["status"] == "observed" else "- none recorded"]
        if r["history"]:
            out += ["", "**History:** " + "; ".join("%s -> %s (%s)" % (h["from"] or "new", h["to"], h["reason"]) for h in r["history"])]
        out.append("")
    return "\n".join(out).rstrip() + "\n"
