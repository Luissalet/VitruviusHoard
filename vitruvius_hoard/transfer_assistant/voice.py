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
from ..software.runtime import profile


VOICE_PREFIX = "/__vitruvius_preview__/transfer-voice/"
MAX_AUDIO = 4 * 1024 * 1024
MAX_JSON = 32 * 1024
DICTATION_VERSION = "cyrano.dictation/v0"
DICTATION_APP = "cyrano"
DICTATION_TOOLS = ("dictation_understand", "dictation_audio")
SPEECH_TOOL = "speech_transcribe"
FAMILY_TRANSCRIPTION = "Funes / Talos (reserva)"
CYRANO_SPEECH_S = 6
FINAL_TRANSCRIPTION_S = 21
DICTATION_AUDIO_S = 25
SPANISH_TTS_VOICE = "es_ES-davefx-medium"
VOICE_MODE = os.getenv("VITRUVIUS_TRANSFER_VOICE_MODE", "cache-natural")
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


def _tool_names(service):
    owner = _famsvc.owner_of(service)
    status, value = _hub_get(f"/api/apps/{owner}/tools", timeout=0.8)
    if status != 200 or not isinstance(value, dict) or not value.get("ok"):
        return set()
    return {tool.get("name") for tool in value.get("tools", []) if isinstance(tool, dict)}


def _offers(service, *required):
    return _tool_names(service).issuperset(required)


def _transcription_ready():
    if _offers("stt", "transcribe_file", "transcribe_status"):
        return True
    result = _famsvc.call_tool(_famsvc.owner_of("stt"), "transcribe_status",
                              {"job_id": uuid4().hex}, timeout_s=1)
    return result.get("ok", False) or (result.get("status") == 404 and "no such job" in result.get("error", "").lower())


def _dictation_details(*, include_stt=False):
    status, app = _hub_get(f"/api/apps/{DICTATION_APP}", timeout=0.5)
    if status != 200 or not isinstance(app, dict):
        return DICTATION_APP, {}
    health = app.get("health")
    health = health if isinstance(health, dict) else {}
    if not health.get("name") or (include_stt and not isinstance(health.get("stt"), dict)):
        url = app.get("url")
        if isinstance(url, str) and re.fullmatch(r"http://(?:127\.0\.0\.1|localhost|\[::1\]):\d{1,5}/?", url):
            status, fresh_health = fetch(url.rstrip("/") + "/api/health", timeout=0.5)
            if status == 200 and isinstance(fresh_health, dict) and fresh_health.get("service") == "cyrano-hoard":
                health = {**health, **fresh_health}
    name = DICTATION_APP
    for candidate in (health.get("name"), app.get("name")):
        if isinstance(candidate, str) and candidate.strip():
            name = candidate.strip()
            break
    stt = health.get("stt")
    return name, stt if isinstance(stt, dict) and stt.get("warm") is True else {}


def _cyrano_transcription_provider(result):
    if result.get("engine") == "family":
        return FAMILY_TRANSCRIPTION
    model, gpu = result.get("model"), result.get("gpu")
    has_model = isinstance(model, str) and bool(model.strip())
    has_gpu = type(gpu) is int and gpu >= 0
    name, health = _dictation_details(include_stt=not (has_model and has_gpu))
    if not (has_model and has_gpu):
        model = model if has_model else health.get("model")
        gpu = gpu if has_gpu else health.get("gpu")
    parts = [re.sub(r"['’]s Hoard$", "", name, flags=re.IGNORECASE).rstrip() or name]
    if type(gpu) is int and gpu >= 0:
        parts.append(f"GPU {gpu}")
    if isinstance(model, str) and model.strip():
        parts.append(model.strip())
    return " · ".join(parts)


def _cache_root():
    configured = os.environ.get("VITRUVIUS_VOICE_CACHE")
    return Path(configured).resolve() if configured else profile() / "voice-cache"


def _cache_phrases(root):
    try:
        manifest = json.loads((root / "frases.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    phrases = manifest.get("phrases") if isinstance(manifest, dict) else None
    return {key: text for key, text in phrases.items() if isinstance(text, str)} if isinstance(phrases, dict) else {}


def _cached_reply(root, phrase_id):
    try:
        path = (root / f"{phrase_id}.wav").resolve()
        if path.parent != root:
            return _json(404, code="voice_phrase_unavailable")
        audio = path.read_bytes()
    except (OSError, ValueError):
        return _json(404, code="voice_phrase_unavailable")
    if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        return _json(404, code="voice_phrase_unavailable")
    return 200, audio, "audio/wav; source=cache-natural"


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
        outcome = family.call(DICTATION_APP, tool, args, timeout=timeout)
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
            tools = _tool_names("dictation")
            ready = tools.issuperset(DICTATION_TOOLS)
            route = ("common" if common else "app") if ready else "local"
            phrases = _cache_phrases(_cache_root())
            tts = bool(phrases) and (VOICE_MODE == "cache-natural" or VOICE_MODE == "piper" and _offers("tts", "voice_tts"))
            return _json(200, stt=SPEECH_TOOL in tools or _transcription_ready(),
                         tts=tts, dictation=ready, dictation_route=route,
                         dictation_name=_dictation_details()[0],
                         **({"voice_phrases": phrases} if phrases else {}))
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
                started = monotonic()
                window = 1 if preview else CYRANO_SPEECH_S
                value, _ = self._dictation_call(SPEECH_TOOL, {
                    "path": str(path), "language": language, "initial_prompt": prompt,
                    "vad": not preview, "fallback": False, "timeout_s": window,
                }, timeout=window + 1)
                if isinstance(value, dict) and isinstance(value.get("text"), str):
                    return _json(200, text=value["text"], final=not preview,
                                 provider=_cyrano_transcription_provider(value))

                budget = 2 if preview else FINAL_TRANSCRIPTION_S
                remaining = max(1, budget - (monotonic() - started))
                result = fam_media.transcribe(str(path), language=language, word_timestamps=False, initial_prompt=prompt,
                                              timeout_s=remaining, local_fallback=False, vad=not preview)
                if result.get("still_running") and result.get("job_id"):
                    fam_media.transcribe_cancel(result["job_id"])
            if not result.get("ok"):
                return _json(503, code="stt_unavailable")
            return _json(200, text=result.get("text") or "", final=not preview, provider=FAMILY_TRANSCRIPTION)
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
        return _json(200, **{**value, "dictation_route": route, "dictation_name": _dictation_details()[0]})

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
        legacy_text, language = request.get("text"), request.get("language", "es")
        if language not in ("es", "en"):
            return _json(400, code="invalid_voice_request")
        if "text" in request and (not isinstance(legacy_text, str) or not 0 < len(legacy_text.strip()) <= 1000):
            return _json(400, code="invalid_voice_request")
        if VOICE_MODE not in ("cache-natural", "piper"):
            return _json(503, code="tts_disabled")
        phrase_id = request.get("phrase_id")
        if language != "es" or not isinstance(phrase_id, str) or not re.fullmatch(r"[a-z-]{1,40}", phrase_id):
            return _json(404, code="voice_phrase_unavailable")
        root = _cache_root()
        text = _cache_phrases(root).get(phrase_id)
        if not text:
            return _json(404, code="voice_phrase_unavailable")
        if VOICE_MODE == "cache-natural":
            return _cached_reply(root, phrase_id)
        result = fam_media.speak_bytes(text, lang=language, timeout_s=12, local_fallback=False,
                                       voice=SPANISH_TTS_VOICE, engine="piper")
        if not result.get("ok") or not result.get("data"):
            if result.get("status") == 409 or "generation is off" in str(result.get("error")).lower():
                return _json(409, code="tts_disabled")
            return _json(503, code="tts_unavailable")
        return 200, result["data"], "audio/wav"
