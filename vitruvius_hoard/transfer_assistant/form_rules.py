"""Recognise explicit names and clock choices without depending on a remote model."""

import re
from unicodedata import combining, normalize


HOURS = (
    "cero zero", "una uno one", "dos two", "tres three", "cuatro four", "cinco five", "seis six",
    "siete seven", "ocho eight", "nueve nine", "diez ten", "once eleven", "doce twelve",
)
_HOUR_WORDS = {word: hour for hour, words in enumerate(HOURS) for word in words.split()}
_NAME_KEYS = {"persona", "nombre", "name", "full name", "first name", "nombre completo", "attendee", "guest"}
_PERSON_TITLES = re.compile(r"\b(?:persona|visitante|asistente|participante|person|visitor|attendee|guest)\b")
_DAYS = "lunes martes miercoles jueves viernes sabado domingo monday tuesday wednesday thursday friday saturday sunday"
_NOT_NAMES = {*_DAYS.split(), *_HOUR_WORDS, "hola", "hello", "hi", "si", "no", "ok", "vale", "hoy", "manana",
              "today", "tomorrow", "a", "al", "el", "la", "las", "los", "un", "una", "por", "para", "de", "del",
              "gracias", "thanks", "bien", "perfecto", "perfect", "confirmo", "confirmar", "cancelar", "cancela",
              "apunta", "reserva", "enciende"}
_WORD = r"[^\W\d_]+(?:[-'’][^\W\d_]+)*"
_NOMINATION = re.compile(r"(?:\b(?:apunta|apuntar|reserva|reservar|anota|inscribe)\s+a\s+|^\s*a\s+)", re.I)
_CLOCK = re.compile(r"\b(?:a las?\s+|at\s+)(\d{1,2}|[^\W\d_]+)(?::(\d{2}))?\b(?![:\d]|\s+(?:y|and)\b)")
_CLOCK_VALUE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


def fold(text):
    return "".join(c for c in normalize("NFKD", text.casefold()) if not combining(c))


def _person_name(text):
    start = _NOMINATION.search(text)
    tail = text[start.end():] if start else text.strip().rstrip(".!?")
    match = re.match(_WORD + r"(?:\s+" + _WORD + r"){0,3}", tail)
    if not match:
        return None
    first = re.match(_WORD, tail)[0]
    if not first[0].isupper() or fold(first) in _NOT_NAMES:
        return None
    if start:
        length = len(first)
        for word in re.finditer(_WORD, match[0][length:]):
            if not word[0][0].isupper() or fold(word[0]) in _NOT_NAMES:
                break
            # Word offsets are relative to the remainder immediately after the first word.
            length = len(first) + word.end()
        alternative = re.match(r"\s+(?:y|and|o|or)\s+(" + _WORD + r")", tail[length:])
        if alternative and alternative[1][0].isupper() and fold(alternative[1]) not in _NOT_NAMES:
            return None
        return tail[:length], False
    if first == tail:
        return first, True
    return None


def _clock_choices(text, options, *, correction=False):
    matched = list(_CLOCK.finditer(text))
    bare = text.strip(" .!?")
    if not matched:
        standalone = re.fullmatch(r"(\d{1,2}|[^\W\d_]+)(?::(\d{2}))?", bare)
        if standalone:
            matched = [standalone]
    clocks = set()
    for match in matched:
        word, minute = match.groups()
        hour = int(word) if word.isascii() and word.isdigit() else _HOUR_WORDS.get(word)
        if hour is not None and 0 <= hour < 24:
            clocks.add(f"{hour:02d}:{minute or '00'}")
    if clocks:
        choices = [option for option in options if option in clocks]
        exact = len(clocks) == len(choices) == 1
        exclusive = len(matched) == 1 and matched[0][0] == bare
        return (choices[0] if exact else choices or options), exclusive

    for pattern, start, end in (
        (r"\b(?:por la manana|in the morning)\b", "05:00", "12:00"),
        (r"\b(?:por la tarde|in the afternoon)\b", "12:00", "19:00"),
    ):
        if re.search(pattern, text):
            return [option for option in options if start <= option <= end] or options, False
    if correction and re.search(r"\b(?:" + "|".join(_DAYS.split()) + r")\b", text):
        return options, True
    return None, False


def form_rules(text, targets, context, correction):
    proposal = {}
    name_fields = []
    for key, spec in targets.items():
        title = fold(str(spec.get("title", "")))
        key_words = fold(key.replace("_", " "))
        person_title = re.search(r"\b(?:nombre|name)\b", title) and _PERSON_TITLES.search(title)
        if (spec.get("type") == "string" and not spec.get("enum")
                and (person_title or key_words in _NAME_KEYS and (not title or title in _NAME_KEYS))):
            name_fields.append(key)
    name = _person_name(text) if len(name_fields) == 1 else None
    exclusive = False
    if name:
        proposal[name_fields[0]], exclusive = name
    clock_fields = {key: spec["enum"] for key, spec in targets.items() if isinstance(spec.get("enum"), list)
                    and spec["enum"] and all(isinstance(value, str) and _CLOCK_VALUE.fullmatch(value) for value in spec["enum"])}
    target = context.get("field")
    if not isinstance(target, str) or target not in clock_fields:
        target = next(iter(clock_fields)) if len(clock_fields) == 1 else None
    if target in clock_fields:
        choice, only_clock = _clock_choices(fold(text).strip(" .!?"), clock_fields[target], correction=correction)
        if choice is not None:
            proposal[target] = choice
            exclusive = exclusive or only_clock
    return proposal, exclusive
