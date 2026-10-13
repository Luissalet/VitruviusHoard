"""Standalone application runtime, copied into exported projects.

Python standard library only. Pages, assets and schema belong to the project;
data belongs to a separate SQLite file and survives source revisions.
"""
from __future__ import annotations

import argparse
import html
import json
import mimetypes
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def validate_spec(spec):
    if not isinstance(spec, dict) or not isinstance(spec.get("name"), str) or not spec["name"].strip():
        raise ValueError("Project needs a name")
    if not isinstance(spec.get("fields"), list):
        raise ValueError("Project fields must be a list")
    names = set()
    for field in spec["fields"]:
        if not isinstance(field, dict) or not isinstance(field.get("name"), str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field["name"]):
            raise ValueError("Each field needs an identifier name")
        if field["name"] in names or field["name"] == "id":
            raise ValueError("Field names must be unique; id is reserved for record identity")
        names.add(field["name"])
        if field.get("type") not in ("text", "number", "boolean", "choice"):
            raise ValueError("Field type must be text, number, boolean or choice")
        if not isinstance(field.get("label", field["name"]), str):
            raise ValueError("Field label must be text")
        if field["type"] == "choice" and (not isinstance(field.get("choices"), list) or not field["choices"] or any(not isinstance(value, str) for value in field["choices"])):
            raise ValueError("Choice fields need a list of text choices")
    return spec


def validate_input(spec, values, *, partial=False):
    if not isinstance(values, dict):
        raise ValueError("Input must be an object")
    fields = {field["name"]: field for field in spec["fields"]}
    if set(values) - set(fields):
        raise ValueError("Unknown fields: " + ", ".join(sorted(set(values) - set(fields))))
    result = {}
    for name, field in fields.items():
        if name not in values:
            if partial:
                continue
            if field.get("required", True):
                raise ValueError(f"Missing field: {name}")
            continue
        value = values[name]
        kind = field["type"]
        if kind in ("text", "choice") and not isinstance(value, str):
            raise ValueError(f"{name} must be text")
        if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError(f"{name} must be a number")
        if kind == "number":
            import math
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if kind == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")
        if kind == "choice" and value not in field["choices"]:
            raise ValueError(f"Unknown choice for {name}")
        if field.get("required", True) and kind == "text" and not value.strip():
            raise ValueError(f"{name} is required")
        result[name] = value
    return result


class Records:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, body TEXT NOT NULL, created REAL NOT NULL)")

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=15)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    def list(self, query=""):
        with self.connection() as conn:
            rows = [{"id": id, **json.loads(body)} for id, body in conn.execute("SELECT id,body FROM records ORDER BY created DESC,id DESC")]
        return [row for row in rows if not query or query.casefold() in " ".join(str(value) for value in row.values()).casefold()]

    def get(self, id):
        with self.connection() as conn:
            row = conn.execute("SELECT body FROM records WHERE id=?", (id,)).fetchone()
        if not row:
            raise LookupError("Record not found")
        return {"id": id, **json.loads(row[0])}

    def create(self, values):
        id = uuid.uuid4().hex
        with self.connection() as conn:
            conn.execute("INSERT INTO records VALUES (?,?,?)", (id, json.dumps(values, ensure_ascii=False), time.time()))
        return {"id": id, **values}

    def update(self, id, values):
        # Read and merge in the same write transaction: independent fields survive.
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT body FROM records WHERE id=?", (id,)).fetchone()
            if not row:
                raise LookupError("Record not found")
            body = {**json.loads(row[0]), **values}
            conn.execute("UPDATE records SET body=? WHERE id=?", (json.dumps(body, ensure_ascii=False), id))
        return {"id": id, **body}

    def delete(self, id):
        with self.connection() as conn:
            if not conn.execute("DELETE FROM records WHERE id=?", (id,)).rowcount:
                raise LookupError("Record not found")


def routes(root):
    result = []
    for file in sorted((Path(root) / "pages").rglob("*.html")):
        parts = list(file.relative_to(Path(root) / "pages").with_suffix("").parts)
        if parts[-1] == "index":
            parts.pop()
        names = []
        expressions = []
        for part in parts:
            if re.fullmatch(r"\[[A-Za-z_][A-Za-z0-9_]*\]", part):
                names.append(part[1:-1]); expressions.append("([^/]+)")
            else:
                expressions.append(re.escape(part))
        result.append({"path": "/" + "/".join(parts), "file": file, "names": names,
                       "regex": re.compile("^/" + "/".join(expressions) + "/?$")})
    # Static paths win over parameters at the same level.
    return sorted(result, key=lambda row: (len(row["names"]), row["path"]))


def _text(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def render_page(root, spec, store, route, params, query):
    fields = spec["fields"]
    rows = store.list(query)
    row = store.get(params["id"]) if route["path"] == "/records/[id]" and "id" in params else None
    table = '<table><thead><tr>' + ''.join('<th>' + _text(field.get("label", field["name"])) + '</th>' for field in fields) + '<th>Open</th></tr></thead><tbody>'
    for record in rows:
        table += '<tr>' + ''.join('<td>' + _text(record.get(field["name"], "")) + '</td>' for field in fields) + '<td><a href="/records/' + record["id"] + '">Open record</a></td></tr>'
    table += '</tbody></table>'
    if not rows:
        table += '<p class="empty">No records yet. Use the form to add the first one.</p>'
    controls = []
    for field in fields:
        name, kind = field["name"], field["type"]
        label = _text(field.get("label", name))
        value = (row or {}).get(name, "")
        required = ' required' if field.get("required", True) and kind != "boolean" else ''
        if kind == "choice":
            control = '<select name="' + name + '"' + required + '>' + ''.join('<option value="' + _text(choice) + '"' + (' selected' if choice == value else '') + '>' + _text(choice) + '</option>' for choice in field["choices"]) + '</select>'
        elif kind == "boolean":
            control = '<input type="checkbox" name="' + name + '"' + (' checked' if value else '') + '>'
        else:
            control = '<input name="' + name + '" type="' + ('number" step="any' if kind == "number" else 'text') + '" value="' + _text(value) + '"' + required + '>'
        controls.append('<label>' + label + control + '</label>')
    form = '<form id="record-form" data-fields="' + _text(json.dumps(fields, ensure_ascii=False)) + '" data-id="' + _text((row or {}).get("id", "")) + '">' + ''.join(controls) + '<button type="submit">' + ('Save changes' if row else 'Add record') + '</button></form>'
    if row:
        form += '<button id="delete-record" data-id="' + row["id"] + '" type="button">Delete record</button>'
    values = {"name": _text(spec["name"]), "description": _text(spec.get("description", "")), "table": table, "form": form,
              "count": str(len(rows)), "query": _text(query), "record_title": _text((row or {}).get(fields[0]["name"], "Record") if fields else "Record")}
    values.update({"param_" + name: _text(value) for name, value in params.items()})
    page = route["file"].read_text(encoding="utf-8")
    page = re.sub(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}", lambda match: values.get(match[1], match[0]), page)
    layout = (Path(root) / "layout.html").read_text(encoding="utf-8")
    values["content"] = page
    return re.sub(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}", lambda match: values.get(match[1], match[0]), layout)


def make_server(root, database, *, host="127.0.0.1", port=0, revision=""):
    root = Path(root).resolve()
    spec = validate_spec(json.loads((root / "project.json").read_text(encoding="utf-8")))
    store = Records(database)
    discovered = routes(root)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, data, content_type="application/json; charset=utf-8"):
            payload = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            try:
                parts = urlsplit(self.path); path = unquote(parts.path)
                query = parse_qs(parts.query).get("q", [""])[0]
                if path == "/api/health":
                    return self.send(200, {"service": "vitruvius-app", "revision": revision, "records": len(store.list())})
                if path == "/api/schema":
                    return self.send(200, spec)
                if path == "/api/routes":
                    return self.send(200, {"routes": [{"path": route["path"], "file": str(route["file"].relative_to(root))} for route in discovered]})
                if path == "/api/records":
                    return self.send(200, {"records": store.list(query)})
                if path.startswith("/api/records/"):
                    return self.send(200, store.get(path.removeprefix("/api/records/")))
                if path.startswith("/assets/"):
                    asset = (root / path.lstrip("/")).resolve()
                    if not asset.is_relative_to(root / "assets") or not asset.is_file():
                        raise LookupError("Asset not found")
                    return self.send(200, asset.read_bytes(), mimetypes.guess_type(asset)[0] or "application/octet-stream")
                for route in discovered:
                    match = route["regex"].match(path)
                    if match:
                        page = render_page(root, spec, store, route, dict(zip(route["names"], match.groups())), query)
                        return self.send(200, page.encode("utf-8"), "text/html; charset=utf-8")
                raise LookupError("Page not found")
            except LookupError as error:
                self.send(404, {"error": str(error)})
            except (ValueError, OSError) as error:
                self.send(400, {"error": str(error)})

        def mutation(self, method):
            try:
                path = urlsplit(self.path).path
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0")))) if method != "DELETE" else {}
                if path.startswith("/actions/"):
                    if method != "POST":
                        return self.send(405, {"error": "Actions use POST"})
                    action = path.removeprefix("/actions/")
                    if action == "create":
                        return self.send(201, store.create(validate_input(spec, payload)))
                    if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
                        raise ValueError("Action needs a record id")
                    id = payload["id"]
                    if action == "update":
                        return self.send(200, store.update(id, validate_input(spec, {k: v for k, v in payload.items() if k != "id"}, partial=True)))
                    if action == "delete":
                        store.delete(id); return self.send(200, {"ok": True})
                    raise LookupError("Action not found")
                if path == "/api/records" and method == "POST":
                    return self.send(201, store.create(validate_input(spec, payload)))
                if path.startswith("/api/records/"):
                    id = path.removeprefix("/api/records/")
                    if method == "PATCH":
                        return self.send(200, store.update(id, validate_input(spec, payload, partial=True)))
                    if method == "DELETE":
                        store.delete(id); return self.send(200, {"ok": True})
                raise LookupError("API route not found")
            except LookupError as error:
                self.send(404, {"error": str(error)})
            except (ValueError, TypeError) as error:
                self.send(400, {"error": str(error)})

        def do_POST(self): self.mutation("POST")
        def do_PATCH(self): self.mutation("PATCH")
        def do_DELETE(self): self.mutation("DELETE")

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--database", default="data/app.db")
    parser.add_argument("--ready-file")
    parser.add_argument("--revision", default="")
    args = parser.parse_args()
    server = make_server(Path(__file__).resolve().parent, args.database, host=args.host, port=args.port, revision=args.revision)
    ready = {"url": f"http://{args.host}:{server.server_port}", "revision": args.revision}
    if args.ready_file:
        ready_path = Path(args.ready_file)
        temporary = ready_path.with_suffix(".tmp")
        temporary.write_bytes(json.dumps(ready).encode("utf-8"))
        temporary.replace(ready_path)
    print(json.dumps(ready), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
