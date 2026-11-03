"""Small safe expression language for rule predicates and failure signatures.

The text is parsed with ``ast`` and interpreted by a whitelisting walker. It is
never passed to ``eval``/``exec``. Allowed: literals, names bound by the caller,
arithmetic, comparisons, boolean logic, conditional expressions, indexing and
slicing, list/tuple literals, and calls of a fixed set of pure helper functions
(called by plain name only). Attribute access, imports, lambdas, comprehensions,
keyword arguments, starred arguments and any other name are rejected.
"""
import ast
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING, InvalidOperation
import math
import operator
import re

MAX_SOURCE = 2000
MAX_NODES = 400
MAX_SIZE = 100000
MAX_POW = 64


class ExpressionError(ValueError):
    """Rejected or failing expression."""


def _decimal(value):
    try:
        return Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ExpressionError("not a decimal number: %r" % (value,)) from exc


def _quantum(places):
    places = int(places)
    if not -20 <= places <= 20:
        raise ExpressionError("rounding places must be between -20 and 20")
    return Decimal(1).scaleb(-places)


def _round(mode):
    def run(value, places=0):
        return float(_decimal(value).quantize(_quantum(places), rounding=mode)) if int(places) > 0 else \
            int(_decimal(value).quantize(_quantum(places), rounding=mode))
    return run


def _pattern(pattern):
    if not isinstance(pattern, str) or len(pattern) > 300:
        raise ExpressionError("regular expression must be text of at most 300 characters")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ExpressionError("invalid regular expression: %s" % exc) from exc


def _text(value):
    if not isinstance(value, str):
        raise ExpressionError("text expected, got " + type(value).__name__)
    return value


def _sorted(value):
    return sorted(value)


FUNCTIONS = {
    "len": len, "abs": abs, "min": min, "max": max, "sum": sum, "int": int, "float": float, "str": str,
    "bool": bool, "sorted": _sorted, "any": any, "all": all,
    "floor": math.floor, "ceil": math.ceil, "trunc": math.trunc, "sqrt": math.sqrt,
    "round": round,
    "round_half_up": _round(ROUND_HALF_UP), "round_half_even": _round(ROUND_HALF_EVEN),
    "round_floor": _round(ROUND_FLOOR), "round_ceiling": _round(ROUND_CEILING),
    "lower": lambda s: _text(s).lower(), "upper": lambda s: _text(s).upper(),
    "strip": lambda s: _text(s).strip(), "lstrip": lambda s: _text(s).lstrip(), "rstrip": lambda s: _text(s).rstrip(),
    "startswith": lambda s, p: _text(s).startswith(_text(p)), "endswith": lambda s, p: _text(s).endswith(_text(p)),
    "contains": lambda s, p: _text(p) in _text(s),
    "replace": lambda s, a, b: _text(s).replace(_text(a), _text(b)),
    "split": lambda s, sep=None: _text(s).split(sep), "join": lambda sep, items: _text(sep).join(items),
    "lines": lambda s: _text(s).splitlines(), "words": lambda s: _text(s).split(),
    "count": lambda s, p: _text(s).count(_text(p)),
    "regex_search": lambda p, s: _pattern(p).search(_text(s)) is not None,
    "regex_match": lambda p, s: _pattern(p).fullmatch(_text(s)) is not None,
    "regex_findall": lambda p, s: _pattern(p).findall(_text(s)),
    "regex_sub": lambda p, r, s: _pattern(p).sub(_text(r), _text(s)),
    "number": lambda s: float(_decimal(s)),
}

BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
UNARY = {ast.Not: operator.not_, ast.USub: operator.neg, ast.UAdd: operator.pos}
CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
       ast.Gt: operator.gt, ast.GtE: operator.ge, ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}
CONSTANTS = (str, int, float, bool, type(None))


def _size(value):
    if isinstance(value, (str, bytes, list, tuple)) and len(value) > MAX_SIZE:
        raise ExpressionError("value too large")
    return value


class Expression:
    """Compiled, validated expression. ``names`` are the variables it may read."""

    def __init__(self, source, names=()):
        if not isinstance(source, str) or not source.strip():
            raise ExpressionError("expression must be non-empty text")
        if len(source) > MAX_SOURCE:
            raise ExpressionError("expression longer than %d characters" % MAX_SOURCE)
        try:
            tree = ast.parse(source.strip(), mode="eval")
        except SyntaxError as exc:
            raise ExpressionError("syntax error: %s" % exc.msg) from exc
        self.source, self.names, self.count = source, frozenset(names), 0
        self.tree = tree.body
        self.check(self.tree)

    # ---- validation
    def check(self, node):
        self.count += 1
        if self.count > MAX_NODES:
            raise ExpressionError("expression too complex")
        kind = type(node)
        if kind is ast.Constant:
            if not isinstance(node.value, CONSTANTS):
                raise ExpressionError("constant type not allowed")
        elif kind is ast.Name:
            if node.id not in self.names:
                raise ExpressionError("unknown name: " + node.id)
        elif kind is ast.BinOp:
            if type(node.op) not in BIN:
                raise ExpressionError("operator not allowed")
            self.check(node.left); self.check(node.right)
        elif kind is ast.UnaryOp:
            if type(node.op) not in UNARY:
                raise ExpressionError("operator not allowed")
            self.check(node.operand)
        elif kind is ast.BoolOp:
            for v in node.values:
                self.check(v)
        elif kind is ast.Compare:
            if any(type(op) not in CMP for op in node.ops):
                raise ExpressionError("comparison not allowed")
            self.check(node.left)
            for c in node.comparators:
                self.check(c)
        elif kind is ast.IfExp:
            self.check(node.test); self.check(node.body); self.check(node.orelse)
        elif kind is ast.Subscript:
            self.check(node.value); self.check(node.slice)
        elif kind is ast.Slice:
            for part in (node.lower, node.upper, node.step):
                if part is not None:
                    self.check(part)
        elif kind in (ast.List, ast.Tuple):
            for e in node.elts:
                self.check(e)
        elif kind is ast.Call:
            if isinstance(node.func, ast.Attribute):
                raise ExpressionError("attribute access is not allowed (use helper functions such as strip(text))")
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise ExpressionError("call not allowed: only whitelisted functions by plain name (%s)"
                                      % ", ".join(sorted(FUNCTIONS)))
            if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
                raise ExpressionError("keyword and starred arguments are not allowed")
            for a in node.args:
                self.check(a)
        elif kind is ast.Attribute:
            raise ExpressionError("attribute access is not allowed")
        else:
            raise ExpressionError("syntax not allowed: " + kind.__name__)

    # ---- evaluation
    def evaluate(self, variables):
        extra = set(variables) - self.names
        if extra:
            raise ExpressionError("undeclared variables: " + ", ".join(sorted(extra)))
        try:
            return self.walk(self.tree, variables)
        except ExpressionError:
            raise
        except RecursionError as exc:
            raise ExpressionError("expression too deep") from exc
        except Exception as exc:  # arithmetic, type, index, value errors of the data
            raise ExpressionError("%s: %s" % (type(exc).__name__, exc)) from exc

    def walk(self, node, env):
        kind = type(node)
        if kind is ast.Constant:
            return node.value
        if kind is ast.Name:
            if node.id not in env:
                raise ExpressionError("variable not available: " + node.id)
            return env[node.id]
        if kind is ast.BinOp:
            left, right = self.walk(node.left, env), self.walk(node.right, env)
            if type(node.op) is ast.Pow:
                if not (isinstance(right, int) and not isinstance(right, bool) and 0 <= right <= MAX_POW
                        and isinstance(left, (int, float)) and abs(left) <= 10 ** 6):
                    raise ExpressionError("power limited to small integer exponents")
            if type(node.op) is ast.Mult and (isinstance(left, (str, list, tuple)) or isinstance(right, (str, list, tuple))):
                seq, count = (left, right) if isinstance(left, (str, list, tuple)) else (right, left)
                if not isinstance(count, int) or count * len(seq) > MAX_SIZE:
                    raise ExpressionError("repetition too large")
            return _size(BIN[type(node.op)](left, right))
        if kind is ast.UnaryOp:
            return UNARY[type(node.op)](self.walk(node.operand, env))
        if kind is ast.BoolOp:
            if isinstance(node.op, ast.And):
                result = True
                for v in node.values:
                    result = self.walk(v, env)
                    if not result:
                        return result
                return result
            result = False
            for v in node.values:
                result = self.walk(v, env)
                if result:
                    return result
            return result
        if kind is ast.Compare:
            left = self.walk(node.left, env)
            for op, comp in zip(node.ops, node.comparators):
                right = self.walk(comp, env)
                if not CMP[type(op)](left, right):
                    return False
                left = right
            return True
        if kind is ast.IfExp:
            return self.walk(node.body if self.walk(node.test, env) else node.orelse, env)
        if kind is ast.Subscript:
            return self.walk(node.value, env)[self.walk(node.slice, env)]
        if kind is ast.Slice:
            return slice(*(self.walk(p, env) if p is not None else None for p in (node.lower, node.upper, node.step)))
        if kind is ast.List:
            return [self.walk(e, env) for e in node.elts]
        if kind is ast.Tuple:
            return tuple(self.walk(e, env) for e in node.elts)
        if kind is ast.Call:
            return _size(FUNCTIONS[node.func.id](*[self.walk(a, env) for a in node.args]))
        raise ExpressionError("syntax not allowed: " + kind.__name__)


def compile_expression(source, names):
    return Expression(source, names)
