"""Synthesis of rules and small programs from examples (counterexample-guided).

Target language: the safe expression language of ``expressions.py``. Given input/output examples (and outputs the
expression must not produce), a bottom-up enumerative search by expression size, pruned by observational
equivalence, finds the simplest consistent expression (plus one level of ``a if c else b`` splits assembled from
the simplest piece per example subset). A CEGIS loop then validates the candidate against a reference program on
generated and boundary inputs; every disagreement becomes a new example and the search continues until no
counterexample is found within the budget. The primitive operations come from ``expressions`` (BIN, CMP,
FUNCTIONS) and every final candidate is checked through ``Expression.evaluate``; there is no second evaluator
for the language.
"""
import ast
from collections import Counter
from decimal import Decimal, InvalidOperation
import json
import keyword
import math
import random
import shutil
import tempfile
import time

from . import strategies
from .equivalence import DEFAULT_ENV, _clip
from .expressions import BIN, FUNCTIONS, Expression, ExpressionError
from .properties import program
from .rules import PREDICATE_NAMES
from .store import identifier

SCOPE = ("The expression is consistent with the listed examples and, when a reference program was given, no disagreement "
         "was found on the validation inputs that were executed (see validation.coverage). That is evidence, not a proof "
         "of equivalence, and says nothing about Theseus completion.")
ERR = object()
TOL = 1e-9
BATCH = ("import sys,json,importlib\n"
         "if sys.argv[2]: sys.path.insert(0, sys.argv[2])\n"
         "m,f=sys.argv[1].split(':',1)\n"
         "fn=getattr(importlib.import_module(m),f)\n"
         "out=[]\n"
         "for v in json.loads(sys.stdin.read()):\n"
         "    try: out.append({'ok': fn(v)})\n"
         "    except Exception as e: out.append({'err': type(e).__name__+': '+str(e)})\n"
         "print(json.dumps(out,ensure_ascii=False,default=str))\n")
NUM_CONSTANTS = (1, 2, 3, 5, 10, 100, 0.5, 0.1, 0.01)
THRESHOLDS = (0,)
ARITH = (("+", 5, "add"), ("-", 5, "sub"), ("*", 6, "mul"), ("/", 6, "truediv"), ("//", 6, "floordiv"), ("%", 6, "mod"))
ROUNDERS = ("round_half_up", "round_half_even", "round_floor", "round_ceiling")
NUM_UNARY = ("abs", "floor", "ceil", "trunc", "round")
STR_UNARY = ("lower", "upper", "strip", "lstrip", "rstrip")
COMPARE = ((">", "gt"), (">=", "ge"), ("<", "lt"), ("<=", "le"), ("==", "eq"), ("!=", "ne"))
PREC_ITE, PREC_OR, PREC_AND, PREC_NOT, PREC_CMP, PREC_ADD, PREC_MUL, PREC_ATOM = 0, 1, 2, 3, 4, 5, 6, 10


class Budget(Exception):
    """The time or candidate budget ended."""


# ------------------------------------------------------------------ values

def kind_of(value):
    if value is ERR:
        return None
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "num"
    if isinstance(value, str):
        return "str"
    return None


def same(a, b):
    ka, kb = kind_of(a), kind_of(b)
    if ka is None or ka != kb:
        return False
    if ka == "num":
        return abs(a - b) <= TOL * max(1.0, abs(b))
    return a == b


def sig_item(v):
    if v is ERR:
        return "E"
    k = kind_of(v)
    return (k, round(float(v), 9) if k == "num" else v)


def apply(fn, *args):
    if any(a is ERR for a in args):
        return ERR
    try:
        v = fn(*args)
    except Exception:  # data errors of the candidate on this input
        return ERR
    k = kind_of(v)
    if k is None or (k == "num" and (v != v or abs(v) > 1e15)):
        return ERR
    return v


def _paren(node, need):
    return "(%s)" % node[3] if node[4] < need else node[3]


def number_text(value):
    if isinstance(value, float) and value == int(value) and abs(value) < 1e15:
        return repr(float(value))
    return repr(value)


# ------------------------------------------------------------------ search

class Search:
    """Bottom-up enumeration. Node = (type, size, vec, src, prec, uses_var)."""

    def __init__(self, points, variables, out_type, positives, forbidden, constants, thresholds, strings, places, deadline,
                 max_size, max_nodes):
        self.points, self.variables, self.out_type = points, variables, out_type
        self.positives, self.forbidden = positives, forbidden  # {index: value}
        self.deadline, self.max_size, self.max_nodes = deadline, max_size, max_nodes
        self.constants, self.thresholds, self.strings, self.places = constants, thresholds, strings, places
        self.bank, self.seen, self.count, self.ticks = {}, {}, 0, 0
        self.best = []
        self.solution = None
        self.stopped = None
        self.split_found = None
        self.has_str = out_type == "str" or "str" in variables.values()

    # ---- bookkeeping
    def tick(self):
        self.ticks += 1
        if self.ticks % 512 == 0 and time.monotonic() > self.deadline:
            raise Budget("time budget ended")

    def score(self, node):
        good = sum(1 for i, want in self.positives.items() if same(node[2][i], want))
        bad = sum(1 for i, no in self.forbidden.items() if same(node[2][i], no))
        return good, bad

    def add(self, kind, size, vec, src, prec, uses):
        if all(v is ERR for v in vec):
            return None
        key = (kind, tuple(sig_item(v) for v in vec))
        if key in self.seen:
            return None
        node = (kind, size, vec, src, prec, uses)
        self.seen[key] = node
        self.bank.setdefault(kind, {}).setdefault(size, []).append(node)
        self.count += 1
        if self.count > self.max_nodes:
            raise Budget("candidate budget ended")
        if kind == self.out_type:
            good, bad = self.score(node)
            if self.solution is None and good == len(self.positives) and bad == 0:
                self.solution = node
            if uses and (not self.best or good > self.best[-1][0] or len(self.best) < 6):
                self.best.append((good - bad, size, node))
                self.best.sort(key=lambda t: (-t[0], t[1]))
                del self.best[6:]
        return node

    def nodes(self, kind, size):
        return self.bank.get(kind, {}).get(size, [])

    # ---- generation
    def terminals(self):
        for name, kind in self.variables.items():
            self.add(kind, 1, tuple(p[name] for p in self.points), name, PREC_ATOM, True)
        n = len(self.points)
        for c in self.constants:
            self.add("num", 1, (c,) * n, number_text(c), PREC_ATOM, False)
        for s in self.strings:
            self.add("str", 1, (s,) * n, json.dumps(s, ensure_ascii=False), PREC_ATOM, False)

    def level(self, size):
        for a in self.nodes("num", size - 1):
            self.tick()
            for name in NUM_UNARY:
                self.add("num", size, tuple(apply(FUNCTIONS[name], v) for v in a[2]), "%s(%s)" % (name, a[3]), PREC_ATOM, a[5])
        for a in self.nodes("num", size - 2):
            self.tick()
            for name in ROUNDERS:
                for k in self.places:
                    self.add("num", size, tuple(apply(FUNCTIONS[name], v, k) for v in a[2]),
                             "%s(%s, %d)" % (name, a[3], k), PREC_ATOM, a[5])
        for a in self.nodes("str", size - 1):
            self.tick()
            for name in STR_UNARY:
                self.add("str", size, tuple(apply(FUNCTIONS[name], v) for v in a[2]), "%s(%s)" % (name, a[3]), PREC_ATOM, a[5])
            self.add("num", size, tuple(apply(FUNCTIONS["len"], v) for v in a[2]), "len(%s)" % a[3], PREC_ATOM, a[5])
            self.add("num", size, tuple(apply(FUNCTIONS["number"], v) for v in a[2]), "number(%s)" % a[3], PREC_ATOM, a[5])
        for a in self.nodes("num", size - 1) if self.has_str else ():
            self.add("str", size, tuple(apply(FUNCTIONS["str"], v) for v in a[2]), "str(%s)" % a[3], PREC_ATOM, a[5])
        for a in self.nodes("str", size - 2):
            self.tick()
            for s in self.strings:
                for name in ("startswith", "endswith", "contains"):
                    self.add("bool", size, tuple(apply(FUNCTIONS[name], v, s) for v in a[2]),
                             "%s(%s, %s)" % (name, a[3], json.dumps(s, ensure_ascii=False)), PREC_ATOM, a[5])
        for a in self.nodes("bool", size - 1):
            self.add("bool", size, tuple(ERR if v is ERR else (not v) for v in a[2]), "not " + _paren(a, PREC_NOT), PREC_NOT, a[5])
        if size >= 4:
            for a in self.nodes("str", size - 3):
                self.tick()
                for s1 in self.strings:
                    for s2 in self.strings:
                        if s1 != s2:
                            self.add("str", size, tuple(apply(FUNCTIONS["replace"], v, s1, s2) for v in a[2]),
                                     "replace(%s, %s, %s)" % (a[3], json.dumps(s1, ensure_ascii=False), json.dumps(s2, ensure_ascii=False)),
                                     PREC_ATOM, a[5])
        for sa in range(1, size - 1):
            sb = size - 1 - sa
            for a in self.nodes("num", sa):
                self.tick()
                for b in self.nodes("num", sb):
                    uses = a[5] or b[5]
                    if not uses:
                        continue
                    for symbol, prec, fname in ARITH:
                        self.add("num", size, tuple(apply(_BIN[fname], x, y) for x, y in zip(a[2], b[2])),
                                 "%s %s %s" % (_paren(a, prec), symbol, _paren(b, prec + 1)), prec, True)
                    for fname in ("min", "max"):
                        self.add("num", size, tuple(apply(FUNCTIONS[fname], x, y) for x, y in zip(a[2], b[2])),
                                 "%s(%s, %s)" % (fname, a[3], b[3]), PREC_ATOM, True)
                    for symbol, fname in COMPARE:
                        self.add("bool", size, tuple(apply(_CMP[fname], x, y) for x, y in zip(a[2], b[2])),
                                 "%s %s %s" % (_paren(a, PREC_CMP + 1), symbol, _paren(b, PREC_CMP + 1)), PREC_CMP, True)
            for a in self.nodes("str", sa):
                for b in self.nodes("str", sb):
                    if a[5] or b[5]:
                        self.add("str", size, tuple(apply(_BIN["add"], x, y) for x, y in zip(a[2], b[2])),
                                 "%s + %s" % (_paren(a, PREC_ADD), _paren(b, PREC_ADD + 1)), PREC_ADD, True)
                        for symbol, fname in COMPARE[4:]:
                            self.add("bool", size, tuple(apply(_CMP[fname], x, y) for x, y in zip(a[2], b[2])),
                                     "%s %s %s" % (_paren(a, PREC_CMP + 1), symbol, _paren(b, PREC_CMP + 1)), PREC_CMP, True)
            for a in self.nodes("bool", sa):
                for b in self.nodes("bool", sb):
                    for word, prec, op in (("and", PREC_AND, lambda x, y: x and y), ("or", PREC_OR, lambda x, y: x or y)):
                        self.add("bool", size, tuple(ERR if x is ERR or y is ERR else op(x, y) for x, y in zip(a[2], b[2])),
                                 "%s %s %s" % (_paren(a, prec), word, _paren(b, prec + 1)), prec, a[5] or b[5])
        for a in self.nodes("num", size - 2):
            self.tick()
            for symbol, fname in COMPARE:
                for t in self.thresholds:
                    self.add("bool", size, tuple(apply(_CMP[fname], v, t) for v in a[2]),
                             "%s %s %s" % (_paren(a, PREC_CMP + 1), symbol, number_text(t)), PREC_CMP, a[5])

    def run(self, depth=0):
        """Enumerate sizes in order; stop at the first size with a consistent expression or conditional split."""
        try:
            self.terminals()
            for size in range(1, self.max_size + 1):
                if size > 1:
                    self.level(size)
                if self.solution is not None:
                    break
                if depth and size in (3, 4, 5):
                    self.split_found = self.split(depth)
                    if self.split_found is not None:
                        break
        except Budget as exc:
            self.stopped = str(exc)
        return self.solution

    # ---- conditional splits
    def split(self, depth):
        """Simplest ``a if c else b`` whose branches are pool nodes (or nested splits when depth > 1)."""
        pool = sorted(self.bank.get(self.out_type, {}).items())
        flat = [node for _, nodes in pool for node in nodes]
        conds = [node for _, nodes in sorted(self.bank.get("bool", {}).items()) for node in nodes if node[5]]
        indices = tuple(sorted(set(self.positives) | set(self.forbidden)))
        cache = {}

        def accepts(node, i):
            if i in self.positives:
                return same(node[2][i], self.positives[i])
            return node[2][i] is not ERR and not same(node[2][i], self.forbidden[i])

        def best_for(idx, level):
            key = (idx, level)
            if key in cache:
                return cache[key]
            self.tick()
            found = None
            for node in flat:
                if all(accepts(node, i) for i in idx):
                    found = (node[1], node[3], node[4], {i: node[2][i] for i in idx})
                    break
            if level > 1 and (found is None or found[0] > 3):
                limit = found[0] if found else 10 ** 9
                for cond in conds:
                    if cond[1] + 3 >= limit:
                        break
                    if any(cond[2][i] is ERR for i in idx):
                        continue
                    yes = tuple(i for i in idx if cond[2][i])
                    no = tuple(i for i in idx if not cond[2][i])
                    if not yes or not no:
                        continue
                    a, b = best_for(yes, level - 1), best_for(no, level - 1)
                    if a and b and 1 + cond[1] + a[0] + b[0] < limit:
                        limit = 1 + cond[1] + a[0] + b[0]
                        found = (limit, "%s if %s else %s" % (_wrap(a), cond[3], _wrap(b)), PREC_ITE,
                                 {i: (a[3] if cond[2][i] else b[3])[i] for i in idx})
            cache[key] = found
            return found
        try:
            found = best_for(indices, depth + 1)
        except Budget as exc:
            self.stopped = str(exc)
            return None
        return found if found is not None and found[2] == PREC_ITE else None


def _wrap(piece):
    return "(%s)" % piece[1] if piece[2] <= PREC_ITE else piece[1]


import operator as _op
_BIN = {name: getattr(_op, name) for _, _, name in ARITH}
_BIN["add"] = _op.add
_CMP = {name: getattr(_op, name) for _, name in COMPARE}


# ------------------------------------------------------------------ examples and domains

def _is_name(name):
    return isinstance(name, str) and name.isidentifier() and not keyword.iskeyword(name) and name not in FUNCTIONS


def normalise_examples(examples, variables):
    rows = []
    for i, ex in enumerate(examples):
        if not isinstance(ex, dict) or "output" not in ex:
            raise ValueError("example %d needs an output" % (i + 1))
        inputs = ex["input"] if "input" in ex else {k: v for k, v in ex.items() if k != "output"}
        if not isinstance(inputs, dict) or not inputs:
            raise ValueError("example %d needs input values" % (i + 1))
        rows.append((dict(inputs), ex["output"]))
    names = list(variables) if variables else list(dict.fromkeys(k for inputs, _ in rows for k in inputs))
    for name in names:
        if not _is_name(name):
            raise ValueError("variable %r must be an identifier that is not a helper function name" % (name,))
    return names, rows


def variable_types(names, rows):
    types = {}
    for name in names:
        kinds = set()
        for inputs, _ in rows:
            if name not in inputs:
                raise ValueError("variable %s missing from an example" % name)
            kinds.add(kind_of(inputs[name]))
        if len(kinds) != 1 or None in kinds:
            raise ValueError("variable %s must hold numbers, text or booleans of one kind" % name)
        types[name] = kinds.pop()
    return types


def decimals_of(value):
    text = repr(float(value)) if isinstance(value, float) else str(value)
    return len(text.split(".")[1].rstrip("0")) if "." in text and "e" not in text else 0


def roundest(low, high):
    """The coarsest round number m (a multiple of 1, 2, 5 times a power of ten) with low <= m < high."""
    for exponent in range(9, -5, -1):
        for factor in (10, 5, 1):
            grain = factor * 10 ** exponent / 10
            m = math.ceil(low / grain - 1e-12) * grain
            if low <= m < high:
                return int(m) if m == int(m) else round(m, 6)
    return low


def harvest(names, types, positives):
    """Candidate constants from the examples: stable ratios, differences, linear fits; thresholds; string pieces."""
    constants = list(NUM_CONSTANTS)
    extra = Counter()
    for name in names:
        if types[name] != "num":
            continue
        for inputs, out in positives:
            x = inputs[name]
            if kind_of(out) == "num":
                if x != 0:
                    for k in range(1, 5):
                        extra[round(out / x, k)] += 1
                for k in range(0, 4):
                    extra[round(out - x, k)] += 1
    n = len(positives)
    for value, count in sorted(extra.items(), key=lambda t: (-t[1], decimals_of(t[0]), t[0])):
        if count >= max(2, n // 3) and value not in constants and value != 0 and len(constants) < len(NUM_CONSTANTS) + 8:
            constants.append(value)
    outputs = [out for _, out in positives if kind_of(out) == "num"]
    if len(outputs) >= 2:
        for a in outputs:
            if a not in constants and a == int(a) and abs(a) <= 10 ** 6 and len(constants) < len(NUM_CONSTANTS) + 12:
                constants.append(int(a))
    thresholds = list(THRESHOLDS)
    for name in names:
        if types[name] == "num":
            values = sorted({inputs[name] for inputs, _ in positives})
            thresholds += values[:12]
            for a, b in list(zip(values, values[1:]))[:12]:
                thresholds += [roundest(a, b), round((a + b) / 2, 4)]
    strings = []
    texts = [out for _, out in positives if isinstance(out, str)]
    for name in names:
        if types[name] == "str":
            for inputs, out in positives:
                if isinstance(out, str) and out not in (inputs[name], ""):
                    for piece in (out[:2], out[-2:], out[:1], out[-1:]):
                        if piece and piece not in strings and len(strings) < 8 and piece not in inputs[name]:
                            strings.append(piece)
    for text in texts:
        if len(text) <= 3 and text not in strings and len(strings) < 8:
            strings.append(text)
    if any(types[n] == "str" for n in names) or texts:
        strings += [s for s in ("", " ", "-") if s not in strings]
    constants = list(dict.fromkeys(constants))
    thresholds = list(dict.fromkeys(t for t in thresholds if t not in constants))
    places = sorted({0, 1, 2} | {min(decimals_of(o), 4) for o in outputs})
    return constants, thresholds, strings, places


def infer_domain(names, types, rows):
    domain = {}
    for name in names:
        values = [inputs[name] for inputs, _ in rows]
        if types[name] == "num":
            lo, hi = min(0, min(values)), max(max(values) * 2, max(values) + 10)
            places = max(decimals_of(v) for v in values)
            domain[name] = ({"kind": "integers", "min": int(math.floor(lo)), "max": int(math.ceil(hi))} if places == 0 and
                            all(isinstance(v, int) for v in values) else
                            {"kind": "decimals", "min": lo, "max": hi, "places": min(max(places, 1), 4)})
        elif types[name] == "str":
            alphabet = "".join(sorted(set("".join(values)) | set("ab "))) or "ab"
            domain[name] = {"kind": "text", "min_len": 0, "max_len": max(len(v) for v in values) + 4, "alphabet": alphabet}
        else:
            domain[name] = {"kind": "booleans"}
    return domain


# ------------------------------------------------------------------ reference program

def encode_inputs(values, names, mode):
    items = [values[n] for n in names]
    if mode == "json_object":
        return json.dumps({n: values[n] for n in names}, ensure_ascii=False)
    if mode == "json":
        return json.dumps(items[0] if len(items) == 1 else items, ensure_ascii=False)
    return "\n".join(v if isinstance(v, str) else json.dumps(v) if isinstance(v, bool) else repr(v) for v in items)


def decode_output(text, mode):
    stripped = text.strip()
    if mode == "text":
        return stripped
    try:
        value = json.loads(stripped)
        if kind_of(value) is not None:
            return value
    except ValueError:
        pass
    if mode == "json":
        raise ValueError("output is not a JSON scalar")
    if stripped in {"True", "False"}:
        return stripped == "True"
    try:
        number = Decimal(stripped)
        return int(number) if number == number.to_integral_value() and "." not in stripped and "e" not in stripped.lower() else float(number)
    except InvalidOperation:
        return stripped


class Reference:
    def __init__(self, manager, job_id, raw, names):
        raw = dict(raw)
        self.encode, self.decode = raw.pop("encode", "text"), raw.pop("decode", "auto")
        if self.encode not in {"text", "json", "json_object"} or self.decode not in {"auto", "json", "text"}:
            raise ValueError("reference encode is text|json|json_object and decode is auto|json|text")
        self.spec = program(raw, "reference")
        self.callable = self.spec["callable"]
        self.manager, self.job_id, self.names = manager, job_id, names
        if self.callable:
            self.encode = "json" if len(names) == 1 else "json_object"
        self.sandbox = tempfile.mkdtemp(prefix="theseus-synth-")
        self.runs = 0

    def close(self):
        shutil.rmtree(self.sandbox, ignore_errors=True)

    def _execute(self, argv, text, stdin_extra=None):
        command = self.spec["command"]
        return self.manager._execute(self.job_id, argv, {"cwd": self.sandbox, "env": {**DEFAULT_ENV, **command["env"]},
                                                          "stdin": text, "timeout_seconds": command["timeout_seconds"]})

    def run_many(self, inputs):
        """Return a list of (value, None) or (None, problem) for each input dict."""
        self.runs += len(inputs)
        command = self.spec["command"]
        if self.callable:
            argv = command["argv"][:2] + [BATCH] + command["argv"][3:]
            payload = json.dumps([i[self.names[0]] if len(self.names) == 1 else {n: i[n] for n in self.names} for i in inputs], ensure_ascii=False)
            run = self._execute(argv, payload)
            if run["timed_out"] or run["exit_code"] != 0:
                return [(None, "reference failed: " + _clip(run["stderr"])[-200:])] * len(inputs)
            try:
                rows = json.loads(run["stdout"])
            except ValueError:
                return [(None, "reference output is not JSON")] * len(inputs)
            return [(r["ok"], None) if "ok" in r and kind_of(r["ok"]) else (None, r.get("err", "non-scalar result")) for r in rows]
        out = []
        for values in inputs:
            run = self._execute(command["argv"] + self.spec["args"], encode_inputs(values, self.names, self.encode))
            if run["timed_out"]:
                out.append((None, "reference timed out"))
            elif run["exit_code"] != 0:
                out.append((None, "reference exit code %s: %s" % (run["exit_code"], _clip(run["stderr"])[-200:].strip())))
            else:
                try:
                    out.append((decode_output(run["stdout"], self.decode), None))
                except ValueError as exc:
                    out.append((None, str(exc)))
        return out


# ------------------------------------------------------------------ engine

def source_constants(source):
    found = []
    for node in ast.walk(ast.parse(source, mode="eval")):
        if isinstance(node, ast.Constant) and kind_of(node.value) == "num":
            found.append(node.value)
    return list(dict.fromkeys(found))


def check_candidate(source, names, rows, negatives):
    """Authoritative check through the safe expression language."""
    expr = Expression(source, names)
    for inputs, out in rows:
        if not same(expr.evaluate(inputs), out):
            return False
    for inputs, no in negatives:
        try:
            if same(expr.evaluate(inputs), no):
                return False
        except ExpressionError:
            return False
    return True


def validation_points(source, names, types, domain, rng, count, known):
    points, seen = [], set(known)

    def push(values):
        key = json.dumps(values, sort_keys=True)
        if key not in seen and all(strategies.conforms(domain[n], values[n]) for n in names):
            seen.add(key); points.append(values)

    def draw():
        return {n: strategies.generate(domain[n], rng, rng.uniform(.3, 1)) for n in names}
    for name in names:
        if types[name] != "num":
            continue
        step = 1 if domain[name]["kind"] == "integers" else 10 ** -domain[name].get("places", 2)
        for c in source_constants(source):
            for v in (c, c - step, c + step):
                v = int(v) if domain[name]["kind"] == "integers" and v == int(v) else round(v, domain[name].get("places", 2))
                push({**draw(), name: v})
        for edge in (domain[name]["min"], domain[name]["max"]):
            push({**draw(), name: edge})
    boundary = points[:max(1, count // 2) + 4]
    del points[len(boundary):]
    while len(points) < count and len(seen) < len(known) + count * 20:
        push(draw())
        if len(seen) > len(known) + count * 20:
            break
    return points[:count + 4]


class Synthesis:
    def __init__(self, manager, equivalence, rules):
        self.manager, self.store, self.equivalence, self.rules = manager, manager.store, equivalence, rules

    def start(self, project_id, examples, rejected=None, variables=None, reference=None, domain=None, max_size=8,
              time_budget_seconds=20, max_rounds=8, samples=30, max_reference_runs=300, seed=1, max_splits=1, save_rule=None):
        self.store.project(project_id)
        for label, value, low, high in (("max_size", max_size, 3, 12), ("max_rounds", max_rounds, 1, 20),
                                         ("samples", samples, 1, 200), ("max_reference_runs", max_reference_runs, 1, 2000),
                                         ("max_splits", max_splits, 0, 3)):
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError("%s is an integer from %d to %d" % (label, low, high))
        if isinstance(time_budget_seconds, bool) or not isinstance(time_budget_seconds, (int, float)) or not 0 < time_budget_seconds <= 300:
            raise ValueError("time_budget_seconds is a number up to 300")
        if not isinstance(examples, list) or not examples:
            raise ValueError("examples is a non-empty array of {input, output}")
        names, rows = normalise_examples(examples, variables)
        types = variable_types(names, rows)
        negatives = []
        for ex in rejected or []:
            inputs = ex.get("input") if isinstance(ex, dict) else None
            if not isinstance(inputs, dict) or "output" not in ex or set(names) - set(inputs):
                raise ValueError("rejected entries are {input, output} over the same variables")
            negatives.append((dict(inputs), ex["output"]))
        out_types = {kind_of(out) for _, out in rows}
        if len(out_types) != 1 or None in out_types:
            raise ValueError("outputs must be numbers, text or booleans of one kind")
        if reference is not None:
            Reference(self.manager, "validate", reference, names).close()
        if domain is not None:
            if not isinstance(domain, dict) or set(domain) - set(names):
                raise ValueError("domain maps variable names to strategies")
            domain = {k: strategies.validate(v, "domain." + k) for k, v in domain.items()}
        spec = {"examples": rows, "negatives": negatives, "names": names, "types": types, "reference": reference,
                "domain": domain, "max_size": max_size, "time_budget_seconds": time_budget_seconds, "max_rounds": max_rounds,
                "samples": samples, "max_reference_runs": max_reference_runs, "seed": seed, "max_splits": max_splits,
                "save_rule": save_rule}
        if save_rule is not None and (not isinstance(save_rule, dict) or set(save_rule) - {"statement", "title", "rule_id", "evidence", "tags"}):
            raise ValueError("save_rule is {statement, title, rule_id, evidence, tags}")
        job_id = identifier()
        result = {"kind": "synthesis", "scope": SCOPE, "variables": names,
                  "options": {k: spec[k] for k in ("max_size", "time_budget_seconds", "max_rounds", "samples", "max_reference_runs", "seed", "max_splits")},
                  "examples_given": [{"input": i, "output": o} for i, o in rows], "summary": {}}
        self.store.save_job(project_id, job_id, "queued", result)
        self.manager.pool.submit(self._run, project_id, job_id, result, spec)
        return self.store.job(job_id)

    def _run(self, project_id, job_id, result, spec):
        reference = None
        try:
            self.store.save_job(project_id, job_id, "running", result)
            if spec["reference"] is not None:
                reference = Reference(self.manager, job_id, spec["reference"], spec["names"])
            result["summary"] = self.synthesize(job_id, spec, reference)
            if spec["save_rule"] is not None and result["summary"].get("expression"):
                result["rule"] = self._save_rule(project_id, spec, result["summary"], reference)
            self.store.save_job(project_id, job_id, "finished", result)
        except InterruptedError as exc:
            result["message"] = str(exc)
            self.store.save_job(project_id, job_id, "cancelled", result)
        except Exception as exc:
            result["error"] = type(exc).__name__ + ": " + str(exc)
            self.store.save_job(project_id, job_id, "failed", result)
        finally:
            if reference is not None:
                reference.close()
            with self.manager.lock:
                self.manager.cancelled.discard(job_id)

    # ---- CEGIS
    def _search(self, spec, rows, negatives, deadline):
        names, types = spec["names"], spec["types"]
        out_type = kind_of(rows[0][1])
        points = [inputs for inputs, _ in rows] + [inputs for inputs, _ in negatives]
        positives = {i: out for i, (_, out) in enumerate(rows)}
        forbidden = {len(rows) + j: no for j, (_, no) in enumerate(negatives)}
        constants, thresholds, strings, places = harvest(names, types, rows)
        search = Search(points, types, out_type, positives, forbidden, constants, thresholds, strings, places, deadline,
                        spec["max_size"], 150000)
        node = search.run(spec["max_splits"])
        if node is not None:
            return search, (node[1], node[3])
        if search.split_found is not None:
            return search, (search.split_found[0], search.split_found[1])
        return search, None

    def _closest(self, search, names, rows, negatives):
        out = []
        for _, size, node in search.best[:3]:
            try:
                expr = Expression(node[3], names)
                failing = []
                for inputs, want in rows:
                    got = expr.evaluate(inputs)
                    if not same(got, want):
                        failing.append({"input": inputs, "expected": want, "got": got})
            except ExpressionError:
                continue
            out.append({"expression": node[3], "size": size, "matches": len(rows) - len(failing), "of": len(rows),
                        "counterexamples": failing[:5]})
        return out

    def synthesize(self, job_id, spec, reference):
        started = time.monotonic()
        deadline = started + spec["time_budget_seconds"]
        names, types = spec["names"], spec["types"]
        rows, negatives = list(spec["examples"]), list(spec["negatives"])
        initial = len(rows)
        rng = random.Random(spec["seed"])
        domain = spec["domain"] or {}
        inferred = [n for n in names if n not in domain]
        if inferred:
            domain = {**infer_domain(names, types, spec["examples"]), **domain}
        rounds, added, checked, ref_errors, last = [], [], 0, [], None
        known = {json.dumps(i, sort_keys=True) for i, _ in rows}
        final_points = []
        status, source, size, closest = None, None, None, []
        for number in range(1, spec["max_rounds"] + 1):
            self.equivalence._check(job_id)
            search, best = self._search(spec, rows, negatives, deadline)
            entry = {"round": number, "examples": len(rows), "candidates_enumerated": search.count,
                     "stopped": search.stopped}
            if best is None or not check_candidate(best[1], names, rows, negatives):
                closest = self._closest(search, names, rows, negatives)
                entry["found"] = None
                rounds.append(entry)
                status = "budget_exhausted" if search.stopped else "no_expression_found"
                if last is not None:
                    status = "refuted_within_budget" if not search.stopped else "budget_exhausted"
                break
            size, source = best
            last = best
            entry["found"] = source
            if reference is None:
                rounds.append(entry)
                status = "consistent_with_examples"
                break
            budget_left = spec["max_reference_runs"] - reference.runs
            if budget_left <= 0 or time.monotonic() > deadline:
                rounds.append(entry)
                status = "consistent_with_examples_unvalidated"
                break
            points = validation_points(source, names, types, domain, rng, min(spec["samples"], budget_left), known)
            answers = reference.run_many(points)
            expr = Expression(source, names)
            bad = []
            for values, (want, problem) in zip(points, answers):
                checked += 1
                if problem:
                    ref_errors.append({"input": values, "problem": problem})
                    continue
                try:
                    got = expr.evaluate(values)
                except ExpressionError as exc:
                    got = "error: " + str(exc)
                if not same(got, want):
                    bad.append({"input": values, "reference": want, "expression": got})
            final_points = points
            entry.update({"validation_inputs": len(points), "disagreements": len(bad)})
            rounds.append(entry)
            if not bad:
                status = "validated_against_reference"
                break
            for item in bad[:3]:
                rows.append((item["input"], item["reference"]))
                known.add(json.dumps(item["input"], sort_keys=True))
                added.append(item)
            if len(rows) > initial + 40:
                status = "refuted_within_budget"
                break
        else:
            status = "refuted_within_budget"
        if status in {"refuted_within_budget", "budget_exhausted"} and source is not None and not closest:
            closest = [{"expression": source, "size": size, "note": "last candidate; the reference disagreed with it",
                        "counterexamples": added[-5:]}]
        per_variable = {n: {"min": min(v[n] for v in [i for i, _ in rows]), "max": max(v[n] for v in [i for i, _ in rows]),
                            "distinct": len({json.dumps(i[n]) for i, _ in rows})} for n in names if types[n] == "num"}
        success = status in {"validated_against_reference", "consistent_with_examples", "consistent_with_examples_unvalidated"}
        return {
            "status": status, "expression": source if success else None, "size": size if success else None,
            "variables": names, "examples_used": [{"input": i, "output": o} for i, o in rows],
            "examples_added_by_validation": added, "rejected_outputs": [{"input": i, "output": o} for i, o in negatives],
            "validation": {"reference": reference is not None, "rounds": len(rounds), "inputs_checked": checked,
                           "reference_runs": reference.runs if reference else 0, "reference_errors": ref_errors[:5],
                           "domain": domain, "domain_inferred_for": inferred, "coverage": per_variable,
                           "last_round_inputs": final_points[:10], "per_round": rounds},
            "closest_candidates": closest,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "note": {"validated_against_reference": "No disagreement with the reference in the last round. " + SCOPE,
                     "consistent_with_examples": "Consistent with the examples only; no reference program was given to validate it.",
                     "consistent_with_examples_unvalidated": "Consistent with the examples, but the validation budget ended before the reference could confirm it.",
                     "no_expression_found": "No expression up to the size limit is consistent with every example; closest candidates are listed.",
                     "budget_exhausted": "The time or candidate budget ended before a consistent expression was found.",
                     "refuted_within_budget": "Each candidate was refuted by the reference or the rounds ended; the closest candidates and their counterexamples are listed."}[status]}

    # ---- rules bank
    @staticmethod
    def rule_predicate(source, names, types, out_type, reference):
        """Predicate over stdin/stdout for the reference program, or None when the encoding cannot express it."""
        if reference is None or reference.callable or reference.encode != "text" or any(types[n] == "bool" for n in names):
            return None

        class Rewrite(ast.NodeTransformer):
            def visit_Name(self, node):
                if node.id not in names:
                    return node
                i = names.index(node.id)
                raw = ast.parse("stdin" if len(names) == 1 else "lines(stdin)[%d]" % i, mode="eval").body
                return ast.parse("number(%s)" % ast.unparse(raw), mode="eval").body if types[node.id] == "num" else raw
        body = ast.unparse(ast.fix_missing_locations(Rewrite().visit(ast.parse(source, mode="eval").body)))
        if out_type == "num":
            return "abs(number(stdout) - (%s)) <= 0.000000001" % body
        if out_type == "bool":
            return "lower(strip(stdout)) == lower(str(%s))" % body
        return "rstrip(stdout) == (%s)" % body

    def _save_rule(self, project_id, spec, summary, reference):
        options = dict(spec["save_rule"])
        names, types, source = spec["names"], spec["types"], summary["expression"]
        out_type = kind_of(spec["examples"][0][1])
        predicate = self.rule_predicate(source, names, types, out_type, reference)
        check = None
        if predicate and reference is not None:
            inputs = [i for i, _ in summary_examples(summary)]
            inputs += summary["validation"].get("last_round_inputs", [])
            cases = [{"name": "synth-%d" % n, "stdin": encode_inputs(v, names, "text")} for n, v in enumerate(inputs[:40])]
            check = {"reference": reference.spec["command"] | {"argv": reference.spec["command"]["argv"] + reference.spec["args"]},
                     "predicate": predicate, "cases": cases}
        statement = str(options.get("statement") or "The output equals `%s` for inputs %s." % (source, ", ".join(names)))
        status = summary["status"]
        evidence = options.get("evidence") or []
        examples = [{"source": "synthesis", "input": i, "output": o} for i, o in summary_examples(summary)[:6]]
        note = ("Synthesised from %d example(s); status %s. A hypothesis until theseus_rules_check observes it."
                % (len(summary["examples_used"]), status))
        saved = self.rules.save(project_id, statement, rule_id=options.get("rule_id", ""), evidence=evidence,
                                examples=examples + [{"source": "synthesis", "note": note, "expression": source}],
                                check=check, tags=list(options.get("tags") or []) + ["synthesized"],
                                title=str(options.get("title") or ""))
        return {"rule_id": saved["id"], "status": saved["status"], "has_check": saved["check"] is not None,
                "note": note + ("" if check else " No executable check could be built (needs an argv reference with text encoding and numeric or text variables).")}


def summary_examples(summary):
    return [(e["input"], e["output"]) for e in summary["examples_used"]]
