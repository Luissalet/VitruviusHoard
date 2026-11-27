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
import tempfile
import threading
import time
import uuid
import zipfile
from contextlib import closing, contextmanager
from http.client import HTTPConnection, HTTPException
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from .app_canvas import CanvasSessions
from .app_canvas_edits import canvas_token_scale, plan_canvas_edit
from .app_materials import describe_materials
from .app_preview import PreviewProxy
from . import app_critique_loop
from .app_revision_events import RevisionEvents, revision_change
from .app_runtime import validate_spec
from .app_source_map import SourceMapError, edit_source, first_changed_source, source_count, source_position
from .booking import TEMPLATE as BOOKING_TEMPLATE, site_files
from .hoard_link.agentkit import AppError
from .hoard_link.atomic import write_json_atomic
from .static_page import TEMPLATE as STATIC_PAGE_TEMPLATE, page_files as static_page_files
from .transfer_assistant.embedded import embedded_assistant_assets
from .transfer_assistant import ENTRY as TRANSFER_ASSISTANT_ENTRY
from .transfer_assistant import FORM_ENTRY, form_assistant_files

# Previously shipped starter runtimes, normalized by starter_files' text read.
# These copies predate the optional template hook.
_LEGACY_STARTER_RUNTIMES = {
    "29bbdc519e5e42838904793f190e085eca277bf4377b55219becb615cd205fd9",
    "a8eb8d4b158b8147d374880480f02e74e1218c9b0e0a54e0ffaa5facca855ca9",
}
_PROJECT_SCAFFOLD_FILES = {"project.json", "layout.html", "pages/index.html"}

_TEMPLATES = [
    {"id": "work-board", "name": "Work board", "name_es": "Tablero de trabajo", "accent": "#355c7d", "fields": [
        {"name": "title", "label": "Task", "type": "text"}, {"name": "status", "label": "Status", "type": "choice", "choices": ["To do", "In progress", "Done"]}, {"name": "notes", "label": "Notes", "type": "text", "required": False}]},
    {"id": "reference-library", "name": "Reference library", "name_es": "Biblioteca de referencias", "accent": "#6b583a", "fields": [
        {"name": "title", "label": "Title", "type": "text"}, {"name": "category", "label": "Category", "type": "text"}, {"name": "source", "label": "Source", "type": "text", "required": False}, {"name": "reviewed", "label": "Reviewed", "type": "boolean"}]},
    {"id": "inventory", "name": "Inventory", "name_es": "Inventario", "accent": "#286c56", "fields": [
        {"name": "name", "label": "Item", "type": "text"}, {"name": "quantity", "label": "Quantity", "type": "number"}, {"name": "location", "label": "Location", "type": "text"}]},
    BOOKING_TEMPLATE,
    STATIC_PAGE_TEMPLATE,
]


def templates():
    return json.loads(json.dumps(_TEMPLATES))


def _literal(value):
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _standalone_runtime():
    return Path(__file__).with_name("app_runtime.py").read_text(encoding="utf-8")


def starter_files(name, template="work-board", description="", accent=None, fields=None, items=None, lang="en",
                  description_es=None):
    selected = next((row for row in templates() if row["id"] == template), None)
    if not selected:
        raise ValueError("Unknown application template")
    colour = accent or selected["accent"]
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
        raise ValueError("accent must be a six-digit hex colour")
    static = template == STATIC_PAGE_TEMPLATE["id"]
    page_description = description_es if static and lang == "es" and description_es is not None else description
    spec = validate_spec({"format": "vitruvius-app/v1", "name": name, "description": page_description, "fields": fields if fields is not None else selected["fields"], "template": template})
    common = {
        "project.json": json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
        "server.py": _standalone_runtime(),
        "Dockerfile": 'FROM python:3.13-slim\nWORKDIR /app\nCOPY . .\nEXPOSE 3000\nCMD ["python", "server.py", "--host", "0.0.0.0", "--port", "3000"]\n',
        "LICENSE": Path(__file__).with_name("LICENSE").read_text(encoding="utf-8"),
    }
    if static:
        return {**common, **static_page_files(name, colour, lang, page_description)}
    properties = []
    for field in spec["fields"]:
        kind = field["type"]
        typed = " | ".join(_literal(choice) for choice in field["choices"]) if kind == "choice" else {"text": "string", "number": "number", "boolean": "boolean"}[kind]
        properties.append(f'  {_literal(field["name"])}{"" if field.get("required", True) else "?"}: {typed};')
    contracts = "export interface RecordInput {\n" + "\n".join(properties) + "\n}\nexport interface AppRecord extends RecordInput { id: string; }\nexport type AppRoute = '/' | '/records' | `/records/${string}`;\n"
    css = f":root{{--accent:{colour};color-scheme:light}}" + """*{box-sizing:border-box}body{margin:0;background:#f4f3ed;color:#222d30;font:16px/1.6 system-ui,sans-serif}header,main,footer{max-width:1100px;margin:auto;padding:24px clamp(20px,5vw,56px)}header{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap;border-bottom:1px solid #c8cec9}nav{display:flex;gap:24px}a{color:#234a61;text-underline-offset:4px}h1{overflow-wrap:anywhere;font:clamp(34px,5vw,64px)/1.1 Georgia,serif;margin:16px 0}h2{font:28px/1.2 Georgia,serif;margin:32px 0 16px}p{max-width:65ch}section{margin-top:28px}button,input,select{font:inherit;min-height:44px}button{border:1px solid #233e3c;background:#e3eae2;color:#213c37;padding:8px 18px;cursor:pointer}input,select{width:100%;border:1px solid #8a9992;padding:8px;background:#fff;color:#222d30}input[type=checkbox]{width:22px;height:22px;min-height:22px}label{overflow-wrap:anywhere;display:flex;flex-direction:column;gap:6px}#record-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));align-items:end;gap:16px;margin:24px 0}.table-wrap{overflow-x:auto}table{width:100%;min-width:560px;border-collapse:collapse;background:#fff}th,td{text-align:left;vertical-align:top;border-bottom:1px solid #d2d9d3;padding:12px;overflow-wrap:anywhere}th{overflow-wrap:normal;white-space:nowrap;font-size:13px;font-weight:600;letter-spacing:.03em}td:first-child{font-weight:600}.search{display:flex;gap:12px;flex-wrap:wrap}.search label{flex:1;min-width:min(220px,100%)}.empty{padding:20px;background:#e8eee7}#status{min-height:24px;color:#234a61}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--accent);outline-offset:4px}::selection{background:#c9ddce;color:#182923}@media(max-width:600px){header{display:block}nav{margin-top:12px}th,td{padding:9px;font-size:14px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}"""
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
if (form) for (const event of ['input', 'change']) EventTarget.prototype.addEventListener.call(form, event, e => { if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) dirty.add(e.target.name); });
if (form instanceof HTMLFormElement && status) {
  EventTarget.prototype.addEventListener.call(form, 'submit', async (event) => {
    event.preventDefault();
    const button = Element.prototype.querySelector.call(form, 'button');
    if (button) button.disabled = true;
    try {
      const spec = {fields: JSON.parse(Element.prototype.getAttribute.call(form, 'data-fields') || '[]')};
      const values = Object.fromEntries(spec.fields.map(field => {
        const input = HTMLFormControlsCollection.prototype.namedItem.call(Object.getOwnPropertyDescriptor(HTMLFormElement.prototype, 'elements').get.call(form), field.name);
        if (!(input instanceof HTMLInputElement || input instanceof HTMLSelectElement)) throw new Error('Missing field: '+field.name);
        return [field.name, field.type === 'boolean' ? input instanceof HTMLInputElement && input.checked : field.type === 'number' ? Number(input.value) : input.value];
      }));
      const id = Element.prototype.getAttribute.call(form, 'data-id');
      const captured = JSON.stringify(values);
      const row = id ? await updateRecord(id, Object.fromEntries(Object.entries(values).filter(([name]) => dirty.has(name)))) : await createRecord(values);
      Element.prototype.setAttribute.call(form, 'data-id', row.id);
      const now = Object.fromEntries(spec.fields.map(field => { const input = HTMLFormControlsCollection.prototype.namedItem.call(Object.getOwnPropertyDescriptor(HTMLFormElement.prototype, 'elements').get.call(form), field.name); return [field.name, input instanceof HTMLInputElement || input instanceof HTMLSelectElement ? field.type === 'boolean' ? input instanceof HTMLInputElement && input.checked : field.type === 'number' ? Number(input.value) : input.value : null]; }));
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
    files = {
        **common,
        "layout.html": '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{{name}}</title><link rel="stylesheet" href="/assets/style.css"></head><body><header><strong>{{name}}</strong><nav aria-label="Application"><a href="/">Overview</a><a href="/records">Records</a></nav></header><main>{{content}}</main><footer><p id="status" role="status" aria-live="polite"></p></footer><script type="module" src="/assets/client.js"></script></body></html>',
        "pages/index.html": '<h1>{{name}}</h1><p>{{description}}</p><section><h2>Overview</h2><p>{{count}} records in this application.</p><a href="/records">Manage records</a></section><section><h2>Current records</h2><div class="table-wrap">{{table}}</div></section>',
        "pages/records/index.html": '<h1>Records</h1><form class="search" action="/records" method="get"><label>Search records<input name="q" value="{{query}}" type="search"></label><button type="submit">Search</button></form><section><h2>Add a record</h2>{{form}}</section><section><h2>Saved records</h2><div class="table-wrap">{{table}}</div></section>',
        "pages/records/[id].html": '<h1>{{record_title}}</h1><p><a href="/records">Back to records</a></p><section><h2>Edit record</h2>{{form}}</section>',
        "assets/style.css": css, "assets/api.js": api, "assets/client.js": client,
        "contracts.d.ts": contracts,
        "tsconfig.json": json.dumps({"compilerOptions": {"allowJs": True, "checkJs": True, "noEmit": True, "target": "ES2022", "module": "ESNext", "moduleResolution": "Bundler", "lib": ["ES2022", "DOM"]}, "include": ["assets/api.js", "contracts.d.ts"]}, indent=2),
        "README.md": f'# {name}\n\nRun `python server.py --port 3000` and open http://127.0.0.1:3000. Python 3.10+; no packages or workbench required. SQLite data is stored in data/app.db. Edit pages/*.html, layout.html, assets and project.json; restart after editing to use the changed source.\n\nPages are discovered from the pages directory, with index.html and [parameter].html paths. JSON operations are available through /api/records and POST /actions/create, /actions/update, /actions/delete. /api/schema and /api/routes describe the project. contracts.d.ts and the annotated API client share the field types; run `tsc -p tsconfig.json` if TypeScript is installed.\n\nGenerated application source belongs to the exported project. It uses an ordinary local HTTP server, without account, authentication or external service setup. Add production infrastructure appropriate to your deployment.\n',
    }
    if template == "booking":
        if lang not in ("es", "en"):
            raise ValueError("Booking language must be es or en")
        copy = {"es": description_es if description_es is not None else description, "en": description}
        files.update(site_files(spec, colour, items, lang, copy))
    return files


class AppProjects:
    def __init__(self, data_dir, host_port=5191, *, token_name=None):
        self.root = Path(data_dir) / "app-projects"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.processes = {}
        self.proxies = {}
        self.host_port = host_port
        self.token_name = token_name or (lambda _: None)
        self.canvas = CanvasSessions()
        self.revision_events = RevisionEvents()

    @staticmethod
    def _archived(root, index):
        # Earlier creation undos left an empty marker. An explicit index state takes precedence.
        return index["archived"] if "archived" in index else (root / "archived").exists()

    def _load_index(self, id, *, include_archived=False):
        if not re.fullmatch(r"[a-f0-9]{16}", id):
            raise ValueError("Invalid project id")
        root = self.root / id
        try:
            index = json.loads((root / "project-index.json").read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise LookupError("Application project not found") from error
        if not include_archived and self._archived(root, index):
            raise LookupError("Application project not found")
        return root, index

    def _directory(self, id):
        return self._load_index(id)[0]

    def get(self, id, revision=None):
        with self.lock:
            root, index = self._load_index(id)
            selected = revision or index["revision"]
            if selected not in index["revisions"]:
                raise LookupError("Project revision not found")
            snapshot = json.loads((root / "revisions" / selected / "snapshot.json").read_text(encoding="utf-8"))
            public = self._public_index(index)
            if "history" in index:
                public["history"] = [self._with_materials(entry) for entry in index["history"]]
            return {**public, "selected_revision": selected, "files": snapshot["files"], "source_sha256": snapshot["source_sha256"], "preview": self.status(id)}

    def _with_materials(self, entry):
        if not entry.get("examples") and not entry.get("tokens_id"):
            return entry
        return {**entry, "materials": describe_materials(entry, self.token_name)}

    def list(self, archived=False):
        with self.lock:
            result = []
            for path in sorted(self.root.glob("*/project-index.json")):
                item = json.loads(path.read_text(encoding="utf-8"))
                if self._archived(path.parent, item) == archived:
                    metadata = self._public_index(item)
                    if archived:
                        metadata["archived"] = True
                    result.append({**metadata, "preview": self.status(item["id"])})
            return sorted(result, key=lambda item: item["updated_ts"], reverse=True)

    def _set_archived(self, root, index, archived):
        id = index["id"]
        if archived:
            self.stop(id)
        updated = {**index, "archived": archived, "updated_ts": max(time.time(), index["updated_ts"] + 0.000001)}
        write_json_atomic(root / "project-index.json", updated)
        if archived:
            self.revision_events.close_project(id)
        return updated

    def archive(self, id, expected_revision, confirm=False, operation="archive", expected_updated_ts=None, lang="en"):
        es = lang == "es"
        if operation not in ("archive", "restore"):
            raise ValueError("Choose archive or restore.")
        if confirm is not True:
            raise AppError("confirm_required",
                           "Confirma que quieres cambiar el estado del proyecto." if es else "Confirm the project state change.")
        archived = operation == "archive"
        with self.lock:
            root, index = self._load_index(id, include_archived=True)
            if (index["revision"] != expected_revision
                    or expected_updated_ts is not None and index["updated_ts"] != expected_updated_ts):
                raise AppError("conflict",
                               "La versión o el estado del proyecto ha cambiado. Vuelve a cargarlo."
                               if es else "The project revision or state changed. Reload the project.")
            changed = self._archived(root, index) != archived
            if changed:
                index = self._set_archived(root, index, archived)
            result = {"id": id, "revision": index["revision"], "archived": archived,
                      "updated_ts": index["updated_ts"], "changed": changed}
            if changed:
                result["undo"] = {"tool": "app_project_archive", "arguments": {
                    "id": id, "expected_revision": index["revision"], "expected_updated_ts": index["updated_ts"],
                    "operation": "restore" if archived else "archive", "confirm": True, "lang": lang,
                }}
            return result

    def edit_source(self, id, vsrc, tag, expected_revision, change, lang="en", *, actor=None, target=None):
        with self.lock:
            current = self.get(id)
            if current["revision"] != expected_revision:
                raise ValueError(
                    "La revisión cambió. Abre la vista previa actual." if lang == "es"
                    else "The revision changed. Open the current preview."
                )
            try:
                filename, line, column = source_position(vsrc)
                source = current["files"].get(filename)
                if source is None:
                    raise SourceMapError("The source file has changed. Open the current preview.",
                                         "El fichero fuente ha cambiado. Abre la vista previa actual.")
                updated = edit_source(source, line, column, tag, change)
            except SourceMapError as error:
                if lang == "es":
                    raise ValueError(error.spanish) from error
                raise
            if updated == source:
                return current
            return self.update(id, {filename: updated}, expected_revision, actor=actor,
                               target={**(target or {}), "vsrc": vsrc})

    def canvas_scale(self, id, revision, path="/", root_font_px=16):
        with self.lock:
            current = self.get(id, revision)
            served, html = self._preview_html(id, path)
            if served != revision:
                raise ValueError("The preview changed before its token scale could be read.")
            return {"scale": canvas_token_scale(current["files"], html, path, root_font_px)}

    def canvas_edit(self, id, vsrc, tag, expected_revision, change, path="/", operation="apply",
                    expected_count=None, root_font_px=16, lang="en", *, actor=None):
        with self.lock:
            current = self.get(id)
            preview = current["preview"]
            if (current["revision"] != expected_revision or preview.get("revision") != expected_revision
                    or preview["state"] != "running"):
                raise ValueError("La revisión cambió. Selecciona el elemento en la vista previa actual." if lang == "es"
                                 else "The revision changed. Select the element in the current preview.")
            try:
                _, html = self._preview_html(id, path)
                changes, target, scale, token, count = plan_canvas_edit(
                    current["files"], html, path, vsrc, tag, change, root_font_px,
                )
            except SourceMapError as error:
                if lang == "es":
                    raise ValueError(error.spanish) from error
                raise
            confirmation = bool(changes) and (target["kind"] == "class" or count > 1) and expected_count != count
            result = {"revision": expected_revision, "target": target, "affects": count, "token": token,
                      "scale": scale, "confirmation_required": confirmation, "changed": False}
            if target["kind"] == "class":
                # Only the authored preview route was counted. This stylesheet can be linked elsewhere.
                result.update(affects_scope="page", shared_stylesheet=True)
            if operation == "plan" or confirmation or not changes:
                return result
            updated = self.update(id, changes, expected_revision, actor=actor, target={"vsrc": vsrc})
            return {**result, "revision": updated["revision"], "changed": True, "undo": updated["undo"]}

    def _preview_html(self, id, path):
        route = urlsplit(path)
        if not path.startswith("/") or path.startswith("//") or route.netloc or route.fragment:
            raise ValueError("Provide a page path in this preview, such as /records?q=search.")
        with self.lock:
            self._directory(id)
            preview = self.status(id)
            if preview["state"] != "running":
                raise ValueError("Start this project's preview before counting served elements.")
            origin = urlsplit(preview["url"])
            if origin.scheme != "http" or origin.hostname != "127.0.0.1" or not origin.port:
                raise ValueError("The project's preview did not provide a loopback address.")
            with closing(HTTPConnection(origin.hostname, origin.port, timeout=5)) as connection:
                try:
                    connection.request("GET", path)
                    response = connection.getresponse()
                    if response.status != 200 or response.headers.get_content_type() != "text/html":
                        raise ValueError("This preview path did not return an HTML page.")
                    html = response.read().decode("utf-8")
                except (OSError, HTTPException) as error:
                    raise ValueError("The project's preview did not respond.") from error
        return preview["revision"], html

    def source_count(self, id, vsrc, path="/"):
        source_position(vsrc)
        revision, html = self._preview_html(id, path)
        return {"id": id, "revision": revision, "path": path, "vsrc": vsrc,
                "same_vsrc_count": source_count(html, vsrc)}

    def _save(self, root, index, files, *, before_commit=None, action="edit", author=None, details=None):
        destinations = set()
        for name, source in files.items():
            path = PurePosixPath(name)
            if not isinstance(source, str) or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or not path.parts:
                raise ValueError("Project files need relative paths and text content")
            destination = os.path.normcase(str(Path(*path.parts)))
            if destination in destinations:
                raise ValueError("Project file paths refer to the same file: " + name)
            destinations.add(destination)
        required = _PROJECT_SCAFFOLD_FILES | {"server.py"}
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
        now = time.time()
        previous = index.get("revision")
        history = index.get("history")
        if history is None:
            history = [{"revision": saved, "action": "legacy"} for saved in index.get("revisions", [])]
        if revision != previous:
            undo_revision = previous
            if action == "undo":
                restored = next((entry for entry in reversed(history) if entry["revision"] == revision), {})
                undo_revision = restored.get("undo_revision")
            history = [*history, {"id": uuid.uuid4().hex, "revision": revision, "previous_revision": previous,
                                  "ts": now, "undo_revision": undo_revision, "action": action,
                                  "author": author, **(details or {})}]
        updated = {**index, "name": spec["name"], "revision": revision, "updated_ts": now,
                   "revisions": list(dict.fromkeys([*index.get("revisions", []), revision])), "history": history}
        if before_commit is not None:
            before_commit(revision)
        write_json_atomic(root / "project-index.json", updated)
        return self.get(updated["id"])

    def create(self, name, template="work-board", description="", accent=None, fields=None, items=None, lang="en",
               description_es=None, files=None, *, author=None, art_direction=None):
        if files is None or not _PROJECT_SCAFFOLD_FILES.issubset(files):
            starter = "work-board" if files is not None and template == "custom" else template
            defaults = starter_files(name, starter, description, accent, fields, items, lang, description_es)
            files = {**defaults, **(files or {})}
        elif "server.py" not in files:
            files = {**files, "server.py": _standalone_runtime()}
        if art_direction and "project.json" in files:
            spec = json.loads(files["project.json"])
            if isinstance(spec, dict):
                spec["art_direction"] = art_direction
                files = {**files, "project.json": json.dumps(spec, ensure_ascii=False, indent=2) + "\n"}
        project = self.create_from_files(name, template, files, author=author)
        return {**project, "undo": self._undo_call(project)}

    @staticmethod
    def _undo_call(project, revision=None):
        return {"tool": "app_project_undo", "arguments": {
            "id": project["id"], "expected_revision": project["revision"], "revision": revision,
            "expected_updated_ts": project["updated_ts"],
        }}

    def create_from_files(self, name, template, files, *, author=None):
        """Create a project from a complete generated source (instruments use this)."""
        with self.lock:
            id = uuid.uuid4().hex[:16]
            root = self.root / id
            index = {"id": id, "name": name, "template": template, "created_ts": time.time(), "revisions": []}
            return self._save(root, index, files, action="create", author=author)

    def refresh_voice_assistant(self, id, expected_revision):
        """Update the installed assistant bundles in one reversible source revision."""
        with self.lock:
            current = self.get(id)
            if current["revision"] != expected_revision:
                raise AppError("conflict", "Read the current project revision before refreshing the voice assistant",
                               status=409, details={"revision": current["revision"]})
            assets = embedded_assistant_assets(current["files"])
            files = sorted(path for path, content in assets.items() if current["files"].get(path) != content)
            if not files:
                return {"id": id, "revision": expected_revision, "changed": False, "files": []}
            saved = self.update(id, {path: assets[path] for path in files}, expected_revision)
            return {"id": id, "revision": saved["revision"], "changed": True, "files": files, "undo": saved["undo"]}

    @staticmethod
    def _change_details(current, files, target=None, examples=None, tokens_id=None):
        spec = json.loads(files["project.json"])
        library = spec.get("biblioteca") if isinstance(spec, dict) else None
        library = library if isinstance(library, dict) else {}
        references = [item[:120] for item in (examples or [])]
        for key in ("presets", "recetas", "reglas_movimiento"):
            value = library.get(key)
            if isinstance(value, list):
                references.extend(item[:120] for item in value[:12] if isinstance(item, str))
        tokens = tokens_id or library.get("tokens_id")
        target = target or {}
        return {
            "files": sorted(path for path in current["files"].keys() | files.keys()
                            if files.get(path) != current["files"].get(path)),
            "target": target.get("vsrc") or target.get("selector"),
            "examples": list(dict.fromkeys(references))[:12],
            "tokens_id": tokens[:120] if isinstance(tokens, str) else None,
        }

    def update(self, id, files, expected_revision, *, actor=None, target=None, examples=None, tokens_id=None):
        with self.lock:
            current = self.get(id)
            if current["revision"] != expected_revision:
                baseline = self.get(id, expected_revision)
                conflicts = [name for name, content in files.items() if baseline["files"].get(name) != current["files"].get(name) and content != current["files"].get(name)]
                if conflicts:
                    raise ValueError("Project files changed: " + ", ".join(conflicts) + "; read their current source before applying edits")
            merged = {**current["files"], **files}
            if merged == current["files"]:
                return current
            change = None

            def before_commit(revision):
                nonlocal change
                change = revision_change(current, {"revision": revision, "files": merged})
                hint = dict(target or {})
                if expected_revision != current["revision"]:
                    hint.pop("vsrc", None)
                    hint.pop("box", None)
                if not hint.get("vsrc") and not hint.get("selector"):
                    sources = []
                    for name in change["files"]:
                        if name in change["ranges"] or name == "layout.html":
                            position = first_changed_source(name, current["files"].get(name, ""), merged[name])
                            if position:
                                sources.append(position)
                    hint["sources"] = sources
                self.canvas.prepare_edit(id, current["revision"], actor, {"box": None, **hint},
                                         change=self._with_materials(details))
                # Whole-frame refreshes can still outline a caller-supplied selector.
                if hint.get("selector"):
                    change["selectors"] = [hint["selector"]]

            author = {"kind": "agent", "id": actor.get("id", "agent"), "name": actor.get("name")} if actor else {"kind": "person"}
            details = self._change_details(current, merged, target, examples, tokens_id)
            root, index = self._load_index(id)
            saved = self._save(root, index, merged, author=author, details=details,
                               before_commit=before_commit if actor is not None else None)
            self.revision_events.publish(id, change or revision_change(current, saved))
            return {**saved, "undo": self._undo_call(saved, current["revision"])}

    def add_voice_assistant(self, id, expected_revision, page, form_selector, schema, allow_submit=False):
        with self.lock:
            project = self.get(id, expected_revision)
            if page not in project["files"] or not page.endswith(".html"):
                raise ValueError("Select an HTML source file in the project")
            patch = form_assistant_files(page, project["files"][page], form_selector, schema, allow_submit)
            saved = self.update(id, patch, expected_revision)
            receipt = {"id": id, "revision": saved["revision"], "page": page, "form_selector": form_selector,
                       "changed": "undo" in saved}
            if "undo" in saved:
                receipt["undo"] = saved["undo"]
            return receipt

    def revision_cursor(self, id, baseline):
        """Read current source and the corresponding subscription cursor atomically."""
        with self.lock:
            current = self.get(id)
            change = None
            if baseline and baseline != current["revision"]:
                try:
                    previous = self.get(id, baseline)
                except LookupError:
                    previous = None
                change = revision_change(previous, current, baseline=baseline)
            return self.revision_events.sequence, current["revision"], change

    @staticmethod
    def _public_index(index):
        public = {key: value for key, value in index.items() if key != "critique_loop"}
        if "history" in public:
            public["history"] = [{key: value for key, value in entry.items() if key != "materials"}
                                 for entry in public["history"]]
        return public

    def undo(self, id, expected_revision, expected_updated_ts, revision=None, *, author=None):
        with self.lock:
            current = self.get(id)
            if current["revision"] != expected_revision or current["updated_ts"] != expected_updated_ts:
                raise ValueError("Application revision changed after the original operation")
            root, index = self._load_index(id)
            if revision is None:
                if current["revisions"] != [expected_revision]:
                    raise ValueError("The application has retained edits")
                self._set_archived(root, index, True)
                return {"id": id, "archived": True, "revision": expected_revision}
            previous = self.get(id, revision)
            saved = self._save(root, index, previous["files"], action="undo", author=author)
            if saved["revision"] != current["revision"]:
                self.revision_events.publish(id, revision_change(current, saved))
            return saved

    def undo_change(self, id, change_id, expected_revision, expected_updated_ts, *, author=None):
        """Reverse a single recorded edit while keeping other files and conflicting later edits."""
        with self.lock:
            current = self.get(id)
            if current["revision"] != expected_revision or current["updated_ts"] != expected_updated_ts:
                raise AppError("conflict", "Application revision changed after the history was read")
            entry = next((row for row in current.get("history", []) if row.get("id") == change_id), None)
            if not entry or entry.get("action") != "edit":
                raise LookupError("Editable history step not found")
            original = self.get(id, entry["previous_revision"])["files"]
            edited = self.get(id, entry["revision"])["files"]
            files = dict(current["files"])
            conflicts = []
            for path in entry["files"]:
                if files.get(path) == original.get(path):
                    continue
                if files.get(path) != edited.get(path):
                    conflicts.append(path)
                elif path in original:
                    files[path] = original[path]
                else:
                    files.pop(path, None)
            if conflicts:
                raise AppError("conflict", "Later changes overlap: " + ", ".join(conflicts), details={"files": conflicts})
            if files == current["files"]:
                return {**current, "already_undone": True}
            details = {**self._change_details(current, files), "reverted_change": change_id}
            root, index = self._load_index(id)
            saved = self._save(root, index, files,
                               action="undo-change", author=author, details=details)
            self.revision_events.publish(id, revision_change(current, saved))
            return {**saved, "undo": self._undo_call(saved, current["revision"])}

    def critique_loop(self, id, lang="en"):
        with self.lock:
            _, index = self._load_index(id)
            loop = index.get("critique_loop", app_critique_loop.empty_loop())
            return app_critique_loop.loop_view(id, index["revision"], loop, lang)

    def prepare_critique_round(self, id, expected_revision, tokens_id, lang="en"):
        with self.lock:
            _, index = self._load_index(id)
            loop = index.get("critique_loop", app_critique_loop.empty_loop())
            if index["revision"] != expected_revision:
                raise AppError("conflict", "La versión de la aplicación ha cambiado. Vuelve a cargarla." if lang == "es"
                               else "The application revision changed. Read the current source before scoring.", status=409)
            if loop["rounds"] and tokens_id is not None and tokens_id != loop["tokens_id"]:
                raise AppError("critique_settings_changed", "Mantén el mismo sistema de diseño en todo el bucle." if lang == "es"
                               else "Use the same design system throughout the critique loop.", status=409)
            return (index["updated_ts"], loop["rounds"][-1]["id"] if loop["rounds"] else None,
                    loop["tokens_id"] if loop["rounds"] else tokens_id)

    def record_critique_round(self, id, revision, receipt, report, render_id, lang="en"):
        updated_ts, previous_round, tokens_id = receipt
        with self.lock:
            root, index = self._load_index(id)
            loop = index.get("critique_loop", app_critique_loop.empty_loop())
            latest = loop["rounds"][-1]["id"] if loop["rounds"] else None
            if index["revision"] != revision or index["updated_ts"] != updated_ts or latest != previous_round:
                raise AppError("conflict", "La fuente o las rondas han cambiado durante la evaluación. Vuelve a cargar la aplicación." if lang == "es"
                               else "Source or critique rounds changed while scoring. Read the application and retry.", status=409)
            current = self.get(id)
            best = loop["best_round"]
            baseline = self.get(id, loop["rounds"][best]["revision"]) if best is not None else None
            loop, entry = app_critique_loop.add_round(loop, current, baseline, report, render_id, tokens_id)
            final, preview_warning = self._save_critique_loop(root, index, current, loop, entry["active_revision"], "critique-restore")
            view = app_critique_loop.loop_view(id, final["revision"], loop, lang)
            return {**view, "preview_warning": preview_warning, "undo": {
                "tool": "app_project_critique_round_undo", "arguments": {
                    "id": id, "expected_round_id": entry["id"], "expected_revision": final["revision"],
                    "expected_updated_ts": final["updated_ts"], "lang": lang,
                },
            }}

    def undo_critique_round(self, id, expected_round_id, expected_revision, expected_updated_ts, lang="en"):
        with self.lock:
            root, index = self._load_index(id)
            loop = index.get("critique_loop", app_critique_loop.empty_loop())
            if (not loop["rounds"] or loop["rounds"][-1]["id"] != expected_round_id
                    or index["revision"] != expected_revision or index["updated_ts"] != expected_updated_ts):
                raise AppError("conflict", "La fuente o las rondas han cambiado desde esta evaluación." if lang == "es"
                               else "Source or critique rounds changed after this round.", status=409)
            current = self.get(id)
            target = loop["rounds"][-1]["revision"]
            loop = app_critique_loop.remove_round(loop)
            final, preview_warning = self._save_critique_loop(root, index, current, loop, target, "critique-undo")
            return {**app_critique_loop.loop_view(id, final["revision"], loop, lang), "preview_warning": preview_warning}

    def _save_critique_loop(self, root, index, current, loop, target, action):
        index = {**index, "critique_loop": loop}
        if current["revision"] == target:
            write_json_atomic(root / "project-index.json", index)
            return current, None
        id = current["id"]
        files = self.get(id, target)["files"]
        saved = self._save(root, index, files, action=action, author={"kind": "system"},
                           details=self._change_details(current, files))
        self.revision_events.publish(id, revision_change(current, saved))
        if current["preview"]["state"] == "running":
            try:
                self.preview(id, target)
            except (OSError, ValueError) as error:
                return saved, str(error)
        return saved, None

    def status(self, id):
        item = self.processes.get(id)
        if not item:
            return {"state": "stopped"}
        alive = item["process"].poll() is None
        proxy = self.proxies.get(id)
        return {"state": "running" if alive else "stopped", "revision": item["revision"], "url": item["url"] if alive else None,
                "open_path": f"/api/app-projects/{id}/preview/open",
                "pid": item["process"].pid if alive else None, "session": proxy.session if alive and proxy else None}

    def running_preview_url(self, id):
        with self.lock:
            self._directory(id)
            return self.status(id).get("url")

    def open_preview_url(self, id):
        """Resolve an existing preview or start the saved revision for a stable link."""
        with self.lock:
            try:
                url = self.running_preview_url(id)
            except ValueError as error:
                raise LookupError("Application project not found") from error
            return url or self.preview(id)["url"]

    @staticmethod
    def _close_process(item):
        process = item["process"]
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        finally:
            item["log"].close()

    def stop(self, id):
        with self.lock:
            item = self.processes.pop(id, None)
            self.canvas.detach_project(id)
            proxy = self.proxies.pop(id, None)
            if proxy:
                proxy.close()
            if item:
                self._close_process(item)
            return {"state": "stopped"}

    def preview(self, id, revision=None):
        with self.lock:
            project = self.get(id, revision)
            selected = project["selected_revision"]
            status = self.status(id)
            if status["state"] == "running" and status["revision"] == selected:
                return status
            root = self._directory(id)
            run = root / "runs" / uuid.uuid4().hex
            candidate = self._start_runtime(project, run, root / "data" / "app.db")
            try:
                proxy = self.proxies.get(id)
                if proxy is None:
                    proxy = self.proxies[id] = PreviewProxy(self.host_port)
            except Exception:
                self._close_process(candidate)
                raise
            previous = self.processes.get(id)
            candidate["url"] = proxy.url
            proxy.voice_revision = selected if {TRANSFER_ASSISTANT_ENTRY, FORM_ENTRY} & project["files"].keys() else ""
            proxy.backend = (urlsplit(candidate["runtime_url"]).port, selected)
            self.processes[id] = candidate
            if previous:
                self._close_process(previous)
            return self.status(id)

    def _start_runtime(self, project, run, database, *, deadline=None):
        ready = run / "ready.json"
        output = run / "output.log"
        source = run / "source"
        for name, content in project["files"].items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        selected = project["selected_revision"]
        server = source / "server.py"
        renderer = Path(__file__).with_name("app_source_map.py")
        command = [sys.executable, "-u", str(server), "--port", "0", "--database",
                   str(database), "--ready-file", str(ready), "--revision", selected]
        runtime_hash = hashlib.sha256(project["files"]["server.py"].encode("utf-8")).hexdigest()
        if runtime_hash in _LEGACY_STARTER_RUNTIMES:
            command.insert(2, str(renderer))
        preview_env = {**os.environ, "VITRUVIUS_PREVIEW_SOURCE_MAP": str(renderer)}
        log = output.open("wb")
        try:
            process = subprocess.Popen(
                command, cwd=source, env=preview_env, stdout=log, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            log.close()
            raise
        runtime = {"process": process, "log": log, "revision": selected}
        try:
            ready_by = time.monotonic() + 15
            if deadline is not None:
                ready_by = min(ready_by, deadline)
            while not ready.exists() and process.poll() is None and time.monotonic() < ready_by:
                time.sleep(.02)
            if not ready.exists() or process.poll() is not None:
                raise ValueError("Application did not start: " + output.read_text(encoding="utf-8", errors="replace"))
            receipt = urlsplit(json.loads(ready.read_text(encoding="utf-8"))["url"])
            if receipt.scheme != "http" or receipt.hostname != "127.0.0.1" or not receipt.port:
                raise ValueError("Invalid preview process address")
            runtime["runtime_url"] = f"http://127.0.0.1:{receipt.port}"
            return runtime
        except Exception:
            self._close_process(runtime)
            raise

    def preview_runtime(self, id, revision=None):
        """Pin server-side reads and captures to the requested runtime."""
        with self.lock:
            status = self.preview(id, revision)
            return status, self.processes[id]["runtime_url"]

    @contextmanager
    def assay_preview(self, id, revision, *, deadline):
        """Give a page check its own runtime without switching the editor preview or writing project data."""
        with self.lock:
            project = self.get(id, revision)
            live_database = self._directory(id) / "data" / "app.db"
        with tempfile.TemporaryDirectory(prefix="vitruvius-assay-") as directory:
            run = Path(directory)
            database = run / "app.db"
            if live_database.is_file():
                with (closing(sqlite3.connect(live_database.resolve().as_uri() + "?mode=ro", uri=True)) as live,
                      closing(sqlite3.connect(database)) as snapshot):
                    live.backup(snapshot)
            runtime = self._start_runtime(project, run, database, deadline=deadline)
            try:
                yield runtime["runtime_url"]
            finally:
                self._close_process(runtime)

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
        self.revision_events.close()
        for id in list(self.processes):
            self.stop(id)
