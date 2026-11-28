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
              "nadie", "alguien", "ninguno", "ninguna", "cualquiera", "todos", "todas", "todo", "nada",
              "yo", "tu", "usted", "ella", "ellos", "ellas", "nosotros", "nosotras", "vosotros", "vosotras", "ustedes",
              "nobody", "noone", "someone", "somebody", "anyone", "anybody", "everyone", "everybody",
              "none", "nothing", "i", "me", "you", "he", "she", "we", "they", "yes", "okay",
              "apunta", "reserva", "enciende"}
_WORD = r"[^\W\d_]+(?:[-'’][^\W\d_]+)*"
_NOMINATION = re.compile(r"(?:\b(?:apunta|apuntar|reserva|reservar|anota|inscribe)\s+a\s+|^\s*a\s+)", re.I)
_CLOCK = re.compile(r"\b(?:(?:a las?\s+|at\s+)|(?=\d{1,2}:))"
                    r"(\d{1,2}|[^\W\d_]+)(?::(\d{2}))?\b(?![:\d]|\s+(?:y|and)\b)")
_CLOCK_VALUE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
_REJECT_BEFORE = re.compile(r"\b(?:no(?:\s+(?:sea|sean|quiero|puede|puedo|pongas|ponga))?|"
                            r"tampoco|ni|not|neither|nor|except(?: for)?)\s*$")
_REJECT_AFTER = re.compile(r"^\s*,?\s+(?:no|not)\b(?=\s*(?:$|[,.;!?]|\b(?:pero|but|gracias|thanks)\b))")
_NEGATION = re.compile(r"\b(?:no|tampoco|not|neither|ni|nor|except)\b")
_REJECT_LAST = re.compile(r"(?:(?:no[,\s]+)?(?:ese|esa|eso|este|esta|esto)\s+(?:no|tampoco)|"
                          r"(?:no[,\s]+)?not that(?: one)?)")


def fold(text):
    return "".join(c for c in normalize("NFKD", text.casefold()) if not combining(c))


def person_field(key, spec):
    if spec.get("type") != "string" or spec.get("enum"):
        return False
    title = fold(str(spec.get("title", "")))
    key_words = fold(key.replace("_", " "))
    return (key_words in _NAME_KEYS and (not title or title in _NAME_KEYS)
            or bool(re.search(r"\b(?:nombre|name)\b", title) and _PERSON_TITLES.search(title)))


def name_candidate(value):
    if not isinstance(value, str):
        return False
    first = re.search(_WORD, value)
    return bool(first and fold(first[0]) not in _NOT_NAMES)


def _person_name(text):
    start = _NOMINATION.search(text)
    tail = text[start.end():] if start else text.strip().rstrip(".!?")
    match = re.match(_WORD + r"(?:\s+" + _WORD + r"){0,3}", tail)
    if not match:
        return None
    first = re.match(_WORD, tail)[0]
    if not first[0].isupper() or not name_candidate(first):
        return None
    if start:
        length = len(first)
        for word in re.finditer(_WORD, match[0][length:]):
            if not word[0][0].isupper() or not name_candidate(word[0]):
                break
            # Word offsets are relative to the remainder immediately after the first word.
            length = len(first) + word.end()
        alternative = re.match(r"\s+(?:y|and|o|or)\s+(" + _WORD + r")", tail[length:])
        if alternative and alternative[1][0].isupper() and name_candidate(alternative[1]):
            return None
        return tail[:length], False
    if first == tail:
        return first, True
    return None


def _rejects(text, match):
    return _REJECT_BEFORE.search(text[:match.start()]) or _REJECT_AFTER.match(text[match.end():])


def _rejects_value(text, value):
    literal = re.escape(fold(str(value))).replace(r"\ ", r"\s+")
    return bool(literal and any(_rejects(text, match) for match in re.finditer(r"(?<!\w)" + literal + r"(?!\w)", text)))


def _clock_mentions(text):
    matched = list(_CLOCK.finditer(text))
    bare = text.strip(" .!?")
    if not matched:
        standalone = re.fullmatch(r"(\d{1,2}|[^\W\d_]+)(?::(\d{2}))?", bare)
        if standalone:
            matched = [standalone]
    clocks, rejected = set(), set()
    for match in matched:
        word, minute = match.groups()
        hour = int(word) if word.isascii() and word.isdigit() else _HOUR_WORDS.get(word)
        if hour is not None and 0 <= hour < 24:
            value = f"{hour:02d}:{minute or '00'}"
            if _rejects(text, match):
                rejected.add(value)
            else:
                clocks.add(value)
    exclusive = len(matched) == 1 and matched[0][0] == bare
    return clocks, rejected, exclusive


def _clock_choices(text, options, *, correction=False):
    clocks, rejected, exclusive = _clock_mentions(text)
    if rejected:
        return None, True, rejected
    if clocks:
        choices = [option for option in options if option in clocks]
        exact = len(clocks) == len(choices) == 1
        return (choices[0] if exact else choices or options), exclusive, rejected

    for pattern, start, end in (
        (r"\b(?:por la manana|in the morning)\b", "05:00", "12:00"),
        (r"\b(?:por la tarde|in the afternoon)\b", "12:00", "19:00"),
    ):
        if re.search(pattern, text):
            return [option for option in options if start <= option <= end] or options, False, rejected
    if correction and re.search(r"\b(?:" + "|".join(_DAYS.split()) + r")\b", text):
        return options, True, rejected
    return None, False, rejected


def form_rejections(text, properties, targets, context, draft):
    folded = fold(text).strip(" .!?")
    if not _NEGATION.search(folded):
        return {}, {}, {}, False
    if _REJECT_LAST.fullmatch(folded):
        key = context.get("last_changed")
        spec = properties.get(key) if isinstance(key, str) else None
        current = draft.get(key) if isinstance(key, str) else None
        if (not isinstance(spec, dict) or spec.get("type") not in ("string", "number", "integer")
                or type(current) not in (str, int, float) or current == ""):
            return {}, {}, {}, True
        choices = spec.get("enum")
        if isinstance(choices, list):
            return {key: [value for value in choices if value != current]}, {key: current}, {key: [current]}, True
        return {key: None}, {key: current}, {}, True
    _, rejected_hours, _ = _clock_mentions(folded)
    labels = context.get("option_labels")
    labels = labels if isinstance(labels, dict) else {}
    rejected, cleared, declined_options = {}, {}, {}
    for key, spec in properties.items():
        if not isinstance(spec, dict) or spec.get("type") not in ("string", "number", "integer"):
            continue
        current = draft.get(key)
        choices = spec.get("enum")
        if isinstance(choices, list) and (key in targets or current not in (None, "")):
            names = labels.get(key)
            names = names if isinstance(names, dict) else {}
            declined = [value for value in choices if type(value) in (str, int, float) and (
                str(value) in rejected_hours or _rejects_value(folded, value)
                or isinstance(names.get(str(value)), str) and _rejects_value(folded, names[str(value)]))]
            if declined:
                declined_options[key] = declined
                is_current = current in declined
                needs_choice = is_current or current in (None, "")
                rejected[key] = [value for value in choices if value not in declined] if needs_choice else None
                if is_current:
                    cleared[key] = current
        elif type(current) in (str, int, float) and _rejects_value(folded, current):
            rejected[key] = None
            cleared[key] = current

    # A short rejection of a name also makes sense when that field is empty.
    phrase = text.strip(" .!?")
    literal_name = re.sub(r"^(?:no|not)\s+|[,\s]+(?:no|not)$", "", phrase, flags=re.I)
    if literal_name != phrase:
        literal_name = re.sub(r"^no,\s*", "", literal_name, flags=re.I)
    name_only = (literal_name != phrase and re.fullmatch(_WORD + r"(?:\s+" + _WORD + r"){0,3}", literal_name)
                 and name_candidate(literal_name)
                 and (literal_name[0].isupper() or any(fold(str(value)) == fold(literal_name)
                                                       for value in cleared.values())))
    if name_only and not rejected:
        people = [key for key, spec in targets.items() if person_field(key, spec)]
        if len(people) == 1:
            rejected[people[0]] = None
    return rejected, cleared, declined_options, bool(name_only)


def form_rules(text, targets, context, correction):
    proposal = {}
    name_fields = [key for key, spec in targets.items() if person_field(key, spec)]
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
        choice, only_clock, rejected = _clock_choices(fold(text).strip(" .!?"), clock_fields[target], correction=correction)
        if rejected:
            return proposal, exclusive, {target: [option for option in clock_fields[target] if option not in rejected]}
        if choice is not None:
            proposal[target] = choice
            exclusive = exclusive or only_clock
    return proposal, exclusive, {}
