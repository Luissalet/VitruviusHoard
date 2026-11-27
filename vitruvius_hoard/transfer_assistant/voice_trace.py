"""Publish a completed voice turn to the local family bus without waiting for it."""

from hashlib import blake2s
import json
import os
from queue import Empty, Full, Queue
import re
from threading import Lock, Thread
from urllib.parse import parse_qs
from uuid import uuid4

import httpx

from ..hoard_link import family
from .reply import ReplyError, _loopback_origin


# The bus uses these fixed IDs and the original v1 wire labels.
STAGES = {
    "voice.turn": ("vitruvius", "Etapa", "Stage"),
    "voice.cut": ("vitruvius", "Etapa", "Stage"),
    "voice.upload": ("vitruvius", "Etapa", "Stage"),
    "voice.transcribe": ("cyrano", "Transcribir", "Transcribe"),
    "voice.transcribe_reserve": ("funes", "Transcribir", "Transcribe"),
    "voice.understand": ("cyrano", "Entender", "Understand"),
    "voice.local_understand": ("vitruvius", "Entender", "Understand"),
    "voice.speak": ("cyrano", "Hablar", "Speak"),
    "voice.cache": ("cyrano", "Hablar", "Speak"),
    "voice.execute": ("vitruvius", "Ejecutar", "Execute"),
}
OUTCOMES = {"ok", "fallback", "timeout", "error", "cancelled"}
ID = re.compile(r"[a-f0-9]{32}")
ROOT = "0" * 32


def _root_span(trace):
    return blake2s(trace.encode("ascii"), digest_size=16, person=b"vitvoice").hexdigest()


class TurnTrace:
    def __init__(self, *, send=None):
        self.queue = Queue(maxsize=16)
        self.lock = Lock()
        self.worker = None
        self.send = send or self._send

    @staticmethod
    def header(query):
        return TurnTrace.context(parse_qs(query).get("trace", [""])[0])

    @staticmethod
    def context(trace):
        if isinstance(trace, str) and ID.fullmatch(trace) and trace != ROOT:
            return f"{trace}/{_root_span(trace)}"
        return None

    @staticmethod
    def _records(body):
        try:
            report = json.loads(body)
            trace_id, stages = report["trace_id"], report["stages"]
            if not isinstance(trace_id, str) or not ID.fullmatch(trace_id) or trace_id == ROOT:
                return []
            if not isinstance(stages, list) or not 1 <= len(stages) <= len(STAGES):
                return []
        except (KeyError, TypeError, ValueError):
            return []
        root = _root_span(trace_id)
        spans = []
        seen = set()
        for stage in stages:
            if not isinstance(stage, list) or len(stage) != 4:
                return []
            operation, started, duration, outcome = stage
            if (not isinstance(operation, str) or operation not in STAGES or operation in seen
                    or type(started) not in (int, float) or not 0 < started < 1e12
                    or type(duration) not in (int, float) or not 0 <= duration <= 120_000
                    or not isinstance(outcome, str) or outcome not in OUTCOMES):
                return []
            seen.add(operation)
            callee, label_es, label_en = STAGES[operation]
            top = operation == "voice.turn"
            spans.append({
                "version": "hoard.trace/v1", "trace_id": trace_id,
                "span_id": root if top else uuid4().hex, "parent_id": None if top else root,
                "caller": "vitruvius", "callee": callee, "operation": operation,
                "label_es": label_es, "label_en": label_en, "started_at": started,
                "duration_ms": round(duration, 3), "outcome": outcome, "detail": {},
            })
        return spans if "voice.turn" in seen else []

    def submit(self, body):
        if os.environ.get("HOARD_TRACE", "1").strip().lower() in {"0", "false", "no", "off"}:
            return False
        if not family.status()["enabled"]:
            return False
        records = self._records(body)
        if not records:
            return False
        with self.lock:
            if self.worker is None or not self.worker.is_alive():
                self.worker = Thread(target=self._run, name="transfer-turn-trace", daemon=True)
                self.worker.start()
            try:
                self.queue.put_nowait(records)
            except Full:
                return False
        return True

    def _run(self):
        while True:
            try:
                batch = self.queue.get(timeout=10)
            except Empty:
                with self.lock:
                    if self.queue.empty():
                        self.worker = None
                        return
                continue
            try:
                self.send(batch)
            except (httpx.HTTPError, ReplyError, OSError, ValueError):
                pass
            finally:
                self.queue.task_done()

    @staticmethod
    def _send(spans):
        origin = _loopback_origin(family._hub())
        headers = family._headers()
        if not headers:
            return
        # Give a sleeping local bus a short grace period; there is no retry on failure.
        with httpx.Client(base_url=origin, headers=headers, trust_env=False, timeout=2.4) as client:
            response = client.post("/api/events/trace", json={"spans": spans})
            if response.status_code == 404:
                # An older bus accepts the same record as a normal event.
                for span in spans:
                    response = client.post("/api/events", json={"type": "trace.span", "data": span,
                                                               "source": "vitruvius"})
                    if not response.is_success:
                        break
