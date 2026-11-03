"""Stateful HTTP sequence execution against a real service (standard library only).

This module is the single executor for stateful sequences. Theseus imports it, and an exported regression copies it
verbatim next to the generated pytest file (as ``theseus_stateful_adapter.py`` with ``theseus_expressions.py``), so
the receiver runs exactly the same code without Theseus, network access or a language model.

A recipe declares a target (a command started on a free port with a fresh sandbox per run, or a base URL with an
optional reset request), a model (named variables with initial values), actions and oracles. An action has an
explicit precondition over the model, seeded parameters, picks of values bound by earlier responses (recorded by
index, never by value, so a replay against another process or version re-binds identifiers from its own responses),
a request template, an expected status, extractors, model updates and postconditions. Invariants are checked after
every step and may read declared read-only SQLite queries. An optional reference target receives the same symbolic
steps and ``agree`` relations compare both responses.

Outcomes: ``passed``; ``failed`` (an HTTP status the action does not accept, a crash, a timeout, a failed extractor,
a postcondition, an invariant or a reference relation); ``invalid`` (a precondition no longer holds, so the
candidate is not a valid sequence); ``inconclusive`` (the target could not be started, reset or prepared, so the
chain never ran completely); ``error`` (an oracle expression could not be evaluated: a recipe defect).
"""
import ast
import base64
import fnmatch
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

try:
    from .expressions import Expression, ExpressionError
except ImportError:  # running as an exported, standalone adapter
    from theseus_expressions import Expression, ExpressionError

FORMAT = "theseus-stateful/1"
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
RESPONSE = ("status", "body", "headers", "text")
FATAL = ("http_status", "crash", "timeout", "transport", "extraction")
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
CLIP = 2000
LIMIT_ACTIONS, LIMIT_RUNS, LIMIT_LENGTH = 40, 500, 60


class SetupFailure(Exception):
    """The target could not be started, reset or prepared: the chain is inconclusive."""


class RecipeError(ValueError):
    pass


def clip(value):
    if isinstance(value, str):
        return value if len(value) <= CLIP else value[:CLIP] + "...[truncated]"
    text = json.dumps(value, ensure_ascii=False, default=str)
    return value if len(text) <= CLIP else text[:CLIP] + "...[truncated]"


# ------------------------------------------------------------------ validation

def _expr(source, names, where):
    try:
        Expression(str(source), names)
    except ExpressionError as exc:
        raise RecipeError(where + " rejected: " + str(exc)) from exc
    return str(source).strip()


def _templates(value, names, where):
    """Every {placeholder} in a template (text or JSON structure) must be a known name."""
    if isinstance(value, str):
        for name in PLACEHOLDER.findall(value):
            if name not in names and name not in ("sandbox", "port", "python"):
                raise RecipeError("%s uses {%s}, which is not a model variable, parameter or pick" % (where, name))
    elif isinstance(value, dict):
        for k, v in value.items():
            _templates(k, names, where)
            _templates(v, names, where)
    elif isinstance(value, list):
        for v in value:
            _templates(v, names, where)


def _relative(path, where):
    if not isinstance(path, str) or not path.strip():
        raise RecipeError(where + " needs a relative path")
    pure = Path(path)
    if pure.is_absolute() or ".." in pure.parts or path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", path):
        raise RecipeError(where + " must stay inside the sandbox: " + path)
    return path.replace("\\", "/")


def _status_list(value, where):
    if value is None:
        return None
    values = value if isinstance(value, list) else [value]
    if not values or any(isinstance(v, bool) or not isinstance(v, int) or not 100 <= v <= 599 for v in values):
        raise RecipeError(where + " is an HTTP status or a list of statuses (100-599)")
    return values


def _request(value, names, where):
    if not isinstance(value, dict) or set(value) - {"method", "path", "headers", "body"}:
        raise RecipeError(where + " is {method, path, headers, body}")
    method = str(value.get("method", "GET")).upper()
    path = value.get("path", "/")
    if method not in METHODS or not isinstance(path, str) or not path.startswith("/"):
        raise RecipeError(where + ": method is one of %s and path starts with /" % ", ".join(METHODS))
    headers = value.get("headers") or {}
    if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()):
        raise RecipeError(where + ".headers map text to text")
    body = value.get("body")
    json.dumps(body)
    _templates([path, headers, body], names, where)
    return {"method": method, "path": path, "headers": dict(headers), "body": body}


def validate_target(value, where="target"):
    if not isinstance(value, dict):
        raise RecipeError(where + " is {argv, ...} or {base_url, reset}")
    if "base_url" in value:
        if set(value) - {"base_url", "reset", "request_timeout_seconds", "label"}:
            raise RecipeError(where + " with base_url is {base_url, reset, request_timeout_seconds, label}")
        url = urlsplit(str(value["base_url"]))
        if url.scheme != "http" or not url.hostname:
            raise RecipeError(where + ".base_url must be http://host[:port]")
        return {"base_url": str(value["base_url"]).rstrip("/"),
                "reset": _request(value["reset"], set(), where + ".reset") if value.get("reset") else None,
                "request_timeout_seconds": float(value.get("request_timeout_seconds", 10)), "label": str(value.get("label", ""))}
    allowed = {"argv", "cwd", "env", "port_env", "ready", "ready_timeout_seconds", "request_timeout_seconds", "files", "db", "label"}
    if set(value) - allowed:
        raise RecipeError(where + " has unknown fields: " + ", ".join(sorted(set(value) - allowed)))
    argv = value.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a for a in argv):
        raise RecipeError(where + ".argv must be a nonempty array of text (placeholders: {python}, {sandbox}, {port})")
    env = value.get("env") or {}
    if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
        raise RecipeError(where + ".env maps text to text")
    files = value.get("files") or {}
    if not isinstance(files, dict):
        raise RecipeError(where + ".files maps a relative path to text or {base64}")
    for path, content in files.items():
        _relative(path, where + " file")
        if not isinstance(content, str) and not (isinstance(content, dict) and set(content) == {"base64"}):
            raise RecipeError(where + " file content is text or {\"base64\": ...}")
    db = value.get("db")
    if db is not None:
        if not isinstance(db, dict) or set(db) - {"path", "seed_sql"}:
            raise RecipeError(where + ".db is {path, seed_sql}")
        db = {"path": _relative(db.get("path", "app.db"), where + ".db"), "seed_sql": str(db.get("seed_sql", ""))}
    ready = value.get("ready")
    if isinstance(ready, str):
        ready = {"method": "GET", "path": ready}
    if ready is not None:
        ready = _request(ready, set(), where + ".ready")
    timeout = float(value.get("ready_timeout_seconds", 20))
    if not 0 < timeout <= 300:
        raise RecipeError(where + ".ready_timeout_seconds is between 0 and 300")
    return {"argv": list(argv), "cwd": value.get("cwd"), "env": dict(env), "port_env": str(value.get("port_env", "PORT")),
            "ready": ready, "ready_timeout_seconds": timeout,
            "request_timeout_seconds": float(value.get("request_timeout_seconds", 10)),
            "files": dict(files), "db": db, "label": str(value.get("label", ""))}


def _named_exprs(values, names, where, default_prefix):
    out = []
    for j, item in enumerate(values or []):
        entry = item if isinstance(item, dict) else {"expr": item}
        if not isinstance(entry, dict) or set(entry) - {"name", "expr", "explain"}:
            raise RecipeError(where + " entries are {name, expr, explain} or expression text")
        name = str(entry.get("name") or "%s-%d" % (default_prefix, j + 1))
        out.append({"name": name, "expr": _expr(entry.get("expr", ""), names, "%s %s" % (where, name)),
                    "explain": str(entry.get("explain", ""))})
    return out


def validate_recipe(value, strategy_validate=None):
    """Normalised recipe or RecipeError. ``strategy_validate`` validates parameter strategies (Theseus side)."""
    allowed = {"name", "target", "reference", "model", "setup", "actions", "invariants", "queries", "watch",
               "server_errors_fail", "runs", "max_length", "seed", "description"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise RecipeError("recipe is {%s}" % ", ".join(sorted(allowed)))
    recipe = {"format": FORMAT, "name": str(value.get("name") or "stateful"), "description": str(value.get("description", ""))}
    recipe["target"] = validate_target(value.get("target"), "target")
    recipe["reference"] = validate_target(value["reference"], "reference") if value.get("reference") else None
    model = value.get("model") or {}
    if not isinstance(model, dict) or any(not isinstance(k, str) or not k.isidentifier() for k in model):
        raise RecipeError("model maps variable names (identifiers) to initial JSON values")
    json.dumps(model)
    reserved = set(RESPONSE) | {"sql", "step", "action", "ref_status", "ref_body", "ref_headers", "ref_text"}
    if set(model) & reserved:
        raise RecipeError("model variables may not be named " + ", ".join(sorted(set(model) & reserved)))
    recipe["model"] = json.loads(json.dumps(model))
    mvars = tuple(model)
    watch = value.get("watch") or {}
    if not isinstance(watch, dict) or set(watch) - {"sqlite", "tables", "files"}:
        raise RecipeError("watch is {sqlite, tables, files}")
    sqlite_path = watch.get("sqlite")
    if sqlite_path is not None and not isinstance(sqlite_path, str):
        raise RecipeError("watch.sqlite is a database path (relative to the sandbox, or absolute with base_url)")
    if sqlite_path and "argv" in recipe["target"]:
        sqlite_path = _relative(sqlite_path, "watch.sqlite")
    tables = watch.get("tables")
    if tables is not None and (not isinstance(tables, list) or any(not isinstance(t, str) for t in tables)):
        raise RecipeError("watch.tables is a list of table names")
    globs = watch.get("files") or []
    if not isinstance(globs, list) or any(not isinstance(g, str) for g in globs):
        raise RecipeError("watch.files is a list of glob patterns relative to the sandbox")
    if globs and "argv" not in recipe["target"]:
        raise RecipeError("watch.files needs a started target (its sandbox); a base_url target has none")
    recipe["watch"] = {"sqlite": sqlite_path, "tables": tables, "files": list(globs)}
    queries = value.get("queries") or {}
    if not isinstance(queries, dict) or any(not str(k).isidentifier() or not isinstance(q, str) for k, q in queries.items()):
        raise RecipeError("queries map identifiers to read-only SQL text")
    if queries and not sqlite_path:
        raise RecipeError("queries need watch.sqlite")
    for name, sql in queries.items():
        if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.I) or ";" in sql.strip().rstrip(";"):
            raise RecipeError("query %s must be a single SELECT statement" % name)
    recipe["queries"] = dict(queries)
    sql_names = ("sql",) if queries else ()
    recipe["setup"] = []
    for i, item in enumerate(value.get("setup") or []):
        where = "setup %d" % (i + 1)
        if not isinstance(item, dict) or set(item) - {"name", "request", "expect_status", "extract"}:
            raise RecipeError(where + " is {name, request, expect_status, extract}")
        extract = item.get("extract") or {}
        if not isinstance(extract, dict) or set(extract) - set(mvars):
            raise RecipeError(where + ".extract assigns existing model variables")
        names = mvars + RESPONSE
        recipe["setup"].append({"name": str(item.get("name") or "setup-%d" % (i + 1)),
                                "request": _request(item.get("request"), set(mvars), where + ".request"),
                                "expect_status": _status_list(item.get("expect_status"), where + ".expect_status"),
                                "extract": {k: _expr(v, names, "%s extract %s" % (where, k)) for k, v in extract.items()}})
    actions = value.get("actions") or []
    if not isinstance(actions, list) or not actions or len(actions) > LIMIT_ACTIONS:
        raise RecipeError("actions is a nonempty list of at most %d actions" % LIMIT_ACTIONS)
    recipe["actions"], seen = [], set()
    for i, act in enumerate(actions):
        keys = {"name", "pre", "params", "pick", "request", "expect_status", "extract", "update", "post", "agree", "explain"}
        if not isinstance(act, dict) or set(act) - keys:
            raise RecipeError("action %d is {%s}" % (i + 1, ", ".join(sorted(keys))))
        name = str(act.get("name") or "")
        if not name or name in seen or not re.match(r"^[A-Za-z0-9_.-]+$", name):
            raise RecipeError("every action needs a unique name of letters, digits, '.', '_' or '-'")
        seen.add(name)
        where = "action " + name
        params = act.get("params") or {}
        if not isinstance(params, dict) or any(not str(k).isidentifier() or k in mvars for k in params):
            raise RecipeError(where + ": params map identifiers (distinct from model variables) to strategies")
        params = {k: (strategy_validate(v, "%s.%s" % (where, k)) if strategy_validate else v) for k, v in params.items()}
        picks = act.get("pick") or {}
        if not isinstance(picks, dict) or any(not str(k).isidentifier() or k in mvars or k in params or v not in mvars
                                              for k, v in picks.items()):
            raise RecipeError(where + ": pick maps a new name to a list model variable (an element is chosen by index)")
        scope = mvars + tuple(params) + tuple(picks) + tuple(k + "_index" for k in picks)
        pre = _expr(act["pre"], scope, where + " pre") if act.get("pre") else None
        request = _request(act.get("request"), set(scope), where + ".request")
        extract = act.get("extract") or {}
        if not isinstance(extract, dict) or any(not str(k).isidentifier() or k in scope for k in extract):
            raise RecipeError(where + ": extract maps new local names to expressions over the response")
        extracted = {k: _expr(v, scope + RESPONSE, "%s extract %s" % (where, k)) for k, v in extract.items()}
        local = scope + RESPONSE + tuple(extract)
        update = act.get("update") or {}
        if not isinstance(update, dict) or set(update) - set(mvars):
            raise RecipeError(where + ": update assigns existing model variables")
        updates = {k: _expr(v, local, "%s update %s" % (where, k)) for k, v in update.items()}
        post_names = local + tuple("old_" + m for m in mvars) + sql_names
        post = _named_exprs(act.get("post"), post_names, where + " post", "post")
        agree = []
        if act.get("agree"):
            if not recipe["reference"]:
                raise RecipeError(where + ".agree needs a reference target")
            agree = _named_exprs(act["agree"], post_names + ("ref_status", "ref_body", "ref_headers", "ref_text"),
                                 where + " agree", "agree")
        recipe["actions"].append({"name": name, "pre": pre, "params": params, "pick": dict(picks), "request": request,
                                  "expect_status": _status_list(act.get("expect_status"), where + ".expect_status"),
                                  "extract": extracted, "update": updates, "post": post, "agree": agree,
                                  "explain": str(act.get("explain", ""))})
    recipe["invariants"] = _named_exprs(value.get("invariants"), mvars + sql_names + ("step", "action"), "invariant", "invariant")
    recipe["server_errors_fail"] = bool(value.get("server_errors_fail", True))
    for label, default, limit in (("runs", 20, LIMIT_RUNS), ("max_length", 8, LIMIT_LENGTH)):
        number = value.get(label, default)
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= limit:
            raise RecipeError("%s is an integer from 1 to %d" % (label, limit))
        recipe[label] = number
    seed = value.get("seed", 1)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise RecipeError("seed must be an integer")
    recipe["seed"] = seed
    return recipe


# ------------------------------------------------------------------ oracle explanations

def _names_in(source):
    try:
        return {n.id for n in ast.walk(ast.parse(source, mode="eval")) if isinstance(n, ast.Name)}
    except SyntaxError:
        return set()


def evidence_of(source):
    names = _names_in(source)
    if "sql" in names:
        return "sqlite"
    if names & {"ref_status", "ref_body", "ref_headers", "ref_text"}:
        return "reference"
    if names & set(RESPONSE):
        return "http"
    return "model"


def explain(source, env):
    """Values of the operands of a failed comparison (or boolean parts), each re-evaluated, plus the names read."""
    parts = []
    try:
        tree = ast.parse(source.strip(), mode="eval").body
        nodes = [tree.left, *tree.comparators] if isinstance(tree, ast.Compare) else list(tree.values) if isinstance(tree, ast.BoolOp) else []
        if isinstance(tree, ast.UnaryOp) and isinstance(tree.op, ast.Not):
            nodes = [tree.operand]
        for node in nodes:
            text = ast.unparse(node)
            try:
                parts.append({"expr": text, "value": clip(Expression(text, tuple(env)).evaluate(env))})
            except ExpressionError as exc:
                parts.append({"expr": text, "error": str(exc)})
    except SyntaxError:
        pass
    names = {n: clip(env[n]) for n in sorted(_names_in(source)) if n in env}
    return {"operands": parts, "names": names}


def _evaluate(source, env):
    return Expression(source, tuple(env)).evaluate(env)


# ------------------------------------------------------------------ rendering

def render(template, env):
    """Fill {name} placeholders: a string that is exactly one placeholder keeps the value's JSON type."""
    if isinstance(template, str):
        whole = PLACEHOLDER.fullmatch(template)
        if whole and whole.group(1) in env:
            return env[whole.group(1)]
        return PLACEHOLDER.sub(lambda m: (env[m.group(1)] if isinstance(env.get(m.group(1)), str)
                                          else json.dumps(env[m.group(1)], ensure_ascii=False)) if m.group(1) in env else m.group(0),
                               template)
    if isinstance(template, dict):
        return {render(k, env) if isinstance(k, str) else k: render(v, env) for k, v in template.items()}
    if isinstance(template, list):
        return [render(v, env) for v in template]
    return template


def _text_render(template, env):
    value = render(template, env)
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


# ------------------------------------------------------------------ side-effect snapshots

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _sqlite_copy(path):
    """Copy a live SQLite database (with its WAL) to a scratch file; returns (scratch_dir, copy) or None."""
    path = Path(path)
    if not path.is_file():
        return None
    scratch = Path(tempfile.mkdtemp(prefix="theseus-sql-"))
    copy = scratch / "copy.db"
    shutil.copyfile(path, copy)
    for suffix in ("-wal",):
        if Path(str(path) + suffix).exists():
            shutil.copyfile(str(path) + suffix, str(copy) + suffix)
    return scratch, copy


def _read_only(connection):
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}

    def authorize(action, *_):
        return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY
    connection.set_authorizer(authorize)


def sqlite_state(path, tables=None, queries=None):
    """Rows of the watched tables (by primary key when there is one) and the declared read-only query results."""
    made = _sqlite_copy(path) if path else None
    if made is None:
        return {"present": False, "tables": {}, "queries": {}}
    scratch, copy = made
    try:
        connection = sqlite3.connect(copy)
        try:
            names = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            state = {}
            for name in names:
                if tables is not None and name not in tables:
                    continue
                quoted = '"' + name.replace('"', '""') + '"'
                info = list(connection.execute("PRAGMA table_info(" + quoted + ")"))
                columns = [r[1] for r in info]
                pk = [r[1] for r in sorted((r for r in info if r[5]), key=lambda r: r[5])]
                rows = {}
                for n, row in enumerate(connection.execute("SELECT * FROM " + quoted)):
                    record = dict(zip(columns, [v.hex() if isinstance(v, bytes) else v for v in row]))
                    key = json.dumps([record[c] for c in pk] if pk else [n, record], ensure_ascii=False, default=str)
                    rows[key] = record
                state[name] = {"pk": pk, "rows": rows}
            _read_only(connection)
            results = {}
            for qname, sql in (queries or {}).items():
                results[qname] = [list(r) for r in connection.execute(sql)]
            return {"present": True, "tables": state, "queries": results}
        finally:
            connection.close()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def sqlite_diff(before, after):
    out = {}
    for name in sorted(set(before.get("tables", {})) | set(after.get("tables", {}))):
        old = before.get("tables", {}).get(name, {"rows": {}})["rows"]
        new = after.get("tables", {}).get(name, {"rows": {}})["rows"]
        added = [new[k] for k in new if k not in old]
        removed = [old[k] for k in old if k not in new]
        changed = [{"before": old[k], "after": new[k]} for k in new if k in old and old[k] != new[k]]
        if added or removed or changed:
            out[name] = {"added": len(added), "removed": len(removed), "changed": len(changed),
                         "sample": {"added": added[:5], "removed": removed[:5], "changed": changed[:5]}}
    return out


def files_state(root, globs, skip=()):
    state = {}
    if not root or not globs:
        return state
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in skip or not any(fnmatch.fnmatch(rel, g) for g in globs):
            continue
        state[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return state


def files_diff(before, after):
    out = {}
    for rel in sorted(set(before) | set(after)):
        if rel not in before:
            out[rel] = {"op": "created", "sha256": after[rel]}
        elif rel not in after:
            out[rel] = {"op": "deleted"}
        elif before[rel] != after[rel]:
            out[rel] = {"op": "modified", "sha256": after[rel]}
    return out


# ------------------------------------------------------------------ lanes (one target process or URL)

class Lane:
    """One target: started fresh in its own sandbox on a free port, or an existing base URL (optionally reset)."""

    def __init__(self, recipe, target, label):
        self.recipe, self.target, self.label = recipe, target, label
        self.process = self.root = self.sandbox = None
        self.host, self.port = "127.0.0.1", None
        self.model = json.loads(json.dumps(recipe["model"]))
        self.err_path = None

    def _sub(self, text):
        text = text.replace("{python}", sys.executable)
        if self.sandbox is not None:
            text = text.replace("{sandbox}", str(self.sandbox))
        if self.port is not None:
            text = text.replace("{port}", str(self.port))
        return text

    def start(self):
        t = self.target
        if "base_url" in t:
            url = urlsplit(t["base_url"])
            self.host, self.port, self.prefix = url.hostname, url.port or 80, url.path.rstrip("/")
            if t["reset"]:
                try:
                    got = self.request(t["reset"]["method"], t["reset"]["path"], t["reset"]["headers"], t["reset"]["body"])
                except OSError as exc:
                    raise SetupFailure("reset request failed: %s" % exc) from exc
                if got["status"] >= 400:
                    raise SetupFailure("reset request answered HTTP %s" % got["status"])
            return
        self.prefix = ""
        self.root = Path(tempfile.mkdtemp(prefix="theseus-stateful-"))
        self.sandbox = self.root / "sandbox"
        self.sandbox.mkdir()
        for rel, content in t["files"].items():
            path = self.sandbox / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(content["base64"]) if isinstance(content, dict) else content.encode("utf-8"))
        if t["db"]:
            path = self.sandbox / t["db"]["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path)
            try:
                if t["db"]["seed_sql"].strip():
                    connection.executescript(t["db"]["seed_sql"])
                connection.commit()
            finally:
                connection.close()
        self.port = _free_port()
        argv = [self._sub(a) for a in t["argv"]]
        cwd = self._sub(t["cwd"]) if t.get("cwd") else str(self.sandbox)
        if not Path(cwd).is_absolute():
            cwd = str(self.sandbox / cwd)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "THESEUS_SANDBOX": str(self.sandbox),
               **{k: self._sub(v) for k, v in t["env"].items()}, t["port_env"]: str(self.port)}
        self.err_path = self.root / "server.err"
        try:
            with open(self.err_path, "wb") as err:
                self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                                stdout=subprocess.DEVNULL, stderr=err)
        except OSError as exc:
            raise SetupFailure("target could not be started: %s" % exc) from exc
        deadline = time.monotonic() + t["ready_timeout_seconds"]
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise SetupFailure("target exited with code %s before becoming ready: %s" % (self.process.returncode, self.stderr_tail()))
            try:
                if t["ready"]:
                    got = self.request(t["ready"]["method"], t["ready"]["path"], {}, None, timeout=1)
                    if got["status"] < 500:
                        return
                else:
                    socket.create_connection((self.host, self.port), timeout=.3).close()
                    return
            except OSError:
                pass
            time.sleep(.05)
        raise SetupFailure("target did not become ready within %.0f s" % t["ready_timeout_seconds"])

    def stderr_tail(self):
        try:
            return self.err_path.read_text(encoding="utf-8", errors="replace")[-600:] if self.err_path else ""
        except OSError:
            return ""

    def alive(self):
        return self.process is None or self.process.poll() is None

    def request(self, method, path, headers, body, timeout=None):
        payload, sent_headers = None, dict(headers)
        if body is not None:
            if isinstance(body, str):
                payload = body.encode("utf-8")
            else:
                payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
                if not any(k.lower() == "content-type" for k in sent_headers):
                    sent_headers["Content-Type"] = "application/json"
        sent_headers["Connection"] = "close"
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout or self.target["request_timeout_seconds"])
        try:
            connection.request(method, self.prefix + path, body=payload, headers=sent_headers)
            response = connection.getresponse()
            raw = response.read()
            headers_out = {k.lower(): v for k, v in response.getheaders()}
            status = response.status
        finally:
            connection.close()
        text = raw.decode("utf-8", "replace")
        try:
            parsed = json.loads(text) if text.strip() else None
        except ValueError:
            parsed = text
        return {"status": status, "body": parsed, "headers": headers_out, "text": text}

    def db_path(self):
        path = self.recipe["watch"]["sqlite"]
        if not path:
            return None
        return Path(path) if self.sandbox is None else self.sandbox / path

    def snapshot(self):
        w = self.recipe["watch"]
        sql = sqlite_state(self.db_path(), w["tables"], self.recipe["queries"]) if w["sqlite"] else None
        skip = ()
        if w["sqlite"] and self.sandbox is not None:
            skip = tuple(w["sqlite"] + s for s in ("", "-wal", "-shm", "-journal"))
        files = files_state(self.sandbox, w["files"], skip) if w["files"] else None
        return {"sql": sql, "files": files}

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.root is not None:
            for _ in range(20):
                shutil.rmtree(self.root, ignore_errors=True)
                if not self.root.exists():
                    break
                time.sleep(.05)


# ------------------------------------------------------------------ sessions

class Session:
    """A fresh main lane (plus an optional reference lane) executing symbolic steps one at a time."""

    def __init__(self, recipe, target=None, reference=None):
        self.recipe = recipe
        self.actions = {a["name"]: a for a in recipe["actions"]}
        self.main = Lane(recipe, target or recipe["target"], "target")
        ref = reference if reference is not None else recipe["reference"]
        self.reference = Lane(recipe, ref, "reference") if ref else None
        self.lanes = [self.main] + ([self.reference] if self.reference else [])
        self.trace, self.ids = [], []
        self.state = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        for lane in self.lanes:
            lane.close()

    def start(self):
        """Start (or reset) every lane and run setup requests. Raises SetupFailure (inconclusive)."""
        for lane in self.lanes:
            lane.start()
            for item in self.recipe["setup"]:
                env = dict(lane.model)
                req = item["request"]
                try:
                    got = lane.request(req["method"], _text_render(req["path"], env),
                                       {k: _text_render(v, env) for k, v in req["headers"].items()}, render(req["body"], env))
                except OSError as exc:
                    raise SetupFailure("setup %s on %s failed: %s" % (item["name"], lane.label, exc)) from exc
                if item["expect_status"] and got["status"] not in item["expect_status"]:
                    raise SetupFailure("setup %s on %s answered HTTP %s (expected %s): %s" % (
                        item["name"], lane.label, got["status"], item["expect_status"], clip(got["text"])[:300]))
                try:
                    for var, source in item["extract"].items():
                        lane.model[var] = _evaluate(source, {**lane.model, **got})
                except ExpressionError as exc:
                    raise SetupFailure("setup %s extract failed on %s: %s" % (item["name"], lane.label, exc)) from exc
        self.state = [lane.snapshot() for lane in self.lanes]

    # ---- symbolic steps
    def bind(self, lane, step):
        """Environment for a step on one lane (model + params + picks), or None if the precondition fails."""
        action = self.actions.get(step["action"])
        if action is None:
            return None
        env = {**lane.model, **step.get("params", {})}
        for name, var in action["pick"].items():
            index = step.get("picks", {}).get(name)
            values = lane.model.get(var)
            if not isinstance(values, list) or not isinstance(index, int) or not 0 <= index < len(values):
                return None
            env[name], env[name + "_index"] = values[index], index
        if action["pre"]:
            try:
                if not _evaluate(action["pre"], env):
                    return None
            except ExpressionError:
                return None
        return env

    def enabled(self, step):
        return all(self.bind(lane, step) is not None for lane in self.lanes)

    def _send(self, lane, action, env):
        req = action["request"]
        rendered = {"method": req["method"], "path": _text_render(req["path"], env),
                    "headers": {k: _text_render(v, env) for k, v in req["headers"].items()}, "body": render(req["body"], env)}
        try:
            return rendered, lane.request(rendered["method"], rendered["path"], rendered["headers"], rendered["body"]), None
        except socket.timeout:
            return rendered, None, {"kind": "timeout", "name": "timeout", "evidence": "process",
                                    "detail": "no response within %.1f s" % lane.target["request_timeout_seconds"]}
        except (OSError, http.client.HTTPException) as exc:
            time.sleep(.1)
            if not lane.alive():
                return rendered, None, {"kind": "crash", "name": "process exited", "evidence": "process",
                                        "detail": "target exited with code %s: %s" % (lane.process.returncode, lane.stderr_tail())}
            return rendered, None, {"kind": "transport", "name": type(exc).__name__, "evidence": "process", "detail": str(exc)}

    def _check(self, sources, env, kind):
        violations, errors = [], []
        for item in sources:
            try:
                ok = bool(_evaluate(item["expr"], env))
            except ExpressionError as exc:
                errors.append({"kind": kind, "name": item["name"], "expr": item["expr"], "detail": "could not evaluate: " + str(exc)})
                continue
            if not ok:
                violations.append({"kind": kind, "name": item["name"], "expr": item["expr"], "evidence": evidence_of(item["expr"]),
                                   "explain": item.get("explain", ""), "observed": explain(item["expr"], env)})
        return violations, errors

    def execute(self, step, index):
        """Execute one symbolic step on every lane. Returns the step record; record['outcome'] is
        'ok', 'failed', 'invalid' or 'error'."""
        action = self.actions[step["action"]]
        record = {"index": index, "action": action["name"], "params": step.get("params", {}), "picks": step.get("picks", {}),
                  "lanes": {}, "violations": [], "errors": [], "outcome": "ok"}
        envs = [self.bind(lane, step) for lane in self.lanes]
        if envs[0] is None:
            record["outcome"] = "invalid"
            record["detail"] = "precondition or pick does not hold on the target"
            return record
        if len(envs) > 1 and envs[1] is None:
            record["outcome"] = "inconclusive"
            record["detail"] = "the reference cannot take this step (its model diverged)"
            return record
        results = []
        for n, (lane, env) in enumerate(zip(self.lanes, envs)):
            rendered, got, fatal = self._send(lane, action, env)
            lane_record = {"request": rendered}
            if got is not None:
                lane_record["response"] = {"status": got["status"], "body": clip(got["body"]), "headers": {
                    k: v for k, v in got["headers"].items() if k in ("content-type", "location", "idempotency-key", "etag")}}
            if fatal is None and action["expect_status"] and got["status"] not in action["expect_status"]:
                fatal = {"kind": "http_status", "name": "status %s" % got["status"], "evidence": "http",
                         "detail": "HTTP %s is not an accepted status %s" % (got["status"], action["expect_status"]),
                         "observed": {"status": got["status"], "body": clip(got["text"])}}
            if fatal is None and not action["expect_status"] and self.recipe["server_errors_fail"] and got["status"] >= 500:
                fatal = {"kind": "http_status", "name": "status %s" % got["status"], "evidence": "http",
                         "detail": "server error HTTP %s" % got["status"], "observed": {"status": got["status"], "body": clip(got["text"])}}
            extracted = {}
            if fatal is None:
                local = {**env, **{k: got[k] for k in RESPONSE}}
                for var, source in action["extract"].items():
                    try:
                        extracted[var] = _evaluate(source, local)
                    except ExpressionError as exc:
                        fatal = {"kind": "extraction", "name": var, "expr": source, "evidence": "http",
                                 "detail": "extractor failed on the response: " + str(exc), "observed": {"status": got["status"], "body": clip(got["body"])}}
                        break
                if extracted:
                    lane_record["extracted"] = {k: clip(v) for k, v in extracted.items()}
                    if lane is self.main:
                        self.ids.extend(str(v) for v in extracted.values() if isinstance(v, (str, int)) and not isinstance(v, bool))
            if fatal is not None:
                fatal["lane"] = lane.label
                if lane is self.main:
                    record["violations"].append(fatal)
                    record["lanes"][lane.label] = lane_record
                    record["outcome"] = "failed"
                else:
                    record["lanes"][lane.label] = lane_record
                    record["outcome"] = "inconclusive"
                    record["detail"] = "the reference failed this step: " + fatal["detail"]
                return record
            local = {**env, **{k: got[k] for k in RESPONSE}, **extracted}
            new = dict(lane.model)
            try:
                for var, source in action["update"].items():
                    new[var] = _evaluate(source, local)
            except ExpressionError as exc:
                record["errors"].append({"kind": "update", "name": var, "expr": source, "detail": str(exc), "lane": lane.label})
                record["outcome"] = "error"
                return record
            results.append((lane, env, got, extracted, local, new, lane_record))
        # side effects and oracles, after every lane has answered
        for lane, env, got, extracted, local, new, lane_record in results:
            n = self.lanes.index(lane)
            after = lane.snapshot()
            before = self.state[n] if self.state else {"sql": None, "files": None}
            effects = {}
            if after["sql"] is not None:
                effects["sqlite"] = sqlite_diff(before["sql"] or {}, after["sql"])
            if after["files"] is not None:
                effects["files"] = files_diff(before["files"] or {}, after["files"])
            lane_record["effects"] = effects
            self.state[n] = after
            old = lane.model
            lane.model = new
            lane_record["model"] = {k: clip(v) for k, v in new.items()}
            if lane is not self.main:
                continue
            check = {**local, **new, **{"old_" + k: v for k, v in old.items()}}
            if self.recipe["queries"]:
                check["sql"] = (after["sql"] or {}).get("queries", {})
            violations, errors = self._check(action["post"], check, "postcondition")
            inv_env = {**new, "step": index, "action": action["name"]}
            if self.recipe["queries"]:
                inv_env["sql"] = check["sql"]
            v2, e2 = self._check(self.recipe["invariants"], inv_env, "invariant")
            violations += v2
            errors += e2
            if self.reference is not None and action["agree"]:
                ref = results[1]
                agree_env = {**check, "ref_status": ref[2]["status"], "ref_body": ref[2]["body"], "ref_headers": ref[2]["headers"],
                             "ref_text": ref[2]["text"]}
                v3, e3 = self._check(action["agree"], agree_env, "reference")
                violations += v3
                errors += e3
            record["violations"] += violations
            record["errors"] += errors
        for lane, *_rest, lane_record in results:
            record["lanes"][lane.label] = lane_record
        if record["errors"]:
            record["outcome"] = "error"
        elif record["violations"]:
            record["outcome"] = "failed"
        return record


def signature(failure):
    """Failure signature kept during reduction: action, kind and oracle (or status) name."""
    return None if failure is None else [failure["action"], failure["kind"], failure["name"]]


def run_sequence(recipe, sequence, target=None, reference=None):
    """Execute a symbolic sequence in a fresh session. Returns the outcome with the full trace."""
    with Session(recipe, target, reference) as session:
        try:
            session.start()
        except SetupFailure as exc:
            return {"outcome": "inconclusive", "reason": "setup: " + str(exc), "trace": [], "ids": [], "steps_run": 0}
        for i, step in enumerate(sequence):
            record = session.execute(step, i)
            session.trace.append(record)
            if record["outcome"] == "ok":
                continue
            result = {"outcome": record["outcome"], "trace": session.trace, "ids": session.ids, "steps_run": i + 1,
                      "at": i}
            if record["outcome"] == "failed":
                first = record["violations"][0]
                result["failure"] = {"index": i, "action": record["action"], **first}
                result["violations"] = record["violations"]
                result["signature"] = signature(result["failure"])
            elif record["outcome"] == "inconclusive":
                result["reason"] = record.get("detail", "")
            elif record["outcome"] == "invalid":
                result["reason"] = "step %d (%s): %s" % (i + 1, record["action"], record.get("detail", ""))
            else:
                result["reason"] = "oracle or update expression could not be evaluated"
                result["errors"] = record["errors"]
            return result
        return {"outcome": "passed", "trace": session.trace, "ids": session.ids, "steps_run": len(sequence)}


def describe(result):
    """One human-readable paragraph for a run_sequence result (used in reports and exported tests)."""
    if result["outcome"] == "passed":
        return "All %d steps ran and every declared oracle held." % result["steps_run"]
    if result["outcome"] != "failed":
        return "%s: %s" % (result["outcome"], result.get("reason", ""))
    lines = []
    f = result["failure"]
    lines.append("Step %d (%s) failed: %s %s via %s evidence." % (f["index"] + 1, f["action"], f["kind"], f["name"], f.get("evidence", "?")))
    for v in result["violations"]:
        line = "- [%s/%s] %s" % (v["kind"], v.get("evidence", "?"), v["name"])
        if v.get("expr"):
            line += ": " + v["expr"]
        if v.get("detail"):
            line += " (" + v["detail"] + ")"
        for part in (v.get("observed") or {}).get("operands", []):
            line += "\n    %s = %s" % (part["expr"], json.dumps(part.get("value", part.get("error")), ensure_ascii=False, default=str))
        lines.append(line)
    return "\n".join(lines)
