"""Source positions for rendered project templates and edits to their literal HTML."""
from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import PurePosixPath

_MARKER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_GENERATED_HTML = {"table", "form"}
_VOID = set("area base br col embed hr img input link meta param source track wbr".split())
_RAW = set("script style xmp iframe noembed noframes plaintext".split())
_TEXT_ONLY = _RAW | {"title", "textarea"}
_TAG_NAME = re.compile(r"<[^\t\n\f\r />]+")
_SPACE = "\t\n\f\r "
_ATTRIBUTE = re.compile(
    r"""[\t\n\f\r ]+(?P<name>[^\t\n\f\r "'<>/=]+)"""
    r"""(?:[\t\n\f\r ]*=[\t\n\f\r ]*(?:"(?P<double>[^"]*)"|'(?P<single>[^']*)'|(?P<bare>[^\t\n\f\r "'=<>\x60]+)))?"""
)
_ATTRIBUTE_NAME = re.compile(r"""[^\s"'<>/=\x00]+""")
_MAP_ATTRIBUTES = {"data-vsrc", "data-vgen"}


class SourceMapError(ValueError):
    def __init__(self, message, spanish):
        super().__init__(message)
        self.spanish = spanish


@dataclass
class _Tag:
    name: str
    start: int
    raw: str
    attrs: list
    top_level: bool
    text: list[tuple[int, int]] = field(default_factory=list)


class _HTML(HTMLParser):
    # Retain raw spans even for entities, and treat CSS and RCDATA as text.
    CDATA_CONTENT_ELEMENTS = tuple(_TEXT_ONLY)

    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0, *(match.end() for match in re.finditer("\n", source))]
        self.tags = []
        self.stack = []
        self.text = []
        self.feed(source)
        self.close()

    def parse_html_declaration(self, index):
        # Older parsers raise on unknown marked sections instead of treating them as comments.
        try:
            return super().parse_html_declaration(index)
        except AssertionError:
            return self.parse_bogus_comment(index)

    def _offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def location(self, filename, offset):
        line = bisect_right(self.lines, offset)
        return f"{filename}:{line}:{offset - self.lines[line - 1] + 1}"

    def _open(self, name, attrs, *, closed=False):
        tag = _Tag(name, self._offset(), self.get_starttag_text(), attrs, not self.stack)
        self.tags.append(tag)
        if not closed and name not in _VOID:
            self.stack.append(tag)

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, closed=True)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].name == tag:
                del self.stack[index:]
                break

    def _data(self, start, end):
        parent = self.stack[-1] if self.stack else None
        if parent:
            self._append_span(parent.text, start, end)
        if parent is None or parent.name not in _TEXT_ONLY:
            self._append_span(self.text, start, end)

    @staticmethod
    def _append_span(spans, start, end):
        if spans and spans[-1][1] == start:
            spans[-1] = (spans[-1][0], end)
        else:
            spans.append((start, end))

    def handle_data(self, data):
        start = self._offset()
        self._data(start, start + len(data))

    def _entity(self, token):
        start = self._offset()
        end = start + len(token)
        self._data(start, end + self.source.startswith(";", end))

    def handle_entityref(self, name):
        self._entity("&" + name)

    def handle_charref(self, name):
        self._entity("&#" + name)


def _apply(source, edits):
    parts = []
    cursor = 0
    for start, end, value in sorted(edits):
        parts.extend((source[cursor:start], value))
        cursor = end
    parts.append(source[cursor:])
    return "".join(parts)


def _tag_end(tag):
    return tag.start + _TAG_NAME.match(tag.raw).end()


def _annotation(tag, vsrc, marker=None):
    position = _tag_end(tag)
    attributes = f' data-vsrc="{escape(vsrc, quote=True)}"'
    if marker:
        attributes += f' data-vgen="{marker}"'
    return position, position, attributes


def render_template(root, path, values):
    """Annotate openings and generated fragment roots before emitting rendered HTML."""
    source = path.read_bytes().decode("utf-8")
    filename = path.relative_to(root).as_posix()
    parsed = _HTML(source)
    edits = [_annotation(tag, parsed.location(filename, tag.start)) for tag in parsed.tags]
    text_spans = iter(parsed.text)
    span = next(text_spans, None)
    for match in _MARKER.finditer(source):
        name = match[1]
        if name not in values:
            continue
        value = values[name]
        if name in _GENERATED_HTML:
            while span and span[1] <= match.start():
                span = next(text_spans, None)
            if span and span[0] <= match.start() and match.end() <= span[1]:
                vsrc = parsed.location(filename, match.start())
                fragment = _HTML(value)
                value = _apply(value, [_annotation(tag, vsrc, name) for tag in fragment.tags if tag.top_level])
        edits.append((match.start(), match.end(), value))
    return _apply(source, edits)


def first_changed_source(filename, old, new):
    """Find the first edited opening tag or owning literal text node in the old HTML."""
    offset = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
    parsed = _HTML(old)
    for tag in reversed(parsed.tags):
        if tag.start <= offset < tag.start + len(tag.raw) or any(
            start <= offset <= end for start, end in tag.text
        ):
            return parsed.location(filename, tag.start)
    return None


def source_count(rendered, vsrc):
    """Count actual markup attributes, excluding strings in comments and raw text."""
    return sum(next((value for name, value in tag.attrs if name == "data-vsrc"), None) == vsrc
               for tag in _HTML(rendered).tags)


def source_position(vsrc):
    match = re.fullmatch(r"(.+):([1-9][0-9]*):([1-9][0-9]*)", vsrc)
    if match:
        filename, line, column = match.groups()
        path = PurePosixPath(filename)
        if (filename == "layout.html" or
                path.parts[:1] == ("pages",) and path.suffix == ".html" and
                filename == path.as_posix() and ".." not in path.parts and
                "\\" not in filename and ":" not in filename):
            return filename, int(line), int(column)
    raise SourceMapError("Expected a source position in layout.html or pages/**/*.html",
                         "Se esperaba una posición en layout.html o pages/**/*.html")


def _generated(marker):
    return SourceMapError(
        f"Comes from {{{{{marker}}}}}. Change it in the project fields or styles.",
        f"Viene de {{{{{marker}}}}}. Cámbialo en los campos o los estilos del proyecto.",
    )


def _reject_marker(raw):
    marker = _MARKER.search(raw)
    if marker:
        raise _generated(marker[1])


def _conflict():
    return SourceMapError("The source position no longer points to the expected HTML tag. Open the current preview.",
                          "La posición ya no apunta a la etiqueta HTML esperada. Abre la vista previa actual.")


def _literal(value):
    # An authored literal containing template syntax must display exactly as typed.
    return _MARKER.sub(lambda match: "&#123;&#123;" + match[1] + "}}", escape(value, quote=True))


def _direct_text_spans(source, tag):
    return [(start, end) for start, end in tag.text if source[start:end].strip(_SPACE)]


def project_text_field(source, tag, index):
    """Recognise a complete text binding, excluding mixed text and generated markup."""
    spans = _direct_text_spans(source, tag)
    if tag.name not in _RAW and 0 <= index < len(spans):
        start, end = spans[index]
        marker = _MARKER.fullmatch(source[start:end].strip(_SPACE))
        if marker and marker[1] in {"name", "description"}:
            return marker[1]
    return None


def _text_edit(source, tag, change):
    if tag.name in _RAW:
        raise SourceMapError("Edit script or style contents in the source file.",
                             "Edita el contenido de scripts o estilos en el fichero fuente.")
    spans = _direct_text_spans(source, tag)
    if "index" in change:
        index = change["index"]
        if not 0 <= index < len(spans):
            raise _conflict()
        start, end = spans[index]
        _reject_marker(source[start:end])
    else:
        for start, end in spans:
            _reject_marker(source[start:end])
        if len(spans) != 1:
            raise SourceMapError("This tag needs a single direct literal text node. Edit the source file.",
                                 "La etiqueta necesita un solo nodo de texto literal directo. Edita el fichero fuente.")
        start, end = spans[0]
    raw = source[start:end]
    start += len(raw) - len(raw.lstrip(_SPACE))
    end -= len(raw) - len(raw.rstrip(_SPACE))
    raw_value = source[start:end]
    old = unescape(raw_value)
    if "original" in change and unescape(raw_value.replace("\r\n", "\n").replace("\r", "\n")) != change["original"]:
        raise _conflict()
    value = change["value"]
    if old == value:
        return source
    return source[:start] + _literal(value) + source[end:]


def _attributes(tag):
    start = _TAG_NAME.match(tag.raw).end()
    end = len(tag.raw) - 1
    attributes = []
    for match in _ATTRIBUTE.finditer(tag.raw, start, end):
        if match.start() != start:
            break
        attributes.append(match)
        start = match.end()
    if tag.raw[start:end].strip(_SPACE) not in {"", "/"}:
        raise SourceMapError("The opening tag has ambiguous attribute syntax. Edit the source file.",
                             "La etiqueta de apertura tiene atributos ambiguos. Edita el fichero fuente.")
    return attributes


def _attribute_edit(source, tag, change):
    name = "class" if change["kind"] == "class" else change["name"].lower()
    if not _ATTRIBUTE_NAME.fullmatch(name) or name in _MAP_ATTRIBUTES:
        raise SourceMapError("Invalid or reserved HTML attribute.", "Atributo HTML no válido o reservado.")
    matches = [match for match in _attributes(tag) if match["name"].lower() == name]
    if len(matches) > 1:
        raise SourceMapError("The opening tag repeats this attribute. Edit the source file.",
                             "La etiqueta repite este atributo. Edita el fichero fuente.")
    match = matches[0] if matches else None
    group = next((group for group in ("double", "single", "bare") if match and match[group] is not None), None)
    raw = match[group] if group else ""
    _reject_marker(raw)
    old = unescape(raw)
    value = change["value"]
    if change["kind"] == "class":
        if not value or re.search(r"[\t\n\f\r \x00]", value):
            raise SourceMapError("Supply a single CSS class.", "Indica una sola clase CSS.")
        classes = re.findall(r"[^\t\n\f\r ]+", old)
        present = value in classes
        if (change["operation"] == "add") == present:
            return source
        value = " ".join(classes + [value] if change["operation"] == "add" else [item for item in classes if item != value])
    if value is None:
        if not match:
            return source
        start, end = match.span()
        replacement = ""
    elif group and value == old:
        return source
    elif group:
        start, end = match.span(group)
        replacement = _literal(value)
        if group == "bare" and (not replacement or re.search(r"[\t\n\f\r =\x60]", replacement)):
            replacement = '"' + replacement + '"'
    elif match:
        start = end = match.end()
        replacement = f'="{_literal(value)}"'
    else:
        position = _tag_end(tag)
        return source[:position] + f' {name}="{_literal(value)}"' + source[position:]
    return _apply(source, [(tag.start + start, tag.start + end, replacement)])


def source_tag(source, line, column, expected_tag):
    """Find the literal opening tag at a preview source position."""
    parsed = _HTML(source)
    if not 1 <= line <= len(parsed.lines) or column < 1:
        raise _conflict()
    offset = parsed.lines[line - 1] + column - 1
    if line < len(parsed.lines) and offset >= parsed.lines[line]:
        raise _conflict()
    marker = _MARKER.match(source, offset)
    if marker:
        raise _generated(marker[1])
    tag = next((tag for tag in parsed.tags if tag.start == offset), None)
    if tag is None or tag.name != expected_tag.lower():
        raise _conflict()
    return tag


def edit_source(source, line, column, expected_tag, change):
    """Apply a single positional change, preserving bytes outside the target span."""
    tag = source_tag(source, line, column, expected_tag)
    if change["kind"] == "text":
        return _text_edit(source, tag, change)
    return _attribute_edit(source, tag, change)


def _launch_legacy_preview():
    """Keep the retained server's routing and add the template hook to its renderer."""
    import runpy
    import sys
    from functools import partial

    from app_runtime import render_page

    server, *arguments = sys.argv[1:]
    sys.argv = [server, *arguments]
    main = runpy.run_path(server)["main"]
    main.__globals__["render_page"] = partial(render_page, render_template=render_template)
    main()


if __name__ == "__main__":
    _launch_legacy_preview()
