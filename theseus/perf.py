"""Causal performance workshop: repeated, controlled profiling and statistically checked before/after comparison.

A command (or an HTTP request against a server the workshop starts) is run under
the same inputs after warm-up. Python commands are profiled with cProfile; the
profile's self time is attributed to categories (database, serialization,
rendering, network, model/inference calls, waiting, user CPU, other) and
summarised across runs with median and p90. Comparisons interleave the two
versions, test differences with an exact/normal Mann-Whitney U test plus a
bootstrap interval, and refuse to call a speed-up a success when the outputs
differ (checked with the equivalence runner).

Profiling slows a run down, so category *shares* come from profiled runs while
wall-clock numbers come from separate unprofiled runs.
"""
import fnmatch
import hashlib
import http.client
import itertools
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time

from .equivalence import (DEFAULT_ENV, Equivalence, _place, _relative, _seed, texts_equal, validate_case, validate_suite,
                          _normalisers)
from .store import identifier, now

CATEGORIES = ("database", "serialization", "rendering", "network", "model", "cpu_user", "waiting", "other")
PROFILE_NOTE = ("Shares are self time under cProfile (which inflates call-heavy code); they locate the dominant cost, they are not "
                "wall-clock seconds. Wall-clock figures come from separate unprofiled runs.")
MAX_RUNS = 50
COPY_SKIP = {".git", ".hg", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache"}

RUNNER = r'''
import cProfile, json, os, pstats, runpy, sys, threading, time, traceback
OUT = sys.argv[1]
mode = sys.argv[2]
HERE = os.path.abspath(__file__)

def dump(prof, path, code, run_seconds):
    stats = pstats.Stats(prof).stats
    rows = []
    for (f, l, n), (cc, nc, tt, ct, callers) in stats.items():
        if f == HERE:
            continue
        cl = [[cf, cln, cn, round(v[2], 7)] for (cf, cln, cn), v in callers.items() if cf != HERE]
        if not cl and callers:
            continue
        if tt < 1e-6 and not cl:
            continue
        rows.append([f, l, n, nc, round(tt, 7), round(ct, 7), cl])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"exit_code": code, "run_seconds": run_seconds, "functions": rows}, fh)
    os.replace(tmp, path)

def target(rest):
    if rest[0] == "-m":
        sys.argv = [rest[1]] + rest[2:]
        return lambda: runpy.run_module(rest[1], run_name="__main__", alter_sys=True)
    sys.argv = list(rest)
    sys.path[0] = os.path.dirname(os.path.abspath(rest[0]))
    return lambda: runpy.run_path(rest[0], run_name="__main__")

if mode == "run":
    rest = sys.argv[4:]
    fn = target(rest)
    prof = cProfile.Profile()
    code = 0
    started = time.perf_counter()
    prof.enable()
    try:
        fn()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        if not isinstance(exc.code, (int, type(None))):
            print(exc.code, file=sys.stderr)
    except BaseException:
        traceback.print_exc()
        code = 1
    finally:
        prof.disable()
        elapsed = time.perf_counter() - started
        sys.stdout.flush(); sys.stderr.flush()
        dump(prof, OUT, code, elapsed)
    sys.exit(code)
else:
    # Server mode: cProfile shares one call stack between threads (Python 3.12+), which corrupts the timings of a
    # threaded server, so threads are measured with a per-thread sys.setprofile hook instead.
    ctl = sys.argv[3]
    rest = sys.argv[5:]
    fn = target(rest)

    def cname(arg):
        owner = getattr(arg, "__self__", None)
        name = getattr(arg, "__name__", "?")
        if owner is None or type(owner).__name__ == "module":
            module = getattr(arg, "__module__", None) or (getattr(owner, "__name__", None) if owner is not None else "builtins")
            return "<built-in method %s.%s>" % (module, name)
        t = type(owner)
        tn = t.__name__ if t.__module__ == "builtins" else "%s.%s" % (t.__module__, t.__name__)
        return "<method '%s' of '%s' objects>" % (name, tn)

    class Hook:
        def __init__(self):
            self.lock = threading.Lock()
            self.local = threading.local()
            self.reset()

        def reset(self):
            with self.lock:
                self.stats = {}
                self.edges = {}
                self.epoch = time.perf_counter()

        def __call__(self, frame, event, arg):
            now = time.perf_counter()
            stack = getattr(self.local, "stack", None)
            if stack is None:
                stack = self.local.stack = []
            if event == "call":
                code = frame.f_code
                stack.append([(code.co_filename, code.co_firstlineno, code.co_name), now, 0.0, True])
            elif event == "c_call":
                stack.append([("~", 0, cname(arg)), now, 0.0, False])
            elif event in ("return", "c_return", "c_exception"):
                python = event == "return"
                if not stack or stack[-1][3] != python:
                    return
                key, start, child, _ = stack.pop()
                elapsed = max(now - max(start, self.epoch), 0.0)
                own = max(elapsed - child, 0.0)
                parent = stack[-1] if stack else None
                if parent is not None:
                    parent[2] += elapsed
                with self.lock:
                    row = self.stats.setdefault(key, [0, 0.0, 0.0])
                    row[0] += 1
                    row[1] += own
                    row[2] += elapsed
                    if parent is not None:
                        edge = self.edges.setdefault(key, {}).setdefault(parent[0], [0.0])
                        edge[0] += own

        def dump(self, path):
            with self.lock:
                rows = []
                for key, (nc, tt, ct) in self.stats.items():
                    callers = [[ck[0], ck[1], ck[2], round(v[0], 7)] for ck, v in self.edges.get(key, {}).items()]
                    rows.append([key[0], key[1], key[2], nc, round(tt, 7), round(ct, 7), callers])
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"exit_code": 0, "run_seconds": 0.0, "functions": rows}, fh)
            os.replace(tmp, path)

    hook = Hook()

    def control():
        sys.setprofile(None)
        seen = ""
        while True:
            try:
                with open(os.path.join(ctl, "cmd"), encoding="utf-8") as fh:
                    text = fh.read().strip()
            except OSError:
                text = ""
            if text and text != seen:
                seen = text
                name, _, token = text.partition(" ")
                if name == "reset":
                    hook.reset()
                else:
                    hook.dump(OUT)
                with open(os.path.join(ctl, "ack"), "w", encoding="utf-8") as fh:
                    fh.write(token)
            time.sleep(0.003)
    threading.Thread(target=control, daemon=True).start()
    time.sleep(0.02)
    threading.setprofile(hook)
    sys.setprofile(hook)
    fn()
'''


# ------------------------------------------------------------------ statistics

def percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def summarise(values):
    if not values:
        return {"n": 0, "median": None, "p90": None, "min": None, "max": None}
    return {"n": len(values), "median": statistics.median(values), "p90": percentile(values, .9), "min": min(values),
            "max": max(values), "mean": statistics.fmean(values)}


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def mann_whitney(a, b):
    """Two-sided Mann-Whitney U. Exact (permutation of the observed ranks) up to 20000 arrangements, normal approximation otherwise."""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return {"u": None, "p_value": None, "method": "none"}
    ranks = _ranks(list(a) + list(b))
    observed = sum(ranks[:n])
    u = observed - n * (n + 1) / 2
    mean = n * (n + m + 1) / 2
    if math.comb(n + m, n) <= 20000:
        total = hits = 0
        for combo in itertools.combinations(range(n + m), n):
            total += 1
            if abs(sum(ranks[i] for i in combo) - mean) >= abs(observed - mean) - 1e-9:
                hits += 1
        return {"u": u, "p_value": hits / total, "method": "exact permutation of ranks"}
    ties = {}
    for r in ranks:
        ties[r] = ties.get(r, 0) + 1
    tie_term = sum(c ** 3 - c for c in ties.values()) / ((n + m) * (n + m - 1))
    variance = n * m / 12 * ((n + m + 1) - tie_term)
    if variance <= 0:
        return {"u": u, "p_value": 1.0, "method": "normal approximation"}
    z = (abs(u - n * m / 2) - .5) / math.sqrt(variance)
    return {"u": u, "p_value": math.erfc(max(z, 0) / math.sqrt(2)), "method": "normal approximation with tie correction"}


def bootstrap_change(before, after, seed=0, resamples=2000):
    """95% bootstrap interval of the relative change of the median (after versus before)."""
    rng = random.Random(seed)
    changes = []
    for _ in range(resamples):
        b = statistics.median(rng.choices(before, k=len(before)))
        a = statistics.median(rng.choices(after, k=len(after)))
        if b > 0:
            changes.append((a - b) / b)
    if not changes:
        return None
    changes.sort()
    return [changes[int(.025 * (len(changes) - 1))], changes[int(.975 * (len(changes) - 1))]]


def compare_samples(before, after, alpha=.05):
    mb, ma = statistics.median(before), statistics.median(after)
    test = mann_whitney(before, after)
    ci = bootstrap_change(before, after)
    change = (ma - mb) / mb if mb > 0 else None
    significant = bool(test["p_value"] is not None and test["p_value"] < alpha and ci is not None and (ci[0] > 0 or ci[1] < 0))
    return {"median_before": mb, "median_after": ma, "change": change, "ci95": ci, "p_value": test["p_value"], "test": test["method"],
            "significant": significant, "direction": None if not significant else "faster" if ma < mb else "slower"}


# ------------------------------------------------------------- classification

WAIT_MARKERS = ("time.sleep", "'acquire' of '_thread", "select.select", "'poll' of 'select", "'accept' of '_socket", "'control' of 'select.kqueue",
                "'wait' of '_thread", "_thread.lock", "_thread.rlock", "'join' of", "lock.acquire")
DB_FILES = ("/sqlalchemy/", "/psycopg", "/pymysql/", "/mysql/", "/asyncpg/", "/sqlite3/", "/peewee", "/pymongo/")
SER_FILES = ("/json/", "/pickle.py", "/yaml/", "/orjson", "/ujson", "/simplejson", "/msgpack", "/marshal", "/plistlib.py")
SER_MARKERS = ("_json", "_pickle", "pickle.", "marshal.", "json.")
RENDER_FILES = ("/jinja2/", "/mako/", "/django/template", "/markupsafe/", "/chevron/", "/genshi/", "/pystache/", "/mustache")
NET_FILES = ("/socket.py", "/ssl.py", "/http/client.py", "/urllib/", "/urllib3/", "/requests/", "/httpx/", "/httpcore/", "/aiohttp/",
             "/smtplib.py", "/ftplib.py")
NET_MARKERS = ("_socket.", "_ssl.", "socket.", "getaddrinfo")


def _norm(path):
    return path.replace("\\", "/")


def classify(file, line, name, user_roots, model_patterns):
    f = _norm(file)
    low = (f + " " + name).lower()
    qualified = [name, f"{f}:{name}", f"{Path(f).stem}.{name}"]
    if model_patterns and any(fnmatch.fnmatchcase(q.lower(), p.lower()) for p in model_patterns for q in qualified):
        return "model"
    if any(m in low for m in WAIT_MARKERS):
        return "waiting"
    if "sqlite3" in low or any(m in f for m in DB_FILES):
        return "database"
    if any(m in f for m in SER_FILES) or (f == "~" and any(m in low for m in SER_MARKERS)):
        return "serialization"
    if any(m in f for m in RENDER_FILES) or (f.endswith("/string.py") and "substitute" in name):
        return "rendering"
    if any(m in f for m in NET_FILES) or (f == "~" and any(m in low for m in NET_MARKERS)):
        return "network"
    if f != "~" and "/site-packages/" not in f and "/lib/python" not in f and "/Lib/" not in file and any(
            f.startswith(_norm(r).rstrip("/") + "/") or f == _norm(r) for r in user_roots):
        return "cpu_user"
    return "other"


def attribute(functions, user_roots, model_patterns):
    """Category totals (seconds of self time) and per-function categories, with inheritance for library helpers
    that are only ever called from one categorised function."""
    cats = {}
    callers = {}
    for f, l, n, nc, tt, ct, cl in functions:
        key = (f, l, n)
        cats[key] = classify(f, l, n, user_roots, model_patterns)
        callers[key] = cl
    for _ in range(3):
        for key, cl in callers.items():
            if cats[key] != "other" or not cl:
                continue
            weights = {}
            for cf, cln, cn, ctt in cl:
                c = cats.get((cf, cln, cn))
                if c is not None:
                    weights[c] = weights.get(c, 0) + max(ctt, 1e-9)
            if weights and len(weights) == 1:
                only = next(iter(weights))
                if only not in ("other", "cpu_user", "waiting"):
                    cats[key] = only
    totals = dict.fromkeys(CATEGORIES, 0.0)
    for f, l, n, nc, tt, ct, cl in functions:
        totals[cats[(f, l, n)]] += tt
    return totals, cats


def _display(path, roots):
    p = _norm(path)
    for r in roots:
        base = _norm(str(r)).rstrip("/") + "/"
        if p.startswith(base):
            return p[len(base):]
    if "/site-packages/" in p:
        return "<site>/" + p.split("/site-packages/", 1)[1]
    match = re.search(r"/[Ll]ib/(?:python[\d.]+/)?", p)
    if match:
        return "<stdlib>/" + p[match.end():]
    return p


def _call_lines(callers, name, roots):
    """Lines in the (user) caller functions whose text mentions the called method; the profile itself has no line of call."""
    token = name.split("'")[1] if "'" in name else name.rsplit(".", 1)[-1].strip("<>")
    token = token.split(" ")[-1].strip("<>{}'")
    lines = []
    for cf, cl, cn, _ in callers[:3]:
        try:
            text = Path(cf).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        end = len(text)
        indent = len(text[cl - 1]) - len(text[cl - 1].lstrip()) if 0 < cl <= len(text) else 0
        for i in range(cl, len(text)):
            s = text[i]
            if s.strip() and len(s) - len(s.lstrip()) <= indent and not s.lstrip().startswith(("#", ")", "]", "}")):
                end = i
                break
        for i in range(cl - 1, end):
            if token and re.search(r"\b" + re.escape(token) + r"\b", text[i]):
                lines.append(f"{_display(cf, roots)}:{i + 1}")
    return lines[:3]


def summarise_profiles(runs, user_roots, model_patterns, top=10, exclude_waiting=False):
    """runs: list of profile dicts. Returns per-category stats, ranked diagnosis and hotspots."""
    per_run, run_cats, by_key = [], [], {}
    for run in runs:
        totals, cats = attribute(run["functions"], user_roots, model_patterns)
        per_run.append(totals)
        run_cats.append(cats)
        for f, l, n, nc, tt, ct, cl in run["functions"]:
            by_key.setdefault((f, l, n), []).append((tt, nc, cl))
    categories = {}
    denominators = []
    for totals in per_run:
        denominators.append(sum(v for k, v in totals.items() if not (exclude_waiting and k == "waiting")) or 1e-12)
    for c in CATEGORIES:
        seconds = [t[c] for t in per_run]
        shares = [t[c] / d for t, d in zip(per_run, denominators)]
        categories[c] = {"seconds": summarise(seconds), "share": summarise(shares)}
    ranked = sorted((c for c in CATEGORIES if not (exclude_waiting and c == "waiting")),
                    key=lambda c: -categories[c]["share"]["median"])
    hotspots = []
    for key, entries in by_key.items():
        median_tt = statistics.median([e[0] for e in entries] + [0.0] * (len(runs) - len(entries)))
        hotspots.append((median_tt, key, entries))
    hotspots.sort(key=lambda x: -x[0])
    total_median = statistics.median([sum(t.values()) for t in per_run]) or 1e-12
    out = []
    for median_tt, key, entries in hotspots[:top]:
        f, l, n = key
        callers = sorted(entries[-1][2], key=lambda c: -c[3])
        category = next((cats[key] for cats in run_cats if key in cats), "other")
        item = {"function": n, "category": category, "calls": int(statistics.median([e[1] for e in entries])),
                "self_seconds_median": median_tt, "share_median": median_tt / total_median,
                "callers": [{"function": cn, "location": f"{_display(cf, user_roots)}:{cln}"} for cf, cln, cn, _ in callers[:3]]}
        if f == "~":
            item["location"] = "(C function)"
            item["call_lines"] = _call_lines(callers, n, user_roots)
        else:
            item["location"] = f"{_display(f, user_roots)}:{l}"
        out.append(item)
    primary = ranked[0]
    share = categories[primary]["share"]
    diagnosis = (f"Most time goes to {primary}: median {share['median'] * 100:.0f}% of profiled self time (p90 {share['p90'] * 100:.0f}%, "
                 f"{share['n']} runs)."
                 + (f" Top hotspot: {out[0]['function']} at {out[0]['call_lines'][0] if out[0].get('call_lines') else out[0]['location']}." if out else ""))
    return {"categories": categories, "ranked": ranked, "primary_category": primary, "diagnosis": diagnosis, "hotspots": out}


# --------------------------------------------------------------------- sources

def _copy_tree(source, dest):
    shutil.copytree(source, dest, ignore=lambda _d, names: [n for n in names if n in COPY_SKIP or n.endswith(".pyc")])


def _git_archive(repo, ref, dest):
    done = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", ref], capture_output=True)
    if done.returncode != 0:
        raise ValueError("git archive failed for " + ref + ": " + done.stderr.decode("utf-8", "replace").strip()[:300])
    dest.mkdir(parents=True)
    import io
    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ValueError("git archive produced an unsafe path")
        tar.extractall(dest, filter="data") if sys.version_info >= (3, 12) else tar.extractall(dest)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _command_spec(value, field):
    if not isinstance(value, dict):
        raise ValueError(field + " must be an object")
    allowed = {"argv", "cwd", "env", "timeout_seconds", "source_dir", "git", "label"}
    if set(value) - allowed:
        raise ValueError(field + " has unknown fields: " + ", ".join(sorted(set(value) - allowed)))
    base = {k: value[k] for k in ("argv", "cwd", "env", "timeout_seconds") if k in value}
    base.setdefault("timeout_seconds", 120)
    argv = base.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a for a in argv):
        raise ValueError(field + ".argv must be a nonempty array of text")
    if value.get("source_dir") and value.get("git"):
        raise ValueError(field + ": give source_dir or git, not both")
    if value.get("git") and (not isinstance(value["git"], dict) or set(value["git"]) != {"repo", "ref"}):
        raise ValueError(field + ".git is {repo, ref}")
    base["env"] = dict(base.get("env") or {})
    return {**base, "source_dir": value.get("source_dir"), "git": value.get("git"), "label": value.get("label", field)}


def _input(value):
    case = validate_case({"name": "operation", **(value or {})})
    if len(case["steps"]) != 1:
        raise ValueError("input is a single operation: give args/stdin/files/db, not several steps")
    return case


def _options(runs, warmup, alpha=None):
    if not isinstance(runs, int) or isinstance(runs, bool) or not 3 <= runs <= MAX_RUNS:
        raise ValueError(f"runs is an integer from 3 to {MAX_RUNS}")
    if not isinstance(warmup, int) or isinstance(warmup, bool) or not 0 <= warmup <= 10:
        raise ValueError("warmup is an integer from 0 to 10")
    if alpha is not None and not 0 < alpha < 1:
        raise ValueError("alpha is between 0 and 1")


def _http_spec(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"request", "ready_timeout_seconds", "port_env"}:
        raise ValueError("http is {request:{method,path,headers,body}, ready_timeout_seconds, port_env}")
    request = value.get("request") or {}
    if set(request) - {"method", "path", "headers", "body"}:
        raise ValueError("http.request is {method, path, headers, body}")
    path = request.get("path", "/")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("http.request.path must start with /")
    return {"request": {"method": str(request.get("method", "GET")).upper(), "path": path,
                        "headers": dict(request.get("headers") or {}), "body": request.get("body", "")},
            "ready_timeout_seconds": float(value.get("ready_timeout_seconds", 20)), "port_env": value.get("port_env", "PORT")}


# ----------------------------------------------------------------------- Perf

class Target:
    """One version of the operation: a command run per measurement, or a server kept up for the whole experiment."""

    def __init__(self, perf, job_id, spec, case, http, model_patterns, user_paths, root):
        self.perf, self.job_id, self.spec, self.case, self.http = perf, job_id, spec, case, http
        self.model_patterns, self.root = model_patterns, root
        self.src = None
        self.user_roots = [str(Path(p)) for p in user_paths]
        self.server = None
        self.profile_available = True
        self.profile_reason = None
        self.sandbox_serial = 0
        self.runner = root / "theseus_perf_runner.py"
        if not self.runner.exists():
            self.runner.write_text(RUNNER, encoding="utf-8")
        self.prepare_source()

    # ---- source and substitution
    def prepare_source(self):
        spec = self.spec
        if spec.get("source_dir"):
            self.src = self.root / ("src-" + identifier()[:8])
            _copy_tree(Path(spec["source_dir"]), self.src)
        elif spec.get("git"):
            self.src = self.root / ("src-" + identifier()[:8])
            _git_archive(spec["git"]["repo"], spec["git"]["ref"], self.src)
        if self.src is not None:
            self.user_roots.append(str(self.src))

    def sub(self, text, sandbox, port=None):
        text = text.replace("{sandbox}", str(sandbox))
        if self.src is not None:
            text = text.replace("{src}", str(self.src))
        if port is not None:
            text = text.replace("{port}", str(port))
        return text

    def new_sandbox(self):
        self.sandbox_serial += 1
        sandbox = self.root / f"sandbox-{identifier()[:8]}"
        sandbox.mkdir()
        _place(sandbox, self.case["files"])
        _seed(sandbox, self.case["db"])
        step = self.case["steps"][0]
        _place(sandbox, step["files"])
        return sandbox

    def python_argv(self):
        argv = self.spec["argv"]
        name = Path(argv[0]).name.lower().removesuffix(".exe")
        if not (name.startswith("python") or argv[0] == sys.executable):
            return False
        return len(argv) > 1 and (argv[1] == "-m" or not argv[1].startswith("-"))

    def environment(self, sandbox, port=None):
        step = self.case["steps"][0]
        return {**DEFAULT_ENV, "THESEUS_SANDBOX": str(sandbox),
                **{k: self.sub(v, sandbox, port) for k, v in {**self.spec["env"], **step["env"]}.items()}}

    def cwd(self, sandbox):
        cwd = self.spec.get("cwd")
        if cwd is None:
            return str(sandbox)
        cwd = self.sub(cwd, sandbox)
        if not Path(cwd).is_absolute():
            cwd = str(sandbox / _relative(cwd, "cwd"))
            Path(cwd).mkdir(parents=True, exist_ok=True)
        return cwd

    def roots(self, sandbox):
        roots = [*self.user_roots, str(sandbox)]
        argv = self.spec["argv"]
        if len(argv) > 1 and argv[1] != "-m" and not argv[1].startswith("-"):
            script = Path(self.sub(argv[1], sandbox))
            if not script.is_absolute():
                script = Path(self.cwd(sandbox)) / script
            roots.append(str(script.resolve().parent))
        return roots

    # ---- command measurements
    def command_argv(self, sandbox, wrapped, out=None):
        step = self.case["steps"][0]
        base = [self.sub(a, sandbox) for a in self.spec["argv"]]
        args = [self.sub(a, sandbox) for a in step["args"]]
        if not wrapped:
            return base + args
        return [base[0], str(self.runner), out, "run", "--", *base[1:], *args]

    def run_command(self, wrapped):
        sandbox = self.new_sandbox()
        try:
            out = str(sandbox.parent / (sandbox.name + ".prof.json"))
            step = self.case["steps"][0]
            run = self.perf.manager._execute(self.job_id, self.command_argv(sandbox, wrapped, out), {
                "cwd": self.cwd(sandbox), "env": self.environment(sandbox), "stdin": step["stdin"],
                "timeout_seconds": self.spec["timeout_seconds"]})
            result = {"wall": run["duration_seconds"], "exit_code": run["exit_code"], "timed_out": run["timed_out"],
                      "stdout": run["stdout"], "stderr": run["stderr"]}
            if wrapped:
                try:
                    profile = json.loads(Path(out).read_text(encoding="utf-8"))
                    result.update(profile=profile, in_process=profile["run_seconds"])
                except (OSError, ValueError):
                    result["profile"] = None
            return result, self.roots(sandbox)
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)
            Path(str(sandbox) + ".prof.json").unlink(missing_ok=True)

    # ---- http measurements
    def start_server(self):
        sandbox = self.new_sandbox()
        self.server_sandbox = sandbox
        port = _free_port()
        self.port = port
        self.ctl = sandbox.parent / (sandbox.name + ".ctl")
        self.ctl.mkdir()
        self.server_out = str(self.ctl / "snap.json")
        base = [self.sub(a, sandbox, port) for a in self.spec["argv"]]
        env = {**os.environ, **self.environment(sandbox, port), self.http["port_env"]: str(port)}
        self.profile_available = self.python_argv()
        if not self.profile_available:
            self.profile_reason = "the server command is not a Python script; only wall-clock segments were measured"
            argv = base
        else:
            argv = [base[0], str(self.runner), self.server_out, "server", str(self.ctl), "--", *base[1:]]
        self.server = subprocess.Popen(argv, cwd=self.cwd(sandbox), env=env, stdout=subprocess.DEVNULL, stderr=open(self.ctl / 'server.err', 'wb'))
        deadline = time.monotonic() + self.http["ready_timeout_seconds"]
        while time.monotonic() < deadline:
            if self.server.poll() is not None:
                raise RuntimeError("server exited before becoming ready: " + (self.ctl / "server.err").read_text(encoding="utf-8", errors="replace")[-500:])
            try:
                socket.create_connection(("127.0.0.1", port), timeout=.2).close()
                return
            except OSError:
                time.sleep(.05)
        raise RuntimeError("server did not accept connections within the ready timeout")

    def control(self, name):
        token = identifier()[:8]
        (self.ctl / "cmd").write_text(f"{name} {token}", encoding="utf-8")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if (self.ctl / "ack").read_text(encoding="utf-8") == token:
                    return
            except OSError:
                pass
            time.sleep(.003)
        raise RuntimeError("server profiler did not acknowledge " + name)

    def request_once(self):
        req = self.http["request"]
        started = time.perf_counter()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.spec["timeout_seconds"])
        conn.connect()
        connected = time.perf_counter()
        headers = {**req["headers"], "Connection": "close"}
        conn.request(req["method"], req["path"], body=req["body"] or None, headers=headers)
        sent = time.perf_counter()
        response = conn.getresponse()
        first = time.perf_counter()
        body = response.read()
        done = time.perf_counter()
        conn.close()
        return {"wall": done - started, "connect": connected - started, "wait_first_byte": first - sent, "download": done - first,
                "status": response.status, "body": body}

    def measure(self, profiled):
        if self.http is None:
            return self.run_command(profiled and self.python_argv())
        if profiled and self.profile_available:
            self.control("reset")
        result = self.request_once()
        if profiled and self.profile_available:
            self.control("snapshot")
            try:
                result["profile"] = json.loads(Path(self.server_out).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                result["profile"] = None
        return result, self.roots(self.server_sandbox)

    def close(self):
        if self.server is not None:
            self.server.terminate()
            try:
                self.server.wait(5)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait()


def _output_signature(result, http):
    if http is not None:
        return {"status": result["status"], "sha256": hashlib.sha256(result["body"]).hexdigest()}
    return {"exit_code": result["exit_code"], "stdout_sha256": hashlib.sha256(result["stdout"].encode("utf-8", "replace")).hexdigest(),
            "stderr_sha256": hashlib.sha256(result["stderr"].encode("utf-8", "replace")).hexdigest()}


class Perf:
    def __init__(self, manager, equivalence=None):
        self.manager, self.store = manager, manager.store
        self.equivalence = equivalence or Equivalence(manager)

    def _check(self, job_id):
        self.equivalence._check(job_id)

    def _start(self, project_id, kind, result, work):
        job_id = identifier()
        result["kind"] = kind
        self.store.save_job(project_id, job_id, "queued", result)
        self.manager.pool.submit(self._job, project_id, job_id, result, work)
        return self.store.job(job_id)

    def _job(self, project_id, job_id, result, work):
        root = Path(tempfile.mkdtemp(prefix="theseus-perf-"))
        try:
            self.store.save_job(project_id, job_id, "running", result)
            work(job_id, result, root, lambda: self.store.save_job(project_id, job_id, "running", result))
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
            shutil.rmtree(root, ignore_errors=True)

    # ------------------------------------------------------------ profile
    def profile(self, project_id, command, input=None, warmup=1, runs=5, model_functions=None, user_paths=None, top=10, http=None):
        self.store.project(project_id)
        spec = _command_spec(command, "command")
        case, http = _input(input), _http_spec(http)
        _options(runs, warmup)
        patterns = [str(p) for p in (model_functions or [])]
        paths = [str(p) for p in (user_paths or [])]
        result = {"command": spec, "input": {k: case[k] for k in ("steps", "files", "db")}, "http": http, "scope": PROFILE_NOTE,
                  "options": {"warmup": warmup, "runs": runs, "model_functions": patterns, "top": top}}

        def work(job_id, result, root, save):
            target = Target(self, job_id, spec, case, http, patterns, paths, root)
            try:
                if http is not None:
                    target.start_server()
                measurements = self._measure(job_id, [target], warmup, runs, result, save)[0]
            finally:
                target.close()
            result.update(self._report(target, measurements, patterns, top, http))

        return self._start(project_id, "perf_profile", result, work)

    def _measure(self, job_id, targets, warmup, runs, result, save):
        """Warm-up, then interleaved unprofiled and profiled measurements of every target."""
        for _ in range(warmup):
            for t in targets:
                self._check(job_id)
                t.measure(False)
        out = [{"wall": [], "profiles": [], "roots": [], "signatures": [], "segments": [], "failures": 0, "profile_missing": 0} for _ in targets]
        for i in range(runs):
            order = list(range(len(targets))) if i % 2 == 0 else list(reversed(range(len(targets))))
            for idx in order:
                self._check(job_id)
                t, bucket = targets[idx], out[idx]
                plain, _ = t.measure(False)
                bucket["signatures"].append(_output_signature(plain, t.http))
                if plain.get("timed_out") or (t.http is None and plain.get("exit_code") not in (0, None)):
                    bucket["failures"] += 1
                bucket["wall"].append(plain["wall"])
                bucket["segments"].append({k: plain[k] for k in ("connect", "wait_first_byte", "download", "wall") if k in plain}
                                          if t.http is not None else {"total": plain["wall"]})
                profiled, roots = t.measure(True)
                if profiled.get("profile"):
                    bucket["profiles"].append(profiled["profile"])
                    bucket["roots"] = roots
                elif t.http is None and t.python_argv() or (t.http is not None and t.profile_available):
                    bucket["profile_missing"] += 1
            result["completed_runs"] = i + 1
            save()
        return out

    def _report(self, target, m, patterns, top, http):
        wall = summarise(m["wall"])
        report = {"wall_seconds": wall, "wall_samples": [round(x, 5) for x in m["wall"]],
                  "segments": self._segments(m["segments"], target, m),
                  "determinism": {"distinct_outputs": len({json.dumps(s, sort_keys=True) for s in m["signatures"]}),
                                  "failed_runs": m["failures"]}}
        if m["profiles"]:
            roots = [*target.user_roots, *m["roots"]]
            summary = summarise_profiles(m["profiles"], roots, patterns, top, exclude_waiting=http is not None)
            report["profile"] = {"runs": len(m["profiles"]), **summary,
                                 **({"waiting_excluded": "idle and blocked time of server threads is excluded from the shares"} if http else {})}
            report["diagnosis"] = summary["diagnosis"]
        else:
            report["profile"] = None
            report["diagnosis"] = ("No cProfile data: " + (target.profile_reason or "the command is not a Python interpreter invocation")
                                   + ". Only wall-clock segments are available.")
        if m["failures"]:
            report["warning"] = f"{m['failures']} run(s) exited nonzero or timed out; timings may not describe the intended operation."
        return report

    @staticmethod
    def _segments(rows, target, m):
        keys = sorted({k for r in rows for k in r})
        segments = {k: summarise([r[k] for r in rows if k in r]) for k in keys}
        profiles = m["profiles"]
        if profiles and target.http is None:
            inner = [p["run_seconds"] for p in profiles]
            segments["in_process_profiled"] = summarise(inner)
        return segments

    # ------------------------------------------------------------ compare
    def compare(self, project_id, before, after, input=None, warmup=1, runs=6, alpha=.05, model_functions=None, user_paths=None,
                check_inputs=None, normalisers=None, http=None, top=5):
        self.store.project(project_id)
        b_spec, a_spec = _command_spec(before, "before"), _command_spec(after, "after")
        case, http = _input(input), _http_spec(http)
        _options(runs, warmup, alpha)
        checks = [{"name": f"check-{i + 1}", **c} for i, c in enumerate(check_inputs or [])]
        for c in checks:
            validate_case(c)
        norms = _normalisers(normalisers, "normalisers")
        patterns = [str(p) for p in (model_functions or [])]
        paths = [str(p) for p in (user_paths or [])]
        result = {"before": b_spec, "after": a_spec, "input": {k: case[k] for k in ("steps", "files", "db")}, "http": http,
                  "scope": PROFILE_NOTE, "options": {"warmup": warmup, "runs": runs, "alpha": alpha, "normalisers": norms,
                                                     "model_functions": patterns}}

        def work(job_id, result, root, save):
            ta = Target(self, job_id, b_spec, case, http, patterns, paths, root)
            tb = Target(self, job_id, a_spec, case, http, patterns, paths, root)
            try:
                if http is not None:
                    ta.start_server()
                    tb.start_server()
                mb, ma = self._measure(job_id, [ta, tb], warmup, runs, result, save)
            finally:
                ta.close()
                tb.close()
            result["before_report"] = self._report(ta, mb, patterns, top, http)
            result["after_report"] = self._report(tb, ma, patterns, top, http)
            result["total"] = compare_samples(mb["wall"], ma["wall"], alpha)
            result["total"]["speedup"] = (result["total"]["median_before"] / result["total"]["median_after"]
                                          if result["total"]["median_after"] else None)
            result["categories"] = self._category_changes(mb, ma, ta, tb, patterns, alpha, http)
            result["equivalence"] = self._outputs(job_id, ta, tb, b_spec, a_spec, case, checks, norms, mb, ma, http, root)
            result["verdict"] = self._verdict(result)

        return self._start(project_id, "perf_compare", result, work)

    def _category_changes(self, mb, ma, ta, tb, patterns, alpha, http):
        if not mb["profiles"] or not ma["profiles"]:
            return None
        out = {}
        sb = [attribute(p["functions"], [*ta.user_roots, *mb["roots"]], patterns)[0] for p in mb["profiles"]]
        sa = [attribute(p["functions"], [*tb.user_roots, *ma["roots"]], patterns)[0] for p in ma["profiles"]]
        tot_b = [sum(t.values()) for t in sb]
        tot_a = [sum(t.values()) for t in sa]
        for c in CATEGORIES:
            xb, xa = [t[c] for t in sb], [t[c] for t in sa]
            if statistics.median(xb) < 1e-5 and statistics.median(xa) < 1e-5:
                continue
            if statistics.median(xb) <= 0:
                out[c] = {"median_before": 0.0, "median_after": statistics.median(xa), "change": None, "significant": False}
                continue
            out[c] = compare_samples(xb, xa, alpha)
        out["total_profiled"] = compare_samples(tot_b, tot_a, alpha)
        out["note"] = "Seconds of profiled self time per category (cProfile overhead included); runs are paired by position, not by pair."
        return out

    def _outputs(self, job_id, ta, tb, b_spec, a_spec, case, checks, norms, mb, ma, http, root):
        """Same outputs? Commands go through the equivalence runner (fresh sandboxes, all channels); servers compare status and body."""
        if http is not None:
            sig_b = {json.dumps(s, sort_keys=True) for s in mb["signatures"]}
            sig_a = {json.dumps(s, sort_keys=True) for s in ma["signatures"]}
            same = len(sig_b) == 1 and sig_b == sig_a
            return {"method": "http status and body hash", "identical": same, "before": sorted(sig_b), "after": sorted(sig_a),
                    "scope": "Only the measured request was compared."}
        step = case["steps"][0]
        sub = lambda spec, t: {"argv": [t.sub(a, "{sandbox}") for a in spec["argv"]], "env": {k: t.sub(v, "{sandbox}") for k, v in spec["env"].items()},
                                "cwd": spec.get("cwd") and t.sub(spec["cwd"], "{sandbox}"), "timeout_seconds": spec["timeout_seconds"]}
        measured = {"name": "measured-operation", "stdin": step["stdin"], "args": step["args"], "files": {**case["files"], **step["files"]},
                    **({"db": case["db"]} if case["db"] else {})}
        cases = [measured] + list(checks)
        suite = validate_suite({"reference": sub(b_spec, ta), "candidate": sub(a_spec, tb), "cases": cases, "normalisers": norms})
        details, differing = [], []
        for c in suite["cases"]:
            ref, cand, found, matched, invalid = self.equivalence.run_case(job_id, suite, c)
            verdict = self.equivalence.verdict(found, invalid)
            details.append({"case": c["name"], "verdict": verdict,
                            **({"first_disagreement": next(d for d in found if d["status"] == "disagreement")} if verdict == "different" else {})})
            if verdict != "equivalent":
                differing.append(c["name"])
        return {"method": "equivalence runner (fresh sandboxes; exit code, stdout, stderr, files, SQLite)", "identical": not differing,
                "cases": details, "differing_cases": differing,
                "scope": "Only the measured operation and the listed check inputs were compared; agreement is not whole-program equivalence."}

    @staticmethod
    def _verdict(result):
        total, eq = result["total"], result["equivalence"]
        if not eq["identical"]:
            speed = ("faster" if total["direction"] == "faster" else "not faster")
            return {"status": "failed", "reason": f"the outputs differ ({speed}); a change in results is not an optimisation",
                    "outputs_identical": False, "speedup": total.get("speedup"), "total": total["direction"]}
        if total["direction"] == "faster":
            status = "faster"
        elif total["direction"] == "slower":
            status = "slower"
        else:
            status = "no_significant_change"
        runs = result["options"]["runs"]
        note = None
        if status == "no_significant_change" and runs < 4:
            note = "with fewer than 4 runs per version no difference can reach p < 0.05; increase runs"
        return {"status": status, "reason": "wall-clock median change is statistically " + ("significant" if status != "no_significant_change"
                                                                                               else "not significant") + " and outputs are identical",
                "outputs_identical": True, "speedup": total.get("speedup"), **({"note": note} if note else {})}
