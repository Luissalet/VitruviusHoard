"""Figma frame -> compact spec -> HTML/CSS -> a Vitruvius design project, compared with Figma's own render.

The reduction (auto-layout read as flex, repeated styles collapsed into named style ids, only what a builder needs kept) follows
the idea of Figma-Context-MCP by GLips (MIT); the code is original. The token is a Figma personal access token kept in
``<data>/figma-token`` (never in the repository). Without a token a frame can still be imported from the JSON the REST API
returns (``GET /v1/files/:key/nodes``), which is also how the tests run.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

API = "https://api.figma.com/v1"
TOKEN_HELP = ("Paste a Figma personal access token in Settings: in Figma open Settings > Security > Personal access tokens, "
              "create one with the 'File content: read' scope and paste it here. It is kept in the app's data folder only.")


def token_path(data_dir: Path) -> Path:
    return Path(data_dir) / "figma-token"


def read_token(data_dir: Path) -> str:
    try:
        return token_path(data_dir).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_token(data_dir: Path, value: str) -> None:
    p = token_path(data_dir)
    value = (value or "").strip()
    if not value:
        p.unlink(missing_ok=True)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(value, encoding="utf-8")


def parse_link(link: str) -> tuple[str, Optional[str]]:
    """(file key, node id) from a Figma link (``/design/<key>/...?node-id=12-34`` or ``/file/<key>``) or ``key`` / ``key:node``."""
    link = (link or "").strip()
    m = re.search(r"figma\.com/(?:design|file|proto|board)/([A-Za-z0-9]{10,})", link)
    if m:
        key = m.group(1)
        n = re.search(r"[?&]node-id=([0-9]+[-:%3A]+[0-9]+)", link)
        node = re.sub(r"-|%3A", ":", n.group(1)) if n else None
        return key, node
    m = re.fullmatch(r"([A-Za-z0-9]{10,})(?::([0-9]+[:-][0-9]+))?", link)
    if m:
        return m.group(1), (m.group(2).replace("-", ":") if m.group(2) else None)
    raise ValueError("Not a Figma link: expected https://www.figma.com/design/<key>/...?node-id=12-34")


# ---------------------------------------------------------------------------- reduce a node tree to a compact spec

def _rgba(c: dict, opacity: float = 1.0) -> str:
    r, g, b = (int(round(float(c.get(k, 0)) * 255)) for k in ("r", "g", "b"))
    a = round(float(c.get("a", 1)) * opacity, 3)
    return f"#{r:02x}{g:02x}{b:02x}" if a >= 0.999 else f"rgba({r}, {g}, {b}, {a:g})"


def _paint(fills: list, *, text: bool = False) -> dict[str, str]:
    out: dict[str, str] = {}
    layers = []
    for f in reversed([f for f in (fills or []) if f.get("visible", True)]):
        op = float(f.get("opacity", 1))
        if f.get("type") == "SOLID":
            layers.append(_rgba(f.get("color") or {}, op))
        elif str(f.get("type", "")).startswith("GRADIENT_"):
            stops = ", ".join(f"{_rgba(s.get('color') or {}, op)} {round(float(s.get('position', 0)) * 100)}%" for s in f.get("gradientStops") or [])
            kind = "radial-gradient(circle" if "RADIAL" in f["type"] else "linear-gradient(180deg"
            layers.append(f"{kind}, {stops})")
        elif f.get("type") == "IMAGE":
            out["image"] = "1"
    if not layers:
        return out
    if text:
        out["color"] = layers[-1] if not layers[-1].startswith(("linear", "radial")) else "#222222"
    elif len(layers) == 1 and not layers[0].startswith(("linear", "radial")):
        out["background-color"] = layers[0]
    else:
        out["background"] = ", ".join(l if l.startswith(("linear", "radial")) else f"linear-gradient({l}, {l})" for l in reversed(layers))
    return out


def _effects(effects: list) -> dict[str, str]:
    shadows, out = [], {}
    for e in effects or []:
        if not e.get("visible", True):
            continue
        if e.get("type") in ("DROP_SHADOW", "INNER_SHADOW"):
            o = e.get("offset") or {}
            shadows.append(f"{'inset ' if e['type'] == 'INNER_SHADOW' else ''}{o.get('x', 0):g}px {o.get('y', 0):g}px {e.get('radius', 0):g}px "
                           f"{e.get('spread', 0):g}px {_rgba(e.get('color') or {})}")
        elif e.get("type") == "LAYER_BLUR":
            out["filter"] = f"blur({e.get('radius', 0):g}px)"
        elif e.get("type") == "BACKGROUND_BLUR":
            out["backdrop-filter"] = f"blur({e.get('radius', 0):g}px)"
    if shadows:
        out["box-shadow"] = ", ".join(shadows)
    return out


def _stroke(n: dict) -> dict[str, str]:
    strokes = [s for s in n.get("strokes") or [] if s.get("visible", True) and s.get("type") == "SOLID"]
    w = n.get("strokeWeight") or 0
    if not strokes or not w:
        return {}
    col = _rgba(strokes[0].get("color") or {}, float(strokes[0].get("opacity", 1)))
    ind = n.get("individualStrokeWeights")
    if ind:
        return {f"border-{side}": f"{ind.get(side, 0):g}px solid {col}" for side in ("top", "right", "bottom", "left") if ind.get(side)}
    return {"border": f"{w:g}px solid {col}"}


def _radius(n: dict) -> dict[str, str]:
    rr = n.get("rectangleCornerRadii")
    if rr and any(rr):
        return {"border-radius": " ".join(f"{v:g}px" for v in rr)}
    if n.get("cornerRadius"):
        return {"border-radius": f"{n['cornerRadius']:g}px"}
    if n.get("type") == "ELLIPSE":
        return {"border-radius": "50%"}
    return {}


_CASE = {"UPPER": "uppercase", "LOWER": "lowercase", "TITLE": "capitalize"}
_TALIGN = {"LEFT": "left", "CENTER": "center", "RIGHT": "right", "JUSTIFIED": "justify"}


def _text_style(s: dict) -> dict[str, str]:
    out = {}
    if s.get("fontFamily"):
        out["font-family"] = f"'{s['fontFamily']}', system-ui, sans-serif"
    if s.get("fontWeight"):
        out["font-weight"] = f"{int(s['fontWeight'])}"
    if s.get("fontSize"):
        out["font-size"] = f"{s['fontSize']:g}px"
    if s.get("lineHeightPx"):
        out["line-height"] = f"{round(float(s['lineHeightPx']), 2):g}px"
    if s.get("letterSpacing"):
        out["letter-spacing"] = f"{round(float(s['letterSpacing']), 2):g}px"
    if s.get("italic"):
        out["font-style"] = "italic"
    if s.get("textCase") in _CASE:
        out["text-transform"] = _CASE[s["textCase"]]
    if s.get("textAlignHorizontal") in _TALIGN:
        out["text-align"] = _TALIGN[s["textAlignHorizontal"]]
    if s.get("textDecoration") == "UNDERLINE":
        out["text-decoration"] = "underline"
    return out


_JUSTIFY = {"MIN": "flex-start", "CENTER": "center", "MAX": "flex-end", "SPACE_BETWEEN": "space-between"}
_ALIGN = {"MIN": "flex-start", "CENTER": "center", "MAX": "flex-end", "BASELINE": "baseline"}
MAX_NODES = 1500


class _Styles:
    """Identical style dicts collapse into one named id (``fill_1``, ``text_2``...)."""

    def __init__(self) -> None:
        self.by_key: dict[str, str] = {}
        self.styles: dict[str, dict[str, str]] = {}
        self.uses: dict[str, int] = {}

    def ref(self, kind: str, decls: dict[str, str]) -> Optional[str]:
        if not decls:
            return None
        key = kind + json.dumps(decls, sort_keys=True)
        sid = self.by_key.get(key)
        if sid is None:
            sid = f"{kind}_{sum(1 for k in self.styles if k.startswith(kind + '_')) + 1}"
            self.by_key[key] = sid
            self.styles[sid] = decls
        self.uses[sid] = self.uses.get(sid, 0) + 1
        return sid


def _layout(n: dict) -> Optional[dict[str, Any]]:
    mode = n.get("layoutMode")
    if mode not in ("HORIZONTAL", "VERTICAL"):
        return None
    pad = [n.get(k, 0) or 0 for k in ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft")]
    return {"mode": "row" if mode == "HORIZONTAL" else "column", "gap": n.get("itemSpacing", 0) or 0, "padding": pad,
            "justify": _JUSTIFY.get(n.get("primaryAxisAlignItems") or "MIN", "flex-start"),
            "align": _ALIGN.get(n.get("counterAxisAlignItems") or "MIN", "flex-start"), "wrap": n.get("layoutWrap") == "WRAP"}


def reduce(document: dict, *, name: str = "") -> dict[str, Any]:
    """A Figma node (``document`` of a /nodes answer) -> {name, width, height, root, styles, counts}."""
    styles = _Styles()
    bb = document.get("absoluteBoundingBox") or {}
    ox, oy = float(bb.get("x", 0)), float(bb.get("y", 0))
    count = [0]

    def walk(n: dict, parent_layout: Optional[dict]) -> Optional[dict[str, Any]]:
        if not n.get("visible", True) or count[0] >= MAX_NODES:
            return None
        count[0] += 1
        b = n.get("absoluteBoundingBox") or {}
        node: dict[str, Any] = {"id": n.get("id"), "name": n.get("name", ""), "type": n.get("type"),
                                "box": [round(float(b.get("x", ox)) - ox, 1), round(float(b.get("y", oy)) - oy, 1),
                                        round(float(b.get("width", 0)), 1), round(float(b.get("height", 0)), 1)]}
        lay = _layout(n)
        if lay:
            node["layout"] = lay
        if parent_layout and n.get("layoutPositioning") != "ABSOLUTE":
            node["sizing"] = {"h": (n.get("layoutSizingHorizontal") or "FIXED").lower(), "v": (n.get("layoutSizingVertical") or "FIXED").lower(),
                              "grow": n.get("layoutGrow", 0) or 0, "stretch": n.get("layoutAlign") == "STRETCH"}
        else:
            node["absolute"] = True
        refs = []
        is_text = n.get("type") == "TEXT"
        paint = _paint(n.get("fills") or [], text=is_text)
        if paint.pop("image", None):
            node["image"] = True
        refs.append(styles.ref("text" if is_text else "fill", {**paint, **(_text_style(n.get("style") or {}) if is_text else {})}))
        refs.append(styles.ref("stroke", _stroke(n)))
        refs.append(styles.ref("effect", _effects(n.get("effects") or [])))
        refs.append(styles.ref("radius", _radius(n)))
        if n.get("opacity") is not None and float(n["opacity"]) < 0.999:
            node["opacity"] = round(float(n["opacity"]), 3)
        if n.get("clipsContent"):
            node["clip"] = True
        node["style"] = [r for r in refs if r]
        if is_text:
            node["text"] = n.get("characters", "")
        kids = [walk(c, lay) for c in n.get("children") or []]
        kids = [k for k in kids if k]
        if kids:
            node["children"] = kids
        return node

    root = walk(document, None) or {}
    root.pop("absolute", None)
    return {"name": name or document.get("name", ""), "node_id": document.get("id"), "width": round(float(bb.get("width", 0))),
            "height": round(float(bb.get("height", 0))), "root": root, "styles": styles.styles,
            "counts": {"nodes": count[0], "styles": len(styles.styles), "style_uses": sum(styles.uses.values()), "truncated": count[0] >= MAX_NODES}}


# ---------------------------------------------------------------------------- spec -> HTML/CSS

def _node_css(node: dict, parent: Optional[dict]) -> dict[str, str]:
    x, y, w, h = node["box"]
    css: dict[str, str] = {}
    lay = node.get("layout")
    if lay:
        css.update({"display": "flex", "flex-direction": lay["mode"], "gap": f"{lay['gap']:g}px", "justify-content": lay["justify"],
                    "align-items": lay["align"], "padding": " ".join(f"{v:g}px" for v in lay["padding"])})
        if lay["wrap"]:
            css["flex-wrap"] = "wrap"
    if parent is None:
        css.update({"position": "relative", "width": f"{w:g}px", "min-height": f"{h:g}px", "margin": "0 auto"})
    elif node.get("absolute"):
        px_, py_ = parent["box"][0], parent["box"][1]
        css.update({"position": "absolute", "left": f"{x - px_:g}px", "top": f"{y - py_:g}px", "width": f"{w:g}px", "height": f"{h:g}px"})
    else:
        s = node.get("sizing") or {}
        row = (parent.get("layout") or {}).get("mode") == "row"
        main, cross = ("h", "v") if row else ("v", "h")
        dim = {"h": ("width", w), "v": ("height", h)}
        for axis in ("h", "v"):
            prop, val = dim[axis]
            mode = s.get(axis, "fixed")
            if mode == "fixed":
                css[prop] = f"{val:g}px"
            elif mode == "fill":
                if axis == main:
                    css["flex"] = "1 1 0"
                    css["min-" + prop] = "0"
                else:
                    css["align-self"] = "stretch"
        if s.get("grow") and "flex" not in css:
            css["flex-grow"] = "1"
        if s.get("stretch"):
            css["align-self"] = "stretch"
        if "flex" not in css:
            css["flex-shrink"] = "0"
    if node.get("children") and any(c.get("absolute") for c in node["children"]) and "position" not in css:
        css["position"] = "relative"
    if node.get("opacity") is not None:
        css["opacity"] = f"{node['opacity']:g}"
    if node.get("clip"):
        css["overflow"] = "hidden"
    if node.get("type") == "TEXT":
        css["white-space"] = "pre-wrap"
        css["margin"] = "0"
    if node.get("image"):
        css.setdefault("background-color", "#d9d9d9")
    return css


def _decls(d: dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in d.items())


def to_html(spec: dict) -> str:
    rules: list[str] = [f".{sid.replace('_', '-')} {{ {_decls(d)} }}" for sid, d in spec["styles"].items()]
    body: list[str] = []
    families = set()
    for d in spec["styles"].values():
        if d.get("font-family"):
            families.add(d["font-family"].split(",")[0].strip("' "))
    counter = [0]

    def emit(node: dict, parent: Optional[dict], depth: int) -> None:
        counter[0] += 1
        nid = f"n{counter[0]}"
        rules.append(f"#{nid} {{ {_decls(_node_css(node, parent))} }}")
        classes = " ".join(s.replace("_", "-") for s in node.get("style") or [])
        pad = "  " * depth
        label = html_lib.escape(node.get("name") or "", quote=True)
        if node.get("type") == "TEXT":
            tag = "p"
            body.append(f'{pad}<{tag} id="{nid}" class="{classes}" data-figma="{label}">{html_lib.escape(node.get("text") or "")}</{tag}>')
            return
        aria = ' role="img" aria-label="' + label + '"' if node.get("image") else ""
        body.append(f'{pad}<div id="{nid}" class="{classes}" data-figma="{label}"{aria}>')
        for c in node.get("children") or []:
            emit(c, node, depth + 1)
        body.append(f"{pad}</div>")

    if spec.get("root"):
        emit(spec["root"], None, 1)
    fonts = ""
    if families:
        q = "&".join("family=" + re.sub(r"\s+", "+", f) + ":wght@300;400;500;600;700;800" for f in sorted(families))
        fonts = f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{q}&display=swap">\n'
    title = html_lib.escape(spec.get("name") or "Figma frame")
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{title}</title>\n{fonts}<style>\n*, *::before, *::after {{ box-sizing: border-box; }}\n"
            "body { margin: 0; font-family: system-ui, sans-serif; }\n" + "\n".join(rules) + "\n</style>\n</head>\n<body>\n"
            + "\n".join(body) + "\n</body>\n</html>\n")


# ---------------------------------------------------------------------------- the REST API

def _get(path: str, token: str, params: dict[str, Any], timeout: float = 40.0) -> dict[str, Any]:
    import httpx
    r = httpx.get(f"{API}{path}", params=params, headers={"X-Figma-Token": token}, timeout=timeout)
    if r.status_code in (401, 403):
        raise PermissionError("Figma refused the token (401/403): check it in Settings and that it can read this file.")
    if r.status_code == 404:
        raise LookupError("Figma has no such file or frame (404): check the link and the node-id.")
    r.raise_for_status()
    return r.json()


def fetch_frame(token: str, key: str, node: Optional[str]) -> tuple[dict, str]:
    """(the node's document, the file name). Without a node-id the first frame of the first page is used."""
    if not node:
        data = _get(f"/files/{key}", token, {"depth": 2})
        pages = (data.get("document") or {}).get("children") or []
        frames = [c for p in pages for c in p.get("children") or [] if c.get("type") in ("FRAME", "COMPONENT", "SECTION")]
        if not frames:
            raise LookupError("The file has no top-level frame; copy a link to a frame (it carries ?node-id=).")
        node = frames[0]["id"]
    data = _get(f"/files/{key}/nodes", token, {"ids": node})
    return document_of(data, node), data.get("name", "")


def document_of(data: dict, node: Optional[str] = None) -> dict:
    nodes = data.get("nodes") or {}
    if not nodes:
        if data.get("document"):
            return data["document"]
        raise ValueError("This JSON has no 'nodes' (expected the answer of GET /v1/files/:key/nodes).")
    entry = nodes.get(node) if node else None
    entry = entry or next(iter(nodes.values()))
    if not entry or not entry.get("document"):
        raise LookupError("The frame is empty or not visible to this token.")
    return entry["document"]


def fetch_image(token: str, key: str, node: str, scale: float = 1.0) -> bytes:
    import httpx
    data = _get(f"/images/{key}", token, {"ids": node, "format": "png", "scale": scale})
    url = (data.get("images") or {}).get(node)
    if not url:
        raise LookupError("Figma did not render an image of this frame.")
    r = httpx.get(url, timeout=60.0)
    r.raise_for_status()
    return r.content


# ---------------------------------------------------------------------------- tokens from the spec

def tokens_brief(spec: dict) -> dict[str, Any]:
    """A tokens_generate brief from the frame: the most used saturated fill as the hue, the text families as fonts."""
    from .tokens import hex_to_oklch
    fills: dict[str, int] = {}
    families: dict[str, int] = {}
    radii: list[float] = []

    def walk(n: dict) -> None:
        for sid in n.get("style") or []:
            d = spec["styles"].get(sid) or {}
            for k in ("background-color", "color"):
                v = d.get(k, "")
                if re.fullmatch(r"#[0-9a-f]{6}", v):
                    fills[v] = fills.get(v, 0) + 1
            if d.get("font-family"):
                fam = d["font-family"].split(",")[0].strip("' ")
                families[fam] = families.get(fam, 0) + max(1, len(n.get("text") or ""))
            if d.get("border-radius", "").endswith("px") and " " not in d["border-radius"]:
                radii.append(float(d["border-radius"][:-2]))
        for c in n.get("children") or []:
            walk(c)
    walk(spec.get("root") or {})
    chroma = sorted(((hex_to_oklch(h)[1], n, h) for h, n in fills.items()), key=lambda t: (-(t[0] > 0.06) * t[1], -t[0]))
    accent = next((h for c, n, h in chroma if c > 0.06), None)
    fams = [f for f, _ in sorted(families.items(), key=lambda kv: -kv[1])]
    brief: dict[str, Any] = {"name": f"Figma: {spec.get('name') or 'frame'}"[:80]}
    if accent:
        brief["base_color"] = accent
    if fams:
        heading = fams[1] if len(fams) > 1 else fams[0]
        brief["fonts"] = {"heading": f"'{heading}', system-ui, sans-serif", "body": f"'{fams[0]}', system-ui, sans-serif"}
    med = sorted(radii)[len(radii) // 2] if radii else 8
    brief["style"] = "sharp" if med <= 4 else "pill" if med >= 16 else "soft"
    return brief


# ---------------------------------------------------------------------------- the import

def store_dir(data_dir: Path) -> Path:
    d = Path(data_dir) / "figma"
    d.mkdir(parents=True, exist_ok=True)
    return d


CAPTURE_VIEWPORT_H = 900   # the viewport height browser.capture shoots every width with


def _viewport_fill(img, start: int) -> int:
    """Rows from `start` to the bottom when they are all one flat colour (else 0)."""
    if start <= 0 or start >= img.height:
        return 0
    extrema = img.crop((0, start, img.width, img.height)).getextrema()
    return img.height - start if all(lo == hi for lo, hi in extrema) else 0


def _diff(png_a: Path, png_b: Path, out: Path, *, viewport_fill_from: Optional[int] = None) -> dict[str, Any]:
    """Pixel difference of the frame's PNG (a) and the render (b) over the whole canvas of both.

    `diff_pct` counts the rows only one image has (a truncated render, an extra footer) as different, so a partial match
    never reads 0 %. `scope` is full (same size), normalized (render scaled to the frame width, heights then equal) or
    partial (heights differ); sizes, scale, compared rectangle, coverage and the in-overlap difference are reported.
    """
    try:
        from PIL import Image, ImageChops
    except Exception:  # noqa: BLE001
        return {"diff_pct": None, "error": "Pillow not available"}
    a, b = Image.open(png_a).convert("RGB"), Image.open(png_b).convert("RGB")
    reference_size, render_size = [a.width, a.height], [b.width, b.height]
    # A page shorter than the capture viewport is padded to the viewport height with the empty canvas. The caller passes
    # viewport_fill_from (the frame height) only for such a capture; flat rows below it are that padding, not page
    # content, and are dropped (reported as viewport_fill_rows). Anything drawn there keeps counting as extra rows.
    fill = _viewport_fill(b, viewport_fill_from) if viewport_fill_from else 0
    if fill:
        b = b.crop((0, 0, b.width, b.height - fill))
    scale = 1.0
    if b.width != a.width:
        # Declared normalisation: the render is resized to the frame's width (aspect kept) before comparing.
        scale = a.width / b.width
        b = b.resize((a.width, max(1, round(b.height * scale))), Image.LANCZOS)
    w, h = a.width, max(a.height, b.height)          # the canvas covers both images
    oh = min(a.height, b.height)                     # rows present in both (widths are equal now)
    d = ImageChops.difference(a.crop((0, 0, w, oh)), b.crop((0, 0, w, oh)))
    differing = sum(d.convert("L").histogram()[24:])
    unmatched = w * (h - oh)                         # rows only one image has: missing or extra content, all different
    canvas = Image.new("RGB", (w, h), (255, 0, 255))
    canvas.paste(d, (0, 0))
    canvas.save(out)
    area = w * h
    scope = "partial" if oh < h else ("normalized" if scale != 1.0 or fill else "full")
    steps = ([f"{fill} flat viewport-padding rows below the frame height dropped"] if fill else []) + \
        ([f"render resized x{scale:.4g} to the frame width {a.width}px"] if scale != 1.0 else [])
    return {
        "diff_pct": round(100.0 * (differing + unmatched) / area, 2) if area else None,
        "overlap_diff_pct": round(100.0 * differing / (w * oh), 2) if w * oh else None,
        "diff_image": str(out), "width": w, "height": h,
        "reference_size": reference_size, "render_size": render_size, "render_compared_size": [b.width, b.height],
        "render_scale": round(scale, 4), "viewport_fill_rows": fill,
        "normalization": "; ".join(steps) or None,
        "compared_rect": [0, 0, w, oh], "coverage": round(oh / h, 4) if h else 0.0,
        "missing_rows": a.height - oh, "extra_rows": b.height - oh,
        "scope": scope,
        "note": "Pixel measure only, not semantic equivalence. Rows that only one image has count as different "
                "(magenta in diff.png).",
    }


def import_frame(svc, *, link: Optional[str] = None, nodes_json: Optional[dict] = None, image_png: Optional[bytes] = None,
                 make_tokens: bool = True, critique: bool = True, use_vision: bool = False) -> dict[str, Any]:
    """Import one frame into a design project: spec + HTML (+ render, design system, Figma image, pixel diff, critique)."""
    t0 = time.monotonic()
    data_dir = Path(svc.config.data_dir)
    key, node = (parse_link(link) if link else (None, None))
    file_name = ""
    if nodes_json is not None:
        document = document_of(nodes_json, node)
        file_name = nodes_json.get("name", "")
    else:
        token = read_token(data_dir)
        if not token:
            raise PermissionError(TOKEN_HELP)
        if not key:
            raise ValueError("Give the link of a Figma frame.")
        document, file_name = fetch_frame(token, key, node)
        node = node or document.get("id")
        if image_png is None:
            try:
                image_png = fetch_image(token, key, node)
            except Exception:  # noqa: BLE001 — the comparison is optional; the import stands without it
                image_png = None
    spec = reduce(document, name=document.get("name", ""))
    page = to_html(spec)
    import_id = uuid.uuid4().hex[:12]
    folder = store_dir(data_dir) / import_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "page.html").write_text(page, encoding="utf-8")
    width = max(320, min(2560, int(spec.get("width") or 1440)))
    # A frame is drawn for one width: render it at that width (a phone capture of a desktop frame only measures the overflow).
    render = svc.render(html=page, widths=[width], full_page=True, title=f"figma: {spec['name']}"[:120])
    out: dict[str, Any] = {"import_id": import_id, "file": file_name, "file_key": key, "node_id": spec.get("node_id"), "name": spec["name"],
                           "width": spec["width"], "height": spec["height"], "counts": spec["counts"], "styles": spec["styles"],
                           "html_path": str(folder / "page.html"), "spec_path": str(folder / "spec.json"), "render_id": render["id"],
                           "lint_score": (render.get("lint") or {}).get("score")}
    if make_tokens:
        tok = svc.tokens_generate(tokens_brief(spec))
        out["tokens_id"] = tok["id"]
    if image_png:
        fig = folder / "figma.png"
        fig.write_bytes(image_png)
        out["figma_image"] = str(fig)
        entry = next((f for f in render.get("files") or [] if f["width"] == width), None)
        shot = Path(entry["path"]) if entry else None
        if shot and shot.is_file():
            # browser.capture shoots at least one 900px viewport: a shorter frame gets padding rows below its height.
            frame_h = int(round(float(spec.get("height") or 0)))
            padded = entry.get("full_page") and int(entry.get("h") or 0) == CAPTURE_VIEWPORT_H and 0 < frame_h < CAPTURE_VIEWPORT_H
            out["compare"] = _diff(fig, shot, folder / "diff.png", viewport_fill_from=frame_h if padded else None)
    if critique and not (render.get("metrics") or {}).get("error"):
        try:
            c = svc.critique_render(render["id"], use_vision=use_vision, tokens_id=out.get("tokens_id"))
            out["critique"] = {"score": c.get("score"), "gate": (c.get("gate") or {}).get("state"), "findings": len(c.get("findings") or [])}
        except Exception as exc:  # noqa: BLE001
            out["critique"] = {"error": str(exc)[:200]}
    meta = {k: v for k, v in out.items() if k != "styles"}
    meta["created_ts"] = time.time()
    (folder / "import.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    out["ms"] = round((time.monotonic() - t0) * 1000)
    return out


def imports(data_dir: Path, limit: int = 30) -> list[dict[str, Any]]:
    rows = []
    for p in sorted(store_dir(data_dir).glob("*/import.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            rows.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return rows


def import_file(data_dir: Path, import_id: str, name: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", import_id or "") or name not in ("page.html", "spec.json", "figma.png", "diff.png"):
        raise PermissionError("not an import file")
    return store_dir(data_dir) / import_id / name
