"""Standalone application runtime, copied into exported projects.

Python standard library only. Pages, assets and schema belong to the project;
data belongs to a separate SQLite file and survives source revisions.
"""
from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import re
import runpy
import sqlite3
import time
import uuid
from contextlib import contextmanager
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


class ActionError(ValueError):
    def __init__(self, message, code="invalid_input", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def validate_request_key(key):
    if key is not None and (not isinstance(key, str) or not re.fullmatch(r"[!-~]{1,128}", key)):
        raise ValueError("Idempotency key must contain 1 to 128 visible ASCII characters")


def _integer(value):
    return type(value) is int and abs(value) <= 2**53 - 1


def _iban(value, name):
    normalized = "".join(value.split()).upper()
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", normalized):
        raise ValueError(f"{name} must be a valid IBAN")
    rearranged = normalized[4:] + normalized[:4]
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    if int(digits) % 97 != 1:
        raise ValueError(f"{name} must be a valid IBAN")
    return normalized


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value)


def _record_id(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]+", value)


def _validate_fields(fields, collections=None):
    if not isinstance(fields, list):
        raise ValueError("Project fields must be a list")
    names = set()
    kinds = {"text", "number", "boolean", "choice"}
    if collections is not None:
        kinds.update(("integer", "ref"))
    for field in fields:
        if not isinstance(field, dict) or not _identifier(field.get("name")):
            raise ValueError("Each field needs an identifier name")
        name, kind = field["name"], field.get("type")
        if name in names or name == "id":
            raise ValueError("Field names must be unique; id is reserved for record identity")
        names.add(name)
        if not isinstance(kind, str) or kind not in kinds:
            if collections is None:
                raise ValueError("Field type must be text, number, boolean or choice")
            raise ValueError(f"Unknown field type for {name}")
        if not isinstance(field.get("label", name), str):
            raise ValueError("Field label must be text")
        if kind == "choice" and (not isinstance(field.get("choices"), list) or not field["choices"] or any(not isinstance(value, str) for value in field["choices"])):
            raise ValueError("Choice fields need a list of text choices")
        if collections is None:
            continue
        if not isinstance(field.get("required", True), bool):
            raise ValueError(f"required must be boolean for {name}")
        if "format" in field and (kind != "text" or field["format"] != "iban"):
            raise ValueError(f"Unknown text format for {name}")
        if kind == "ref" and (not _identifier(field.get("collection")) or field["collection"] not in collections):
            raise ValueError(f"Unknown referenced collection for {name}")
        for bound in ("min", "max"):
            if bound in field and (kind != "integer" or not _integer(field[bound])):
                raise ValueError(f"{bound} must be an integer bound for {name}")
        if "min" in field and "max" in field and field["min"] > field["max"]:
            raise ValueError(f"Invalid bounds for {name}")
    return {field["name"]: field for field in fields}


def validate_spec(spec):
    if not isinstance(spec, dict) or not isinstance(spec.get("name"), str) or not spec["name"].strip():
        raise ValueError("Project needs a name")
    if spec.get("format") == "vitruvius-app/v2":
        _validate_collection_spec(spec)
    else:
        _validate_fields(spec.get("fields"))
    return spec


def validate_input(spec, values, *, partial=False, typed=False):
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
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"{name} must be finite")
        if kind == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")
        if kind == "choice" and value not in field["choices"]:
            raise ValueError(f"Unknown choice for {name}")
        if field.get("required", True) and kind == "text" and not value.strip():
            raise ValueError(f"{name} is required")
        if typed and kind == "ref" and not _record_id(value):
            raise ValueError(f"{name} must be a record id")
        if typed and kind == "integer":
            if not _integer(value):
                raise ValueError(f"{name} must be an integer in the supported range")
            if ("min" in field and value < field["min"]) or ("max" in field and value > field["max"]):
                raise ValueError(f"{name} is outside its bounds")
        if typed and kind == "text" and field.get("format") == "iban":
            value = _iban(value, name)
        result[name] = value
    return result


def _validate_expression(expr, inputs, lookups):
    if not isinstance(expr, dict):
        if type(expr) not in (str, int, float, bool):
            raise ValueError("An expression needs a literal or a declared operand")
        return
    keys = set(expr)
    if keys == {"input"} and _identifier(expr["input"]) and expr["input"] in inputs:
        return
    if keys == {"record", "field"} and _identifier(expr["record"]) and _identifier(expr["field"]):
        if expr["record"] in lookups and (expr["field"] == "id" or expr["field"] in lookups[expr["record"]]):
            return
    if keys == {"negate"}:
        _validate_expression(expr["negate"], inputs, lookups)
        return
    if keys == {"coalesce"} and isinstance(expr["coalesce"], list) and expr["coalesce"]:
        for operand in expr["coalesce"]:
            _validate_expression(operand, inputs, lookups)
        return
    raise ValueError("Unknown expression or undeclared operand")


def _validate_collection_spec(spec):
    collections = spec.get("collections")
    actions = spec.get("actions", {})
    if not isinstance(collections, dict) or not collections or not isinstance(actions, dict):
        raise ValueError("Collections and actions must be named objects")
    schemas = {}
    for name, collection in collections.items():
        if not _identifier(name) or not isinstance(collection, dict):
            raise ValueError("Each collection needs an identifier name and a schema")
        schemas[name] = _validate_fields(collection.get("fields"), collections)
        seeds = collection.get("records", [])
        if not isinstance(seeds, list):
            raise ValueError(f"Initial records must be a list for {name}")
        ids = set()
        for row in seeds:
            if not isinstance(row, dict) or not _record_id(row.get("id")) or row["id"] in ids:
                raise ValueError(f"Initial records need unique ids in {name}")
            ids.add(row["id"])
            validate_input(collection, {k: v for k, v in row.items() if k != "id"}, typed=True)
    for name, action in actions.items():
        if not _identifier(name) or not isinstance(action, dict):
            raise ValueError("Each action needs an identifier name and a declaration")
        if not isinstance(action.get("confirmable_by_voice", False), bool):
            raise ValueError("confirmable_by_voice must be boolean")
        inputs = _validate_fields(action.get("input"), collections)
        choices = action.get("exactly_one")
        if "exactly_one" in action and (
            not isinstance(choices, list) or len(choices) < 2
            or any(not _identifier(key) or key not in inputs or inputs[key].get("required", True) for key in choices)
            or len(set(choices)) != len(choices)
        ):
            raise ValueError("exactly_one needs distinct optional input field names")
        lookups = {}
        declared = action.get("lookups", {})
        if not isinstance(declared, dict):
            raise ValueError("Action lookups must be named objects")
        for alias, lookup in declared.items():
            if not _identifier(alias) or not isinstance(lookup, dict) or set(lookup) != {"collection", "field", "equals"}:
                raise ValueError("A lookup needs a collection, field and equals expression")
            collection, field = lookup["collection"], lookup["field"]
            if not _identifier(collection) or collection not in schemas or not _identifier(field) or (field != "id" and field not in schemas[collection]):
                raise ValueError("Lookup refers to an unknown collection or field")
            _validate_expression(lookup["equals"], inputs, lookups)
            lookups[alias] = schemas[collection]
        if "different" in action:
            pair = action["different"]
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("different requires two expressions")
            for expr in pair:
                _validate_expression(expr, inputs, lookups)
        effects = action.get("effects")
        if not isinstance(effects, list) or not effects:
            raise ValueError("An action needs at least one effect")
        for effect in effects:
            _validate_effect(effect, schemas, inputs, lookups)


def _validate_effect(effect, schemas, inputs, lookups):
    if not isinstance(effect, dict) or not _identifier(effect.get("collection")) or effect["collection"] not in schemas:
        raise ValueError("An effect needs a declared collection")
    fields = schemas[effect["collection"]]
    op = effect.get("op")
    keys = set(effect) - {"when"}
    if op == "create" and keys == {"op", "collection", "values"}:
        if not isinstance(effect["values"], dict) or set(effect["values"]) - set(fields):
            raise ValueError("Create values must name declared fields")
        operands = list(effect["values"].values())
        if any(field.get("required", True) and name not in effect["values"] for name, field in fields.items()):
            raise ValueError("Create effects need all required fields")
    elif op == "adjust" and keys == {"op", "collection", "id", "field", "amount"}:
        if not _identifier(effect["field"]) or fields.get(effect["field"], {}).get("type") != "integer":
            raise ValueError("Adjust needs an integer field")
        operands = [effect["id"], effect["amount"]]
    else:
        raise ValueError("An effect must declare create or adjust with its operands")
    if "when" in effect:
        operands.append(effect["when"])
    for expr in operands:
        _validate_expression(expr, inputs, lookups)


_MISSING = object()


def _evaluate(expr, inputs, lookups):
    if not isinstance(expr, dict):
        return expr
    if "input" in expr:
        return inputs.get(expr["input"], _MISSING)
    if "record" in expr:
        return lookups[expr["record"]].get(expr["field"], _MISSING)
    if "negate" in expr:
        value = _evaluate(expr["negate"], inputs, lookups)
        if value is _MISSING:
            return value
        if not _integer(value):
            raise ValueError("Negate needs an integer")
        return -value
    for operand in expr["coalesce"]:
        value = _evaluate(operand, inputs, lookups)
        if value is not _MISSING:
            return value
    return _MISSING


class _Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=15)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()


class Records(_Database):
    def __init__(self, path):
        super().__init__(path)
        with self.connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, body TEXT NOT NULL, created REAL NOT NULL)")

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


class Collections(_Database):
    def __init__(self, path, spec):
        super().__init__(path)
        self.schemas = spec["collections"]
        self.actions = spec.get("actions", {})
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS app_collections(name TEXT PRIMARY KEY)")
            conn.execute("""CREATE TABLE IF NOT EXISTS app_collection_records(
                collection TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                created REAL NOT NULL, last_action TEXT, PRIMARY KEY(collection, id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS app_action_receipts(
                token TEXT PRIMARY KEY, request_key TEXT UNIQUE, signature TEXT NOT NULL,
                result TEXT NOT NULL, changes TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0
            )""")
            seeded = []
            for collection, schema in self.schemas.items():
                initialized = conn.execute("INSERT OR IGNORE INTO app_collections VALUES (?)", (collection,))
                if initialized.rowcount:
                    for row in schema.get("records", []):
                        body = validate_input(schema, {k: v for k, v in row.items() if k != "id"}, typed=True)
                        self._insert(conn, collection, row["id"], body)
                        seeded.append((collection, body))
            # Seeds in one collection can refer to seeds declared later.
            for collection, body in seeded:
                self._check_references(conn, self.schemas[collection]["fields"], body)

    def _schema(self, collection):
        if collection not in self.schemas:
            raise ActionError("Collection not found", "collection_not_found", 404)
        return self.schemas[collection]

    def _rows(self, conn, collection):
        return conn.execute(
            "SELECT id,body FROM app_collection_records WHERE collection=? ORDER BY created DESC,id DESC",
            (collection,),
        )

    def _get(self, conn, collection, id):
        return conn.execute(
            "SELECT body,last_action FROM app_collection_records WHERE collection=? AND id=?",
            (collection, id),
        ).fetchone()

    def _insert(self, conn, collection, id, body, token=None):
        conn.execute("INSERT INTO app_collection_records VALUES (?,?,?,?,?)",
                     (collection, id, json.dumps(body, ensure_ascii=False), time.time(), token))

    def _check_references(self, conn, fields, values):
        for field in fields:
            name = field["name"]
            if field["type"] == "ref" and name in values and not self._get(conn, field["collection"], values[name]):
                raise ActionError(f"Record for {name} was not found", "invalid_reference")

    def list(self, collection, query=""):
        self._schema(collection)
        with self.connection() as conn:
            rows = [{"id": id, **json.loads(body)} for id, body in self._rows(conn, collection)]
        return [row for row in rows if not query or query.casefold() in " ".join(str(value) for value in row.values()).casefold()]

    def get(self, collection, id):
        self._schema(collection)
        with self.connection() as conn:
            row = self._get(conn, collection, id)
        if row is None:
            raise ActionError("Record not found", "record_not_found", 404)
        return {"id": id, **json.loads(row[0])}

    def count(self):
        with self.connection() as conn:
            return sum(conn.execute("SELECT count(*) FROM app_collection_records WHERE collection=?", (name,)).fetchone()[0]
                       for name in self.schemas)

    def _lookup(self, conn, collection, field, value):
        if value is _MISSING:
            return {}
        if field == "id":
            if not _record_id(value):
                raise ValueError("A lookup by id needs a record id")
            row = self._get(conn, collection, value)
            return {"id": value, **json.loads(row[0])} if row else {}
        match = {}
        for id, raw in self._rows(conn, collection):
            row = json.loads(raw)
            candidate = row.get(field, _MISSING)
            if value == candidate and isinstance(value, bool) == isinstance(candidate, bool):
                if match:
                    raise ActionError(f"Multiple records match {collection}.{field}", "ambiguous_reference", 409)
                match = {"id": id, **row}
        return match

    def _adjust(self, conn, effect, schema, id, amount, token):
        collection, field = effect["collection"], effect["field"]
        if not _record_id(id) or not _integer(amount):
            raise ValueError("Adjust needs a record id and an integer amount")
        before = self._get(conn, collection, id)
        if before is None:
            raise ActionError(f"Record to adjust was not found in {collection}", "invalid_reference")
        body = json.loads(before[0])
        if not _integer(body.get(field)):
            raise ActionError(f"The stored value of {field} must be an integer", "invalid_record", 409)
        body[field] += amount
        definition = next(item for item in schema["fields"] if item["name"] == field)
        if "min" in definition and body[field] < definition["min"]:
            raise ActionError(f"Adjustment would put {field} below its minimum", "insufficient_balance", 409)
        body = validate_input(schema, body, typed=True)
        self._check_references(conn, schema["fields"], body)
        conn.execute("UPDATE app_collection_records SET body=?,last_action=? WHERE collection=? AND id=?",
                     (json.dumps(body, ensure_ascii=False), token, collection, id))
        return body, before

    def perform(self, name, values, request_key=None):
        action = self.actions.get(name)
        if action is None:
            raise ActionError("Action not found", "action_not_found", 404)
        validate_request_key(request_key)
        inputs = validate_input({"fields": action["input"]}, values, typed=True)
        if "exactly_one" in action and len(set(inputs).intersection(action["exactly_one"])) != 1:
            raise ValueError("Supply exactly one of: " + ", ".join(action["exactly_one"]))
        signature = json.dumps([name, inputs], sort_keys=True, ensure_ascii=False)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if request_key is not None:
                prior = conn.execute("SELECT signature,result,undone FROM app_action_receipts WHERE request_key=?",
                                     (request_key,)).fetchone()
                if prior:
                    if prior[0] != signature or prior[2]:
                        raise ActionError("Idempotency key was already used", "idempotency_conflict", 409)
                    return json.loads(prior[1])
            self._check_references(conn, action["input"], inputs)
            lookups = {}

            def evaluate(expr):
                return _evaluate(expr, inputs, lookups)

            for alias, lookup in action.get("lookups", {}).items():
                lookups[alias] = self._lookup(conn, lookup["collection"], lookup["field"], evaluate(lookup["equals"]))
            if "different" in action:
                left, right = map(evaluate, action["different"])
                if left is not _MISSING and right is not _MISSING and left == right:
                    raise ValueError("Action requires different values")
            token = uuid.uuid4().hex
            changes, previous = [], {}
            for effect in action["effects"]:
                if "when" in effect and evaluate(effect["when"]) is _MISSING:
                    continue
                collection, op = effect["collection"], effect["op"]
                schema = self.schemas[collection]
                if op == "create":
                    values = {key: evaluate(expr) for key, expr in effect["values"].items()}
                    body = validate_input(schema, {k: v for k, v in values.items() if v is not _MISSING}, typed=True)
                    self._check_references(conn, schema["fields"], body)
                    id, before = uuid.uuid4().hex, None
                    self._insert(conn, collection, id, body, token)
                else:
                    id = evaluate(effect["id"])
                    body, before = self._adjust(conn, effect, schema, id, evaluate(effect["amount"]), token)
                previous.setdefault((collection, id), before)
                changes.append({"collection": collection, "operation": op, "record": {"id": id, **body}})
            result = {"ok": True, "action": name, "undo_token": token, "changes": changes}
            conn.execute("INSERT INTO app_action_receipts (token,request_key,signature,result,changes) VALUES (?,?,?,?,?)",
                         (token, request_key, signature, json.dumps(result, ensure_ascii=False),
                          json.dumps([[collection, id, before] for (collection, id), before in previous.items()])))
            return result

    def undo(self, token):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            receipt = conn.execute("SELECT changes,undone FROM app_action_receipts WHERE token=?", (token,)).fetchone()
            if receipt is None:
                raise ActionError("Action receipt not found", "undo_not_found", 404)
            if receipt[1]:
                raise ActionError("Action was already undone", "undo_conflict", 409)
            previous = json.loads(receipt[0])
            removed, restored = {}, []
            for collection, id, before in previous:
                row = self._get(conn, collection, id)
                if row is None or row[1] != token:
                    raise ActionError("A record was changed by a later action", "undo_conflict", 409)
                if collection not in self.schemas:
                    raise ActionError("The collection schema has changed", "undo_conflict", 409)
                schema = self.schemas[collection]
                if before is None:
                    conn.execute("DELETE FROM app_collection_records WHERE collection=? AND id=?", (collection, id))
                    removed.setdefault(collection, set()).add(id)
                else:
                    try:
                        body = validate_input(schema, json.loads(before[0]), typed=True)
                    except ValueError as error:
                        raise ActionError("The collection schema has changed", "undo_conflict", 409) from error
                    restored.append((schema["fields"], body))
                    conn.execute("UPDATE app_collection_records SET body=?,last_action=? WHERE collection=? AND id=?",
                                 (*before, collection, id))
            for fields, body in restored:
                self._check_references(conn, fields, body)
            for collection, schema in self.schemas.items():
                refs = {field["name"]: removed[field["collection"]] for field in schema["fields"]
                        if field["type"] == "ref" and field["collection"] in removed}
                if refs:
                    for _, body in self._rows(conn, collection):
                        row = json.loads(body)
                        if any(row.get(field) in ids for field, ids in refs.items()):
                            raise ActionError("A later record refers to a record this action created", "undo_conflict", 409)
            conn.execute("UPDATE app_action_receipts SET undone=1 WHERE token=?", (token,))
            return {"ok": True, "undo_token": token}


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


def _render_template(_root, path, values):
    source = path.read_text(encoding="utf-8")
    return re.sub(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}", lambda match: values.get(match[1], match[0]), source)


_RECORDS_COPY = {
    "en": {
        "open": "Open",
        "open_record": "Open record",
        "empty": "No records yet. Use the form to add the first one.",
        "save": "Save changes",
        "add": "Add record",
        "delete": "Delete record",
        "record": "Record",
    },
    "es": {
        "open": "Abrir",
        "open_record": "Abrir registro",
        "empty": "Aún no hay registros. Usa el formulario para añadir el primero.",
        "save": "Guardar cambios",
        "add": "Añadir registro",
        "delete": "Eliminar registro",
        "record": "Registro",
    },
}


class _LayoutLanguage(HTMLParser):
    language = "en"

    def handle_starttag(self, tag, attrs):
        if tag == "html":
            language = dict(attrs).get("lang") or "en"
            self.language = language.lower().split("-")[0]


def _choice_label(field, value):
    labels = field.get("choice_labels")
    if field["type"] == "choice" and isinstance(labels, dict) and isinstance(value, str):
        return labels.get(value, value)
    return value


def render_page(root, spec, store, route, params, query, *, render_template=_render_template, lang="en"):
    if isinstance(store, Collections):
        values = {"name": _text(spec["name"]), "description": _text(spec.get("description", "")), "query": _text(query)}
        values.update({"param_" + name: _text(value) for name, value in params.items()})
        values["content"] = render_template(root, route["file"], values)
        return render_template(root, Path(root) / "layout.html", values)
    copy = _RECORDS_COPY.get(lang, _RECORDS_COPY["en"])
    fields = spec["fields"]
    rows = store.list(query)
    row = store.get(params["id"]) if route["path"] == "/records/[id]" and "id" in params else None
    headers = "".join(f'<th>{_text(field.get("label", field["name"]))}</th>' for field in fields)
    table = f'<table><thead><tr>{headers}<th>{copy["open"]}</th></tr></thead><tbody>'
    for record in rows:
        cells = "".join(
            f'<td>{_text(_choice_label(field, record.get(field["name"], "")))}</td>' for field in fields
        )
        table += f'<tr>{cells}<td><a href="/records/{record["id"]}">{copy["open_record"]}</a></td></tr>'

    table += '</tbody></table>'
    if not rows:
        table += f'<p class="empty">{copy["empty"]}</p>'
    controls = []
    for field in fields:
        name, kind = field["name"], field["type"]
        label = _text(field.get("label", name))
        value = (row or {}).get(name, "")
        required = ' required' if field.get("required", True) and kind != "boolean" else ''
        if kind == "choice":
            options = "".join(
                f'<option value="{_text(choice)}"' + (" selected" if choice == value else "")
                + f'>{_text(_choice_label(field, choice))}</option>'
                for choice in field["choices"]
            )
            control = f'<select name="{name}"{required}>{options}</select>'

        elif kind == "boolean":
            control = '<input type="checkbox" name="' + name + '"' + (' checked' if value else '') + '>'
        else:
            control = '<input name="' + name + '" type="' + ('number" step="any' if kind == "number" else 'text') + '" value="' + _text(value) + '"' + required + '>'
        controls.append('<label>' + label + control + '</label>')
    form = (
        f'<form id="record-form" data-fields="{_text(json.dumps(fields, ensure_ascii=False))}"'
        f' data-id="{_text((row or {}).get("id", ""))}">{"".join(controls)}'
        f'<button type="submit">{copy["save" if row else "add"]}</button></form>'
    )
    if row:
        form += f'<button id="delete-record" data-id="{row["id"]}" type="button">{copy["delete"]}</button>'
    fallback_title = copy["record"]
    record_title = (row or {}).get(fields[0]["name"], fallback_title) if fields else fallback_title
    values = {"name": _text(spec["name"]), "description": _text(spec.get("description", "")), "table": table, "form": form,
              "count": str(len(rows)), "query": _text(query), "record_title": _text(record_title)}

    values.update({"param_" + name: _text(value) for name, value in params.items()})
    root = Path(root)
    values["content"] = render_template(root, route["file"], values)
    return render_template(root, root / "layout.html", values)


def make_server(root, database, *, host="127.0.0.1", port=0, revision="", render_template=_render_template):
    root = Path(root).resolve()
    spec = validate_spec(json.loads((root / "project.json").read_text(encoding="utf-8")))
    language = _LayoutLanguage()
    layout = root / "layout.html"
    if layout.is_file():
        language.feed(layout.read_text(encoding="utf-8"))
    typed = spec.get("format") == "vitruvius-app/v2"
    store = Collections(database, spec) if typed else Records(database)
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

        def fail(self, error, status=400, code="invalid_input"):
            if isinstance(error, ActionError):
                status, code = error.status, error.code
            payload = {"error": str(error)}
            if typed:
                payload["code"] = code
            return self.send(status, payload)

        def do_GET(self):
            try:
                parts = urlsplit(self.path); path = unquote(parts.path)
                query = parse_qs(parts.query).get("q", [""])[0]
                if path == "/api/health":
                    return self.send(200, {"service": "vitruvius-app", "revision": revision,
                                           "records": store.count() if typed else len(store.list())})
                if path == "/api/schema":
                    return self.send(200, spec)
                if path == "/api/routes":
                    return self.send(200, {"routes": [{"path": route["path"], "file": str(route["file"].relative_to(root))} for route in discovered]})
                if typed and path.startswith("/api/collections/"):
                    parts = path.removeprefix("/api/collections/").split("/")
                    if len(parts) == 1:
                        return self.send(200, {"records": store.list(parts[0], query)})
                    if len(parts) == 2 and _record_id(parts[1]):
                        return self.send(200, store.get(*parts))
                    raise LookupError("Collection route not found")
                if not typed and path == "/api/records":
                    return self.send(200, {"records": store.list(query)})
                if not typed and path.startswith("/api/records/"):
                    return self.send(200, store.get(path.removeprefix("/api/records/")))
                public = root / "public"
                if path in ("/", "/index.html") and (public / "index.html").is_file():
                    return self.send(200, (public / "index.html").read_bytes(), "text/html; charset=utf-8")
                if path.startswith("/assets/"):
                    static_asset = (public / path.lstrip("/")).resolve()
                    if static_asset.is_relative_to(public / "assets") and static_asset.is_file():
                        return self.send(200, static_asset.read_bytes(), mimetypes.guess_type(static_asset)[0] or "application/octet-stream")
                    asset = (root / path.lstrip("/")).resolve()
                    if not asset.is_relative_to(root / "assets") or not asset.is_file():
                        raise LookupError("Asset not found")
                    return self.send(200, asset.read_bytes(), mimetypes.guess_type(asset)[0] or "application/octet-stream")
                for route in discovered:
                    match = route["regex"].match(path)
                    if match:
                        page = render_page(root, spec, store, route, dict(zip(route["names"], match.groups())), query,
                                           render_template=render_template, lang=language.language)
                        return self.send(200, page.encode("utf-8"), "text/html; charset=utf-8")
                raise LookupError("Page not found")
            except LookupError as error:
                self.fail(error, 404, "not_found")
            except (ValueError, OSError) as error:
                self.fail(error)
            except sqlite3.DatabaseError:
                if not typed:
                    raise
                self.fail("Storage temporarily unavailable", 503, "storage_unavailable")

        def typed_mutation(self, path, method):
            action = re.fullmatch(r"/api/actions/([A-Za-z_][A-Za-z0-9_]*)", path)
            undo = re.fullmatch(r"/api/action-receipts/([a-f0-9]{32})/undo", path)
            if not action and not undo:
                raise LookupError("API route not found")
            if method != "POST":
                return self.fail("Actions use POST", 405, "method_not_allowed")
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0:
                raise ValueError("Invalid content length")
            raw = self.rfile.read(length)
            if undo:
                return self.send(200, store.undo(undo[1]))
            payload = json.loads(raw)
            return self.send(200, store.perform(action[1], payload, self.headers.get("Idempotency-Key")))

        def mutation(self, method):
            try:
                path = urlsplit(self.path).path
                if typed:
                    return self.typed_mutation(path, method)
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
                self.fail(error, 404, "not_found")
            except (ValueError, TypeError) as error:
                self.fail(error)
            except sqlite3.DatabaseError:
                if not typed:
                    raise
                self.fail("Storage temporarily unavailable", 503, "storage_unavailable")

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
    root = Path(__file__).resolve().parent
    render_template = _render_template
    preview_renderer = os.environ.get("VITRUVIUS_PREVIEW_SOURCE_MAP")
    if preview_renderer:
        render_template = runpy.run_path(preview_renderer)["render_template"]
    server = make_server(root, args.database, host=args.host, port=args.port, revision=args.revision,
                         render_template=render_template)
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
