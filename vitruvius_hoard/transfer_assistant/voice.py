"""Same-origin voice access for an opted-in application preview."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic
from urllib.parse import parse_qs
from uuid import uuid4

from ..hoard_link import _famsvc, fam_media, family
from ..hoard_link._hubclient import fetch


VOICE_PREFIX = "/__vitruvius_preview__/transfer-voice/"
MAX_AUDIO = 4 * 1024 * 1024
MAX_JSON = 32 * 1024
DICTATION_VERSION = "cyrano.dictation/v0"
DICTATION_TOOLS = ("dictation_understand", "dictation_audio")
FINAL_TRANSCRIPTION_S = 21
DICTATION_AUDIO_S = 25
SPANISH_TTS_VOICE = "es_ES-davefx-medium"
VOICE_MODE = os.getenv("VITRUVIUS_TRANSFER_VOICE_MODE", "cache-natural")
VOICE_CACHE = os.getenv("VITRUVIUS_VOICE_CACHE", "")
AUDIO_TYPES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
}


def _json(status, **value):
    return status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"


def _hub_get(path, timeout):
    return fetch(family._hub() + path, timeout=timeout, headers=family._headers())


def _offers(service, *required):
    owner = _famsvc.owner_of(service)
    status, value = _hub_get(f"/api/apps/{owner}/tools", timeout=0.8)
    if status != 200 or not isinstance(value, dict) or not value.get("ok"):
        return False
    names = {tool.get("name") for tool in value.get("tools", []) if isinstance(tool, dict)}
    return names.issuperset(required)


def _transcription_ready():
    if _offers("stt", "transcribe_file", "transcribe_status"):
        return True
    result = _famsvc.call_tool(_famsvc.owner_of("stt"), "transcribe_status",
                              {"job_id": uuid4().hex}, timeout_s=1)
    return result.get("ok", False) or (result.get("status") == 404 and "no such job" in result.get("error", "").lower())


def _cache_root():
    return Path(VOICE_CACHE).resolve() if VOICE_CACHE else None


def _cached_reply(phrase_id, text):
    root = _cache_root()
    if root is None or not isinstance(phrase_id, str) or not re.fullmatch(r"[a-z-]{1,40}", phrase_id):
        return _json(404, code="voice_phrase_unavailable")
    try:
        manifest = json.loads((root / "frases.json").read_text(encoding="utf-8-sig"))
        phrases = manifest.get("phrases", {}) if isinstance(manifest, dict) else {}
        path = (root / f"{phrase_id}.wav").resolve()
        if not isinstance(phrases, dict) or phrases.get(phrase_id) != text or path.parent != root:
            return _json(404, code="voice_phrase_unavailable")
        audio = path.read_bytes()
    except (OSError, ValueError):
        return _json(404, code="voice_phrase_unavailable")
    if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        return _json(404, code="voice_phrase_unavailable")
    return 200, audio, "audio/wav; source=cache-natural"


def _voice_ready():
    if VOICE_MODE == "piper":
        return _offers("tts", "voice_tts")
    root = _cache_root()
    return VOICE_MODE == "cache-natural" and root is not None and (root / "frases.json").is_file()


class TransferVoice:
    def __init__(self):
        self.partial = Lock()
        self.discovery = Lock()
        self.discovered_at = float("-inf")
        self.registered = False

    def _common_dictation(self):
        with self.discovery:
            now = monotonic()
            if now - self.discovered_at >= 8:
                status, catalogue = _hub_get("/api/services/status", timeout=2.2)
                self.registered = status == 200 and isinstance(catalogue, dict) and any(
                    row.get("service") == "dictation" for row in catalogue.get("services", []) if isinstance(row, dict)
                )
                self.discovered_at = now
            return self.registered

    def _dictation_call(self, tool, args, *, timeout):
        if self._common_dictation():
            outcome = _famsvc.call_tool(_famsvc.owner_of("dictation"), tool, args, timeout_s=timeout)
            return (outcome.get("data") if outcome.get("ok") else None), "common"
        outcome = family.call("cyrano", tool, args, timeout=timeout)
        return (outcome.get("result") if outcome.get("ok") else None), "app"

    @staticmethod
    def max_body(route):
        if route == "transcribe":
            return MAX_AUDIO
        if route == "understand":
            return MAX_AUDIO * 4 // 3 + MAX_JSON
        return MAX_JSON

    def handle(self, method, route, query, content_type, body):
        if method == "GET" and route == "capabilities":
            common = self._common_dictation()
            ready = _offers("dictation", *DICTATION_TOOLS)
            route = ("common" if common else "app") if ready else "local"
            return _json(200, stt=_transcription_ready(),
                         tts=_voice_ready(), dictation=ready, dictation_route=route)
        if method == "POST" and route == "transcribe":
            return self._transcribe(query, content_type, body)
        if method == "POST" and route == "understand":
            return self._understand(body)
        if method == "POST" and route == "speak":
            return self._speak(body)
        return _json(404, code="voice_route_not_found")

    def _transcribe(self, query, content_type, body):
        suffix = AUDIO_TYPES.get(content_type.split(";", 1)[0].lower())
        if not suffix:
            return _json(415, code="unsupported_audio")
        if not body or len(body) > MAX_AUDIO:
            return _json(400, code="invalid_audio")
        parameters = parse_qs(query)
        language = parameters.get("language", ["es"])[0]
        if language not in ("es", "en"):
            return _json(400, code="invalid_language")
        preview = parameters.get("partial", ["false"])[0] == "true"
        prompt = parameters.get("initial_prompt", [""])[0][:1000]
        if preview and not self.partial.acquire(blocking=False):
            return _json(429, code="partial_busy")
        try:
            with TemporaryDirectory(prefix="transfer-voice-") as directory:
                path = Path(directory) / ("utterance" + suffix)
                path.write_bytes(body)
                result = fam_media.transcribe(str(path), language=language, word_timestamps=False, initial_prompt=prompt,
                                              timeout_s=2 if preview else FINAL_TRANSCRIPTION_S,
                                              local_fallback=False, vad=not preview)
                if result.get("still_running") and result.get("job_id"):
                    fam_media.transcribe_cancel(result["job_id"])
            if not result.get("ok"):
                return _json(503, code="stt_unavailable")
            return _json(200, text=result.get("text") or "", final=not preview)
        finally:
            if preview:
                self.partial.release()

    def _understand(self, body):
        try:
            request = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return _json(400, code="invalid_dictation")
        if not isinstance(request, dict) or request.get("version") != DICTATION_VERSION:
            return _json(400, code="invalid_dictation")
        language = request.get("language", "es-ES")
        if language not in ("es-ES", "en-IE"):
            return _json(400, code="invalid_language")
        options = {name: request[name] for name in ("version", "language", "vocabulary", "schema", "context") if name in request}
        if len(json.dumps(options).encode("utf-8")) > MAX_JSON:
            return _json(400, code="invalid_dictation")
        text, audio = request.get("text"), request.get("audio")
        if (text is None) == (audio is None):
            return _json(400, code="invalid_dictation")
        if text is not None:
            if not isinstance(text, str) or not 0 < len(text.strip()) <= 1000:
                return _json(400, code="invalid_dictation")
            value, route = self._dictation_call("dictation_understand", {**options, "text": text}, timeout=2)
        else:
            if not isinstance(audio, dict) or not isinstance(audio.get("mime_type"), str):
                return _json(400, code="invalid_audio")
            suffix = AUDIO_TYPES.get(audio["mime_type"].split(";", 1)[0].lower())
            if not suffix:
                return _json(415, code="unsupported_audio")
            try:
                raw = base64.b64decode(audio["data_base64"], validate=True)
            except (binascii.Error, ValueError, TypeError, KeyError):
                return _json(400, code="invalid_audio")
            if not 0 < len(raw) <= MAX_AUDIO:
                return _json(400, code="invalid_audio")
            with TemporaryDirectory(prefix="transfer-dictation-") as directory:
                path = Path(directory) / ("utterance" + suffix)
                path.write_bytes(raw)
                value, route = self._dictation_call("dictation_audio", {**options, "path": str(path)}, timeout=DICTATION_AUDIO_S)
        if not isinstance(value, dict) or value.get("version") != DICTATION_VERSION:
            return _json(503, code="dictation_unavailable")
        return _json(200, **{**value, "dictation_route": route})

    @staticmethod
    def _speak(body):
        if not body or len(body) > MAX_JSON:
            return _json(400, code="invalid_voice_request")
        try:
            request = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return _json(400, code="invalid_voice_request")
        if not isinstance(request, dict):
            return _json(400, code="invalid_voice_request")
        text, language = request.get("text"), request.get("language", "es")
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 1000 or language not in ("es", "en"):
            return _json(400, code="invalid_voice_request")
        if VOICE_MODE == "cache-natural":
            return _cached_reply(request.get("phrase_id"), text) if language == "es" else _json(404, code="voice_phrase_unavailable")
        if VOICE_MODE != "piper":
            return _json(503, code="tts_disabled")
        result = fam_media.speak_bytes(text, lang=language, timeout_s=12, local_fallback=False,
                                       voice=SPANISH_TTS_VOICE if language == "es" else None,
                                       engine="piper" if language == "es" else None)
        if not result.get("ok") or not result.get("data"):
            if result.get("status") == 409 or "generation is off" in str(result.get("error")).lower():
                return _json(409, code="tts_disabled")
            return _json(503, code="tts_unavailable")
        return 200, result["data"], "audio/wav"
