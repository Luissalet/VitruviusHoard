"""Comments pinned on elements of an application preview, which the agent works through.

A person turns on Comment in the preview bar, clicks an element and writes a note; the note becomes a pin on that
element. The comment keeps where it was made (source position, selector, box, page) and the source revision the page
was served from. It lives in the project's own data folder (``comments.json``, next to the revisions), never in the
source files and never in an export.

Life cycle (who moves it):

    pending  --acknowledge (agent)-->  seen
    pending|seen|answered  --resolve with a summary (agent)-->  resolved
    pending|seen  --reply (agent)-->  answered        (a question or answer for the person)
    pending|seen|answered  --dismiss (agent or person)-->  dismissed
    answered  --respond (person)-->  pending
    resolved|dismissed  --reopen (person)-->  pending
    any step  --undo-->  the state before it

Every step is kept in the comment's ``history`` and can be undone, so nothing a tool writes is lost.
"""
from __future__ import annotations

import re
import threading
import time

from .hoard_link.atomic import write_json_atomic
from .preview_inspector import normalise

FORMAT = "vitruvius-preview-comments/v1"
STATUSES = ("pending", "seen", "answered", "resolved", "dismissed")
OPEN = ("pending", "seen")
MAX_COMMENTS = 300
MAX_NOTE = 2000
MAX_SUMMARY = 1200
_BOX = ("x", "y", "w", "h")
_FIELDS = ("summary", "reply", "resolved_in")


def _text(value, limit):
    return value.strip()[:limit] if isinstance(value, str) else ""


def _box(raw):
    box = raw if isinstance(raw, dict) else {}
    return {key: (box.get(key) if isinstance(box.get(key), (int, float)) and not isinstance(box.get(key), bool) else 0) for key in _BOX}


def _page(value):
    page = _text(value, 300)
    return page if page.startswith("/") else "/" + page if page else "/"


class PreviewComments:
    def __init__(self, app_projects):
        self.app_projects = app_projects
        self._lock = threading.RLock()

    # ---- storage -------------------------------------------------------------------------------------------
    def _path(self, project_id):
        return self.app_projects._directory(project_id) / "comments.json"

    def _load(self, project_id):
        from json import loads
        path = self._path(project_id)
        if not path.is_file():
            return {"format": FORMAT, "next": 1, "comments": []}
        data = loads(path.read_text(encoding="utf-8"))
        if data.get("format") != FORMAT or not isinstance(data.get("comments"), list):
            raise ValueError("comments.json is not a Vitruvius comment file")
        return data

    def _save(self, project_id, data):
        write_json_atomic(self._path(project_id), data)

    def _find(self, data, comment_id):
        for comment in data["comments"]:
            if comment["id"] == comment_id:
                return comment
        raise LookupError(f"Comment not found: {comment_id}")

    def _current_revision(self, project_id):
        return self.app_projects.get(project_id)["revision"]

    def _view(self, comment, current):
        item = {key: value for key, value in comment.items() if key != "history"}
        item["stale"] = comment["revision"] != current
        item["history"] = [dict(entry) for entry in comment["history"]]
        return item

    # ---- reading -------------------------------------------------------------------------------------------
    def list(self, project_id, status="open"):
        """Comments of a project. ``status``: one status, ``open`` (pending + seen), ``lost`` (no anchor) or ``all``."""
        with self._lock:
            data = self._load(project_id)
            current = self._current_revision(project_id)
        comments = data["comments"]
        counts = {name: sum(1 for c in comments if c["status"] == name) for name in STATUSES}
        counts["lost"] = sum(1 for c in comments if (c.get("anchor") or {}).get("state") == "lost" and c["status"] in OPEN + ("answered",))
        if status == "open":
            picked = [c for c in comments if c["status"] in OPEN]
        elif status == "lost":
            picked = [c for c in comments if (c.get("anchor") or {}).get("state") == "lost"]
        elif status == "all":
            picked = list(comments)
        elif status in STATUSES:
            picked = [c for c in comments if c["status"] == status]
        else:
            raise ValueError("status must be one of: open, all, lost, " + ", ".join(STATUSES))
        result = {"id": project_id, "revision": current, "count": len(picked), "counts": counts, "comments": [self._view(c, current) for c in picked]}
        if not picked:
            result["note"] = "No comments match." if comments else "Nobody has commented on the preview yet. The person uses Comment on the preview."
        return result

    # ---- the person's side ---------------------------------------------------------------------------------
    def add(self, project_id, note, revision, page, element):
        note = _text(note, MAX_NOTE)
        if not note:
            raise ValueError("A comment needs a note")
        if not isinstance(revision, str) or not revision:
            raise ValueError("A comment needs the source revision the preview was served from")
        [target] = normalise([element]) or [None]
        if target is None:
            raise ValueError("A comment needs the element it is pinned to")
        with self._lock:
            project = self.app_projects.get(project_id)
            if revision not in project["revisions"]:
                raise ValueError(f"Unknown revision {revision}: the comment must name a revision of this project")
            data = self._load(project_id)
            if len(data["comments"]) >= MAX_COMMENTS:
                raise ValueError(f"A project keeps at most {MAX_COMMENTS} comments: dismiss or resolve some first")
            now = time.time()
            number = data["next"]
            comment = {
                "id": f"c{number}", "n": number, "status": "pending", "note": note, "page": _page(page), "revision": revision,
                "vsrc": target.get("vsrc"), "vgen": target.get("vgen"), "selector": target["selector"], "tag": target["tag"],
                "classes": target["classes"], "element_text": target["text"], "box": target["box"],
                "anchor": {"state": "ok", "revision": revision, "vsrc": target.get("vsrc"), "checked_ts": now},
                "created_ts": now, "updated_ts": now, "summary": None, "reply": None, "resolved_in": None,
                "history": [{"ts": now, "by": "person", "status": "pending", "text": note, "before": None}],
            }
            data["next"] = number + 1
            data["comments"].append(comment)
            self._save(project_id, data)
            return self._view(comment, project["revision"])

    def set_anchors(self, project_id, revision, anchors):
        """The page says which pins it found on screen. A pin whose element is gone keeps its comment, flagged ``lost``."""
        if not isinstance(anchors, list):
            raise ValueError("anchors must be a list")
        with self._lock:
            data = self._load(project_id)
            changed = 0
            for raw in anchors[:MAX_COMMENTS]:
                if not isinstance(raw, dict) or raw.get("state") not in ("ok", "lost"):
                    continue
                try:
                    comment = self._find(data, str(raw.get("id")))
                except LookupError:
                    continue
                before = comment.get("anchor") or {}
                vsrc = _text(raw.get("vsrc"), 300) or None
                anchor = {"state": raw["state"], "revision": revision if isinstance(revision, str) else before.get("revision"),
                          "vsrc": vsrc if raw["state"] == "ok" else before.get("vsrc"), "checked_ts": time.time()}
                box = _box(raw.get("box")) if raw["state"] == "ok" and isinstance(raw.get("box"), dict) else comment["box"]
                if (before.get("state"), before.get("revision"), before.get("vsrc")) != (anchor["state"], anchor["revision"], anchor["vsrc"]) or box != comment["box"]:
                    comment["anchor"], comment["box"] = anchor, box
                    changed += 1
            if changed:
                self._save(project_id, data)
            return {"id": project_id, "changed": changed}

    # ---- steps ---------------------------------------------------------------------------------------------
    def _step(self, project_id, comment_id, by, to, allowed, text=None, fields=None, require_text=False):
        text = _text(text, MAX_SUMMARY)
        if require_text and not text:
            raise ValueError("This step needs a text")
        with self._lock:
            data = self._load(project_id)
            comment = self._find(data, comment_id)
            if comment["status"] not in allowed:
                raise ValueError(f"Comment {comment_id} is {comment['status']}: it can go to {to} only from {', '.join(allowed)}")
            now = time.time()
            before = {"status": comment["status"], **{key: comment.get(key) for key in _FIELDS}}
            comment["history"].append({"ts": now, "by": by, "status": to, "text": text, "before": before})
            comment["status"], comment["updated_ts"] = to, now
            comment.update(fields or {})
            self._save(project_id, data)
            return self._view(comment, self._current_revision(project_id))

    def acknowledge(self, project_id, ids):
        ids = [ids] if isinstance(ids, str) else list(ids or [])
        if not ids:
            raise ValueError("Name at least one comment id")
        done = []
        for comment_id in ids:
            with self._lock:
                data = self._load(project_id)
                current = self._find(data, comment_id)["status"]
            if current == "seen":
                done.append(self._view(self._find(self._load(project_id), comment_id), self._current_revision(project_id)))
            else:
                done.append(self._step(project_id, comment_id, "agent", "seen", ("pending",)))
        return {"id": project_id, "comments": done}

    def resolve(self, project_id, comment_id, summary, revision=None):
        """Resolved with a summary of what changed; ``revision`` is the project revision holding the change (default: the current one)."""
        current = self._current_revision(project_id)
        return self._step(project_id, comment_id, "agent", "resolved", ("pending", "seen", "answered"), summary,
                          {"summary": _text(summary, MAX_SUMMARY), "resolved_in": revision or current, "reply": None}, require_text=True)

    def reply(self, project_id, comment_id, text):
        return self._step(project_id, comment_id, "agent", "answered", ("pending", "seen"), text, {"reply": _text(text, MAX_SUMMARY)}, require_text=True)

    def dismiss(self, project_id, comment_id, reason=None, by="agent"):
        return self._step(project_id, comment_id, by, "dismissed", ("pending", "seen", "answered"), reason)

    def respond(self, project_id, comment_id, text):
        """The person answers the agent's question: the comment is pending again."""
        return self._step(project_id, comment_id, "person", "pending", ("answered",), text, require_text=True)

    def reopen(self, project_id, comment_id, text=None):
        return self._step(project_id, comment_id, "person", "pending", ("resolved", "dismissed"), text, {"summary": None, "resolved_in": None, "reply": None})

    def undo(self, project_id, comment_id):
        with self._lock:
            data = self._load(project_id)
            comment = self._find(data, comment_id)
            last = comment["history"][-1]
            if not last.get("before"):
                raise ValueError("Nothing to undo: the comment is as it was created")
            comment["history"].pop()
            before = last["before"]
            comment["status"] = before["status"]
            for key in _FIELDS:
                comment[key] = before.get(key)
            comment["updated_ts"] = time.time()
            self._save(project_id, data)
            return self._view(comment, self._current_revision(project_id))


# ---- tool and API entry points (an unknown project is a LookupError, like the other project tools) ------------
def _store(services, project_id):
    services.app_projects._directory(project_id)
    return services.preview_comments


def list_comments(services, project_id, status="open"):
    return _store(services, project_id).list(project_id, status)


def acknowledge_comments(services, project_id, ids):
    return _store(services, project_id).acknowledge(project_id, ids)


def resolve_comment(services, project_id, comment_id, summary, revision=None):
    return _store(services, project_id).resolve(project_id, comment_id, summary, revision)


def reply_to_comment(services, project_id, comment_id, text):
    return _store(services, project_id).reply(project_id, comment_id, text)


def dismiss_comment(services, project_id, comment_id, reason=None):
    return _store(services, project_id).dismiss(project_id, comment_id, reason, "agent")


def undo_comment(services, project_id, comment_id):
    return _store(services, project_id).undo(project_id, comment_id)
