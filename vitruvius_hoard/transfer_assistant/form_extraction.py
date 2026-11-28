"""Ground proposed model values in the current form and its utterance."""

from concurrent.futures import CancelledError, FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import json
import math
import re
from time import monotonic

import httpx
from hoard_link.errors import HoardLinkError
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry
from referencing.exceptions import Unresolvable

from .voice_directory import VoiceCall
from .form_rules import HOURS, fold as _fold, form_rejections, form_rules, name_candidate, person_field


MODEL_TIMEOUT_S = 3.0
MODEL_MAX_TOKENS = 96
_FORMATS = FormatChecker()
_REGISTRY = Registry()
_RULES = ThreadPoolExecutor(max_workers=8, thread_name_prefix="form-dictation")
_SYSTEM = (
    "Extract ONLY requested form fields from the utterance. Return a compact JSON object keyed by field id. "
    "Omit unrelated, unsupported or unspecified values. Copy free text literally, without the field label. "
    "For choices output the exact value, not its label. Choose one only if the utterance singles it out. "
    "Never return a rejected value or a pronoun in place of a person's name. "
    "If it fits several choices (e.g. morning with 10:00 and 12:00), return those values as an array. "
    "A day or a broad time is not an exact hour. Never invent names or choices. No explanation."
)


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
            words = [str(hour), *(HOURS[hour].split() if hour < len(HOURS) else ())]
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
    properties = properties if isinstance(properties, dict) else {}
    required = schema.get("required", []) if isinstance(schema, dict) else []
    required = [key for key in required if isinstance(key, str)] if isinstance(required, list) else []
    context = options.get("context")
    context = context if isinstance(context, dict) else {}
    draft = context.get("draft")
    draft = draft if isinstance(draft, dict) else {}
    targets = {}
    if not re.search(r"\w", text):
        return required, context, draft, targets, properties
    for key in required:
        spec = properties.get(key)
        if isinstance(spec, dict) and (draft.get(key) in (None, "") or correction and context.get("field") == key):
            targets[key] = spec
    return required, context, draft, targets, properties


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


def _rejected_options(properties, context, declined):
    previous = context.get("rejected_options")
    previous = previous if isinstance(previous, dict) else {}
    excluded = {}
    for key in previous.keys() | declined.keys():
        spec = properties.get(key)
        choices = spec.get("enum") if isinstance(spec, dict) else None
        if not isinstance(choices, list):
            continue
        saved = previous.get(key)
        denied = (saved if isinstance(saved, list) else []) + declined.get(key, [])
        values = [choice for choice in choices if choice in denied and _valid(choice, spec)]
        if values:
            excluded[key] = values
    return excluded


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
        if not _valid(proposed, spec) or person_field(key, spec) and not name_candidate(proposed):
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
    required, context, draft, targets, properties = _scope(options, text, correction)
    empty = {"version": options["version"], "is_final": True, "raw_transcript": text,
             "text_clean": text, "fields": {}, "missing": required}
    model_step = {"method": "model", "ms": 0, "outcome": "unavailable"}

    def wire(value, rules_step, model_tried):
        steps = [rules_step, model_step] if model_tried else [rules_step]
        if rejected_options:
            value = {**value, "ambiguous": [
                {**row, "candidates": [choice for choice in row["candidates"]
                                       if choice not in rejected_options.get(row.get("field"), ())]}
                if isinstance(row.get("candidates"), list) else row
                for row in value.get("ambiguous", [])
            ]}
        return VoiceCall({**value, "cleared": cleared, "rejected_options": rejected_options,
                          "understanding_steps": steps}, ms=rules_step["ms"])

    started_local = monotonic()
    rejected, cleared, declined, rejection_only = form_rejections(text, properties, targets, context, draft)
    rejected_options = _rejected_options(properties, context, declined)
    for key, denied in rejected_options.items():
        if key not in targets or key in rejected:
            continue
        choices = [choice for choice in targets[key]["enum"] if choice not in denied]
        if choices:
            targets[key] = {**targets[key], "enum": choices}
        else:
            rejected[key] = []
    targets = {key: spec for key, spec in targets.items() if key not in rejected}
    draft = {key: value for key, value in draft.items() if key not in cleared}
    proposal, exclusive, alternatives = form_rules(text, targets, context, correction)
    alternatives.update({key: choices for key, choices in rejected.items() if choices is not None})
    if proposal or alternatives or rejected:
        seeded = {**empty, "ambiguous": [
            {"field": key, "candidates": [option for option in choices if option not in rejected_options.get(key, ())
                                           and _valid(option, properties[key])]}
            for key, choices in alternatives.items()
        ]}
        local = _apply(seeded, proposal, targets, required, context, draft, text, {})
        settled = set(rejected) | set(local["fields"]) | {item["field"] for item in local["ambiguous"]}
    else:
        local, settled = empty, set()
    local_ms = (monotonic() - started_local) * 1000
    if rejection_only or settled and (exclusive or settled >= targets.keys()):
        if not settled:
            local = _apply(local, {}, targets, required, context, draft, text, {})
        return wire(local, {"method": "rules", "ms": local_ms}, False)
    targets = {key: spec for key, spec in targets.items() if key not in settled}
    people = {key for key, spec in properties.items() if isinstance(spec, dict) and person_field(key, spec)}

    def merge_rules(remote):
        remote_fields = remote.get("fields")
        remote_fields = remote_fields if isinstance(remote_fields, dict) else {}
        discarded = settled | {key for key in people & remote_fields.keys()
                               if not isinstance(remote_fields[key], dict)
                               or not name_candidate(remote_fields[key].get("value"))}
        discarded.update(key for key in rejected_options.keys() & remote_fields.keys()
                         if isinstance(remote_fields[key], dict)
                         and remote_fields[key].get("value") in rejected_options[key])
        fields = {key: field for key, field in remote_fields.items() if key not in discarded}
        fields.update(local["fields"])
        ambiguous = [item for item in (remote.get("ambiguous") or [])
                     if isinstance(item, dict) and item.get("field") not in settled]
        ambiguous.extend(local.get("ambiguous", []))
        changed = [key for key in (remote.get("changed") or []) if key not in discarded]
        return {**remote, "fields": fields, "ambiguous": ambiguous,
                "changed": list(dict.fromkeys([*changed, *local.get("changed", [])]))}

    if not targets or submit is None:
        result = rules_call()
        if not result.value or result.value.get("is_final") is not True:
            return wire(local, {"method": "rules", "ms": local_ms}, bool(targets)) if settled else result
        value = _apply(merge_rules(result.value), {}, targets, required, context, draft, text, {})
        return wire(value, {"method": "rules", "ms": local_ms + result.ms}, bool(targets))

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
    value = local
    try:
        while waiting:
            done, waiting = wait(waiting, timeout=max(0.0, deadline - monotonic()), return_when=FIRST_COMPLETED)
            if not done:
                break
            if rules in done:
                rule_result = rules.result()
                rule_step = {"method": "rules", "ms": local_ms + rule_result.ms}
                if rule_result.value and rule_result.value.get("is_final") is True:
                    value = merge_rules(rule_result.value)
                    if _complete(value, targets):
                        model_step.update(outcome="superseded", ms=(finished.get("model", monotonic()) - start) * 1000)
                        return wire(_apply(value, {}, targets, required, context, draft, text, {}), rule_step, True)
                else:
                    rule_step["outcome"] = "unavailable"
            if model in done:
                model_step["ms"] = (finished.get("model", monotonic()) - start) * 1000
                proposal = _result(model, model_step)
            if proposal and rule_result is None:
                early = _apply(local, proposal, targets, required, context, draft, text, model_step)
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
