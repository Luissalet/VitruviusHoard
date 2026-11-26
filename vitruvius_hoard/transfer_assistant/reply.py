"""Relay the resident voice job through an owned preview's origin."""

from contextlib import contextmanager
from dataclasses import dataclass
import re
from threading import Lock
from time import monotonic
from typing import Iterable
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


VERSION = "cyrano.voice/v0"
NDJSON = "application/x-ndjson"
ENGINE_ID = re.compile(r"[a-zA-Z0-9_.-]{1,128}")
JOB_ID = re.compile(r"[a-f0-9]{32}")
EARLY_CANCEL_S = 60


class ReplyError(Exception):
    def __init__(self, code, status):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass
class ReplyStream:
    job_id: str
    engine: str
    chunks: Iterable[bytes]


@dataclass
class PendingReply:
    cancelled: bool = False
    job: tuple[str, str] | None = None

    def take_job(self):
        job, self.job = self.job, None
        return job


def _loopback_origin(url):
    if not isinstance(url, str):
        raise ReplyError("tts_unavailable", 503)
    try:
        parts = urlsplit(url)
        if (parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}
                and parts.port and parts.username is None and parts.password is None
                and parts.path in ("", "/") and not parts.query and not parts.fragment):
            return f"http://{parts.netloc}"
    except ValueError:
        pass
    raise ReplyError("tts_unavailable", 503)


def _check_response(response):
    if response.status_code == 200:
        return
    code = "tts_unavailable"
    if response.is_error:
        try:
            details = response.json()
            if isinstance(details, dict) and isinstance(details.get("code"), str):
                code = details["code"]
        except (ValueError, httpx.ResponseNotRead):
            pass
    raise ReplyError(code, response.status_code if response.is_error else 503)


class ReplyRelay:
    def __init__(self, origin, client_factory=None):
        self.origin = origin
        self.client_factory = client_factory or httpx.Client
        self.lock = Lock()
        self.active = {}
        self.cancelled_requests = {}
        self.closed = False

    def _client(self, origin, **kwargs):
        return self.client_factory(base_url=origin, follow_redirects=False, trust_env=False, **kwargs)

    @contextmanager
    def stream(self, arguments, request_id=None):
        key = request_id or uuid4().hex
        with self.lock:
            self._prune_cancellations()
            if self.closed:
                raise ReplyError("tts_unavailable", 503)
            if key in self.cancelled_requests:
                raise ReplyError("tts_cancelled", 409)
            if key in self.active:
                raise ReplyError("tts_request_exists", 409)
            pending = self.active[key] = PendingReply()
        finished = False
        try:
            origin = _loopback_origin(self.origin())
            with self._client(origin, timeout=httpx.Timeout(4, read=None)) as client:
                self._check_pending(pending)
                receipt = client.post("/api/voice/speak", json=arguments, timeout=4)
                _check_response(receipt)
                job = receipt.json()
                candidate = job.get("job_id") if isinstance(job, dict) else None
                if not isinstance(candidate, str) or not JOB_ID.fullmatch(candidate):
                    raise ReplyError("tts_invalid_reply", 502)
                job_id = candidate
                with self.lock:
                    pending.job = (origin, job_id)
                self._check_pending(pending)
                engine = job.get("engine_id")
                path = f"/api/voice/jobs/{job_id}/stream"
                if (job.get("version") != VERSION or not isinstance(engine, str) or not ENGINE_ID.fullmatch(engine)
                        or job.get("stream_url") != path or arguments.get("engine", engine) != engine):
                    raise ReplyError("tts_invalid_reply", 502)
                with client.stream("GET", path) as response:
                    self._check_pending(pending)
                    _check_response(response)
                    if response.headers.get("Content-Type", "").split(";", 1)[0] != NDJSON:
                        raise ReplyError("tts_invalid_reply", 502)

                    def packets():
                        nonlocal finished
                        for chunk in response.iter_raw():
                            self._check_pending(pending)
                            yield chunk
                        finished = True

                    yield ReplyStream(job_id, engine, packets())
        except (httpx.HTTPError, ValueError) as error:
            raise ReplyError("tts_unavailable", 503) from error
        finally:
            with self.lock:
                if self.active.get(key) is pending:
                    self.active.pop(key)
                job = pending.take_job()
            if job and not finished:
                self._cancel(*job)

    def _check_pending(self, pending):
        with self.lock:
            if pending.cancelled:
                raise ReplyError("tts_cancelled", 409)

    def _prune_cancellations(self):
        now = monotonic()
        while self.cancelled_requests:
            key = next(iter(self.cancelled_requests))
            if self.cancelled_requests[key] > now:
                break
            self.cancelled_requests.pop(key)

    def _cancel(self, origin, job_id):
        try:
            with self._client(origin, timeout=1) as client:
                client.delete(f"/api/voice/jobs/{job_id}")
        except httpx.HTTPError:
            pass  # the worker may have stopped while the browser was playing

    def _detach(self, key):
        pending = self.active.pop(key, None)
        if pending:
            pending.cancelled = True
            return pending.take_job()

    def cancel_request(self, request_id):
        with self.lock:
            self._prune_cancellations()
            # A DELETE may arrive before the browser's POST reaches this relay.
            self.cancelled_requests.pop(request_id, None)
            self.cancelled_requests[request_id] = monotonic() + EARLY_CANCEL_S
            job = self._detach(request_id)
        if job:
            self._cancel(*job)

    def cancel(self, job_id):
        with self.lock:
            key = next((key for key, pending in self.active.items() if pending.job and pending.job[1] == job_id), None)
            job = self._detach(key)
        if job:
            self._cancel(*job)

    def close(self):
        with self.lock:
            self.closed = True
            jobs = [self._detach(key) for key in list(self.active)]
            self.cancelled_requests.clear()
        for job in jobs:
            if job:
                self._cancel(*job)
