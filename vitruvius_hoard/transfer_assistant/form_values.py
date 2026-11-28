"""Ground spoken dates, headcounts and group names in the current form."""

from datetime import date
import re

from hoard_link.dates import MONTHS, WEEKDAYS

from .form_rules import fold


_NUMBERS = {}
for words in (
    "cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciseis diecisiete dieciocho diecinueve",
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen",
):
    _NUMBERS.update({word: index for index, word in enumerate(words.split())})
_NUMBERS.update({"un": 1, "una": 1, "veintiun": 21, "veintiuna": 21, "cien": 100, "hundred": 100, "one hundred": 100})
_TENS_ES = "veinte treinta cuarenta cincuenta sesenta setenta ochenta noventa".split()
_TENS_EN = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_UNITS_ES = "uno dos tres cuatro cinco seis siete ocho nueve".split()
_UNITS_EN = "one two three four five six seven eight nine".split()
for tens, (es, en) in enumerate(zip(_TENS_ES, _TENS_EN), 2):
    _NUMBERS.update({es: tens * 10, en: tens * 10})
    for digit, (unit_es, unit_en) in enumerate(zip(_UNITS_ES, _UNITS_EN), 1):
        _NUMBERS[("veinti" if tens == 2 else es + " y ") + unit_es] = tens * 10 + digit
        _NUMBERS[en + " " + unit_en] = _NUMBERS[en + " and " + unit_en] = tens * 10 + digit
_NUMBER = r"(?:[0-9]+|" + "|".join(map(re.escape, sorted(_NUMBERS, key=len, reverse=True))) + ")"
_MONTH = {alias: index for lang in ("es", "en") for index, aliases in enumerate(MONTHS[lang], 1) for alias in aliases}
_WEEKDAY = {alias: index for lang in ("es", "en") for index, aliases in enumerate(WEEKDAYS[lang]) for alias in aliases}
_DAY = r"(?:(?P<weekday>" + "|".join(_WEEKDAY) + r")[,\s]+)?"
_MONTH_WORD = r"(?P<month>" + "|".join(_MONTH) + ")"
_DATES = (
    re.compile(r"\b" + _DAY + r"(?P<day>" + _NUMBER + r")\s+de\s+" + _MONTH_WORD + r"(?:\s+de\s+(?P<year>\d{4}))?\b"),
    re.compile(r"\b" + _DAY + _MONTH_WORD + r"\s+(?P<day>" + _NUMBER + r")(?:,\s*|\s+)?(?P<year>\d{4})?\b"),
)
_GROUP = re.compile(r"\b(?:de parte (?:de|del)|somos|on behalf of|we are)\s+([^.!?;,\n]+)", re.I)
_GROUP_FIELD = re.compile(r"\b(?:grupo|colectivo|agrupacion|organizacion|group|organization|organisation|team)\b")
_COUNT_UNIT = r"personas?|plazas?|entradas?|asistentes?|butacas?|people|persons?|seats?|tickets?|attendees?"
_COUNT = re.compile(r"\b(?P<number>" + _NUMBER + r")\s+(?:" + _COUNT_UNIT + r")\b")
_COUNT_FIELD = re.compile(r"\b(?:" + _COUNT_UNIT + r"|aforo|headcount|attendance)\b")
_NEGATIVE = re.compile(r"\b(?:no|tampoco|not|never|neither)\b")


def _number(word):
    return int(word) if word.isdigit() else _NUMBERS[word]


def _date_mentions(text):
    for pattern in _DATES:
        for match in pattern.finditer(text):
            yield (_MONTH[match["month"]], _number(match["day"]), match["year"], _WEEKDAY.get(match["weekday"]), match[0])


def _date_matches(value, mention):
    try:
        selected = date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    month, day, year, weekday, _ = mention
    return (selected.month == month and selected.day == day and (year is None or int(year) == selected.year)
            and (weekday is None or selected.weekday() == weekday))


def _field_words(key, spec):
    aliases = spec.get("aliases")
    words = [key.replace("_", " "), str(spec.get("title", ""))]
    if isinstance(aliases, list):
        words.extend(word for word in aliases if isinstance(word, str))
    return fold(" ".join(words))


def spoken_form_values(text, targets, context):
    """Return schema values with their evidence from this turn."""
    folded = fold(text)
    # Negations and corrections have their own rules. Do not extract a positive value from them here.
    if _NEGATIVE.search(folded):
        return {}, {}
    proposals, quotes = {}, {}
    named = [(key, spec, _field_words(key, spec)) for key, spec in targets.items()]
    groups = [key for key, spec, words in named if spec.get("type") == "string" and not spec.get("enum")
              and _GROUP_FIELD.search(words)]
    group = _GROUP.search(text)
    if len(groups) == 1 and group:
        value = re.split(r"\s+(?:preferimos|queremos|we prefer|we want)\b", group[1], maxsplit=1, flags=re.I)[0].strip()
        if value and value[0].isalpha() and fold(value.split()[0]) not in _NUMBERS:
            proposals[groups[0]], quotes[groups[0]] = value, value
    counts = [key for key, spec, words in named if spec.get("type") in ("integer", "number") and _COUNT_FIELD.search(words)]
    matches = list(_COUNT.finditer(folded)) if counts else []
    if len(counts) == len(matches) == 1:
        proposals[counts[0]], quotes[counts[0]] = _number(matches[0]["number"]), matches[0][0]

    mentions = list(_date_mentions(folded))
    labels = context.get("option_labels")
    if len(mentions) != 1 or not isinstance(labels, dict):
        return proposals, quotes
    mention = mentions[0]
    dates = [key for key, spec, _ in named if spec.get("format") == "date"]
    if len(dates) != 1 or not isinstance(labels.get(dates[0]), dict):
        return proposals, quotes
    matching = [choice for choice in labels[dates[0]] if _date_matches(choice, mention)]
    if len(matching) != 1:
        return proposals, quotes
    proposals[dates[0]], quotes[dates[0]] = matching[0], mention[-1]
    for key, spec, _ in named:
        choices = spec.get("enum")
        field_labels = labels.get(key)
        if key == dates[0] or not isinstance(choices, list) or not isinstance(field_labels, dict):
            continue
        matching_choices = [choice for choice in choices if isinstance(field_labels.get(str(choice)), str)
                            and any(label_date[:2] == mention[:2] and label_date[2] in (None, matching[0][:4])
                                    for label_date in _date_mentions(fold(field_labels[str(choice)])))]
        if matching_choices:
            proposals[key] = matching_choices[0] if len(matching_choices) == 1 else matching_choices
            quotes[key] = mention[-1]
    return proposals, quotes
