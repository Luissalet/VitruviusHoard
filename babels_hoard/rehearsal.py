"""Dependency upgrade rehearsal: what would moving ``package`` to ``target_version`` break in this project?

Everything reuses Babel's own machinery: the griffe indexer (``indexing``), the
call/attribute resolution of ``api_check_code`` (``checker``) and the project
dependency reader (``deps``). Both versions are indexed into private scratch
databases from isolated source trees (``pip install --target`` into a temp
folder, or folders the caller names); the user's environment and project are
never modified. Proposed edits are only applied to a throwaway copy.

Python only. TypeScript/JS projects are refused explicitly: the JS indexer
reads declaration files but the checker has no call-shape analysis for it.
"""
from __future__ import annotations

import ast
import difflib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from . import checker, db, deps, environments, indexing
from .markdown_index import _split_markdown

SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", ".env", "node_modules", "__pycache__", "site-packages",
    "build", "dist", ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode",
}
MAX_FILES = 3000
MAX_LISTED = 200
CHANGELOG_RE = re.compile(r"^(changelog|changes|history|news|release[-_ ]?notes|whatsnew)[^/]*\.(md|rst|txt)$", re.I)
CHANGE_WORDS_RE = re.compile(r"versionchanged|changed in|behaviou?r|no longer|now (returns|raises|defaults|uses|requires)|deprecated|removed|renamed|breaking", re.I)
LIMITATIONS = [
    "Python only: JavaScript/TypeScript projects are not analysed.",
    "Only call sites the static checker can resolve are classified; values of unknown type, dynamic attribute access and "
    "code behind hasattr/version guards are counted as unchecked, and a textual scan lists leftover mentions of removed names as at risk.",
    "Classification compares indexed public signatures, not behaviour: a changed return value or side effect is reported only "
    "when the docstring, the changelog or a default value says so.",
    "Mechanical edits are limited to renamed keyword arguments (one-to-one position/default match) and moved imports "
    "where the new location is unique. Everything else is listed as manual.",
    "Packages above Babel's indexing cap are partially indexed; absence of a name is then not provable and stays unchecked.",
]


class RehearsalError(ValueError):
    """A request the rehearsal cannot honour (bad project, unknown version, pip failure)."""


# ------------------------------------------------------------------ helpers
def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def project_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for base, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith((".egg-info", ".dist-info")))
        for n in sorted(names):
            if n.endswith(".py"):
                found.append(Path(base) / n)
                if len(found) >= MAX_FILES:
                    return found
    return found


def _char_col(line: str, byte_col: int) -> int:
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", "replace"))


def _pip_target(python: str, spec: str, dest: Path, extra: list[str], timeout: float, deps_too: bool) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [python, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location", "--upgrade",
           "--target", str(dest), *([] if deps_too else ["--no-deps"]), *extra, spec]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RehearsalError(f"pip timed out after {int(timeout)} s installing {spec}") from exc
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-6:]
        raise RehearsalError(f"pip could not install {spec} into an isolated folder: " + " | ".join(tail))


def _import_names_in(folder: Path, package: str) -> list[str]:
    """Top-level import names a ``pip --target`` folder holds for ``package`` (from its RECORD)."""
    want = _norm(package)
    for info in sorted(folder.glob("*.dist-info")):
        stem = info.name[: -len(".dist-info")].rsplit("-", 1)[0]
        if _norm(stem) != want:
            continue
        top = info / "top_level.txt"
        names: list[str] = []
        if top.is_file():
            names = [n.strip() for n in top.read_text(encoding="utf-8", errors="replace").splitlines() if n.strip()]
        elif (info / "RECORD").is_file():
            for line in (info / "RECORD").read_text(encoding="utf-8", errors="replace").splitlines():
                first = line.split(",", 1)[0].replace("\\", "/")
                head = first.split("/", 1)[0]
                if head.endswith(".py"):
                    head = head[:-3]
                if head and head.isidentifier() and not head.startswith("_") and not head.endswith("-info"):
                    names.append(head)
        names = sorted({n for n in names if n.isidentifier() and not n.startswith("_")})
        if names:
            return names
    return []


def _installed_version(folder: Path, package: str) -> str | None:
    want = _norm(package)
    for info in sorted(folder.glob("*.dist-info")):
        stem = info.name[: -len(".dist-info")]
        name, _, version = stem.rpartition("-")
        if _norm(name) == want:
            return version
    return None


# -------------------------------------------------------------- API surface
def _public(qualname: str) -> bool:
    for seg in qualname.split("."):
        if seg.startswith("_") and not (seg.startswith("__") and seg.endswith("__") and seg == "__init__"):
            return False
    return True


def load_surface(conn, lib_ids: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for lib_id in lib_ids:
        for r in conn.execute("SELECT * FROM entries WHERE library_id=?", (lib_id,)):
            q = r["qualname"]
            if not _public(q) or q in out:
                continue
            meta = db.from_json(r["meta_json"]) or {}
            out[q] = {
                "qualname": q, "kind": r["kind"], "signature": r["signature"], "params": db.from_json(r["params_json"]) or [],
                "returns": r["returns"], "deprecated": bool(r["deprecated"]), "deprecated_note": r["deprecated_note"],
                "doc": r["doc"] or "", "target": r["target"], "meta": meta, "path": r["source_path"], "line": r["source_line"],
            }
    return out


_CALLABLE = {"function", "method"}
_POSITIONAL = {"POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD"}


def _effective_params(e: dict[str, Any]) -> list[dict[str, Any]]:
    params = list(e["params"])
    if e["kind"] == "method" and (e["meta"].get("mt") in ("i", "c")) and params and params[0].get("kind") in _POSITIONAL:
        params = params[1:]
    return params


def _required(p: dict[str, Any]) -> bool:
    return p.get("kind") in _POSITIONAL | {"KEYWORD_ONLY"} and p.get("default") is None


def compare_entry(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Differences between two indexed entries of the same qualname."""
    out: dict[str, Any] = {}
    if old["kind"] != new["kind"]:
        out["kind_change"] = {"from": old["kind"], "to": new["kind"]}
        out["breaking"] = True
        return out
    if old["kind"] in _CALLABLE:
        if old["meta"].get("as") != new["meta"].get("as"):
            out["async_change"] = {"from": bool(old["meta"].get("as")), "to": bool(new["meta"].get("as"))}
            out["breaking"] = True
        if old["meta"].get("mt") != new["meta"].get("mt"):
            out["receiver_change"] = {"from": old["meta"].get("mt"), "to": new["meta"].get("mt")}
            out["breaking"] = True
        po, pn = _effective_params(old), _effective_params(new)
        names_o, names_n = [p["name"] for p in po], [p["name"] for p in pn]
        gone = [n for n in names_o if n not in names_n]
        fresh = [n for n in names_n if n not in names_o]
        renames: dict[str, str] = {}
        for g in gone:
            io = names_o.index(g)
            cands = [a for a in fresh if names_n.index(a) == io and pn[names_n.index(a)].get("kind") == po[io].get("kind")
                     and pn[names_n.index(a)].get("default") == po[io].get("default")]
            if len(cands) == 1 and cands[0] not in renames.values():
                renames[g] = cands[0]
        removed = [g for g in gone if g not in renames]
        added = [a for a in fresh if a not in renames.values()]
        if renames:
            out["renamed_params"] = renames
            out["breaking"] = True
        if removed:
            has_kwargs = any(p.get("kind") == "VAR_KEYWORD" for p in pn)
            out["removed_params"] = removed
            if not has_kwargs:
                out["breaking"] = True
        required_new = [a for a in added if _required(pn[names_n.index(a)])]
        if required_new:
            out["added_required_params"] = required_new
            out["breaking"] = True
        if added and not required_new:
            out["added_optional_params"] = [a for a in added if a not in required_new]
        defaults = {n: {"from": po[names_o.index(n)].get("default"), "to": pn[names_n.index(n)].get("default")}
                    for n in names_o if n in names_n and po[names_o.index(n)].get("default") != pn[names_n.index(n)].get("default")}
        if defaults:
            out["default_changed"] = defaults
            # becoming required / optional also changes whether callers may omit it
            if any(v["to"] is None for v in defaults.values()):
                out["breaking"] = True
        kinds = {n: {"from": po[names_o.index(n)].get("kind"), "to": pn[names_n.index(n)].get("kind")}
                 for n in names_o if n in names_n and po[names_o.index(n)].get("kind") != pn[names_n.index(n)].get("kind")}
        if kinds:
            out["param_kind_changed"] = kinds
            if any(v["from"] in _POSITIONAL | {"KEYWORD_ONLY"} and v["to"] != v["from"] and not (
                    v["from"] == "POSITIONAL_ONLY" and v["to"] == "POSITIONAL_OR_KEYWORD") for v in kinds.values()):
                out["breaking"] = True
        common_pos = [n for n in names_o if n in names_n and pn[names_n.index(n)].get("kind") in _POSITIONAL]
        if common_pos != [n for n in names_n if n in common_pos]:
            out["order_changed"] = True
            out["breaking"] = True
        notes = {n: {"from": po[names_o.index(n)].get("annotation"), "to": pn[names_n.index(n)].get("annotation")}
                 for n in names_o if n in names_n and po[names_o.index(n)].get("annotation") != pn[names_n.index(n)].get("annotation")}
        if notes:
            out["annotation_changed"] = notes
        if old["returns"] != new["returns"]:
            out["returns_changed"] = {"from": old["returns"], "to": new["returns"]}
    if new["deprecated"] and not old["deprecated"]:
        out["newly_deprecated"] = new["deprecated_note"] or True
    return out


def _shape(e: dict[str, Any]) -> tuple:
    return tuple((p["name"], p.get("kind"), p.get("default")) for p in _effective_params(e))


def diff_surfaces(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> dict[str, Any]:
    removed_all = {q for q in old if q not in new}
    top_removed = sorted(q for q in removed_all if q.rsplit(".", 1)[0] not in removed_all)
    added = sorted(q for q in new if q not in old)
    by_leaf: dict[tuple[str, str], list[str]] = {}
    for q in added:
        by_leaf.setdefault((q.rsplit(".", 1)[-1], new[q]["kind"]), []).append(q)
    moved: dict[str, str] = {}
    ambiguous: dict[str, list[str]] = {}
    for q in sorted(removed_all):
        e = old[q]
        parent = old.get(q.rsplit(".", 1)[0])
        if e["kind"] not in ("function", "class") or parent is None or parent["kind"] != "module":
            continue
        cands = [c for c in by_leaf.get((q.rsplit(".", 1)[-1], e["kind"]), []) if c.rsplit(".", 1)[0] != q.rsplit(".", 1)[0]]
        if e["kind"] in _CALLABLE:
            cands = [c for c in cands if _shape(old[q]) == _shape(new[c])]
        elif e["kind"] == "class":
            kids = {k[len(q) + 1:] for k in old if k.startswith(q + ".")}
            cands = [c for c in cands if {k[len(c) + 1:] for k in new if k.startswith(c + ".")} == kids]
        if len(cands) == 1:
            moved[q] = cands[0]
        elif cands:
            ambiguous[q] = cands
    changed = {}
    for q in old.keys() & new.keys():
        c = compare_entry(old[q], new[q])
        if c:
            changed[q] = c
    return {"removed": top_removed, "removed_total": len(removed_all), "added": added, "moved": moved,
            "ambiguous_moves": ambiguous, "changed": changed}


# --------------------------------------------------------------- changelog
def _changelog_sections(paths: list[Path]) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for heading, body in _split_markdown(text, rst=p.suffix.lower() == ".rst"):
            if body.strip():
                sections.append({"file": p.name, "heading": heading or "(top)", "text": body})
    return sections


def _discover_changelogs(folders: list[Path]) -> list[Path]:
    found: list[Path] = []
    for folder in folders:
        if not folder.is_dir():
            continue
        for base, dirs, names in os.walk(folder):
            depth = len(Path(base).relative_to(folder).parts)
            dirs[:] = [d for d in dirs if depth < 2 and d not in SKIP_DIRS]
            for n in names:
                if CHANGELOG_RE.match(n):
                    found.append(Path(base) / n)
    return found[:20]


def _doc_evidence(symbol: str, new_entry: dict[str, Any] | None, sections: list[dict[str, str]]) -> list[dict[str, str]]:
    leaf = symbol.rsplit(".", 1)[-1]
    out: list[dict[str, str]] = []
    if new_entry:
        for line in new_entry["doc"].splitlines():
            if CHANGE_WORDS_RE.search(line):
                out.append({"source": "docstring", "text": line.strip()[:240]})
                break
    word = re.compile(r"(?<![\w.])`?" + re.escape(leaf) + r"`?(?![\w])")
    for s in sections:
        for line in s["text"].splitlines():
            if word.search(line) and CHANGE_WORDS_RE.search(line):
                out.append({"source": f"{s['file']} / {s['heading']}", "text": line.strip()[:240]})
                break
        if len(out) >= 3:
            break
    return out


# -------------------------------------------------------------- scanning
def _scan(conn_old, env_old, conn_new, env_new, files: list[Path], root: Path, names: list[str]):
    inventory: list[dict[str, Any]] = []
    base_findings: set[tuple] = set()
    new_findings: list[dict[str, Any]] = []
    unchecked = 0
    scanned = 0
    sources: dict[str, str] = {}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not any(n in text for n in names):
            continue
        rel = path.relative_to(root).as_posix()
        sources[rel] = text
        uses: list[dict[str, Any]] = []
        before = checker.api_check_code(conn_old, text, env_row=env_old, lazy=False, uses=uses)
        if any(f["code"] == "syntax_error" for f in before["findings"]):
            continue
        scanned += 1
        after = checker.api_check_code(conn_new, text, env_row=env_new, lazy=False)
        unchecked += after["unchecked"]
        for u in uses:
            inventory.append({"file": rel, **u})
        for f in before["findings"]:
            base_findings.add((rel, f["line"], f["code"], f["symbol"]))
        for f in after["findings"]:
            if f["severity"] == "error" or f["code"] == "deprecated":
                new_findings.append({"file": rel, **f})
    return inventory, base_findings, new_findings, unchecked, scanned, sources


def _import_statements(sources: dict[str, str], names: list[str]):
    """``from <package...> import ...`` statements, with exact character spans."""
    out = []
    for rel, text in sources.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        lines = text.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and not node.level and node.module and node.module.split(".")[0] in names:
                out.append({"file": rel, "node": node, "lines": lines})
    return out


def _propose_import_moves(statements, diff, surface_old, surface_new):
    """Per statement: which imported names vanished, and is a unique new home known?"""
    edits: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    broken: list[dict[str, Any]] = []
    for st in statements:
        node, lines, rel = st["node"], st["lines"], st["file"]
        module = node.module
        stay, moving, lost = [], [], []
        for alias in node.names:
            if alias.name == "*":
                stay.append(alias)
                continue
            q = f"{module}.{alias.name}"
            if q in surface_new:
                stay.append(alias)
            elif q in surface_old or module in diff["removed"] or any(module == r or module.startswith(r + ".") for r in diff["removed"]):
                key = q if q in diff["moved"] else None
                if key is None:  # a whole module may have moved: look for the name inside the old module's moved children
                    key = next((k for k in diff["moved"] if k == q), None)
                if key:
                    moving.append((alias, diff["moved"][key]))
                else:
                    lost.append((alias, diff["ambiguous_moves"].get(q, [])))
            else:
                stay.append(alias)
        for alias, cands in lost:
            broken.append({"file": rel, "line": node.lineno, "col": node.col_offset, "code": "removed_import",
                           "symbol": f"{module}.{alias.name}",
                           "message": f"'{alias.name}' no longer exists in '{module}' in the target version.",
                           **({"candidates": cands} if cands else {})})
            manual.append({"file": rel, "line": node.lineno,
                           "action": f"'{alias.name}' was removed from '{module}'"
                                     + (f"; candidate new locations: {', '.join(cands)}" if cands else "; no equivalent symbol found"),
                           "reason": "removed" if not cands else "ambiguous move"})
        for alias, new_q in moving:
            broken.append({"file": rel, "line": node.lineno, "col": node.col_offset, "code": "moved_import",
                           "symbol": f"{module}.{alias.name}",
                           "message": f"'{alias.name}' moved from '{module}' to '{new_q.rsplit('.', 1)[0]}'.", "moved_to": new_q})
        if not moving:
            continue
        targets = {n.rsplit(".", 1)[0] for _a, n in moving}
        single_line = node.lineno == getattr(node, "end_lineno", node.lineno)
        renamed_leaf = any(n.rsplit(".", 1)[-1] != a.name for a, n in moving)
        if not single_line or renamed_leaf:
            manual.append({"file": rel, "line": node.lineno, "action": "update the import to the new location(s): " +
                           ", ".join(f"{a.name} -> {n}" for a, n in moving), "reason": "multi-line import"})
            continue
        line = lines[node.lineno - 1]
        start, end = _char_col(line, node.col_offset), _char_col(line, node.end_col_offset)
        indent = line[:start]
        stmts = []

        def render(mod: str, aliases) -> str:
            return f"from {mod} import " + ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in aliases)
        if stay:
            stmts.append(render(module, stay))
        for t in sorted(targets):
            stmts.append(render(t, [a for a, n in moving if n.rsplit(".", 1)[0] == t]))
        if stay and any(a.name == "*" for a in stay):
            manual.append({"file": rel, "line": node.lineno, "action": "star import mixed with a moved name", "reason": "star import"})
            continue
        edits.append({"file": rel, "line": node.lineno, "col": start, "end_line": node.lineno, "end_col": end,
                      "old": line[start:end], "new": ("\n" + indent).join(stmts), "kind": "moved_import",
                      "reason": "; ".join(f"{a.name}: {module} -> {n.rsplit('.', 1)[0]}" for a, n in moving) + " (unique new location)"})
    return edits, manual, broken


def _classify(inventory, base_findings, new_findings, diff, surface_new, sources, sections, edits_import_lines):
    broken: list[dict[str, Any]] = []
    at_risk: list[dict[str, Any]] = []
    edits: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    calls_by_line: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for u in inventory:
        if u["kind"] == "call":
            calls_by_line.setdefault((u["file"], u["line"]), []).append(u)
    covered: set[tuple[str, int, str]] = set()
    for f in new_findings:
        key = (f["file"], f["line"], f["code"], f["symbol"])
        if key in base_findings:
            continue
        if f["code"] == "deprecated":
            at_risk.append({"file": f["file"], "line": f["line"], "col": f["col"], "symbol": f["symbol"], "reason": f["message"],
                            "evidence": [{"source": "index", "text": f["message"]}]})
            continue
        if f["file"] and (f["file"], f["line"]) in edits_import_lines and f["code"] in ("unknown_attribute", "unknown_module"):
            continue  # already reported (with its edit or manual item) by the import analysis
        entry = {"file": f["file"], "line": f["line"], "col": f["col"], "code": f["code"], "symbol": f["symbol"],
                 "message": f["message"], **({"suggestion": f["suggestion"]} if f.get("suggestion") else {})}
        covered.add((f["file"], f["line"], f["symbol"]))
        if f["code"] == "unexpected_keyword":
            m = re.search(r"\((\w+)=\.\.\.\)$", f["symbol"])
            kw = m.group(1) if m else None
            hit = next(((c, k) for c in calls_by_line.get((f["file"], f["line"]), []) for k in c.get("keywords", []) if k["name"] == kw), None)
            if hit:
                call, kwd = hit
                ch = diff["changed"].get(call["symbol"], {})
                new_name = ch.get("renamed_params", {}).get(kw)
                entry["cause"] = {"symbol": call["symbol"], **{k: v for k, v in ch.items() if k in ("renamed_params", "removed_params")}}
                line_text = sources[f["file"]].splitlines()[kwd["line"] - 1]
                col = _char_col(line_text, kwd["col"])
                if new_name and line_text[col:col + len(kw)] == kw:
                    edit = {"file": f["file"], "line": kwd["line"], "col": col, "end_line": kwd["line"], "end_col": col + len(kw),
                            "old": kw, "new": new_name, "kind": "renamed_keyword",
                            "reason": f"{call['symbol']}: parameter '{kw}' was renamed to '{new_name}' "
                                      "(same position, kind and default)"}
                    edits.append(edit)
                    entry["edit"] = f"{kw} -> {new_name}"
                else:
                    manual.append({"file": f["file"], "line": f["line"], "action": f"keyword '{kw}' no longer accepted by {call['symbol']}"
                                   + (f"; try '{f['suggestion']}'" if f.get("suggestion") else ""), "reason": "no certain replacement"})
        elif f["code"] in ("unknown_attribute", "unknown_module"):
            q = f["symbol"]
            if q in diff["moved"]:
                entry["cause"] = {"moved_to": diff["moved"][q]}
                manual.append({"file": f["file"], "line": f["line"], "action": f"'{q}' moved to '{diff['moved'][q]}'; update this reference",
                               "reason": "moved, not an import statement"})
            elif q in diff["ambiguous_moves"]:
                entry["cause"] = {"candidates": diff["ambiguous_moves"][q]}
                manual.append({"file": f["file"], "line": f["line"], "action": f"'{q}' removed; candidates: {', '.join(diff['ambiguous_moves'][q])}",
                               "reason": "ambiguous move"})
            else:
                entry["cause"] = {"removed": q} if q in diff["removed"] or any(q.startswith(r + ".") for r in diff["removed"]) else {}
                manual.append({"file": f["file"], "line": f["line"], "action": f"'{q}' no longer exists"
                               + (f"; checker suggests '{f['suggestion']}'" if f.get("suggestion") else ""), "reason": "removed"})
        elif f["code"] == "missing_required":
            calls = calls_by_line.get((f["file"], f["line"]), [])
            ch = diff["changed"].get(calls[0]["symbol"], {}) if calls else {}
            if ch.get("added_required_params"):
                entry["cause"] = {"symbol": calls[0]["symbol"], "added_required_params": ch["added_required_params"]}
            manual.append({"file": f["file"], "line": f["line"], "action": f["message"], "reason": "new required argument: its value is a design decision"})
        else:
            manual.append({"file": f["file"], "line": f["line"], "action": f["message"], "reason": f["code"]})
        broken.append(entry)
    # at-risk / ok from the inventory of uses resolved in the current version
    broken_lines = {(b["file"], b["line"]) for b in broken}
    ok_count = 0
    seen: set[tuple] = set()
    ok_sample: list[dict[str, Any]] = []
    call_lines = {(u["file"], u["line"], u["symbol"]) for u in inventory if u["kind"] == "call"}
    for u in inventory:
        if u["kind"] == "attribute" and (u["file"], u["line"], u["symbol"]) in call_lines:
            continue
        if (u["file"], u["line"]) in broken_lines or (u["file"], u["line"]) in edits_import_lines:
            continue
        key = (u["file"], u["line"], u["col"], u["symbol"], u["kind"])
        if key in seen:
            continue
        seen.add(key)
        sym = u["symbol"]
        reasons: list[str] = []
        evidence: list[dict[str, str]] = []
        ch = diff["changed"].get(sym, {})
        if sym not in surface_new and (u["file"], u["line"], sym) not in covered:
            reasons.append("no longer in the indexed target API (the checker could not prove its absence)")
        if ch.get("newly_deprecated"):
            reasons.append("deprecated in the target version")
        if ch.get("default_changed") and u["kind"] == "call":
            given = {k["name"] for k in u.get("keywords", [])}
            for name, d in ch["default_changed"].items():
                if name not in given and not u.get("star"):
                    reasons.append(f"default of '{name}' changed from {d['from']} to {d['to']} and this call relies on it")
        if ch.get("returns_changed"):
            reasons.append(f"return annotation changed from {ch['returns_changed']['from']} to {ch['returns_changed']['to']}")
        if ch.get("param_kind_changed") or ch.get("annotation_changed") and not reasons:
            pass
        if sym in surface_new:
            evidence = _doc_evidence(sym, surface_new[sym], sections)
            if evidence and not reasons and u["kind"] != "import":
                reasons.append("the target documentation or changelog mentions a behaviour change")
        if reasons:
            at_risk.append({"file": u["file"], "line": u["line"], "col": u["col"], "symbol": sym, "reason": "; ".join(reasons),
                            "evidence": evidence})
        else:
            ok_count += 1
            if len(ok_sample) < MAX_LISTED:
                ok_sample.append({"file": u["file"], "line": u["line"], "symbol": sym})
    return broken, at_risk, ok_count, ok_sample, edits, manual


def _textual_leftovers(sources, diff, names, flagged: set[tuple[str, int]]):
    """Mentions of removed leaf names on values of unknown type: at risk, never broken."""
    leaves = {}
    for q in diff["removed"]:
        leaf = q.rsplit(".", 1)[-1]
        if not leaf.startswith("_") and "." in q:
            leaves.setdefault(leaf, []).append(q)
    out = []
    if not leaves:
        return out
    pattern = re.compile(r"\.(" + "|".join(re.escape(x) for x in leaves) + r")\b")
    for rel, text in sources.items():
        for i, line in enumerate(text.splitlines(), 1):
            if (rel, i) in flagged or line.lstrip().startswith("#"):
                continue
            m = pattern.search(line)
            if m:
                out.append({"file": rel, "line": i, "col": m.start(1), "symbol": "|".join(leaves[m.group(1)][:3]),
                            "reason": f"'.{m.group(1)}' matches a name removed in the target version; the receiver's type is unknown to the checker",
                            "evidence": [], "confidence": "text-match"})
    return out[:MAX_LISTED]


# --------------------------------------------------------------- applying
def apply_edits(sources: dict[str, str], edits: list[dict[str, Any]]) -> dict[str, str]:
    result = dict(sources)
    per_file: dict[str, list[dict[str, Any]]] = {}
    for e in edits:
        per_file.setdefault(e["file"], []).append(e)
    for rel, items in per_file.items():
        lines = result[rel].split("\n")
        last = None
        for e in sorted(items, key=lambda x: (x["line"], x["col"]), reverse=True):
            if last is not None and (e["line"], e["end_col"]) > last:
                continue  # overlapping edit: skip (kept in the manual list by the caller)
            ln = lines[e["line"] - 1]
            if ln[e["col"]:e["end_col"]] != e["old"]:
                continue
            lines[e["line"] - 1] = ln[:e["col"]] + e["new"] + ln[e["end_col"]:]
            last = (e["line"], e["col"])
        result[rel] = "\n".join(lines)
    return result


def _unified(sources: dict[str, str], edited: dict[str, str]) -> str:
    chunks = []
    for rel in sorted(sources):
        if sources[rel] != edited.get(rel, sources[rel]):
            chunks.extend(difflib.unified_diff(sources[rel].splitlines(keepends=True), edited[rel].splitlines(keepends=True),
                                               f"a/{rel}", f"b/{rel}"))
    return "".join(chunks)


# ------------------------------------------------------------- test runs
_FAIL_RE = re.compile(r"^(FAILED|ERROR)\s+(\S+)", re.M)


def _test_command(command: Any, python: str) -> list[str]:
    if command is None:
        return [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE"]
    argv = shlex.split(command, posix=os.name != "nt") if isinstance(command, str) else list(command)
    if not argv:
        raise RehearsalError("test_command is empty")
    if Path(argv[0]).name.lower().removesuffix(".exe") in ("python", "python3", "py"):
        return [python, *argv[1:]]
    if argv[0] == "pytest":
        return [python, "-m", "pytest", *argv[1:]]
    return argv


def _run_tests(directory: Path, argv: list[str], pythonpath: list[Path], timeout: float) -> dict[str, Any]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if pythonpath:
        env["PYTHONPATH"] = os.pathsep.join([*(str(p) for p in pythonpath), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])])
    started = time.perf_counter()
    try:
        done = subprocess.run(argv, cwd=directory, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        code, out, timed_out = done.returncode, (done.stdout or "") + (done.stderr or ""), False
    except subprocess.TimeoutExpired as exc:
        code, out, timed_out = None, ((exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")), True
    except OSError as exc:
        return {"exit_code": None, "error": str(exc), "failed": [], "seconds": 0.0}
    return {"exit_code": code, "timed_out": timed_out, "seconds": round(time.perf_counter() - started, 3),
            "failed": sorted({m.group(2) for m in _FAIL_RE.finditer(out)}), "summary": (out.strip().splitlines() or [""])[-1][:300],
            "output_tail": "\n".join(out.strip().splitlines()[-25:])[-3000:]}


def _copy_project(root: Path, dest: Path) -> None:
    def ignore(_dir, names):
        return [n for n in names if n in SKIP_DIRS or n.endswith((".egg-info", ".pyc"))]
    shutil.copytree(root, dest, ignore=ignore)


def _has_tests(root: Path) -> bool:
    return any(p.name.startswith("test_") or p.name.endswith("_test.py") for p in project_files(root))


# ------------------------------------------------------------------ main
def rehearse(
    project_path: str,
    package: str,
    target_version: str,
    *,
    old_version: str | None = None,
    old_path: str | None = None,
    new_path: str | None = None,
    import_names: list[str] | None = None,
    requirement: str | None = None,
    old_requirement: str | None = None,
    pip_args: list[str] | None = None,
    install_dependencies: bool = False,
    language: str = "python",
    run_tests: bool = True,
    test_command: Any = None,
    test_timeout: float = 300.0,
    changelog_paths: list[str] | None = None,
    pip_timeout: float = 600.0,
    keep_workdir: bool = False,
) -> dict[str, Any]:
    if language != "python":
        raise RehearsalError("unsupported_language: the upgrade rehearsal analyses Python projects only")
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        raise RehearsalError(f"project folder not found: {root}")
    if not package or not target_version:
        raise RehearsalError("package and target_version are required")
    project_python = environments.detect_project_python(root)
    python = str(project_python) if project_python else sys.executable
    work = Path(tempfile.mkdtemp(prefix="babel-rehearsal-"))
    try:
        return _rehearse(root, package, target_version, work, python, project_python is not None, locals())
    finally:
        if not keep_workdir:
            shutil.rmtree(work, ignore_errors=True)


def _rehearse(root: Path, package: str, target_version: str, work: Path, python: str, has_env: bool, opts: dict[str, Any]):
    pip_args = list(opts["pip_args"] or [])
    probe = environments.probe_python(Path(python))
    # ---- the two source trees (never the user's environment)
    isolation: dict[str, Any] = {"mode": "pip --target into a temp folder, user environment and project untouched"}
    dist = indexing.distribution_by_name(probe, package)
    old_version = opts["old_version"] or (dist["version"] if dist else None)
    old_dir: Path | None = Path(opts["old_path"]).resolve() if opts["old_path"] else None
    old_search: list[str]
    old_pythonpath: list[Path] = []
    if old_dir is not None:
        old_search = [str(old_dir)]
        old_pythonpath = [old_dir]
        old_version = old_version or _installed_version(old_dir, package) or "current"
        isolation["old"] = f"folder {old_dir}"
    elif dist is not None and not opts["old_requirement"] and (not opts["old_version"] or opts["old_version"] == dist["version"]):
        old_search = list(probe.get("sys_path") or [])
        isolation["old"] = f"the project's installed {package} {dist['version']} (read only)"
    elif old_version or opts["old_requirement"]:
        old_version = old_version or "previous"
        old_dir = work / "old"
        _pip_target(python, opts["old_requirement"] or f"{package}=={old_version}", old_dir, pip_args, opts["pip_timeout"], opts["install_dependencies"])
        old_search, old_pythonpath = [str(old_dir)], [old_dir]
        isolation["old"] = f"pip --target {opts['old_requirement'] or f'{package}=={old_version}'}"
    else:
        raise RehearsalError(f"{package} is not installed in the project environment; give old_version or old_path")
    if opts["new_path"]:
        new_dir = Path(opts["new_path"]).resolve()
        isolation["new"] = f"folder {new_dir}"
    else:
        new_dir = work / "new"
        _pip_target(python, opts["requirement"] or f"{package}=={target_version}", new_dir, pip_args, opts["pip_timeout"],
                    opts["install_dependencies"])
        isolation["new"] = f"pip --target {opts['requirement'] or f'{package}=={target_version}'}"
    new_version = _installed_version(new_dir, package) or target_version
    names = list(opts["import_names"] or [])
    if not names:
        names = (_import_names_in(new_dir, package) or (indexing.import_names_for(probe, dist) if dist else [])
                 or [package.replace("-", "_").lower()])
    base_paths = [p for p in (probe.get("sys_path") or []) if p not in old_search]

    def build(tag: str, version: str, search: list[str]):
        conn = db.connect(work / f"{tag}.db")
        env = environments.get_environment(conn, environments.builtin_env_id(conn))
        ids = []
        for n in names:
            lib = indexing.index_python_library(conn, env=env, probe=probe, import_name=n, dist_name=package, version=version,
                                                search_paths=[*search, *base_paths], force=True)
            if lib["status"] not in ("done", "partial"):
                raise RehearsalError(f"could not index {n} {version}: {lib.get('note')}")
            ids.append(lib["id"])
        return conn, env, ids

    conn_old, env_old, ids_old = build("old", old_version, old_search)
    conn_new, env_new, ids_new = build("new", new_version, [str(new_dir)])
    try:
        surface_old, surface_new = load_surface(conn_old, ids_old), load_surface(conn_new, ids_new)
        diff = diff_surfaces(surface_old, surface_new)
        files = project_files(root)
        inventory, base_findings, new_findings, unchecked, scanned, sources = _scan(conn_old, env_old, conn_new, env_new, files, root, names)
        sections = _changelog_sections([Path(p) for p in (opts["changelog_paths"] or [])] or _discover_changelogs([new_dir]))
        statements = _import_statements(sources, names)
        import_edits, import_manual, import_broken = _propose_import_moves(statements, diff, surface_old, surface_new)
        import_lines = {(b["file"], b["line"]) for b in import_broken}
        broken, at_risk, ok_count, ok_sample, edits, manual = _classify(inventory, base_findings, new_findings, diff, surface_new,
                                                                        sources, sections, import_lines)
        broken = import_broken + broken
        manual = import_manual + manual
        edits = import_edits + edits
        flagged = {(x["file"], x["line"]) for x in [*broken, *at_risk]}
        at_risk += _textual_leftovers(sources, diff, names, flagged)
        edited = apply_edits(sources, edits)
        applied = [e for e in edits if sources[e["file"]] != edited[e["file"]]]
        plan = {"mechanical_edits": edits, "manual": manual, "diff": _unified(sources, edited),
                "note": "Edits are proposals. They are applied only to a throwaway copy; the project itself is never modified."}
        tests = _rehearse_tests(root, work, python, old_pythonpath, [new_dir], edited, sources, opts) if opts["run_tests"] else \
            {"skipped": "run_tests is false"}
    finally:
        conn_old.close()
        conn_new.close()
    changed_breaking = {q: c for q, c in diff["changed"].items() if c.get("breaking")}
    summary = {
        "package": package, "from": old_version, "to": new_version,
        "verdict": "breaking" if broken or (isinstance(tests, dict) and tests.get("regressions")) else "at_risk" if at_risk else "safe_on_checked_uses",
        "broken": len(broken), "at_risk": len(at_risk), "ok": ok_count, "unchecked_nodes": unchecked,
        "mechanical_edits": len(edits), "manual_items": len(manual), "files_scanned": scanned,
        "api": {"removed": len(diff["removed"]), "moved": len(diff["moved"]), "changed": len(diff["changed"]),
                "breaking_signature_changes": len(changed_breaking), "added": len(diff["added"])},
    }
    api = {"removed": [{"symbol": q, "kind": surface_old[q]["kind"], **({"moved_to": diff["moved"][q]} if q in diff["moved"] else {}),
                        **({"candidates": diff["ambiguous_moves"][q]} if q in diff["ambiguous_moves"] else {})} for q in diff["removed"][:MAX_LISTED]],
           "changed": {q: c for q, c in list(diff["changed"].items())[:MAX_LISTED]},
           "added_count": len(diff["added"]), "added_sample": diff["added"][:20],
           "removed_total": diff["removed_total"]}
    return {"ok": not broken, "language": "python", "package": package, "old_version": old_version, "new_version": new_version,
            "import_names": names, "isolation": isolation, "summary": summary, "api_diff": api,
            "uses": {"broken": broken[:MAX_LISTED], "at_risk": at_risk[:MAX_LISTED], "ok_count": ok_count, "ok_sample": ok_sample,
                     "unchecked_nodes": unchecked},
            "plan": plan, "tests": tests, "changelog_sections_read": len(sections), "limitations": LIMITATIONS}


def _rehearse_tests(root, work, python, old_pythonpath, new_pythonpath, edited, sources, opts):
    argv = _test_command(opts["test_command"], python)
    if opts["test_command"] is None and not _has_tests(root):
        return {"skipped": "no test files found and no test_command given"}
    results: dict[str, Any] = {"command": argv[1:] if argv and argv[0] == python else argv}
    copies = {}
    for tag in ("before", "after", "after_edits"):
        dest = work / f"copy_{tag}"
        _copy_project(root, dest)
        copies[tag] = dest
    for rel, text in edited.items():
        if text != sources[rel]:
            (copies["after_edits"] / rel).write_text(text, encoding="utf-8", newline="")
    results["before"] = _run_tests(copies["before"], argv, old_pythonpath, opts["test_timeout"])
    results["after"] = _run_tests(copies["after"], argv, new_pythonpath, opts["test_timeout"])
    results["after_edits"] = _run_tests(copies["after_edits"], argv, new_pythonpath, opts["test_timeout"])

    def regress(a, b):
        if a.get("exit_code") not in (0, None) and not a["failed"]:
            return []
        gone = [t for t in b["failed"] if t not in a["failed"]]
        if not gone and a.get("exit_code") == 0 and b.get("exit_code") not in (0, None):
            return ["(run failed; no individual test ids reported)"]
        return gone
    results["regressions"] = regress(results["before"], results["after"])
    results["regressions_after_edits"] = regress(results["before"], results["after_edits"])
    remaining = results["regressions_after_edits"]
    results["fixed_by_edits"] = [t for t in results["regressions"] if t not in remaining and not any(r.startswith(t + "::") for r in remaining)]
    results["partly_fixed_by_edits"] = [t for t in results["regressions"] if "::" not in t and any(r.startswith(t + "::") for r in remaining)]
    results["note"] = ("Runs happen in throwaway copies of the project with the old and the new version put first on PYTHONPATH; "
                       "the project folder is untouched.")
    return results
