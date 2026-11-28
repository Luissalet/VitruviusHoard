"""Ground proposed model values in the current form and its utterance."""

from concurrent.futures import CancelledError, FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import json
import math
import re
from time import monotonic
from unicodedata import normalize

import httpx
from hoard_link.errors import HoardLinkError
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry
from referencing.exceptions import Unresolvable

from .voice_directory import VoiceCall


MODEL_TIMEOUT_S = 3.0
MODEL_MAX_TOKENS = 96
_FORMATS = FormatChecker()
_REGISTRY = Registry()
_RULES = ThreadPoolExecutor(max_workers=8, thread_name_prefix="form-dictation")
_HOURS = (
    "cero zero", "una uno one", "dos two", "tres three", "cuatro four", "cinco five", "seis six",
    "siete seven", "ocho eight", "nueve nine", "diez ten", "once eleven", "doce twelve",
)
_SYSTEM = (
    "Extract ONLY requested form fields from the utterance. Return a compact JSON object keyed by field id. "
    "Omit unrelated, unsupported or unspecified values. Copy free text literally, without the field label. "
    "For choices output the exact value, not its label. Choose one only if the utterance singles it out. "
    "If it fits several choices (e.g. morning with 10:00 and 12:00), return those values as an array. "
    "A day or a broad time is not an exact hour. Never invent names or choices. No explanation."
)


def _fold(text):
    return "".join(c for c in normalize("NFKD", text.casefold()) if not 0x300 <= ord(c) <= 0x36f)


def _literal(text, value):
    if not value:
        return None
    # Fold each character separately so Unicode expansions still point at the original words.
    indices = [index for index, char in enumerate(text) for _ in _fold(char)]
    match = re.search(r"(?<!\w)" + re.escape(_fold(value)) + r"(?!\w)", _fold(text))
    if match and match.start() < match.end() <= len(indices):
        return text[indices[match.start()]:indices[match.end() - 1] + 1]
    return None


def _valid(value, spec):
    if type(value) not in (str, int, float, bool) or isinstance(value, str) and not value.strip():
        return False
    if type(value) is float and not math.isfinite(value):
        return False
    try:
        return Draft202012Validator(spec, registry=_REGISTRY, format_checker=_FORMATS).is_valid(value)
    except (Unresolvable, ValueError):
        return False


def _quote(text, value, labels):
    if type(value) is bool:
        words = ("si", "yes", "true") if value else ("no", "false")
        return text.strip() if _fold(text).strip(" .!?") in words else None
    text_value = str(value)
    if type(value) is str and re.fullmatch(r"\d{2}:\d{2}", value):
        exact = re.search(r"(?<!\d)" + re.escape(value) + r"(?![\d:])", text)
        if exact:
            return exact[0]
        hour, minute = map(int, value.split(":"))
        if minute == 0:
            words = [str(hour), *(_HOURS[hour].split() if hour < len(_HOURS) else ())]
            hour_pattern = r"(?:" + "|".join(words) + r")"
            folded = _fold(text.strip())
            if re.fullmatch(hour_pattern + r"[.!?]?", folded):
                return text.strip().rstrip(".!?")
            match = re.search(r"\b(?:a las? |at )" + hour_pattern + r"\b(?!\s+(?:y|and|\d)\b|[:.,]\d)", folded)
            if match:
                return _literal(text, match[0])
        # Requiring the full hour also rejects a partial match in an unlisted clock time.
        return None
    return _literal(text, text_value) or next((span for label in labels
                                                if (span := _literal(text, label))), None)


def _labels(context, key, value):
    field = context.get("option_labels", {}).get(key, {}) if isinstance(context.get("option_labels"), dict) else {}
    label = field.get(str(value)) if isinstance(field, dict) else None
    return [label] if isinstance(label, str) and label.strip() else []


def _scope(options, text, correction):
    schema = options.get("schema", {})
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    required = schema.get("required", []) if isinstance(schema, dict) else []
    required = [key for key in required if isinstance(key, str)] if isinstance(required, list) else []
    context = options.get("context")
    context = context if isinstance(context, dict) else {}
    draft = context.get("draft")
    draft = draft if isinstance(draft, dict) else {}
    targets = {}
    if not isinstance(properties, dict) or not re.search(r"\w", text):
        return required, context, draft, targets
    for key in required:
        spec = properties.get(key)
        if isinstance(spec, dict) and (draft.get(key) in (None, "") or correction and context.get("field") == key):
            targets[key] = spec
    return required, context, draft, targets


def _messages(targets, context, text):
    requested = {}
    for key, spec in targets.items():
        field = {k: spec[k] for k in ("type", "title", "format", "enum") if k in spec}
        if isinstance(spec.get("enum"), list):
            labels = {str(choice): found[0] for choice in spec["enum"]
                      if (found := _labels(context, key, choice)) and found[0] != str(choice)}
            if labels:
                field["option_labels"] = labels
        requested[key] = field
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": json.dumps({
        "fields": requested, "context_field": context.get("field"), "utterance": text,
    }, ensure_ascii=False, separators=(",", ":"))}]


def _result(model, step):
    try:
        response = model.result()
        proposal = json.loads(response.text)
        if isinstance(proposal, dict):
            step.update(outcome="no_match", model=response.model)
            return proposal
    except (TimeoutError, httpx.TimeoutException):
        step["outcome"] = "timeout"
    except (CancelledError, ValueError, TypeError, AttributeError, OSError, RuntimeError, httpx.HTTPError, HoardLinkError):
        pass
    return {}


def _valid_rule(fields, key, spec):
    field = fields.get(key)
    return (isinstance(field, dict) and field.get("validation") == "valid"
            and _valid(field.get("value"), spec) and bool(field.get("quote")))


def _complete(value, targets):
    fields = value.get("fields")
    return isinstance(fields, dict) and all(_valid_rule(fields, key, spec) for key, spec in targets.items())


def _apply(value, proposal, targets, required, context, draft, text, model_step):
    rules_fields = value.get("fields")
    fields = dict(rules_fields) if isinstance(rules_fields, dict) else {}
    ambiguities = [row for row in (value.get("ambiguous") or []) if isinstance(row, dict)]
    changed = list(value.get("changed") or [])
    for key, spec in targets.items():
        if _valid_rule(fields, key, spec):
            continue
        proposed = proposal.get(key)
        candidates = spec.get("enum")
        if isinstance(candidates, list) and (isinstance(proposed, list) or key in proposal and not _valid(proposed, spec)):
            allowed = [choice for choice in candidates if _valid(choice, spec)]
            choices = [choice for choice in allowed if isinstance(proposed, list) and choice in proposed]
            if not any(row.get("field") == key for row in ambiguities):
                ambiguities.append({"field": key, "candidates": choices or allowed})
            continue
        if not _valid(proposed, spec):
            continue
        quote = _quote(text, proposed, _labels(context, key, proposed))
        if quote and isinstance(candidates, list):
            mentioned = [choice for choice in candidates if _valid(choice, spec)
                         and _quote(text, choice, _labels(context, key, choice))]
            if len(mentioned) > 1:
                if not any(row.get("field") == key for row in ambiguities):
                    ambiguities.append({"field": key, "candidates": mentioned})
                continue
        if quote:
            fields[key] = {"value": proposed, "quote": quote, "validation": "valid"}
            ambiguities = [row for row in ambiguities if row.get("field") != key]
            if key not in changed:
                changed.append(key)
            model_step["outcome"] = "applied"
    missing = [key for key in required if isinstance(key, str) and key not in fields and draft.get(key) in (None, "")]
    return {**value, "fields": fields, "missing": missing, "ambiguous": ambiguities, "changed": changed}


def understand_form(submit, rules_call, options, text, *, correction=False):
    """Let a complete result finish the turn. Merge partial results without replacing validated rules."""
    required, context, draft, targets = _scope(options, text, correction)
    empty = {"version": options["version"], "is_final": True, "raw_transcript": text,
             "text_clean": text, "fields": {}, "missing": required}
    model_step = {"method": "model", "ms": 0, "outcome": "unavailable"}

    def wire(value, rules_step, model_tried):
        steps = [rules_step, model_step] if model_tried else [rules_step]
        return VoiceCall({**value, "understanding_steps": steps}, ms=rules_step["ms"])

    if not targets or submit is None:
        result = rules_call()
        if not result.value or result.value.get("is_final") is not True:
            return result
        return wire(result.value, {"method": "rules", "ms": result.ms}, bool(targets))

    start = monotonic()
    deadline = start + MODEL_TIMEOUT_S
    rules = _RULES.submit(rules_call)
    try:
        model = submit(_messages(targets, context, text), timeout=MODEL_TIMEOUT_S, max_tokens=MODEL_MAX_TOKENS)
    except (ValueError, OSError, RuntimeError, httpx.HTTPError, HoardLinkError) as error:
        model = Future()
        model.set_exception(error)
    finished = {}
    model.add_done_callback(lambda _: finished.setdefault("model", monotonic()))
    waiting = {rules, model}
    rule_result = None
    rule_step = {"method": "rules", "ms": 0, "outcome": "superseded"}
    proposal = {}
    value = empty
    try:
        while waiting:
            done, waiting = wait(waiting, timeout=max(0.0, deadline - monotonic()), return_when=FIRST_COMPLETED)
            if not done:
                break
            if rules in done:
                rule_result = rules.result()
                rule_step = {"method": "rules", "ms": rule_result.ms}
                if rule_result.value and rule_result.value.get("is_final") is True:
                    value = rule_result.value
                    if _complete(value, targets):
                        model_step.update(outcome="superseded", ms=(finished.get("model", monotonic()) - start) * 1000)
                        return wire(value, rule_step, True)
                else:
                    rule_step["outcome"] = "unavailable"
            if model in done:
                model_step["ms"] = (finished.get("model", monotonic()) - start) * 1000
                proposal = _result(model, model_step)
            if proposal and rule_result is None:
                early = _apply(empty, proposal, targets, required, context, draft, text, model_step)
                if _complete(early, targets):
                    rule_step["ms"] = (monotonic() - start) * 1000
                    return wire(early, rule_step, True)
        if rules in waiting:
            rule_step.update(outcome="timeout", ms=(monotonic() - start) * 1000)
        if model in waiting:
            model_step.update(outcome="timeout", ms=(monotonic() - start) * 1000)
        if value is empty and not proposal:
            return rule_result or VoiceCall(reason="boltagon_timeout", ms=rule_step["ms"])
        if model_step["outcome"] == "applied":
            model_step["outcome"] = "no_match"
        value = _apply(value, proposal, targets, required, context, draft, text, model_step)
        return wire(value, rule_step, True)
    finally:
        rules.cancel()
        model.cancel()
