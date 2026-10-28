"""Reading a page's source without a browser: colours, a small CSS parser, an HTML tree and a cascade good enough for
the static rules. Everything here is conservative: a selector or value it cannot read is skipped, never guessed.
"""

from __future__ import annotations

import colorsys
import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Iterator, Optional

RGBA = tuple[float, float, float, float]

_NAMED = {
    "white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0), "blue": (0, 0, 255), "green": (0, 128, 0),
    "yellow": (255, 255, 0), "orange": (255, 165, 0), "purple": (128, 0, 128), "violet": (238, 130, 238),
    "indigo": (75, 0, 130), "magenta": (255, 0, 255), "cyan": (0, 255, 255), "pink": (255, 192, 203),
    "gray": (128, 128, 128), "grey": (128, 128, 128), "silver": (192, 192, 192), "navy": (0, 0, 128),
    "teal": (0, 128, 128), "lime": (0, 255, 0), "aqua": (0, 255, 255), "fuchsia": (255, 0, 255), "maroon": (128, 0, 0),
    "olive": (128, 128, 0), "gold": (255, 215, 0), "beige": (245, 245, 220), "ivory": (255, 255, 240),
    "tomato": (255, 99, 71), "coral": (255, 127, 80), "salmon": (250, 128, 114), "crimson": (220, 20, 60),
}

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)"


def parse_color(value: Optional[str]) -> Optional[RGBA]:
    """rgb/rgba/hex/hsl/oklch/named -> (r, g, b, a) with channels 0-255 and alpha 0-1; None when unreadable."""
    if not value:
        return None
    v = value.strip().lower()
    if v in ("transparent",):
        return (0.0, 0.0, 0.0, 0.0)
    if v in _NAMED:
        r, g, b = _NAMED[v]
        return (float(r), float(g), float(b), 1.0)
    m = re.fullmatch(r"#([0-9a-f]{3,8})", v)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            h += "ff"
        if len(h) == 8:
            return (int(h[0:2], 16) * 1.0, int(h[2:4], 16) * 1.0, int(h[4:6], 16) * 1.0, int(h[6:8], 16) / 255)
        return None
    m = re.match(rf"rgba?\(\s*({_NUM})(%?)[\s,]+({_NUM})(%?)[\s,]+({_NUM})(%?)(?:\s*[,/]\s*({_NUM})(%?))?\s*\)", v)
    if m:
        def ch(num, pct):
            x = float(num)
            return x * 2.55 if pct else x
        a = 1.0
        if m.group(7) is not None:
            a = float(m.group(7)) / (100 if m.group(8) else 1)
        return (ch(m.group(1), m.group(2)), ch(m.group(3), m.group(4)), ch(m.group(5), m.group(6)), min(1.0, max(0.0, a)))
    m = re.match(rf"hsla?\(\s*({_NUM})(?:deg)?[\s,]+({_NUM})%[\s,]+({_NUM})%(?:\s*[,/]\s*({_NUM})(%?))?\s*\)", v)
    if m:
        h, s, l = float(m.group(1)) % 360 / 360, float(m.group(2)) / 100, float(m.group(3)) / 100
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        a = 1.0 if m.group(4) is None else float(m.group(4)) / (100 if m.group(5) else 1)
        return (r * 255, g * 255, b * 255, a)
    m = re.match(rf"oklch\(\s*({_NUM})(%?)\s+({_NUM})\s+({_NUM})(?:deg)?(?:\s*/\s*({_NUM})(%?))?\s*\)", v)
    if m:
        from ..tokens import oklch_to_rgb01
        L = float(m.group(1)) / (100 if m.group(2) else 1)
        r, g, b = oklch_to_rgb01(L, float(m.group(3)), float(m.group(4)))
        a = 1.0 if m.group(5) is None else float(m.group(5)) / (100 if m.group(6) else 1)
        return (r * 255, g * 255, b * 255, a)
    return None


def to_hex(c: RGBA) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(round(x)))) for x in c[:3]))


def hsl_of(c: RGBA) -> tuple[float, float, float]:
    """(hue 0-360, saturation 0-1, lightness 0-1)."""
    h, l, s = colorsys.rgb_to_hls(c[0] / 255, c[1] / 255, c[2] / 255)
    return h * 360, s, l


def oklch_of(c: RGBA) -> tuple[float, float, float]:
    from ..tokens import rgb01_to_oklch
    return rgb01_to_oklch(c[0] / 255, c[1] / 255, c[2] / 255)


def spread(c: RGBA) -> float:
    return max(c[:3]) - min(c[:3])


def is_chromatic(c: Optional[RGBA], min_spread: float = 40) -> bool:
    return c is not None and c[3] > 0.1 and spread(c) >= min_spread


def hue_gap(a: float, b: float) -> float:
    d = abs((a - b) % 360)
    return min(d, 360 - d)


def luminance(c: RGBA) -> float:
    def lin(x: float) -> float:
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def contrast(a: RGBA, b: RGBA) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def over(fg: RGBA, bg: RGBA) -> RGBA:
    a = fg[3]
    return (fg[0] * a + bg[0] * (1 - a), fg[1] * a + bg[1] * (1 - a), fg[2] * a + bg[2] * (1 - a), 1.0)


_COLOR_TOKEN = re.compile(r"(#[0-9a-fA-F]{3,8}\b|(?:rgba?|hsla?|oklch)\([^)]*\))")


def colors_in(value: str) -> list[RGBA]:
    out = []
    for m in _COLOR_TOKEN.finditer(value or ""):
        c = parse_color(m.group(1))
        if c:
            out.append(c)
    return out


def px(value: Optional[str], base: float = 16.0) -> Optional[float]:
    """A CSS length in px (px, rem, em, pt); None for anything else (%, vw, calc, var)."""
    if value is None:
        return None
    m = re.fullmatch(rf"\s*({_NUM})(px|rem|em|pt)?\s*", str(value).lower())
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2) or "px"
    return n * {"px": 1, "rem": base, "em": base, "pt": 96 / 72}[unit] if n else 0.0


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

@dataclass
class CssRule:
    selector: str
    decls: dict[str, str]
    order: int
    media: str = ""
    pairs: list[tuple[str, str]] = field(default_factory=list)   # every declaration in source order


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _split_top(text: str, sep: str) -> list[str]:
    out, depth, quote, cur = [], 0, "", []
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch in "([":
            depth += 1
            cur.append(ch)
        elif ch in ")]":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def parse_decls(body: str) -> list[tuple[str, str]]:
    pairs = []
    for part in _split_top(body, ";"):
        if ":" not in part:
            continue
        prop, _, value = part.partition(":")
        prop = prop.strip().lower()
        value = re.sub(r"\s*!important\s*$", "", value.strip(), flags=re.I).strip()
        if prop and value:
            pairs.append((prop, value))
    return pairs


def _blocks(css: str) -> Iterator[tuple[str, str]]:
    """Top-level ``prelude { body }`` pairs of a stylesheet (statements like @import are skipped)."""
    i, n = 0, len(css)
    while i < n:
        j = i
        depth_paren = 0
        while j < n and not (css[j] == "{" and depth_paren == 0) and not (css[j] == ";" and depth_paren == 0):
            if css[j] == "(":
                depth_paren += 1
            elif css[j] == ")":
                depth_paren = max(0, depth_paren - 1)
            j += 1
        if j >= n:
            break
        if css[j] == ";":
            i = j + 1
            continue
        prelude = css[i:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
            k += 1
        yield prelude, css[j + 1:k - 1]
        i = k


def parse_css(css: str) -> tuple[list[CssRule], dict[str, list[tuple[str, dict[str, str]]]], list[dict[str, str]]]:
    """(style rules in source order with @media flattened, @keyframes by name, @font-face descriptor dicts)."""
    rules: list[CssRule] = []
    keyframes: dict[str, list[tuple[str, dict[str, str]]]] = {}
    faces: list[dict[str, str]] = []
    counter = [0]

    def walk(text: str, media: str) -> None:
        for prelude, body in _blocks(text):
            low = prelude.lower()
            if low.startswith("@keyframes") or low.startswith("@-webkit-keyframes"):
                name = prelude.split(None, 1)[1].strip() if " " in prelude.strip() else ""
                frames = []
                for sel, fb in _blocks(body):
                    pairs = parse_decls(fb)
                    frames.append((sel.strip().lower(), dict(pairs)))
                keyframes[name.strip("\"'")] = frames
            elif low.startswith("@font-face"):
                faces.append(dict(parse_decls(body)))
            elif low.startswith("@media") or low.startswith("@supports") or low.startswith("@layer") or low.startswith("@container") or low.startswith("@scope"):
                walk(body, (media + " " + prelude).strip() if low.startswith("@media") else media)
            elif low.startswith("@"):
                continue
            else:
                pairs = parse_decls(body)
                for sel in _split_top(prelude, ","):
                    sel = sel.strip()
                    if sel:
                        counter[0] += 1
                        rules.append(CssRule(sel, dict(pairs), counter[0], media, pairs))

    walk(strip_comments(css), "")
    return rules, keyframes, faces


# ---------------------------------------------------------------------------
# HTML tree
# ---------------------------------------------------------------------------

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
SKIP_TEXT = {"script", "style", "noscript", "template", "head", "title"}


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict[str, str]
    parent: Optional["Node"]
    idx: int
    children: list["Node"] = field(default_factory=list)
    chunks: list[tuple[int, str]] = field(default_factory=list)  # (child position, text) in document order
    _text: Optional[str] = None

    @property
    def classes(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    @property
    def id(self) -> str:
        return self.attrs.get("id", "")

    def own_text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(t for _, t in self.chunks)).strip()

    def text(self) -> str:
        if self._text is None:
            parts: list[str] = []

            def walk(n: "Node") -> None:
                if n.tag in SKIP_TEXT:
                    return
                children = iter(n.children)
                pending = list(n.chunks)
                # chunks carry the number of children that came before them, so text and children interleave
                done = 0
                for pos, t in pending:
                    while done < pos:
                        walk(next(children))
                        done += 1
                    parts.append(t)
                for c in children:
                    walk(c)

            walk(self)
            self._text = re.sub(r"\s+", " ", " ".join(parts)).strip()
        return self._text

    def text_without(self, skip: set[str]) -> str:
        """Visible text with some elements (pre, code, svg ...) left out."""
        parts: list[str] = []

        def walk(n: "Node") -> None:
            if n.tag in SKIP_TEXT or n.tag in skip:
                return
            children = iter(n.children)
            done = 0
            for pos, t in n.chunks:
                while done < pos:
                    walk(next(children))
                    done += 1
                parts.append(t)
            for c in children:
                walk(c)

        walk(self)
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    def ancestors(self) -> Iterator["Node"]:
        n = self.parent
        while n is not None:
            yield n
            n = n.parent

    def descendants(self) -> Iterator["Node"]:
        for c in self.children:
            yield c
            yield from c.descendants()

    def label(self) -> str:
        s = self.tag
        if self.id:
            s += "#" + self.id
        if self.classes:
            s += "." + ".".join(self.classes[:2])
        return s


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None, 0)
        self.cur = self.root
        self.nodes: list[Node] = []
        self.styles: list[str] = []
        self._style_open = False
        self._style_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur, len(self.nodes) + 1)
        self.cur.children.append(node)
        self.nodes.append(node)
        if tag == "style":
            self._style_open = True
            self._style_buf = []
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur, len(self.nodes) + 1)
        self.cur.children.append(node)
        self.nodes.append(node)

    def handle_endtag(self, tag):
        if tag == "style" and self._style_open:
            self.styles.append("".join(self._style_buf))
            self._style_open = False
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent or self.root

    def handle_data(self, data):
        if self._style_open:
            self._style_buf.append(data)
        if data.strip():
            self.cur.chunks.append((len(self.cur.children), data))


_SPECIFICITY_ID = re.compile(r"#[\w-]+")
_SPECIFICITY_CLASS = re.compile(r"\.[\w-]+|\[[^\]]+\]|:(?!:)[\w-]+(?:\([^)]*\))?")
_SPECIFICITY_TAG = re.compile(r"(?:^|[\s>+~(])([a-zA-Z][\w-]*)")


def specificity(selector: str) -> tuple[int, int, int]:
    s = re.sub(r"::?(?:where)\([^)]*\)", "", selector)
    return (len(_SPECIFICITY_ID.findall(s)), len(_SPECIFICITY_CLASS.findall(s)), len(_SPECIFICITY_TAG.findall(s)))


_DYNAMIC = re.compile(r"::?(?:hover|focus|focus-within|focus-visible|active|visited|checked|disabled|before|after|placeholder|selection|"
                      r"first-line|first-letter|target|marker|backdrop|-webkit-[\w-]+|-moz-[\w-]+|file-selector-button)", re.I)
_COMPOUND = re.compile(r"^((?:[a-zA-Z][\w-]*|\*)?)((?:[.#][\w-]+|\[[^\]]+\]|:[\w-]+(?:\([^)]*\))?)*)$")


def _parse_selector(selector: str) -> Optional[list[tuple[str, str]]]:
    """[(combinator, compound)] left to right, or None when the selector uses something this reader skips."""
    if _DYNAMIC.search(selector):
        return None
    s = re.sub(r"\s*([>+~])\s*", r" \1 ", selector.strip())
    parts = s.split()
    out: list[tuple[str, str]] = []
    comb = " "
    for p in parts:
        if p in (">", "+", "~"):
            comb = p
            continue
        out.append((comb, p))
        comb = " "
    return out or None


def _match_compound(node: Node, compound: str) -> bool:
    m = _COMPOUND.match(compound)
    if not m:
        return False
    tag, rest = m.group(1), m.group(2)
    if tag and tag != "*" and tag.lower() != node.tag:
        return False
    for tok in re.findall(r"[.#][\w-]+|\[[^\]]+\]|:[\w-]+(?:\([^)]*\))?", rest):
        if tok[0] == ".":
            if tok[1:] not in node.classes:
                return False
        elif tok[0] == "#":
            if node.id != tok[1:]:
                return False
        elif tok[0] == "[":
            am = re.fullmatch(r"\[\s*([\w-]+)\s*(?:([~|^$*]?=)\s*[\"']?([^\"'\]]*)[\"']?)?\s*\]", tok)
            if not am:
                return False
            name, op, val = am.group(1), am.group(2), am.group(3)
            if name not in node.attrs:
                return False
            have = node.attrs[name]
            if op == "=" and have != val:
                return False
            if op == "^=" and not have.startswith(val or ""):
                return False
            if op == "*=" and (val or "") not in have:
                return False
            if op == "~=" and (val or "") not in have.split():
                return False
        elif tok.startswith(":root"):
            if node.tag != "html":
                return False
        elif tok.startswith((":not(", ":is(", ":where(")):
            inner = tok[tok.index("(") + 1:-1]
            hit = any(_match_compound(node, c.strip()) for c in inner.split(","))
            if tok.startswith(":not(") == hit:
                return False
        else:
            return False   # :first-child, :nth-child ... are not evaluated: the rule is skipped, not guessed
    return True


def _index_key(compound: str) -> str:
    """The cheapest thing a matching node must have: its id, else its first class, else its tag."""
    m = re.match(r"^([a-zA-Z][\w-]*|\*)?", compound)
    tag = m.group(1) if m else ""
    ident = re.search(r"#([\w-]+)", compound)
    if ident:
        return "#" + ident.group(1)
    cls = re.search(r"\.([\w-]+)", compound)
    if cls:
        return "." + cls.group(1)
    if tag and tag != "*":
        return tag.lower()
    return "*"


def selector_matches(node: Node, parsed: list[tuple[str, str]]) -> bool:
    def match_at(n: Optional[Node], i: int) -> bool:
        if n is None:
            return False
        comb, compound = parsed[i]
        if not _match_compound(n, compound):
            return False
        if i == 0:
            return True
        prev_comb = comb
        if prev_comb == ">":
            return match_at(n.parent, i - 1)
        if prev_comb == " ":
            a = n.parent
            while a is not None:
                if match_at(a, i - 1):
                    return True
                a = a.parent
            return False
        if prev_comb in ("+", "~"):
            if n.parent is None:
                return False
            sibs = n.parent.children
            pos = sibs.index(n)
            cands = sibs[:pos][-1:] if prev_comb == "+" else sibs[:pos]
            return any(match_at(c, i - 1) for c in cands)
        return False

    return match_at(node, len(parsed) - 1)


INHERITED = {"color", "font-family", "font-size", "font-style", "font-weight", "line-height", "letter-spacing",
             "text-transform", "text-align", "word-spacing", "font-variant", "visibility", "cursor", "text-wrap"}


class Page:
    """A parsed page: HTML tree, style rules and keyframes, with a small cascade."""

    def __init__(self, html: str = "", extra_css: str = ""):
        self.html = html or ""
        builder = _TreeBuilder()
        try:
            builder.feed(self.html)
            builder.close()
        except Exception:  # noqa: BLE001 — a malformed document still yields what was parsed so far
            pass
        self.root = builder.root
        self.nodes = builder.nodes
        self.css = "\n".join([*builder.styles, extra_css or ""])
        self.rules, self.keyframes, self.font_faces = parse_css(self.css)
        self._parsed: list[tuple[CssRule, Any, tuple[int, int, int]]] = []
        self._index: dict[str, list[tuple[CssRule, Any, tuple[int, int, int]]]] = {}
        for r in self.rules:
            parsed = _parse_selector(r.selector)
            if parsed is not None:
                entry = (r, parsed, specificity(r.selector))
                self._parsed.append(entry)
                self._index.setdefault(_index_key(parsed[-1][1]), []).append(entry)
        self._var_cache: Optional[dict[str, str]] = None
        self._decl_cache: dict[int, dict[str, str]] = {}
        self._text: Optional[str] = None

    # -- lookup -----------------------------------------------------------------
    def find(self, tag: str) -> list[Node]:
        return [n for n in self.nodes if n.tag == tag]

    def find_any(self, tags: set[str] | tuple[str, ...]) -> list[Node]:
        s = set(tags)
        return [n for n in self.nodes if n.tag in s]

    @property
    def text(self) -> str:
        if self._text is None:
            body = next((n for n in self.nodes if n.tag == "body"), None)
            self._text = (body or self.root).text()
        return self._text

    # -- cascade ----------------------------------------------------------------
    def variables(self) -> dict[str, str]:
        """Custom properties declared on :root / html / body / * (the token block), light scheme only."""
        if self._var_cache is None:
            v: dict[str, str] = {}
            for rule in self.rules:
                if rule.media and "prefers-color-scheme" in rule.media:
                    continue
                if not re.fullmatch(r"(?::root|html|body|\*)(?:\s*[.#][\w-]+)?", rule.selector.strip()):
                    continue
                for prop, val in rule.pairs:
                    if prop.startswith("--"):
                        v[prop] = val
            self._var_cache = v
        return self._var_cache

    def resolve(self, value: str, depth: int = 0) -> str:
        if "var(" not in value or depth > 4:
            return value
        vars_ = self.variables()

        def sub(m: re.Match) -> str:
            name, _, fallback = m.group(1).partition(",")
            got = vars_.get(name.strip())
            return got if got is not None else fallback.strip()

        out = re.sub(r"var\(\s*([^()]*(?:\([^()]*\)[^()]*)*)\)", sub, value)
        return self.resolve(out, depth + 1) if "var(" in out else out

    def declared(self, node: Node) -> dict[str, str]:
        """The declarations that apply to this very node: matching rules by specificity and order, then inline."""
        cached = self._decl_cache.get(id(node))
        if cached is not None:
            return cached
        hits: list[tuple[tuple[int, int, int], int, CssRule]] = []
        keys = ["*", node.tag, *("." + c for c in node.classes)]
        if node.id:
            keys.append("#" + node.id)
        candidates = [e for k in keys for e in self._index.get(k, ())]
        for rule, parsed, spec in candidates:
            try:
                if selector_matches(node, parsed):
                    hits.append((spec, rule.order, rule))
            except Exception:  # noqa: BLE001
                continue
        hits.sort(key=lambda h: (h[0], h[1]))
        out: dict[str, str] = {}
        for _, _, rule in hits:
            if rule.media and re.search(r"max-width|min-width|print|prefers-reduced-motion|prefers-color-scheme", rule.media):
                continue  # the base layout; breakpoint overrides are not evaluated
            for prop, val in rule.pairs:
                out[prop] = val
        for prop, val in parse_decls(node.attrs.get("style", "")):
            out[prop] = val
        out = {k: self.resolve(v) for k, v in out.items()}
        self._decl_cache[id(node)] = out
        return out

    def style(self, node: Node, prop: str, inherit: Optional[bool] = None) -> Optional[str]:
        inherit = prop in INHERITED if inherit is None else inherit
        n: Optional[Node] = node
        while n is not None:
            d = self.declared(n)
            if prop in d and d[prop] not in ("inherit",):
                return d[prop]
            if not inherit:
                return None
            n = n.parent
        return None

    def rule_pairs(self) -> Iterator[tuple[CssRule, str, str]]:
        for r in self.rules:
            for prop, val in r.pairs:
                yield r, prop, self.resolve(val)

    def all_declarations(self) -> Iterator[tuple[str, str, str]]:
        """(selector or 'inline:<tag>', property, value) for every stylesheet and inline-style declaration."""
        for r, prop, val in self.rule_pairs():
            yield r.selector, prop, val
        for n in self.nodes:
            st = n.attrs.get("style")
            if st:
                for prop, val in parse_decls(st):
                    yield "inline:" + n.label(), prop, self.resolve(val)


PROSE_SKIP = {"pre", "code", "kbd", "samp", "svg", "textarea", "math", "canvas", "select", "option"}


def prose(page: Page) -> str:
    """The page's running text: no code blocks, no svg, no form internals."""
    body = next((n for n in page.nodes if n.tag == "body"), None)
    return (body or page.root).text_without(PROSE_SKIP)


_PAGE_CACHE: dict[str, Page] = {}


def page_of(probe: Optional[dict], html: str) -> Page:
    """The parsed page for a lint run (cached: a dozen static rules read the same page). For a captured URL the browser
    hands back its serialised DOM and stylesheet text in the probe, so static rules work there too."""
    probe = probe or {}
    source = html or probe.get("html_text") or ""
    extra = probe.get("css_text") or ""
    key = hashlib.sha1((source + "\x00" + extra).encode("utf-8", "ignore")).hexdigest()
    page = _PAGE_CACHE.get(key)
    if page is None:
        if len(_PAGE_CACHE) > 6:
            _PAGE_CACHE.pop(next(iter(_PAGE_CACHE)))
        page = _PAGE_CACHE[key] = Page(source, extra)
    return page


def has_source(probe: Optional[dict], html: str) -> bool:
    return bool((html or "").strip() or (probe or {}).get("html_text"))
