"""Relay calls from native agent tools to an already open preview frame."""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from concurrent.futures import Future, TimeoutError, wait
from dataclasses import dataclass, field
from hashlib import blake2b


PRESENCE_WAIT = 1.5
ACTOR_TOOLS = frozenset({
    "app_project_canvas_view", "app_project_canvas_act", "app_project_update",
    "app_project_edit_source", "app_project_canvas_edit",
})
_ACTOR_COLORS = ("#7551bd", "#246cb4", "#147c68", "#a46114", "#b94265", "#8c522a", "#465ccc", "#237c87")


def failure(code: str, message: str):
    return {"ok": False, "error": {"code": code, "message": message}}


@dataclass
class CanvasSession:
    project: str
    revision: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    loop: asyncio.AbstractEventLoop = field(default_factory=asyncio.get_running_loop)
    events: asyncio.Queue = field(default_factory=asyncio.Queue)
    pending: dict[str, Future] = field(default_factory=dict)

    async def next_event(self):
        while True:
            event = await self.events.get()
            if event is None or event.get("expires_at", float("inf")) > time.time() * 1000:
                return event


class CanvasSessions:
    def __init__(self):
        self._lock = threading.Condition()
        self._sessions: dict[str, CanvasSession] = {}
        self._actor_profiles: dict[tuple[str, str], dict] = {}

    def actor_for(self, project: str, caller: str, declared: dict) -> dict:
        # A declared identity survives cursor expiry and frame reloads.
        with self._lock:
            key = (project, caller)
            previous = self._actor_profiles.get(key)
            profile = {**(previous or {}), **declared}
            if not profile.get("color"):
                occupied = {
                    other["color"].strip().lower()
                    for (other_project, other_caller), other in self._actor_profiles.items()
                    if other_project == project and other_caller != caller
                }
                index = int.from_bytes(blake2b(caller.encode(), digest_size=2).digest(), "big") % len(_ACTOR_COLORS)
                options = _ACTOR_COLORS[index:] + _ACTOR_COLORS[:index]
                profile["color"] = next((color for color in options if color not in occupied), options[0])
            self._actor_profiles[key] = profile
            actor_id = profile.get("id", caller)
            if previous is not None and (previous_id := previous.get("id", caller)) != actor_id:
                message = {"hoardDock": 1, "type": "dock/cursor", "state": "gone", "actor": {"id": previous_id}}
                for session in self._sessions.values():
                    if session.project == project and not session.loop.is_closed():
                        try:
                            session.loop.call_soon_threadsafe(session.events.put_nowait, message)
                        except RuntimeError:
                            # A disconnect can close the loop between the check and the send.
                            pass
        return {"id": actor_id, "name": profile.get("name") or actor_id, "color": profile["color"]}

    def attach(self, project: str, revision: str | None = None) -> CanvasSession:
        session = CanvasSession(project, revision)
        with self._lock:
            self._sessions[session.id] = session
            self._lock.notify_all()
        return session

    def wait_for_revision(self, project: str, revision: str, *, timeout=PRESENCE_WAIT):
        # The previous write may have returned while the visible iframe still follows its revision.
        # Keep this wait outside the project lock so the preview can start the new runtime.
        with self._lock:
            if not any(session.project == project and session.revision for session in self._sessions.values()):
                return
            self._lock.wait_for(lambda: any(session.project == project and session.revision == revision
                                            for session in self._sessions.values()), timeout=timeout)

    def _detach(self, session):
        if self._sessions.pop(session.id, None) is None:
            return
        for pending in session.pending.values():
            pending.set_result(failure("preview_closed", "The preview closed before answering."))
        session.pending.clear()
        if not session.loop.is_closed():
            session.loop.call_soon_threadsafe(session.events.put_nowait, None)

    def detach(self, session: CanvasSession):
        with self._lock:
            self._detach(session)

    def detach_project(self, project: str):
        with self._lock:
            for session in list(self._sessions.values()):
                if session.project == project:
                    self._detach(session)

    def prepare_edit(self, project: str, revision: str, actor: dict, target: dict, *, timeout=PRESENCE_WAIT, change: dict | None = None):
        """Give attached previews a bounded chance to show the cursor before committing."""
        id = uuid.uuid4().hex
        event = {"hoardDock": 1, "type": "canvas/presence", "id": id,
                 "actor": actor, "revision": revision, "target": target,
                 "expires_at": int((time.time() + timeout) * 1000)}
        if change:
            event["change"] = change
        pending = {}
        with self._lock:
            for session in self._sessions.values():
                if session.project != project or session.loop.is_closed():
                    continue
                session.pending[id] = reply = Future()
                try:
                    session.loop.call_soon_threadsafe(session.events.put_nowait, event)
                except RuntimeError:
                    session.pending.pop(id)
                    continue
                pending[session.id] = reply
        try:
            if pending:
                wait(pending.values(), timeout=timeout)
        finally:
            with self._lock:
                for session_id in pending:
                    session = self._sessions.get(session_id)
                    if session:
                        session.pending.pop(id, None)

    def call(self, project: str, tool: str, args: dict, actor: dict, *, target=None, timeout: float = 47):
        id = uuid.uuid4().hex
        pending = Future()
        with self._lock:
            sessions = [session for session in self._sessions.values() if session.project == project]
            if not sessions:
                return failure("no_preview", "Open the project's preview in the Applications page first.")
            if len(sessions) > 1:
                return failure("multiple_previews", "Keep a single Applications tab open on this project's preview.")
            session = sessions[0]
            session.pending[id] = pending
            event = {"hoardDock": 1, "type": "dock/call", "id": id, "tool": tool, "args": args, "actor": actor}
            if target is not None:
                event["presence"] = target
            session.loop.call_soon_threadsafe(session.events.put_nowait, event)
        try:
            return pending.result(timeout)
        except TimeoutError:
            return failure("timeout", "The open preview did not answer in time.")
        finally:
            with self._lock:
                session.pending.pop(id, None)

    def resolve(self, project: str, session_id: str, call_id: str, result: dict) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.project != project:
                return False
            pending = session.pending.pop(call_id, None)
            if pending is None:
                return False
            pending.set_result(result)
            return True
