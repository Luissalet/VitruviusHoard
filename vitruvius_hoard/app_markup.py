"""Check the structure of HTML sources before publishing a project revision."""
from __future__ import annotations

import re
from html.parser import HTMLParser

from .app_source_map import _TEXT_ONLY, _VOID
from .hoard_link.agentkit import AppError

_PARAGRAPH_BREAK = frozenset(
    "address article aside blockquote details dialog div dl fieldset figcaption figure footer form "
    "h1 h2 h3 h4 h5 h6 header hgroup hr main menu nav ol p pre search section table ul".split()
)
_NEXT_TAG = {
    "head": {"body"},
    "li": {"li"},
    "dt": {"dt", "dd"}, "dd": {"dt", "dd"},
    "p": _PARAGRAPH_BREAK,
    "rt": {"rt", "rp"}, "rp": {"rt", "rp"},
    "option": {"option", "optgroup", "hr"}, "optgroup": {"optgroup", "hr"},
    "colgroup": {"colgroup", "thead", "tbody", "tfoot", "tr"},
    "caption": {"colgroup", "thead", "tbody", "tfoot", "tr"},
    "thead": {"tbody", "tfoot"}, "tbody": {"tbody", "tfoot"},
    "tr": {"tr", "tbody", "tfoot"},
    "td": {"td", "th", "tr", "tbody", "tfoot"}, "th": {"td", "th", "tr", "tbody", "tfoot"},
}
_OPTIONAL_END = frozenset("html head body li dd p rt rp optgroup option colgroup caption tbody tfoot tr td th".split())
_EXPLICIT_PARAGRAPH_PARENT = frozenset("a audio del ins map noscript video".split())
_DOCUMENT = {"html", "head", "body"}
_FOREIGN_ROOT = {"svg", "math"}
_FOREIGN_HTML = {"foreignobject", "desc", "title"}
_INCOMPLETE = re.compile(r"^<(?:/?[a-zA-Z]|[!?])")


class _Markup(HTMLParser):
    CDATA_CONTENT_ELEMENTS = tuple(_TEXT_ONLY | {"noscript"})

    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.stack = []
        self.document_ends = set()
        self.has_h1 = False
        self.issue = None
        self.feed(source)
        if _INCOMPLETE.match(self.rawdata):
            self._record()
        self.close()
        while self._optional_end():
            self.stack.pop()
        if self.stack:
            self._record(self.stack[-1][2])

    def _record(self, at=None):
        if self.issue is None:
            self.issue = at or self.getpos()

    def _optional_end(self):
        if not self.stack:
            return False
        tag, foreign, _ = self.stack[-1]
        parent = self.stack[-2][0] if len(self.stack) > 1 else ""
        return not foreign and tag in _OPTIONAL_END and (
            tag != "p" or parent not in _EXPLICIT_PARAGRAPH_PARENT and "-" not in parent
        )

    def _start(self, tag, self_closing=False):
        while self.stack and not self.stack[-1][1] and tag in _NEXT_TAG.get(self.stack[-1][0], ()):
            self.stack.pop()
        foreign = tag in _FOREIGN_ROOT or bool(
            self.stack and self.stack[-1][1] and self.stack[-1][0] not in _FOREIGN_HTML
        )
        if tag == "h1" and not foreign and not any(name == "template" for name, _, _ in self.stack):
            self.has_h1 = True
        if not foreign and tag in _VOID or foreign and self_closing:
            return
        if self_closing:
            self._record()
        self.stack.append((tag, foreign, self.getpos()))

    def handle_starttag(self, tag, attrs):
        self._start(tag)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, self_closing=True)

    def handle_endtag(self, tag):
        while self.stack and self.stack[-1][0] != tag and self._optional_end():
            self.stack.pop()
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
        elif tag in self.document_ends or tag not in _DOCUMENT or any(
                name != "html" for name, _, _ in self.stack):
            self._record()
        if tag in _DOCUMENT:
            self.document_ends.add(tag)


def _message(lang, es, en):
    if lang == "es":
        return es
    if lang == "en":
        return en
    return f"{es} / {en}"


def validate_revision_markup(files, previous, *, preserve_h1, lang):
    for name, source in files.items():
        before = previous.get(name)
        if not name.lower().endswith(".html") or source == before:
            continue
        try:
            markup = _Markup(source)
        except (AssertionError, ValueError):
            raise AppError("invalid_html", _message(lang, f"Revisa el cierre del HTML en {name}.",
                                                   f"Check the HTML closing tags in {name}."), details={"file": name}) from None
        if markup.issue is not None:
            line, column = markup.issue
            raise AppError(
                "invalid_html",
                _message(lang, f"Revisa el cierre del HTML en {name}, línea {line}.",
                         f"Check the HTML closing tags in {name}, line {line}."),
                details={"file": name, "line": line, "column": column + 1},
            )
        if preserve_h1 and before and not markup.has_h1:
            try:
                had_h1 = _Markup(before).has_h1
            except (AssertionError, ValueError):
                continue  # Allow recovery from legacy markup the parser cannot read.
            if had_h1:
                raise AppError(
                    "missing_h1",
                    _message(lang, f"Conserva el encabezado h1 en {name}.",
                             f"Keep the h1 heading in {name}."),
                    details={"file": name},
                )
