"""Plan positional canvas edits against the HTML and CSS served by the owned preview."""
from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import re
from urllib.parse import unquote, urljoin, urlsplit

from .app_source_map import SourceMapError, _HTML, edit_source, source_position, source_tag


STYLE_PROPERTIES = (
    "width", "height", "margin-top", "margin-right", "margin-bottom", "margin-left",
    "padding-top", "padding-right", "padding-bottom", "padding-left",
)
_CLASS_PREFIX = "canvas-"
_MANAGED_CLASS = re.compile(r"canvas-[a-f0-9]{12}(?:-[0-9]+)?")
_CSS_SPACE = re.compile(r"[\t\n\f\r ]+")


def _error(en, es):
    return SourceMapError(en, es)


def _classes(attrs):
    return _CSS_SPACE.split((attrs.get("class") or "").strip("\t\n\f\r "))


def _sheets(files, page, route):
    """Follow same-page stylesheet links in document order, using the runtime's asset precedence."""
    base = urljoin("http://preview.invalid/", route)
    for tag in page.tags:
        attrs = dict(tag.attrs)
        if tag.name == "base" and attrs.get("href"):
            base = urljoin(base, attrs["href"])
            break
    for tag in page.tags:
        attrs = dict(tag.attrs)
        if (tag.name != "link" or "stylesheet" not in (attrs.get("rel") or "").lower().split()
                or "disabled" in attrs or (attrs.get("media") or "all").lower().strip() != "all"
                or not attrs.get("href")):
            continue
        url = urlsplit(urljoin(base, attrs["href"]))
        path = unquote(url.path).lstrip("/")
        if url.scheme != "http" or url.netloc != "preview.invalid" or not path.startswith("assets/"):
            continue
        if f"public/{path}" in files:
            yield f"public/{path}"
        elif path in files:
            yield path


def _significant(tokens):
    return [token for token in tokens if token.type not in ("whitespace", "comment")]


@dataclass(frozen=True)
class _Selector:
    tag: str | None
    element_id: str | None
    classes: tuple[str, ...]

    def matches(self, tag, attrs):
        return (self.tag in (None, tag) and self.element_id in (None, attrs.get("id"))
                and all(name in _classes(attrs) for name in self.classes))

    @property
    def priority(self):
        managed = any(_MANAGED_CLASS.fullmatch(name) for name in self.classes)
        return managed, self.element_id is not None, len(self.classes), self.tag is not None


def _selectors(prelude):
    """Parse grouped simple selectors, including an optional tag or ID and several classes."""
    groups = [[]]
    for token in prelude:
        if token == ",":
            groups.append([])
        elif token.type != "comment":
            groups[-1].append(token)
    result = []
    for group in groups:
        while group and group[0].type == "whitespace":
            group.pop(0)
        while group and group[-1].type == "whitespace":
            group.pop()
        if not group:
            return []
        tag = group.pop(0).lower_value if group[0].type == "ident" else None
        element_id = None
        classes = []
        while group:
            token = group.pop(0)
            if token.type == "hash" and token.is_identifier and element_id is None:
                element_id = token.value
            elif token == "." and group and group[0].type == "ident":
                classes.append(group.pop(0).value)
            else:
                return []
        result.append(_Selector(tag, element_id, tuple(classes)))
    return result


def _declarations(tinycss2, tokens):
    return tinycss2.parse_declaration_list(tokens, skip_comments=True, skip_whitespace=True)


def _read_sheets(tinycss2, files, paths, tag=None, attrs=None):
    tokens = {}
    candidates = []
    for path in paths:
        for rule in tinycss2.parse_stylesheet(files[path], skip_comments=True, skip_whitespace=True):
            if rule.type != "qualified-rule":
                continue
            if tinycss2.serialize(rule.prelude).strip() == ":root":
                for declaration in _declarations(tinycss2, rule.content):
                    if declaration.type == "declaration" and declaration.name.startswith("--"):
                        previous = tokens.get(declaration.name)
                        if previous is None or declaration.important or not previous.important:
                            tokens[declaration.name] = declaration
            if tag is not None:
                selectors = _selectors(rule.prelude)
                matching = [selector.priority for selector in selectors if selector.classes and selector.matches(tag, attrs)]
                if matching:
                    priority = max(matching)
                    candidates.append((priority, path, rule, selectors))
    candidate = max(reversed(candidates), key=lambda item: item[0], default=None)
    return tokens, candidate


def _scale(tokens, root_font_px):
    def length(name, visited):
        if name not in tokens or name in visited:
            return None
        value = _significant(tokens[name].value)
        if len(value) != 1:
            return None
        token = value[0]
        if token.type == "dimension" and token.lower_unit in {"px", "rem"}:
            return token.value * (root_font_px if token.lower_unit == "rem" else 1)
        if token.type == "number" and token.value == 0:
            return 0
        if token.type == "function" and token.lower_name == "var":
            arguments = _significant(token.arguments)
            if len(arguments) == 1 and arguments[0].type == "ident":
                return length(arguments[0].value, visited | {name})
        return None

    scale = []
    for name in tokens:
        value = length(name, set())
        if value is not None and abs(value) <= 100_000:
            scale.append({"name": name, "pixels": round(value, 4)})
    return scale


def _css_offset(starts, token):
    return starts[token.source_line - 1] + token.source_column - 1


def _insert_declaration(tinycss2, css, rule, property_name, value, important=False):
    """Insert only at the winning rule, leaving the rest of the stylesheet byte-for-byte."""
    starts = [0, *(match.end() for match in re.finditer(r"\r\n|[\r\n\f]", css))]
    tokens = tinycss2.parse_component_value_list(css)
    offsets = [_css_offset(starts, token) for token in tokens]
    start = _css_offset(starts, rule)
    for index in range(bisect_right(offsets, start), len(tokens)):
        if tokens[index].type == "{} block":
            break
    else:
        raise _error("Open the stylesheet to edit this rule.", "Abre la hoja de estilos para editar esta regla.")
    end = (offsets[index + 1] if index + 1 < len(tokens) else len(css)) - 1
    if css[end] != "}":
        raise _error("Close the CSS rule before editing it.", "Cierra la regla CSS antes de editarla.")
    declarations = _declarations(tinycss2, rule.content)
    shorthand = property_name.split("-")[0]
    last = next((item for item in reversed(declarations)
                 if item.type == "declaration" and item.lower_name in {property_name, shorthand, "all"}), None)
    important = important or any(item.type == "declaration" and item.important
                                 and item.lower_name in {property_name, shorthand, "all"} for item in declarations)
    if last and last.lower_name == property_name and last.important == important:
        significant = _significant(last.value)
        previous = tinycss2.serialize(last.value).strip()
        if previous == value:
            return css
        if len(significant) == 1 and all(token.type != "comment" for token in last.value):
            begin = _css_offset(starts, significant[0])
            if css.startswith(previous, begin):
                return css[:begin] + value + css[begin + len(previous):]
    before = css[:end].rstrip()
    separator = ";" if before and before[-1] not in "{;" else ""
    declaration = f"{property_name}: {value}{' !important' if important else ''};"
    newline = "\r\n" if "\r\n" in css else "\n"
    block = css[offsets[index]:end]
    if "\n" in block:
        tail = css[len(before):end]
        indent = re.search(r"(?:^|\n)([ \t]+)[^ \t\r\n]", block)
        line = (indent[1] if indent else "  ") + declaration
        return before + separator + newline + line + (tail if "\n" in tail else newline) + css[end:]
    return before + separator + " " + declaration + css[len(before):]


def _add_stylesheet(files):
    filename = "assets/canvas-edits.css"
    serial = 1
    while filename in files or f"public/{filename}" in files:
        serial += 1
        filename = f"assets/canvas-edits-{serial}.css"
    layout = files["layout.html"]
    tags = _HTML(layout).tags
    anchor = next((tag for tag in tags if tag.name == "head"), None)
    if anchor is None:
        anchor = next((tag for tag in tags if tag.name in {"html", "body"}), None)
    doctype = re.match(r"\ufeff?\s*<!doctype[^>]*>", layout, re.I)
    offset = anchor.start + len(anchor.raw) if anchor else doctype.end() if doctype else 0
    link = f'<link rel="stylesheet" href="/{filename}">'
    return filename, layout[:offset] + link + layout[offset:]


def _target_class(vsrc, page, files):
    stem = _CLASS_PREFIX + sha256(vsrc.encode()).hexdigest()[:12]
    classes = {name for tag in page.tags for name in _classes(dict(tag.attrs))}
    # Reserve dormant rules and classes on other pages as well as rendered classes.
    for path, content in files.items():
        if path.lower().endswith((".css", ".html")):
            classes.update(re.findall(r"\b" + re.escape(stem) + r"(?:-[0-9]+)?\b", content))
    name = stem
    serial = 1
    while name in classes:
        serial += 1
        name = f"{stem}-{serial}"
    return name


def _css_parser():
    try:
        import tinycss2
    except ImportError as error:
        raise _error(
            "Canvas style editing needs tinycss2. Install the project dependencies or use the source editor.",
            "La edición de estilos en el lienzo requiere tinycss2. Instala las dependencias o usa el editor de fuente.",
        ) from error
    return tinycss2


def canvas_token_scale(files, html, route, root_font_px):
    """Read the same snapping tokens the style planner uses without planning an edit."""
    try:
        parser = _css_parser()
    except SourceMapError:
        return []
    paths = list(dict.fromkeys(_sheets(files, _HTML(html), route)))
    tokens, _ = _read_sheets(parser, files, paths)
    return _scale(tokens, root_font_px)


def _style_plan(files, page, route, vsrc, source, tag, line, column, change, root_font_px):
    property_name, pixels = change["property"], change["pixels"]
    if property_name not in STYLE_PROPERTIES or not -100_000 <= pixels <= 100_000:
        raise _error("Choose a supported size or spacing value.", "Elige un valor de tamaño o espaciado admisible.")
    if pixels < 0 and not property_name.startswith("margin-"):
        raise _error("Use zero or a positive size.", "Usa cero o un tamaño positivo.")

    tinycss2 = _css_parser()
    attrs = dict(tag.attrs)
    paths = list(dict.fromkeys(_sheets(files, page, route)))
    tokens, candidate = _read_sheets(tinycss2, files, paths, tag.name, attrs)
    scale = _scale(tokens, root_font_px)
    token = next((item["name"] for item in scale if item["pixels"] == pixels), None)
    number = format(Decimal(str(pixels)).normalize(), "f")
    value = f"var({tinycss2.serialize_identifier(token)})" if token else f"{number}px"

    inline = [item for item in _declarations(tinycss2, attrs.get("style") or "") if item.type == "declaration"
              and item.lower_name in {property_name, property_name.split("-")[0], "all"}]
    if any(item.important for item in inline):
        raise _error("This property has an important inline declaration. Edit it in the source file first.",
                     "Esta propiedad tiene una declaración en línea prioritaria. Edítala primero en el fichero fuente.")

    if candidate and (not inline or candidate[0][0]):
        _, filename, rule, selectors = candidate
        css = files[filename]
        updated = _insert_declaration(tinycss2, css, rule, property_name, value, important=bool(inline))
        affected = sum(any(selector.matches(entry.name, dict(entry.attrs)) for selector in selectors)
                       for entry in page.tags)
        target = {"kind": "class", "selector": tinycss2.serialize(rule.prelude).strip(), "file": filename}
        return {filename: updated} if updated != css else {}, target, scale, token, affected

    name = next((name for name in _classes(attrs) if _MANAGED_CLASS.fullmatch(name)), None) or _target_class(vsrc, page, files)
    source_file = source_position(vsrc)[0]
    updated = edit_source(source, line, column, tag.name, {"kind": "class", "operation": "add", "value": name})
    changes = {source_file: updated}
    if paths:
        filename = paths[-1]
    else:
        filename, layout = _add_stylesheet({**files, **changes})
        changes["layout.html"] = layout
    css = files.get(filename, "")
    suffix = " !important" if inline else ""
    element_id = attrs.get("id") or ""
    id_prefix = f"#{tinycss2.serialize_identifier(element_id)}" if element_id and "{{" not in element_id else ""
    selector = f"{id_prefix}.{name}"
    changes[filename] = css + ("\n" if css and not css.endswith("\n") else "") + f"{selector} {{ {property_name}: {value}{suffix}; }}\n"
    target = {"kind": "new_class", "selector": selector, "file": filename}
    return changes, target, scale, token, None


def plan_canvas_edit(files, html, route, vsrc, expected_tag, change, root_font_px):
    filename, line, column = source_position(vsrc)
    source = files.get(filename)
    if source is None:
        raise _error("Open the current preview; the source file has changed.",
                     "Abre la vista previa actual. El fichero fuente ha cambiado.")
    tag = source_tag(source, line, column, expected_tag)
    page = _HTML(html)
    occurrences = sum(dict(entry.attrs).get("data-vsrc") == vsrc and entry.name == tag.name for entry in page.tags)
    if not occurrences:
        raise _error("This source position is missing from the preview page. Select the element again.",
                     "La posición ya no aparece en la página. Vuelve a seleccionar el elemento.")
    if change["kind"] == "text":
        updated = edit_source(source, line, column, expected_tag, change)
        return ({filename: updated} if updated != source else {},
                {"kind": "text", "file": filename}, [], None, occurrences)
    updates, target, scale, token, affected = _style_plan(
        files, page, route, vsrc, source, tag, line, column, change, root_font_px,
    )
    return updates, target, scale, token, affected if affected is not None else occurrences
