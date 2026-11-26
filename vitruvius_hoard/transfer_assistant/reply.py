"""Relay the resident voice job through an owned preview's origin."""

from contextlib import contextmanager
from dataclasses import dataclass
import re
from threading import Lock
from typing import Iterable
from urllib.parse import urlsplit

import httpx


VERSION = "cyrano.voice/v0"
NDJSON = "application/x-ndjson"
ENGINE_ID = re.compile(r"[a-zA-Z0-9_.-]{1,128}")
JOB_ID = re.compile(r"[a-f0-9]{32}")


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
        self.closed = False

    def _client(self, origin, **kwargs):
        return self.client_factory(base_url=origin, follow_redirects=False, trust_env=False, **kwargs)

    @contextmanager
    def stream(self, arguments):
        origin = _loopback_origin(self.origin())
        job_id = None
        finished = False
        registered = False
        try:
            with self._client(origin, timeout=httpx.Timeout(4, read=None)) as client:
                receipt = client.post("/api/voice/speak", json=arguments, timeout=4)
                _check_response(receipt)
                job = receipt.json()
                candidate = job.get("job_id") if isinstance(job, dict) else None
                if not isinstance(candidate, str) or not JOB_ID.fullmatch(candidate):
                    raise ReplyError("tts_invalid_reply", 502)
                job_id = candidate
                engine = job.get("engine_id")
                path = f"/api/voice/jobs/{job_id}/stream"
                if (job.get("version") != VERSION or not isinstance(engine, str) or not ENGINE_ID.fullmatch(engine)
                        or job.get("stream_url") != path or arguments.get("engine", engine) != engine):
                    raise ReplyError("tts_invalid_reply", 502)
                with self.lock:
                    if self.closed:
                        raise ReplyError("tts_unavailable", 503)
                    self.active[job_id] = origin
                    registered = True
                with client.stream("GET", path) as response:
                    _check_response(response)
                    if response.headers.get("Content-Type", "").split(";", 1)[0] != NDJSON:
                        raise ReplyError("tts_invalid_reply", 502)

                    def packets():
                        nonlocal finished
                        yield from response.iter_raw()
                        finished = True

                    yield ReplyStream(job_id, engine, packets())
        except (httpx.HTTPError, ValueError) as error:
            raise ReplyError("tts_unavailable", 503) from error
        finally:
            if job_id:
                if registered:
                    self.cancel(job_id, finished=finished)
                else:
                    self._cancel(origin, job_id)

    def _cancel(self, origin, job_id):
        try:
            with self._client(origin, timeout=1) as client:
                client.delete(f"/api/voice/jobs/{job_id}")
        except httpx.HTTPError:
            pass  # the worker may have stopped while the browser was playing

    def cancel(self, job_id, *, finished=False):
        with self.lock:
            origin = self.active.pop(job_id, None)
        if origin and not finished:
            self._cancel(origin, job_id)

    def close(self):
        with self.lock:
            self.closed = True
            active = self.active
            self.active = {}
        for job_id, origin in active.items():
            self._cancel(origin, job_id)
