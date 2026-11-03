"""Equivalence workshop: explicit reference/candidate suites compared on observable effects.

Extends the existing differential oracle (Comparisons._execute, background jobs,
evidence store). It compares only the listed cases and channels; equality is
never whole-program equivalence.
"""
import base64
import difflib
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import sqlite3
import sys
import tempfile
import time

from .store import identifier, now

CHANNELS = ("exit_code", "timeout", "stdout", "stderr", "files", "db")
DEFAULT_CHANNELS = ["exit_code", "timeout", "stdout", "stderr", "files", "db"]
TEXT_CHANNELS = {"stdout", "stderr", "files"}
NORMALISERS = {"strip_trailing_spaces", "strip", "normalize_newlines", "collapse_whitespace",
               "sort_lines", "ignore_regex", "numeric_tolerance"}
DEFAULT_ENV = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
EVIDENCE_TEXT = 4000
SCOPE = ("Only the listed cases, steps and channels were compared in fresh sandboxes. "
         "Agreement is not whole-program equivalence.")
LIMIT_CASES, LIMIT_STEPS = 500, 50
SQLITE_AUX = ("-wal", "-shm", "-journal")


def _sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8", "replace")).hexdigest()


def _clip(text):
    return text if len(text) <= EVIDENCE_TEXT else text[:EVIDENCE_TEXT] + "...[truncated]"


# ----------------------------------------------------------------- validation

def _relative(path, what):
    if not isinstance(path, str) or not path.strip():
        raise ValueError(what + " needs a relative path")
    pure = Path(path)
    if pure.is_absolute() or ".." in pure.parts or path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", path):
        raise ValueError(what + " must stay inside the sandbox: " + path)
    return path.replace("\\", "/")


def _command(value, field):
    if not isinstance(value, dict):
        raise ValueError(field + " must be an object with argv")
    unknown = set(value) - {"argv", "cwd", "env", "timeout_seconds"}
    if unknown:
        raise ValueError(field + " has unknown fields: " + ", ".join(sorted(unknown)))
    argv = value.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a for a in argv):
        raise ValueError(field + ".argv must be a nonempty array of arguments")
    if value.get("cwd") is not None and not isinstance(value["cwd"], str):
        raise ValueError(field + ".cwd must be text")
    env = value.get("env", {})
    if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
        raise ValueError(field + ".env must map text to text")
    timeout = value.get("timeout_seconds", 30)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError(field + ".timeout_seconds must be positive")
    return {"argv": list(argv), "cwd": value.get("cwd"), "env": dict(env), "timeout_seconds": timeout}


def _normalisers(values, where):
    result = []
    for item in values or []:
        entry = {"name": item} if isinstance(item, str) else dict(item) if isinstance(item, dict) else None
        if entry is None or entry.get("name") not in NORMALISERS:
            raise ValueError(where + ": unknown normaliser; choose from " + ", ".join(sorted(NORMALISERS)))
        applies = entry.get("apply_to", ["stdout", "stderr"])
        if not isinstance(applies, list) or not applies or set(applies) - TEXT_CHANNELS:
            raise ValueError(where + ": apply_to is a subset of stdout, stderr, files")
        entry["apply_to"] = applies
        if entry["name"] == "ignore_regex":
            try:
                re.compile(entry.get("pattern", ""))
            except re.error as exc:
                raise ValueError(where + ": invalid regular expression: " + str(exc)) from exc
            if not entry.get("pattern"):
                raise ValueError(where + ": ignore_regex needs a pattern")
            entry.setdefault("replacement", "<IGNORED>")
        if entry["name"] == "numeric_tolerance":
            entry["abs"] = float(entry.get("abs", 0.0))
            entry["rel"] = float(entry.get("rel", 0.0))
            if entry["abs"] < 0 or entry["rel"] < 0 or (entry["abs"] == 0 and entry["rel"] == 0):
                raise ValueError(where + ": numeric_tolerance needs a positive abs or rel")
        result.append(entry)
    return result


def _files(value, where):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(where + " files map a relative path to text or {base64}")
    result = {}
    for path, content in value.items():
        _relative(path, where + " file")
        if isinstance(content, str):
            continue
        if not (isinstance(content, dict) and set(content) == {"base64"} and isinstance(content["base64"], str)):
            raise ValueError(where + " file content is text or {\"base64\": ...}")
        base64.b64decode(content["base64"], validate=True)
        result[path] = content
    return {**value}


def _db(value, where):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"path", "seed_sql"}:
        raise ValueError(where + " db is {path, seed_sql}")
    seed = value.get("seed_sql", "")
    if isinstance(seed, list):
        if any(not isinstance(s, str) for s in seed):
            raise ValueError(where + " seed_sql statements must be text")
        seed = ";\n".join(seed)
    if not isinstance(seed, str):
        raise ValueError(where + " seed_sql must be text")
    return {"path": _relative(value.get("path", "app.db"), where + " db"), "seed_sql": seed}


def _step(value, where):
    if not isinstance(value, dict) or set(value) - {"args", "stdin", "files", "env", "name"}:
        raise ValueError(where + " is {args, stdin, files, env}")
    args = value.get("args", [])
    if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
        raise ValueError(where + " args must be an array of text")
    if not isinstance(value.get("stdin", ""), str):
        raise ValueError(where + " stdin must be text")
    return {"args": list(args), "stdin": value.get("stdin", ""), "files": _files(value.get("files"), where),
            "env": dict(value.get("env", {})), **({"name": str(value["name"])} if value.get("name") else {})}


def validate_case(value, index=0):
    if not isinstance(value, dict):
        raise ValueError("A case is an object")
    allowed = {"name", "stdin", "args", "files", "db", "steps", "channels", "normalisers", "ordered_tables"}
    if set(value) - allowed:
        raise ValueError("Case has unknown fields: " + ", ".join(sorted(set(value) - allowed)))
    name = str(value.get("name") or "case-" + str(index + 1))
    where = "case " + name
    if "steps" in value and ("stdin" in value or "args" in value):
        raise ValueError(where + ": use either steps or top-level args/stdin, not both")
    steps = value.get("steps")
    if steps is None:
        steps = [{"args": value.get("args", []), "stdin": value.get("stdin", "")}]
    if not isinstance(steps, list) or not steps or len(steps) > LIMIT_STEPS:
        raise ValueError(where + ": steps is a nonempty array of at most " + str(LIMIT_STEPS))
    case = {"name": name, "steps": [_step(s, where + " step " + str(i + 1)) for i, s in enumerate(steps)],
            "files": _files(value.get("files"), where), "db": _db(value.get("db"), where),
            "ordered_tables": list(value.get("ordered_tables", []))}
    if value.get("channels") is not None:
        case["channels"] = _channels(value["channels"], where)
    case["normalisers"] = _normalisers(value.get("normalisers"), where)
    return case


def _channels(value, where):
    if not isinstance(value, list) or not value or set(value) - set(CHANNELS):
        raise ValueError(where + ": channels are a subset of " + ", ".join(CHANNELS))
    return list(dict.fromkeys(value))


GENERATOR_KINDS = ("integers", "decimals", "strings", "permutations")


def validate_suite(value):
    if not isinstance(value, dict):
        raise ValueError("A suite is a JSON object")
    allowed = {"reference", "candidate", "cases", "generators", "channels", "normalisers", "ignore_paths",
               "ordered_tables", "authorized_deviations", "description"}
    if set(value) - allowed:
        raise ValueError("Suite has unknown fields: " + ", ".join(sorted(set(value) - allowed)))
    suite = {"reference": _command(value.get("reference"), "reference"),
             "candidate": _command(value.get("candidate"), "candidate"),
             "channels": _channels(value.get("channels", DEFAULT_CHANNELS), "suite"),
             "normalisers": _normalisers(value.get("normalisers"), "suite"),
             "ignore_paths": [str(p) for p in value.get("ignore_paths", [])],
             "ordered_tables": list(value.get("ordered_tables", [])),
             "description": str(value.get("description", ""))}
    cases = value.get("cases", [])
    if not isinstance(cases, list) or len(cases) > LIMIT_CASES:
        raise ValueError("cases is an array of at most " + str(LIMIT_CASES))
    suite["cases"] = [validate_case(c, i) for i, c in enumerate(cases)]
    names = [c["name"] for c in suite["cases"]]
    if len(set(names)) != len(names):
        raise ValueError("Case names must be distinct")
    generators = value.get("generators", [])
    if not isinstance(generators, list):
        raise ValueError("generators is an array")
    suite["generators"] = []
    for i, generator in enumerate(generators):
        if not isinstance(generator, dict) or generator.get("kind") not in GENERATOR_KINDS:
            raise ValueError("generator " + str(i + 1) + ": kind is one of " + ", ".join(GENERATOR_KINDS))
        if set(generator) - {"kind", "count", "seed", "template", "items", "separator"}:
            raise ValueError("generator " + str(i + 1) + " has unknown fields")
        count = generator.get("count", 10)
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 200:
            raise ValueError("generator count is an integer from 1 to 200")
        seed = generator.get("seed", 0)
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError("generator seed must be an integer")
        template = generator.get("template")
        if not isinstance(template, dict):
            raise ValueError("generator needs a case template using {value}")
        validate_case({**template, "name": "template"})
        if generator["kind"] == "permutations" and (not isinstance(generator.get("items"), list) or len(generator["items"]) < 2
                                                    or any(not isinstance(x, str) for x in generator["items"])):
            raise ValueError("permutations need an items array of at least two text items")
        suite["generators"].append({"kind": generator["kind"], "count": count, "seed": seed, "template": template,
                                    **({"items": generator["items"]} if "items" in generator else {}),
                                    "separator": generator.get("separator", ",")})
    deviations = value.get("authorized_deviations", [])
    if not isinstance(deviations, list):
        raise ValueError("authorized_deviations is an array")
    suite["authorized_deviations"] = []
    for i, dev in enumerate(deviations):
        if not isinstance(dev, dict) or set(dev) - {"case", "channel", "expected", "reason", "step", "path", "expected_candidate"}:
            raise ValueError("authorized deviation " + str(i + 1) + " is {case, channel, expected, reason, step, path, expected_candidate}")
        if not str(dev.get("reason", "")).strip() or not str(dev.get("expected", "")).strip():
            raise ValueError("An authorized deviation needs an expected behaviour and a reason")
        if dev.get("channel", "*") != "*" and dev["channel"] not in CHANNELS:
            raise ValueError("authorized deviation channel is * or one of " + ", ".join(CHANNELS))
        expected = dev.get("expected_candidate")
        if expected is not None:
            if not isinstance(expected, dict) or set(expected) - {"equals", "regex"} or len(expected) != 1:
                raise ValueError("expected_candidate is {equals} or {regex}")
            if "regex" in expected:
                re.compile(expected["regex"])
        suite["authorized_deviations"].append({**dev, "case": dev.get("case", "*"), "channel": dev.get("channel", "*")})
    if not suite["cases"] and not suite["generators"]:
        raise ValueError("A suite needs cases or generators")
    return suite


# ------------------------------------------------------------------ generation

INT_BOUNDS = [0, 1, -1, 2, -2, 9, 10, 127, 128, -128, 255, 256, 2 ** 15 - 1, 2 ** 15, 2 ** 31 - 1, 2 ** 31,
              -2 ** 31, 2 ** 63 - 1, -2 ** 63, 2 ** 63]
DECIMAL_TIES = ["0.5", "1.5", "2.5", "-0.5", "-1.5", "-2.5", "2.675", "1.005", "0.125", "0.375", "0.1", "0.2",
                "0.30000000000000004", "1e-7", "100.5", "0.045"]
STRING_EDGES = ["", " ", "a", "A", "é", "é", "ñandú", "日本語", "\U0001f44d", "a b", "  lead",
                "trail  ", "x\ty", "line\nbreak", "z", "Z", "ß", "i̇"]
ALPHABET = "abcXYZ019 -_éñ日\U0001f600"


def generate_values(generator):
    rng = random.Random(generator["seed"])
    kind, count = generator["kind"], generator["count"]
    if kind == "integers":
        pool = [str(v) for v in INT_BOUNDS]
        while len(pool) < count:
            pool.append(str(rng.randint(-10 ** rng.randint(1, 12), 10 ** rng.randint(1, 12))))
    elif kind == "decimals":
        pool = list(DECIMAL_TIES)
        while len(pool) < count:
            whole = rng.randint(-50, 50)
            digits = rng.randint(1, 4)
            frac = rng.randint(0, 10 ** digits - 1)
            pool.append(("-" if whole < 0 else "") + str(abs(whole)) + "." + str(frac).zfill(digits)
                        if rng.random() < .5 else str(whole) + ".5")
    elif kind == "strings":
        pool = list(STRING_EDGES)
        while len(pool) < count:
            pool.append("".join(rng.choice(ALPHABET) for _ in range(rng.randint(1, 10))))
    else:
        items, pool, seen = generator["items"], [], set()
        base = list(items)
        for ordering in (base, base[::-1], sorted(base)):
            if tuple(ordering) not in seen:
                seen.add(tuple(ordering)); pool.append(generator["separator"].join(ordering))
        attempts = 0
        while len(pool) < count and attempts < count * 20:
            attempts += 1
            order = base[:]; rng.shuffle(order)
            if tuple(order) not in seen:
                seen.add(tuple(order)); pool.append(generator["separator"].join(order))
    return pool[:count]


def _substitute(template, value, index):
    def walk(node):
        if isinstance(node, str):
            return node.replace("{value}", value).replace("{index}", str(index))
        if isinstance(node, list):
            return [walk(n) for n in node]
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return node
    return walk(template)


def expand_generators(suite):
    cases = []
    for g, generator in enumerate(suite["generators"]):
        for i, value in enumerate(generate_values(generator)):
            case = validate_case({**_substitute(generator["template"], value, i),
                                  "name": "gen%d:%s:%d" % (g + 1, generator["kind"], i)})
            case["generated"] = {"generator": g, "kind": generator["kind"], "value": value, "index": i}
            cases.append(case)
    return cases


def shrink_candidates(kind, value, separator=","):
    """Simpler values first. Each candidate is only a proposal: the caller re-runs both programs."""
    out = []
    def add(v):
        if v != value and v not in out:
            out.append(v)
    if kind == "permutations":
        items = value.split(separator) if value else []
        for i in range(len(items)):
            if len(items) > 2:
                add(separator.join(items[:i] + items[i + 1:]))
        add(separator.join(sorted(items)))
        for i in range(len(items) - 1):
            swapped = items[:]; swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
            add(separator.join(swapped))
        return out
    add("")
    if kind in {"integers", "decimals"}:
        add("0"); add("1")
        try:
            if kind == "integers":
                number = int(value)
                add(str(abs(number))); add(str(number // 2)); add(str(int(number / 10)))
        except ValueError:
            pass
    if len(value) > 1:
        add(value[: len(value) // 2]); add(value[len(value) // 2:])
    for i in range(len(value)):
        add(value[:i] + value[i + 1:])
    for i, ch in enumerate(value):
        simple = "0" if ch.isdigit() else "a"
        if ch != simple:
            add(value[:i] + simple + value[i + 1:])
        if ch.isdigit() and ch not in "01":
            add(value[:i] + str(int(ch) // 2) + value[i + 1:])
    return out


# ---------------------------------------------------------------- normalisation

NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def apply_normalisers(text, normalisers, channel):
    tol = None
    for n in normalisers:
        if channel not in n["apply_to"]:
            continue
        name = n["name"]
        if name == "strip_trailing_spaces":
            text = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
        elif name == "strip":
            text = text.strip()
        elif name == "normalize_newlines":
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        elif name == "collapse_whitespace":
            text = re.sub(r"\s+", " ", text).strip()
        elif name == "sort_lines":
            text = "\n".join(sorted(text.split("\n")))
        elif name == "ignore_regex":
            text = re.sub(n["pattern"], n["replacement"], text)
        elif name == "numeric_tolerance":
            tol = n
    return text, tol


def texts_equal(left, right, normalisers, channel):
    """Returns (equal, normalised_left, normalised_right, used_normalisers_names)."""
    a, tol = apply_normalisers(left, normalisers, channel)
    b, _ = apply_normalisers(right, normalisers, channel)
    if a == b:
        return True, a, b
    if tol:
        sa, sb = NUMBER.sub("#", a), NUMBER.sub("#", b)
        na, nb = NUMBER.findall(a), NUMBER.findall(b)
        if sa == sb and len(na) == len(nb) and all(
                math.isclose(float(x), float(y), rel_tol=tol["rel"], abs_tol=tol["abs"]) for x, y in zip(na, nb)):
            return True, a, b
    return False, a, b


def text_diff(left, right):
    a, b = left.split("\n"), right.split("\n")
    lines = list(difflib.unified_diff(a, b, "reference", "candidate", n=0, lineterm=""))
    if len(lines) > 40:
        lines = lines[:40] + ["...[diff truncated]"]
    return "\n".join(lines)


# --------------------------------------------------------------------- sandbox

def _place(sandbox, files):
    for rel, content in (files or {}).items():
        target = sandbox / _relative(rel, "file")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(content["base64"]) if isinstance(content, dict) else content.encode("utf-8"))


def _seed(sandbox, db):
    if not db:
        return
    path = sandbox / db["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        if db["seed_sql"].strip():
            connection.executescript(db["seed_sql"])
        connection.commit()
    finally:
        connection.close()


def _snapshot_files(sandbox, ignore, db_path):
    state = {}
    skip = set()
    if db_path:
        skip = {db_path, *(db_path + s for s in SQLITE_AUX)}
    for path in sorted(sandbox.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(sandbox).as_posix()
        if rel in skip or any(fnmatch.fnmatch(rel, pattern) for pattern in ignore):
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8") if len(raw) <= 65536 else None
        except UnicodeDecodeError:
            text = None
        state[rel] = {"sha256": _sha(raw), "size": len(raw), "text": text}
    return state


def _file_effects(before, after):
    effects = {}
    for rel in sorted(set(before) | set(after)):
        if rel not in before:
            effects[rel] = {"op": "created", **after[rel]}
        elif rel not in after:
            effects[rel] = {"op": "deleted", "sha256": None, "size": 0, "text": None}
        elif before[rel]["sha256"] != after[rel]["sha256"]:
            effects[rel] = {"op": "modified", **after[rel]}
    return effects


def _jsonable(value):
    if isinstance(value, bytes):
        return {"hex": value.hex()}
    return value


def snapshot_db(sandbox, db):
    if not db:
        return None
    path = sandbox / db["path"]
    if not path.is_file():
        return {"present": False}
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "copy.db"
        shutil.copyfile(path, copy)
        for suffix in SQLITE_AUX[:1]:
            if Path(str(path) + suffix).exists():
                shutil.copyfile(str(path) + suffix, str(copy) + suffix)
        connection = sqlite3.connect(copy)
        try:
            schema = [list(r) for r in connection.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
            tables = {}
            for kind, name, _, _ in schema:
                if kind != "table":
                    continue
                quoted = '"' + name.replace('"', '""') + '"'
                info = list(connection.execute("PRAGMA table_info(" + quoted + ")"))
                columns = [r[1] for r in info]
                pk = [r[1] for r in sorted((r for r in info if r[5]), key=lambda r: r[5])]
                order = "" if "WITHOUT ROWID" in schema_sql(schema, name) else " ORDER BY rowid"
                rows = [[_jsonable(v) for v in row] for row in connection.execute("SELECT * FROM " + quoted + order)]
                tables[name] = {"columns": columns, "pk": pk, "rows": rows}
        except sqlite3.DatabaseError as exc:
            return {"present": True, "error": str(exc)}
        finally:
            connection.close()
    return {"present": True, "schema": schema, "tables": tables}


def schema_sql(schema, name):
    for kind, n, _, sql in schema:
        if n == name and kind == "table":
            return (sql or "").upper()
    return ""


def db_hash(snapshot):
    return _sha(json.dumps(snapshot, sort_keys=True, ensure_ascii=False)) if snapshot else None


def _canon(row):
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def compare_db(ref, cand, ordered):
    """Disagreements as dicts {path, kind, reference, candidate}."""
    if ref is None and cand is None:
        return []
    found = []
    if ref.get("present") != cand.get("present") or ref.get("error") != cand.get("error"):
        return [{"path": "(database)", "kind": "presence", "reference": _clip(json.dumps(ref)), "candidate": _clip(json.dumps(cand))}]
    if not ref.get("present") or ref.get("error"):
        return []
    rs = {(k, n): (t, s) for k, n, t, s in ref["schema"]}
    cs = {(k, n): (t, s) for k, n, t, s in cand["schema"]}
    for key in sorted(set(rs) | set(cs)):
        if rs.get(key) != cs.get(key):
            found.append({"path": key[1], "kind": "schema", "reference": rs.get(key), "candidate": cs.get(key),
                          "diff": text_diff((rs.get(key) or ("", ""))[1] or "<absent>", (cs.get(key) or ("", ""))[1] or "<absent>")})
    for table in sorted(set(ref["tables"]) & set(cand["tables"])):
        a, b = ref["tables"][table], cand["tables"][table]
        if a["columns"] != b["columns"]:
            continue
        keep_order = "*" in ordered or table in ordered
        arows, brows = a["rows"], b["rows"]
        if keep_order:
            if arows != brows:
                for position in range(max(len(arows), len(brows))):
                    left = arows[position] if position < len(arows) else None
                    right = brows[position] if position < len(brows) else None
                    if left != right:
                        found.append({"path": table, "kind": "row_order", "row": position, "reference": left, "candidate": right})
                        break
            continue
        pk = [a["columns"].index(c) for c in a["pk"]]
        if pk:
            amap = {_canon([r[i] for i in pk]): r for r in arows}
            bmap = {_canon([r[i] for i in pk]): r for r in brows}
            for key in sorted(set(amap) | set(bmap)):
                if key not in bmap:
                    found.append({"path": table, "kind": "row_missing", "key": json.loads(key), "reference": amap[key], "candidate": None})
                elif key not in amap:
                    found.append({"path": table, "kind": "row_extra", "key": json.loads(key), "reference": None, "candidate": bmap[key]})
                elif amap[key] != bmap[key]:
                    cols = [c for c, x, y in zip(a["columns"], amap[key], bmap[key]) if x != y]
                    found.append({"path": table, "kind": "row_changed", "key": json.loads(key), "columns": cols,
                                  "reference": amap[key], "candidate": bmap[key]})
        else:
            from collections import Counter
            ac, bc = Counter(_canon(r) for r in arows), Counter(_canon(r) for r in brows)
            for row in sorted((ac - bc).elements()):
                found.append({"path": table, "kind": "row_missing", "reference": json.loads(row), "candidate": None})
            for row in sorted((bc - ac).elements()):
                found.append({"path": table, "kind": "row_extra", "reference": None, "candidate": json.loads(row)})
    return found


# --------------------------------------------------------------------- engine

class Equivalence:
    def __init__(self, manager):
        self.manager, self.store = manager, manager.store
        with self.store.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS equivalence_suites (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL, suite TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL
            );
            """)

    # ---- suites
    def save_suite(self, project_id, name, suite, suite_id=""):
        self.store.project(project_id)
        validate_suite(suite)
        key = suite_id or identifier()
        with self.store.db() as db:
            previous = db.execute("SELECT project_id,revision FROM equivalence_suites WHERE id=?", (key,)).fetchone()
            if previous is not None and previous[0] != project_id:
                raise ValueError("Suite belongs to another project")
            revision = (previous[1] if previous else 0) + 1
            db.execute("INSERT OR REPLACE INTO equivalence_suites VALUES (?,?,?,?,?,?)",
                       (key, project_id, name.strip() or "Equivalence suite", json.dumps(suite, ensure_ascii=False),
                        revision, now()))
        return self.read_suite(project_id, key)

    def read_suite(self, project_id, suite_id=""):
        self.store.project(project_id)
        with self.store.db() as db:
            if suite_id:
                row = db.execute("SELECT * FROM equivalence_suites WHERE id=? AND project_id=?", (suite_id, project_id)).fetchone()
                if row is None:
                    raise LookupError("Suite not found in this project")
                rows = [row]
            else:
                rows = db.execute("SELECT * FROM equivalence_suites WHERE project_id=? ORDER BY rowid", (project_id,)).fetchall()
        suites = [{"id": r["id"], "name": r["name"], "revision": r["revision"], "updated_at": r["updated_at"],
                   "suite": json.loads(r["suite"])} for r in rows]
        return suites[0] if suite_id else {"suites": [{k: s[k] for k in ("id", "name", "revision", "updated_at")}
                                                      | {"cases": len(s["suite"].get("cases", [])),
                                                         "generators": len(s["suite"].get("generators", []))} for s in suites]}

    # ---- run
    def start(self, project_id, suite_id="", suite=None, strength=True, shrink=True, shrink_budget=100):
        self.store.project(project_id)
        if bool(suite_id) == bool(suite):
            raise ValueError("Give either suite_id or an inline suite")
        revision = None
        if suite_id:
            saved = self.read_suite(project_id, suite_id)
            suite, revision = saved["suite"], saved["revision"]
        suite = validate_suite(suite)
        if not isinstance(shrink_budget, int) or isinstance(shrink_budget, bool) or not 1 <= shrink_budget <= 1000:
            raise ValueError("shrink_budget is an integer from 1 to 1000")
        job_id = identifier()
        result = {"kind": "equivalence_run", "suite_id": suite_id or None, "suite_revision": revision, "suite": suite,
                  "suite_sha256": _sha(json.dumps(suite, sort_keys=True, ensure_ascii=False)),
                  "options": {"strength": bool(strength), "shrink": bool(shrink), "shrink_budget": shrink_budget},
                  "scope": SCOPE, "cases": [], "summary": {}}
        self.store.save_job(project_id, job_id, "queued", result)
        self.manager.pool.submit(self._run, project_id, job_id, result, suite)
        return self.store.job(job_id)

    def _check(self, job_id):
        with self.manager.lock:
            if job_id in self.manager.cancelled:
                raise InterruptedError("Equivalence run cancelled")

    @staticmethod
    def _subst(text, sandbox):
        return text.replace("{sandbox}", str(sandbox))

    def observe(self, job_id, command, case, suite, argv=None):
        """Run every step of one case in a fresh sandbox at a fixed path; returns observation with full data."""
        self._check(job_id)
        root = Path(tempfile.mkdtemp(prefix="theseus-equiv-"))
        sandbox = root / "sandbox"
        try:
            sandbox.mkdir()
            _place(sandbox, case["files"])
            _seed(sandbox, case["db"])
            db_path = case["db"]["path"] if case["db"] else None
            before = _snapshot_files(sandbox, suite["ignore_paths"], db_path)
            steps = []
            for step in case["steps"]:
                self._check(job_id)
                _place(sandbox, step["files"])
                if step["files"]:
                    before = {**before, **{k: v for k, v in _snapshot_files(sandbox, suite["ignore_paths"], db_path).items()
                                           if k in step["files"]}}
                cwd = command.get("cwd")
                if cwd is None:
                    cwd = str(sandbox)
                else:
                    cwd = self._subst(cwd, sandbox)
                    if not Path(cwd).is_absolute():
                        cwd = str(sandbox / _relative(cwd, "cwd"))
                        Path(cwd).mkdir(parents=True, exist_ok=True)
                base = [self._subst(a, sandbox) for a in (argv or command["argv"])]
                env = {**DEFAULT_ENV, "THESEUS_SANDBOX": str(sandbox),
                       **{k: self._subst(v, sandbox) for k, v in {**command["env"], **step["env"]}.items()}}
                run = self.manager._execute(job_id, base + [self._subst(a, sandbox) for a in step["args"]], {
                    "cwd": cwd, "env": env, "stdin": step["stdin"], "timeout_seconds": command["timeout_seconds"]})
                after = _snapshot_files(sandbox, suite["ignore_paths"], db_path)
                effects = _file_effects(before, after)
                before = after
                db_state = snapshot_db(sandbox, case["db"])
                steps.append({"exit_code": run["exit_code"], "timed_out": run["timed_out"], "stdout": run["stdout"],
                              "stderr": run["stderr"], "files": effects, "db": db_state, "duration_seconds": run["duration_seconds"]})
            return {"steps": steps}
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def _covering(self, suite, case_name, step, channel, path, candidate_value):
        for dev in suite["authorized_deviations"]:
            if not fnmatch.fnmatchcase(case_name, dev["case"]) or dev["channel"] not in {"*", channel}:
                continue
            if dev.get("step") not in (None, step + 1):
                continue
            if dev.get("path") not in (None, path):
                continue
            expected = dev.get("expected_candidate")
            if expected is None:
                return {"deviation": dev, "expectation_checked": False}
            text = candidate_value if isinstance(candidate_value, str) else json.dumps(candidate_value, ensure_ascii=False)
            ok = text == expected["equals"] if "equals" in expected else re.search(expected["regex"], text) is not None
            if ok:
                return {"deviation": dev, "expectation_checked": True}
            return {"deviation": dev, "expectation_checked": True, "violated": True}
        return None

    def compare(self, suite, case, ref, cand):
        channels = case.get("channels", suite["channels"])
        norms = suite["normalisers"] + case["normalisers"]
        ordered = list(suite["ordered_tables"]) + list(case["ordered_tables"])
        found, matched = [], []

        def record(step, channel, path, kind, left, right, diff="", extra=None):
            covering = self._covering(suite, case["name"], step, channel, path, right if isinstance(right, str) else right)
            entry = {"case": case["name"], "step": step + 1, "channel": channel, "path": path, "kind": kind,
                     "reference": left if not isinstance(left, str) else _clip(left),
                     "candidate": right if not isinstance(right, str) else _clip(right),
                     "diff": diff, "status": "disagreement"}
            if extra:
                entry.update(extra)
            if covering and not covering.get("violated"):
                entry["status"] = "authorized_deviation"
                entry["authorization"] = {"expected": covering["deviation"]["expected"], "reason": covering["deviation"]["reason"],
                                          "expectation_checked": covering["expectation_checked"]}
            elif covering:
                entry["authorization_violated"] = {"expected": covering["deviation"]["expected"],
                                                   "reason": covering["deviation"]["reason"],
                                                   "note": "Candidate behaviour differs from the authorized behaviour"}
            found.append(entry)

        for i, (a, b) in enumerate(zip(ref["steps"], cand["steps"])):
            if "exit_code" in channels and a["exit_code"] != b["exit_code"] and not (a["timed_out"] or b["timed_out"]):
                record(i, "exit_code", None, "value", a["exit_code"], b["exit_code"], "reference %s / candidate %s" % (a["exit_code"], b["exit_code"]))
            if "timeout" in channels and a["timed_out"] != b["timed_out"]:
                record(i, "timeout", None, "value", a["timed_out"], b["timed_out"], "timeout expired on " + ("reference" if a["timed_out"] else "candidate"))
            for channel in ("stdout", "stderr"):
                if channel not in channels:
                    continue
                equal, na, nb = texts_equal(a[channel], b[channel], norms, channel)
                if equal and a[channel] != b[channel]:
                    matched.append({"step": i + 1, "channel": channel})
                if not equal:
                    record(i, channel, None, "text", a[channel], b[channel], text_diff(na, nb))
            if "files" in channels:
                for rel in sorted(set(a["files"]) | set(b["files"])):
                    fa, fb = a["files"].get(rel), b["files"].get(rel)
                    if fa is None or fb is None or fa["op"] != fb["op"]:
                        record(i, "files", rel, "effect", fa and {"op": fa["op"], "sha256": fa["sha256"]},
                               fb and {"op": fb["op"], "sha256": fb["sha256"]},
                               "reference %s / candidate %s" % (fa["op"] if fa else "untouched", fb["op"] if fb else "untouched"))
                        continue
                    if fa["sha256"] == fb["sha256"]:
                        continue
                    if fa["text"] is not None and fb["text"] is not None:
                        equal, na, nb = texts_equal(fa["text"], fb["text"], norms, "files")
                        if equal:
                            matched.append({"step": i + 1, "channel": "files", "path": rel})
                            continue
                        record(i, "files", rel, "content", {"sha256": fa["sha256"], "text": _clip(fa["text"])},
                               {"sha256": fb["sha256"], "text": _clip(fb["text"])}, text_diff(na, nb))
                    else:
                        record(i, "files", rel, "content", {"sha256": fa["sha256"], "size": fa["size"]},
                               {"sha256": fb["sha256"], "size": fb["size"]}, "binary or large content differs by hash")
            if "db" in channels and case["db"]:
                for item in compare_db(a["db"], b["db"], ordered):
                    path = item.pop("path")
                    kind = item.pop("kind")
                    diff = item.pop("diff", "")
                    left, right = item.pop("reference"), item.pop("candidate")
                    record(i, "db", path, kind, left, right, diff or ("reference %s / candidate %s" % (_canon(left), _canon(right))), item)
        return found, matched

    @staticmethod
    def _evidence(observation):
        steps = []
        for s in observation["steps"]:
            steps.append({"exit_code": s["exit_code"], "timed_out": s["timed_out"],
                          "stdout": _clip(s["stdout"]), "stdout_sha256": _sha(s["stdout"]),
                          "stderr": _clip(s["stderr"]), "stderr_sha256": _sha(s["stderr"]),
                          "files": {p: {"op": f["op"], "sha256": f["sha256"], "size": f["size"],
                                        "text": _clip(f["text"]) if f["text"] is not None else None} for p, f in s["files"].items()},
                          "db_sha256": db_hash(s["db"]),
                          "db_tables": {t: len(v["rows"]) for t, v in (s["db"] or {}).get("tables", {}).items()}})
        return {"steps": steps}

    def run_case(self, job_id, suite, case, reference=None):
        ref = reference or self.observe(job_id, suite["reference"], case, suite)
        cand = self.observe(job_id, suite["candidate"], case, suite)
        found, matched = self.compare(suite, case, ref, cand)
        invalid = [i + 1 for i, s in enumerate(ref["steps"]) if s["timed_out"]]
        return ref, cand, found, matched, invalid

    @staticmethod
    def verdict(found, invalid):
        if invalid:
            return "invalid"
        if any(d["status"] == "disagreement" for d in found):
            return "different"
        return "authorized_deviation" if found else "equivalent"

    def _case_result(self, suite, case, ref, cand, found, matched, invalid):
        real = [d for d in found if d["status"] == "disagreement"]
        first = real[0] if real else (found[0] if found else None)
        norms = suite["normalisers"] + case["normalisers"]
        return {"name": case["name"], "verdict": self.verdict(found, invalid),
                "invalid_reference_timeout_steps": invalid,
                "first_disagreement": first, "disagreements": found,
                "normalisers": [{k: v for k, v in n.items()} for n in norms],
                "equal_only_after_normalisation": matched,
                **({"generated": case["generated"]} if "generated" in case else {}),
                "reference": self._evidence(ref), "candidate": self._evidence(cand)}

    def _shrink(self, job_id, suite, case, budget, case_first):
        generated = case["generated"]
        generator = suite["generators"][generated["generator"]]
        kind, separator = generated["kind"], generator.get("separator", ",")
        def build(value):
            built = validate_case({**_substitute(generator["template"], value, generated["index"]), "name": case["name"]})
            built["generated"] = {**generated, "value": value}
            return built
        current, runs, trail = generated["value"], 0, []
        original = next(d for d in case_first if d["status"] == "disagreement")
        same_failure = lambda real: [d for d in real if d["channel"] == original["channel"]]
        progress = True
        while progress and runs < budget:
            progress = False
            for value in shrink_candidates(kind, current, separator):
                if runs >= budget:
                    break
                runs += 1
                trial = build(value)
                _, _, found, _, invalid = self.run_case(job_id, suite, trial)
                real = same_failure([d for d in found if d["status"] == "disagreement"])
                if real and not invalid:
                    current = value
                    trail.append({"value": value, "confirmed_by_rerun": True, "first_disagreement": real[0]})
                    progress = True
                    break
        final = build(current)
        _, _, found, _, invalid = self.run_case(job_id, suite, final)
        real = same_failure([d for d in found if d["status"] == "disagreement"])
        return {"original_value": generated["value"], "minimal_value": current, "reruns": runs + 1,
                "budget_exhausted": runs >= budget, "reexecuted_and_confirmed": bool(real) and not invalid,
                "first_disagreement": real[0] if real else None, "steps": trail,
                "preserves_channel": original["channel"],
                "note": "Each accepted reduction was confirmed by running both programs again on the same failing channel; the minimum is local, not global."}

    def _strength(self, job_id, suite, observations):
        """Constant candidates must be rejected, otherwise the suite cannot distinguish them."""
        first = observations[0][1]["steps"][0]
        scratch = Path(tempfile.mkdtemp(prefix="theseus-equiv-const-"))
        try:
            echo = scratch / "echo_first.py"
            data = scratch / "first.json"
            data.write_text(json.dumps({"stdout": first["stdout"], "stderr": first["stderr"], "exit_code": first["exit_code"]}), encoding="utf-8")
            echo.write_text("import json,sys\nd=json.load(open(sys.argv[1],encoding='utf-8'))\n"
                            "sys.stdout.write(d['stdout']);sys.stderr.write(d['stderr']);sys.exit(d['exit_code'])\n", encoding="utf-8")
            silent = scratch / "silent.py"
            silent.write_text("import sys\nsys.stdin.read()\n", encoding="utf-8")
            mutants = [("constant: echoes the reference output of the first case", [sys.executable, str(echo), str(data)]),
                       ("constant: prints nothing and exits 0", [sys.executable, str(silent)])]
            report = []
            for name, argv in mutants:
                rejected_by = None
                for case, ref in observations:
                    cand = self.observe(job_id, suite["candidate"], case, suite, argv=argv)
                    found, _ = self.compare(suite, case, ref, cand)
                    real = [d for d in found if d["status"] == "disagreement"]
                    if real:
                        rejected_by = {"case": case["name"], "step": real[0]["step"], "channel": real[0]["channel"]}
                        break
                report.append({"mutant": name, "rejected": rejected_by is not None, "rejected_by": rejected_by})
            survivors = [m["mutant"] for m in report if not m["rejected"]]
            return {"mutants": report, "weak": bool(survivors),
                    "message": ("These cases cannot distinguish a constant program: " + "; ".join(survivors)) if survivors
                    else "Every constant program was rejected by at least one case."}
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def _run(self, project_id, job_id, result, suite):
        try:
            self.store.save_job(project_id, job_id, "running", result)
            options = result["options"]
            cases = [*suite["cases"], *expand_generators(suite)]
            result["generated_case_count"] = len(cases) - len(suite["cases"])
            observations = []
            for case in cases:
                self._check(job_id)
                result["running_case"] = case["name"]
                ref, cand, found, matched, invalid = self.run_case(job_id, suite, case)
                observations.append((case, ref))
                entry = self._case_result(suite, case, ref, cand, found, matched, invalid)
                if (options["shrink"] and "generated" in case and entry["verdict"] == "different"):
                    entry["shrunk"] = self._shrink(job_id, suite, case, options["shrink_budget"], entry["disagreements"])
                result["cases"].append(entry)
                self.store.save_job(project_id, job_id, "running", result)
            result.pop("running_case", None)
            if options["strength"] and observations:
                result["strength"] = self._strength(job_id, suite, observations)
            verdicts = [c["verdict"] for c in result["cases"]]
            overall = ("invalid" if "invalid" in verdicts else "different" if "different" in verdicts
                       else "authorized_deviation_only" if "authorized_deviation" in verdicts else "agrees_on_listed_cases")
            strength = result.get("strength")
            result["summary"] = {
                "verdict": overall, "cases": len(verdicts),
                **{v: verdicts.count(v) for v in ("equivalent", "authorized_deviation", "different", "invalid")},
                "authorized_deviations": sum(1 for c in result["cases"] for d in c["disagreements"] if d["status"] == "authorized_deviation"),
                "weak_suite": None if strength is None else strength["weak"],
                "first_disagreement": next(({"case": c["name"], **c["first_disagreement"]} for c in result["cases"]
                                            if c["verdict"] == "different"), None),
                "scope": SCOPE}
            with self.manager.lock:
                stopped = job_id in self.manager.cancelled
            self.store.save_job(project_id, job_id, "cancelled" if stopped else "finished", result)
        except InterruptedError as exc:
            result["message"] = str(exc)
            self.store.save_job(project_id, job_id, "cancelled", result)
        except Exception as exc:
            result["error"] = type(exc).__name__ + ": " + str(exc)
            self.store.save_job(project_id, job_id, "failed", result)
        finally:
            with self.manager.lock:
                self.manager.cancelled.discard(job_id)
