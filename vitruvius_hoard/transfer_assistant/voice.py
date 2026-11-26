"""Same-origin voice access for an opted-in application preview."""

from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from urllib.parse import parse_qs

from ..hoard_link import fam_media, family


VOICE_PREFIX = "/__vitruvius_preview__/transfer-voice/"
MAX_AUDIO = 4 * 1024 * 1024
MAX_JSON = 32 * 1024
DICTATION_VERSION = "cyrano.dictation/v0"
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


class TransferVoice:
    def __init__(self):
        self.partial = Lock()

    @staticmethod
    def max_body(route):
        if route == "transcribe":
            return MAX_AUDIO
        if route == "understand":
            return MAX_AUDIO * 4 // 3 + MAX_JSON
        return MAX_JSON

    def handle(self, method, route, query, content_type, body):
        if method == "GET" and route == "capabilities":
            return _json(200, stt=fam_media.available("stt"), tts=fam_media.available("tts"),
                         dictation=fam_media.available("cyrano"))
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
        if preview and not self.partial.acquire(blocking=False):
            return _json(429, code="partial_busy")
        try:
            with TemporaryDirectory(prefix="transfer-voice-") as directory:
                path = Path(directory) / ("utterance" + suffix)
                path.write_bytes(body)
                result = fam_media.transcribe(str(path), language=language, word_timestamps=False,
                                              timeout_s=2 if preview else 10, local_fallback=False, vad=not preview)
                if result.get("still_running") and result.get("job_id"):
                    fam_media.transcribe_cancel(result["job_id"])
            if not result.get("ok"):
                return _json(503, code="stt_unavailable")
            return _json(200, text=result.get("text") or "", final=not preview)
        finally:
            if preview:
                self.partial.release()

    @staticmethod
    def _understand(body):
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
            result = family.call("cyrano", "dictation_understand", {**options, "text": text}, timeout=2)
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
                result = family.call("cyrano", "dictation_audio", {**options, "path": str(path)}, timeout=11)
        value = result.get("result")
        if not result.get("ok") or not isinstance(value, dict) or value.get("version") != DICTATION_VERSION:
            return _json(503, code="dictation_unavailable")
        return _json(200, **value)

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
        result = fam_media.speak_bytes(text, lang=language, timeout_s=7, local_fallback=False)
        if not result.get("ok") or not result.get("data"):
            return _json(503, code="tts_unavailable")
        return 200, result["data"], "audio/wav"
