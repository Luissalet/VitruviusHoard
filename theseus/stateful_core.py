"""Stateful HTTP sequence execution against a real service (standard library only).

This module is the single executor for stateful sequences. Theseus imports it, and an exported regression copies it
verbatim next to the generated pytest file (as ``theseus_stateful_adapter.py`` with ``theseus_expressions.py``), so
the receiver runs exactly the same code without Theseus, network access or a language model.

A recipe declares a target (a command started on a free port with a fresh sandbox per run, or a base URL with an
optional reset request), a model (named variables with initial values), actions and oracles. An action has an
explicit precondition over the model, seeded parameters, picks of values bound by earlier responses (recorded either
by index into the model list, or by producer: ``{"from": <step id>, "var": <extractor>}``, the value that step
extracted; never by value, so a replay against another process or version re-binds identifiers from its own
responses),
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
import contextlib
import contextvars
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

# ------------------------------------------------------------------ messages (English and Spanish of Spain)
# Machine fields (outcomes, kinds, evidence, signatures, JSON field paths) are never translated; process stderr and
# expression-evaluator details are data and are inserted verbatim into the translated framing sentence.

LANGUAGES = ("en", "es")
MESSAGES = {
    "expr_rejected": ("{where} rejected: {detail}", "{where} rechazada: {detail}"),
    "unknown_placeholder": ("{where} uses {{{name}}}, which is not a model variable, parameter or pick",
                            "{where} usa {{{name}}}, que no es una variable del modelo, un parámetro ni una elección"),
    "needs_relative": ("{where} needs a relative path", "{where} necesita una ruta relativa"),
    "outside_sandbox": ("{where} must stay inside the sandbox: {path}", "{where} debe quedar dentro del entorno aislado: {path}"),
    "status_list": ("{where} is an HTTP status or a list of statuses (100-599)",
                    "{where} es un estado HTTP o una lista de estados (100-599)"),
    "request_shape": ("{where} is {{method, path, headers, body}}", "{where} es {{method, path, headers, body}}"),
    "request_method": ("{where}: method is one of {methods} and path starts with /",
                       "{where}: method es uno de {methods} y path empieza por /"),
    "headers_text": ("{where}.headers map text to text", "{where}.headers asocia texto con texto"),
    "target_shape": ("{where} is {{argv, ...}} or {{base_url, reset}}", "{where} es {{argv, ...}} o {{base_url, reset}}"),
    "base_url_shape": ("{where} with base_url is {{base_url, reset, request_timeout_seconds, label}}",
                       "{where} con base_url es {{base_url, reset, request_timeout_seconds, label}}"),
    "base_url_http": ("{where}.base_url must be http://host[:port]", "{where}.base_url debe ser http://host[:puerto]"),
    "unknown_fields": ("{where} has unknown fields: {fields}", "{where} tiene campos desconocidos: {fields}"),
    "argv_shape": ("{where}.argv must be a nonempty array of text (placeholders: {{python}}, {{sandbox}}, {{port}})",
                   "{where}.argv debe ser una lista de textos no vacía (marcadores: {{python}}, {{sandbox}}, {{port}})"),
    "env_text": ("{where}.env maps text to text", "{where}.env asocia texto con texto"),
    "files_shape": ("{where}.files maps a relative path to text or {{base64}}",
                    "{where}.files asocia una ruta relativa con texto o {{base64}}"),
    "file_content": ("{where} file content is text or {{\"base64\": ...}}",
                     "el contenido de un archivo de {where} es texto o {{\"base64\": ...}}"),
    "db_shape": ("{where}.db is {{path, seed_sql}}", "{where}.db es {{path, seed_sql}}"),
    "ready_timeout": ("{where}.ready_timeout_seconds is between 0 and 300", "{where}.ready_timeout_seconds está entre 0 y 300"),
    "entries_shape": ("{where} entries are {{name, expr, explain}} or expression text",
                      "las entradas de {where} son {{name, expr, explain}} o el texto de una expresión"),
    "recipe_shape": ("recipe is {{{fields}}}", "la receta es {{{fields}}}"),
    "model_shape": ("model maps variable names (identifiers) to initial JSON values",
                    "model asocia nombres de variable (identificadores) con valores JSON iniciales"),
    "model_reserved": ("model variables may not be named {names}", "las variables del modelo no pueden llamarse {names}"),
    "watch_shape": ("watch is {{sqlite, tables, files}}", "watch es {{sqlite, tables, files}}"),
    "watch_sqlite": ("watch.sqlite is a database path (relative to the sandbox, or absolute with base_url)",
                     "watch.sqlite es la ruta de una base de datos (relativa al entorno aislado, o absoluta con base_url)"),
    "watch_tables": ("watch.tables is a list of table names", "watch.tables es una lista de nombres de tabla"),
    "watch_files": ("watch.files is a list of glob patterns relative to the sandbox",
                    "watch.files es una lista de patrones glob relativos al entorno aislado"),
    "watch_files_target": ("watch.files needs a started target (its sandbox); a base_url target has none",
                           "watch.files necesita un destino arrancado (su entorno aislado); un destino base_url no lo tiene"),
    "queries_shape": ("queries map identifiers to read-only SQL text",
                      "queries asocia identificadores con SQL de sólo lectura"),
    "queries_need": ("queries need watch.sqlite", "queries necesita watch.sqlite"),
    "query_select": ("query {name} must be a single SELECT statement", "la consulta {name} debe ser una única sentencia SELECT"),
    "setup_shape": ("{where} is {{name, request, expect_status, extract}}", "{where} es {{name, request, expect_status, extract}}"),
    "setup_extract_shape": ("{where}.extract assigns existing model variables",
                            "{where}.extract asigna variables existentes del modelo"),
    "actions_shape": ("actions is a nonempty list of at most {limit} actions",
                      "actions es una lista no vacía de como máximo {limit} acciones"),
    "action_shape": ("action {n} is {{{fields}}}", "la acción {n} es {{{fields}}}"),
    "action_name": ("every action needs a unique name of letters, digits, '.', '_' or '-'",
                    "cada acción necesita un nombre único de letras, dígitos, '.', '_' o '-'"),
    "params_shape": ("{where}: params map identifiers (distinct from model variables) to strategies",
                     "{where}: params asocia identificadores (distintos de las variables del modelo) con estrategias"),
    "pick_shape": ("{where}: pick maps a new name to a list model variable (an element is chosen by index, or by the "
                   "step that produced it)",
                   "{where}: pick asocia un nombre nuevo con una variable lista del modelo (se elige un elemento por "
                   "índice o por el paso que lo produjo)"),
    "pick_ref_shape": ("step {n}: pick {pick} is an index or {{from, var}} naming a step id and one of its extractors",
                       "paso {n}: la elección {pick} es un índice o {{from, var}} con el id de un paso y uno de sus extractores"),
    "step_id_shape": ("step {n}: id must be unique text of letters, digits, '.', '_' or '-'",
                      "paso {n}: id debe ser un texto único de letras, dígitos, '.', '_' o '-'"),
    "pick_producer_unknown": ("step {n}: pick {pick} refers to {producer}.{var}, which is not an extractor of an earlier step",
                              "paso {n}: la elección {pick} se refiere a {producer}.{var}, que no es un extractor de un paso anterior"),
    "pick_unavailable": ("pick {pick}: step {producer} produced no {var} before this step",
                         "elección {pick}: el paso {producer} no produjo {var} antes de este paso"),
    "pick_gone": ("pick {pick}: the {var} produced by step {producer} is no longer in {pool}",
                  "elección {pick}: el {var} producido por el paso {producer} ya no está en {pool}"),
    "extract_shape": ("{where}: extract maps new local names to expressions over the response",
                      "{where}: extract asocia nombres locales nuevos con expresiones sobre la respuesta"),
    "update_shape": ("{where}: update assigns existing model variables", "{where}: update asigna variables existentes del modelo"),
    "agree_reference": ("{where}.agree needs a reference target", "{where}.agree necesita un destino de referencia"),
    "integer_range": ("{label} is an integer from 1 to {limit}", "{label} es un entero de 1 a {limit}"),
    "seed_integer": ("seed must be an integer", "seed debe ser un entero"),
    "where_setup": ("setup {n}", "preparación {n}"),
    "where_action": ("action {name}", "acción {name}"),
    "lane_target": ("target", "destino"),
    "lane_reference": ("reference", "referencia"),
    "reset_failed": ("reset request failed: {detail}", "la petición de reinicio falló: {detail}"),
    "reset_status": ("reset request answered HTTP {status}", "la petición de reinicio respondió HTTP {status}"),
    "start_failed": ("target could not be started: {detail}", "no se pudo arrancar el destino: {detail}"),
    "exited_before_ready": ("target exited with code {code} before becoming ready: {stderr}",
                            "el destino terminó con código {code} antes de estar listo: {stderr}"),
    "not_ready": ("target did not become ready within {seconds:.0f} s", "el destino no estuvo listo en {seconds:.0f} s"),
    "setup_failed": ("setup {name} on {lane} failed: {detail}", "la preparación {name} en {lane} falló: {detail}"),
    "setup_status": ("setup {name} on {lane} answered HTTP {status} (expected {expected}): {body}",
                     "la preparación {name} en {lane} respondió HTTP {status} (se esperaba {expected}): {body}"),
    "setup_extract_failed": ("setup {name} extract failed on {lane}: {detail}",
                             "falló el extractor de la preparación {name} en {lane}: {detail}"),
    "setup_prefix": ("setup: {detail}", "preparación: {detail}"),
    "no_response": ("no response within {seconds:.1f} s", "sin respuesta en {seconds:.1f} s"),
    "exited": ("target exited with code {code}: {stderr}", "el destino terminó con código {code}: {stderr}"),
    "could_not_evaluate": ("could not evaluate: {detail}", "no se pudo evaluar: {detail}"),
    "status_not_accepted": ("HTTP {status} is not an accepted status {expected}",
                            "HTTP {status} no es un estado aceptado {expected}"),
    "server_error": ("server error HTTP {status}", "error del servidor HTTP {status}"),
    "extractor_failed": ("extractor failed on the response: {detail}", "el extractor falló con la respuesta: {detail}"),
    "precondition_failed": ("precondition or pick does not hold on the target",
                            "la precondición o la elección no se cumple en el destino"),
    "reference_diverged": ("the reference cannot take this step (its model diverged)",
                           "la referencia no puede dar este paso (su modelo ha divergido)"),
    "reference_failed": ("the reference failed this step: {detail}", "la referencia falló en este paso: {detail}"),
    "invalid_step": ("step {n} ({action}): {detail}", "paso {n} ({action}): {detail}"),
    "oracle_error": ("oracle or update expression could not be evaluated",
                     "no se pudo evaluar un oráculo o una actualización del modelo"),
    "describe_passed": ("All {n} steps ran and every declared oracle held.",
                        "Se ejecutaron los {n} pasos y se cumplieron todos los oráculos declarados."),
    "describe_other": ("{outcome}: {reason}", "{outcome}: {reason}"),
    "outcome_inconclusive": ("inconclusive", "inconcluso"),
    "outcome_invalid": ("invalid", "no válido"),
    "outcome_error": ("error", "error"),
    "describe_failed": ("Step {n} ({action}) failed: {kind} {name} via {evidence} evidence.",
                        "El paso {n} ({action}) falló: {kind} {name}, con evidencia {evidence}."),
}
_LANG = contextvars.ContextVar("theseus_stateful_lang", default="en")


def check_lang(lang):
    if lang not in LANGUAGES:
        raise ValueError("lang is one of: " + ", ".join(LANGUAGES))
    return lang


@contextlib.contextmanager
def language(lang):
    """Messages produced inside this block use ``lang`` (en or es)."""
    if lang is None:  # keep the language of the enclosing block
        yield
        return
    token = _LANG.set(check_lang(lang))
    try:
        yield
    finally:
        _LANG.reset(token)


def current_language():
    return _LANG.get()


def t(key, **values):
    en, es = MESSAGES[key]
    return (es if _LANG.get() == "es" else en).format(**values)


def lane_name(label):
    return t("lane_" + label) if label in ("target", "reference") else label


FORMAT = "theseus-stateful/1"
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
RESPONSE = ("status", "body", "headers", "text")
FATAL = ("http_status", "crash", "timeout", "transport", "extraction")
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
CLIP = 2000
LIMIT_ACTIONS, LIMIT_RUNS, LIMIT_LENGTH = 40, 500, 60


def _same(a, b):
    return type(a) is type(b) and a == b


def _find(values, value):
    for i, item in enumerate(values):
        if _same(item, value):
            return i
    return -1


def _scalar(value):
    return isinstance(value, (str, int)) and not isinstance(value, bool)


def pick_ref(value):
    """A producer pick is {"from": step id, "var": extractor name}; anything else is an index."""
    return isinstance(value, dict) and set(value) == {"from", "var"} and all(isinstance(v, str) and v for v in value.values())


def check_sequence(recipe, sequence):
    """Reject malformed steps before execution: picks are indexes or well-formed producer references to an
    extractor of an earlier step (unique ids). Whether the referenced value is still live is decided at run time and
    reported as an invalid step with its reason, never swallowed."""
    ids, extractors = set(), {}
    for n, step in enumerate(sequence, 1):
        if "id" in step:
            ident = step["id"]
            if not isinstance(ident, str) or not re.match(r"^[A-Za-z0-9_.-]+$", ident) or ident in ids:
                raise RecipeError(t("step_id_shape", n=n))
        if not isinstance(step.get("picks", {}), dict) or not isinstance(step.get("params", {}), dict):
            raise RecipeError(t("pick_ref_shape", n=n, pick="picks"))
        for name, ref in step.get("picks", {}).items():
            if isinstance(ref, dict):
                if not pick_ref(ref):
                    raise RecipeError(t("pick_ref_shape", n=n, pick=name))
                if ref["var"] not in extractors.get(ref["from"], ()):
                    raise RecipeError(t("pick_producer_unknown", n=n, pick=name, producer=ref["from"], var=ref["var"]))
            elif not isinstance(ref, int) or isinstance(ref, bool):
                raise RecipeError(t("pick_ref_shape", n=n, pick=name))
        if "id" in step:
            ids.add(step["id"])
            action = next((a for a in recipe["actions"] if a["name"] == step["action"]), None)
            extractors[step["id"]] = set(action["extract"]) if action else set()


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
        raise RecipeError(t("expr_rejected", where=where, detail=exc)) from exc
    return str(source).strip()


def _templates(value, names, where):
    """Every {placeholder} in a template (text or JSON structure) must be a known name."""
    if isinstance(value, str):
        for name in PLACEHOLDER.findall(value):
            if name not in names and name not in ("sandbox", "port", "python"):
                raise RecipeError(t("unknown_placeholder", where=where, name=name))
    elif isinstance(value, dict):
        for k, v in value.items():
            _templates(k, names, where)
            _templates(v, names, where)
    elif isinstance(value, list):
        for v in value:
            _templates(v, names, where)


def _relative(path, where):
    if not isinstance(path, str) or not path.strip():
        raise RecipeError(t("needs_relative", where=where))
    pure = Path(path)
    if pure.is_absolute() or ".." in pure.parts or path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", path):
        raise RecipeError(t("outside_sandbox", where=where, path=path))
    return path.replace("\\", "/")


def _status_list(value, where):
    if value is None:
        return None
    values = value if isinstance(value, list) else [value]
    if not values or any(isinstance(v, bool) or not isinstance(v, int) or not 100 <= v <= 599 for v in values):
        raise RecipeError(t("status_list", where=where))
    return values


def _request(value, names, where):
    if not isinstance(value, dict) or set(value) - {"method", "path", "headers", "body"}:
        raise RecipeError(t("request_shape", where=where))
    method = str(value.get("method", "GET")).upper()
    path = value.get("path", "/")
    if method not in METHODS or not isinstance(path, str) or not path.startswith("/"):
        raise RecipeError(t("request_method", where=where, methods=", ".join(METHODS)))
    headers = value.get("headers") or {}
    if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()):
        raise RecipeError(t("headers_text", where=where))
    body = value.get("body")
    json.dumps(body)
    _templates([path, headers, body], names, where)
    return {"method": method, "path": path, "headers": dict(headers), "body": body}


def validate_target(value, where="target"):
    if not isinstance(value, dict):
        raise RecipeError(t("target_shape", where=where))
    if "base_url" in value:
        if set(value) - {"base_url", "reset", "request_timeout_seconds", "label"}:
            raise RecipeError(t("base_url_shape", where=where))
        url = urlsplit(str(value["base_url"]))
        if url.scheme != "http" or not url.hostname:
            raise RecipeError(t("base_url_http", where=where))
        return {"base_url": str(value["base_url"]).rstrip("/"),
                "reset": _request(value["reset"], set(), where + ".reset") if value.get("reset") else None,
                "request_timeout_seconds": float(value.get("request_timeout_seconds", 10)), "label": str(value.get("label", ""))}
    allowed = {"argv", "cwd", "env", "port_env", "ready", "ready_timeout_seconds", "request_timeout_seconds", "files", "db", "label"}
    if set(value) - allowed:
        raise RecipeError(t("unknown_fields", where=where, fields=", ".join(sorted(set(value) - allowed))))
    argv = value.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a for a in argv):
        raise RecipeError(t("argv_shape", where=where))
    env = value.get("env") or {}
    if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
        raise RecipeError(t("env_text", where=where))
    files = value.get("files") or {}
    if not isinstance(files, dict):
        raise RecipeError(t("files_shape", where=where))
    for path, content in files.items():
        _relative(path, where + " file")
        if not isinstance(content, str) and not (isinstance(content, dict) and set(content) == {"base64"}):
            raise RecipeError(t("file_content", where=where))
    db = value.get("db")
    if db is not None:
        if not isinstance(db, dict) or set(db) - {"path", "seed_sql"}:
            raise RecipeError(t("db_shape", where=where))
        db = {"path": _relative(db.get("path", "app.db"), where + ".db"), "seed_sql": str(db.get("seed_sql", ""))}
    ready = value.get("ready")
    if isinstance(ready, str):
        ready = {"method": "GET", "path": ready}
    if ready is not None:
        ready = _request(ready, set(), where + ".ready")
    timeout = float(value.get("ready_timeout_seconds", 20))
    if not 0 < timeout <= 300:
        raise RecipeError(t("ready_timeout", where=where))
    return {"argv": list(argv), "cwd": value.get("cwd"), "env": dict(env), "port_env": str(value.get("port_env", "PORT")),
            "ready": ready, "ready_timeout_seconds": timeout,
            "request_timeout_seconds": float(value.get("request_timeout_seconds", 10)),
            "files": dict(files), "db": db, "label": str(value.get("label", ""))}


def _named_exprs(values, names, where, default_prefix):
    out = []
    for j, item in enumerate(values or []):
        entry = item if isinstance(item, dict) else {"expr": item}
        if not isinstance(entry, dict) or set(entry) - {"name", "expr", "explain"}:
            raise RecipeError(t("entries_shape", where=where))
        name = str(entry.get("name") or "%s-%d" % (default_prefix, j + 1))
        out.append({"name": name, "expr": _expr(entry.get("expr", ""), names, "%s %s" % (where, name)),
                    "explain": str(entry.get("explain", ""))})
    return out


def validate_recipe(value, strategy_validate=None):
    """Normalised recipe or RecipeError. ``strategy_validate`` validates parameter strategies (Theseus side)."""
    allowed = {"name", "target", "reference", "model", "setup", "actions", "invariants", "queries", "watch",
               "server_errors_fail", "runs", "max_length", "seed", "description"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise RecipeError(t("recipe_shape", fields=", ".join(sorted(allowed))))
    recipe = {"format": FORMAT, "name": str(value.get("name") or "stateful"), "description": str(value.get("description", ""))}
    recipe["target"] = validate_target(value.get("target"), "target")
    recipe["reference"] = validate_target(value["reference"], "reference") if value.get("reference") else None
    model = value.get("model") or {}
    if not isinstance(model, dict) or any(not isinstance(k, str) or not k.isidentifier() for k in model):
        raise RecipeError(t("model_shape"))
    json.dumps(model)
    reserved = set(RESPONSE) | {"sql", "step", "action", "ref_status", "ref_body", "ref_headers", "ref_text"}
    if set(model) & reserved:
        raise RecipeError(t("model_reserved", names=", ".join(sorted(set(model) & reserved))))
    recipe["model"] = json.loads(json.dumps(model))
    mvars = tuple(model)
    watch = value.get("watch") or {}
    if not isinstance(watch, dict) or set(watch) - {"sqlite", "tables", "files"}:
        raise RecipeError(t("watch_shape"))
    sqlite_path = watch.get("sqlite")
    if sqlite_path is not None and not isinstance(sqlite_path, str):
        raise RecipeError(t("watch_sqlite"))
    if sqlite_path and "argv" in recipe["target"]:
        sqlite_path = _relative(sqlite_path, "watch.sqlite")
    tables = watch.get("tables")
    if tables is not None and (not isinstance(tables, list) or any(not isinstance(t, str) for t in tables)):
        raise RecipeError(t("watch_tables"))
    globs = watch.get("files") or []
    if not isinstance(globs, list) or any(not isinstance(g, str) for g in globs):
        raise RecipeError(t("watch_files"))
    if globs and "argv" not in recipe["target"]:
        raise RecipeError(t("watch_files_target"))
    recipe["watch"] = {"sqlite": sqlite_path, "tables": tables, "files": list(globs)}
    queries = value.get("queries") or {}
    if not isinstance(queries, dict) or any(not str(k).isidentifier() or not isinstance(q, str) for k, q in queries.items()):
        raise RecipeError(t("queries_shape"))
    if queries and not sqlite_path:
        raise RecipeError(t("queries_need"))
    for name, sql in queries.items():
        if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.I) or ";" in sql.strip().rstrip(";"):
            raise RecipeError(t("query_select", name=name))
    recipe["queries"] = dict(queries)
    sql_names = ("sql",) if queries else ()
    recipe["setup"] = []
    for i, item in enumerate(value.get("setup") or []):
        where = t("where_setup", n=i + 1)
        if not isinstance(item, dict) or set(item) - {"name", "request", "expect_status", "extract"}:
            raise RecipeError(t("setup_shape", where=where))
        extract = item.get("extract") or {}
        if not isinstance(extract, dict) or set(extract) - set(mvars):
            raise RecipeError(t("setup_extract_shape", where=where))
        names = mvars + RESPONSE
        recipe["setup"].append({"name": str(item.get("name") or "setup-%d" % (i + 1)),
                                "request": _request(item.get("request"), set(mvars), where + ".request"),
                                "expect_status": _status_list(item.get("expect_status"), where + ".expect_status"),
                                "extract": {k: _expr(v, names, "%s extract %s" % (where, k)) for k, v in extract.items()}})
    actions = value.get("actions") or []
    if not isinstance(actions, list) or not actions or len(actions) > LIMIT_ACTIONS:
        raise RecipeError(t("actions_shape", limit=LIMIT_ACTIONS))
    recipe["actions"], seen = [], set()
    for i, act in enumerate(actions):
        keys = {"name", "pre", "params", "pick", "request", "expect_status", "extract", "update", "post", "agree", "explain"}
        if not isinstance(act, dict) or set(act) - keys:
            raise RecipeError(t("action_shape", n=i + 1, fields=", ".join(sorted(keys))))
        name = str(act.get("name") or "")
        if not name or name in seen or not re.match(r"^[A-Za-z0-9_.-]+$", name):
            raise RecipeError(t("action_name"))
        seen.add(name)
        where = t("where_action", name=name)
        params = act.get("params") or {}
        if not isinstance(params, dict) or any(not str(k).isidentifier() or k in mvars for k in params):
            raise RecipeError(t("params_shape", where=where))
        params = {k: (strategy_validate(v, "%s.%s" % (where, k)) if strategy_validate else v) for k, v in params.items()}
        picks = act.get("pick") or {}
        if not isinstance(picks, dict) or any(not str(k).isidentifier() or k in mvars or k in params or v not in mvars
                                              for k, v in picks.items()):
            raise RecipeError(t("pick_shape", where=where))
        scope = mvars + tuple(params) + tuple(picks) + tuple(k + "_index" for k in picks)
        pre = _expr(act["pre"], scope, where + " pre") if act.get("pre") else None
        request = _request(act.get("request"), set(scope), where + ".request")
        extract = act.get("extract") or {}
        if not isinstance(extract, dict) or any(not str(k).isidentifier() or k in scope for k in extract):
            raise RecipeError(t("extract_shape", where=where))
        extracted = {k: _expr(v, scope + RESPONSE, "%s extract %s" % (where, k)) for k, v in extract.items()}
        local = scope + RESPONSE + tuple(extract)
        update = act.get("update") or {}
        if not isinstance(update, dict) or set(update) - set(mvars):
            raise RecipeError(t("update_shape", where=where))
        updates = {k: _expr(v, local, "%s update %s" % (where, k)) for k, v in update.items()}
        post_names = local + tuple("old_" + m for m in mvars) + sql_names
        post = _named_exprs(act.get("post"), post_names, where + " post", "post")
        agree = []
        if act.get("agree"):
            if not recipe["reference"]:
                raise RecipeError(t("agree_reference", where=where))
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
            raise RecipeError(t("integer_range", label=label, limit=limit))
        recipe[label] = number
    seed = value.get("seed", 1)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise RecipeError(t("seed_integer"))
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
        self.produced = {}  # step id -> {extractor: value this lane's own response gave}
        self.born = set()   # (step id, extractor) whose value entered a model list in that same step

    def _sub(self, text):
        text = text.replace("{python}", sys.executable)
        if self.sandbox is not None:
            text = text.replace("{sandbox}", str(self.sandbox))
        if self.port is not None:
            text = text.replace("{port}", str(self.port))
        return text

    def start(self):
        spec = self.target
        if "base_url" in spec:
            url = urlsplit(spec["base_url"])
            self.host, self.port, self.prefix = url.hostname, url.port or 80, url.path.rstrip("/")
            if spec["reset"]:
                try:
                    got = self.request(spec["reset"]["method"], spec["reset"]["path"], spec["reset"]["headers"], spec["reset"]["body"])
                except OSError as exc:
                    raise SetupFailure(t("reset_failed", detail=exc)) from exc
                if got["status"] >= 400:
                    raise SetupFailure(t("reset_status", status=got["status"]))
            return
        self.prefix = ""
        self.root = Path(tempfile.mkdtemp(prefix="theseus-stateful-"))
        self.sandbox = self.root / "sandbox"
        self.sandbox.mkdir()
        for rel, content in spec["files"].items():
            path = self.sandbox / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(content["base64"]) if isinstance(content, dict) else content.encode("utf-8"))
        if spec["db"]:
            path = self.sandbox / spec["db"]["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path)
            try:
                if spec["db"]["seed_sql"].strip():
                    connection.executescript(spec["db"]["seed_sql"])
                connection.commit()
            finally:
                connection.close()
        self.port = _free_port()
        argv = [self._sub(a) for a in spec["argv"]]
        cwd = self._sub(spec["cwd"]) if spec.get("cwd") else str(self.sandbox)
        if not Path(cwd).is_absolute():
            cwd = str(self.sandbox / cwd)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "THESEUS_SANDBOX": str(self.sandbox),
               **{k: self._sub(v) for k, v in spec["env"].items()}, spec["port_env"]: str(self.port)}
        self.err_path = self.root / "server.err"
        try:
            with open(self.err_path, "wb") as err:
                self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                                stdout=subprocess.DEVNULL, stderr=err)
        except OSError as exc:
            raise SetupFailure(t("start_failed", detail=exc)) from exc
        deadline = time.monotonic() + spec["ready_timeout_seconds"]
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise SetupFailure(t("exited_before_ready", code=self.process.returncode, stderr=self.stderr_tail()))
            try:
                if spec["ready"]:
                    got = self.request(spec["ready"]["method"], spec["ready"]["path"], {}, None, timeout=1)
                    if got["status"] < 500:
                        return
                else:
                    socket.create_connection((self.host, self.port), timeout=.3).close()
                    return
            except OSError:
                pass
            time.sleep(.05)
        raise SetupFailure(t("not_ready", seconds=spec["ready_timeout_seconds"]))

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
                    raise SetupFailure(t("setup_failed", name=item["name"], lane=lane_name(lane.label), detail=exc)) from exc
                if item["expect_status"] and got["status"] not in item["expect_status"]:
                    raise SetupFailure(t("setup_status", name=item["name"], lane=lane_name(lane.label), status=got["status"],
                                         expected=item["expect_status"], body=clip(got["text"])[:300]))
                try:
                    for var, source in item["extract"].items():
                        lane.model[var] = _evaluate(source, {**lane.model, **got})
                except ExpressionError as exc:
                    raise SetupFailure(t("setup_extract_failed", name=item["name"], lane=lane_name(lane.label), detail=exc)) from exc
        self.state = [lane.snapshot() for lane in self.lanes]

    # ---- symbolic steps
    def _bind(self, lane, step):
        """(environment, None) for a step on one lane (model + params + picks), or (None, reason) if the precondition
        or a pick does not hold."""
        action = self.actions.get(step["action"])
        if action is None:
            return None, t("precondition_failed")
        env = {**lane.model, **step.get("params", {})}
        for name, var in action["pick"].items():
            ref = step.get("picks", {}).get(name)
            values = lane.model.get(var)
            if not isinstance(values, list):
                return None, t("precondition_failed")
            if isinstance(ref, dict):
                if not pick_ref(ref):
                    return None, t("pick_ref_shape", n=step.get("id", "?"), pick=name)
                got = lane.produced.get(ref["from"])
                if got is None or ref["var"] not in got:
                    return None, t("pick_unavailable", pick=name, producer=ref["from"], var=ref["var"])
                index = _find(values, got[ref["var"]])
                if index < 0:
                    return None, t("pick_gone", pick=name, producer=ref["from"], var=ref["var"], pool=var)
            else:
                index = ref
                if not isinstance(index, int) or not 0 <= index < len(values):
                    return None, t("precondition_failed")
            env[name], env[name + "_index"] = values[index], index
        if action["pre"]:
            try:
                if not _evaluate(action["pre"], env):
                    return None, t("precondition_failed")
            except ExpressionError:
                return None, t("precondition_failed")
        return env, None

    def bind(self, lane, step):
        return self._bind(lane, step)[0]

    def provenance(self, lane, var, index):
        """The producer reference of the element at ``index`` of model list ``var``: the latest step whose extracted
        value entered a model list in its own step and equals the element (and whose first occurrence is ``index``,
        so resolving the reference gives back the same position). None when the element has no such origin."""
        values = lane.model.get(var)
        if not isinstance(values, list) or not 0 <= index < len(values) or not _scalar(values[index]):
            return None
        if _find(values, values[index]) != index:
            return None
        for sid in reversed(list(lane.produced)):
            for evar, got in lane.produced[sid].items():
                if (sid, evar) in lane.born and _same(got, values[index]):
                    return {"from": sid, "var": evar}
        return None

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
                                    "detail": t("no_response", seconds=lane.target["request_timeout_seconds"])}
        except (OSError, http.client.HTTPException) as exc:
            time.sleep(.1)
            if not lane.alive():
                return rendered, None, {"kind": "crash", "name": "process exited", "evidence": "process",
                                        "detail": t("exited", code=lane.process.returncode, stderr=lane.stderr_tail())}
            return rendered, None, {"kind": "transport", "name": type(exc).__name__, "evidence": "process", "detail": str(exc)}

    def _check(self, sources, env, kind):
        violations, errors = [], []
        for item in sources:
            try:
                ok = bool(_evaluate(item["expr"], env))
            except ExpressionError as exc:
                errors.append({"kind": kind, "name": item["name"], "expr": item["expr"], "detail": t("could_not_evaluate", detail=exc)})
                continue
            if not ok:
                violations.append({"kind": kind, "name": item["name"], "expr": item["expr"], "evidence": evidence_of(item["expr"]),
                                   "explain": item.get("explain", ""), "observed": explain(item["expr"], env)})
        return violations, errors

    def execute(self, step, index):
        """Execute one symbolic step on every lane. Returns the step record; record['outcome'] is
        'ok', 'failed', 'invalid' or 'error'."""
        action = self.actions[step["action"]]
        record = {"index": index, **({"id": step["id"]} if step.get("id") else {}), "action": action["name"], "params": step.get("params", {}), "picks": step.get("picks", {}),
                  "lanes": {}, "violations": [], "errors": [], "outcome": "ok"}
        bound = [self._bind(lane, step) for lane in self.lanes]
        envs = [b[0] for b in bound]
        if envs[0] is None:
            record["outcome"] = "invalid"
            record["detail"] = bound[0][1]
            return record
        if len(envs) > 1 and envs[1] is None:
            record["outcome"] = "inconclusive"
            record["detail"] = t("reference_diverged")
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
                         "detail": t("status_not_accepted", status=got["status"], expected=action["expect_status"]),
                         "observed": {"status": got["status"], "body": clip(got["text"])}}
            if fatal is None and not action["expect_status"] and self.recipe["server_errors_fail"] and got["status"] >= 500:
                fatal = {"kind": "http_status", "name": "status %s" % got["status"], "evidence": "http",
                         "detail": t("server_error", status=got["status"]), "observed": {"status": got["status"], "body": clip(got["text"])}}
            extracted = {}
            if fatal is None:
                local = {**env, **{k: got[k] for k in RESPONSE}}
                for var, source in action["extract"].items():
                    try:
                        extracted[var] = _evaluate(source, local)
                    except ExpressionError as exc:
                        fatal = {"kind": "extraction", "name": var, "expr": source, "evidence": "http",
                                 "detail": t("extractor_failed", detail=exc), "observed": {"status": got["status"], "body": clip(got["body"])}}
                        break
                if step.get("id"):
                    lane.produced[step["id"]] = dict(extracted)
                if action["pick"]:
                    lane_record["bound"] = {n: {"index": env[n + "_index"], "value": clip(env[n])} for n in action["pick"]}
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
                    record["detail"] = t("reference_failed", detail=fatal["detail"])
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
            if step.get("id"):
                for evar, value in extracted.items():
                    if _scalar(value) and any(isinstance(new.get(v), list) and _find(new[v], value) >= 0
                                              and _find(old.get(v) if isinstance(old.get(v), list) else [], value) < 0 for v in new):
                        lane.born.add((step["id"], evar))
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
            return {"outcome": "inconclusive", "reason": t("setup_prefix", detail=exc), "trace": [], "ids": [], "steps_run": 0}
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
                result["reason"] = t("invalid_step", n=i + 1, action=record["action"], detail=record.get("detail", ""))
            else:
                result["reason"] = t("oracle_error")
                result["errors"] = record["errors"]
            return result
        return {"outcome": "passed", "trace": session.trace, "ids": session.ids, "steps_run": len(sequence)}


def describe(result):
    """One human-readable paragraph for a run_sequence result (used in reports and exported tests)."""
    if result["outcome"] == "passed":
        return t("describe_passed", n=result["steps_run"])
    if result["outcome"] != "failed":
        return t("describe_other", outcome=t("outcome_" + result["outcome"]), reason=result.get("reason", ""))
    lines = []
    f = result["failure"]
    lines.append(t("describe_failed", n=f["index"] + 1, action=f["action"], kind=f["kind"], name=f["name"], evidence=f.get("evidence", "?")))
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
