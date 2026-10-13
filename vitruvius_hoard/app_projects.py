"""Versioned source projects, standalone export and owned preview processes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath

from .app_runtime import validate_spec
from .hoard_link.atomic import write_json_atomic

_TEMPLATES = [
    {"id": "work-board", "name": "Work board", "name_es": "Tablero de trabajo", "accent": "#355c7d", "fields": [
        {"name": "title", "label": "Task", "type": "text"}, {"name": "status", "label": "Status", "type": "choice", "choices": ["To do", "In progress", "Done"]}, {"name": "notes", "label": "Notes", "type": "text", "required": False}]},
    {"id": "reference-library", "name": "Reference library", "name_es": "Biblioteca de referencias", "accent": "#6b583a", "fields": [
        {"name": "title", "label": "Title", "type": "text"}, {"name": "category", "label": "Category", "type": "text"}, {"name": "source", "label": "Source", "type": "text", "required": False}, {"name": "reviewed", "label": "Reviewed", "type": "boolean"}]},
    {"id": "inventory", "name": "Inventory", "name_es": "Inventario", "accent": "#286c56", "fields": [
        {"name": "name", "label": "Item", "type": "text"}, {"name": "quantity", "label": "Quantity", "type": "number"}, {"name": "location", "label": "Location", "type": "text"}]},
]


def templates():
    return json.loads(json.dumps(_TEMPLATES))


def _literal(value):
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def starter_files(name, template="work-board", description="", accent=None, fields=None):
    selected = next((row for row in templates() if row["id"] == template), None)
    if not selected:
        raise ValueError("Unknown application template")
    colour = accent or selected["accent"]
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
        raise ValueError("accent must be a six-digit hex colour")
    spec = validate_spec({"format": "vitruvius-app/v1", "name": name, "description": description, "fields": fields if fields is not None else selected["fields"], "template": template})
    properties = []
    for field in spec["fields"]:
        kind = field["type"]
        typed = " | ".join(_literal(choice) for choice in field["choices"]) if kind == "choice" else {"text": "string", "number": "number", "boolean": "boolean"}[kind]
        properties.append(f'  {_literal(field["name"])}{"" if field.get("required", True) else "?"}: {typed};')
    contracts = "export interface RecordInput {\n" + "\n".join(properties) + "\n}\nexport interface AppRecord extends RecordInput { id: string; }\nexport type AppRoute = '/' | '/records' | `/records/${string}`;\n"
    css = f":root{{--accent:{colour};color-scheme:light}}" + """*{box-sizing:border-box}body{margin:0;background:#f4f3ed;color:#222d30;font:16px/1.6 system-ui,sans-serif}header,main,footer{max-width:1100px;margin:auto;padding:24px clamp(20px,5vw,56px)}header{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap;border-bottom:1px solid #c8cec9}nav{display:flex;gap:24px}a{color:#234a61;text-underline-offset:4px}h1{overflow-wrap:anywhere;font:clamp(34px,5vw,64px)/1.1 Georgia,serif;margin:16px 0}h2{font:28px/1.2 Georgia,serif;margin:32px 0 16px}p{max-width:65ch}section{margin-top:28px}button,input,select{font:inherit;min-height:44px}button{border:1px solid #233e3c;background:#e3eae2;color:#213c37;padding:8px 18px;cursor:pointer}input,select{width:100%;border:1px solid #8a9992;padding:8px;background:#fff;color:#222d30}input[type=checkbox]{width:22px;height:22px;min-height:22px}label{overflow-wrap:anywhere;display:flex;flex-direction:column;gap:6px}#record-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));align-items:end;gap:16px;margin:24px 0}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;background:#fff}th,td{text-align:left;vertical-align:top;border-bottom:1px solid #d2d9d3;padding:12px;overflow-wrap:anywhere}th{font-size:13px;font-weight:600;letter-spacing:.03em}td:first-child{font-weight:600}.search{display:flex;gap:12px;flex-wrap:wrap}.search label{flex:1;min-width:min(220px,100%)}.empty{padding:20px;background:#e8eee7}#status{min-height:24px;color:#234a61}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--accent);outline-offset:4px}::selection{background:#c9ddce;color:#182923}@media(max-width:600px){header{display:block}nav{margin-top:12px}th,td{padding:9px;font-size:14px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}"""
    if template == "reference-library":
        css += "body{background:#eee8dd}header{border-bottom:2px solid #6b583a}h1{font-style:italic}table{background:#faf7ef}"
    elif template == "inventory":
        css += "body{background:#eaf0ed}h1{font-family:system-ui,sans-serif;font-size:clamp(32px,5vw,58px);font-weight:650}table{border-top:3px solid #286c56}"
    api = '''/** @typedef {import('../contracts').RecordInput} RecordInput */
/** @typedef {import('../contracts').AppRecord} AppRecord */
/** @param {string} path @param {string} method @param {unknown} [body] @returns {Promise<any>} */
async function request(path, method, body) {
  const response = await fetch(path, {method, headers: {'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed: ${response.status}`);
  return result;
}
/** @param {RecordInput} input @returns {Promise<AppRecord>} */
export const createRecord = (input) => request('/actions/create', 'POST', input);
/** @param {string} id @param {Partial<RecordInput>} input @returns {Promise<AppRecord>} */
export const updateRecord = (id, input) => request('/actions/update', 'POST', {...input, id});
/** @param {string} id @returns {Promise<{ok:boolean}>} */
export const deleteRecord = (id) => request('/actions/delete', 'POST', {id});
/** @param {string} id @returns {`/records/${string}`} */
export const recordPath = (id) => `/records/${encodeURIComponent(id)}`;
'''
    client = '''import {createRecord, updateRecord, deleteRecord, recordPath} from './api.js';
const form = document.querySelector('#record-form');
const status = document.querySelector('#status');
const dirty = new Set();
if (form) for (const event of ['input', 'change']) form.addEventListener(event, e => { if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) dirty.add(e.target.name); });
if (form instanceof HTMLFormElement && status) {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('button');
    if (button) button.disabled = true;
    try {
      const spec = {fields: JSON.parse(form.dataset.fields || '[]')};
      const values = Object.fromEntries(spec.fields.map(field => {
        const input = form.elements.namedItem(field.name);
        if (!(input instanceof HTMLInputElement || input instanceof HTMLSelectElement)) throw new Error('Missing field: '+field.name);
        return [field.name, field.type === 'boolean' ? input instanceof HTMLInputElement && input.checked : field.type === 'number' ? Number(input.value) : input.value];
      }));
      const id = form.dataset.id;
      const captured = JSON.stringify(values);
      const row = id ? await updateRecord(id, Object.fromEntries(Object.entries(values).filter(([name]) => dirty.has(name)))) : await createRecord(values);
      form.dataset.id = row.id;
      const now = Object.fromEntries(spec.fields.map(field => { const input = form.elements.namedItem(field.name); return [field.name, input instanceof HTMLInputElement || input instanceof HTMLSelectElement ? field.type === 'boolean' ? input instanceof HTMLInputElement && input.checked : field.type === 'number' ? Number(input.value) : input.value : null]; }));
      if (JSON.stringify(now) === captured) location.assign(recordPath(row.id));
      else status.textContent = 'Submitted values saved. Your newer edits are still here.';
    } catch (error) { status.textContent = error instanceof Error ? error.message : String(error); }
    finally { if (button) button.disabled = false; }
  });
}
const remove = document.querySelector('#delete-record');
if (remove instanceof HTMLButtonElement && status) remove.addEventListener('click', async () => {
  remove.disabled = true;
  try { await deleteRecord(remove.dataset.id || ''); location.assign('/records'); }
  catch (error) { status.textContent = error instanceof Error ? error.message : String(error); remove.disabled = false; }
});
'''
    return {
        "project.json": json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
        "server.py": Path(__file__).with_name("app_runtime.py").read_text(encoding="utf-8"),
        "layout.html": '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{{name}}</title><link rel="stylesheet" href="/assets/style.css"></head><body><header><strong>{{name}}</strong><nav aria-label="Application"><a href="/">Overview</a><a href="/records">Records</a></nav></header><main>{{content}}</main><footer><p id="status" role="status" aria-live="polite"></p></footer><script type="module" src="/assets/client.js"></script></body></html>',
        "pages/index.html": '<h1>{{name}}</h1><p>{{description}}</p><section><h2>Overview</h2><p>{{count}} records in this application.</p><a href="/records">Manage records</a></section><section><h2>Current records</h2><div class="table-wrap">{{table}}</div></section>',
        "pages/records/index.html": '<h1>Records</h1><form class="search" action="/records" method="get"><label>Search records<input name="q" value="{{query}}" type="search"></label><button type="submit">Search</button></form><section><h2>Add a record</h2>{{form}}</section><section><h2>Saved records</h2><div class="table-wrap">{{table}}</div></section>',
        "pages/records/[id].html": '<h1>{{record_title}}</h1><p><a href="/records">Back to records</a></p><section><h2>Edit record</h2>{{form}}</section>',
        "assets/style.css": css, "assets/api.js": api, "assets/client.js": client,
        "contracts.d.ts": contracts,
        "tsconfig.json": json.dumps({"compilerOptions": {"allowJs": True, "checkJs": True, "noEmit": True, "target": "ES2022", "module": "ESNext", "moduleResolution": "Bundler", "lib": ["ES2022", "DOM"]}, "include": ["assets/api.js", "contracts.d.ts"]}, indent=2),
        "Dockerfile": 'FROM python:3.13-slim\nWORKDIR /app\nCOPY . .\nEXPOSE 3000\nCMD ["python", "server.py", "--host", "0.0.0.0", "--port", "3000"]\n',
        "LICENSE": Path(__file__).parent.parent.joinpath("LICENSE").read_text(encoding="utf-8"),
        "README.md": f'# {name}\n\nRun `python server.py --port 3000` and open http://127.0.0.1:3000. Python 3.10+; no packages or workbench required. SQLite data is stored in data/app.db. Edit pages/*.html, layout.html, assets and project.json; restart after editing to use the changed source.\n\nPages are discovered from the pages directory, with index.html and [parameter].html paths. JSON operations are available through /api/records and POST /actions/create, /actions/update, /actions/delete. /api/schema and /api/routes describe the project. contracts.d.ts and the annotated API client share the field types; run `tsc -p tsconfig.json` if TypeScript is installed.\n\nGenerated application source belongs to the exported project. It uses an ordinary local HTTP server, without account, authentication or external service setup. Add production infrastructure appropriate to your deployment.\n',
    }


class AppProjects:
    def __init__(self, data_dir):
        self.root = Path(data_dir) / "app-projects"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.processes = {}

    def _directory(self, id):
        if not re.fullmatch(r"[a-f0-9]{16}", id):
            raise ValueError("Invalid project id")
        path = self.root / id
        if not (path / "project-index.json").is_file():
            raise LookupError("Application project not found")
        return path

    def get(self, id, revision=None):
        with self.lock:
            root = self._directory(id)
            index = json.loads((root / "project-index.json").read_text(encoding="utf-8"))
            selected = revision or index["revision"]
            if selected not in index["revisions"]:
                raise LookupError("Project revision not found")
            snapshot = json.loads((root / "revisions" / selected / "snapshot.json").read_text(encoding="utf-8"))
            return {**index, "selected_revision": selected, "files": snapshot["files"], "source_sha256": snapshot["source_sha256"], "preview": self.status(id)}

    def list(self):
        with self.lock:
            result = []
            for path in sorted(self.root.glob("*/project-index.json")):
                item = json.loads(path.read_text(encoding="utf-8"))
                result.append({**item, "preview": self.status(item["id"])})
            return sorted(result, key=lambda item: item["updated_ts"], reverse=True)

    def _save(self, root, index, files):
        destinations = set()
        for name, source in files.items():
            path = PurePosixPath(name)
            if not isinstance(source, str) or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or not path.parts:
                raise ValueError("Project files need relative paths and text content")
            destination = os.path.normcase(str(Path(*path.parts)))
            if destination in destinations:
                raise ValueError("Project file paths refer to the same file: " + name)
            destinations.add(destination)
        required = {"project.json", "server.py", "layout.html", "pages/index.html"}
        if not required.issubset(files):
            raise ValueError("Project needs project.json, server.py, layout.html and pages/index.html")
        spec = validate_spec(json.loads(files["project.json"]))
        serialized = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        revision = digest[:20]
        directory = root / "revisions" / revision
        if not directory.exists():
            stage = root / "revisions" / (".stage-" + uuid.uuid4().hex)
            stage.mkdir(parents=True)
            try:
                for name, source in files.items():
                    path = stage / "source" / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(source.encode("utf-8"))
                write_json_atomic(stage / "snapshot.json", {"files": files, "source_sha256": digest})
                stage.rename(directory)
            finally:
                if stage.exists() and stage.resolve().parent == (root / "revisions").resolve():
                    shutil.rmtree(stage)
        updated = {**index, "name": spec["name"], "revision": revision, "updated_ts": time.time(), "revisions": list(dict.fromkeys(index.get("revisions", []) + [revision]))}
        write_json_atomic(root / "project-index.json", updated)
        return self.get(updated["id"])

    def create(self, name, template="work-board", description="", accent=None, fields=None):
        files = starter_files(name, template, description, accent, fields)
        with self.lock:
            id = uuid.uuid4().hex[:16]
            root = self.root / id
            root.mkdir()
            index = {"id": id, "name": name, "template": template, "created_ts": time.time(), "revisions": []}
            return self._save(root, index, files)

    def update(self, id, files, expected_revision):
        with self.lock:
            current = self.get(id)
            if current["revision"] != expected_revision:
                baseline = self.get(id, expected_revision)
                conflicts = [name for name, content in files.items() if baseline["files"].get(name) != current["files"].get(name) and content != current["files"].get(name)]
                if conflicts:
                    raise ValueError("Project files changed: " + ", ".join(conflicts) + "; read their current source before applying edits")
            merged = {**current["files"], **files}
            return self._save(self._directory(id), {k: v for k, v in current.items() if k not in ("files", "selected_revision", "source_sha256", "preview")}, merged)

    def status(self, id):
        item = self.processes.get(id)
        if not item:
            return {"state": "stopped"}
        alive = item["process"].poll() is None
        return {"state": "running" if alive else "stopped", "revision": item["revision"], "url": item["url"] if alive else None,
                "pid": item["process"].pid if alive else None}

    def stop(self, id):
        with self.lock:
            item = self.processes.pop(id, None)
            if item:
                process = item["process"]
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                item["log"].close()
            return {"state": "stopped"}

    def preview(self, id, revision=None):
        with self.lock:
            project = self.get(id, revision)
            selected = project["selected_revision"]
            status = self.status(id)
            if status["state"] == "running" and status["revision"] == selected:
                return status
            self.stop(id)
            root = self._directory(id)
            run = root / "runs" / uuid.uuid4().hex
            run.mkdir(parents=True)
            ready = run / "ready.json"
            log = (run / "output.log").open("wb")
            # One captured source dictionary owns both the process and its receipt.
            source = run / "source"
            for name, content in project["files"].items():
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content.encode("utf-8"))
            process = subprocess.Popen([sys.executable, "-u", str(source / "server.py"), "--port", "0", "--database", str(root / "data" / "app.db"), "--ready-file", str(ready), "--revision", selected],
                                       cwd=source, stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.processes[id] = {"process": process, "log": log, "revision": selected, "url": None}
            deadline = time.monotonic() + 15
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            if not ready.exists():
                self.stop(id)
                raise ValueError("Application did not start: " + (run / "output.log").read_text(encoding="utf-8", errors="replace"))
            receipt = json.loads(ready.read_text(encoding="utf-8"))
            self.processes[id]["url"] = receipt["url"]
            return self.status(id)

    def export(self, id, revision=None, include_data=False):
        with self.lock:
            project = self.get(id, revision)
            root = self._directory(id)
            out = root / "exports" / (uuid.uuid4().hex + ".zip")
            out.parent.mkdir(exist_ok=True)
            database = root / "data" / "app.db"
            actual_data = include_data and database.is_file()
            with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for name, content in project["files"].items():
                    bundle.writestr(name, content.encode("utf-8"))
                bundle.writestr("vitruvius-export.json", json.dumps({"format": "vitruvius-app-export/v1", "project_id": id, "revision": project["selected_revision"], "source_sha256": project["source_sha256"], "includes_data": actual_data}, indent=2))
                if actual_data:
                    snapshot = out.with_suffix(".db")
                    with closing(sqlite3.connect(database)) as live, closing(sqlite3.connect(snapshot)) as copied:
                        live.backup(copied)
                    bundle.write(snapshot, "data/app.db")
                    snapshot.unlink()
            return {"id": id, "revision": project["selected_revision"], "source_sha256": project["source_sha256"], "path": str(out), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "includes_data": actual_data}

    def close(self):
        for id in list(self.processes):
            self.stop(id)
