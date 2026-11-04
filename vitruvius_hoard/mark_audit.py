"""Mark (logo) audit: how a logo holds up in one colour, on light and dark grounds, small, and as a favicon or avatar.

Deterministic and local: Pillow and numpy measure the image, nothing is sent anywhere. The score is 100 minus 25 per
failed check, 8 per warning and 1 per note. `test_sheet` draws the same mark on light, dark and grey grounds, in one
colour, inverted and at 128/64/32/16 px, so a person sees what the numbers say. The checklist idea comes from the
logo-design-skill notes (ideas only; no code taken). Reports, the normalised mark and the sheet live in data/marks/<id>/.
"""

from __future__ import annotations

import base64
import io
import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PENALTY = {"fail": 25, "warn": 8, "note": 1, "pass": 0}
LIGHT = (255, 255, 255)
DARK = (17, 17, 17)
GREY = (122, 122, 122)
MAX_SIDE = 1024
MAX_BYTES = 15 * 1024 * 1024
ID_RE = re.compile(r"^[0-9a-f]{12}$")
HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


class MarkError(ValueError):
    """A mark that cannot be read (missing file, not an image, SVG without a browser)."""


def _marks_dir(data_dir: Path) -> Path:
    path = Path(data_dir) / "marks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_source(*, path: Optional[str] = None, data: Optional[str] = None, svg: Optional[str] = None) -> tuple[bytes, str, str]:
    """Exactly one of path / data (base64 or data: URL) / svg (markup) -> (bytes, "svg" | "raster", name)."""
    given = [x for x in (path, data, svg) if x]
    if len(given) != 1:
        raise MarkError("Pasa exactamente una fuente: path, data o svg.")
    if path:
        file = Path(path).expanduser()
        if not file.is_file():
            raise MarkError(f"No existe el archivo {path}.")
        if file.stat().st_size > MAX_BYTES:
            raise MarkError("La imagen pasa de 15 MB.")
        raw, name = file.read_bytes(), file.name
    elif data:
        match = re.match(r"^data:[\w/+.-]+;base64,(.*)$", data.strip(), re.S)
        try:
            raw = base64.b64decode(match.group(1) if match else data.strip(), validate=False)
        except Exception as error:  # noqa: BLE001 - any decoding problem is the same answer
            raise MarkError("data no es base64 válido.") from error
        name = "subida"
    else:
        raw, name = svg.encode("utf-8"), "marca.svg"
    head = raw[:4096].lstrip().lower()
    kind = "svg" if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head) else "raster"
    return raw, kind, name


def _rasterize_svg(raw: bytes, browser: Any, out_dir: Path) -> Image.Image:
    """Draw an SVG at 512 px on white through the local browser worker; white then reads as background."""
    if browser is None:
        raise MarkError("Para un SVG hace falta el navegador local de Vitruvius; sube un PNG o arranca el navegador.")
    src = "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii")
    html = ('<!doctype html><html><body style="margin:0;background:#fff">'
            f'<img src="{src}" style="display:block;width:512px;height:512px;object-fit:contain"></body></html>')
    result = browser.capture(html=html, widths=[512], full_page=False, wait_ms=200, out_dir=out_dir / "svg")
    if not isinstance(result, dict) or result.get("error"):
        hint = (result or {}).get("hint") if isinstance(result, dict) else ""
        raise MarkError(f"No pude dibujar el SVG: {(result or {}).get('error') if isinstance(result, dict) else result} {hint or ''}".strip())
    files = result.get("files") or result.get("screenshots") or []
    shot = next((f.get("path") for f in files if isinstance(f, dict) and f.get("path")), None)
    if not shot or not Path(shot).is_file():
        raise MarkError("El navegador no devolvió la imagen del SVG.")
    with Image.open(shot) as img:
        rgb = img.convert("RGB").crop((0, 0, 512, 512))
    arr = np.asarray(rgb).astype(np.float32)
    dist = (255.0 - arr).max(axis=2)
    alpha = np.clip(dist / 48.0, 0.0, 1.0) * 255.0
    return Image.fromarray(np.dstack([arr, alpha]).astype(np.uint8), "RGBA")


def _load_raster(raw: bytes) -> tuple[Image.Image, str]:
    """-> (RGBA image at most MAX_SIDE, background) with background "transparent", "removed" (a flat ground was cut
    out by colour distance) or "opaque" (no flat ground: the whole picture counts as the mark)."""
    try:
        img = Image.open(io.BytesIO(raw))
        img.seek(0)
        img.load()
    except Exception as error:  # noqa: BLE001 - Pillow raises many kinds for a non-image
        raise MarkError("No es una imagen que se pueda leer (PNG, JPG, WebP, GIF, BMP, ICO o SVG).") from error
    rgba = img.convert("RGBA")
    if max(rgba.size) > MAX_SIDE:
        rgba.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    arr = np.asarray(rgba).astype(np.float32)
    if (arr[:, :, 3] < 250).mean() > 0.01:
        return rgba, "transparent"
    border = np.concatenate([arr[0, :, :3], arr[-1, :, :3], arr[:, 0, :3], arr[:, -1, :3]])
    ground = np.median(border, axis=0)
    if np.abs(border - ground).max(axis=1).mean() > 18:
        return rgba, "opaque"
    dist = np.abs(arr[:, :, :3] - ground).max(axis=2)
    arr[:, :, 3] = np.clip((dist - 10.0) / 38.0, 0.0, 1.0) * 255.0
    return Image.fromarray(arr.astype(np.uint8), "RGBA"), "removed"


def _square(mark: Image.Image, side: int, pad: float = 0.08) -> Image.Image:
    """The cropped mark centred on a transparent square of `side` px with `pad` margin."""
    inner = max(1, int(round(side * (1 - 2 * pad))))
    copy = mark.copy()
    copy.thumbnail((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(copy, ((side - copy.width) // 2, (side - copy.height) // 2), copy)
    return canvas


def _alpha(img: Image.Image) -> np.ndarray:
    return np.asarray(img.getchannel("A")).astype(np.float32) / 255.0


def _on(img: Image.Image, ground: tuple[int, int, int]) -> Image.Image:
    base = Image.new("RGBA", img.size, ground + (255,))
    base.alpha_composite(img)
    return base.convert("RGB")


def _mono(img: Image.Image, colour: tuple[int, int, int]) -> Image.Image:
    solid = Image.new("RGBA", img.size, colour + (255,))
    solid.putalpha(img.getchannel("A"))
    return solid


def _edge_count(img: Image.Image) -> int:
    edges = np.asarray(img.convert("RGB").filter(ImageFilter.FIND_EDGES)).max(axis=2)
    return int((edges > 40).sum())


def _luminance(rgb: tuple[float, float, float]) -> float:
    def lin(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def _palette(mark: Image.Image) -> list[dict[str, Any]]:
    """Colours that cover at least 2 % of the solid pixels (anti-aliased edges ignored), largest first."""
    arr = np.asarray(mark).reshape(-1, 4)
    solid = arr[arr[:, 3] > 230][:, :3]
    if not len(solid):
        return []
    if len(solid) > 60000:
        solid = solid[np.linspace(0, len(solid) - 1, 60000).astype(int)]
    strip = Image.fromarray(solid.reshape(1, -1, 3).astype(np.uint8), "RGB")
    quant = strip.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    pal = quant.getpalette()[: 8 * 3]
    counts = np.bincount(np.asarray(quant).ravel(), minlength=8)
    shades = []
    for idx, count in enumerate(counts):
        share = count / counts.sum()
        if share >= 0.02:
            shades.append({"rgb": tuple(pal[idx * 3: idx * 3 + 3]), "share": float(share)})
    # Shades of one hue (a gradient, a shadow) are one colour family: join shades that are close, chaining through the ramp.
    families: list[list[dict[str, Any]]] = []
    for shade in sorted(shades, key=lambda s: -s["share"]):
        near = [f for f in families if any(max(abs(a - b) for a, b in zip(shade["rgb"], m["rgb"])) <= 40 for m in f)]
        if near:
            near[0].append(shade)
            for other in near[1:]:
                near[0].extend(other)
                families.remove(other)
        else:
            families.append([shade])
    rows = []
    for fam in families:
        top = max(fam, key=lambda s: s["share"])
        r, g, b = top["rgb"]
        rows.append({"hex": f"#{r:02x}{g:02x}{b:02x}", "rgb": (r, g, b), "share": round(sum(s["share"] for s in fam), 3), "shades": len(fam)})
    return sorted(rows, key=lambda r: -r["share"])


def _check(cid: str, title: str, status: str, detail: str, value: Any = None) -> dict[str, Any]:
    return {"id": cid, "title": title, "status": status, "detail": detail, "value": value}


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return 1.0 if union == 0 else float(np.logical_and(a, b).sum() / union)


def _small_iou(square: Image.Image, size: int, ref: int = 128) -> float:
    """How much of the silhouette survives being drawn at `size` px (intersection over union, 1 = intact)."""
    big = square.resize((ref, ref), Image.LANCZOS)
    base = _alpha(big) > 0.5
    small = big.getchannel("A").resize((size, size), Image.BOX).resize((ref, ref), Image.BILINEAR)
    return round(_iou(base, np.asarray(small) > 127), 3)


def analyse(rgba: Image.Image, background: str, kind: str = "raster") -> tuple[list[dict[str, Any]], dict[str, Any], Image.Image]:
    """-> (checks, metrics, cropped mark). Every check is pass / note / warn / fail with a sentence in Spanish."""
    alpha = _alpha(rgba)
    ys, xs = np.nonzero(alpha > 0.125)
    if not len(xs):
        raise MarkError("La imagen está vacía: no hay nada que no sea fondo.")
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    mark = rgba.crop((x0, y0, x1, y1))
    square = _square(mark, 256)
    palette = _palette(mark)
    checks: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {"canvas": [rgba.width, rgba.height], "bbox": [x0, y0, x1, y1], "background": background,
                               "palette": [{"hex": p["hex"], "share": p["share"], "shades": p["shades"]} for p in palette]}

    if background == "opaque":
        checks.append(_check("background", "Fondo", "warn", "No hay transparencia ni un fondo liso que separar: se mide la imagen entera como marca. Sube la versión con fondo transparente o en SVG."))
    elif background == "removed":
        checks.append(_check("background", "Fondo", "note", "Fondo liso, no transparente: se ha separado por color. Conviene tener la versión con transparencia."))
    else:
        checks.append(_check("background", "Fondo", "pass", "Vector." if kind == "svg" else "Fondo transparente."))

    colour_edges = _edge_count(_on(square, LIGHT))
    mono_edges = _edge_count(_on(_mono(square, (0, 0, 0)), LIGHT))
    ratio = 1.0 if len(palette) <= 1 or colour_edges == 0 else round(min(1.0, mono_edges / colour_edges), 3)
    metrics["one_colour_ratio"] = ratio
    status = "fail" if ratio < 0.45 else "warn" if ratio < 0.7 else "pass"
    checks.append(_check("one_colour", "Un solo color", status, {
        "fail": "En un color se pierde la mayor parte del dibujo: las partes solo se distinguen por el color. Separa las formas con huecos o contornos.",
        "warn": "En un color se pierde parte del dibujo interior; revisa la versión monocroma.",
        "pass": "Se sostiene en un solo color."}[status], ratio))

    solid = np.asarray(mark).reshape(-1, 4)
    solid = solid[solid[:, 3] > 230][:, :3]
    dominant = tuple(palette[0]["rgb"]) if palette else tuple(float(v) for v in (solid.mean(axis=0) if len(solid) else (0, 0, 0)))
    on_light, on_dark = contrast(dominant, LIGHT), contrast(dominant, DARK)
    metrics["contrast"] = {"dominant": "#%02x%02x%02x" % tuple(int(v) for v in dominant), "on_light": on_light, "on_dark": on_dark}
    if max(on_light, on_dark) < 3:
        checks.append(_check("contrast", "Contraste", "fail", f"El color principal se pierde en fondo claro ({on_light}:1) y oscuro ({on_dark}:1); necesita al menos 3:1 en uno.", [on_light, on_dark]))
    elif on_light < 3:
        checks.append(_check("contrast", "Contraste", "note", f"Sobre fondo claro solo da {on_light}:1: hace falta la versión invertida u oscura para fondos claros.", [on_light, on_dark]))
    elif on_dark < 3:
        checks.append(_check("contrast", "Contraste", "note", f"Sobre fondo oscuro solo da {on_dark}:1: hace falta la versión invertida (clara) para fondos oscuros.", [on_light, on_dark]))
    else:
        checks.append(_check("contrast", "Contraste", "pass", f"Funciona sobre claro ({on_light}:1) y oscuro ({on_dark}:1).", [on_light, on_dark]))

    i32, i16 = _small_iou(square, 32), _small_iou(square, 16)
    metrics["small"] = {"iou_32": i32, "iou_16": i16}
    s32 = "fail" if i32 < 0.75 else "warn" if i32 < 0.85 else "pass"
    checks.append(_check("small_32", "A 32 px", s32, {
        "fail": f"A 32 px se deshace (queda el {round(i32 * 100)} % de la forma): trazos o huecos demasiado finos.",
        "warn": f"A 32 px pierde detalle (queda el {round(i32 * 100)} %); simplifica para iconos.",
        "pass": f"A 32 px se mantiene ({round(i32 * 100)} %)."}[s32], i32))
    s16 = "warn" if i16 < 0.65 else "note" if i16 < 0.8 else "pass"
    checks.append(_check("small_16", "A 16 px (favicon)", s16, {
        "warn": f"Como favicon (16 px) no se reconoce ({round(i16 * 100)} %): conviene una versión reducida del símbolo.",
        "note": f"Como favicon (16 px) queda justo ({round(i16 * 100)} %).",
        "pass": f"Como favicon se reconoce ({round(i16 * 100)} %)."}[s16], i16))

    n = len(palette)
    ramps = sum(1 for p in palette if p.get("shades", 1) >= 3)
    sc = "warn" if n > 5 else "note" if n >= 4 or ramps else "pass"
    ramp_text = f" Lleva degradado en {ramps} color{'es' if ramps != 1 else ''}: para tinta plana hará falta una versión sin degradado." if ramps else ""
    checks.append(_check("colours", "Número de colores", sc, {
        "warn": f"{n} colores: cuesta reproducirlo (bordado, serigrafía, un color). Quédate en tres o menos.",
        "note": f"{n} color{'es' if n != 1 else ''}{': en el límite de lo fácil de reproducir.' if n >= 4 else '.'}",
        "pass": f"{n} color{'es' if n != 1 else ''}."}[sc] + ramp_text, n))

    w, h = x1 - x0, y1 - y0
    ratio_wh = round(max(w, h) / max(1, min(w, h)), 2)
    metrics["aspect"] = ratio_wh
    sa = "warn" if ratio_wh > 4 else "note" if ratio_wh > 2.5 else "pass"
    checks.append(_check("aspect", "Proporción", sa, {
        "warn": f"Muy alargado ({ratio_wh}:1): no cabe en un avatar o un favicon cuadrado; hace falta un símbolo aparte.",
        "note": f"Alargado ({ratio_wh}:1): en espacios cuadrados quedará pequeño.",
        "pass": f"Proporción {ratio_wh}:1, cabe en cuadrado."}[sa], ratio_wh))

    if background != "opaque":
        side = max(rgba.width, rgba.height)
        margin = min(x0, y0, rgba.width - x1, rgba.height - y1) / side
        off = max(abs((x0 + x1) / 2 - rgba.width / 2) / rgba.width, abs((y0 + y1) / 2 - rgba.height / 2) / rgba.height)
        metrics["margin"], metrics["off_centre"] = round(margin, 3), round(off, 3)
        if margin < 0.02:
            checks.append(_check("margin", "Margen", "note", "El dibujo toca el borde del archivo: deja un margen de seguridad.", round(margin, 3)))
        elif off > 0.08:
            checks.append(_check("margin", "Margen", "note", f"Descentrado un {round(off * 100)} % en el archivo.", round(off, 3)))
        else:
            checks.append(_check("margin", "Margen", "pass", "Tiene margen y está centrado.", round(margin, 3)))

    area = float((_alpha(square) > 0.5).sum())
    complexity = round(mono_edges ** 2 / (4 * np.pi * area), 1) if area else 0.0
    metrics["complexity"] = complexity
    sd = "warn" if complexity > 200 else "note" if complexity > 100 else "pass"
    checks.append(_check("detail", "Detalle", sd, {
        "warn": "Mucho detalle para una marca: se verá sucio en tamaños pequeños y al bordar o grabar.",
        "note": "Bastante detalle (normal en logotipos con texto); vigila los tamaños pequeños.",
        "pass": "Detalle contenido."}[sd], complexity))
    return checks, metrics, mark


def score_of(checks: list[dict[str, Any]]) -> tuple[int, str, dict[str, int]]:
    counts = {k: sum(1 for c in checks if c["status"] == k) for k in ("fail", "warn", "note", "pass")}
    score = max(0, 100 - sum(PENALTY[c["status"]] for c in checks))
    verdict = "lista" if score >= 85 else "revisar" if score >= 60 else "rehacer"
    return score, verdict, counts


def _font(size: int = 13) -> Any:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def parse_hex(value: str) -> tuple[int, int, int]:
    match = HEX_RE.match((value or "").strip())
    if not match:
        raise MarkError(f"Color no válido: {value!r} (usa #rrggbb).")
    h = match.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def render_sheet(mark: Image.Image, backgrounds: Optional[list[str]] = None) -> Image.Image:
    """The test sheet: grounds and versions on the first row, real sizes on the second."""
    cell, pad, label = 168, 14, 24
    big = _square(mark, cell)
    row1: list[tuple[str, Image.Image]] = [
        ("Original · claro", _on(big, LIGHT)), ("Original · oscuro", _on(big, DARK)), ("Original · gris", _on(big, GREY)),
        ("Un color", _on(_mono(big, (0, 0, 0)), LIGHT)), ("Invertido", _on(_mono(big, (255, 255, 255)), DARK)),
    ]
    for value in backgrounds or []:
        ground = parse_hex(value)
        row1.append((f"Original · #{'%02x%02x%02x' % ground}", _on(big, ground)))
    row2: list[tuple[str, Image.Image]] = []
    for size in (128, 64, 32, 16):
        tile = Image.new("RGB", (cell, cell), LIGHT)
        small = _on(_square(mark, size), LIGHT)
        tile.paste(small, ((cell - size) // 2, (cell - size) // 2))
        row2.append((f"{size} px", tile))
    for size, ground, name in ((32, LIGHT, "32 px ampliado"), (16, LIGHT, "16 px ampliado"), (16, DARK, "16 px ampliado · oscuro")):
        row2.append((name, _on(_square(mark, size), ground).resize((cell, cell), Image.NEAREST)))

    cols = max(len(row1), len(row2))
    width = pad + cols * (cell + pad)
    height = pad + 2 * (cell + label + pad)
    sheet = Image.new("RGB", (width, height), (236, 236, 236))
    draw = ImageDraw.Draw(sheet)
    font = _font(13)
    for r, row in enumerate((row1, row2)):
        top = pad + r * (cell + label + pad)
        for c, (name, tile) in enumerate(row):
            left = pad + c * (cell + pad)
            sheet.paste(tile, (left, top))
            draw.rectangle((left - 1, top - 1, left + cell, top + cell), outline=(200, 200, 200))
            draw.text((left, top + cell + 5), name, fill=(40, 40, 40), font=font)
    return sheet


def _load(data_dir: Path, browser: Any, *, path: Optional[str], data: Optional[str], svg: Optional[str], work: Path) -> tuple[Image.Image, str, str, str]:
    raw, kind, name = _read_source(path=path, data=data, svg=svg)
    if kind == "svg":
        return _rasterize_svg(raw, browser, work), "transparent", kind, name
    rgba, background = _load_raster(raw)
    return rgba, background, kind, name


def _urls(mark_id: str) -> dict[str, str]:
    return {"sheet_url": f"/api/marks/{mark_id}/sheet.png", "mark_url": f"/api/marks/{mark_id}/mark.png"}


def audit(data_dir: Path, browser: Any = None, *, path: Optional[str] = None, data: Optional[str] = None,
          svg: Optional[str] = None, name: str = "", backgrounds: Optional[list[str]] = None) -> dict[str, Any]:
    """Score a mark and save the report, the normalised mark and its test sheet under data/marks/<id>/."""
    for value in backgrounds or []:
        parse_hex(value)
    mark_id = uuid.uuid4().hex[:12]
    folder = _marks_dir(data_dir) / mark_id
    folder.mkdir(parents=True, exist_ok=True)
    try:
        rgba, background, kind, source_name = _load(data_dir, browser, path=path, data=data, svg=svg, work=folder)
        checks, metrics, mark = analyse(rgba, background, kind)
        score, verdict, counts = score_of(checks)
        mark.save(folder / "mark.png")
        render_sheet(mark, backgrounds).save(folder / "sheet.png")
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)  # a source that cannot be audited leaves no empty report folder
        raise
    report = {"id": mark_id, "name": (name or source_name)[:120], "kind": kind, "created_at": time.time(), "score": score,
              "verdict": verdict, "counts": counts, "checks": checks, "metrics": metrics, "backgrounds": list(backgrounds or []),
              **_urls(mark_id), "sheet_path": str(folder / "sheet.png"),
              "limits": ["Mide la forma y el color, no el concepto ni si se parece a otra marca.",
                         "Un SVG se dibuja sobre blanco: las partes blancas de la marca cuentan como fondo."]}
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def get_report(data_dir: Path, mark_id: str) -> dict[str, Any]:
    if not ID_RE.match(mark_id or ""):
        raise LookupError(f"No hay una auditoría de marca {mark_id}.")
    file = _marks_dir(data_dir) / mark_id / "report.json"
    if not file.is_file():
        raise LookupError(f"No hay una auditoría de marca {mark_id}.")
    return json.loads(file.read_text(encoding="utf-8"))


def list_reports(data_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    rows = []
    for file in _marks_dir(data_dir).glob("*/report.json"):
        try:
            r = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows.append({k: r.get(k) for k in ("id", "name", "kind", "created_at", "score", "verdict", "counts", "sheet_url", "mark_url")})
    rows.sort(key=lambda r: -(r.get("created_at") or 0))
    return rows[: max(1, limit)]


def file_path(data_dir: Path, mark_id: str, which: str) -> Path:
    if which not in ("sheet", "mark") or not ID_RE.match(mark_id or ""):
        raise LookupError("No existe ese archivo.")
    file = _marks_dir(data_dir) / mark_id / f"{which}.png"
    if not file.is_file():
        raise LookupError("No existe ese archivo.")
    return file


def test_sheet(data_dir: Path, browser: Any = None, *, mark_id: Optional[str] = None, path: Optional[str] = None,
               data: Optional[str] = None, svg: Optional[str] = None, backgrounds: Optional[list[str]] = None) -> dict[str, Any]:
    """Redraw the sheet of an audited mark (mark_id) with extra grounds, or audit a new source and return its sheet."""
    if not mark_id:
        report = audit(data_dir, browser, path=path, data=data, svg=svg, backgrounds=backgrounds)
        mark_id = report["id"]
    else:
        if path or data or svg:
            raise MarkError("Pasa mark_id o una fuente, no los dos.")
        report = get_report(data_dir, mark_id)
        for value in backgrounds or []:
            parse_hex(value)
        with Image.open(file_path(data_dir, mark_id, "mark")) as img:
            mark = img.convert("RGBA")
        render_sheet(mark, backgrounds).save(_marks_dir(data_dir) / mark_id / "sheet.png")
        report["backgrounds"] = list(backgrounds or [])
        (_marks_dir(data_dir) / mark_id / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    folder = _marks_dir(data_dir) / mark_id
    return {"id": mark_id, "name": report.get("name"), "backgrounds": report.get("backgrounds", []), **_urls(mark_id),
            "sheet_path": str(folder / "sheet.png"), "updated_at": time.time()}
