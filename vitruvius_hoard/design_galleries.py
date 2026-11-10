"""Design galleries as first-class references: what each one gives, when to use it, the areas it covers, and a captured sample page.

The galleries live in ``seeds.json`` (``galleries``). The curated ones (scroll templates, scroll shaders, footers, CTAs, product styles,
heroes, 3D icons, glassmorphism) carry ``provides`` / ``when`` (English and Spanish), ``areas``, ``keywords``, a licence note and a
``sample_url``. ``search`` finds them by word or area in either language ("referencias de footers", "ejemplos de CTA").
``ingest`` captures each sample page into the reference gallery (desktop + mobile screenshots, palette, fonts) and stores the useful
fragments of the page (headings, CTA texts, footer links and an excerpt of its HTML, glass / scroll / sticky signals) so the brief
and the critique can cite them as ``[vitruvius: gallery/<id>]``.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import unicodedata
from functools import lru_cache
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional

SEEDS = Path(__file__).resolve().parent / "seeds.json"
AREAS = ("layout", "motion", "color", "typography", "components", "effects", "imagery", "iconography", "content")
TAG = "gallery"

_STOP = {
    "reference", "references", "referencia", "referencias", "example", "examples", "ejemplo", "ejemplos", "idea", "ideas",
    "inspiration", "inspiracion", "gallery", "galleries", "galeria", "galerias", "de", "del", "la", "el", "los", "las", "un", "una",
    "unos", "unas", "para", "for", "of", "the", "a", "an", "and", "y", "o", "or", "con", "with", "some", "algunos", "algunas",
    "dame", "give", "me", "show", "muestra", "muestrame", "busca", "buscar", "find", "search", "sobre", "about", "design", "diseno",
    "web", "website", "websites", "page", "pages", "pagina", "paginas", "site", "sites", "good", "buenos", "buenas", "que", "what",
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _fold(text))


def _slug(name: str) -> str:
    return "-".join(_words(name)) or "gallery"


def _normalise(raw: dict[str, Any]) -> dict[str, Any]:
    g = dict(raw)
    g["id"] = g.get("id") or _slug(g.get("name", ""))
    g["curated"] = bool(g.get("provides"))
    g.setdefault("kind", "gallery")
    g.setdefault("areas", ["layout"])
    g.setdefault("keywords", [])
    g.setdefault("provides", g.get("note", ""))
    g.setdefault("provides_es", g["provides"])
    g.setdefault("when", "")
    g.setdefault("when_es", g["when"])
    g.setdefault("license", "Browse for reference; each page belongs to its site.")
    g.setdefault("sample_url", "")
    g["cite"] = f"[vitruvius: gallery/{g['id']}]"
    return g


@lru_cache(maxsize=1)
def load() -> tuple[dict[str, Any], ...]:
    """Every gallery of seeds.json, curated ones first."""
    try:
        raw = json.loads(SEEDS.read_text(encoding="utf-8")).get("galleries", [])
    except (OSError, ValueError):
        raw = []
    rows = [_normalise(r) for r in raw if isinstance(r, dict) and r.get("name") and r.get("url")]
    return tuple(sorted(rows, key=lambda g: not g["curated"]))


def get(gallery_id: str) -> Optional[dict[str, Any]]:
    key = (gallery_id or "").strip().lower()
    return next((g for g in load() if g["id"] == key), None)


def _match(q: str, k: str) -> bool:
    """Same word, or one is the other plus a short plural/inflection ending (footer/footers, boton/botones, hero/heroes)."""
    if q == k:
        return True
    if min(len(q), len(k)) < 3:
        return False
    short, long_ = (q, k) if len(q) <= len(k) else (k, q)
    return long_.startswith(short) and len(long_) - len(short) <= 2


def _score(g: dict[str, Any], tokens: list[str]) -> float:
    fields = [
        (4.0, _words(" ".join([g["id"], g["name"]]))),
        (3.0, _words(" ".join(g["keywords"]))),
        (3.0, _words(" ".join(g["areas"]))),
        (1.0, _words(" ".join([g["provides"], g["provides_es"], g["when"], g["when_es"]]))),
    ]
    score = 0.0
    for t in tokens:
        best = 0.0
        for weight, words in fields:
            if any(_match(t, w) for w in words):
                best = max(best, weight)
        score += best
    return score


def query_tokens(query: Optional[str]) -> list[str]:
    return [t for t in _words(query or "") if t not in _STOP]


def search(db: Any = None, *, query: Optional[str] = None, area: Optional[str] = None, limit: int = 20,
           require_match: bool = False, samples: bool = True) -> list[dict[str, Any]]:
    """Galleries for a word or an area, best first. No words (or only filler like "referencias de") lists them all, unless
    ``require_match`` (the brief and the critique only want galleries that actually fit)."""
    tokens = query_tokens(query)
    wanted_area = _fold(area or "").strip()
    out = []
    for g in load():
        if wanted_area and wanted_area not in g["areas"]:
            continue
        score = _score(g, tokens) if tokens else 0.0
        if tokens and score <= 0:
            continue
        if require_match and not tokens and not wanted_area:
            continue
        item = {k: g[k] for k in ("id", "name", "url", "sample_url", "kind", "areas", "provides", "provides_es", "when", "when_es",
                                  "keywords", "license", "curated", "cite")}
        item["score"] = round(score, 2)
        out.append(item)
    if tokens:
        out.sort(key=lambda r: (-r["score"], not r["curated"]))
    out = out[:max(1, limit)]
    if samples and db is not None:
        for item in out:
            item["samples"] = sample_rows(db, item["id"])
    return out


def sample_rows(db: Any, gallery_id: str) -> list[dict[str, Any]]:
    """The captured sample pages of a gallery (newest first), with their files and a short view of the fragments."""
    rows = db.query("SELECT * FROM references_t WHERE tags LIKE ? ORDER BY created_ts DESC", (f'%"{TAG}:{gallery_id}"%',))
    out = []
    for r in rows:
        analysis = json.loads(r["analysis"] or "{}")
        frags = analysis.get("fragments") or {}
        out.append({"id": r["id"], "title": r["title"], "url": r["url"], "created_ts": r["created_ts"],
                    "files": json.loads(r["files"] or "{}"), "palette": json.loads(r["palette"] or "[]"),
                    "fragments": {"headings": (frags.get("headings") or [])[:6], "ctas": (frags.get("ctas") or [])[:6],
                                  "footer_links": (frags.get("footer", {}).get("links") or [])[:10], "signals": frags.get("signals") or {}},
                    "cite": f"[vitruvius: gallery/{gallery_id} § {r['id']}]"})
    return out


# ---------------------------------------------------------------------------- fragments of a captured page

_CTA_WORDS = re.compile(
    r"\b(get|start|try|sign|join|subscribe|book|buy|download|contact|explore|browse|submit|request|claim|shop|order|learn more|see all|view all|"
    r"empieza|empezar|prueba|probar|registr|suscr|descarga|compra|contacta|explora|reserva|ver todo|ver m[aá]s)\b", re.I)
_CTA_CLASS = re.compile(r"\b(btn|button|cta)\b|btn-|button-|cta-|-cta", re.I)
_SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


def _clean(text: str, limit: int = 140) -> str:
    return re.sub(r"\s+", " ", unescape(text or "")).strip()[:limit]


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.skip = 0
        self.headings: list[dict[str, Any]] = []
        self.ctas: list[str] = []
        self.footer_links: list[str] = []
        self.footer_text: list[str] = []
        self.nav_links: list[str] = []
        self.paragraphs: list[str] = []
        self._buf: list[list[str]] = []  # text buffers of open h*/a/button/p

    def _inside(self, *tags: str) -> bool:
        return any(t in tags for t, _ in self.stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in _SKIP:
            self.skip += 1
            return
        if tag in _VOID:
            return
        a = {k: (v or "") for k, v in attrs}
        self.stack.append((tag, a))
        if tag in ("h1", "h2", "h3", "a", "button", "p"):
            self._buf.append([])

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if not any(t == tag for t, _ in self.stack):
            return
        while self.stack:
            t, a = self.stack.pop()
            if t in ("h1", "h2", "h3", "a", "button", "p"):
                text = _clean(" ".join(self._buf.pop() if self._buf else []))
                if text:
                    self._close(t, a, text)
            if t == tag:
                break

    def _close(self, tag: str, attrs: dict[str, str], text: str) -> None:
        if tag in ("h1", "h2", "h3") and len(self.headings) < 24:
            self.headings.append({"level": int(tag[1]), "text": text})
        elif tag == "p" and len(self.paragraphs) < 12 and len(text) > 30:
            self.paragraphs.append(_clean(text, 280))
        elif tag in ("a", "button"):
            if self._inside("footer"):
                if text not in self.footer_links and len(self.footer_links) < 40:
                    self.footer_links.append(text)
            elif self._inside("nav", "header"):
                if text not in self.nav_links and len(self.nav_links) < 20:
                    self.nav_links.append(text)
            short = len(text) <= 40
            klass = " ".join([attrs.get("class", ""), attrs.get("id", ""), attrs.get("role", "")])
            if short and (tag == "button" or _CTA_CLASS.search(klass) or _CTA_WORDS.search(text)) and text not in self.ctas and len(self.ctas) < 16:
                self.ctas.append(text)

    def handle_data(self, data: str) -> None:
        if self.skip or not data.strip():
            return
        for buf in self._buf:
            buf.append(data)
        if self._inside("footer") and sum(len(t) for t in self.footer_text) < 800:
            self.footer_text.append(data.strip())


def _footer_html(html: str, limit: int = 4000) -> str:
    found = re.findall(r"<footer\b.*?</footer>", html or "", flags=re.S | re.I)
    if not found:
        return ""
    block = found[-1]
    block = re.sub(r"<(script|style|noscript|template)\b.*?</\1>", "", block, flags=re.S | re.I)
    block = re.sub(r"<svg\b.*?</svg>", "<svg/>", block, flags=re.S | re.I)
    block = re.sub(r"\s+", " ", block)
    return block[:limit]


def extract_fragments(html: str, css: str = "") -> dict[str, Any]:
    """Headings, hero text, CTA texts, navigation and footer links, an excerpt of the footer's HTML and a few CSS signals."""
    c = _Collector()
    try:
        c.feed(html or "")
        c.close()
    except Exception:  # noqa: BLE001 — a malformed page still yields what was read
        pass
    source = f"{html or ''}\n{css or ''}"
    h1 = next((h["text"] for h in c.headings if h["level"] == 1), "")
    return {
        "headings": c.headings,
        "hero": {"headline": h1, "lede": c.paragraphs[0] if c.paragraphs else ""},
        "ctas": c.ctas,
        "nav_links": c.nav_links,
        "footer": {"links": c.footer_links, "text": _clean(" ".join(c.footer_text), 800), "html": _footer_html(html)},
        "signals": {
            "backdrop_filter": len(re.findall(r"backdrop-filter", source, re.I)),
            "scroll_timeline": len(re.findall(r"(animation|scroll|view)-timeline", source, re.I)),
            "sticky": len(re.findall(r"position\s*:\s*sticky", source, re.I)),
            "canvas": len(re.findall(r"<canvas\b", html or "", re.I)),
            "webgl": len(re.findall(r"webgl|three(\.module)?\.js|ogl|shader", source, re.I)),
        },
    }


# ---------------------------------------------------------------------------- capturing the sample pages

def tags_for(g: dict[str, Any]) -> list[str]:
    """Tags of a sample: the gallery marker, its areas and its first plain keywords, so reference_search finds it by "footer" or "cta"."""
    words = [k for k in g["keywords"] if re.fullmatch(r"[a-z0-9-]+", k)][:6]
    out: list[str] = []
    for t in [TAG, f"{TAG}:{g['id']}", *g["areas"], *words]:
        if t not in out:
            out.append(t)
    return out


def _remove_reference(db: Any, references_dir: Path, ref_id: str) -> None:
    db.execute("DELETE FROM references_t WHERE id = ?", (ref_id,))
    root = Path(references_dir).resolve()
    folder = (root / ref_id).resolve()
    if folder.parent == root and folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


def ingest_one(svc: Any, g: dict[str, Any], *, video: bool = False) -> dict[str, Any]:
    url = g.get("sample_url") or g["url"]
    started = time.time()
    captured: dict[str, Any] = {}

    def extra(desktop: dict[str, Any]) -> dict[str, Any]:
        probe = desktop.get("probe") or {}
        captured["error"] = desktop.get("error") and (desktop.get("hint") or desktop["error"])
        fragments = extract_fragments(probe.get("html_text") or "", probe.get("css_text") or "")
        captured["fragments"] = fragments
        return {"gallery": {"id": g["id"], "name": g["name"], "url": g["url"], "areas": g["areas"], "kind": g["kind"],
                            "provides": g["provides"], "when": g["when"], "license": g["license"], "captured_ts": time.time()},
                "fragments": fragments}

    previous = [s["id"] for s in sample_rows(svc.db, g["id"])]
    row = svc.reference_add(url=url, tags=tags_for(g), note=f"{g['name']}: {g['provides']}", video=video, analyze=False,
                            extra_analysis=extra)
    if not (row.get("files") or {}).get("desktop"):
        _remove_reference(svc.db, svc.config.references_dir, row["id"])
        return {"id": g["id"], "ok": False, "url": url, "error": captured.get("error") or "the page did not load", "ms": round((time.time() - started) * 1000)}
    for old in previous:
        _remove_reference(svc.db, svc.config.references_dir, old)
    frags = captured.get("fragments") or {}
    return {"id": g["id"], "ok": True, "url": url, "reference_id": row["id"], "title": row["title"], "files": row["files"],
            "palette": row["palette"], "fonts": row["fonts"], "replaced": previous,
            "fragments": {"headings": len(frags.get("headings") or []), "ctas": len(frags.get("ctas") or []),
                          "footer_links": len((frags.get("footer") or {}).get("links") or []), "signals": frags.get("signals") or {}},
            "cite": f"[vitruvius: gallery/{g['id']} § {row['id']}]", "ms": round((time.time() - started) * 1000)}


def ingest(svc: Any, ids: Optional[list[str]] = None, *, video: bool = False) -> dict[str, Any]:
    """Capture the sample page of the given galleries (default: every curated gallery with a sample page)."""
    if ids:
        unknown = [i for i in ids if get(i) is None]
        if unknown:
            raise LookupError(f"Unknown gallery: {', '.join(unknown)} (list them with design_galleries).")
        targets = [get(i) for i in ids]
    else:
        targets = [g for g in load() if g["curated"] and g["sample_url"]]
    results = []
    for g in targets:
        try:
            results.append(ingest_one(svc, g, video=video))
        except Exception as error:  # noqa: BLE001 — one gallery that fails does not stop the others
            results.append({"id": g["id"], "ok": False, "url": g.get("sample_url") or g["url"], "error": f"{type(error).__name__}: {error}"[:300]})
    return {"count": len(results), "ok": sum(1 for r in results if r["ok"]), "results": results}
