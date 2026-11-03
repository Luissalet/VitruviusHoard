"""Instrument runtime: typed spec, safe formulas, explainer and a tiny HTTP server.

Python standard library only. Vitruvius imports this module to compute and the very same file is copied into every
exported instrument as ``server.py``, so the host, the exported bundle and the explainer share one computation.
"""
from __future__ import annotations

import argparse
import ast
import html as _html
import json
import math
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

KINDS = ("calculator", "viewer", "comparator", "editor")
INPUT_TYPES = ("number", "integer", "text", "choice", "boolean")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class InputError(ValueError):
    """Invalid input values; ``errors`` lists {field, message}."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(f"{e['field']}: {e['message']}" for e in errors))


def _clamp(x, low, high):
    return max(low, min(high, x))


def _power(base, exponent):
    if abs(exponent) > 64:
        raise ValueError("pow exponent must be between -64 and 64")
    return math.pow(base, exponent)


def _round_half_up(x, digits=0):
    factor = 10 ** int(digits)
    return math.floor(abs(x) * factor + 0.5) / factor * (1 if x >= 0 else -1)


FUNCTIONS = {"min": min, "max": max, "abs": abs, "round": _round_half_up, "floor": math.floor, "ceil": math.ceil,
             "sqrt": math.sqrt, "pow": _power, "clamp": _clamp, "log": math.log, "exp": math.exp}
_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b, ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b}
_CMP = {ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
        ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b}


def compile_formula(text, names, functions):
    """Validate a formula against the allowed names and return a callable ``f(env, funcs)``."""
    if not isinstance(text, str) or not text.strip() or len(text) > 400:
        raise ValueError("A formula must be a non-empty text of at most 400 characters")
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as error:
        raise ValueError(f"Formula '{text}' is not valid: {error.msg}") from error
    allowed = set(names)

    def check(node):
        if isinstance(node, ast.Expression):
            return check(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or isinstance(node.value, (int, float, str)):
                return
            raise ValueError(f"Formula '{text}' uses an unsupported constant")
        if isinstance(node, ast.Name):
            if node.id not in allowed:
                raise ValueError(f"Formula '{text}' uses unknown name '{node.id}'")
            return
        if isinstance(node, ast.BinOp):
            if type(node.op) not in _BIN:
                raise ValueError(f"Formula '{text}': operator not allowed; use pow(x, n) instead of **")
            return [check(node.left), check(node.right)]
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
                raise ValueError(f"Formula '{text}': operator not allowed")
            return check(node.operand)
        if isinstance(node, ast.BoolOp):
            return [check(v) for v in node.values]
        if isinstance(node, ast.Compare):
            if any(type(op) not in _CMP for op in node.ops):
                raise ValueError(f"Formula '{text}': comparison not allowed")
            return [check(node.left), *(check(c) for c in node.comparators)]
        if isinstance(node, ast.IfExp):
            return [check(node.test), check(node.body), check(node.orelse)]
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in functions or node.keywords:
                raise ValueError(f"Formula '{text}': only calls to {', '.join(sorted(functions))} with positional arguments are allowed")
            return [check(a) for a in node.args]
        raise ValueError(f"Formula '{text}' uses unsupported syntax ({type(node).__name__})")

    check(tree)

    def evaluate(node, env, funcs):
        if isinstance(node, ast.Expression):
            return evaluate(node.body, env, funcs)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return env[node.id]
        if isinstance(node, ast.BinOp):
            return _BIN[type(node.op)](evaluate(node.left, env, funcs), evaluate(node.right, env, funcs))
        if isinstance(node, ast.UnaryOp):
            value = evaluate(node.operand, env, funcs)
            return (not value) if isinstance(node.op, ast.Not) else (-value if isinstance(node.op, ast.USub) else +value)
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                result = True
                for v in node.values:
                    result = evaluate(v, env, funcs)
                    if not result:
                        return result
                return result
            result = False
            for v in node.values:
                result = evaluate(v, env, funcs)
                if result:
                    return result
            return result
        if isinstance(node, ast.Compare):
            left = evaluate(node.left, env, funcs)
            for op, comparator in zip(node.ops, node.comparators):
                right = evaluate(comparator, env, funcs)
                if not _CMP[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return evaluate(node.body if evaluate(node.test, env, funcs) else node.orelse, env, funcs)
        if isinstance(node, ast.Call):
            return funcs[node.func.id](*(evaluate(a, env, funcs) for a in node.args))
        raise ValueError("unsupported syntax")

    return lambda env, funcs: evaluate(tree, env, funcs)


# ---------------- spec ----------------

def _ident(value, what):
    if not isinstance(value, str) or not _IDENT.match(value):
        raise ValueError(f"{what} needs an identifier name (letters, digits, underscore): {value!r}")
    return value


def _num(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number")
    return value


def validate_instrument_spec(spec):
    """Return a normalised copy of the spec or raise ValueError listing every problem found first."""
    if not isinstance(spec, dict):
        raise ValueError("Instrument spec must be an object")
    spec = json.loads(json.dumps(spec))
    name = spec.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError("Instrument needs a name of at most 120 characters")
    kind = spec.setdefault("kind", "calculator")
    if kind not in KINDS:
        raise ValueError("kind must be one of " + ", ".join(KINDS))
    spec.setdefault("description", "")
    if not isinstance(spec["description"], str):
        raise ValueError("description must be text")
    inputs = spec.get("inputs")
    if not isinstance(inputs, list) or not inputs or len(inputs) > 40:
        raise ValueError("Instrument needs 1 to 40 inputs")
    taken = set()

    def claim(identifier, what):
        if identifier in taken or identifier in FUNCTIONS:
            raise ValueError(f"{what} '{identifier}' clashes with another name or a built-in function")
        taken.add(identifier)

    for item in inputs:
        if not isinstance(item, dict):
            raise ValueError("Each input must be an object")
        _ident(item.get("name"), "Input")
        claim(item["name"], "Input")
        item.setdefault("label", item["name"])
        kind_of = item.get("type")
        if kind_of not in INPUT_TYPES:
            raise ValueError(f"Input '{item['name']}' type must be one of " + ", ".join(INPUT_TYPES))
        item.setdefault("required", True)
        if kind_of in ("number", "integer"):
            for key in ("min", "max", "step", "default", "to_base"):
                if key in item:
                    _num(item[key], f"Input '{item['name']}' {key}")
            if "min" in item and "max" in item and item["min"] > item["max"]:
                raise ValueError(f"Input '{item['name']}' has min above max")
            item.setdefault("to_base", 1)
            if item["to_base"] == 0:
                raise ValueError(f"Input '{item['name']}' to_base cannot be 0")
        elif kind_of == "choice":
            if not isinstance(item.get("choices"), list) or not item["choices"] or any(not isinstance(c, str) for c in item["choices"]):
                raise ValueError(f"Choice input '{item['name']}' needs a list of text choices")
        if "default" in item:
            try:
                _check_value(item, item["default"])
            except InputError as error:
                raise ValueError(f"Default of '{item['name']}' is invalid: {error}") from error
    operations = spec.setdefault("operations", [])
    functions = dict(FUNCTIONS)
    if not isinstance(operations, list):
        raise ValueError("operations must be a list")
    for op in operations:
        _ident(op.get("name") if isinstance(op, dict) else None, "Operation")
        params = op.get("params", [])
        if not isinstance(params, list):
            raise ValueError(f"Operation '{op['name']}' params must be a list")
        for p in params:
            _ident(p, "Operation parameter")
        if op["name"] in functions or op["name"] in taken:
            raise ValueError(f"Operation '{op['name']}' clashes with another name")
        compile_formula(op.get("formula"), params, functions)
        functions[op["name"]] = None  # reserved so later operations may call earlier ones
    steps = spec.setdefault("steps", [])
    outputs = spec.get("outputs")
    if not isinstance(steps, list):
        raise ValueError("steps must be a list")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("Instrument needs at least one output")
    visible = set(taken)
    for group, what in ((steps, "Step"), (outputs, "Output")):
        for item in group:
            if not isinstance(item, dict):
                raise ValueError(f"Each {what.lower()} must be an object")
            _ident(item.get("name"), what)
            claim(item["name"], what)
            item.setdefault("label", item["name"])
            if what == "Output":
                item.setdefault("decimals", 2)
                if not isinstance(item["decimals"], int) or isinstance(item["decimals"], bool) or not 0 <= item["decimals"] <= 10:
                    raise ValueError(f"Output '{item['name']}' decimals must be an integer from 0 to 10")
            if "operation" in item:
                op = next((o for o in operations if o["name"] == item["operation"]), None)
                if op is None:
                    raise ValueError(f"{what} '{item['name']}' refers to unknown operation '{item['operation']}'")
                args = item.get("args", [])
                if not isinstance(args, list) or len(args) != len(op.get("params", [])):
                    raise ValueError(f"{what} '{item['name']}' must pass {len(op.get('params', []))} args to '{op['name']}'")
                item["formula"] = f"{op['name']}({', '.join(str(a) for a in args)})"
            if "formula" not in item:
                raise ValueError(f"{what} '{item['name']}' needs a formula or an operation")
            compile_formula(item["formula"], visible, functions)
            visible.add(item["name"])
    invariants = spec.setdefault("invariants", [])
    if not isinstance(invariants, list):
        raise ValueError("invariants must be a list")
    for inv in invariants:
        if not isinstance(inv, dict) or not isinstance(inv.get("name"), str):
            raise ValueError("Each invariant needs a name and an expression")
        compile_formula(inv.get("expression"), visible, functions)
    for key in ("examples",):
        if not isinstance(spec.setdefault(key, []), list):
            raise ValueError(f"{key} must be a list")
    output_names = {o["name"] for o in outputs}
    for index, example in enumerate(spec["examples"]):
        if not isinstance(example, dict) or not isinstance(example.get("inputs"), dict) or not isinstance(example.get("expected"), dict) or not example["expected"]:
            raise ValueError(f"Example {index + 1} needs inputs and expected outputs")
        example.setdefault("name", f"example {index + 1}")
        if set(example["expected"]) - output_names:
            raise ValueError(f"Example '{example['name']}' expects unknown outputs: " + ", ".join(sorted(set(example["expected"]) - output_names)))
        tolerance = example.setdefault("tolerance", 1e-9)
        _num(tolerance, "Example tolerance")
    rows = spec.setdefault("rows", [])
    if not isinstance(rows, list) or len(rows) > 500 or any(not isinstance(r, dict) for r in rows):
        raise ValueError("rows must be a list of at most 500 input objects")
    if kind == "viewer" and not rows:
        raise ValueError("A viewer needs rows of input values to display")
    views = spec.setdefault("views", ["form", "explainer"])
    if not isinstance(views, list) or any(v not in ("form", "table", "explainer") for v in views):
        raise ValueError("views may contain form, table and explainer")
    allowed = {"name", "kind", "description", "inputs", "operations", "steps", "outputs", "invariants", "examples", "rows", "views", "title", "notes"}
    if set(spec) - allowed:
        raise ValueError("Unknown spec keys: " + ", ".join(sorted(set(spec) - allowed)))
    for row in rows:
        compute(spec, row)  # viewer/editor rows must be valid as authored
    return spec


# ---------------- computing ----------------

def _check_value(field, value):
    kind = field["type"]
    name = field["name"]
    if kind in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise InputError([{"field": name, "message": "must be a finite number"}])
        if kind == "integer" and value != int(value):
            raise InputError([{"field": name, "message": "must be a whole number"}])
        if "min" in field and value < field["min"]:
            raise InputError([{"field": name, "message": f"must be at least {field['min']}"}])
        if "max" in field and value > field["max"]:
            raise InputError([{"field": name, "message": f"must be at most {field['max']}"}])
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise InputError([{"field": name, "message": "must be true or false"}])
    else:
        if not isinstance(value, str):
            raise InputError([{"field": name, "message": "must be text"}])
        if kind == "choice" and value not in field["choices"]:
            raise InputError([{"field": name, "message": "must be one of " + ", ".join(field["choices"])}])
        if len(value) > 500:
            raise InputError([{"field": name, "message": "is too long"}])


def validate_inputs(spec, values):
    if not isinstance(values, dict):
        raise InputError([{"field": "*", "message": "inputs must be an object"}])
    fields = {f["name"]: f for f in spec["inputs"]}
    errors = [{"field": name, "message": "is not an input of this instrument"} for name in values if name not in fields]
    result = {}
    for name, field in fields.items():
        if name not in values or values[name] is None:
            if "default" in field:
                result[name] = field["default"]
            elif field.get("required", True):
                errors.append({"field": name, "message": "is required"})
            continue
        try:
            _check_value(field, values[name])
            result[name] = values[name]
        except InputError as error:
            errors.extend(error.errors)
    if errors:
        raise InputError(errors)
    return result


def _functions(spec):
    functions = dict(FUNCTIONS)
    for op in spec.get("operations", []):
        params = op.get("params", [])
        visible = dict(functions)
        code = compile_formula(op["formula"], params, visible)

        def make(code, params, visible):
            def call(*args):
                if len(args) != len(params):
                    raise ValueError("wrong number of arguments")
                return code(dict(zip(params, args)), visible)
            return call
        functions[op["name"]] = make(code, params, visible)
    return functions


def _number(value):
    if isinstance(value, float) and value == int(value) and abs(value) < 1e15:
        return int(value)
    return value


def compute(spec, values):
    """Compute steps, outputs and invariants for validated spec and raw input values."""
    inputs = validate_inputs(spec, values)
    functions = _functions(spec)
    env = {}
    for field in spec["inputs"]:
        if field["name"] in inputs:
            value = inputs[field["name"]]
            if field["type"] in ("number", "integer"):
                value = value * field.get("to_base", 1)
            env[field["name"]] = value
    steps, outputs = [], []
    try:
        for group, bucket in ((spec.get("steps", []), steps), (spec["outputs"], outputs)):
            for item in group:
                raw = compile_formula(item["formula"], set(env) | set(functions), functions)(env, functions)
                if isinstance(raw, float) and not math.isfinite(raw):
                    raise ValueError("result is not a finite number")
                shown = round(raw, item.get("decimals", 4)) if isinstance(raw, float) else raw
                env[item["name"]] = raw
                bucket.append({"name": item["name"], "label": item.get("label", item["name"]), "unit": item.get("unit", ""),
                               "formula": item["formula"], "value": _number(shown)})
    except ZeroDivisionError as error:
        raise ValueError(f"Division by zero while computing '{item['name']}'") from error
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"Cannot compute '{item['name']}': {error}") from error
    # invariants see the rounded values a reader sees
    seen = dict(env)
    for row in steps + outputs:
        seen[row["name"]] = row["value"]
    invariants = [{"name": inv["name"], "expression": inv["expression"],
                   "holds": bool(compile_formula(inv["expression"], set(seen) | set(functions), functions)(seen, functions))}
                  for inv in spec.get("invariants", [])]
    return {"inputs": inputs, "steps": steps, "outputs": outputs, "invariants": invariants}


def match_expected(example, got):
    """Mismatches between an example's expected outputs and the computed ``got`` {output: value}."""
    bad = []
    for name, expected in example["expected"].items():
        value = got.get(name)
        numeric = (isinstance(expected, (int, float)) and not isinstance(expected, bool)
                   and isinstance(value, (int, float)) and not isinstance(value, bool))
        if not (numeric and abs(value - expected) <= example.get("tolerance", 1e-9)) and value != expected:
            bad.append({"output": name, "expected": expected, "got": value})
    return bad


def check_examples(spec):
    """Recompute every example of the spec; return one report per example."""
    reports = []
    for example in spec.get("examples", []):
        try:
            result = compute(spec, example["inputs"])
        except ValueError as error:
            reports.append({"name": example["name"], "ok": False, "error": str(error), "mismatches": []})
            continue
        bad = match_expected(example, {o["name"]: o["value"] for o in result["outputs"]})
        reports.append({"name": example["name"], "ok": not bad, "mismatches": bad})
    return reports


# ---------------- explainer ----------------

def _fmt(value, decimals=None):
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float) and decimals is not None:
        return f"{value:.{decimals}f}"
    return str(value)


def explain(spec, values):
    """The explainer's data: every input, intermediate step and output with the formula that produced it."""
    result = compute(spec, values)
    shown = []
    fields = {f["name"]: f for f in spec["inputs"]}
    for name, value in result["inputs"].items():
        shown.append({"name": name, "kind": "input", "label": fields[name]["label"], "unit": fields[name].get("unit", ""), "value": value, "formula": ""})
    decimals = {o["name"]: o.get("decimals", 2) for o in spec["outputs"]}
    for row in result["steps"]:
        shown.append({**row, "kind": "step"})
    for row in result["outputs"]:
        shown.append({**row, "kind": "output"})
    for row in shown:
        row["text"] = _fmt(row["value"], decimals.get(row["name"]))
    return {**result, "shown": shown}


def explain_html(spec, values, *, note=""):
    """Server-rendered explainer; every number carries data-name/data-kind/data-value so it can be checked."""
    esc = _html.escape
    try:
        data = explain(spec, values)
        error = ""
    except InputError as problem:
        data, error = None, "; ".join(f"{e['field']} {e['message']}" for e in problem.errors)
    except ValueError as problem:
        data, error = None, str(problem)
    fields = []
    current = (data or {}).get("inputs", {}) if data else {}
    for f in spec["inputs"]:
        value = current.get(f["name"], values.get(f["name"], f.get("default", "")))
        label = esc(f["label"]) + (f" ({esc(f['unit'])})" if f.get("unit") else "")
        ident = "in-" + f["name"]
        if f["type"] in ("number", "integer"):
            slider = ""
            if "min" in f and "max" in f:
                slider = f'<input type="range" aria-label="{esc(f["label"])} slider" min="{f["min"]}" max="{f["max"]}" step="{f.get("step", 1 if f["type"] == "integer" else "any")}" value="{esc(str(value))}" data-follow="{ident}">'
            control = f'<input id="{ident}" name="{esc(f["name"])}" type="number" inputmode="decimal" step="{f.get("step", 1 if f["type"] == "integer" else "any")}" value="{esc(str(value))}"' + (f' min="{f["min"]}"' if "min" in f else "") + (f' max="{f["max"]}"' if "max" in f else "") + f'>{slider}'
        elif f["type"] == "choice":
            control = f'<select id="{ident}" name="{esc(f["name"])}">' + "".join(f'<option{" selected" if c == value else ""}>{esc(c)}</option>' for c in f["choices"]) + "</select>"
        elif f["type"] == "boolean":
            control = f'<input id="{ident}" name="{esc(f["name"])}" type="checkbox" value="true"{" checked" if value is True else ""}>'
        else:
            control = f'<input id="{ident}" name="{esc(f["name"])}" type="text" value="{esc(str(value))}">'
        fields.append(f'<div class="field"><label for="{ident}">{label}</label>{control}</div>')
    body = ""
    if data:
        rows = []
        for row in data["shown"]:
            unit = f" {esc(row['unit'])}" if row.get("unit") else ""
            formula = f"<code>{esc(row['formula'])}</code>" if row.get("formula") else "<span>your input</span>"
            rows.append(f'<tr data-kind="{row["kind"]}"><th scope="row">{esc(row["label"])}</th><td>{formula}</td>'
                        f'<td><output data-name="{esc(row["name"])}" data-kind="{row["kind"]}" data-value="{esc(json.dumps(row["value"]))}">{esc(row["text"])}</output>{unit}</td></tr>')
        invariants = "".join(f'<li data-invariant="{esc(i["name"])}" data-holds="{str(i["holds"]).lower()}">{"Holds" if i["holds"] else "Violated"}: {esc(i["name"])} <code>{esc(i["expression"])}</code></li>'
                             for i in data["invariants"])
        body = ('<table><caption>How each number is obtained</caption><thead><tr><th scope="col">Quantity</th><th scope="col">Computed as</th><th scope="col">Value</th></tr></thead><tbody>'
                + "".join(rows) + "</tbody></table>" + (f'<h2>Invariants</h2><ul class="invariants">{invariants}</ul>' if invariants else ""))
    elif error:
        body = f'<p class="problem" role="alert">{esc(error)}</p>'
    title = esc(spec["name"])
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{title} explained</title><style>{_CSS}</style></head><body><header><a href="/">{title}</a></header><main>'
            f'<h1>{title}: worked example</h1><p>Change a value to see every intermediate state. These numbers come from the same computation as the instrument.</p>'
            f'{("<p>" + esc(note) + "</p>") if note else ""}<form method="get" action="/explain" class="grid">{"".join(fields)}<button type="submit">Recalculate</button></form>'
            f'{body}</main><script>document.querySelectorAll("[data-follow]").forEach(function(r){{var t=document.getElementById(r.dataset.follow);r.addEventListener("input",function(){{t.value=r.value;t.form.submit()}})}})</script></body></html>')


_CSS = ("*{box-sizing:border-box}body{margin:0;background:#f6f5f0;color:#1f2a2c;font:16px/1.6 system-ui,sans-serif}header,main{max-width:960px;margin:auto;padding:16px clamp(16px,4vw,40px)}"
        "header a{color:#1f4e63;font-weight:600}h1{font:clamp(28px,4vw,44px)/1.15 Georgia,serif;margin:12px 0}h2{font:22px/1.3 Georgia,serif}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:16px;align-items:end;margin:20px 0}"
        ".field{display:flex;flex-direction:column;gap:6px}label{font-weight:600}input,select,button{font:inherit;min-height:44px;padding:6px 10px;border:1px solid #6d7b78;background:#fff;color:#1f2a2c}"
        "input[type=checkbox]{width:24px;height:24px;min-height:24px}input[type=range]{padding:0}button{background:#1f4e63;color:#fff;cursor:pointer;border-color:#1f4e63}"
        "table{width:100%;border-collapse:collapse;background:#fff}caption{text-align:left;font-weight:600;padding:8px 0}th,td{text-align:left;padding:10px;border-bottom:1px solid #d5dad7;overflow-wrap:anywhere}"
        "output{font-weight:700;font-variant-numeric:tabular-nums}code{background:#eceae2;padding:1px 5px}.problem{background:#f9e3e0;color:#7a1f14;padding:12px}.invariants{padding-left:20px}"
        "a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #1f4e63;outline-offset:2px}.table-wrap{overflow-x:auto}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}")


# ---------------- server ----------------

def _coerce_query(spec, query):
    fields = {f["name"]: f for f in spec["inputs"]}
    values = {}
    for name, items in query.items():
        field, raw = fields.get(name), items[-1]
        if field is None:
            values[name] = raw
        elif raw == "":
            continue
        elif field["type"] in ("number", "integer"):
            try:
                number = float(raw)
                values[name] = int(number) if field["type"] == "integer" and number == int(number) else number
            except ValueError:
                values[name] = raw
        elif field["type"] == "boolean":
            values[name] = raw.lower() in ("true", "1", "on", "yes")
        else:
            values[name] = raw
    return values


def make_server(root, *, host="127.0.0.1", port=0, revision=""):
    root = Path(root).resolve()
    spec = validate_instrument_spec(json.loads((root / "instrument.json").read_text(encoding="utf-8")))
    page = (root / "pages" / "index.html").read_text(encoding="utf-8")
    page = page.replace("{{name}}", _html.escape(spec["name"])).replace("{{spec_json}}", json.dumps(spec, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, payload, content_type="application/json; charset=utf-8"):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def run(self, operation):
            try:
                return operation()
            except InputError as error:
                self.send(400, {"error": str(error), "errors": error.errors})
            except LookupError as error:
                self.send(404, {"error": str(error)})
            except (ValueError, TypeError) as error:
                self.send(400, {"error": str(error)})

        def do_GET(self):
            parts = urlsplit(self.path)
            query = parse_qs(parts.query, keep_blank_values=True)

            def go():
                if parts.path in ("/", "/index.html"):
                    return self.send(200, page.encode("utf-8"), "text/html; charset=utf-8")
                if parts.path == "/favicon.ico":
                    return self.send(204, b"", "image/x-icon")
                if parts.path == "/api/health":
                    return self.send(200, {"service": "vitruvius-instrument", "revision": revision, "name": spec["name"]})
                if parts.path == "/api/spec":
                    return self.send(200, spec)
                if parts.path == "/api/examples":
                    return self.send(200, {"examples": check_examples(spec)})
                if parts.path == "/api/compute":
                    return self.send(200, compute(spec, _coerce_query(spec, query)))
                if parts.path == "/api/explain":
                    return self.send(200, explain(spec, _coerce_query(spec, query)))
                if parts.path == "/explain":
                    values = _coerce_query(spec, query) if query else dict(spec["examples"][0]["inputs"]) if spec["examples"] else {}
                    if query:
                        for f in spec["inputs"]:
                            if f["type"] == "boolean" and f["name"] not in values:
                                values[f["name"]] = False
                    return self.send(200, explain_html(spec, values).encode("utf-8"), "text/html; charset=utf-8")
                raise LookupError("Not found")
            self.run(go)

        def do_POST(self):
            def go():
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                if self.path == "/api/compute":
                    return self.send(200, compute(spec, body))
                if self.path == "/api/table":
                    rows = body.get("rows")
                    if not isinstance(rows, list) or len(rows) > 500:
                        raise ValueError("rows must be a list of at most 500 inputs")
                    out = []
                    for row in rows:
                        try:
                            out.append({"ok": True, **compute(spec, row)})
                        except ValueError as error:
                            out.append({"ok": False, "error": str(error), "errors": getattr(error, "errors", [])})
                    return self.send(200, {"rows": out})
                raise LookupError("Not found")
            self.run(go)

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--database", default="")  # accepted for compatibility with previews; instruments keep no data
    parser.add_argument("--ready-file")
    parser.add_argument("--revision", default="")
    args = parser.parse_args()
    server = make_server(Path(__file__).resolve().parent, host=args.host, port=args.port, revision=args.revision)
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
