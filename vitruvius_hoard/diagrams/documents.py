"""Editable diagram documents and immutable revisions, shared by people and agents.

SQLite transactions publish source, view and rendering together. A three-way merge
uses the revision the editor actually read, so unrelated edits are retained.
Legacy diagram files remain readable and are never rewritten on discovery.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from html import escape
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

from ..hoard_link.agentkit import AppError
from .layout import Box, Frame, Layout, Route, MARGIN, GROUP_PAD, GROUP_LABEL_H, wrap
from .render import DEFAULT, FONT_STACK, gates, layout_of, svg
from .spec import Diagram, GRAPH_TYPES


class EditorDiagram(Diagram):
    """An empty graph is a valid new editor document, unlike a render request."""
    def _consistent(self):
        if self.type in GRAPH_TYPES and not self.nodes and not self.edges:
            return self
        return super()._consistent()


_MISSING = object()


def _copy(value):
    return _MISSING if value is _MISSING else deepcopy(value)


def merge(base, proposed, current, path=""):
    """Merge just the fields changed against base, using object IDs in collections."""
    if base == proposed or proposed == current:
        return _copy(current)
    if current == base:
        return _copy(proposed)
    if all(isinstance(v, dict) for v in (base, proposed, current)):
        result = {}
        for key in dict.fromkeys([*current, *proposed, *base]):
            value = merge(base.get(key, _MISSING), proposed.get(key, _MISSING), current.get(key, _MISSING), f"{path}/{key}")
            if value is not _MISSING:
                result[key] = value
        return result
    if all(isinstance(v, list) for v in (base, proposed, current)):
        if all(isinstance(item, dict) and item.get("id") for values in (base, proposed, current) for item in values):
            maps = [{item["id"]: item for item in values} for values in (base, proposed, current)]
            merged = merge(*maps, path)
            order = dict.fromkeys([*(item["id"] for item in current), *(item["id"] for item in proposed)])
            return [merged[key] for key in order if key in merged]
    raise AppError("conflict", "This field changed after the revision you read.",
                   details={"field": path, "current": None if current is _MISSING else current},
                   hint="Keep your draft, read the current document and resolve this field.")


def normalize(content):
    if not isinstance(content, dict):
        raise ValueError("diagram content must be an object")
    raw = deepcopy(content)
    diagram = EditorDiagram.model_validate(raw.get("diagram") or {"type": "flowchart", "nodes": []})
    raw["diagram"] = diagram.model_dump(by_alias=True)
    view = raw.setdefault("view", {})
    if not isinstance(view, dict):
        raise ValueError("view must be an object")
    for collection in ("nodes", "edges"):
        given = view.setdefault(collection, {})
        if not isinstance(given, dict):
            raise ValueError(f"view.{collection} must be an object")
        valid = {item.id for item in getattr(diagram, collection)}
        view[collection] = {key: value for key, value in given.items() if key in valid}
    for item in view["nodes"].values():
        if not isinstance(item, dict):
            raise ValueError("node geometry must be an object")
        for key in ("x", "y", "width", "height"):
            if key in item and (not isinstance(item[key], (int, float)) or not math.isfinite(item[key]) or item[key] < 0):
                raise ValueError(f"node {key} must be a finite positive coordinate")
        if any(key in item and item[key] < 24 for key in ("width", "height")):
            raise ValueError("node dimensions must be at least 24 pixels")
        for key in ("fill", "stroke", "ink"):
            if key in item and (not isinstance(item[key], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", item[key])):
                raise ValueError("node colours must be six-digit hex colours")
    for item in view["edges"].values():
        if not isinstance(item, dict):
            raise ValueError("edge view must be an object")
        for key in ("source_port", "target_port"):
            if item.get(key, "auto") not in ("auto", "top", "right", "bottom", "left"):
                raise ValueError("unknown connector port")
        if not isinstance(item.get("points", []), list):
            raise ValueError("connector points must be a list")
        for point in item.get("points", []):
            if not isinstance(point, list) or len(point) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in point):
                raise ValueError("connector points need two finite coordinates")
    raw["profile"] = raw.get("profile") or {"name": "default", "font": FONT_STACK, **deepcopy(DEFAULT)}
    if not isinstance(raw["profile"], dict):
        raise ValueError("profile must be an object")
    for mode in ("light", "dark"):
        colours = raw["profile"].get(mode, {})
        if not isinstance(colours, dict):
            raise ValueError(f"profile.{mode} must be an object")
        for role in ("paper", "ink", "muted", "accent", "surface", "border"):
            if not isinstance(colours.get(role), str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", colours.get(role, "")):
                raise ValueError(f"profile.{mode}.{role} must be a six-digit hex colour")
        series = colours.get("series", [])
        if not isinstance(series, list) or not series or any(not isinstance(c, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in series):
            raise ValueError("profile series needs hex colours")
    raw.setdefault("source", "")
    return raw


def _port(box, side):
    return {"top": (box.cx, box.y), "bottom": (box.cx, box.y + box.h),
            "left": (box.x, box.cy), "right": (box.x + box.w, box.cy)}[side]


def document_layout(content):
    d = EditorDiagram.model_validate(content["diagram"])
    if not d.nodes and d.type in GRAPH_TYPES:
        return d, Layout(960, 640, {}, [], [], 36 if d.title else 0)
    lay = layout_of(d)
    if not isinstance(lay, Layout):
        return d, lay
    view = content.get("view", {})
    positions = view.get("nodes", {})
    for key, position in positions.items():
        box = lay.boxes.get(key)
        if box is None:
            continue
        box.x, box.y = position.get("x", box.x), position.get("y", box.y)
        box.w, box.h = position.get("width", box.w), position.get("height", box.h)
        if box.shape != "er":
            box.lines = wrap(next(n.label for n in d.nodes if n.id == key), max(3, int((box.w - 28) / 7.6)))
    lay.routes = []
    for index, edge in enumerate(d.edges):
        a, b = lay.boxes[edge.source], lay.boxes[edge.target]
        ev = view.get("edges", {}).get(edge.id, {})
        returning = any(other.source == edge.target and other.target == edge.source for other in d.edges[:index]) and edge.source != edge.target
        if abs(b.cx - a.cx) >= abs(b.cy - a.cy):
            start_side, end_side = ("right", "left") if b.cx >= a.cx else ("left", "right")
        else:
            start_side, end_side = ("bottom", "top") if b.cy >= a.cy else ("top", "bottom")
        if returning:
            start_side = end_side = "right"
        start_side = ev.get("source_port", "auto") if ev.get("source_port", "auto") != "auto" else start_side
        end_side = ev.get("target_port", "auto") if ev.get("target_port", "auto") != "auto" else end_side
        start, end = _port(a, start_side), _port(b, end_side)
        middle = ev.get("points")
        if middle:
            points = [start, *(tuple(p) for p in middle), end]
        elif returning:
            lane = max(a.x + a.w, b.x + b.w) + 40
            points = [start, (lane, start[1]), (lane, end[1]), end]
        elif edge.source == edge.target:
            points = [start, (a.x + a.w + 36, start[1]), (a.x + a.w + 36, a.y - 24), (a.cx, a.y - 24), (a.cx, a.y)]
        elif start_side in ("left", "right"):
            mid = (start[0] + end[0]) / 2
            points = [start, (mid, start[1]), (mid, end[1]), end]
        else:
            mid = (start[1] + end[1]) / 2
            points = [start, (start[0], mid), (end[0], mid), end]
        halfway = points[len(points) // 2]
        lay.routes.append(Route(edge.source, edge.target, points, edge.label, edge.style, edge.cardinality, halfway))
    for frame in lay.frames:
        boxes = [lay.boxes[k] for k in frame.members if k in lay.boxes]
        if boxes:
            frame.x = min(b.x for b in boxes) - GROUP_PAD
            frame.y = min(b.y for b in boxes) - GROUP_PAD - GROUP_LABEL_H
            frame.w = max(b.x + b.w for b in boxes) - frame.x + GROUP_PAD
            frame.h = max(b.y + b.h for b in boxes) - frame.y + GROUP_PAD
    lay.width = max(640, *(b.x + b.w + MARGIN for b in lay.boxes.values()), *(f.x + f.w + MARGIN for f in lay.frames), *(x + MARGIN for r in lay.routes for x, y in r.points))
    lay.height = max(400, *(b.y + b.h + MARGIN for b in lay.boxes.values()), *(f.y + f.h + MARGIN for f in lay.frames), *(y + MARGIN for r in lay.routes for x, y in r.points))
    return d, lay


def drawing(content):
    d, lay = document_layout(content)
    profile = content["profile"]
    report = gates(d, profile, lay) if d.nodes or d.type not in GRAPH_TYPES else []
    result = {"svg": {mode: svg(d, profile, mode, lay, content["view"]["nodes"]) for mode in ("light", "dark")},
              "gates": report}
    result["ok"] = all(g["ok"] for g in result["gates"])
    if isinstance(lay, Layout):
        result["scene"] = json.loads(json.dumps(asdict(lay)))
        result["scene"]["edge_ids"] = [e.id for e in d.edges]
    return result


class DocumentStore:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "diagrams" / "documents.sqlite3"

    def _open(self, write=False):
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        elif not self.path.exists():
            raise LookupError("No editable diagram documents have been saved.")
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        if write:
            db.executescript("""CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, head INTEGER NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions(document TEXT NOT NULL, revision INTEGER NOT NULL,
                    created REAL NOT NULL, content TEXT NOT NULL, rendering TEXT NOT NULL, reason TEXT NOT NULL,
                    PRIMARY KEY(document,revision));""")
        return db

    def _read(self, db, did, revision=None):
        if revision is None:
            row = db.execute("SELECT head FROM documents WHERE id=?", (did,)).fetchone()
            if row is None:
                raise LookupError(f"Unknown editable diagram '{did}'.")
            revision = row[0]
        row = db.execute("SELECT * FROM revisions WHERE document=? AND revision=?", (did, revision)).fetchone()
        if row is None:
            raise LookupError(f"Unknown diagram revision '{did}/{revision}'.")
        return {"id": did, "revision": revision, "created_ts": row["created"], "content": json.loads(row["content"]),
                "rendering": json.loads(row["rendering"]), "reason": row["reason"]}

    def get(self, did, revision=None):
        db = self._open()
        try:
            result = self._read(db, did, revision)
            result["head_revision"] = db.execute("SELECT head FROM documents WHERE id=?", (did,)).fetchone()[0]
            return result
        finally:
            db.close()

    def list(self):
        if not self.path.exists():
            return []
        db = self._open()
        try:
            return [{"id": row["id"], "revision": row["head"], "created_ts": row["created"],
                     "title": json.loads(row["content"])["diagram"]["title"], "editable": True}
                    for row in db.execute("SELECT d.*,r.content FROM documents d JOIN revisions r ON r.document=d.id AND r.revision=d.head ORDER BY d.created DESC")]
        finally:
            db.close()

    def history(self, did):
        db = self._open()
        try:
            self._read(db, did)
            return [dict(row) for row in db.execute("SELECT revision,created,reason FROM revisions WHERE document=? ORDER BY revision DESC", (did,))]
        finally:
            db.close()

    def _commit(self, db, did, revision, content, reason):
        content = normalize(content)
        rendered = drawing(content)
        stamp = time.time()
        db.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?)", (did, revision, stamp,
                   json.dumps(content, ensure_ascii=False), json.dumps(rendered, ensure_ascii=False), reason))
        db.execute("UPDATE documents SET head=? WHERE id=?", (revision, did))
        return {"id": did, "revision": revision, "head_revision": revision, "created_ts": stamp,
                "content": content, "rendering": rendered, "reason": reason}

    def save(self, content, *, did=None, base_revision=None, reason="Edit diagram"):
        db = self._open(True)
        try:
            db.execute("BEGIN IMMEDIATE")
            if did is None:
                did, revision = uuid.uuid4().hex[:12], 1
                db.execute("INSERT INTO documents VALUES(?,?,?)", (did, revision, time.time()))
            else:
                if base_revision is None:
                    raise ValueError("An edit must name the revision that was read.")
                base = self._read(db, did, base_revision)["content"]
                current = self._read(db, did)
                content = merge(base, normalize(content), current["content"])
                revision = current["revision"] + 1
            result = self._commit(db, did, revision, content, reason)
            db.commit()
            return result
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def undo(self, did, revision):
        """Reverse one saved change, keeping later independent edits intact."""
        if revision < 2:
            raise ValueError("The initial revision cannot be undone.")
        db = self._open(True)
        try:
            db.execute("BEGIN IMMEDIATE")
            after = self._read(db, did, revision)["content"]
            before = self._read(db, did, revision - 1)["content"]
            current = self._read(db, did)
            content = merge(after, before, current["content"])
            result = self._commit(db, did, current["revision"] + 1, content, f"Undo revision {revision}")
            db.commit()
            return result
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def delete(self, did):
        db = self._open(True)
        try:
            db.execute("BEGIN IMMEDIATE")
            self._read(db, did)
            db.execute("DELETE FROM revisions WHERE document=?", (did,))
            db.execute("DELETE FROM documents WHERE id=?", (did,))
            db.commit()
            return True
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
