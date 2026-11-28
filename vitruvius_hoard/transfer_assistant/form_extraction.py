"""Ground proposed model values in the current form and its utterance."""

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


MODEL_TIMEOUT_S = 3.0
MODEL_MAX_TOKENS = 96
_FORMATS = FormatChecker()
_REGISTRY = Registry()
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


def extract_missing(call, value, options, text, rules_ms, *, correction=False):
    """Extend a valid rules result. A proposal is advisory until it passes schema and evidence checks."""
    steps = [{"method": "rules", "ms": rules_ms}]
    base = {**value, "understanding_steps": steps}
    schema = options.get("schema", {})
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    required = schema.get("required", []) if isinstance(schema, dict) else []
    if not isinstance(properties, dict) or not isinstance(required, list) or not re.search(r"\w", text):
        return base
    context = options.get("context")
    context = context if isinstance(context, dict) else {}
    draft = context.get("draft")
    draft = draft if isinstance(draft, dict) else {}
    rules_fields = value.get("fields")
    fields = dict(rules_fields) if isinstance(rules_fields, dict) else {}
    targets = {}
    for key in required:
        spec = properties.get(key) if isinstance(key, str) else None
        rule = fields.get(key) if isinstance(key, str) else None
        if not isinstance(spec, dict) or isinstance(rule, dict) and rule.get("validation") == "valid":
            continue
        if key not in draft or draft[key] in (None, "") or correction and context.get("field") == key:
            targets[key] = spec
    if not targets:
        return base

    start = monotonic()
    model_step = {"method": "model", "ms": 0, "outcome": "unavailable"}
    steps.append(model_step)
    if call is None:
        return base

    requested = {}
    for key, spec in targets.items():
        field = {k: spec[k] for k in ("type", "title", "format", "enum") if k in spec}
        if isinstance(spec.get("enum"), list):
            labels = {str(choice): found[0] for choice in spec["enum"]
                      if (found := _labels(context, key, choice)) and found[0] != str(choice)}
            if labels:
                field["option_labels"] = labels
        requested[key] = field
    messages = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": json.dumps({
        "fields": requested, "context_field": context.get("field"), "utterance": text,
    }, ensure_ascii=False, separators=(",", ":"))}]
    try:
        response = call(messages, timeout=MODEL_TIMEOUT_S, max_tokens=MODEL_MAX_TOKENS)
        proposal = json.loads(response.text)
        if not isinstance(proposal, dict):
            return base
        model_step["outcome"] = "no_match"
        model_step["model"] = response.model
    except (TimeoutError, httpx.TimeoutException):
        model_step["outcome"] = "timeout"
        return base
    except (ValueError, TypeError, AttributeError, OSError, httpx.HTTPError, HoardLinkError):
        return base
    finally:
        model_step["ms"] = (monotonic() - start) * 1000

    ambiguities = [row for row in (value.get("ambiguous") or []) if isinstance(row, dict)]
    changed = list(value.get("changed") or [])
    for key, spec in targets.items():
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
    return {**base, "fields": fields, "missing": missing, "ambiguous": ambiguities, "changed": changed}
