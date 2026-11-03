"""A small, safe expression language for protocol specs (a subset of Python syntax).

Allowed: literals, names, + - * // % (integers), comparisons (incl. chained, in,
not in), and/or/not, x if c else y, tuples/lists/dicts/sets literals,
subscripts, and the functions len, min, max, abs, sorted, set_add,
set_remove, append, put, without (pure: they return new values).
Values are immutable: lists become tuples, dicts become sorted tuples of pairs
wrapped in :class:`FDict`, sets become frozensets.
"""
from __future__ import annotations

import ast
from typing import Any


class SpecError(ValueError):
    pass


class FDict(tuple):
    """Immutable dict (sorted key/value pairs) usable inside hashed states."""

    def __new__(cls, items):
        return super().__new__(cls, tuple(sorted(items, key=lambda kv: repr(kv[0]))))

    def __eq__(self, other):
        return isinstance(other, FDict) and tuple.__eq__(self, other)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash((FDict, tuple(self)))

    def get(self, key, default=None):
        for k, v in self:
            if k == key:
                return v
        return default

    def __contains__(self, key):  # dict semantics: membership tests keys
        return any(k == key for k, _ in self)

    def keys(self):
        return [k for k, _ in self]

    def __repr__(self):
        return "{" + ", ".join(f"{k!r}: {v!r}" for k, v in self) + "}"


def freeze(v: Any) -> Any:
    if isinstance(v, FDict):
        return v
    if isinstance(v, dict):
        return FDict((freeze(k), freeze(x)) for k, x in v.items())
    if isinstance(v, (list, tuple)) and not isinstance(v, FDict):
        return tuple(freeze(x) for x in v)
    if isinstance(v, (set, frozenset)):
        return frozenset(freeze(x) for x in v)
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    raise SpecError(f"valor no soportado en el estado: {v!r} (usa enteros, texto, booleanos, null, listas, conjuntos o diccionarios)")


def thaw(v: Any) -> Any:
    if isinstance(v, FDict):
        return {str(k) if not isinstance(k, str) else k: thaw(x) for k, x in v}
    if isinstance(v, frozenset):
        return sorted((thaw(x) for x in v), key=repr)
    if isinstance(v, tuple):
        return [thaw(x) for x in v]
    return v


def _put(d, k, v):
    items = [(a, b) for a, b in d if a != k] if isinstance(d, FDict) else []
    return FDict(items + [(k, v)])


def _without(c, k):
    if isinstance(c, FDict):
        return FDict((a, b) for a, b in c if a != k)
    if isinstance(c, frozenset):
        return c - {k}
    if isinstance(c, tuple):
        out = list(c)
        if k in out:
            out.remove(k)
        return tuple(out)
    raise SpecError("without() espera un diccionario, conjunto o lista")


FUNCS = {
    "len": len, "min": min, "max": max, "abs": abs,
    "sorted": lambda x: tuple(sorted(x)),
    "set_add": lambda s, x: frozenset(s) | {x},
    "set_remove": lambda s, x: frozenset(s) - {x},
    "append": lambda l, x: tuple(l) + (x,),
    "put": _put,
    "without": _without,
}

_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b}
_CMP = {ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b, ast.Lt: lambda a, b: a < b,
        ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
        ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}


class Expr:
    """A parsed, validated expression; ``names`` are the free variables it reads."""

    __slots__ = ("text", "tree", "names")

    def __init__(self, text: str):
        if not isinstance(text, str) or not text.strip():
            raise SpecError("expresión vacía")
        self.text = text
        try:
            self.tree = ast.parse(text.strip(), mode="eval").body
        except SyntaxError as e:
            raise SpecError(f"expresión no válida {text!r}: {e.msg}") from None
        self.names = set()
        self._check(self.tree)

    def _check(self, n):
        if isinstance(n, ast.Constant):
            if not (n.value is None or isinstance(n.value, (bool, int, str))):
                raise SpecError(f"constante no soportada en {self.text!r}")
        elif isinstance(n, ast.Name):
            if n.id not in ("True", "False", "None"):
                self.names.add(n.id)
        elif isinstance(n, ast.BinOp):
            if type(n.op) not in _BIN:
                raise SpecError(f"operador no soportado en {self.text!r} (solo + - * // %)")
            self._check(n.left)
            self._check(n.right)
        elif isinstance(n, ast.UnaryOp):
            if not isinstance(n.op, (ast.Not, ast.USub)):
                raise SpecError(f"operador unario no soportado en {self.text!r}")
            self._check(n.operand)
        elif isinstance(n, ast.BoolOp):
            for v in n.values:
                self._check(v)
        elif isinstance(n, ast.Compare):
            if any(type(o) not in _CMP for o in n.ops):
                raise SpecError(f"comparación no soportada en {self.text!r}")
            self._check(n.left)
            for c in n.comparators:
                self._check(c)
        elif isinstance(n, ast.IfExp):
            self._check(n.test)
            self._check(n.body)
            self._check(n.orelse)
        elif isinstance(n, (ast.Tuple, ast.List, ast.Set)):
            for e in n.elts:
                self._check(e)
        elif isinstance(n, ast.Dict):
            for k in n.keys:
                if k is None:
                    raise SpecError("** no está permitido")
                self._check(k)
            for v in n.values:
                self._check(v)
        elif isinstance(n, ast.Subscript):
            self._check(n.value)
            self._check(n.slice)
        elif isinstance(n, ast.Call):
            if not isinstance(n.func, ast.Name) or n.func.id not in FUNCS or n.keywords:
                raise SpecError(f"función no permitida en {self.text!r}; disponibles: {', '.join(sorted(FUNCS))}")
            for a in n.args:
                self._check(a)
        else:
            raise SpecError(f"sintaxis no permitida en {self.text!r}: {type(n).__name__}")

    def eval(self, env: dict[str, Any]) -> Any:
        try:
            return freeze(self._eval(self.tree, env))
        except SpecError:
            raise
        except KeyError as e:
            raise SpecError(f"{self.text!r}: clave inexistente {e}") from None
        except IndexError:
            raise SpecError(f"{self.text!r}: índice fuera de rango") from None
        except ZeroDivisionError:
            raise SpecError(f"{self.text!r}: división por cero") from None
        except TypeError as e:
            raise SpecError(f"{self.text!r}: {e}") from None

    def _eval(self, n, env):
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id == "True":
                return True
            if n.id == "False":
                return False
            if n.id == "None":
                return None
            if n.id not in env:
                raise SpecError(f"{self.text!r}: variable desconocida {n.id!r}")
            return env[n.id]
        if isinstance(n, ast.BinOp):
            a, b = self._eval(n.left, env), self._eval(n.right, env)
            if isinstance(n.op, ast.Add) and isinstance(a, tuple) and isinstance(b, tuple):
                return a + b
            return _BIN[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp):
            v = self._eval(n.operand, env)
            return (not v) if isinstance(n.op, ast.Not) else -v
        if isinstance(n, ast.BoolOp):
            if isinstance(n.op, ast.And):
                r = True
                for v in n.values:
                    r = self._eval(v, env)
                    if not r:
                        return r
                return r
            r = False
            for v in n.values:
                r = self._eval(v, env)
                if r:
                    return r
            return r
        if isinstance(n, ast.Compare):
            left = self._eval(n.left, env)
            for op, c in zip(n.ops, n.comparators):
                right = self._eval(c, env)
                if not _CMP[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(n, ast.IfExp):
            return self._eval(n.body, env) if self._eval(n.test, env) else self._eval(n.orelse, env)
        if isinstance(n, (ast.Tuple, ast.List)):
            return tuple(self._eval(e, env) for e in n.elts)
        if isinstance(n, ast.Set):
            return frozenset(self._eval(e, env) for e in n.elts)
        if isinstance(n, ast.Dict):
            return FDict((self._eval(k, env), self._eval(v, env)) for k, v in zip(n.keys, n.values))
        if isinstance(n, ast.Subscript):
            c = self._eval(n.value, env)
            k = self._eval(n.slice, env)
            if isinstance(c, FDict):
                for a, b in c:
                    if a == k:
                        return b
                raise KeyError(k)
            return c[k]
        if isinstance(n, ast.Call):
            return FUNCS[n.func.id](*(self._eval(a, env) for a in n.args))
        raise SpecError(f"sintaxis no permitida en {self.text!r}")
