"""Project revision diffs and subscriptions shared by the UI and agent tools."""
from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit


class StylesheetLinks(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.paths = set()
        try:
            self.feed(html)
        except AssertionError:
            # Invalid source can still be saved and reloaded by the browser.
            self.paths = None

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        attrs = dict(attrs)
        if "stylesheet" not in (attrs.get("rel") or "").lower().split():
            return
        try:
            url = urlsplit(attrs.get("href") or "")
        except ValueError:
            return
        if not (url.scheme or url.netloc):
            self.paths.add(unquote(url.path).removeprefix("./").lstrip("/"))


def _line_span(old, new):
    """One inclusive span per side; an insertion or deletion can have an empty side."""
    before, after = old.splitlines(keepends=True), new.splitlines(keepends=True)
    shared = min(len(before), len(after))
    start = 0
    while start < shared and before[start] == after[start]:
        start += 1
    end = 0
    while end < shared - start and before[-1 - end] == after[-1 - end]:
        end += 1
    return {"before": [start + 1, len(before) - end], "after": [start + 1, len(after) - end]}


def revision_change(previous, current, *, baseline=None):
    if previous is None:
        return {"revision": current["revision"], "previous_revision": baseline, "files": [], "reset": True}
    old, new = previous["files"], current["files"]
    files = sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))
    css = {name for name in files if name.lower().endswith(".css")}
    linked = StylesheetLinks(new["layout.html"]).paths if css else set()
    global_styles = css if linked is None else linked & css
    return {
        "revision": current["revision"],
        "previous_revision": previous["selected_revision"],
        "files": files,
        "ranges": {name: _line_span(old.get(name, ""), new.get(name, "")) for name in files
                   if name.startswith("pages/") and name.lower().endswith(".html")},
        "global_styles": sorted(global_styles),
    }


class RevisionEvents:
    """Fan out ordered, committed changes to event loops without waiting on clients."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers = {}
        self._sequence = 0
        self._closed = False

    @property
    def sequence(self):
        with self._lock:
            return self._sequence

    @contextmanager
    def subscribe(self, project_id):
        subscriber = asyncio.get_running_loop(), asyncio.Queue(maxsize=32)
        with self._lock:
            if self._closed:
                subscriber[1].put_nowait(None)
            else:
                self._subscribers.setdefault(project_id, set()).add(subscriber)
        try:
            yield subscriber[1]
        finally:
            with self._lock:
                watchers = self._subscribers.get(project_id)
                if watchers is not None:
                    watchers.discard(subscriber)
                    if not watchers:
                        self._subscribers.pop(project_id)

    @staticmethod
    def _enqueue(queue, message):
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(message)

    def _send(self, subscribers, message):
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(self._enqueue, queue, message)
            except RuntimeError:
                # The browser's server loop can close before a worker finishes an edit.
                pass

    def publish(self, project_id, change):
        with self._lock:
            self._sequence += 1
            self._send(self._subscribers.get(project_id, ()), (self._sequence, change))

    def close_project(self, project_id):
        with self._lock:
            self._send(self._subscribers.pop(project_id, ()), None)

    def close(self):
        with self._lock:
            self._closed = True
            for subscribers in self._subscribers.values():
                self._send(subscribers, None)
            self._subscribers.clear()
