"""Portable historical evidence, without original files or executable sessions."""
import base64
import binascii
import hashlib
import json
from pathlib import Path
import shutil
from jsonschema import validate, ValidationError

from .native_analysis import analysis_file
from .store import identifier, now
from .workflow import fingerprint
from . import retained_scenarios


SCHEMA = "theseus/evidence-1"
COLLECTIONS = ("artifacts", "findings", "scenarios", "jobs", "claims", "handoffs")
EXCLUDED = ["original artifact files", "native Ghidra projects", "engine sessions and credentials"]
LINKS = {"project_id", "artifact_id", "candidate_artifact_id", "job_id", "scenario_id",
         "session_id", "candidate_session_id", "reference_session_id", "source_analysis_job_id",
         "candidate_analysis_job_id", "handoff_id"}


class Evidence:
    def __init__(self, workflow):
        self.workflow, self.store = workflow, workflow.store

    def export(self, project_id):
        payload = self.store.export(project_id)
        payload.pop("schema")
        for kind in ("claims", "handoffs"):
            payload[kind] = self.workflow.documents(project_id, kind)
        with self.store.db() as db:
            payload["analysis_records"] = [dict(row) for row in db.execute(
                "SELECT r.* FROM analysis_records r JOIN jobs j ON j.id=r.job_id "
                "WHERE j.project_id=? ORDER BY r.job_id,r.section,r.ordinal", (project_id,))]
        payload["analysis_documents"], unavailable = {}, []
        for job in payload["jobs"]:
            result = job["result"]
            if result.get("kind") not in {"native_analysis", "runtime_analysis"} or not result.get("analysis_file"):
                continue
            try:
                raw = analysis_file(self.store, job["id"]).read_bytes()
                sha = hashlib.sha256(raw).hexdigest()
                if sha != result.get("analysis_sha256"):
                    raise ValueError("Retained analysis differs from its recorded SHA-256")
                json.loads(raw)
            except (OSError, ValueError) as exc:
                unavailable.append({"job_id": job["id"], "reason": str(exc)})
                continue
            payload["analysis_documents"][job["id"]] = {
                "sha256": sha, "base64": base64.b64encode(raw).decode("ascii")}
        return {"schema": SCHEMA, "created_at": now(), "payload": payload,
                "manifest": {"sha256": fingerprint(payload), "excluded": EXCLUDED,
                             "unavailable_analyses": unavailable,
                             "receipt": "Imported observations are historical; rerun scenarios to verify current behavior."}}

    def _validate(self, bundle):
        # Validate everything before writing a project or touching a bundled path.
        try:
            fields = {
                "project": ("id name question specification created_at updated_at", {"archived": {"type": "integer"}}),
                "artifacts": ("id project_id name path sha256 created_at", {"size": {"type": "integer"}, "inspection": {"type": "object"}}),
                "findings": ("id project_id artifact_id location observation interpretation source_sha256 created_at", {"source_refs": {"type": "array", "items": {"type": "object", "required": ["artifact_id", "sha256"]}}}),
                "scenarios": ("id project_id name updated_at", {"definition": {"type": "object"}}),
                "jobs": ("id project_id state created_at updated_at", {"result": {"type": "object"}}),
                "claims": ("id project_id kind statement owner resolution updated_at", {"revision": {"type": "integer"}, **{key: {"type": "array", "items": {"type": "string"}} for key in ("finding_ids", "scenario_ids", "depends_on")}}),
                "handoffs": ("id project_id created_at builder_directory sha256", {"builder": {"type": "object"}, "reader_evidence": {"type": "array"}, "claim_revisions": {"type": "object"}}),
                "analysis_records": ("job_id section record_key name search_text record", {"ordinal": {"type": "integer"}, "source_offset": {"type": ["integer", "null"]}}),
            }
            properties = {}
            for kind, (strings, extra) in fields.items():
                props = {**{key: {"type": "string"} for key in strings.split()}, **extra}
                row = {"type": "object", "properties": props, "required": list(props)}
                properties[kind] = row if kind == "project" else {"type": "array", "items": row}
            properties["claims"]["items"]["properties"]["kind"] = {"enum": ["obligation", "unknown"]}
            handoff = properties["handoffs"]["items"]["properties"]
            handoff["reader_evidence"]["items"] = properties["findings"]["items"]
            handoff["builder"] = {"type": "object", "required": ["schema", "name", "question", "specification", "claims"],
                "properties": {"schema": {"const": "theseus/behavior-handoff-1"},
                               **{key: {"type": "string"} for key in ("name", "question", "specification")},
                               "claims": {"type": "array"}}}
            properties["analysis_documents"] = {"type": "object", "additionalProperties": {
                "type": "object", "properties": {"sha256": {"type": "string"}, "base64": {"type": "string"}},
                "required": ["sha256", "base64"]}}
            validate(bundle, {"type": "object", "required": ["schema", "payload", "manifest"], "properties": {
                "schema": {"const": SCHEMA}, "manifest": {"type": "object", "required": ["sha256"]},
                "payload": {"type": "object", "properties": properties, "required": list(properties)}}})
            if bundle["schema"] != SCHEMA:
                raise ValueError("Unsupported evidence schema")
            payload = bundle["payload"]
            if fingerprint(payload) != bundle["manifest"]["sha256"]:
                raise ValueError("Evidence payload SHA-256 mismatch")
            project = payload["project"]
            if not project["name"].strip():
                raise ValueError("The imported project needs a name")
            ids = {project["id"]}
            groups = {}
            for kind in COLLECTIONS:
                rows = payload[kind]
                if not isinstance(rows, list):
                    raise ValueError("Invalid evidence collection: " + kind)
                groups[kind] = {row["id"] for row in rows}
                for row in rows:
                    if not isinstance(row["id"], str) or not row["id"] or row["id"] in ids:
                        raise ValueError("Duplicate or invalid evidence identity")
                    ids.add(row["id"])
                    if row["project_id"] != project["id"]:
                        raise ValueError("Evidence contains a foreign project")
            def links(values, kind):
                if set(values) - groups[kind]:
                    raise ValueError("Evidence contains missing " + kind + " links")
            for row in payload["findings"]:
                links([row["artifact_id"], *[r["artifact_id"] for r in row["source_refs"]]], "artifacts")
            for row in payload['scenarios']:
                definition=row['definition']
                if retained_scenarios.selected(definition):
                    retained_scenarios.validate(definition)
                    links([definition['reference_job_id'],definition['candidate_job_id']],'jobs')
            artifact_link_keys = set()
            for row in payload.get("artifact_links", []):
                links([row["parent_id"], row["child_id"]], "artifacts")
                links([row["job_id"]], "jobs")
                if not isinstance(row["source_location"], str):
                    raise ValueError("Invalid extracted artifact source location")
                key = (row["parent_id"], row["child_id"], row["job_id"])
                if key in artifact_link_keys:
                    raise ValueError("Duplicate extracted artifact relationship")
                artifact_link_keys.add(key)
            edges = {}
            for row in payload["claims"]:
                links(row["finding_ids"], "findings")
                links(row["scenario_ids"], "scenarios")
                links(row["depends_on"], "claims")
                edges[row["id"]] = row["depends_on"]
            visited = set()
            def visit(key, trail):
                if key in trail:
                    raise ValueError("Imported claim dependencies contain a cycle")
                if key not in visited:
                    for parent in edges[key]:
                        visit(parent, trail | {key})
                    visited.add(key)
            for key in edges:
                visit(key, set())
            for row in payload["handoffs"]:
                if fingerprint(row["builder"]) != row["sha256"]:
                    raise ValueError("Behavior handoff SHA-256 mismatch")
                links(row["claim_revisions"], "claims")
                links([finding["id"] for finding in row["reader_evidence"]], "findings")
            record_keys = set()
            for row in payload["analysis_records"]:
                links([row["job_id"]], "jobs")
                key = (row["job_id"], row["section"], row["record_key"])
                if key in record_keys:
                    raise ValueError("Duplicate analysis record")
                record_keys.add(key)
                json.loads(row["record"])
            jobs = {row["id"]: row for row in payload["jobs"]}
            documents = {}
            for key, entry in payload["analysis_documents"].items():
                links([key], "jobs")
                raw = base64.b64decode(entry["base64"], validate=True)
                sha = hashlib.sha256(raw).hexdigest()
                if sha != entry["sha256"] or sha != jobs[key]["result"]["analysis_sha256"]:
                    raise ValueError("Analysis document SHA-256 mismatch")
                if jobs[key]["result"]["kind"] not in {"native_analysis", "runtime_analysis"}:
                    raise ValueError("Analysis document has an incompatible job")
                json.loads(raw)
                documents[key] = raw
            return payload, ids, documents
        except (KeyError, TypeError, AttributeError, binascii.Error, UnicodeError, ValidationError) as exc:
            raise ValueError("Malformed evidence bundle: " + str(exc)) from exc

    def load(self, bundle, name=""):
        # Round-trip JSON also ensures callers cannot mutate the validated object.
        bundle = json.loads(json.dumps(bundle))
        payload, ids, documents = self._validate(bundle)
        mapping = {key: identifier() for key in ids}
        pid = mapping[payload["project"]["id"]]
        folder = self.store.directory / "imports" / pid
        analysis_root = self.store.directory / "analyses"
        written = []
        folder_created = False
        stamp = now()

        def remap_definition(definition):
            if not retained_scenarios.selected(definition):return definition
            return {key:mapping.get(value,value) if key in {'reference_job_id','candidate_job_id'} and isinstance(value,str)
                    else value for key,value in definition.items()}

        def remap(value):
            if isinstance(value, list):
                return [remap(child) for child in value]
            if isinstance(value, dict):
                # Frozen program inputs, stdout and raw observations are opaque.
                return {key: mapping.get(child, child) if key in LINKS and isinstance(child, str)
                        else remap_definition(child) if key=='definition' and isinstance(child,dict)
                        else child if key in {"definition", "reference", "candidate", "stdout", "stderr", "record"}
                        else remap(child) for key, child in value.items()}
            return value

        try:
            folder.mkdir(parents=True)
            folder_created = True
            (folder / "evidence.json").write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
            (folder / "identities.json").write_text(json.dumps({"id_map": mapping,
                "source_project_id": payload["project"]["id"], "sha256": bundle["manifest"]["sha256"]}), encoding="utf-8")
            for key, raw in documents.items():
                destination = analysis_root / mapping[key]
                destination.mkdir(parents=True)
                written.append(destination)
                (destination / "analysis.json").write_bytes(raw)
            with self.store.db() as db:
                p = payload["project"]
                db.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?)", (
                    pid, name.strip() or p["name"], p["question"], p["specification"],
                    p["archived"], p["created_at"], stamp))
                for row in payload["artifacts"]:
                    db.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?)", (
                        mapping[row["id"]], pid, row["name"], row["path"], row["sha256"], row["size"],
                        json.dumps(row["inspection"], ensure_ascii=False), row["created_at"]))
                for row in payload["findings"]:
                    db.execute("INSERT INTO findings (id,project_id,artifact_id,location,observation,interpretation,source_sha256,created_at,source_refs) VALUES (?,?,?,?,?,?,?,?,?)", (
                        mapping[row["id"]], pid, mapping[row["artifact_id"]], row["location"], row["observation"],
                        row["interpretation"], row["source_sha256"], row["created_at"], json.dumps(remap(row["source_refs"]))))
                for row in payload["scenarios"]:
                    db.execute("INSERT INTO scenarios VALUES (?,?,?,?,?)", (
                        mapping[row["id"]], pid, row["name"], json.dumps(remap_definition(row["definition"])), row["updated_at"]))
                for row in payload["jobs"]:
                    key = mapping[row["id"]]
                    result = remap(row["result"])
                    for collection in ("scenarios", "derived_artifacts"):
                        if isinstance(result.get(collection), list):
                            for case in result[collection]:
                                case["id"] = mapping.get(case.get("id"), case.get("id"))
                    # No imported receipt can certify current behavior or reopen a
                    # native project/credential file on the exporting machine.
                    result["evidence_import"] = {"source_job_id": row["id"], "source_state": row["state"],
                                                  "bundle_sha256": bundle["manifest"]["sha256"]}
                    result["folder"] = str(analysis_root / key)
                    result.pop("analysis_file", None)
                    result.pop("project_directory", None)
                    if row["id"] in documents:
                        result["analysis_file"] = str(analysis_root / key / "analysis.json")
                    if result.get("kind") == "binary_session" or (result.get("kind") == "runtime_analysis" and result.get("operation", "").startswith("frida.") and result.get("session_id")):
                        result["session_state"] = "imported"
                    db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)", (
                        key, pid, "imported", json.dumps(result, ensure_ascii=False), row["created_at"], stamp))
                for row in payload["analysis_records"]:
                    db.execute("INSERT INTO analysis_records VALUES (?,?,?,?,?,?,?,?)", (
                        mapping[row["job_id"]], row["section"], row["record_key"], row["ordinal"],
                        row["name"], row["search_text"], row["source_offset"], row["record"]))
                for row in payload.get("artifact_links", []):
                    db.execute("INSERT INTO artifact_links VALUES (?,?,?,?)", (
                        mapping[row["parent_id"]], mapping[row["child_id"]], mapping[row["job_id"]], row["source_location"]))
                for row in payload["claims"]:
                    document = remap(row)
                    document.update(id=mapping[row["id"]], **{key: [mapping[item] for item in row[key]]
                                    for key in ("finding_ids", "scenario_ids", "depends_on")})
                    db.execute("INSERT INTO reconstruction_claims VALUES (?,?,?,?)", (
                        document["id"], pid, json.dumps(document, ensure_ascii=False), row["updated_at"]))
                for row in payload["handoffs"]:
                    # The builder's immutable contract and its hash stay exact.
                    document = {**remap(row), "id": mapping[row["id"]], "builder": row["builder"],
                                "reader_evidence": [{**remap(finding), "id": mapping.get(finding["id"], finding["id"])} for finding in row["reader_evidence"]],
                                "claim_revisions": {mapping[key]: value for key, value in row["claim_revisions"].items()},
                                "evidence_import": {"source_handoff_id": row["id"], "id_map": mapping}}
                    db.execute("INSERT INTO reconstruction_handoffs VALUES (?,?,?,?)", (
                        document["id"], pid, json.dumps(document, ensure_ascii=False), row["created_at"]))
            return {"project": self.store.project(pid), "id_map": mapping, "sha256": bundle["manifest"]["sha256"],
                    "job_state": "imported", "excluded": EXCLUDED,
                    "original_bundle": f"/api/projects/{pid}/evidence/original",
                    "id_map_url": f"/api/projects/{pid}/evidence/identities"}
        except Exception:
            # These are newly generated directories, never paths from the input.
            for target, root in ([(folder, self.store.directory / "imports")] if folder_created else []) + [(p, analysis_root) for p in written]:
                if target.resolve().parent != root.resolve():
                    raise ValueError("Invalid generated evidence directory")
                if target.exists():
                    shutil.rmtree(target)
            raise

    def original(self, project_id):
        self.store.project(project_id)
        path = self.store.directory / "imports" / project_id / "evidence.json"
        if not path.is_file():
            raise LookupError("This project was not imported from an evidence bundle")
        return path

    def identities(self, project_id):
        return self.original(project_id).with_name("identities.json")
