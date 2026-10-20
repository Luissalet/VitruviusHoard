"""Saved reconstruction obligations, behavior handoffs and oracle perturbations."""
import hashlib
import json
from pathlib import Path

from .comparison import observation_differences, validate_scenario
from .inspection import digest
from .store import identifier, now
from . import retained_scenarios


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Workflow:
    def __init__(self, manager):
        self.manager, self.store = manager, manager.store
        with self.store.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS reconstruction_claims (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                document TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reconstruction_handoffs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                document TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """)

    def documents(self, project_id, collection):
        self.store.project(project_id)
        table = {"claims": "reconstruction_claims", "handoffs": "reconstruction_handoffs"}[collection]
        with self.store.db() as db:
            return [json.loads(row[0]) for row in db.execute(
                f"SELECT document FROM {table} WHERE project_id=? ORDER BY rowid", (project_id,))]

    def save_claim(self, project_id, kind, statement, claim_id="", owner="", finding_ids=None,
                   scenario_ids=None, depends_on=None, resolution=""):
        if kind not in {"obligation", "unknown"} or not statement.strip():
            raise ValueError("Choose obligation or unknown and describe its behavior")
        self.store.project(project_id)
        claims = self.documents(project_id, "claims")
        key = claim_id or identifier()
        if claim_id and not any(row["id"] == key for row in claims):
            raise LookupError("Claim not found in this project")
        links = {"finding_ids": finding_ids or [], "scenario_ids": scenario_ids or [], "depends_on": depends_on or []}
        available = {"finding_ids": {row["id"] for row in self.store.items("findings", project_id)},
                     "scenario_ids": {row["id"] for row in self.store.items("scenarios", project_id)},
                     "depends_on": {row["id"] for row in claims} - {key}}
        for name, values in links.items():
            if set(values) - available[name]:
                raise ValueError("Unknown or foreign " + name)
        edges = {row["id"]: row["depends_on"] for row in claims}
        edges[key] = links["depends_on"]
        def visit(node, trail):
            if node in trail:
                raise ValueError("Claim dependencies contain a cycle")
            for parent in edges.get(node, []):
                visit(parent, trail | {node})
        visit(key, set())
        previous = next((row for row in claims if row["id"] == key), {})
        document = {"id": key, "project_id": project_id, "kind": kind, "statement": statement.strip(),
                    "owner": owner, "resolution": resolution, **links,
                    "revision": previous.get("revision", 0) + 1, "updated_at": now()}
        with self.store.db() as db:
            db.execute("INSERT INTO reconstruction_claims VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                       "document=excluded.document,updated_at=excluded.updated_at",
                       (key, project_id, json.dumps(document, ensure_ascii=False), document["updated_at"]))
        return document

    def handoff(self, project_id, builder_directory, finding_ids=None):
        project = self.store.project(project_id)
        if not project["specification"].strip():
            raise ValueError("Write a behavior specification before creating a handoff")
        path = Path(builder_directory).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError("The builder workspace must be a directory")
        findings = {row["id"]: row for row in self.store.items("findings", project_id)}
        selected = list(findings) if finding_ids is None else finding_ids
        if set(selected) - findings.keys():
            raise ValueError("A finding does not belong to this project")
        # Evidence stays with the reader. The downloadable builder document contains
        # only the supplied behavioral specification and explicitly open questions.
        builder = {"schema": "theseus/behavior-handoff-1", "name": project["name"],
                   "question": project["question"], "specification": project["specification"],
                   "claims": [{key: row[key] for key in ("id", "kind", "statement", "owner", "resolution", "depends_on")}
                              for row in self.documents(project_id, "claims")]}
        document = {"id": identifier(), "project_id": project_id, "created_at": now(),
                    "builder_directory": str(path), "builder": builder, "sha256": fingerprint(builder),
                    "reader_evidence": [findings[key] for key in selected],
                    "claim_revisions": {row["id"]: row["revision"] for row in self.documents(project_id, "claims")}}
        with self.store.db() as db:
            db.execute("INSERT INTO reconstruction_handoffs VALUES (?,?,?,?)",
                       (document["id"], project_id, json.dumps(document, ensure_ascii=False), document["created_at"]))
        return document

    def read_handoff(self, project_id, handoff_id, builder_only=False):
        document = next((row for row in self.documents(project_id, "handoffs") if row["id"] == handoff_id), None)
        if document is None:
            raise LookupError("Handoff not found in this project")
        return document["builder"] if builder_only else document

    def verify(self, project_id, handoff_id, scenario_ids=None):
        handoff = self.read_handoff(project_id, handoff_id)
        return self.manager.start(project_id, scenario_ids, context={
            "handoff_id": handoff_id, "handoff_sha256": handoff["sha256"],
            "builder_directory": handoff["builder_directory"],
            "specification_changed": handoff["builder"]["specification"] != self.store.project(project_id)["specification"]})

    def selftest(self, project_id, variants, scenario_ids=None):
        scenarios = self.store.items("scenarios", project_id)
        if scenario_ids is not None:
            selected = set(scenario_ids)
            scenarios = [row for row in scenarios if row["id"] in selected]
            if {row["id"] for row in scenarios} != selected:
                raise ValueError("A selected scenario does not belong to this project")
        if not scenarios or not variants:
            raise ValueError("Select scenarios and at least one deliberately wrong candidate")
        variants = json.loads(json.dumps(variants))
        if len({row["name"] for row in variants}) != len(variants):
            raise ValueError("Perturbations need distinct names")
        retained=all(retained_scenarios.selected(row['definition']) for row in scenarios)
        if not retained and any(retained_scenarios.selected(row['definition']) for row in scenarios):
            raise ValueError('Selftest selects either command scenarios or retained page scenarios')
        for variant in variants:
            if not variant["name"].strip():
                raise ValueError("Name each deliberate defect")
            if retained:
                if set(variant)!={'name','captures'}:
                    raise ValueError('A retained perturbation selects captures, not commands')
                captures=variant.get('captures',[])
                if not isinstance(captures,list) or len(captures)!=len(scenarios) or {row['scenario_id'] for row in captures}!={row['id'] for row in scenarios}:
                    raise ValueError('A retained perturbation needs exactly one capture for each selected scenario')
                for scenario in scenarios:
                    capture=next(row for row in captures if row['scenario_id']==scenario['id'])
                    definition={**scenario['definition'],**{key:capture[key] for key in ('candidate_job_id','candidate_sha256')}}
                    retained_scenarios.validate_bindings(self.store,project_id,definition)
            else:
                if 'candidate' not in variant:
                    raise ValueError('A command perturbation needs a candidate command')
                validate_scenario({**scenarios[0]["definition"], "candidate": variant["candidate"]})
        snapshot = [{key: row[key] for key in ("id", "name", "definition")} for row in scenarios]
        result = {"kind": "oracle_selftest", "scenarios": snapshot, "variants": variants,
                  "definition_sha256": fingerprint(snapshot), "cases": [], "detected": [], "survived": [], "invalid": []}
        job_id = identifier()
        self.store.save_job(project_id, job_id, "queued", result)
        self.manager.pool.submit(self._selftest_run, project_id, job_id, result)
        return self.store.job(job_id)

    def _selftest_run(self, project_id, job_id, result):
        try:
            self.store.save_job(project_id, job_id, "running", result)
            references = result["references"] = {}
            for scenario in result["scenarios"]:
                definition = scenario["definition"]
                reference = self.manager.observe(project_id,job_id,definition,'reference')
                references[scenario["id"]] = reference
                self.store.save_job(project_id, job_id, "running", result)
                if not retained_scenarios.selected(definition) and (observation_differences(reference, reference, definition) or (
                        reference["exit_code"] != definition.get("expected_exit_code", 0))):
                    raise ValueError("Reference fails its expectation or produces invalid/timed-out output")
            result["references"] = references
            for variant in result["variants"]:
                detected, invalid = False, False
                for scenario in result["scenarios"]:
                    definition = scenario["definition"]
                    retained=retained_scenarios.selected(definition)
                    if retained:
                        capture=next(row for row in variant['captures'] if row['scenario_id']==scenario['id'])
                        definition={**definition,**{key:capture[key] for key in ('candidate_job_id','candidate_sha256')}}
                        candidate=self.manager.observe(project_id,job_id,definition,'candidate')
                    else:
                        candidate = self.manager._execute(job_id, variant["candidate"], definition)
                    reference = references[scenario["id"]]
                    differences = observation_differences(reference, candidate, definition)
                    # A timeout cannot certify sensitivity to the intended defect.
                    if retained:
                        valid=retained_scenarios.valid_pair(reference,candidate)
                        invalid |= not valid
                        detected |= valid and bool(differences)
                    else:
                        invalid |= candidate["timed_out"] or candidate["exit_code"] != variant.get("expected_exit_code", reference["exit_code"])
                        detected |= bool(differences) and not candidate["timed_out"]
                    result["cases"].append({"variant": variant["name"], "scenario_id": scenario["id"],
                        "differences": differences, "reference": reference, "candidate": candidate})
                    if retained:
                        result['cases'][-1].update(valid=valid,sources=reference['sources']+candidate['sources'])
                    self.store.save_job(project_id, job_id, "running", result)
                result["invalid" if invalid else "detected" if detected else "survived"].append(variant["name"])
            with self.manager.lock:
                cancelled = job_id in self.manager.cancelled
            result["sensitive"] = not result["survived"] and not result["invalid"]
            self.store.save_job(project_id, job_id, "cancelled" if cancelled else "finished", result)
        except InterruptedError:
            self.store.save_job(project_id, job_id, "cancelled", result)
        except Exception as exc:
            result["error"] = type(exc).__name__ + ": " + str(exc)
            self.store.save_job(project_id, job_id, "failed", result)
        finally:
            with self.manager.lock:
                self.manager.cancelled.discard(job_id)

    def read(self, project_id):
        specification = self.store.project(project_id)["specification"]
        specification_sha = fingerprint(specification)
        claims = self.documents(project_id, "claims")
        scenarios = {row["id"]: row for row in self.store.items("scenarios", project_id)}
        jobs = self.store.items("jobs", project_id)
        file_hashes = {}
        def unchanged(observation):
            if observation.get('kind')==retained_scenarios.KIND:
                return retained_scenarios.unchanged(self.store,project_id,observation)
            for path, recorded in observation.get("file_sha256", {}).items():
                if path not in file_hashes:
                    try:
                        file_hashes[path] = digest(path)
                    except OSError:
                        file_hashes[path] = None
                if file_hashes[path] != recorded:
                    return False
            return True
        def matching(job, scenario_id, reference_only=False):
            row = next((row for row in job["result"].get("scenarios", []) if row["id"] == scenario_id), None)
            if row is None or scenario_id not in scenarios:
                return False
            if not reference_only and job["result"].get("specification_sha256") != specification_sha:
                return False
            if not reference_only and job["result"].get("reconstruction", {}).get("specification_changed"):
                return False
            left, right = dict(row["definition"]), dict(scenarios[scenario_id]["definition"])
            if reference_only:
                left.pop("candidate", None); right.pop("candidate", None)
                if retained_scenarios.selected(left):
                    for field in ('candidate_job_id','candidate_sha256'):
                        left.pop(field,None);right.pop(field,None)
            if left != right:
                return False
            if reference_only:
                return unchanged(job["result"].get("references", {}).get(scenario_id, {}))
            case = next((row for row in job["result"].get("cases", []) if row["scenario_id"] == scenario_id), None)
            return bool(case and unchanged(case["reference"]) and unchanged(case["candidate"]))
        statuses = {}
        def evaluate(claim):
            if claim["id"] in statuses:
                return statuses[claim["id"]]
            evidence, missing, failures, unchecked = [], [], [], []
            for key in claim["scenario_ids"]:
                observed = next((job for job in reversed(jobs) if job["state"] == "finished" and
                    job["result"].get("kind") != "oracle_selftest" and matching(job, key)), None)
                case = next((row for row in observed["result"].get("cases", []) if row["scenario_id"] == key), None) if observed else None
                if case is None:
                    missing.append(key)
                elif not case["passed"]:
                    failures.append(key)
                else:
                    evidence.append({"scenario_id": key, "job_id": observed["id"]})
                oracle = next((job for job in reversed(jobs) if job["state"] == "finished" and
                    job["result"].get("kind") == "oracle_selftest" and matching(job, key, True)), None)
                checked = bool(oracle and oracle["result"].get("sensitive"))
                if checked and retained_scenarios.selected(scenarios[key]['definition']):
                    # Keep the latest reference-matching selftest authoritative;
                    # a changed mutant must not fall back to an older PASS.
                    cases=[row for row in oracle['result']['cases'] if row['scenario_id']==key]
                    checked=bool(cases) and all(row.get('valid') and unchanged(row['candidate']) for row in cases)
                if not checked:
                    unchecked.append(key)
            parents = [evaluate(next(row for row in claims if row["id"] == key)) for key in claim["depends_on"]]
            if claim["kind"] == "unknown":
                status = "resolved" if claim["resolution"].strip() and (claim["finding_ids"] or evidence) else "unknown"
            else:
                status = "different" if failures else "verified" if claim["scenario_ids"] and not missing else "unknown"
            if any(row["status"] not in {"verified", "resolved"} for row in parents) and status in {"verified", "resolved"}:
                status = "unknown"
            document = {**claim, "status": status, "evidence": evidence, "unobserved": missing,
                        "different": failures, "oracle_unchecked": unchecked,
                        "complete": status in {"verified", "resolved"} and not unchecked and all(row["complete"] for row in parents)}
            statuses[claim["id"]] = document
            return document
        evaluated = [evaluate(row) for row in claims]
        handoffs = self.documents(project_id, "handoffs")
        for row in handoffs:
            row["specification_changed"] = row["builder"]["specification"] != specification
            row["claims_changed"] = row["claim_revisions"] != {claim["id"]: claim["revision"] for claim in claims}
        return {"claims": evaluated, "handoffs": handoffs, "complete": bool(evaluated) and all(row["complete"] for row in evaluated),
                "oracle_jobs": [row for row in jobs if row["result"].get("kind") == "oracle_selftest"]}
