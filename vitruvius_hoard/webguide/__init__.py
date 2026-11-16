"""Modern web platform guidance: a vendored guide library with an index, search and a reader.

The guides are the Apache-2.0 collection published by the Chrome team (see ``LICENSE-Apache-2.0.txt`` and ``UPSTREAM.md``),
copied here unchanged under ``guides/<category>/<id>.md``. Everything is read from disk: no engine, no data store and no network.
``search`` ranks guides by word overlap (English, with a Spanish synonym table), ``read`` returns one or more guides, and
``legacy`` scans source files for older patterns that a guide replaces with a native feature.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent
GUIDES = ROOT / "guides"
CITE = "[vitruvius: webguide/{id}]"

# Spanish words an agent or a person may use, mapped to the English words the guides are written in.
_ES = {
    "dialogo": "dialog modal", "modal": "dialog modal", "emergente": "popover", "ventana": "dialog", "tooltip": "tooltip",
    "globo": "tooltip", "tabla": "table", "tablas": "table", "formulario": "form", "formularios": "form", "campo": "input",
    "animacion": "animation animate", "animaciones": "animation animate", "transicion": "transition", "transiciones": "transition",
    "desplazamiento": "scroll", "scroll": "scroll", "paralaje": "parallax", "colores": "color", "color": "color",
    "tipografia": "typography font text", "fuente": "font", "accesibilidad": "accessibility", "accesible": "accessibility",
    "rendimiento": "performance", "seguridad": "security", "menu": "menu", "menus": "menu", "pestanas": "tabs", "pestana": "tabs",
    "oscuro": "dark", "claro": "light", "icono": "icons icon", "iconos": "icons icon", "imagen": "image", "imagenes": "image",
    "carrusel": "carousel", "acordeon": "accordion", "desplegable": "dropdown select", "selector": "select picker",
    "cabecera": "header sticky", "navegacion": "navigation navbar", "barra": "bar", "cajon": "drawer", "tarjeta": "card",
    "contenedor": "container", "contenedores": "container", "adaptable": "responsive", "responsive": "responsive", "movil": "mobile",
    "capa": "layer", "textura": "texture", "sombra": "shadow", "degradado": "gradient", "fecha": "date calendar",
    "zona": "timezone", "idioma": "language", "traduccion": "translator translate", "web": "web", "componentes": "components",
    "tema": "theme", "copiar": "copy", "portapapeles": "clipboard copy", "notificacion": "toast notification",
    "notificaciones": "toast notification", "progreso": "progress", "cargando": "spinner progress", "interactivo": "interactive",
    "arrastrar": "drag drop", "deslizar": "swipe", "tres": "3d", "escena": "scene 3d", "shader": "webgl shaders", "webgl": "webgl shaders",
    "antiguo": "legacy", "moderno": "modern", "nativo": "native", "contrasenas": "passkeys password", "clave": "passkey",
}
_STOP = {"al", "hacer", "como", "que", "por", "se", "de", "del", "la", "el", "los", "las", "un", "una", "para", "con", "y", "o", "en", "a", "the", "and", "or", "for", "of", "to", "in", "an", "with"}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", _fold(text)) if w not in _STOP]


def _terms(query: str) -> list[str]:
    out: list[str] = []
    for word in _words(query):
        out.append(word)
        if word in _ES:
            out.extend(_ES[word].split())
        elif len(word) > 3 and word.endswith("s") and word[:-1] not in out:
            out.append(word[:-1])
    return out


@lru_cache(maxsize=1)
def _index() -> tuple[dict, ...]:
    rows = []
    for path in sorted(GUIDES.glob("*/*.md")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        title = next((line[2:].strip() for line in lines if line.startswith("# ")), path.stem)
        body = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
        summary = body[0] if body else ""
        rows.append({"id": path.stem, "category": path.parent.name, "title": title, "summary": summary[:360],
                     "path": f"{path.parent.name}/{path.name}", "bytes": len(text.encode("utf-8")),
                     "cite": CITE.format(id=path.stem), "_haystack": _fold(" ".join([path.stem.replace("-", " "), title, summary]))})
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("web guide ids must be unique across categories")
    return tuple(rows)


def _public(row: dict, score: int | None = None) -> dict:
    out = {k: v for k, v in row.items() if not k.startswith("_")}
    if score is not None:
        out["score"] = score
    return out


def categories() -> list[dict]:
    counts: dict[str, int] = {}
    for row in _index():
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    return [{"category": name, "guides": counts[name]} for name in sorted(counts)]


def listing(category: str | None = None) -> dict:
    rows = [_public(row) for row in _index() if not category or row["category"] == category]
    return {"guides": rows, "categories": categories(), "total": len(_index())}


def search(query: str = "", category: str | None = None, limit: int = 8) -> dict:
    """Guides whose id, title or opening paragraph share words with the query, best first. An empty query lists them all."""
    terms = _terms(query)
    rows = []
    for row in _index():
        if category and row["category"] != category:
            continue
        if not terms:
            rows.append((0, row))
            continue
        id_words = set(row["id"].split("-"))
        title_words = set(_words(row["title"]))
        hay = set(re.findall(r"[a-z0-9]+", row["_haystack"]))
        score = 0
        for term in set(terms):
            if term in id_words:
                score += 6
            if term in title_words:
                score += 4
            if term in hay:
                score += 2
            elif any(term in word or word in term for word in hay if len(word) > 4 and len(term) > 4):
                score += 1
        if score:
            rows.append((score, row))
    rows.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    limit = max(1, min(int(limit or 8), 50))
    return {"query": query, "guides": [_public(row, score) for score, row in rows[:limit]], "matched": len(rows)}


def _rewrite(text: str) -> str:
    """Point the guides' cross-references at this library instead of the command line they were written for."""
    text = re.sub(r"`?npx -y modern-web-guidance@latest retrieve \"([a-z0-9-]+)\"`?", r"`web_guide_read` with id `\1`", text)
    return re.sub(r"`?npx -y modern-web-guidance@latest search \"([^\"]+)\"`?", r"`web_guide_search` with query `\1`", text)


def read(ids) -> dict:
    """Read guides by id (a list, or one string with comma-separated ids). Unknown ids are reported, not raised."""
    wanted = [part.strip() for part in (ids.split(",") if isinstance(ids, str) else ids or []) if str(part).strip()]
    if not wanted:
        raise ValueError("Give at least one guide id")
    known = {row["id"]: row for row in _index()}
    guides, missing = [], []
    for guide_id in wanted:
        row = known.get(guide_id)
        if row is None:
            missing.append(guide_id)
            continue
        text = (GUIDES / row["path"]).read_text(encoding="utf-8")
        guides.append({**_public(row), "markdown": _rewrite(text)})
    if not guides:
        near = [row["id"] for row in search(" ".join(wanted).replace("-", " "), limit=5)["guides"]]
        raise LookupError(f"Unknown web guide: {', '.join(missing)}" + (f". Similar: {', '.join(near)}" if near else ""))
    return {"guides": guides, "missing": missing, "license": "Apache-2.0 (Chrome team); see vitruvius_hoard/webguide/UPSTREAM.md"}
