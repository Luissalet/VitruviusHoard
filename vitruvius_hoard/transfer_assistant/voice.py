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
from time import monotonic, sleep
from urllib.parse import parse_qs, urlencode

from ..hoard_link.waiting import DONE_STATES
from ..software.runtime import profile
from .form_extraction import extract_missing
from .reply import ENGINE_ID, JOB_ID, VERSION as TTS_VERSION, ReplyError, ReplyRelay
from .voice_directory import DICTATION_APP, STT_APP, TTS_APP, VoiceDirectory
from .voice_trace import TurnTrace


VOICE_PREFIX = "/__vitruvius_preview__/transfer-voice/"
MAX_AUDIO = 4 * 1024 * 1024
MAX_JSON = 32 * 1024
MAX_REPLY_JSON = 128 * 1024
DICTATION_VERSION = "cyrano.dictation/v0"
DICTATION_DISPLAY_NAME = "Boltagon"
DICTATION_TOOLS = {"dictation_understand", "dictation_audio"}
SPEECH_TOOL = "speech_transcribe"
END_TURN_TOOL = "dictation_end_turn"
FAMILY_TRANSCRIPTION = "Funes / Talos (reserva)"
CYRANO_SPEECH_S = 6
FINAL_TRANSCRIPTION_S = 21
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


def _visible_dictation_name(candidate):
    if not isinstance(candidate, str):
        return None
    name = candidate.strip()
    label = re.sub(r"['’]s Hoard$", "", name, flags=re.IGNORECASE).strip()
    return name if label and label.casefold() not in (DICTATION_APP, "cyrano-hoard") else None


def _cyrano_transcription_provider(result, name):
    if result.get("engine") == "family":
        return FAMILY_TRANSCRIPTION
    model, gpu = result.get("model"), result.get("gpu")
    label = re.sub(r"['’]s Hoard$", "", name, flags=re.IGNORECASE).strip()
    parts = [label]
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
    def __init__(self, *, replies=None, directory=None, tracer=None, form_chat=None):
        self.partial = Lock()
        self.directory = directory if directory is not None else VoiceDirectory()
        self.replies = replies if replies is not None else ReplyRelay(self.directory.origin)
        self.tracer = tracer if tracer is not None else TurnTrace()
        self.form_chat = form_chat

    @property
    def dictation_name(self):
        app = self.directory.app(DICTATION_APP)
        return (_visible_dictation_name(app.name) if app else None) or DICTATION_DISPLAY_NAME

    def _fallback_transcription(self, body, suffix, *, language, prompt, preview, timeout, trace):
        if not self.directory.app(STT_APP):
            return None
        deadline = monotonic() + timeout
        with TemporaryDirectory(prefix="transfer-voice-") as directory:
            path = Path(directory) / ("utterance" + suffix)
            path.write_bytes(body)
            outcome = self.directory.tool(STT_APP, "transcribe_file", {
                "path": str(path), "language": language, "word_timestamps": False,
                "initial_prompt": prompt, "vad": not preview, "wait_s": 0,
            }, timeout=min(1, timeout), trace=trace)
            result = outcome.value or {}
            job = result.get("job_id")
            finished = {*DONE_STATES, "completed", "ok"}
            while job and result.get("status") not in finished:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                polled = monotonic()
                outcome = self.directory.tool(STT_APP, "transcribe_status", {
                    "job_id": job, "wait_s": remaining,
                }, timeout=remaining + 0.25, trace=trace)
                if outcome.value is None:
                    break
                result = outcome.value
                if result.get("status") not in finished:
                    sleep(max(0, min(0.15 - (monotonic() - polled), deadline - monotonic())))
            if str(result.get("status") or "done").lower() in {"done", "completed", "ok"}:
                text = result.get("text")
                if isinstance(text, str):
                    return text
                if isinstance(result.get("segments"), list):
                    return " ".join(str(row.get("text") or "") for row in result["segments"] if isinstance(row, dict))
            if job and result.get("status") not in finished:
                self.directory.tool(STT_APP, "transcribe_cancel", {"job_id": job}, timeout=0.5, trace=trace)
        return None

    @staticmethod
    def max_body(route):
        if route == "reply":
            return MAX_REPLY_JSON
        if route == "transcribe":
            return MAX_AUDIO
        if route == "understand":
            return MAX_AUDIO * 4 // 3 + MAX_JSON
        return MAX_JSON

    def handle(self, method, route, query, content_type, body):
        if method == "GET" and route == "capabilities":
            self.directory.prepare()
            app = self.directory.app(DICTATION_APP)
            reserve = self.directory.app(STT_APP)
            piper = self.directory.app(TTS_APP)
            tools = app.tools if app else set()
            ready = DICTATION_TOOLS <= tools
            phrases = _cache_phrases(_cache_root())
            tts = bool(phrases) and (VOICE_MODE == "cache-natural"
                                    or VOICE_MODE == "piper" and piper and "voice_tts" in piper.tools)
            return _json(200, stt=SPEECH_TOOL in tools or bool(reserve and "transcribe_file" in reserve.tools),
                         tts=bool(tts), dictation=ready, dictation_route="direct" if ready else "local",
                         dictation_name=self.dictation_name,
                         **({"adaptive_turn": True} if ready and END_TURN_TOOL in tools else {}),
                         **({"voice_phrases": phrases} if phrases else {}))
        trace = TurnTrace.header(query)
        if method == "POST" and route == "transcribe":
            return self._transcribe(query, content_type, body, trace)
        if method == "POST" and route == "understand":
            return self._understand(body, trace)
        if method == "POST" and route == "form-understand":
            return self._understand(body, trace, form=True)
        if method == "POST" and route == "end-turn":
            return self._end_turn(body, trace)
        if method == "POST" and route == "speak":
            return self._speak(body)
        if method == "POST" and route == "trace":
            return _json(202, queued=self.tracer.submit(body))
        if method == "DELETE" and route.startswith("reply/"):
            job_id = route.removeprefix("reply/")
            if job_id.startswith("request/"):
                request_id = job_id.removeprefix("request/")
                if JOB_ID.fullmatch(request_id):
                    self.replies.cancel_request(request_id)
                    return _json(200, ok=True)
            if JOB_ID.fullmatch(job_id):
                self.replies.cancel(job_id)
                return _json(200, ok=True)
        return _json(404, code="voice_route_not_found")

    def reply(self, body):
        if VOICE_MODE == "off":
            raise ReplyError("tts_disabled", 503)
        try:
            request = json.loads(body)
            text = request.get("text")
            language = request.get("language")
            engine = request.get("engine")
            request_id = request.get("request_id")
            if (request.get("version") != TTS_VERSION or not isinstance(text, str)
                    or not text.strip() or len(text) > 20_000 or language not in ("es", "en")
                    or (request_id is not None and (not isinstance(request_id, str) or not JOB_ID.fullmatch(request_id)))
                    or (engine is not None and (not isinstance(engine, str) or not ENGINE_ID.fullmatch(engine)))):
                raise ValueError
        except (AttributeError, ValueError):
            raise ReplyError("invalid_voice_request", 400) from None
        arguments = {"version": TTS_VERSION, "text": text, "lang": "es-ES" if language == "es" else "en",
                     "voice": "default", "speed": 1, "wait": False}
        if engine is not None:
            arguments["engine"] = engine
        trace = TurnTrace.context(request.get("trace_id"))
        return self.replies.stream(arguments, request_id, **({"trace": trace} if trace else {}))

    def _transcribe(self, query, content_type, body, trace):
        started = monotonic()
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
        adaptive = preview and parameters.get("adaptive", ["false"])[0] == "true"
        prompt = parameters.get("initial_prompt", [""])[0][:1000]
        if preview and not self.partial.acquire(blocking=False):
            return _json(429, code="partial_busy")
        try:
            window = 1 if preview else CYRANO_SPEECH_S
            call = self.directory.dictation(SPEECH_TOOL, {
                "audio": {"mime_type": content_type, "data_base64": base64.b64encode(body).decode("ascii")},
                "language": language, "initial_prompt": prompt,
                "vad": adaptive or not preview, "fallback": False, "timeout_s": window,
            }, timeout=window + 0.25, trace=trace)
            value = call.value or {}
            speech = value.get("trace")
            speech = speech if isinstance(speech, dict) else {}
            if isinstance(value.get("text"), str):
                return _json(200, text=value["text"], final=not preview,
                             provider=_cyrano_transcription_provider(value, self.dictation_name),
                             timing={"gateway_ms": (monotonic() - started) * 1000, "service_ms": call.ms},
                             **({"fallback_reason": speech["fallback_reason"]} if speech.get("fallback_reason") else {}))
            why = call.reason or "boltagon_contract_invalid"
            if adaptive:
                return _json(503, code="stt_unavailable", fallback_reason=why)
            budget = 2 if preview else FINAL_TRANSCRIPTION_S
            remaining = max(1, budget - (monotonic() - started))
            fallback_started = monotonic()
            transcript = self._fallback_transcription(body, suffix, language=language, prompt=prompt,
                                                     preview=preview, timeout=remaining, trace=trace)
            total = (monotonic() - started) * 1000
            if not isinstance(transcript, str):
                return _json(503, code="stt_unavailable", fallback_reason=why)
            return _json(200, text=transcript, final=not preview, provider=FAMILY_TRANSCRIPTION, fallback_reason=why,
                         timing={"gateway_ms": total, "service_ms": (monotonic() - fallback_started) * 1000,
                                 "primary_ms": call.ms})
        finally:
            if preview:
                self.partial.release()

    def _end_turn(self, body, trace):
        if not body or len(body) > MAX_JSON:
            return _json(400, code="invalid_end_turn")
        try:
            request = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return _json(400, code="invalid_end_turn")
        if (not isinstance(request, dict) or request.get("version") != DICTATION_VERSION
                or request.get("dialogue") not in ("open", "slots", "confirm")
                or not isinstance(request.get("text"), str) or not 0 < len(request["text"].strip()) <= 1000):
            return _json(400, code="invalid_end_turn")
        options = {name: request[name] for name in
                   ("version", "language", "vocabulary", "schema", "context", "dialogue", "text") if name in request}
        call = self.directory.dictation(END_TURN_TOOL, options, timeout=0.75, trace=trace)
        value = call.value
        if not isinstance(value, dict) or value.get("decision") not in ("short", "long"):
            return _json(503, code=call.reason or "boltagon_contract_invalid")
        interpretation = value.get("interpretation")
        if isinstance(interpretation, dict):
            value = {**value, "interpretation": {**interpretation, "dictation_route": "direct",
                                                 "dictation_name": self.dictation_name}}
        return _json(200, **value, service_ms=call.ms)

    def _understand(self, body, trace, *, form=False):
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
        if form and audio is not None:
            return _json(400, code="invalid_dictation")
        if text is not None:
            if not isinstance(text, str) or not 0 < len(text.strip()) <= 1000:
                return _json(400, code="invalid_dictation")
        if audio is not None:
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
            prompt = options.get("vocabulary")
            prompt = ", ".join(term for term in prompt if isinstance(term, str))[:1000] if isinstance(prompt, list) else ""
            query = urlencode({"language": language[:2], "initial_prompt": prompt})
            transcription = self._transcribe(query, audio["mime_type"], raw, trace)
            if transcription[0] != 200:
                return transcription
            text = json.loads(transcription[1])["text"]
            if not text.strip():
                return _json(422, code="dictation_empty")
        call = self.directory.dictation("dictation_understand", {**options, "text": text}, timeout=1.2, trace=trace)
        value = call.value
        if not isinstance(value, dict) or value.get("version") != DICTATION_VERSION:
            return _json(503, code=call.reason or "boltagon_contract_invalid", service_ms=call.ms)
        if form and value.get("is_final") is True:
            value = extract_missing(self.form_chat, value, options, text, call.ms,
                                    correction=request.get("correction") is True)
        return _json(200, **{**value, "dictation_route": "direct", "dictation_name": self.dictation_name},
                     service_ms=call.ms)

    def _speak(self, body):
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
        call = self.directory.tool(TTS_APP, "voice_tts", {
            "text": text, "lang": language, "voice": SPANISH_TTS_VOICE, "engine": "piper",
        }, timeout=12)
        result = call.value or {}
        path = result.get("path")
        if not isinstance(path, str):
            if "generation is off" in json.dumps(result, ensure_ascii=False).lower():
                return _json(409, code="tts_disabled")
            return _json(503, code="tts_unavailable")
        try:
            audio = Path(path).read_bytes()
        except OSError:
            return _json(503, code="tts_unavailable")
        return 200, audio, "audio/wav"
