"""One persistent project store, shared by HTTP, MCP and the workbench."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier():
    return uuid.uuid4().hex


def _identity(value):
    """Readable text for an identity object such as {"kind": "id", "id": 2} or {"kind": "name", "name": "ICON"}."""
    if isinstance(value, dict):
        if isinstance(value.get("name"), str):
            return value["name"]
        if "id" in value:
            return "#" + str(value["id"])
    return value

class Store:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "uploads").mkdir(exist_ok=True)
        self.path = self.directory / "theseus.db"
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, question TEXT NOT NULL,
                specification TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
                size INTEGER NOT NULL, inspection TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                artifact_id TEXT NOT NULL REFERENCES artifacts(id), location TEXT NOT NULL,
                observation TEXT NOT NULL, interpretation TEXT NOT NULL,
                source_sha256 TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scenarios (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL, definition TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                state TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analysis_records (
                job_id TEXT NOT NULL REFERENCES jobs(id), section TEXT NOT NULL,
                record_key TEXT NOT NULL, ordinal INTEGER NOT NULL,
                name TEXT NOT NULL, search_text TEXT NOT NULL,
                source_offset INTEGER, record TEXT NOT NULL,
                PRIMARY KEY(job_id, section, record_key)
            );
            CREATE INDEX IF NOT EXISTS analysis_records_order ON analysis_records(job_id,section,ordinal);
            CREATE TABLE IF NOT EXISTS artifact_links (
                parent_id TEXT NOT NULL REFERENCES artifacts(id), child_id TEXT NOT NULL REFERENCES artifacts(id),
                job_id TEXT NOT NULL REFERENCES jobs(id), source_location TEXT NOT NULL,
                PRIMARY KEY(parent_id,child_id,job_id)
            );
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(findings)")}
            if "source_sha256" not in columns:
                db.execute("ALTER TABLE findings ADD COLUMN source_sha256 TEXT NOT NULL DEFAULT ''")
            if "source_refs" not in columns:
                db.execute("ALTER TABLE findings ADD COLUMN source_refs TEXT NOT NULL DEFAULT '[]'")
            db.execute("UPDATE findings SET source_sha256=(SELECT sha256 FROM artifacts WHERE artifacts.id=findings.artifact_id) WHERE source_sha256=''")
            db.execute("UPDATE jobs SET state='interrupted', updated_at=? WHERE state IN ('queued','running')", (now(),))

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def project(self, project_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise LookupError("Project not found")
        return dict(row)

    def projects(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM projects ORDER BY updated_at DESC")]

    def create_project(self, name, question=""):
        if not str(name).strip():
            raise ValueError("A project needs a name")
        key, stamp = identifier(), now()
        with self.db() as db:
            db.execute("INSERT INTO projects(id,name,question,created_at,updated_at) VALUES (?,?,?,?,?)",
                       (key, name.strip(), question, stamp, stamp))
        return self.project(key)

    def update_project(self, project_id, **fields):
        self.project(project_id)
        allowed = {k: v for k, v in fields.items() if k in {"name", "question", "specification", "archived"}}
        if "name" in allowed and not str(allowed["name"]).strip():
            raise ValueError("A project needs a name")
        allowed["updated_at"] = now()
        with self.db() as db:
            db.execute("UPDATE projects SET " + ",".join(f"{k}=?" for k in allowed) + " WHERE id=?",
                       [*allowed.values(), project_id])
        return self.project(project_id)

    def items(self, table, project_id):
        if table not in {"artifacts", "findings", "scenarios", "jobs"}:
            raise ValueError("Unknown collection")
        self.project(project_id)
        with self.db() as db:
            rows = [dict(r) for r in db.execute(f"SELECT * FROM {table} WHERE project_id=? ORDER BY rowid", (project_id,))]
        for row in rows:
            for key in ("inspection", "definition", "result", "source_refs"):
                if key in row:
                    row[key] = json.loads(row[key])
            if table == 'jobs': self._runtime_progress(row)
        return rows

    def artifact(self, project_id, artifact_id):
        artifact = next((r for r in self.items("artifacts", project_id) if r["id"] == artifact_id), None)
        if artifact is None:
            raise LookupError("Artifact not found in this project")
        return artifact

    def add_artifact(self, project_id, path):
        from .inspection import inspect_file
        self.project(project_id)
        path = Path(path).expanduser().resolve(strict=True)
        inspection = inspect_file(path)
        key = identifier()
        with self.db() as db:
            db.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?)", (
                key, project_id, path.name, str(path), inspection["sha256"],
                inspection["size"], json.dumps(inspection), now()))
        return self.artifact(project_id, key)

    def add_finding(self, project_id, artifact_id, location, observation, interpretation="", source_sha256="", source_refs=None):
        artifact = self.artifact(project_id, artifact_id)
        if not str(location).strip() or not str(observation).strip():
            raise ValueError("A finding needs its artifact location and observation")
        key = identifier()
        sources = json.loads(json.dumps(source_refs or []))
        for source in sources:
            self.artifact(project_id, source["artifact_id"])
            if not source.get("sha256"):
                raise ValueError("Each source reference needs its inspected content hash")
        with self.db() as db:
            db.execute("INSERT INTO findings (id,project_id,artifact_id,location,observation,interpretation,source_sha256,created_at,source_refs) VALUES (?,?,?,?,?,?,?,?,?)", (
                key, project_id, artifact["id"], location, observation, interpretation,
                source_sha256 or artifact["sha256"], now(), json.dumps(sources, ensure_ascii=False)))
        return next(r for r in self.items("findings", project_id) if r["id"] == key)

    def save_scenario(self, project_id, name, definition, scenario_id=""):
        from .comparison import validate_scenario
        self.project(project_id)
        validate_scenario(definition)
        from . import retained_scenarios
        if retained_scenarios.selected(definition):
            retained_scenarios.validate_bindings(self,project_id,definition)
        key = scenario_id or identifier()
        with self.db() as db:
            previous = db.execute("SELECT project_id FROM scenarios WHERE id=?", (key,)).fetchone()
            if previous is not None and previous[0] != project_id:
                raise ValueError("Scenario belongs to another project")
            db.execute("INSERT OR REPLACE INTO scenarios VALUES (?,?,?,?,?)",
                       (key, project_id, name.strip() or "Scenario", json.dumps(definition), now()))
        return next(r for r in self.items("scenarios", project_id) if r["id"] == key)

    def job(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise LookupError("Comparison not found")
        result = dict(row)
        result["result"] = json.loads(result["result"])
        self._runtime_progress(result)
        return result

    def _runtime_progress(self, job):
        if job['state'] not in {'queued','running'} or job['result'].get('operation')!='browser.coverage':return
        folder=self.directory/'analyses'/job['id']
        versions=sorted(folder.glob('progress-*.json'))
        path=versions[-1] if versions else folder/'progress.json'
        try:job['result']['progress']=json.loads(path.read_text(encoding='utf8'))
        except (OSError,ValueError):pass

    def save_job(self, project_id, job_id, state, result):
        self.project(project_id)
        stamp = now()
        with self.db() as db:
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                       "state=excluded.state,result=excluded.result,updated_at=excluded.updated_at",
                       (job_id, project_id, state, json.dumps(result), stamp, stamp))
        return self.job(job_id)

    def export(self, project_id):
        return {"schema": "theseus/project-1", "project": self.project(project_id),
                "artifact_links": self.artifact_links(project_id),
                **{kind: self.items(kind, project_id) for kind in ("artifacts", "findings", "scenarios", "jobs")}}

    def artifact_links(self, project_id):
        self.project(project_id)
        with self.db() as db:
            return [dict(row) for row in db.execute("SELECT l.* FROM artifact_links l JOIN artifacts a "
                "ON a.id=l.parent_id WHERE a.project_id=? ORDER BY l.rowid", (project_id,))]

    def link_artifact(self, project_id, parent_id, child_id, job_id, source_location):
        self.artifact(project_id, parent_id)
        self.artifact(project_id, child_id)
        if self.job(job_id)["project_id"] != project_id:
            raise ValueError("The extraction job belongs to another project")
        with self.db() as db:
            db.execute("INSERT INTO artifact_links VALUES (?,?,?,?)", (parent_id, child_id, job_id, source_location))

    def index_analysis(self, job_id, document):
        """Keep large analyses out of polling/tool responses; every record stays readable."""
        self.job(job_id)
        sections = {}
        projected = {}
        for section, value in document.items():
            nested=section in {"graph", "semantic_graph", "application_graph", "components", "trace", "verification", "classes", "references"}
            nested=nested or (section=='coverage' and document.get('capture_mode')=='precise-main-document-coverage-and-script-texts')
            if nested and isinstance(value, dict):
                projected[section] = {key: child for key, child in value.items() if not isinstance(child, list)}
                for key, child in value.items():
                    if isinstance(child, list):
                        projected[section + "." + key] = child
            else:
                projected[section] = value
        with self.db() as db:
            db.execute("DELETE FROM analysis_records WHERE job_id=?", (job_id,))
            for section, value in projected.items():
                rows = value if isinstance(value, list) else [value]
                sections[section] = len(rows)
                used = set()
                for ordinal, raw in enumerate(rows):
                    row = raw if isinstance(raw, dict) else {"value": raw}
                    evidence_id = row.get("evidence", {}).get("evidence_id") if isinstance(row.get("evidence"), dict) else None
                    key = str(row.get("token") or row.get("address") or row.get("id") or row.get("node_id") or row.get("relation_id") or evidence_id or ordinal)
                    if key in used:
                        key += "#" + str(ordinal)
                    used.add(key)
                    identities = [row[side] for side in ("left", "right", "reference", "candidate")
                                  if isinstance(row.get(side), dict)]
                    identity_names = [str(item.get("declaring_type", "")) + "." + str(item["name"])
                                      for item in identities if item.get("name")]
                    opcode = row["operation"].get("opcode") if isinstance(row.get("operation"), dict) else None
                    if all(isinstance(row.get(part), dict) for part in ("type", "name", "language")):
                        # Resource-style identities: type/name/language, each a text name or a numeric id.
                        name = "/".join(str(_identity(row[part])) for part in ("type", "name", "language"))
                    else:
                        name = None
                    name = name or str(_identity(row.get("name")) or row.get("package_name") or row.get("serial") or row.get("path") or row.get("url") or row.get("label") or row.get("declaring_type") or row.get("selector") or row.get("instruction") or opcode or
                               (identity_names[0].lstrip(".") if identity_names else None) or row.get("mnemonic") or section)
                    search = (name + " " + " ".join(identity_names) + " " + str(row.get("declaring_type", "")) + " " + str(row.get("selector", "")) + " " + str(row.get("kind", "")) + " " + str(evidence_id or row.get("evidence_id", ""))).casefold()
                    source = row.get("row_offset", row.get("file_offset"))
                    db.execute("INSERT INTO analysis_records VALUES (?,?,?,?,?,?,?,?)",
                        (job_id, section, key, ordinal, name, search, source, json.dumps(raw, ensure_ascii=False)))
        return sections

    def analysis_records(self, job_id, section, query="", offset=0, limit=100):
        job = self.job(job_id)
        if offset < 0 or (limit is not None and limit < 0):
            raise ValueError("Record window must be nonnegative")
        parameters = (job_id, section, str(query).casefold())
        where = "job_id=? AND section=? AND instr(search_text,?)>0"
        with self.db() as db:
            total = db.execute("SELECT count(*) FROM analysis_records WHERE " + where, parameters).fetchone()[0]
            rows = db.execute("SELECT record_key,name,source_offset,ordinal FROM analysis_records WHERE " + where +
                              " ORDER BY ordinal LIMIT ? OFFSET ?", (*parameters, -1 if limit is None else limit, offset)).fetchall()
        sources = self.analysis_sources(job, section)
        return {"job_id": job_id, "artifact_sha256": sources[0].get("sha256"), "sources": sources, "section": section,
                "total": total, "offset": offset, "has_more": offset + len(rows) < total,
                "records": [dict(row) for row in rows]}

    def analysis_record(self, job_id, section, record_key):
        job = self.job(job_id)
        with self.db() as db:
            row = db.execute("SELECT record FROM analysis_records WHERE job_id=? AND section=? AND record_key=?",
                             (job_id, section, str(record_key))).fetchone()
            if row is None and section == "source_observations":
                row = db.execute("SELECT record FROM analysis_records WHERE job_id=? AND section=? AND json_extract(record,'$.evidence.evidence_id')=?",
                                 (job_id, section, str(record_key))).fetchone()
        if row is None:
            raise LookupError("Analysis record not found")
        record = json.loads(row[0])
        sources = self.analysis_sources(job, section, record)
        return {"job_id": job_id, "artifact_id": sources[0].get("artifact_id"),
                "artifact_sha256": sources[0].get("sha256"), "sources": sources, "section": section,
                "record_key": str(record_key), "record": record}

    def analysis_sources(self, job, section, record=None):
        result = job["result"]
        if result.get("source_analyses"):
            sources = [{key: row[key] for key in ("side", "artifact_id", "sha256")} for row in result["source_analyses"]]
            selected = "candidate" if section.startswith(("right", "candidate")) else "reference" if section.startswith(("left", "reference")) else None
            return [row for row in sources if row["side"] == selected] if selected else sources
        reference = {"artifact_id": result.get("artifact_id"), "sha256": result.get("artifact_sha256")}
        if result.get("kind") == "runtime_analysis":
            reference.update(kind="runtime-observation", target=result.get("source_identity"))
        if result.get("operation") != "binary.compare":
            return [reference]
        reference["side"] = "reference"
        candidate = {"side": "candidate", "artifact_id": result.get("candidate_artifact_id") or
                     self.job(result["candidate_session_id"])["result"]["artifact_id"],
                     "sha256": result["candidate_artifact_sha256"]}
        side = record.get("side") if isinstance(record, dict) else None
        if section.startswith("candidate") or side == "candidate":
            return [candidate]
        if section.startswith("reference") or side == "reference":
            return [reference]
        return [reference, candidate]
