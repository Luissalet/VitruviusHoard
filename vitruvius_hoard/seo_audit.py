"""Deterministic SEO and GEO audit of a site.

Every finding comes from a measurement that can be repeated: fetched documents (HTML, robots.txt, sitemap, llms.txt, images,
links), headers, parsed structured data and, for the Core Web Vitals, a real Chromium load (`BrowserWorker` job `vitals`).
Nothing is scored by a model. What a measurement cannot decide (is the content good, is the author credible) is reported as a
*judgement* finding: it carries `judgement: true`, never changes the score and goes to the human-review phase of the plan.

Scores. Each finding has a severity (critical, high, medium, low, info) that costs 40, 20, 10, 4 or 0 points of its category; a
check repeated on many pages costs at most twice its penalty. A category scores 100 minus its penalties (floor 0); the total is
the weighted mean of the categories that were measured (content 23, technical 22, on-page 20, schema 10, Core Web Vitals 10,
AI visibility 10, images 5). A category that could not be measured (no browser, no page) has `score: null` and does not enter
the mean, so a missing measurement never looks like a good score.

The checklist and the weights follow the structure of the open audit skill credited in NOTICE (claude-seo, MIT); the checks are
original code. The fetcher and the vitals job are injectable, so the whole audit runs offline in tests.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

SCHEMA = "site-audit/1"
CATEGORIES: dict[str, dict[str, Any]] = {
    "content": {"name": "Contenido", "weight": 23},
    "technical": {"name": "SEO técnico", "weight": 22},
    "onpage": {"name": "SEO en página", "weight": 20},
    "schema": {"name": "Datos estructurados", "weight": 10},
    "cwv": {"name": "Rendimiento (Core Web Vitals)", "weight": 10},
    "ai": {"name": "Visibilidad en IA (GEO)", "weight": 10},
    "images": {"name": "Imágenes", "weight": 5},
}
SEVERITIES = ("critical", "high", "medium", "low", "info")
PENALTY = {"critical": 40, "high": 20, "medium": 10, "low": 4, "info": 0}
REPEAT_CAP = 2  # a check repeated on many pages costs at most this many times its penalty

# Crawlers by purpose: training data, search/citation in AI answers, fetch on behalf of a user. Blocking the first does not stop the
# second: a site can opt out of training and still be cited.
AI_CRAWLERS: tuple[tuple[str, str, str], ...] = (
    ("GPTBot", "OpenAI", "training"), ("ClaudeBot", "Anthropic", "training"), ("anthropic-ai", "Anthropic", "training"),
    ("Google-Extended", "Google", "training"), ("Applebot-Extended", "Apple", "training"), ("CCBot", "Common Crawl", "training"),
    ("Bytespider", "ByteDance", "training"), ("meta-externalagent", "Meta", "training"), ("cohere-ai", "Cohere", "training"),
    ("OAI-SearchBot", "OpenAI", "search"), ("Claude-SearchBot", "Anthropic", "search"), ("PerplexityBot", "Perplexity", "search"),
    ("DuckAssistBot", "DuckDuckGo", "search"), ("Googlebot", "Google", "search"), ("bingbot", "Microsoft", "search"),
    ("ChatGPT-User", "OpenAI", "user"), ("Claude-User", "Anthropic", "user"), ("Perplexity-User", "Perplexity", "user"),
    ("MistralAI-User", "Mistral", "user"),
)
SECURITY_HEADERS = (  # header, severity when missing, why
    ("strict-transport-security", "medium", "Sin HSTS el navegador puede abrir la versión http primero."),
    ("content-security-policy", "medium", "Sin política de contenido no se limita qué scripts pueden ejecutarse."),
    ("x-content-type-options", "low", "Sin `nosniff` el navegador puede reinterpretar el tipo de los archivos."),
    ("referrer-policy", "low", "Sin política de referencia se envía la URL completa a otros sitios."),
    ("permissions-policy", "info", "Sin política de permisos las funciones del navegador quedan por defecto."),
)
_SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".ico", ".zip", ".gz", ".mp4", ".webm", ".mp3", ".css", ".js", ".json", ".xml", ".txt", ".woff", ".woff2", ".ttf", ".rss", ".atom")
_GENERIC_ANCHORS = {"aquí", "aqui", "click aquí", "clic aquí", "pulsa aquí", "haz clic aquí", "leer más", "ver más", "más", "más información", "saber más",
                    "here", "click here", "read more", "learn more", "more", "more info", "link", "this link"}
_STOPWORDS = frozenset("""a al algo como con de del el ella ellos en es esta este esto la las lo los me mi muy no nos o para pero por que se si sin su sus un una uno y ya
the and of to in is it for on with as at by an be this that from or are was were we you your our not but have has can will more""".split())
# Properties Google lists as required or strongly recommended per type (lower case type -> properties).
SCHEMA_PROPS = {
    "organization": ("name", "url"), "person": ("name",), "website": ("name", "url"), "article": ("headline", "datePublished", "author"),
    "blogposting": ("headline", "datePublished", "author"), "newsarticle": ("headline", "datePublished", "author"),
    "product": ("name", "offers"), "localbusiness": ("name", "address"), "breadcrumblist": ("itemListElement",),
    "faqpage": ("mainEntity",), "softwareapplication": ("name", "offers"), "event": ("name", "startDate", "location"),
}


class AuditError(ValueError):
    """The audit cannot start (an address that is not a web address)."""


# ---------------------------------------------------------------------------------------------- findings
class _Ctx:
    def __init__(self, fetch: Callable[..., dict], budget_s: float, max_requests: int):
        self.fetch = fetch
        self.cache: dict[str, dict] = {}
        self.requests = 0
        self.max_requests = max_requests
        self.deadline = time.monotonic() + budget_s
        self.findings: list[dict] = []
        self.limits: list[str] = []
        self.truncated = False

    def add(self, category: str, check: str, severity: str, title: str, description: str, recommendation: str, *, url: str = "", judgement: bool = False, evidence: Any = None) -> None:
        fid = f"{category}.{check}"
        if url:
            path = urlsplit(url).path or "/"
            fid = f"{fid}@{path}"
        row: dict[str, Any] = {"id": fid, "category": category, "severity": severity, "title": title, "description": description,
                               "recommendation": recommendation, "judgement": bool(judgement)}
        if url:
            row["url"] = url
        if evidence not in (None, "", [], {}):
            row["evidence"] = evidence
        if all(f["id"] != fid for f in self.findings):
            self.findings.append(row)

    def get(self, url: str, *, accept: str = "html", max_bytes: Optional[int] = None) -> dict:
        key = f"{accept}|{url}"
        if key in self.cache:
            return self.cache[key]
        if self.requests >= self.max_requests or time.monotonic() > self.deadline:
            self.truncated = True
            return {"ok": False, "url": url, "final_url": url, "status": 0, "headers": {}, "text": "", "size": 0, "error": "audit budget reached", "error_kind": "budget", "skipped": True}
        self.requests += 1
        try:
            res = self.fetch(url, accept=accept, max_bytes=max_bytes)
        except Exception as error:  # noqa: BLE001 - a broken fetcher is one failed request, not a failed audit
            res = {"ok": False, "url": url, "final_url": url, "status": 0, "headers": {}, "text": "", "size": 0, "error": f"{type(error).__name__}: {error}"[:200], "error_kind": "network"}
        res.setdefault("headers", {})
        res.setdefault("text", "")
        res.setdefault("status", 0)
        res.setdefault("final_url", url)
        self.cache[key] = res
        return res


def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def _norm(url: str) -> str:
    url, _ = urldefrag(url.strip())
    p = urlsplit(url)
    path = p.path or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))


def _same_site(a: str, b: str) -> bool:
    ha, hb = (urlsplit(a).hostname or "").lower(), (urlsplit(b).hostname or "").lower()
    return ha.removeprefix("www.") == hb.removeprefix("www.")


# ---------------------------------------------------------------------------------------------- HTML scan
class _Scan(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = ""
        self.title = ""
        self.metas: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.headings: list[tuple[int, str]] = []
        self.anchors: list[dict[str, Any]] = []
        self.images: list[dict[str, str]] = []
        self.ld: list[str] = []
        self.resources: list[tuple[str, str]] = []
        self.microdata = False
        self.scripts = 0
        self._text_target: Optional[list[str]] = None
        self._anchor: Optional[dict[str, Any]] = None
        self._ld_buf: Optional[list[str]] = None
        self._title_buf: Optional[list[str]] = None
        self._head: Optional[tuple[int, list[str]]] = None
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "title" and not self.title:
            self._title_buf = []
        elif tag == "meta":
            self.metas.append(a)
        elif tag == "link":
            self.links.append(a)
            if a.get("href") and "stylesheet" in a.get("rel", "").lower():
                self.resources.append(("link", a["href"]))
        elif tag == "script":
            if a.get("type", "").lower() == "application/ld+json":
                self._ld_buf = []
            else:
                self.scripts += 1  # executable scripts only: structured data is not code
            if a.get("src"):
                self.resources.append(("script", a["src"]))
            self._skip += 1
        elif tag == "style":
            self._skip += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._head = (int(tag[1]), [])
        elif tag == "a" and a.get("href") is not None:
            self._anchor = {"href": a.get("href", ""), "rel": a.get("rel", ""), "aria": a.get("aria-label", ""), "title": a.get("title", ""), "text": [], "img_alt": ""}
        elif tag == "img":
            self.images.append(a)
            if self._anchor is not None and a.get("alt"):
                self._anchor["img_alt"] = a["alt"]
            if a.get("src"):
                self.resources.append(("img", a["src"]))
        elif tag in ("iframe", "source", "video", "audio") and (a.get("src") or a.get("srcset")):
            self.resources.append((tag, (a.get("src") or a.get("srcset", "").split(",")[0].split(" ")[0])))
        if "itemscope" in a or "itemtype" in a:
            self.microdata = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._title_buf is not None:
            self.title = " ".join("".join(self._title_buf).split())
            self._title_buf = None
        elif tag == "script":
            if self._ld_buf is not None:
                self.ld.append("".join(self._ld_buf))
                self._ld_buf = None
            self._skip = max(0, self._skip - 1)
        elif tag == "style":
            self._skip = max(0, self._skip - 1)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._head is not None:
            self.headings.append((self._head[0], " ".join("".join(self._head[1]).split())))
            self._head = None
        elif tag == "a" and self._anchor is not None:
            self._anchor["text"] = " ".join("".join(self._anchor["text"]).split())
            self.anchors.append(self._anchor)
            self._anchor = None

    def handle_data(self, data: str) -> None:
        if self._ld_buf is not None:
            self._ld_buf.append(data)
        elif self._title_buf is not None:
            self._title_buf.append(data)
        else:
            if self._head is not None:
                self._head[1].append(data)
            if self._anchor is not None:
                self._anchor["text"].append(data)

    def meta(self, key: str) -> str:
        key = key.lower()
        for m in self.metas:
            if m.get("name", "").lower() == key or m.get("property", "").lower() == key or m.get("http-equiv", "").lower() == key:
                if m.get("content"):
                    return m["content"].strip()
        return ""


def _scan(html: str) -> _Scan:
    s = _Scan()
    try:
        s.feed(html or "")
        s.close()
    except Exception:  # noqa: BLE001 - a broken page is scanned as far as it goes
        pass
    return s


def _visible_text(html: str) -> str:
    try:
        from .hoard_link.web.htmltext import visible_text
        return visible_text(html)
    except Exception:  # noqa: BLE001
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")))


def _jsonld(scan: _Scan) -> tuple[list[Any], list[str]]:
    from .hoard_link.web import meta as web_meta
    return web_meta._blocks_from_scripts(scan.ld)


def _words(text: str) -> list[str]:
    return re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ'-]+", text.lower())


# ---------------------------------------------------------------------------------------------- page model
class _Page:
    def __init__(self, url: str, res: dict):
        self.url = url
        self.res = res
        self.final = res.get("final_url") or url
        self.status = int(res.get("status") or 0)
        self.headers = {k.lower(): v for k, v in (res.get("headers") or {}).items()}
        self.html = res.get("text") or ""
        self.scan = _scan(self.html)
        self.text = _visible_text(self.html)
        self.words = _words(self.text)
        self.blocks, self.ld_errors = _jsonld(self.scan)
        self.title = self.scan.title
        self.description = self.scan.meta("description")

    @property
    def canonical(self) -> str:
        for link in self.scan.links:
            if "canonical" in link.get("rel", "").lower().split() and link.get("href"):
                return urljoin(self.final, link["href"])
        return ""

    def internal_links(self) -> list[str]:
        out: list[str] = []
        for a in self.scan.anchors:
            href = (a["href"] or "").strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:", "sms:")):
                continue
            full = _norm(urljoin(self.final, href))
            if urlsplit(full).scheme in ("http", "https") and _same_site(full, self.final) and full not in out:
                out.append(full)
        return out

    def external_links(self) -> list[str]:
        out: list[str] = []
        for a in self.scan.anchors:
            full = urljoin(self.final, (a["href"] or "").strip())
            if urlsplit(full).scheme in ("http", "https") and not _same_site(full, self.final) and full not in out:
                out.append(full)
        return out


# ---------------------------------------------------------------------------------------------- site-level technical checks
def _parse_robots(text: str):
    from .hoard_link.web.robots import RobotsRules
    return RobotsRules(text)


def _technical_site(ctx: _Ctx, start: str, home: _Page, out: dict) -> tuple[Any, list[str]]:
    origin = _origin(home.final)
    final = home.final
    # protocol
    if urlsplit(final).scheme != "https":
        ctx.add("technical", "https", "critical", "El sitio no se sirve por HTTPS", f"La dirección final es {final}.", "Instala un certificado y redirige todo el tráfico a https.")
    elif urlsplit(start).scheme == "https":
        plain = ctx.get("http://" + final.split("://", 1)[1], accept="any", max_bytes=2048)
        if plain.get("status") and urlsplit(plain.get("final_url") or "").scheme != "https" and plain.get("status") < 400:
            ctx.add("technical", "https-redirect", "high", "La versión http no redirige a https", "http:// responde sin pasar a https.", "Añade una redirección 301 de http a https en el servidor.")
    if home.status >= 400 or home.status == 0:
        ctx.add("technical", "status", "critical", f"La portada responde {home.status or 'sin respuesta'}", home.res.get("error") or "El servidor no devolvió un documento válido.", "Corrige el servidor para que la portada devuelva 200.")
    chain = home.res.get("redirects") or []
    if len(chain) > 2:
        ctx.add("technical", "redirect-chain", "medium", f"Cadena de {len(chain)} redirecciones hasta la portada", " → ".join(chain[:5]), "Enlaza directamente a la dirección final con una sola redirección.")
    # robots.txt
    robots = ctx.get(origin + "/robots.txt", accept="any", max_bytes=512 * 1024)
    rules = None
    sitemap_urls: list[str] = []
    if robots.get("status") == 200 and robots.get("text"):
        rules = _parse_robots(robots["text"])
        sitemap_urls = [urljoin(origin + "/", s) for s in rules.sitemaps]
        out["robots"] = {"present": True, "sitemaps": sitemap_urls}
        if not rules.allowed("*", "/"):
            ctx.add("technical", "robots-blocks-all", "critical", "robots.txt bloquea todo el sitio", "La regla de `*` prohíbe la raíz.", "Quita `Disallow: /` salvo que el sitio deba permanecer privado.")
        elif not rules.allowed("Googlebot", "/"):
            ctx.add("technical", "robots-blocks-all", "critical", "robots.txt bloquea al buscador principal", "Googlebot no puede rastrear la raíz.", "Revisa las reglas de Googlebot en robots.txt.")
        if not sitemap_urls:
            ctx.add("technical", "robots-no-sitemap", "low", "robots.txt no declara el mapa del sitio", "Falta una línea `Sitemap:`.", "Añade `Sitemap: https://tu-dominio/sitemap.xml`.")
    else:
        out["robots"] = {"present": False}
        ctx.add("technical", "robots-missing", "low", "No hay robots.txt", f"{origin}/robots.txt devuelve {robots.get('status') or 'error'}.", "Publica un robots.txt, aunque solo declare el mapa del sitio.")
    # sitemap
    candidates = sitemap_urls or [origin + "/sitemap.xml"]
    sitemap_pages: list[str] = []
    found = None
    for cand in candidates[:3]:
        sm = ctx.get(cand, accept="any", max_bytes=2 * 1024 * 1024)
        if sm.get("status") == 200 and sm.get("text"):
            found = (cand, sm)
            break
    if not found:
        ctx.add("technical", "sitemap-missing", "medium", "No se encuentra el mapa del sitio", f"Se probó {', '.join(candidates[:3])}.", "Genera un sitemap.xml con las páginas indexables y decláralo en robots.txt.")
        out["sitemap"] = {"present": False}
    else:
        cand, sm = found
        locs, nested, lastmods = _sitemap_locs(sm["text"])
        if nested:  # an index: read the first child
            child = ctx.get(nested[0], accept="any", max_bytes=2 * 1024 * 1024)
            if child.get("status") == 200:
                locs, _, lastmods = _sitemap_locs(child.get("text") or "")
        out["sitemap"] = {"present": True, "url": cand, "urls": len(locs), "index": bool(nested)}
        if not locs and not nested:
            ctx.add("technical", "sitemap-invalid", "high", "El mapa del sitio no se puede leer o está vacío", f"{cand} no contiene direcciones <loc> válidas.", "Regenera el sitemap con XML válido y direcciones absolutas.")
        else:
            offsite = [u for u in locs if not _same_site(u, final)]
            if offsite:
                ctx.add("technical", "sitemap-offsite", "medium", f"El mapa del sitio lista {len(offsite)} direcciones de otro dominio", offsite[0], "Deja solo direcciones del propio sitio.")
            sitemap_pages = [u for u in locs if _same_site(u, final)]
            bad = []
            for u in sitemap_pages[:5]:
                r = ctx.get(u, accept="html", max_bytes=300_000)
                if r.get("status", 0) >= 400 or (r.get("status", 0) == 0 and not r.get("skipped")):
                    bad.append(f"{u} ({r.get('status') or r.get('error_kind')})")
            if bad:
                ctx.add("technical", "sitemap-dead-urls", "high", f"El mapa del sitio incluye {len(bad)} direcciones que fallan", "; ".join(bad[:3]), "Retira del sitemap las páginas que no devuelven 200.")
            if locs and not lastmods:
                ctx.add("technical", "sitemap-no-lastmod", "info", "El mapa del sitio no indica fechas de modificación", "Ninguna entrada trae <lastmod>.", "Añade <lastmod> con la fecha real de cambio.")
            else:
                old = _stale_lastmod(lastmods)
                if old:
                    ctx.add("technical", "sitemap-stale", "low", "Todas las fechas del mapa del sitio tienen más de 24 meses", f"La más reciente es {old}.", "Actualiza el contenido o la fecha solo cuando cambie de verdad.", judgement=True)
    out["_sitemap_pages"] = sitemap_pages
    # security headers (homepage)
    hdr = home.headers
    missing = []
    for name, severity, why in SECURITY_HEADERS:
        if name not in hdr:
            if name == "strict-transport-security" and urlsplit(final).scheme != "https":
                continue
            missing.append(name)
            ctx.add("technical", f"header-{name}", severity, f"Falta la cabecera {name}", why, f"Configura `{name}` en el servidor o en la capa de CDN. Un alojamiento estático puro no permite cabeceras propias.", url=final)
    if "x-frame-options" not in hdr and "frame-ancestors" not in hdr.get("content-security-policy", ""):
        ctx.add("technical", "header-frame", "low", "Nada impide incrustar el sitio en otro (clickjacking)", "No hay X-Frame-Options ni `frame-ancestors`.", "Añade `X-Frame-Options: SAMEORIGIN` o `frame-ancestors 'self'`.", url=final)
    out["security_headers"] = {"missing": missing}
    # compression, cache
    if len(home.html) > 1500 and not hdr.get("content-encoding"):
        ctx.add("technical", "compression", "low", "La portada no se sirve comprimida", "No hay Content-Encoding.", "Activa gzip o brotli en el servidor.", url=final)
    if "cache-control" not in hdr and "etag" not in hdr and "last-modified" not in hdr:
        ctx.add("technical", "cache", "low", "La portada no declara caché ni validadores", "Faltan Cache-Control, ETag y Last-Modified.", "Declara una política de caché.", url=final)
    # soft 404
    ghost = f"{origin}/vitruvius-audit-{hashlib.sha1(origin.encode()).hexdigest()[:8]}-no-existe"
    g = ctx.get(ghost, accept="html", max_bytes=100_000)
    if g.get("status") == 200:
        ctx.add("technical", "soft-404", "medium", "Una dirección inexistente responde 200", f"{ghost} no devolvió 404.", "Haz que las páginas que no existen respondan 404 con una página de ayuda.")
    elif g.get("status") == 404 and len(_words(_visible_text(g.get("text") or ""))) < 3:
        ctx.add("technical", "404-empty", "low", "La página 404 está vacía", "La respuesta 404 no tiene texto visible.", "Ofrece una página 404 con enlaces a las secciones principales.")
    return rules, sitemap_pages


def _sitemap_locs(xml: str) -> tuple[list[str], list[str], list[str]]:
    locs, nested, lastmods = [], [], []
    is_index = "<sitemapindex" in xml[:2000].lower()
    for m in re.finditer(r"<(url|sitemap)\b[^>]*>(.*?)</\1>", xml, re.S | re.I):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", m.group(2), re.S | re.I)
        if not loc:
            continue
        value = loc.group(1).replace("&amp;", "&")
        (nested if is_index or m.group(1).lower() == "sitemap" else locs).append(value)
        lm = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", m.group(2), re.S | re.I)
        if lm:
            lastmods.append(lm.group(1))
    return locs, nested, lastmods


def _stale_lastmod(values: list[str]) -> str:
    dates = []
    for v in values:
        try:
            dates.append(datetime.fromisoformat(v.replace("Z", "+00:00")[:25]).replace(tzinfo=None))
        except ValueError:
            continue
    if not dates:
        return ""
    newest = max(dates)
    return newest.date().isoformat() if (datetime.now() - newest).days > 730 else ""


# ---------------------------------------------------------------------------------------------- per-page checks
def _is_shell(page: _Page) -> bool:
    """An empty document that scripts fill in: its body cannot be judged from the raw HTML."""
    return len(page.words) < 40 and (page.scan.scripts >= 1 or bool(re.search(r'id=["\'](root|app|__next)["\']', page.html)))


def _onpage(ctx: _Ctx, page: _Page, is_home: bool, shell: bool = False) -> None:
    u, s = page.final, page.scan
    title, desc = page.title, page.description
    if not title:
        ctx.add("onpage", "title-missing", "high", "Falta el título de la página", "No hay etiqueta <title>.", "Escribe un título único de 30 a 60 caracteres con el tema de la página.", url=u)
    elif len(title) < 20 or len(title) > 65:
        ctx.add("onpage", "title-length", "low", f"El título mide {len(title)} caracteres", title[:90], "Mantén el título entre 30 y 60 caracteres para que no se corte.", url=u)
    if not desc:
        ctx.add("onpage", "description-missing", "medium", "Falta la meta descripción", "No hay <meta name=\"description\">.", "Resume la página en 70 a 160 caracteres.", url=u)
    elif len(desc) < 70 or len(desc) > 165:
        ctx.add("onpage", "description-length", "low", f"La meta descripción mide {len(desc)} caracteres", desc[:120], "Mantén la descripción entre 70 y 160 caracteres.", url=u)
    h1 = [t for lvl, t in s.headings if lvl == 1 and t]
    if shell:
        ctx.add("ai", "js-dependent", "medium", "La página se pinta con JavaScript y no se pudo juzgar su contenido", f"El HTML inicial trae {len(page.words)} palabras; solo la portada se carga en un navegador.", "Comprueba que el texto principal esté en el HTML inicial o que se renderice en servidor.", url=u, judgement=True)
    elif not h1:
        ctx.add("onpage", "h1-missing", "high", "No hay encabezado H1", "La página no tiene <h1>.", "Añade un único H1 con el tema principal.", url=u)
    elif len(h1) > 1:
        ctx.add("onpage", "h1-multiple", "low", f"Hay {len(h1)} encabezados H1", "; ".join(h1[:3]), "Usa un H1 y organiza el resto con H2 y H3.", url=u)
    prev = 0
    for lvl, text in s.headings:
        if prev and lvl > prev + 1:
            ctx.add("onpage", "heading-skip", "low", f"El encabezado salta de H{prev} a H{lvl}", text[:80], "No saltes niveles: la jerarquía ayuda a lectores de pantalla y a los buscadores.", url=u)
            break
        prev = lvl
    if any(not t for _, t in s.headings):
        ctx.add("onpage", "heading-empty", "low", "Hay encabezados vacíos", "Algún <h1>–<h6> no contiene texto.", "Elimina o rellena los encabezados vacíos.", url=u)
    if not s.lang:
        ctx.add("onpage", "lang-missing", "medium", "Falta el idioma en <html>", "No hay atributo lang.", "Declara `<html lang=\"es\">` (o el idioma real).", url=u)
    viewport = s.meta("viewport")
    if not viewport:
        ctx.add("onpage", "viewport-missing", "high", "Falta la etiqueta viewport", "Sin ella la página no se adapta a móviles.", "Añade `<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">`.", url=u)
    elif "user-scalable=no" in viewport.replace(" ", "").lower() or "maximum-scale=1" in viewport.replace(" ", "").lower():
        ctx.add("onpage", "viewport-zoom", "low", "El viewport impide ampliar", viewport, "Permite el zoom del usuario.", url=u)
    og = [k for k in ("og:title", "og:description", "og:image") if not s.meta(k)]
    if og:
        ctx.add("onpage", "social-og", "low", f"Faltan etiquetas Open Graph: {', '.join(og)}", "Los enlaces compartidos mostrarán una vista previa pobre.", "Añade las etiquetas Open Graph que falten.", url=u)
    if not s.meta("twitter:card"):
        ctx.add("onpage", "social-twitter", "info", "Falta twitter:card", "Sin ella algunas redes usan una vista previa genérica.", "Añade `<meta name=\"twitter:card\" content=\"summary_large_image\">`.", url=u)
    path = urlsplit(u).path
    if len(u) > 115 or "_" in path or path != path.lower():
        ctx.add("onpage", "url-shape", "low", "La dirección es larga o poco limpia", u[:120], "Usa direcciones cortas, en minúsculas y con guiones.", url=u)
    generic = [a for a in s.anchors if (a["text"] or "").strip().lower() in _GENERIC_ANCHORS]
    if generic:
        ctx.add("onpage", "anchor-generic", "low", f"{len(generic)} enlaces con texto genérico", ", ".join(sorted({a['text'] for a in generic})[:4]), "Describe el destino en el texto del enlace.", url=u)
    empty = [a for a in s.anchors if not (a["text"] or a["aria"] or a["title"] or a["img_alt"]).strip()]
    if empty:
        ctx.add("onpage", "anchor-empty", "medium", f"{len(empty)} enlaces sin texto accesible", empty[0]["href"][:80], "Da a cada enlace texto visible, `aria-label` o una imagen con `alt`.", url=u)
    if is_home and not any("icon" in l.get("rel", "").lower() for l in s.links):
        ctx.add("onpage", "favicon", "info", "No se declara favicon", "Falta <link rel=\"icon\">.", "Declara un icono del sitio.", url=u)
    robots_meta = (s.meta("robots") + " " + page.headers.get("x-robots-tag", "")).lower()
    if "noindex" in robots_meta:
        ctx.add("technical", "noindex", "critical" if is_home else "high", "La página pide no ser indexada", robots_meta.strip()[:100], "Quita `noindex` si la página debe aparecer en buscadores.", url=u)
    canon = page.canonical
    if not canon:
        ctx.add("technical", "canonical-missing", "medium", "Falta la dirección canónica", "No hay <link rel=\"canonical\">.", "Declara la URL canónica absoluta de la página.", url=u)
    else:
        if not _same_site(canon, u):
            ctx.add("technical", "canonical-offsite", "high", "La canónica apunta a otro dominio", canon, "Apunta la canónica a la propia página salvo que la copia sea intencionada.", url=u)
        elif _norm(canon).rstrip("/") != _norm(u).rstrip("/"):
            ctx.add("technical", "canonical-other", "low", "La canónica apunta a otra página del sitio", canon, "Comprueba que la página debe consolidarse con esa otra.", url=u)
    insecure = [src for tag, src in s.resources if src.startswith("http://")]
    if urlsplit(u).scheme == "https" and insecure:
        ctx.add("technical", "mixed-content", "high", f"{len(insecure)} recursos se piden por http", insecure[0][:100], "Sirve todos los recursos por https.", url=u)


def _content_page(ctx: _Ctx, page: _Page, is_home: bool, article_like: bool) -> None:
    u = page.final
    n = len(page.words)
    if n < 150 and page.status == 200:
        ctx.add("content", "thin", "medium" if is_home else "low", f"Contenido escaso: {n} palabras", "Hay poco texto visible para entender la página.", "Explica el tema con texto propio: qué es, para quién y qué aporta.", url=u, evidence={"words": n})
    sentences = [x for x in re.split(r"[.!?…]+\s", page.text) if len(_words(x)) > 2]
    if sentences:
        avg = sum(len(_words(x)) for x in sentences) / len(sentences)
        if avg > 28:
            ctx.add("content", "long-sentences", "low", f"Frases largas: {avg:.0f} palabras de media", "Las frases muy largas cuestan de leer y de extraer como respuesta.", "Divide las frases por encima de 25 palabras.", url=u, evidence={"avg_words": round(avg, 1)})
    content_words = [w for w in page.words if w not in _STOPWORDS and len(w) > 3]
    if len(content_words) > 120:
        top, count = Counter(content_words).most_common(1)[0]
        if count / len(content_words) > 0.06 and count > 12:
            ctx.add("content", "keyword-stuffing", "low", f"La palabra «{top}» se repite en exceso", f"{count} de {len(content_words)} palabras de contenido.", "Varía el vocabulario y escribe para personas.", url=u)
    if len(page.internal_links()) < 2 and not is_home and page.status == 200:
        ctx.add("content", "few-internal-links", "low", "Pocos enlaces internos", "La página enlaza a menos de dos páginas del sitio.", "Enlaza a páginas relacionadas con texto descriptivo.", url=u)
    if article_like:
        has_date = bool(page.scan.meta("article:published_time") or page.scan.meta("date") or re.search(r"<time\b", page.html, re.I))
        has_author = bool(page.scan.meta("author") or re.search(r"\bautor\b|\bby\b|rel=[\"']author", page.html, re.I))
        if not (has_date and has_author):
            ctx.add("content", "byline", "info", "Un artículo sin autor o fecha visibles", "No se detecta autoría o fecha de publicación.", "Muestra quién escribe y cuándo se publicó o actualizó.", url=u, judgement=True)


def _schema_page(ctx: _Ctx, page: _Page, is_home: bool, entity_types: set[str]) -> None:
    from .hoard_link.web import meta as web_meta
    u = page.final
    if page.ld_errors:
        ctx.add("schema", "invalid", "high", f"{len(page.ld_errors)} bloques JSON-LD no se pueden leer", "; ".join(page.ld_errors[:2]), "Valida el JSON-LD: comillas, comas finales y llaves.", url=u)
    nodes = list(web_meta.jsonld_nodes(page.blocks, None, skip=()))
    if not page.scan.ld:
        if is_home:
            ctx.add("schema", "none", "medium", "La portada no tiene datos estructurados", "No hay bloques JSON-LD.", "Añade al menos Organization o Person y WebSite con `sameAs`.", url=u, evidence={"microdata": page.scan.microdata})
        return
    for block in page.blocks:
        blocks = block if isinstance(block, list) else [block]
        for b in blocks:
            if isinstance(b, dict) and "@context" not in b and "@graph" not in b:
                ctx.add("schema", "context", "medium", "Un bloque JSON-LD no declara @context", "Falta `\"@context\": \"https://schema.org\"`.", "Añade @context a cada bloque.", url=u)
                break
    for node in nodes:
        kinds = web_meta._types(node)
        entity_types |= kinds
        for kind in kinds:
            need = SCHEMA_PROPS.get(kind)
            if need:
                gone = [p for p in need if not node.get(p)]
                if gone:
                    ctx.add("schema", f"props-{kind}", "medium", f"{kind} sin propiedades recomendadas: {', '.join(gone)}", "Los buscadores esperan estas propiedades.", "Complétalas con datos reales de la página.", url=u)
        if kinds & {"organization", "person"} and not node.get("sameAs") and is_home:
            ctx.add("schema", "sameas", "low", "La entidad no enlaza sus perfiles (sameAs)", "Sin `sameAs` los modelos y buscadores identifican peor quién es.", "Lista los perfiles oficiales (LinkedIn, GitHub, etc.) en `sameAs`.", url=u)
        if "faqpage" in kinds or "howto" in kinds:
            ctx.add("schema", "restricted-rich-result", "info", "FAQPage/HowTo ya no generan resultados enriquecidos en la mayoría de sitios", "Google los limitó a sitios concretos.", "Mantenlos solo si ayudan a describir el contenido.", url=u)
    canon = page.canonical
    for node in nodes:
        if node.get("url") and canon and web_meta._types(node) & {"webpage", "website"} and _norm(str(node["url"])).rstrip("/") not in (_norm(canon).rstrip("/"), _origin(canon)):
            ctx.add("schema", "url-mismatch", "low", "La URL del JSON-LD no coincide con la canónica", str(node["url"])[:100], "Usa la misma dirección en ambos sitios.", url=u)
            break


def _images_page(ctx: _Ctx, page: _Page, size_budget: dict) -> None:
    u = page.final
    imgs = page.scan.images
    if not imgs:
        return
    no_alt = [i for i in imgs if "alt" not in i]
    if no_alt:
        ctx.add("images", "alt-missing", "medium", f"{len(no_alt)} de {len(imgs)} imágenes sin atributo alt", (no_alt[0].get("src") or "")[:90], "Describe cada imagen informativa; usa `alt=\"\"` en las decorativas.", url=u)
    junk = [i for i in imgs if i.get("alt") and re.fullmatch(r"(img|image|dsc|photo|screenshot)[-_ ]?\d*(\.\w+)?", i["alt"].strip(), re.I)]
    if junk:
        ctx.add("images", "alt-filename", "low", f"{len(junk)} imágenes con un alt que parece un nombre de archivo", junk[0]["alt"][:60], "Escribe un alt que describa lo que se ve.", url=u)
    no_dim = [i for i in imgs if not (i.get("width") and i.get("height"))]
    if no_dim:
        ctx.add("images", "dimensions", "low", f"{len(no_dim)} imágenes sin width y height", (no_dim[0].get("src") or "")[:90], "Declara las dimensiones para reservar espacio y evitar saltos de maquetación.", url=u)
    late = [i for i in imgs[2:] if (i.get("loading") or "").lower() != "lazy"]
    if len(imgs) > 4 and late:
        ctx.add("images", "lazy", "low", f"{len(late)} imágenes por debajo de la primera pantalla sin carga diferida", "Faltan `loading=\"lazy\"`.", "Aplica `loading=\"lazy\"` salvo a las imágenes visibles al abrir la página.", url=u)
    legacy = [i for i in imgs if re.search(r"\.(jpe?g|png|gif|bmp)(\?|$)", i.get("src", ""), re.I)]
    modern = [i for i in imgs if re.search(r"\.(webp|avif|svg)(\?|$)", i.get("src", ""), re.I)]
    if len(legacy) >= 3 and not modern:
        ctx.add("images", "format", "low", f"{len(legacy)} imágenes en formatos antiguos y ninguna en WebP o AVIF", (legacy[0].get("src") or "")[:90], "Sirve WebP o AVIF para fotografías.", url=u)
    for i in imgs:
        src = i.get("src", "")
        if not src or src.startswith("data:") or size_budget["left"] <= 0:
            continue
        full = urljoin(u, src)
        if full in size_budget["seen"]:
            continue
        size_budget["seen"].add(full)
        size_budget["left"] -= 1
        r = ctx.get(full, accept="any", max_bytes=2048)
        length = int((r.get("headers") or {}).get("content-length") or 0)
        if r.get("status", 0) >= 400:
            ctx.add("images", "broken", "high", "Una imagen no carga", f"{full[:100]} responde {r['status']}.", "Corrige la ruta o elimina la imagen.", url=u)
        elif length > 1_000_000:
            ctx.add("images", "heavy", "high", f"Imagen de {length // 1024} KB", full[:100], "Comprime y redimensiona la imagen.", url=u)
        elif length > 300_000:
            ctx.add("images", "large", "medium", f"Imagen de {length // 1024} KB", full[:100], "Comprime la imagen o sirve una versión más pequeña con srcset.", url=u)


# ---------------------------------------------------------------------------------------------- AI / GEO
def _ai_checks(ctx: _Ctx, home: _Page, raw: _Page, rules: Any, out: dict, rendered_len: Optional[int]) -> None:
    """`home` is the page the checks read (the rendered DOM when the raw HTML is an empty shell); `raw` is the HTML a crawler gets without scripts."""
    origin = _origin(home.final)
    table = []
    for token, operator, purpose in AI_CRAWLERS:
        allowed = True if rules is None else bool(rules.allowed(token, "/"))
        table.append({"crawler": token, "operator": operator, "purpose": purpose, "allowed": allowed})
    out["ai_crawlers"] = table
    blocked_search = [r["crawler"] for r in table if r["purpose"] in ("search", "user") and not r["allowed"]]
    blocked_train = [r["crawler"] for r in table if r["purpose"] == "training" and not r["allowed"]]
    if blocked_search:
        ctx.add("ai", "search-blocked", "high", f"Se bloquea a rastreadores que citan: {', '.join(blocked_search[:4])}", "Estos rastreadores leen páginas para mostrarlas como fuente en respuestas de IA o a petición de una persona.", "Permítelos si quieres ser citado. Bloquear el entrenamiento no exige bloquear estos.")
    if blocked_train:
        ctx.add("ai", "training-blocked", "info", f"Se bloquea el entrenamiento: {', '.join(blocked_train[:4])}", "Es una decisión legítima. No impide que te citen los rastreadores de búsqueda.", "Mantén la decisión si es intencionada; entrenamiento y citación son permisos distintos.", judgement=True)
    named = {c[0].lower() for c in AI_CRAWLERS}
    if rules is not None and not blocked_search and not blocked_train and not any(t in named for g in rules.groups for t in g[0]):
        ctx.add("ai", "no-policy", "info", "robots.txt no distingue rastreadores de IA", "Todos están permitidos por omisión.", "Declara de forma explícita qué rastreadores de entrenamiento permites y cuáles de búsqueda.", judgement=True)
    llms = ctx.get(origin + "/llms.txt", accept="any", max_bytes=200_000)
    if llms.get("status") == 200 and llms.get("text"):
        first = (llms["text"].lstrip().splitlines() or [""])[0]
        out["llms_txt"] = {"present": True}
        if not first.startswith("# ") or "](" not in llms["text"]:
            ctx.add("ai", "llms-format", "low", "llms.txt no sigue el formato propuesto", "Debe abrir con un H1 y enlazar páginas en Markdown.", "Empieza con `# Nombre` y lista enlaces `[título](url)`.")
    else:
        out["llms_txt"] = {"present": False}
        ctx.add("ai", "llms-missing", "info", "No hay llms.txt", "Es una propuesta sin respaldo de los buscadores; su efecto en citas no está demostrado.", "Valora publicarlo como resumen del sitio para agentes.", judgement=True)
    raw_words = len(raw.words)
    if rendered_len is not None:
        if raw_words < 60 and rendered_len > 400 and rendered_len > 3 * max(1, len(raw.text)):
            ctx.add("ai", "js-dependent", "high", "El contenido principal solo aparece al ejecutar JavaScript", f"El HTML inicial trae {raw_words} palabras y la página renderizada {rendered_len} caracteres.", "Entrega el contenido en el HTML (renderizado en servidor o estático): muchos rastreadores de IA no ejecutan scripts.", evidence={"raw_words": raw_words, "rendered_chars": rendered_len})
    elif raw_words < 40 and (raw.scan.scripts >= 3 or re.search(r'id=["\'](root|app|__next)["\']', raw.html)):
        ctx.add("ai", "js-dependent", "medium", "Parece que el contenido se pinta con JavaScript", f"El HTML inicial trae {raw_words} palabras.", "Comprueba que el texto principal esté en el HTML inicial.", judgement=True)
    robots_meta = (raw.scan.meta("robots") + " " + raw.headers.get("x-robots-tag", "")).lower()
    if re.search(r"nosnippet|max-snippet:\s*0", robots_meta):
        ctx.add("ai", "nosnippet", "medium", "`nosnippet` impide mostrar fragmentos en respuestas generadas", robots_meta.strip()[:100], "Quita `nosnippet` si quieres aparecer como fuente.")
    if "noai" in robots_meta:
        ctx.add("ai", "noai", "info", "La página declara `noai`", robots_meta.strip()[:100], "Es una decisión del propietario; no la respetan todos los rastreadores.", judgement=True)
    questions = [t for lvl, t in home.scan.headings if t.endswith("?")]
    lists = len(re.findall(r"<(ul|ol|table)\b", home.html, re.I))
    out["citability"] = {"question_headings": len(questions), "lists_and_tables": lists, "words": raw_words}
    ctx.add("ai", "citability", "info", "Revisa si el texto responde con frases citables", f"{len(questions)} encabezados en forma de pregunta, {lists} listas o tablas, {raw_words} palabras.", "Abre cada sección con una respuesta directa de 40 a 60 palabras y respáldala con datos y fuentes.", judgement=True)


def _judgement_content(ctx: _Ctx, home: _Page) -> None:
    ctx.add("content", "eeat", "info", "Experiencia, autoridad y confianza (E-E-A-T)", "Una medición no puede decidir si la autoría es creíble ni si el contenido refleja experiencia real.", "Revisa: autor identificable, credenciales, fuentes citadas, datos de contacto y una página «Acerca de».", judgement=True)
    ctx.add("content", "intent", "info", "Encaje con la intención de búsqueda", "Que el contenido responda a lo que busca la persona requiere criterio humano.", "Para cada página principal, escribe la pregunta que resuelve y comprueba que el primer párrafo la contesta.", judgement=True)
    ctx.add("content", "originality", "info", "Originalidad y profundidad", "Una medición no distingue texto original de texto genérico.", "Comprueba que cada página aporta datos, ejemplos o criterio propios.", judgement=True)
    trust = [w for w in ("contact", "contacto", "about", "acerca", "sobre", "privacidad", "privacy", "aviso legal") if any(w in (a["href"] + " " + a["text"]).lower() for a in home.scan.anchors)]
    if not trust:
        ctx.add("content", "trust-links", "low", "La portada no enlaza contacto, «Acerca de» ni privacidad", "No se detectan señales de confianza básicas.", "Enlaza una página de contacto y otra sobre quién está detrás.", url=home.final)


# ---------------------------------------------------------------------------------------------- Core Web Vitals
VITAL_LIMITS = {  # metric -> (good, poor) Google's thresholds, lab values in ms (cls unitless)
    "lcp_ms": (2500, 4000), "cls": (0.1, 0.25), "inp_ms": (200, 500), "fcp_ms": (1800, 3000), "ttfb_ms": (800, 1800), "tbt_ms": (200, 600),
}
VITAL_NAMES = {"lcp_ms": "LCP", "cls": "CLS", "inp_ms": "INP", "fcp_ms": "FCP", "ttfb_ms": "TTFB", "tbt_ms": "TBT"}


def rate_vital(metric: str, value: float) -> str:
    good, poor = VITAL_LIMITS[metric]
    return "good" if value <= good else ("poor" if value > poor else "needs-improvement")


def _cwv(ctx: _Ctx, home: _Page, vitals: Optional[dict], out: dict) -> bool:
    if not vitals or vitals.get("error"):
        reason = (vitals or {}).get("hint") or (vitals or {}).get("error") or "No se ha podido medir en un navegador real."
        out["vitals"] = {"measured": False, "reason": reason}
        ctx.limits.append("Core Web Vitals no medidos: " + str(reason))
        ctx.add("cwv", "unavailable", "info", "No se han podido medir los Core Web Vitals", str(reason)[:200], "Instala Chromium para Playwright (`python -m playwright install chromium`) y repite la auditoría.")
        return False
    m = vitals.get("metrics") or {}
    out["vitals"] = {"measured": True, **{k: vitals.get(k) for k in ("profile", "conditions", "metrics", "ratings", "js_errors", "note") if k in vitals}}
    ratings: dict[str, str] = {}
    for key, (good, poor) in VITAL_LIMITS.items():
        value = m.get(key)
        if value is None:
            continue
        rating = rate_vital(key, value)
        ratings[key] = rating
        if rating == "good":
            continue
        name = VITAL_NAMES[key]
        sev = {"lcp_ms": ("high", "medium"), "cls": ("high", "medium"), "inp_ms": ("high", "medium"), "fcp_ms": ("medium", "low"), "ttfb_ms": ("medium", "low"), "tbt_ms": ("medium", "low")}[key][0 if rating == "poor" else 1]
        unit = "" if key == "cls" else " ms"
        shown = f"{value:.3f}" if key == "cls" else f"{value:.0f}"
        ctx.add("cwv", key.removesuffix("_ms"), sev, f"{name} {shown}{unit}: {'malo' if rating == 'poor' else 'mejorable'}", f"Umbral bueno {good}{unit}, malo por encima de {poor}{unit}. Medida de laboratorio ({(vitals.get('conditions') or {}).get('label', 'móvil')}).", _CWV_ADVICE[key], url=home.final, evidence={"value": value, "good": good, "poor": poor})
    out["vitals"]["ratings"] = ratings
    weight = m.get("transfer_bytes")
    if weight and weight > 3_000_000:
        ctx.add("cwv", "weight", "medium", f"La portada descarga {weight / 1_000_000:.1f} MB", f"{m.get('requests', '?')} peticiones.", "Reduce imágenes, fuentes y scripts.", url=home.final)
    if vitals.get("js_errors"):
        ctx.add("cwv", "js-errors", "low", f"{len(vitals['js_errors'])} errores de JavaScript al cargar", str(vitals["js_errors"][0])[:120], "Corrige los errores de consola.", url=home.final)
    return True


_CWV_ADVICE = {
    "lcp_ms": "Optimiza el elemento más grande de la primera pantalla: comprime la imagen, precárgala y evita recursos que bloqueen el pintado.",
    "cls": "Reserva espacio para imágenes, anuncios y fuentes; no insertes contenido sobre lo ya visible.",
    "inp_ms": "Reduce el trabajo de JavaScript en los manejadores de eventos y divide las tareas largas.",
    "fcp_ms": "Reduce CSS y JavaScript que bloquean el pintado y sirve el HTML cuanto antes.",
    "ttfb_ms": "Acelera la respuesta del servidor: caché, CDN y menos redirecciones.",
    "tbt_ms": "Divide las tareas largas de JavaScript y retrasa los scripts que no son críticos.",
}


# ---------------------------------------------------------------------------------------------- broken links
def _broken_links(ctx: _Ctx, pages: list[_Page], max_internal: int, max_external: int) -> dict:
    seen_pages = {_norm(p.final) for p in pages}
    internal: dict[str, str] = {}
    external: dict[str, str] = {}
    for p in pages:
        for link in p.internal_links():
            if link not in seen_pages:
                internal.setdefault(link, p.final)
        for link in p.external_links():
            external.setdefault(link, p.final)
    checked = {"internal": 0, "external": 0, "broken": []}
    for kind, items, cap, sev in (("internal", internal, max_internal, "high"), ("external", external, max_external, "medium")):
        for link, source in list(items.items())[:cap]:
            r = ctx.get(link, accept="any", max_bytes=2048)
            if r.get("skipped"):
                break
            checked[kind] += 1
            status = r.get("status", 0)
            if status >= 400 or (status == 0 and r.get("error_kind") in ("dns", "refused", "tls")):
                checked["broken"].append({"url": link, "status": status or r.get("error_kind"), "found_on": source})
                if status in (401, 403, 429, 999) and kind == "external":
                    continue  # the site refuses automated visitors: not proof that it is broken
                ctx.add("technical", f"broken-{kind}", sev, f"Enlace {kind == 'internal' and 'interno' or 'externo'} roto: {status or r.get('error_kind')}", link[:140], "Corrige o elimina el enlace.", url=source, evidence={"target": link, "status": status})
    return checked


# ---------------------------------------------------------------------------------------------- crawl
def _discover(ctx: _Ctx, home: _Page, sitemap_pages: list[str], max_pages: int) -> list[_Page]:
    pages = [home]
    seen = {_norm(home.final)}
    queue: list[str] = []
    for u in sitemap_pages + home.internal_links():
        n = _norm(u)
        if n in seen or n in queue or urlsplit(n).path.lower().endswith(_SKIP_EXT):
            continue
        queue.append(n)
    for n in queue:
        if len(pages) >= max_pages:
            break
        r = ctx.get(n, accept="html", max_bytes=1_500_000)
        if r.get("skipped"):
            break
        if r.get("status") == 200 and "html" in (r.get("content_type") or r.get("headers", {}).get("content-type") or "html").lower():
            page = _Page(n, r)
            fin = _norm(page.final)
            if fin not in seen:
                seen.add(fin)
                pages.append(page)
    return pages


# ---------------------------------------------------------------------------------------------- scoring and plan
def _score(findings: list[dict], measured: dict[str, bool]) -> dict[str, Optional[int]]:
    scores: dict[str, Optional[int]] = {}
    for cat in CATEGORIES:
        if not measured.get(cat, True):
            scores[cat] = None
            continue
        groups: dict[str, list[int]] = {}
        for f in findings:
            if f["category"] != cat or f["judgement"]:
                continue
            groups.setdefault(f["id"].split("@")[0], []).append(PENALTY[f["severity"]])
        penalty = 0
        for key, vals in groups.items():
            vals.sort(reverse=True)
            penalty += sum(vals[:REPEAT_CAP])
        scores[cat] = max(0, 100 - penalty)
    live = [(CATEGORIES[c]["weight"], s) for c, s in scores.items() if s is not None]
    scores["total"] = round(sum(w * s for w, s in live) / sum(w for w, _ in live)) if live else None
    return scores


def _plan(findings: list[dict]) -> dict:
    def item(f: dict) -> dict:
        row = {"id": f["id"], "category": f["category"], "severity": f["severity"], "title": f["title"]}
        if f.get("url"):
            row["url"] = f["url"]
        return row
    real = [f for f in findings if not f["judgement"]]
    order = {s: i for i, s in enumerate(SEVERITIES)}
    phases = [
        {"phase": 1, "name": "Corregir ya", "timeframe": "esta semana", "items": [item(f) for f in sorted(real, key=lambda f: order[f["severity"]]) if f["severity"] in ("critical", "high")]},
        {"phase": 2, "name": "Mejorar", "timeframe": "2 a 4 semanas", "items": [item(f) for f in real if f["severity"] == "medium"]},
        {"phase": 3, "name": "Pulir y vigilar", "timeframe": "continuo", "items": [item(f) for f in real if f["severity"] in ("low", "info")]},
        {"phase": 4, "name": "Revisión humana", "timeframe": "cuando haya criterio editorial", "items": [item(f) for f in findings if f["judgement"]]},
    ]
    return {"phases": phases}


def _diff(findings: list[dict], previous: Optional[dict]) -> Optional[dict]:
    if not previous:
        return None
    before = {f["id"] for f in previous.get("findings", []) if not f.get("judgement")}
    now = {f["id"] for f in findings if not f["judgement"]}
    return {"id": previous.get("id"), "audited_at": previous.get("audited_at"), "score": previous.get("score"),
            "new": sorted(now - before), "fixed": sorted(before - now), "persisting": len(now & before)}


# ---------------------------------------------------------------------------------------------- public API
def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise AuditError("Falta la dirección del sitio.")
    if "://" not in raw:
        raw = "https://" + raw
    p = urlsplit(raw)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise AuditError("La dirección debe ser http o https.")
    if p.username or p.password:
        raise AuditError("La dirección no puede llevar credenciales.")
    return _norm(raw)


def audit(url: str, *, fetch: Callable[..., dict], vitals: Optional[Callable[[str], dict]] = None, max_pages: int = 10, check_links: bool = True,
          budget_s: float = 150.0, max_requests: int = 160, previous: Optional[dict] = None, clock: Callable[[], float] = time.time) -> dict:
    """Audit `url` and return the envelope (see docs/SITE-AUDIT.md). `fetch(url, accept=, max_bytes=)` returns a dict with status,
    final_url, headers, text, size, error; `vitals(url)` returns the measurements of a real browser load (or an error dict)."""
    started = clock()
    start = normalize_url(url)
    ctx = _Ctx(fetch, budget_s, max_requests)
    res = ctx.get(start, accept="html", max_bytes=2_000_000)
    envelope: dict[str, Any] = {"ok": True, "kind": "site_audit", "schema": SCHEMA, "url": start}
    if res.get("status", 0) == 0:
        return {**envelope, "ok": False, "error": res.get("error") or "No se pudo abrir la dirección.", "error_kind": res.get("error_kind") or "network",
                "hint": "Comprueba la dirección, el DNS y que el sitio sea público."}
    raw_home = _Page(start, res)
    home = raw_home
    out: dict[str, Any] = {}
    vitals_result = None
    if vitals is not None:
        try:
            vitals_result = vitals(raw_home.final)
        except Exception as error:  # noqa: BLE001
            vitals_result = {"error": f"{type(error).__name__}: {error}"[:200]}
    rendered_html = (vitals_result or {}).pop("rendered_html", None) if isinstance(vitals_result, dict) else None
    rendered_dom = False
    if rendered_html and len(raw_home.words) < 60 and len(_words(_visible_text(rendered_html))) > 2 * max(1, len(raw_home.words)):
        home = _Page(start, {**res, "text": rendered_html})  # an empty shell filled by scripts: the page checks read what a rendering crawler indexes
        rendered_dom = True
        ctx.limits.append("El HTML inicial está casi vacío: las comprobaciones de página se hicieron sobre el DOM renderizado; ver `ai.js-dependent` para quien no ejecuta scripts.")
    rules, sitemap_pages = _technical_site(ctx, start, raw_home, out)
    pages = _discover(ctx, home, out.pop("_sitemap_pages", sitemap_pages), max(1, min(int(max_pages), 40)))
    entity_types: set[str] = set()
    size_budget = {"left": 24, "seen": set()}
    titles: dict[str, list[str]] = {}
    descs: dict[str, list[str]] = {}
    hashes: dict[str, list[str]] = {}
    for i, page in enumerate(pages):
        is_home = i == 0
        if page.status != 200:
            continue
        shell = (not is_home or not rendered_dom) and _is_shell(page)
        _onpage(ctx, page, is_home, shell)
        article_like = bool(re.search(r"/(blog|post|posts|articulo|articulos|noticias|news)/", page.final)) or any(
            t in ("article", "blogposting", "newsarticle") for t in _ld_types(page))
        if not shell:
            _content_page(ctx, page, is_home, article_like)
        _schema_page(ctx, page, is_home, entity_types)
        _images_page(ctx, page, size_budget)
        if page.title:
            titles.setdefault(page.title.strip().lower(), []).append(page.final)
        if page.description:
            descs.setdefault(page.description.strip().lower(), []).append(page.final)
        if len(page.words) > 80:
            hashes.setdefault(hashlib.sha1(" ".join(page.words).encode()).hexdigest(), []).append(page.final)
    for kind, group, sev, label in (("title", titles, "medium", "título"), ("description", descs, "medium", "meta descripción")):
        for text, urls in group.items():
            if len(urls) > 1:
                ctx.add("onpage", f"{kind}-duplicate", sev, f"{len(urls)} páginas comparten {label}", text[:100], f"Escribe una {label} distinta para cada página.", url=urls[1], evidence={"pages": urls[:5]})
    for urls in hashes.values():
        if len(urls) > 1:
            ctx.add("content", "duplicate", "high", f"{len(urls)} páginas tienen el mismo texto", ", ".join(urls[:3]), "Unifica las copias con una canónica o redirección, o escribe contenido distinto.", url=urls[1], evidence={"pages": urls[:5]})
    linked = {_norm(l) for p in pages for l in p.internal_links()}
    orphans = [u for u in sitemap_pages if _norm(u) not in linked and _norm(u) != _norm(home.final)]
    if orphans and len(pages) > 1:
        ctx.add("content", "orphans", "low", f"{len(orphans)} páginas del mapa del sitio no reciben enlaces internos", orphans[0], "Enlaza esas páginas desde otras relacionadas.")
    if not entity_types & {"organization", "person", "localbusiness"} and home.scan.ld:
        ctx.add("schema", "no-entity", "low", "No se declara la entidad (Organization o Person)", "Los datos estructurados no identifican quién es el sitio.", "Añade Organization o Person con nombre, URL y `sameAs`.", url=home.final)
    links = _broken_links(ctx, pages, 40, 15) if check_links else {"internal": 0, "external": 0, "broken": []}
    measured_cwv = _cwv(ctx, home, vitals_result, out)
    rendered = (vitals_result or {}).get("rendered_text_chars") if measured_cwv else None
    _ai_checks(ctx, home, raw_home, rules, out, rendered)
    _judgement_content(ctx, home)
    if ctx.truncated:
        ctx.limits.append("Se alcanzó el límite de peticiones o de tiempo: no se revisaron todas las páginas ni todos los enlaces.")
    ctx.limits.append("Contenido, E-E-A-T e intención de búsqueda se marcan como juicio y no puntúan.")
    ctx.limits.append("Las métricas de rendimiento son de laboratorio (un navegador, una carga), no datos de usuarios reales.")
    findings = sorted(ctx.findings, key=lambda f: (SEVERITIES.index(f["severity"]), f["category"], f["id"]))
    measured = {c: True for c in CATEGORIES}
    measured["cwv"] = measured_cwv
    scores = _score(findings, measured)
    counts = {s: sum(1 for f in findings if f["severity"] == s and not f["judgement"]) for s in SEVERITIES}
    cats = []
    for cid, meta in CATEGORIES.items():
        cats.append({"id": cid, "name": meta["name"], "weight": meta["weight"], "score": scores[cid], "measured": measured[cid],
                     "findings": [{k: v for k, v in f.items() if k != "category"} for f in findings if f["category"] == cid]})
    envelope.update({
        "final_url": home.final, "audited_at": datetime.fromtimestamp(clock(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_s": round(clock() - started, 1), "score": scores["total"], "scores": scores,
        "summary": {"score": scores["total"], "pages_audited": len(pages), "requests": ctx.requests, "counts": counts,
                    "findings_total": len(findings), "judgement_total": sum(1 for f in findings if f["judgement"]),
                    "categories_measured": [c for c, ok in measured.items() if ok], "categories_unmeasured": [c for c, ok in measured.items() if not ok],
                    "truncated": ctx.truncated, "links_checked": {"internal": links["internal"], "external": links["external"], "broken": len(links["broken"])}},
        "categories": cats,
        "findings": [{"id": f["id"], "category": f["category"], "severity": f["severity"], "title": f["title"], "judgement": f["judgement"],
                      **({"url": f["url"]} if f.get("url") else {})} for f in findings],
        "action_plan": _plan(findings),
        "pages": [{"url": p.final, "status": p.status, "title": p.title[:90], "words": len(p.words), **({"rendered": True} if p is home and rendered_dom else {})} for p in pages],
        "limits": ctx.limits, "fixed_at": None, **{k: v for k, v in out.items() if not k.startswith("_")},
    })
    diff = _diff(findings, previous)
    if diff:
        envelope["previous"] = diff
    return envelope


def _ld_types(page: _Page) -> set[str]:
    from .hoard_link.web import meta as web_meta
    out: set[str] = set()
    for node in web_meta.jsonld_nodes(page.blocks, None, skip=()):
        out |= web_meta._types(node)
    return out


# ---------------------------------------------------------------------------------------------- fetcher and storage
def make_fetcher(allow_local: bool = False) -> tuple[Callable[..., dict], Callable[[], None]]:
    """A `fetch` over the shared polite fetcher (SSRF policy at every hop). Returns `(fetch, close)`."""
    from .hoard_link.web import safety
    from .hoard_link.web.fetch import Fetcher

    fetcher = Fetcher(profile=safety.OPERATOR_LOCAL if allow_local else safety.PUBLIC, min_interval_s=0.15, timeout_s=20, retries=1)

    def fetch(url: str, *, accept: str = "html", max_bytes: Optional[int] = None) -> dict:
        fr = fetcher.get(url, tier="http", accept="html" if accept == "html" else "any", respect_robots=False, max_bytes=max_bytes, timeout=20)
        text = fr.text or ""
        size = len(fr.body) if fr.body is not None else len(text.encode("utf-8", "ignore"))
        return {"ok": fr.ok, "url": url, "final_url": fr.final_url or url, "status": fr.status, "headers": fr.headers, "text": text, "size": size,
                "content_type": fr.content_type, "elapsed_ms": fr.elapsed_ms, "redirects": fr.redirects, "error": fr.error, "error_kind": fr.error_kind,
                "truncated": fr.truncated}

    return fetch, fetcher.close


class ReportStore:
    """Reports kept as JSON under `<data>/site-audits/`: the last one of a url can be reused and compared."""

    def __init__(self, root: Path):
        self.root = Path(root) / "site-audits"

    def save(self, report: dict) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        stamp = (report.get("audited_at") or "").replace("-", "").replace(":", "").replace("T", "-").rstrip("Z")
        digest = hashlib.sha1(report["url"].encode()).hexdigest()[:8]
        n = 1
        while (self.root / f"{stamp}-{n:02d}-{digest}.json").exists():  # two audits of one url inside the same second keep both, in order
            n += 1
        rid = f"{stamp}-{n:02d}-{digest}"
        report["id"] = rid
        (self.root / f"{rid}.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        return rid

    def get(self, rid: str) -> Optional[dict]:
        if not re.fullmatch(r"[0-9a-z-]{8,40}", rid or ""):
            return None
        path = self.root / f"{rid}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def list(self, url: Optional[str] = None, limit: int = 30) -> list[dict]:
        if not self.root.exists():
            return []
        rows = []
        for path in sorted(self.root.glob("*.json"), reverse=True):
            try:
                r = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if url and r.get("url") != url:
                continue
            rows.append({"id": r.get("id", path.stem), "url": r.get("url"), "audited_at": r.get("audited_at"), "score": r.get("score"),
                         "counts": (r.get("summary") or {}).get("counts", {})})
            if len(rows) >= limit:
                break
        return rows

    def latest(self, url: str) -> Optional[dict]:
        rows = self.list(url, 1)
        return self.get(rows[0]["id"]) if rows else None


def run(services: Any, url: str, *, max_pages: int = 10, check_links: bool = True, vitals: bool = True, fresh: bool = False, max_age_s: int = 600) -> dict:
    """The audit as the tools, the API and the screen use it: reuses a report younger than `max_age_s` unless `fresh`, measures the
    vitals in the worker's browser, saves the report and compares it with the previous one of the same url."""
    start = normalize_url(url)
    store = ReportStore(services.config.data_dir)
    last = store.latest(start)
    if last and not fresh:
        age = time.time() - datetime.strptime(last["audited_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        if age < max_age_s:
            return {**last, "from_cache": True, "age_s": int(age)}
    fetch, close = make_fetcher(bool(services.config.allow_local_urls))
    try:
        def measure(target: str) -> dict:
            problem = services.browser.url_problem(target)
            if problem:
                return {"error": "url refused", "hint": problem}
            return services.browser._submit("vitals", {"url": target, "profile": "mobile", "throttle": True})
        report = audit(start, fetch=fetch, vitals=measure if vitals else None, max_pages=max_pages, check_links=check_links, previous=last)
    finally:
        close()
    if report.get("ok"):
        store.save(report)
    report["from_cache"] = False
    return report
