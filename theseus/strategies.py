"""Composable, seeded, shrinkable input strategies for property tests and synthesis validation.

A strategy is a JSON object: ``{"kind": "integers", "min": -5, "max": 5}``. Kinds: integers, decimals, text, lists,
dicts, one_of, tuples, constant, booleans, sampled_from. ``generate`` draws a value from a ``random.Random`` and a
size fraction in (0, 1]; ``shrink`` proposes strictly simpler values that still conform to the strategy. A proposal is
only a proposal: callers re-execute the program under test before accepting it.
"""
import json

KINDS = ("integers", "decimals", "text", "lists", "dicts", "one_of", "tuples", "constant", "booleans", "sampled_from")
DEFAULT_ALPHABET = "abcXYZ019 -_éñ日"
MAX_DEPTH = 6
MAX_ITEMS = 50


def _int(value, field, default):
    value = default if value is None else value
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(field + " must be an integer")
    return value


def _number(value, field, default):
    value = default if value is None else value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(field + " must be a number")
    return value


def validate(strategy, where="input", depth=0):
    """Return a normalised copy or raise ValueError."""
    if depth > MAX_DEPTH:
        raise ValueError(where + " is nested too deeply")
    if not isinstance(strategy, dict) or strategy.get("kind") not in KINDS:
        raise ValueError(where + " is an object whose kind is one of " + ", ".join(KINDS))
    kind = strategy["kind"]
    allowed = {"integers": {"min", "max"}, "decimals": {"min", "max", "places"},
               "text": {"min_len", "max_len", "alphabet"}, "lists": {"of", "min_size", "max_size"},
               "dicts": {"fields", "optional"}, "one_of": {"options"}, "tuples": {"items"},
               "constant": {"value"}, "booleans": set(), "sampled_from": {"values"}}[kind]
    extra = set(strategy) - allowed - {"kind"}
    if extra:
        raise ValueError(where + " has unknown fields: " + ", ".join(sorted(extra)))
    if kind == "integers":
        lo, hi = _int(strategy.get("min"), where + ".min", -1000), _int(strategy.get("max"), where + ".max", 1000)
        if lo > hi:
            raise ValueError(where + ": min is greater than max")
        return {"kind": kind, "min": lo, "max": hi}
    if kind == "decimals":
        places = _int(strategy.get("places"), where + ".places", 2)
        lo, hi = _number(strategy.get("min"), where + ".min", -1000), _number(strategy.get("max"), where + ".max", 1000)
        if not 0 <= places <= 8 or lo > hi:
            raise ValueError(where + ": places is 0-8 and min must not exceed max")
        return {"kind": kind, "min": lo, "max": hi, "places": places}
    if kind == "text":
        lo, hi = _int(strategy.get("min_len"), where + ".min_len", 0), _int(strategy.get("max_len"), where + ".max_len", 12)
        alphabet = strategy.get("alphabet", DEFAULT_ALPHABET)
        if not isinstance(alphabet, str) or not alphabet or not 0 <= lo <= hi <= 500:
            raise ValueError(where + ": alphabet is non-empty text and 0 <= min_len <= max_len <= 500")
        return {"kind": kind, "min_len": lo, "max_len": hi, "alphabet": alphabet}
    if kind == "lists":
        lo, hi = _int(strategy.get("min_size"), where + ".min_size", 0), _int(strategy.get("max_size"), where + ".max_size", 6)
        if not 0 <= lo <= hi <= MAX_ITEMS:
            raise ValueError(where + ": 0 <= min_size <= max_size <= %d" % MAX_ITEMS)
        return {"kind": kind, "of": validate(strategy.get("of"), where + ".of", depth + 1), "min_size": lo, "max_size": hi}
    if kind == "dicts":
        fields = strategy.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise ValueError(where + ".fields maps field names to strategies")
        optional = strategy.get("optional", [])
        if not isinstance(optional, list) or set(optional) - set(fields):
            raise ValueError(where + ".optional lists field names")
        return {"kind": kind, "fields": {str(k): validate(v, where + "." + str(k), depth + 1) for k, v in fields.items()},
                "optional": list(optional)}
    if kind == "one_of":
        options = strategy.get("options")
        if not isinstance(options, list) or not options:
            raise ValueError(where + ".options is a non-empty array of strategies")
        return {"kind": kind, "options": [validate(o, where + ".options[%d]" % i, depth + 1) for i, o in enumerate(options)]}
    if kind == "tuples":
        items = strategy.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError(where + ".items is a non-empty array of strategies")
        return {"kind": kind, "items": [validate(o, where + ".items[%d]" % i, depth + 1) for i, o in enumerate(items)]}
    if kind == "constant":
        if "value" not in strategy:
            raise ValueError(where + " needs a value")
        json.dumps(strategy["value"])
        return {"kind": kind, "value": strategy["value"]}
    if kind == "sampled_from":
        values = strategy.get("values")
        if not isinstance(values, list) or not values:
            raise ValueError(where + ".values is a non-empty array")
        json.dumps(values)
        return {"kind": kind, "values": values}
    return {"kind": "booleans"}


def _window(lo, hi, size):
    """Sub-range near zero (or near ``lo``) that grows with ``size``."""
    span = hi - lo
    bound = max(1, int(span * size))
    if lo <= 0 <= hi:
        return max(lo, -bound), min(hi, bound)
    return lo, min(hi, lo + bound)


def generate(strategy, rng, size=1.0):
    kind = strategy["kind"]
    if kind == "integers":
        lo, hi = strategy["min"], strategy["max"]
        if rng.random() < .25:
            edges = [v for v in (lo, hi, 0, 1, -1) if lo <= v <= hi]
            return rng.choice(edges)
        a, b = _window(lo, hi, size)
        return rng.randint(a, b)
    if kind == "decimals":
        p = strategy["places"]
        scale = 10 ** p
        lo, hi = int(round(strategy["min"] * scale)), int(round(strategy["max"] * scale))
        if rng.random() < .15:
            return round(rng.choice([v for v in (lo, hi, 0, 5 * 10 ** max(p - 1, 0)) if lo <= v <= hi]) / scale, p)
        a, b = _window(lo, hi, size)
        return round(rng.randint(a, b) / scale, p)
    if kind == "text":
        n = strategy["min_len"] + int((strategy["max_len"] - strategy["min_len"]) * size * rng.random() + .5)
        return "".join(rng.choice(strategy["alphabet"]) for _ in range(n))
    if kind == "lists":
        n = strategy["min_size"] + int((strategy["max_size"] - strategy["min_size"]) * size * rng.random() + .5)
        return [generate(strategy["of"], rng, size) for _ in range(n)]
    if kind == "dicts":
        return {k: generate(s, rng, size) for k, s in strategy["fields"].items()
                if k not in strategy["optional"] or rng.random() > .3}
    if kind == "one_of":
        return generate(rng.choice(strategy["options"]), rng, size)
    if kind == "tuples":
        return [generate(s, rng, size) for s in strategy["items"]]
    if kind == "constant":
        return strategy["value"]
    if kind == "sampled_from":
        return rng.choice(strategy["values"])
    return rng.random() < .5


def conforms(strategy, value):
    kind = strategy["kind"]
    if kind == "integers":
        return isinstance(value, int) and not isinstance(value, bool) and strategy["min"] <= value <= strategy["max"]
    if kind == "decimals":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and strategy["min"] <= value <= strategy["max"]
    if kind == "text":
        return isinstance(value, str) and strategy["min_len"] <= len(value) <= strategy["max_len"]
    if kind == "lists":
        return (isinstance(value, list) and strategy["min_size"] <= len(value) <= strategy["max_size"]
                and all(conforms(strategy["of"], v) for v in value))
    if kind == "dicts":
        if not isinstance(value, dict) or set(value) - set(strategy["fields"]):
            return False
        required = set(strategy["fields"]) - set(strategy["optional"])
        return required <= set(value) and all(conforms(strategy["fields"][k], v) for k, v in value.items())
    if kind == "one_of":
        return any(conforms(o, value) for o in strategy["options"])
    if kind == "tuples":
        return (isinstance(value, list) and len(value) == len(strategy["items"])
                and all(conforms(s, v) for s, v in zip(strategy["items"], value)))
    if kind == "constant":
        return value == strategy["value"]
    if kind == "sampled_from":
        return value in strategy["values"]
    return isinstance(value, bool)


def simplest(strategy):
    kind = strategy["kind"]
    if kind == "integers":
        return min(max(0, strategy["min"]), strategy["max"])
    if kind == "decimals":
        return round(float(min(max(0, strategy["min"]), strategy["max"])), strategy["places"])
    if kind == "text":
        return strategy["alphabet"][0] * strategy["min_len"]
    if kind == "lists":
        return [simplest(strategy["of"]) for _ in range(strategy["min_size"])]
    if kind == "dicts":
        return {k: simplest(s) for k, s in strategy["fields"].items() if k not in strategy["optional"]}
    if kind == "one_of":
        return simplest(strategy["options"][0])
    if kind == "tuples":
        return [simplest(s) for s in strategy["items"]]
    if kind == "constant":
        return strategy["value"]
    if kind == "sampled_from":
        return strategy["values"][0]
    return False


def shrink(strategy, value):
    """Yield simpler conforming values, most aggressive first."""
    seen = []

    def out(candidate):
        if candidate != value and candidate not in seen and conforms(strategy, candidate):
            seen.append(candidate)
            return True
        return False
    kind = strategy["kind"]
    if kind == "integers":
        target = simplest(strategy)
        step = value - 1 if value > target else value + 1 if value < target else value
        for c in (target, target + (value - target) // 2, step,
                  abs(value) if strategy["min"] <= abs(value) <= strategy["max"] else value):
            if out(c):
                yield c
    elif kind == "decimals":
        p, target = strategy["places"], simplest(strategy)
        for c in (target, round(target + (value - target) / 2, p), float(round(value)), round(value, max(p - 1, 0))):
            if out(c):
                yield c
    elif kind == "text":
        lo, alphabet = strategy["min_len"], strategy["alphabet"]
        for c in (simplest(strategy), value[:max(lo, len(value) // 2)], value[len(value) // 2:]):
            if out(c):
                yield c
        for i in range(len(value)):
            c = value[:i] + value[i + 1:]
            if out(c):
                yield c
        for i, ch in enumerate(value):
            if ch != alphabet[0]:
                c = value[:i] + alphabet[0] + value[i + 1:]
                if out(c):
                    yield c
    elif kind == "lists":
        lo = strategy["min_size"]
        for c in (value[:lo], value[:max(lo, len(value) // 2)], value[len(value) // 2:]):
            if out(c):
                yield c
        for i in range(len(value)):
            c = value[:i] + value[i + 1:]
            if out(c):
                yield c
        for i, item in enumerate(value):
            for smaller in shrink(strategy["of"], item):
                c = value[:i] + [smaller] + value[i + 1:]
                if out(c):
                    yield c
    elif kind == "dicts":
        for key in strategy["optional"]:
            if key in value:
                c = {k: v for k, v in value.items() if k != key}
                if out(c):
                    yield c
        for key, item in value.items():
            for smaller in shrink(strategy["fields"][key], item):
                c = {**value, key: smaller}
                if out(c):
                    yield c
    elif kind == "tuples":
        for i, item in enumerate(value):
            for smaller in shrink(strategy["items"][i], item):
                c = value[:i] + [smaller] + value[i + 1:]
                if out(c):
                    yield c
    elif kind == "one_of":
        for option in strategy["options"]:
            c = simplest(option)
            if out(c):
                yield c
            if conforms(option, value):
                for smaller in shrink(option, value):
                    if out(smaller):
                        yield smaller
    elif kind == "sampled_from":
        for c in strategy["values"]:
            if strategy["values"].index(c) < strategy["values"].index(value) and out(c):
                yield c
    elif kind == "booleans":
        if value is True and out(False):
            yield False
