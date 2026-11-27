"""Comments pinned on elements of an application preview, which the agent works through.

A person turns on Comment in the preview bar, clicks an element and writes a note; the note becomes a pin on that
element. The comment keeps where it was made (source position, selector, box, page), the source revision the page was
served from and, when the page could take one, a crop of the element as it looked then. It lives in the project's own
data folder (``comments.json`` and ``comment-crops/``, next to the revisions), never in the source files and never in
an export.

Life cycle (who moves it):

    pending  --acknowledge (agent)-->  seen
    seen  --resolve with a summary (agent)-->  resolved
    seen  --reply (agent)-->  answered                (a question or answer for the person)
    seen  --dismiss (agent)-->  dismissed
    pending|seen|answered  --dismiss (person)-->  dismissed
    answered  --respond (person)-->  pending
    resolved|dismissed  --reopen (person)-->  pending
    resolved  --undo the source fix (system)-->  pending
    any step  --undo-->  the state before it

The agent acknowledges a comment before it answers it, so the person always sees "seen" first. A batch of
acknowledgements is all or nothing. Every step is kept in the comment's ``history`` and can be undone.
"""
from __future__ import annotations

import base64
import binascii
import re
import threading
import time

from .hoard_link.atomic import write_json_atomic
from .preview_inspector import StaleSelection, normalise

FORMAT = "vitruvius-preview-comments/v1"
STATUSES = ("pending", "seen", "answered", "resolved", "dismissed")
OPEN = ("pending", "seen")
MAX_COMMENTS = 1000
MAX_PER_PAGE = 300  # what the preview paints: the page script keeps the same limit, so no comment is left without a pin
IDENTITY_ATTRS = ("id", "href", "data-vid", "name", "src", "for")
MAX_NOTE = 2000
MAX_SUMMARY = 1200
MAX_CROP = 300_000
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
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


def _source_fix(history, resolved_pos, comment, explicit):
    if explicit:
        return resolved_pos, history[resolved_pos]

    # The snapshot at resolution can include later saves. Attribute an implicit
    # resolution only to an edit we can identify from the comment's anchor.
    positions = {comment.get("vsrc"), (comment.get("anchor") or {}).get("vsrc")} - {None, ""}
    paths = {position.rsplit(":", 2)[0] for position in positions}
    targets = positions | {comment["selector"]}
    opened = next(entry["ts"] for entry in reversed(comment["history"]) if entry["status"] == "pending")
    exact, in_file = [], []
    for pos in range(resolved_pos, -1, -1):
        entry = history[pos]
        if entry.get("ts", 0) < opened:
            break
        if entry.get("action") != "edit":
            continue
        if entry.get("target") in targets:
            exact.append((pos, entry))
        if paths.intersection(entry.get("files") or ()):
            in_file.append((pos, entry))
    matches = exact or in_file
    return matches[0] if len(matches) == 1 else None


class PreviewComments:
    def __init__(self, app_projects):
        self.app_projects = app_projects
        self._lock = threading.RLock()

    # ---- storage -------------------------------------------------------------------------------------------
    def _path(self, project_id):
        return self.app_projects._directory(project_id) / "comments.json"

    def _load(self, project_id):
        from json import loads
        root, index = self.app_projects._load_index(project_id)
        path = root / "comments.json"
        if not path.is_file():
            return {"format": FORMAT, "next": 1, "comments": []}
        data = loads(path.read_text(encoding="utf-8"))
        if data.get("format") != FORMAT or not isinstance(data.get("comments"), list):
            raise ValueError("comments.json is not a Vitruvius comment file")
        self._apply_source_undos(data["comments"], index.get("history") or ())
        return data

    def _apply_source_undos(self, comments, history):
        """Read source rollbacks from the project journal. The next comment write saves any projected steps."""
        revisions = {}
        undos = []
        for pos, row in enumerate(history):
            earlier = revisions.setdefault(row["revision"], [])
            if row.get("action") in ("undo", "critique-undo") and earlier:
                undos.append((pos, earlier[-1][0], row))
            elif row.get("action") == "undo-change":
                undos.append((pos, None, row))
            earlier.append((pos, row))
        if not undos:
            return

        for comment in comments:
            resolution = comment["history"][-1]
            if comment["status"] != "resolved" or resolution["by"] != "agent" or not comment.get("resolved_in"):
                continue
            # A content hash can recur. Locate the occurrence the agent could have resolved against at the time.
            occurrences = revisions.get(comment["resolved_in"], ())
            resolved_pos = next((pos for pos, row in reversed(occurrences)
                                 if comment["created_ts"] <= row.get("ts", 0) <= resolution["ts"]), None)
            if resolved_pos is None:
                continue
            fix = _source_fix(history, resolved_pos, comment, explicit=bool(resolution.get("source_revision")))
            if fix is None:
                continue
            fix_pos, fix_row = fix
            after = max(resolution["ts"], comment.get("source_undo_ts", 0))
            for undo_pos, target_pos, undo in undos:
                if undo["ts"] <= after:
                    continue
                if target_pos is None:
                    removes_fix = bool(fix_row.get("id")) and undo.get("reverted_change") == fix_row["id"]
                else:
                    removes_fix = target_pos < fix_pos < undo_pos
                if removes_fix:
                    self._move(comment, "system", "pending", comment["summary"],
                               dict.fromkeys(_FIELDS), ts=undo["ts"])
                    comment["history"][-1]["source_undo"] = True
                    break

    def _save(self, project_id, data):
        write_json_atomic(self._path(project_id), data)

    def _find(self, data, comment_id):
        for comment in data["comments"]:
            if comment["id"] == comment_id:
                return comment
        raise LookupError(f"Comment not found: {comment_id}")

    def _current_revision(self, project_id):
        return self.app_projects.get(project_id)["revision"]

    def _check_revision(self, project_id, revision, what, *, anchor_report=False, session=None):
        """Validate the revision and return False for a superseded report from this preview session."""
        if not isinstance(revision, str) or not revision:
            raise ValueError(f"{what} needs the source revision the preview was served from")
        _, index = self.app_projects._load_index(project_id)
        if revision not in index["revisions"]:
            raise ValueError(f"Unknown revision {revision}: {what} must name a revision of this project")
        status = self.app_projects.status(project_id)
        running = status.get("state") == "running"
        if anchor_report:
            if not running:
                raise StaleSelection(f"The preview is not running: {what} from a stopped preview is dropped")
            if not session:
                raise ValueError(f"{what} needs the preview session the page was served from")
            if session != status.get("session"):
                raise StaleSelection(f"{what} is from an earlier opening of the preview: it is dropped")
        served = status.get("revision")
        if running and served and served != revision:
            if anchor_report:
                # A restored snapshot can reuse a revision hash. Use the latest journal occurrence.
                history = index.get("history")
                revisions = [entry["revision"] for entry in history] if history else index["revisions"]
                last = next((item for item in reversed(revisions) if item in (served, revision)), None)
                if last == served:
                    return False
            raise StaleSelection(f"The preview now serves revision {served}, not {revision}: pick the element again on the page that is shown")
        return True

    def _view(self, comment, current):
        item = {key: value for key, value in comment.items() if key not in ("history", "source_undo_ts")}
        item["stale"] = comment["revision"] != current
        item["has_crop"] = bool(comment.get("crop"))
        item["history"] = [dict(entry) for entry in comment["history"]]
        return item

    # ---- the crop ------------------------------------------------------------------------------------------
    def _crop_path(self, project_id, comment_id, suffix=".png"):
        if not re.fullmatch(r"c\d+", comment_id):
            raise LookupError("Comment not found")
        return self.app_projects._directory(project_id) / "comment-crops" / f"{comment_id}{suffix}"

    def crop(self, project_id, comment_id):
        """Path of the element's crop (PNG or JPEG), taken when the comment was made."""
        for suffix in (".png", ".jpg"):
            path = self._crop_path(project_id, comment_id, suffix)
            if path.is_file():
                return path
        raise LookupError("This comment has no crop")

    @staticmethod
    def _decode_crop(crop):
        if crop in (None, ""):
            return None
        if not isinstance(crop, str) or not crop.startswith(("data:image/png;base64,", "data:image/jpeg;base64,")):
            raise ValueError("The crop must be a PNG or JPEG data URL")
        try:
            data = base64.b64decode(crop.split(",", 1)[1], validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("The crop is not valid base64") from error
        if not (data.startswith(PNG_MAGIC) or data.startswith(JPEG_MAGIC)) or len(data) > MAX_CROP:
            raise ValueError(f"The crop must be a PNG or JPEG of at most {MAX_CROP} bytes")
        return data

    @staticmethod
    def _attrs(raw):
        """The identity attributes of the element (an id, a link's address): kept to tell look-alikes apart later."""
        if not isinstance(raw, dict):
            return {}
        return {name: raw[name][:300] for name in IDENTITY_ATTRS if isinstance(raw.get(name), str) and raw[name]}

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
    def add(self, project_id, note, revision, page, element, crop=None, attrs=None):
        note = _text(note, MAX_NOTE)
        if not note:
            raise ValueError("A comment needs a note")
        [target] = normalise([element]) or [None]
        if target is None:
            raise ValueError("A comment needs the element it is pinned to")
        png = self._decode_crop(crop)
        with self._lock:
            project = self.app_projects.get(project_id)
            self._check_revision(project_id, revision, "a comment")
            data = self._load(project_id)
            if len(data["comments"]) >= MAX_COMMENTS:
                raise ValueError(f"A project keeps at most {MAX_COMMENTS} comments")
            if sum(1 for c in data["comments"] if c["page"] == _page(page)) >= MAX_PER_PAGE:
                raise ValueError(f"A page keeps at most {MAX_PER_PAGE} comments: the preview paints that many pins per page")
            now = time.time()
            number = data["next"]
            comment = {
                "id": f"c{number}", "n": number, "status": "pending", "note": note, "page": _page(page), "revision": revision,
                "vsrc": target.get("vsrc"), "vgen": target.get("vgen"), "selector": target["selector"], "tag": target["tag"],
                "classes": target["classes"], "element_text": target["text"], "box": target["box"], "own_vsrc": bool(target.get("own_vsrc")),
                "parent": target.get("parent") or "", "index": target.get("index") or 0, "attrs": self._attrs(attrs),
                "crop": {"revision": revision, "bytes": len(png)} if png else None,
                "anchor": {"state": "ok", "revision": revision, "vsrc": target.get("vsrc"), "checked_ts": now},
                "created_ts": now, "updated_ts": now, "summary": None, "reply": None, "resolved_in": None,
                "history": [{"ts": now, "by": "person", "status": "pending", "text": note, "before": None}],
            }
            data["next"] = number + 1
            data["comments"].append(comment)
            if png:
                path = self._crop_path(project_id, comment["id"], ".png" if png.startswith(PNG_MAGIC) else ".jpg")
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(png)
            self._save(project_id, data)
            return self._view(comment, project["revision"])

    def set_anchors(self, project_id, revision, anchors, session=None):
        """The page says which pins it found on screen, and on which revision. A pin whose element is gone keeps its
        comment, flagged ``lost``. A superseded report from the same opening of the preview is acknowledged without writing."""
        if not isinstance(anchors, list):
            raise ValueError("anchors must be a list")
        with self._lock, self.app_projects.lock:
            if not self._check_revision(project_id, revision, "an anchor report", anchor_report=True, session=session):
                return {"id": project_id, "changed": 0, "stale": True}
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
                anchor = {"state": raw["state"], "revision": revision, "vsrc": vsrc if raw["state"] == "ok" else before.get("vsrc"), "checked_ts": time.time()}
                box = _box(raw.get("box")) if raw["state"] == "ok" and isinstance(raw.get("box"), dict) else comment["box"]
                if (before.get("state"), before.get("revision"), before.get("vsrc")) != (anchor["state"], anchor["revision"], anchor["vsrc"]) or box != comment["box"]:
                    comment["anchor"], comment["box"] = anchor, box
                    changed += 1
            if changed:
                self._save(project_id, data)
            return {"id": project_id, "changed": changed}

    # ---- steps ---------------------------------------------------------------------------------------------
    def _check_step(self, comment, to, allowed):
        if comment["status"] not in allowed:
            raise ValueError(f"Comment {comment['id']} is {comment['status']}: it can go to {to} only from {', '.join(allowed)}")

    def _move(self, comment, by, to, text, fields, *, ts=None):
        now = time.time() if ts is None else ts
        before = {"status": comment["status"], **{key: comment.get(key) for key in _FIELDS}}
        comment["history"].append({"ts": now, "by": by, "status": to, "text": text, "before": before})
        comment["status"], comment["updated_ts"] = to, now
        comment.update(fields or {})

    def _step(self, project_id, comment_id, by, to, allowed, text=None, fields=None, require_text=False, *, history_details=None):
        text = _text(text, MAX_SUMMARY)
        if require_text and not text:
            raise ValueError("This step needs a text")
        with self._lock:
            data = self._load(project_id)
            comment = self._find(data, comment_id)
            self._check_step(comment, to, allowed)
            self._move(comment, by, to, text, fields)
            if history_details:
                comment["history"][-1].update(history_details)
            self._save(project_id, data)
            return self._view(comment, self._current_revision(project_id))

    def acknowledge(self, project_id, ids):
        """Mark comments seen, all or nothing: every id is checked before the first is written."""
        ids = [ids] if isinstance(ids, str) else list(dict.fromkeys(ids or []))
        if not ids:
            raise ValueError("Name at least one comment id")
        with self._lock:
            data = self._load(project_id)
            comments = [self._find(data, comment_id) for comment_id in ids]
            for comment in comments:
                self._check_step(comment, "seen", ("pending", "seen"))
            for comment in comments:
                if comment["status"] == "pending":
                    self._move(comment, "agent", "seen", "", None)
            self._save(project_id, data)
            current = self._current_revision(project_id)
            return {"id": project_id, "comments": [self._view(comment, current) for comment in comments]}

    def resolve(self, project_id, comment_id, summary, revision=None):
        """Resolved with a summary of what changed; ``revision`` is the project revision holding the change (default: the current one)."""
        if revision is not None and revision not in self.app_projects.get(project_id)["revisions"]:
            raise ValueError(f"Unknown revision {revision}: a comment is resolved in a revision of this project")
        return self._step(project_id, comment_id, "agent", "resolved", ("seen",), summary,
                          {"summary": _text(summary, MAX_SUMMARY), "resolved_in": revision or self._current_revision(project_id), "reply": None},
                          require_text=True, history_details={"source_revision": revision} if revision else None)

    def resolve_person(self, project_id, comment_id):
        """Close an open comment from the preview, keeping the step in its undo history."""
        return self._step(project_id, comment_id, "person", "resolved", ("pending", "seen", "answered"),
                          fields={"summary": None, "resolved_in": self._current_revision(project_id), "reply": None})

    def reply(self, project_id, comment_id, text):
        return self._step(project_id, comment_id, "agent", "answered", ("seen",), text, {"reply": _text(text, MAX_SUMMARY)}, require_text=True)

    def dismiss(self, project_id, comment_id, reason=None, by="agent"):
        allowed = ("seen",) if by == "agent" else ("pending", "seen", "answered")
        return self._step(project_id, comment_id, by, "dismissed", allowed, reason)

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
            now = time.time()
            comment["history"].pop()
            if last.get("source_undo"):
                comment["source_undo_ts"] = now
            before = last["before"]
            comment["status"] = before["status"]
            for key in _FIELDS:
                comment[key] = before.get(key)
            comment["updated_ts"] = now
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
