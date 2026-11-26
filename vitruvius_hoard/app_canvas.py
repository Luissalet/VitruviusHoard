"""Relay calls from native agent tools to an already open preview frame."""
from __future__ import annotations

import asyncio
import threading
import uuid
from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass, field


def failure(code: str, message: str):
    return {"ok": False, "error": {"code": code, "message": message}}


@dataclass
class CanvasSession:
    project: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    loop: asyncio.AbstractEventLoop = field(default_factory=asyncio.get_running_loop)
    events: asyncio.Queue = field(default_factory=asyncio.Queue)
    pending: dict[str, Future] = field(default_factory=dict)


class CanvasSessions:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: dict[str, CanvasSession] = {}

    def attach(self, project: str) -> CanvasSession:
        session = CanvasSession(project)
        with self._lock:
            self._sessions[session.id] = session
        return session

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

    def call(self, project: str, tool: str, args: dict, actor: dict, *, timeout: float = 47):
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
