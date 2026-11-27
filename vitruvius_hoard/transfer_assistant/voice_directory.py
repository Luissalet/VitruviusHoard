"""Cached loopback routes for the transfer assistant's voice services."""

from dataclasses import dataclass
import os
from pathlib import Path
from threading import Lock, Thread
from time import monotonic

import httpx

from ..hoard_link import family
from ..hoard_link._hubclient import fetch
from .reply import ReplyError, _loopback_origin


DICTATION_APP = "cyrano"
STT_APP = "funes"
TTS_APP = "prospero"
REFRESH_S = 120
RETRY_S = 10
SPEECH_PATHS = {
    "speech_transcribe": "/api/speech/transcribe",
    "dictation_understand": "/api/dictation/understand",
    "dictation_end_turn": "/api/dictation/end-turn",
}


@dataclass(frozen=True)
class VoiceApp:
    url: str
    name: str
    tools: frozenset[str]
    token_file: str = ""


@dataclass(frozen=True)
class VoiceCall:
    value: dict | None = None
    reason: str = ""
    ms: float = 0


def _hub_apps():
    try:
        origin = _loopback_origin(family._hub())
    except ReplyError:
        return None
    status, catalogue = fetch(origin + "/api/apps", timeout=2.5, headers=family._headers())
    if status == 200 and isinstance(catalogue, dict) and isinstance(catalogue.get("apps"), list):
        return catalogue["apps"]
    return None


def _request(url, path, *, arguments=None, timeout=1, token=None, trace=None):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if trace:
        headers["X-Hoard-Trace"] = trace
    # The directory accepts HTTP loopback only. Avoid constructing a TLS context for each voice call.
    with httpx.Client(base_url=url, follow_redirects=False, trust_env=False, verify=False, timeout=timeout) as client:
        if arguments is None:
            return client.get(path, headers=headers)
        return client.post(path, headers=headers, json=arguments)


def _lookup(row, url, *, token_file=""):
    try:
        origin = _loopback_origin(url)
    except ReplyError:
        return None
    try:
        response = _request(origin, "/api/agent/tools", timeout=0.75)
        payload = response.json() if response.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        payload = {}
    tools = payload.get("tools") if isinstance(payload, dict) else None
    health = row.get("health")
    name = health.get("name") if isinstance(health, dict) else None
    return VoiceApp(origin, str(name or row.get("name") or ""), frozenset(
        entry["name"] for entry in tools or () if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    ), token_file)


class VoiceDirectory:
    def __init__(self):
        self._lock = Lock()
        self._ready = False
        self._refreshing = False
        self._refresh_at = self._retry_at = float("-inf")
        self._apps = {}
        configured = os.environ.get("CYRANO_URL")
        if configured is not None:
            try:
                origin = _loopback_origin(configured)
                self._apps[DICTATION_APP] = VoiceApp(origin, "", frozenset())
            except ReplyError:
                pass
        self._configured = configured

    def app(self, app_id):
        # The published snapshot is replaced atomically. It is never locked during I/O.
        return self._apps.get(app_id)

    def origin(self):
        app = self.app(DICTATION_APP)
        return app.url if app else None

    def prepare(self):
        """Initial discovery is part of page setup. Subsequent reads use the cached snapshot."""
        with self._lock:
            first = not self._ready and not self._refreshing
            if first:
                self._refreshing = True
        if first:
            self._load()
        else:
            self.refresh()

    def refresh(self, *, failed=False):
        with self._lock:
            if self._refreshing or monotonic() < (self._retry_at if failed else self._refresh_at):
                return
            self._refreshing = True
        Thread(target=self._load, name="transfer-voice-discovery", daemon=True).start()

    def _load(self):
        apps = dict(self._apps)
        rows = None
        try:
            rows = _hub_apps()
            by_id = {row["id"]: row for row in rows or () if isinstance(row, dict) and row.get("id") in (
                DICTATION_APP, STT_APP, TTS_APP,
            )}
            for app_id in (DICTATION_APP, STT_APP, TTS_APP):
                row = by_id.get(app_id, {})
                override = self._configured if app_id == DICTATION_APP else None
                url = override if override is not None else row.get("url")
                # Never send an installed or discovered app token to an override.
                path = row.get("token_file") if override is None else None
                found = _lookup(row, url, token_file=path if isinstance(path, str) else "")
                previous = apps.get(app_id)
                if found and (found.tools or previous is None):
                    apps[app_id] = found
            self._apps = apps
        finally:
            with self._lock:
                self._ready = True
                self._refreshing = False
                self._retry_at = monotonic() + RETRY_S
                self._refresh_at = monotonic() + (REFRESH_S if rows is not None else RETRY_S)

    def _call(self, app_id, path, args, *, timeout, agent=False, trace=None):
        app = self.app(app_id)
        if app is None:
            self.refresh(failed=True)
            return VoiceCall(reason="boltagon_undiscovered" if app_id == DICTATION_APP else "service_undiscovered")
        headers_token = None
        if agent:
            try:
                if app.token_file:
                    headers_token = Path(app.token_file).read_text(encoding="utf-8-sig").strip()
            except OSError:
                pass
            if not headers_token:
                return VoiceCall(reason="service_auth")
        start = monotonic()
        try:
            response = _request(app.url, path, arguments=args, timeout=timeout, token=headers_token, trace=trace)
        except httpx.TimeoutException:
            self.refresh(failed=True)
            return VoiceCall(reason="boltagon_timeout", ms=(monotonic() - start) * 1000)
        except httpx.HTTPError:
            self.refresh(failed=True)
            return VoiceCall(reason="boltagon_unreachable", ms=(monotonic() - start) * 1000)
        ms = (monotonic() - start) * 1000
        try:
            value = response.json()
        except ValueError:
            value = None
        if response.status_code == 200 and isinstance(value, dict):
            result = value.get("result", value) if agent else value
            if isinstance(result, dict) and (not agent or value.get("ok") is not False):
                return VoiceCall(value=result, ms=ms)
        kind = {
            401: "service_auth",
            403: "service_auth",
            404: "boltagon_contract_missing",
            422: "boltagon_invalid_request",
            429: "boltagon_busy",
        }.get(response.status_code, "boltagon_failed")
        if kind == "boltagon_contract_missing":
            self.refresh(failed=True)
        details = value.get("detail") if isinstance(value, dict) else None
        if agent and isinstance(value, dict):
            return VoiceCall(value=value, reason=kind, ms=ms)
        if isinstance(details, dict):
            speech_trace = details.get("trace")
            why = speech_trace.get("fallback_reason") if isinstance(speech_trace, dict) else details.get("cause")
            if isinstance(why, str) and why.startswith("resident_") and why.isascii() and why.isidentifier():
                kind = why
        return VoiceCall(reason=kind, ms=ms)

    def dictation(self, operation, args, *, timeout, trace=None):
        return self._call(DICTATION_APP, SPEECH_PATHS[operation], args, timeout=timeout, trace=trace)

    def tool(self, app_id, tool, args, *, timeout, trace=None):
        return self._call(app_id, "/api/agent/call", {"name": tool, "arguments": args},
                          timeout=timeout, agent=True, trace=trace)
