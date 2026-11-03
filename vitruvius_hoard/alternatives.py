"""Design by comparable alternatives: frozen criteria, structural diversity, measured trade-offs, a recorded decision.

A study holds a brief, criteria that are frozen once anything is measured, and 2..N alternatives (pages, application
projects or editable diagrams) that must differ in structure, not only in colour. Every alternative is measured with the
existing tools; ranking, Pareto frontier and trade-off text are computed from stored measurements, so changing a weight
never re-measures.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import re
import threading
import time
import urllib.request
import uuid
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional

from .hoard_link.atomic import write_json_atomic

KINDS = ("page", "app_project", "diagram_document")
DEFAULT_THRESHOLD = 0.2
MAX_ALTERNATIVES = 12
MAX_HTML = 1_500_000
EPS = 1e-9

WEB = ("page", "app_project")
SOURCES: dict[str, dict[str, Any]] = {
    "critique_score": {"direction": "max", "kinds": WEB, "what": "design critique score (0-10, heuristics only, no vision model)"},
    "lint_score": {"direction": "max", "kinds": WEB, "what": "design lint score (0-10) from the render"},
    "page_check_failed": {"direction": "min", "kinds": WEB, "what": "cases that failed in page_check"},
    "contrast_failures": {"direction": "min", "kinds": WEB, "what": "text/background pairs under WCAG AA"},
    "contrast_min_ratio": {"direction": "max", "kinds": WEB, "what": "lowest text contrast ratio"},
    "small_tap_targets": {"direction": "min", "kinds": WEB, "what": "touch targets below 44px"},
    "dom_size": {"direction": "min", "kinds": WEB, "what": "DOM elements"},
    "external_libs": {"direction": "min", "kinds": WEB, "what": "external libraries loaded"},
    "render_ms": {"direction": "min", "kinds": WEB, "what": "capture time in milliseconds (varies between runs)"},
    "page_bytes": {"direction": "min", "kinds": WEB, "what": "HTML size in bytes"},
    "diagram_gate_failures": {"direction": "min", "kinds": ("diagram_document",), "what": "legibility gates that fail"},
    "diagram_nodes": {"direction": "min", "kinds": ("diagram_document",), "what": "nodes"},
    "diagram_edges": {"direction": "min", "kinds": ("diagram_document",), "what": "edges"},
    "manual": {"direction": "max", "kinds": KINDS, "what": "a judgement score with a written rationale"},
}
_RENDER_SOURCES = {"lint_score", "contrast_failures", "contrast_min_ratio", "small_tap_targets", "dom_size", "external_libs", "render_ms", "critique_score"}


# ---------------- structural fingerprints ----------------

_LANDMARKS = ("header", "nav", "main", "aside", "section", "article", "footer", "form", "table", "ul", "ol", "dl", "h1", "h2", "h3",
              "button", "input", "select", "textarea", "img", "svg", "canvas", "video", "details", "dialog")
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_IGNORED = {"script", "style", "head", "title", "meta", "link", "noscript", "template", "html"}


class _Outline(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.paths: Counter = Counter()
        self.tags: Counter = Counter()
        self.css: list[str] = []
        self._style = False

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "style" and value:
                self.css.append(value)
        if tag == "style":
            self._style = True
        if tag in _IGNORED:
            if tag not in _VOID:
                self.stack.append(tag)
            return
        if any(t in ("head", "template") for t in self.stack):
            return
        self.tags[tag] += 1
        self.paths[">".join([t for t in self.stack[-3:] if t not in _IGNORED] + [tag])] += 1
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID and self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag == "style":
            self._style = False
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass

    def handle_data(self, data):
        if self._style:
            self.css.append(data)


def _layout_modes(css: str) -> list[str]:
    css = re.sub(r"/\*.*?\*/", "", css.lower(), flags=re.S)
    modes: set[str] = set()
    if re.search(r"display\s*:\s*(inline-)?grid", css):
        modes.add("grid")
    if re.search(r"display\s*:\s*(inline-)?flex", css):
        modes.add("flex-column" if re.search(r"flex-direction\s*:\s*column", css) else "flex-row")
    if re.search(r"display\s*:\s*table", css):
        modes.add("table")
    if re.search(r"float\s*:\s*(left|right)", css):
        modes.add("float")
    if re.search(r"column-count\s*:|[^-]columns\s*:", css):
        modes.add("columns")
    for match in re.finditer(r"position\s*:\s*(absolute|fixed|sticky)", css):
        modes.add("positioned-" + match.group(1))
    for match in re.finditer(r"grid-template-columns\s*:\s*([^;}]+)", css):
        value = match.group(1).strip()
        repeat = re.match(r"repeat\(\s*(\d+)\s*,", value)
        if repeat:
            modes.add(f"grid-cols:{repeat.group(1)}")
        elif "auto-fit" in value or "auto-fill" in value:
            modes.add("grid-cols:auto")
        else:
            depth, tokens, current = 0, 0, ""
            for char in value:
                depth += char == "("
                depth -= char == ")"
                if char.isspace() and depth == 0:
                    tokens += bool(current)
                    current = ""
                else:
                    current += char
            tokens += bool(current)
            modes.add(f"grid-cols:{tokens}")
    return sorted(modes)


def fingerprint_html(source: str) -> dict[str, Any]:
    """Element-path multiset, landmark counts and layout modes. Text, colours, fonts and class names do not take part."""
    parser = _Outline()
    parser.feed(source)
    parser.close()
    return {"kind": "dom", "paths": dict(parser.paths), "counts": {t: parser.tags[t] for t in _LANDMARKS if parser.tags[t]},
            "layout": _layout_modes("\n".join(parser.css)), "elements": sum(parser.tags.values())}


def fingerprint_project(files: dict[str, str]) -> dict[str, Any]:
    pages = [text for name, text in sorted(files.items()) if name == "layout.html" or (name.startswith("pages/") and name.endswith(".html"))]
    styles = [text for name, text in sorted(files.items()) if name.endswith(".css")]
    fp = fingerprint_html("\n".join(pages) + "".join(f"<style>{c}</style>" for c in styles))
    fp["source"] = "application pages and stylesheets"
    return fp


def fingerprint_diagram(content: dict[str, Any]) -> dict[str, Any]:
    diagram = content.get("diagram") or {}
    nodes, edges = diagram.get("nodes") or [], diagram.get("edges") or []
    degree: Counter = Counter()
    for edge in edges:
        degree[edge.get("from")] += 1
        degree[edge.get("to")] += 1
    paths: Counter = Counter()
    paths[f"type:{diagram.get('type', 'flowchart')}"] += 1
    for node in nodes:
        paths[f"node:{node.get('shape') or node.get('kind') or 'box'}"] += 1
        paths[f"degree:{min(degree[node.get('id')], 6)}"] += 1
    groups = diagram.get("groups") or []
    return {"kind": "diagram", "paths": dict(paths), "counts": {"nodes": len(nodes), "edges": len(edges), "groups": len(groups)},
            "layout": [f"type:{diagram.get('type', 'flowchart')}"], "elements": len(nodes) + len(edges)}


def _weighted_jaccard(a: dict[str, int], b: dict[str, int]) -> float:
    keys = set(a) | set(b)
    high = sum(max(a.get(k, 0), b.get(k, 0)) for k in keys)
    return 1.0 if high == 0 else sum(min(a.get(k, 0), b.get(k, 0)) for k in keys) / high


def distance_parts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, float]:
    if a["kind"] != b["kind"]:
        return {"paths": 1.0, "counts": 1.0, "layout": 1.0, "distance": 1.0}
    paths = 1 - _weighted_jaccard(a["paths"], b["paths"])
    keys = set(a["counts"]) | set(b["counts"])
    high = sum(max(a["counts"].get(k, 0), b["counts"].get(k, 0)) for k in keys)
    counts = 0.0 if high == 0 else sum(abs(a["counts"].get(k, 0) - b["counts"].get(k, 0)) for k in keys) / high
    la, lb = set(a["layout"]), set(b["layout"])
    layout = 0.0 if not (la | lb) else 1 - len(la & lb) / len(la | lb)
    return {"paths": round(paths, 4), "counts": round(counts, 4), "layout": round(layout, 4),
            "distance": round(0.5 * paths + 0.2 * counts + 0.3 * layout, 4)}


def diversity_report(items: list[tuple[str, dict[str, Any]]], threshold: float = DEFAULT_THRESHOLD) -> dict[str, Any]:
    """Pairwise structural distance. Pairs under the threshold are 'too similar' and the study is refused."""
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            parts = distance_parts(items[i][1], items[j][1])
            pairs.append({"a": items[i][0], "b": items[j][0], **parts, "similar": parts["distance"] < threshold})
    similar = [p for p in pairs if p["similar"]]
    return {"threshold": threshold, "pairs": pairs, "ok": not similar, "message": _similarity_message(similar, threshold) if similar else ""}


def _similarity_message(similar: list[dict[str, Any]], threshold: float) -> str:
    lines = []
    for p in similar:
        same = []
        if p["paths"] == 0:
            same.append("the same element structure")
        if p["layout"] == 0:
            same.append("the same layout modes")
        detail = (" with " + " and ".join(same) + "; they differ only in colour, typography, spacing or wording") if p["paths"] == 0 and p["layout"] == 0 else ""
        lines.append(f"'{p['a']}' and '{p['b']}' are structurally {p['distance']:.2f} apart (minimum {threshold:.2f}){detail}")
    return ("These alternatives are variants, not alternatives: " + "; ".join(lines) + ". A comparison of colours or fonts tests taste, not design. "
            "Change the information hierarchy, the layout (columns, grid, flow), the component set or the navigation, and submit them again.")


# ---------------- criteria and analysis ----------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")[:40] or "criterion"


def normalise_criteria(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 12:
        raise ValueError("A study needs 1 to 12 criteria")
    out, seen = [], set()
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError("Each criterion needs a name")
        source = item.get("source")
        if source not in SOURCES:
            raise ValueError(f"Criterion '{item['name']}' source must be one of " + ", ".join(SOURCES))
        direction = item.get("direction") or SOURCES[source]["direction"]
        if direction not in ("max", "min"):
            raise ValueError(f"Criterion '{item['name']}' direction must be max or min")
        weight = item.get("weight", 1)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight < 0 or weight > 1000:
            raise ValueError(f"Criterion '{item['name']}' weight must be a number from 0 to 1000")
        params = item.get("params") or {}
        if source == "manual":
            low, high = params.get("min", 0), params.get("max", 10)
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (low, high)) or low >= high:
                raise ValueError(f"Manual criterion '{item['name']}' needs params min < max (default 0 to 10)")
            params = {"min": low, "max": high}
        identifier = item.get("id") or _slug(item["name"])
        if identifier in seen:
            raise ValueError(f"Two criteria share the id '{identifier}'")
        seen.add(identifier)
        out.append({"id": identifier, "name": item["name"].strip(), "source": source, "direction": direction, "weight": weight,
                    "params": params, "why": str(item.get("why", ""))[:400]})
    if not any(c["weight"] > 0 for c in out):
        raise ValueError("At least one criterion needs a weight above 0")
    return out


def _definition(criterion: dict[str, Any]) -> tuple:
    return (criterion["source"], criterion["direction"], json.dumps(criterion["params"], sort_keys=True))


def _oriented(criterion: dict[str, Any], value: float) -> float:
    return value if criterion["direction"] == "max" else -value


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") if abs(value) < 1000 else f"{value:.0f}"


def analyze(criteria: list[dict[str, Any]], alternatives: list[dict[str, Any]], weights: Optional[dict[str, float]] = None) -> dict[str, Any]:
    """Ranking, Pareto frontier and trade-offs from stored measures. ``weights`` override the frozen weights for what-if."""
    missing = [{"alternative": a["id"], "criterion": c["id"]} for a in alternatives for c in criteria if c["id"] not in a.get("measures", {})]
    if missing:
        return {"complete": False, "missing": missing}
    unknown = set(weights or {}) - {c["id"] for c in criteria}
    if unknown:
        raise ValueError("Unknown criteria in weights: " + ", ".join(sorted(unknown)))
    used = {c["id"]: float((weights or {}).get(c["id"], c["weight"])) for c in criteria}
    if any(w < 0 for w in used.values()) or sum(used.values()) <= 0:
        raise ValueError("Weights must be zero or more, with at least one above zero")
    total = sum(used.values())
    labels = {a["id"]: a["label"] for a in alternatives}
    value = {a["id"]: {c["id"]: float(a["measures"][c["id"]]["value"]) for c in criteria} for a in alternatives}
    oriented = {a: {c["id"]: _oriented(c, value[a][c["id"]]) for c in criteria} for a in value}
    normal: dict[str, dict[str, float]] = {a: {} for a in value}
    for c in criteria:
        low, high = min(oriented[a][c["id"]] for a in value), max(oriented[a][c["id"]] for a in value)
        for a in value:
            normal[a][c["id"]] = 1.0 if high - low < EPS else (oriented[a][c["id"]] - low) / (high - low)
    score = {a: round(sum(used[c["id"]] / total * normal[a][c["id"]] for c in criteria), 6) for a in value}
    order = sorted(value, key=lambda a: (-score[a], labels[a]))
    ranking = [{"rank": i + 1, "id": a, "label": labels[a], "score": score[a]} for i, a in enumerate(order)]

    def dominates(a: str, b: str) -> bool:
        ge = all(oriented[a][c["id"]] >= oriented[b][c["id"]] - EPS for c in criteria)
        gt = any(oriented[a][c["id"]] > oriented[b][c["id"]] + EPS for c in criteria)
        return ge and gt
    dominated_by = {a: [b for b in value if b != a and dominates(b, a)] for a in value}
    frontier = [a for a in order if not dominated_by[a]]
    names = {c["id"]: c["name"] for c in criteria}

    def pair_text(a: str, b: str) -> dict[str, Any]:
        better = [c for c in criteria if oriented[a][c["id"]] > oriented[b][c["id"]] + EPS]
        worse = [c for c in criteria if oriented[a][c["id"]] < oriented[b][c["id"]] - EPS]
        said = lambda cs, x, y: ", ".join(f"{names[c['id']]} ({_fmt(value[x][c['id']])} vs {_fmt(value[y][c['id']])})" for c in cs)  # noqa: E731
        if better and worse:
            text = f"{labels[a]} is better on {said(better, a, b)}, but yields on {said(worse, a, b)}."
        elif better:
            text = f"{labels[a]} is at least as good as {labels[b]} on every criterion and better on {said(better, a, b)}."
        elif worse:
            text = f"{labels[a]} is no better than {labels[b]} anywhere and yields on {said(worse, a, b)}."
        else:
            text = f"{labels[a]} and {labels[b]} measure the same on every criterion."
        return {"a": a, "b": b, "a_better_on": [c["id"] for c in better], "a_worse_on": [c["id"] for c in worse], "text": text}

    tradeoffs = [pair_text(a, b) for i, a in enumerate(frontier) for b in frontier[i + 1:]]
    for a in order:
        for b in dominated_by[a][:1]:
            t = pair_text(b, a)
            tradeoffs.append({**t, "text": f"{labels[a]} is dominated by {labels[b]}: {labels[b]} is at least as good on every criterion and better on "
                              + ", ".join(f"{names[c]} ({_fmt(value[b][c])} vs {_fmt(value[a][c])})" for c in t["a_better_on"]) + "."})
    leads = {}
    for a in value:
        best = [c["id"] for c in criteria if oriented[a][c["id"]] >= max(oriented[x][c["id"]] for x in value) - EPS and
                max(oriented[x][c["id"]] for x in value) - min(oriented[x][c["id"]] for x in value) > EPS]
        worst = [c["id"] for c in criteria if oriented[a][c["id"]] <= min(oriented[x][c["id"]] for x in value) + EPS and
                 max(oriented[x][c["id"]] for x in value) - min(oriented[x][c["id"]] for x in value) > EPS]
        leads[a] = {"leads_on": best, "yields_on": worst}
    return {"complete": True, "weights": {k: round(v / total, 6) for k, v in used.items()}, "ranking": ranking, "leader": order[0],
            "scores": {a: {"total": score[a], "by_criterion": {k: round(v, 6) for k, v in normal[a].items()}} for a in value},
            "values": value, "frontier": frontier, "dominated": {a: {"by": dominated_by[a]} for a in value if dominated_by[a]},
            "leads": leads, "tradeoffs": tradeoffs}


def reweight(criteria, alternatives, weights: dict[str, float]) -> dict[str, Any]:
    """What changes if the weights change; nothing is measured again."""
    before, after = analyze(criteria, alternatives), analyze(criteria, alternatives, {**{c["id"]: c["weight"] for c in criteria}, **weights})
    if not before["complete"]:
        return before
    rank = {r["id"]: r["rank"] for r in before["ranking"]}
    changes = [{"id": r["id"], "label": r["label"], "rank_before": rank[r["id"]], "rank_after": r["rank"], "score_after": r["score"]} for r in after["ranking"]]
    labels = {a["id"]: a["label"] for a in alternatives}
    effect = (f"The leader stays {labels[after['leader']]}." if before["leader"] == after["leader"]
              else f"The leader changes from {labels[before['leader']]} to {labels[after['leader']]}.")
    return {**after, "baseline_weights": before["weights"], "baseline_leader": before["leader"], "changes": changes, "leader_changed": before["leader"] != after["leader"],
            "effect": effect, "frontier_unchanged": before["frontier"] == after["frontier"] or set(before["frontier"]) == set(after["frontier"]),
            "note": "Weights never change the Pareto frontier; they only choose a point on it. Nothing was measured again."}


def sensitivity(criteria, alternatives, criterion_id: str, steps: int = 20) -> dict[str, Any]:
    """Share of the weight on one criterion (others keep their proportions) at which the leader changes."""
    target = next((c for c in criteria if c["id"] == criterion_id), None)
    if target is None:
        raise ValueError(f"Unknown criterion '{criterion_id}'")
    others = [c for c in criteria if c["id"] != criterion_id]
    rest = sum(c["weight"] for c in others)
    labels = {a["id"]: a["label"] for a in alternatives}
    rows, breaks, last = [], [], None
    for k in range(steps + 1):
        share = k / steps
        weights = {c["id"]: (c["weight"] / rest * (1 - share) if rest > 0 else (1 - share) / max(1, len(others))) for c in others}
        weights[criterion_id] = share
        result = analyze(criteria, alternatives, weights)
        if not result["complete"]:
            return result
        rows.append({"weight": share, "leader": result["leader"]})
        if last is not None and result["leader"] != last:
            breaks.append({"at_weight": share, "from": last, "to": result["leader"], "text": f"{labels[result['leader']]} overtakes {labels[last]} once '{target['name']}' carries about {round(share * 100)}% of the weight."})
        last = result["leader"]
    return {"complete": True, "criterion": criterion_id, "leaders": rows, "breaks": breaks,
            "stable": not breaks, "text": "The leader does not change however much weight this criterion carries." if not breaks else " ".join(b["text"] for b in breaks)}


# ---------------- measures from existing tools ----------------

def contrast_stats(probe: dict[str, Any]) -> dict[str, Any]:
    from .lint import _parse_rgb, _to_hex
    from .tokens import contrast_ratio
    ratios, failures = [], []
    for pair in probe.get("contrast_pairs") or []:
        fg, bg = _parse_rgb(pair.get("color")), _parse_rgb(pair.get("background"))
        if not fg or not bg:
            continue
        ratio = contrast_ratio(_to_hex(fg), _to_hex(bg))
        size = float(pair.get("size") or 16)
        weight = int(str(pair.get("weight") or "400").replace("bold", "700").replace("normal", "400") or 400)
        large = size >= 24 or (size >= 18.66 and weight >= 700)
        ratios.append(ratio)
        if ratio < (3.0 if large else 4.5):
            failures.append({"text": pair.get("text"), "ratio": round(ratio, 2)})
    return {"min_ratio": round(min(ratios), 2) if ratios else 21.0, "failures": len(failures), "worst": sorted(failures, key=lambda f: f["ratio"])[:5]}


class AlternativeStudies:
    def __init__(self, services):
        self.services = services
        self.root = Path(services.config.data_dir) / "alternatives"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    # ---------- storage ----------
    def _path(self, id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{12}", id or ""):
            raise ValueError("Invalid study id")
        return self.root / f"{id}.json"

    def _load(self, id: str) -> dict[str, Any]:
        path = self._path(id)
        if not path.is_file():
            raise LookupError("Alternatives study not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, study: dict[str, Any]) -> None:
        study["updated_ts"] = time.time()
        write_json_atomic(self._path(study["id"]), study)

    @staticmethod
    def frozen(study: dict[str, Any]) -> bool:
        return bool(study.get("decision")) or any(a.get("measures") for a in study["alternatives"])

    def _public(self, study: dict[str, Any], with_analysis=True) -> dict[str, Any]:
        out = {k: v for k, v in study.items() if k not in ("alternatives",)}
        out["frozen"] = self.frozen(study)
        out["alternatives"] = [{k: v for k, v in a.items() if k not in ("html", "fingerprint")} | {"structure": {"elements": a["fingerprint"].get("elements"), "layout": a["fingerprint"].get("layout")}} for a in study["alternatives"]]
        out["diversity"] = diversity_report([(a["label"], a["fingerprint"]) for a in study["alternatives"]], study["diversity_threshold"])
        if with_analysis:
            out["analysis"] = analyze(study["criteria"], study["alternatives"])
        return out

    # ---------- alternatives ----------
    def _resolve(self, raw: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("Each alternative must be an object")
        kind = raw.get("kind") or ("app_project" if raw.get("project_id") else "diagram_document" if raw.get("document_id") else "page")
        if kind not in KINDS:
            raise ValueError("Alternative kind must be one of " + ", ".join(KINDS))
        label = str(raw.get("label") or "").strip()
        if not label:
            raise ValueError("Each alternative needs a label")
        out: dict[str, Any] = {"label": label[:80], "kind": kind, "intent": str(raw.get("intent", ""))[:400]}
        if kind == "page":
            if raw.get("html"):
                source = raw["html"]
            elif raw.get("path"):
                from .agent_tools import read_local_page
                source = read_local_page(raw["path"])
            else:
                raise ValueError(f"Page alternative '{label}' needs html or path")
            if len(source) > MAX_HTML:
                raise ValueError(f"Alternative '{label}' is larger than {MAX_HTML // 1000} KB")
            out.update(html=source, sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(), bytes=len(source.encode("utf-8")), fingerprint=fingerprint_html(source))
        elif kind == "app_project":
            project = self.services.app_projects.get(raw.get("project_id") or "", raw.get("revision"))
            out.update(project_id=project["id"], revision=project["selected_revision"], sha256=project["source_sha256"], fingerprint=fingerprint_project(project["files"]))
        else:
            document = self.services_documents().get(raw.get("document_id") or "", raw.get("revision"))
            out.update(document_id=document["id"], revision=document["revision"], sha256=hashlib.sha256(json.dumps(document["content"], sort_keys=True).encode()).hexdigest(),
                       fingerprint=fingerprint_diagram(document["content"]))
        return out

    def services_documents(self):
        from .diagrams.documents import DocumentStore
        return DocumentStore(self.services.config.data_dir)

    def _check_applicable(self, criteria, alternatives):
        for a in alternatives:
            for c in criteria:
                if a["kind"] not in SOURCES[c["source"]]["kinds"]:
                    raise ValueError(f"Criterion '{c['name']}' ({c['source']}) cannot be measured on '{a['label']}' ({a['kind']}); use a manual criterion or compare alternatives of the same kind")

    def create(self, brief: str, criteria: Any, alternatives: Any, diversity_threshold: float = DEFAULT_THRESHOLD, check_only: bool = False) -> dict[str, Any]:
        if not isinstance(brief, str) or len(brief.strip()) < 8:
            raise ValueError("A study needs a brief of at least a sentence")
        criteria = normalise_criteria(criteria)
        if not isinstance(alternatives, list) or not 2 <= len(alternatives) <= MAX_ALTERNATIVES:
            raise ValueError(f"A study needs 2 to {MAX_ALTERNATIVES} alternatives")
        resolved = [self._resolve(a) for a in alternatives]
        labels = [a["label"] for a in resolved]
        if len(set(labels)) != len(labels):
            raise ValueError("Alternative labels must be unique")
        self._check_applicable(criteria, resolved)
        diversity = diversity_report([(a["label"], a["fingerprint"]) for a in resolved], diversity_threshold)
        if check_only:
            return {"checked_only": True, "criteria": criteria, "diversity": diversity}
        if not diversity["ok"]:
            raise ValueError(diversity["message"])
        for i, a in enumerate(resolved, 1):
            a.update(id=f"a{i}", measures={}, added_ts=time.time())
        study = {"id": uuid.uuid4().hex[:12], "brief": brief.strip(), "revision": 1, "criteria": criteria, "diversity_threshold": diversity_threshold,
                 "alternatives": resolved, "decision": None, "history": [], "created_ts": time.time()}
        with self.lock:
            self._save(study)
        return self._public(study)

    def list(self) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(self.root.glob("*.json")):
            study = json.loads(path.read_text(encoding="utf-8"))
            analysis = analyze(study["criteria"], study["alternatives"])
            rows.append({"id": study["id"], "brief": study["brief"][:160], "revision": study["revision"], "alternatives": len(study["alternatives"]),
                         "criteria": len(study["criteria"]), "frozen": self.frozen(study), "complete": analysis["complete"],
                         "decided": (study["decision"] or {}).get("alternative_id"), "updated_ts": study["updated_ts"]})
        return sorted(rows, key=lambda r: r["updated_ts"], reverse=True)

    def get(self, id: str) -> dict[str, Any]:
        return self._public(self._load(id))

    def add_alternative(self, id: str, alternative: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            study = self._load(id)
            if study.get("decision"):
                raise ValueError("This study has a decision; start a new criteria revision before adding alternatives")
            if len(study["alternatives"]) >= MAX_ALTERNATIVES:
                raise ValueError(f"A study holds at most {MAX_ALTERNATIVES} alternatives")
            new = self._resolve(alternative)
            if new["label"] in {a["label"] for a in study["alternatives"]}:
                raise ValueError("Alternative labels must be unique")
            self._check_applicable(study["criteria"], [new])
            diversity = diversity_report([(a["label"], a["fingerprint"]) for a in study["alternatives"]] + [(new["label"], new["fingerprint"])], study["diversity_threshold"])
            if not diversity["ok"]:
                raise ValueError(diversity["message"])
            new.update(id=f"a{max(int(a['id'][1:]) for a in study['alternatives']) + 1}", measures={}, added_ts=time.time())
            study["alternatives"].append(new)
            self._save(study)
            return self._public(study)

    # ---------- criteria ----------
    def set_criteria(self, id: str, criteria: Any, new_revision: bool = False, reason: str = "") -> dict[str, Any]:
        with self.lock:
            study = self._load(id)
            criteria = normalise_criteria(criteria)
            self._check_applicable(criteria, study["alternatives"])
            if not self.frozen(study):
                study["criteria"] = criteria
                self._save(study)
                return self._public(study)
            if not new_revision:
                raise ValueError("The criteria are frozen: alternatives have been measured against them. Create a new study revision (new_revision=true, with a reason) to change them; measures of unchanged criteria carry over.")
            if len(reason.strip()) < 8:
                raise ValueError("A new revision needs the reason the criteria changed")
            study["history"].append({"revision": study["revision"], "criteria": study["criteria"], "decision": study.get("decision"), "ended_ts": time.time(), "reason": reason.strip(),
                                     "measures": {a["id"]: a["measures"] for a in study["alternatives"]}})
            old = {c["id"]: _definition(c) for c in study["criteria"]}
            keep = {c["id"] for c in criteria if old.get(c["id"]) == _definition(c)}
            for a in study["alternatives"]:
                a["measures"] = {k: v for k, v in a["measures"].items() if k in keep}
            study.update(criteria=criteria, revision=study["revision"] + 1, decision=None)
            self._save(study)
            out = self._public(study)
            out["carried_over"] = sorted(keep)
            out["remeasure"] = [c["id"] for c in criteria if c["id"] not in keep]
            return out

    # ---------- measuring ----------
    def evaluate(self, id: str, manual_scores: Optional[list[dict[str, Any]]] = None, remeasure: bool = False) -> dict[str, Any]:
        with self.lock:
            study = self._load(id)
            criteria = {c["id"]: c for c in study["criteria"]}
            by_alt = {a["id"]: a for a in study["alternatives"]}
            for entry in manual_scores or []:
                alt, crit = by_alt.get(entry.get("alternative")), criteria.get(entry.get("criterion"))
                if alt is None or crit is None or crit["source"] != "manual":
                    raise ValueError("Manual scores need an existing alternative id and a manual criterion id")
                score, why = entry.get("score"), str(entry.get("rationale", "")).strip()
                low, high = crit["params"]["min"], crit["params"]["max"]
                if isinstance(score, bool) or not isinstance(score, (int, float)) or not low <= score <= high:
                    raise ValueError(f"Score for '{crit['name']}' must be a number from {low} to {high}")
                if len(why) < 8:
                    raise ValueError("A manual score needs a written rationale")
                alt["measures"][crit["id"]] = {"value": score, "source": "manual", "rationale": why, "measured_ts": time.time()}
            measured = []
            for alt in study["alternatives"]:
                wanted = [c for c in study["criteria"] if c["source"] != "manual" and (remeasure or c["id"] not in alt["measures"])]
                if wanted:
                    values = self._measure(alt, {c["source"] for c in wanted})
                    for c in wanted:
                        got = values[c["source"]]
                        alt["measures"][c["id"]] = {"value": got["value"], "source": c["source"], "detail": got.get("detail"), "measured_ts": time.time()}
                    measured.append(alt["id"])
            self._save(study)
            out = self._public(study)
            out["measured"] = measured
            out["awaiting_manual"] = [{"alternative": a["id"], "criterion": c["id"], "scale": f"{c['params']['min']} to {c['params']['max']}"}
                                      for a in study["alternatives"] for c in study["criteria"] if c["source"] == "manual" and c["id"] not in a["measures"]]
            return out

    def _measure(self, alt: dict[str, Any], sources: set[str]) -> dict[str, dict[str, Any]]:
        s = self.services
        out: dict[str, dict[str, Any]] = {}
        if alt["kind"] == "diagram_document":
            from .diagrams.documents import drawing
            document = self.services_documents().get(alt["document_id"], alt["revision"])
            result = drawing(document["content"])
            failing = [g for g in result["gates"] if not g["ok"]]
            diagram = document["content"]["diagram"]
            values = {"diagram_gate_failures": {"value": len(failing), "detail": [g.get("name") or g.get("id") for g in failing][:8]},
                      "diagram_nodes": {"value": len(diagram.get("nodes") or [])}, "diagram_edges": {"value": len(diagram.get("edges") or [])}}
            return {k: v for k, v in values.items() if k in sources}
        html = alt.get("html")
        row = None
        if alt["kind"] == "page":
            if sources & _RENDER_SOURCES:
                row = s.render(html=html, widths=[390, 1440], lint=True, title=alt["label"])
        else:
            preview = s.app_projects.preview(alt["project_id"], alt["revision"])
            with urllib.request.urlopen(preview["url"] + "/", timeout=10) as response:
                html = response.read().decode("utf-8", "replace")
            if sources & _RENDER_SOURCES:
                row = s.app_project_render(alt["project_id"], alt["revision"])
        if row is not None and "error" in (row.get("metrics") or {}):
            raise ValueError("Measuring needs the browser: " + str(row["metrics"].get("error")) + " " + str(row["metrics"].get("hint") or ""))
        probe = (row or {}).get("_probe") or {}
        if "contrast_failures" in sources or "contrast_min_ratio" in sources:
            stats = contrast_stats(probe)
            out["contrast_failures"] = {"value": stats["failures"], "detail": stats["worst"]}
            out["contrast_min_ratio"] = {"value": stats["min_ratio"], "detail": stats["worst"]}
        if row is not None:
            out["lint_score"] = {"value": row["lint"].get("score"), "detail": row["lint"].get("counts")}
            out["small_tap_targets"] = {"value": probe.get("small_tap_targets") or 0}
            out["dom_size"] = {"value": probe.get("dom_size") or 0}
            out["external_libs"] = {"value": len(probe.get("external_libs") or []), "detail": probe.get("external_libs") or []}
            out["render_ms"] = {"value": round(row["ms"], 1)}
            if "critique_score" in sources:
                critique = s.critique_render(row["id"], use_vision=False)
                out["critique_score"] = {"value": critique["score"], "detail": critique.get("summary")}
            out["render_id"] = {"value": row["id"]}
        if "page_bytes" in sources:
            out["page_bytes"] = {"value": len((html or "").encode("utf-8"))}
        if "page_check_failed" in sources:
            result = s.assay_page(html=html)
            if "error" in result:
                raise ValueError("page_check could not run: " + str(result.get("error")) + " " + str(result.get("hint") or ""))
            out["page_check_failed"] = {"value": int(result.get("failed") or 0), "detail": [f.get("what") for f in (result.get("failing") or [])][:6]}
        return {k: v for k, v in out.items() if k in sources or k == "render_id"}

    # ---------- analysis and decision ----------
    def analyze(self, id: str, weights: Optional[dict[str, float]] = None, sensitivity_of: Optional[str] = None) -> dict[str, Any]:
        study = self._load(id)
        if weights:
            out = reweight(study["criteria"], study["alternatives"], weights)
        else:
            out = analyze(study["criteria"], study["alternatives"])
        if out.get("complete"):
            out["criteria"] = [{k: c[k] for k in ("id", "name", "source", "direction", "weight")} for c in study["criteria"]]
            out["labels"] = {a["id"]: a["label"] for a in study["alternatives"]}
            if sensitivity_of:
                out["sensitivity"] = sensitivity(study["criteria"], study["alternatives"], sensitivity_of)
        out["id"], out["revision"], out["frozen"] = study["id"], study["revision"], self.frozen(study)
        return out

    def decide(self, id: str, alternative_id: str, reason: str, weights: Optional[dict[str, float]] = None, accept_dominated: bool = False) -> dict[str, Any]:
        with self.lock:
            study = self._load(id)
            analysis = analyze(study["criteria"], study["alternatives"], weights)
            if not analysis["complete"]:
                raise ValueError("Measure every alternative on every criterion before deciding; missing: " + json.dumps(analysis["missing"][:6]))
            if alternative_id not in analysis["values"]:
                raise ValueError("Unknown alternative id")
            if len(reason.strip()) < 12:
                raise ValueError("Record the reason for the decision (at least a sentence)")
            labels = {a["id"]: a["label"] for a in study["alternatives"]}
            dominators = analysis["dominated"].get(alternative_id, {}).get("by", [])
            if dominators and not accept_dominated:
                raise ValueError(f"'{labels[alternative_id]}' is dominated by {', '.join(labels[d] for d in dominators)}: they are at least as good on every criterion. Pick one on the frontier ({', '.join(labels[f] for f in analysis['frontier'])}) or pass accept_dominated=true with a reason that names what the criteria miss.")
            rank = next(r["rank"] for r in analysis["ranking"] if r["id"] == alternative_id)
            study["decision"] = {"alternative_id": alternative_id, "label": labels[alternative_id], "reason": reason.strip(), "revision": study["revision"], "decided_ts": time.time(),
                                 "rank": rank, "on_frontier": not dominators, "dominated_by": dominators, "weights": analysis["weights"], "weights_overridden": bool(weights),
                                 "tradeoffs": [t["text"] for t in analysis["tradeoffs"] if alternative_id in (t["a"], t["b"])], "score": analysis["scores"][alternative_id]["total"]}
            self._save(study)
            return self._public(study)
