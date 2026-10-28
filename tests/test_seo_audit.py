"""The SEO/GEO audit: every check against fake sites, the scoring rules, the envelope contract and the vitals job."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from vitruvius_hoard import seo_audit
from vitruvius_hoard.agent_tools import TOOLS, call_tool

ORIGIN = "https://site.test"
GOOD_HEADERS = {"strict-transport-security": "max-age=31536000", "content-security-policy": "default-src 'self'; frame-ancestors 'self'",
                "x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "permissions-policy": "camera=()",
                "content-encoding": "gzip", "cache-control": "max-age=600", "content-type": "text/html"}
PARAGRAPH = ("Diseño sistemas que se pueden usar a diario. Cada proyecto empieza con una pregunta concreta, sigue con una prueba medida y termina con "
             "un resultado que otra persona puede repetir. Aquí cuento cómo trabajo, qué herramientas uso y por qué elijo unas sobre otras. ")


def page(title="Portafolio de Ana Ruiz, ingeniera de software", desc="Proyectos de ingeniería de software de Ana Ruiz: sistemas, herramientas y artículos técnicos con resultados medidos.",
         h1="Ana Ruiz, ingeniera de software", extra_head="", body="", canonical=None, path="/", lang="es", words=5, images="", links=""):
    canon = canonical if canonical is not None else f'<link rel="canonical" href="{ORIGIN}{path}">'
    ld = json.dumps({"@context": "https://schema.org", "@type": "Person", "name": "Ana Ruiz", "url": ORIGIN + "/", "sameAs": ["https://github.com/ana"]})
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{title}</title><meta name="description" content="{desc}">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><meta property="og:title" content="{title}"><meta property="og:description" content="{desc}">'
            f'<meta property="og:image" content="{ORIGIN}/og.png"><meta name="twitter:card" content="summary"><link rel="icon" href="/f.ico">{canon}'
            f'<script type="application/ld+json">{ld}</script>{extra_head}</head><body><main><h1>{h1}</h1><h2>Contacto</h2><p>{PARAGRAPH * words}</p>{images}{links}{body}'
            f'<a href="/contacto/">Contacto</a> <a href="/acerca/">Acerca de mí</a></main></body></html>')


def site(pages: dict[str, dict] | None = None, robots="User-agent: *\nAllow: /\nSitemap: https://site.test/sitemap.xml\n", sitemap="auto", headers=None, ghost=404):
    """A fake web: url -> response. `pages` maps path -> {html or status, headers}."""
    web: dict[str, dict] = {}
    hdr = GOOD_HEADERS if headers is None else headers
    pages = pages if pages is not None else {"/": {"html": page()}, "/acerca/": {"html": page(title="Acerca de Ana Ruiz y su manera de trabajar", desc="Quién es Ana Ruiz, cómo trabaja y qué herramientas y métodos usa en sus proyectos de software.", path="/acerca/", h1="Acerca de", body="<p>Más sobre mí y mis proyectos de ingeniería.</p>")},
                                             "/contacto/": {"html": page(title="Contacto con Ana Ruiz para proyectos de ingeniería", desc="Cómo contactar con Ana Ruiz para hablar de un proyecto de ingeniería de software, una colaboración o una charla.", path="/contacto/", h1="Contacto", body="<p>Escríbeme para hablar de proyectos y colaboraciones.</p>")}}
    for path, spec in pages.items():
        web[ORIGIN + path] = {"status": spec.get("status", 200), "headers": spec.get("headers", hdr), "text": spec.get("html", ""), "content_type": "text/html"}
    if robots is not None:
        web[ORIGIN + "/robots.txt"] = {"status": 200, "text": robots, "headers": {"content-type": "text/plain"}}
    if sitemap == "auto":
        sitemap = "<?xml version='1.0'?><urlset>" + "".join(f"<url><loc>{ORIGIN}{p}</loc><lastmod>2026-09-01</lastmod></url>" for p in pages) + "</urlset>"
    if sitemap is not None:
        web[ORIGIN + "/sitemap.xml"] = {"status": 200, "text": sitemap, "headers": {"content-type": "application/xml"}}
    web["http://site.test/"] = {"status": 200, "final_url": ORIGIN + "/", "headers": {}, "text": "", "redirects": [ORIGIN + "/"]}
    web[ORIGIN + "/og.png"] = {"status": 200, "headers": {"content-length": "40000"}, "text": ""}
    web[ORIGIN + "/llms.txt"] = {"status": 200, "text": "# Ana Ruiz\n\n- [Acerca](https://site.test/acerca/): quién soy\n", "headers": {}}
    web["__ghost__"] = {"status": ghost}
    return web


def fetcher(web: dict, log: list | None = None):
    def fetch(url, *, accept="html", max_bytes=None):
        if log is not None:
            log.append(url)
        if "no-existe" in url:
            row = {**web["__ghost__"]}
            row.setdefault("text", "<html><body><h1>No encontrado</h1><p>Esta página no existe, vuelve al inicio.</p></body></html>" if row["status"] == 404 else page())
            row.setdefault("headers", {})
            return {"ok": row["status"] == 200, "url": url, "final_url": url, **row}
        row = web.get(url)
        if row is None:
            return {"ok": False, "url": url, "final_url": url, "status": 404, "headers": {}, "text": "", "error": "http 404"}
        out = {"ok": row.get("status", 200) < 400, "url": url, "final_url": row.get("final_url", url), "headers": {}, "text": "", "redirects": []}
        out.update(row)
        return out
    return fetch


GOOD_VITALS = {"profile": "mobile", "conditions": {"label": "móvil"}, "metrics": {"lcp_ms": 1800, "cls": 0.02, "fcp_ms": 1200, "ttfb_ms": 300, "tbt_ms": 80, "inp_ms": 90, "transfer_bytes": 400_000, "requests": 12},
               "js_errors": [], "rendered_text_chars": 1200}


def ids(report, severity=None, judgement=False):
    return {f["id"] for f in report["findings"] if (severity is None or f["severity"] == severity) and f["judgement"] == judgement}


def run(web=None, **kw):
    kw.setdefault("vitals", lambda url: GOOD_VITALS)
    return seo_audit.audit(ORIGIN + "/", fetch=fetcher(web if web is not None else site()), **kw)


# ---------------------------------------------------------------- the envelope

def test_a_healthy_site_scores_high_with_no_blocking_findings():
    r = run()
    assert r["ok"] and r["schema"] == "site-audit/1"
    assert r["score"] >= 90, [(f["id"], f["severity"]) for f in r["findings"] if not f["judgement"]]
    assert not ids(r, "critical") and not ids(r, "high")
    assert r["scores"]["total"] == r["score"] and r["scores"]["cwv"] == 100
    assert r["summary"]["pages_audited"] == 3 and r["summary"]["categories_unmeasured"] == []


def test_envelope_has_the_fields_the_monitor_reads():
    r = run()
    assert isinstance(r["score"], int) and 0 <= r["score"] <= 100
    assert [c["id"] for c in r["categories"]] == ["content", "technical", "onpage", "schema", "cwv", "ai", "images"]
    assert sum(c["weight"] for c in r["categories"]) == 100
    for c in r["categories"]:
        assert {"id", "name", "weight", "score", "measured", "findings"} <= set(c)
        for f in c["findings"]:
            assert f["severity"] in seo_audit.SEVERITIES and f["title"] and f["description"] and f["recommendation"] and isinstance(f["judgement"], bool)
    flat = r["findings"]
    assert len({f["id"] for f in flat}) == len(flat), "finding ids must be unique"
    assert all({"id", "category", "severity", "title"} <= set(f) for f in flat)
    assert len(r["action_plan"]["phases"]) == 4 and r["action_plan"]["phases"][3]["name"] == "Revisión humana"
    assert r["audited_at"].endswith("Z") and r["fixed_at"] is None
    json.dumps(r)


def test_unreachable_site_is_an_error_not_a_score():
    r = seo_audit.audit(ORIGIN + "/", fetch=lambda url, **kw: {"ok": False, "status": 0, "error": "dns", "error_kind": "dns"})
    assert r["ok"] is False and r["error_kind"] == "dns" and "score" not in r


@pytest.mark.parametrize("bad", ["", "ftp://x.test", "https://user:pw@x.test/"])
def test_bad_addresses_are_refused(bad):
    with pytest.raises(seo_audit.AuditError):
        seo_audit.normalize_url(bad)
    assert seo_audit.normalize_url("site.test") == "https://site.test/"


# ---------------------------------------------------------------- technical

def test_noindex_and_a_closed_robots_are_critical():
    web = site({"/": {"html": page(extra_head='<meta name="robots" content="noindex">')}}, robots="User-agent: *\nDisallow: /\n")
    r = run(web)
    assert "technical.noindex@/" in ids(r, "critical") and "technical.robots-blocks-all" in ids(r, "critical")
    assert r["score"] < 80


def test_missing_robots_and_sitemap_and_soft_404():
    r = run(site(robots=None, sitemap=None, ghost=200))
    assert {"technical.robots-missing", "technical.sitemap-missing", "technical.soft-404"} <= ids(r)


def test_sitemap_listing_dead_urls_is_high_and_a_stale_one_is_flagged():
    sm = f"<urlset><url><loc>{ORIGIN}/</loc><lastmod>2020-01-01</lastmod></url><url><loc>{ORIGIN}/gone/</loc><lastmod>2020-01-02</lastmod></url></urlset>"
    r = run(site(sitemap=sm))
    assert "technical.sitemap-dead-urls" in ids(r, "high") and "technical.sitemap-stale" in ids(r, judgement=True)


def test_security_headers_are_reported_one_by_one():
    r = run(site(headers={"content-type": "text/html"}))
    names = ids(r)
    assert {"technical.header-strict-transport-security@/", "technical.header-content-security-policy@/", "technical.header-frame@/"} <= names
    assert any(f["id"] == "technical.header-strict-transport-security@/" and f["severity"] == "medium" for f in r["findings"])


def test_canonical_problems():
    web = site({"/": {"html": page(canonical="")}, "/a/": {"html": page(title="Otra página distinta con su propio título largo", path="/a/", canonical='<link rel="canonical" href="https://elsewhere.test/a/">', body="<p>Texto propio de a.</p>")}},
               )
    web[ORIGIN + "/"]["text"] = web[ORIGIN + "/"]["text"].replace('<a href="/contacto/">', '<a href="/a/">a</a> <a href="/contacto/">')
    r = run(web)
    assert "technical.canonical-missing@/" in ids(r, "medium") and "technical.canonical-offsite@/a/" in ids(r, "high")


def test_broken_internal_links_count_but_a_refusing_external_site_does_not():
    web = site()
    web[ORIGIN + "/"]["text"] = web[ORIGIN + "/"]["text"].replace("</main>", '<a href="/roto/">roto</a> <a href="https://other.test/x">otro</a> <a href="https://dead.test/">muerto</a></main>')
    web["https://other.test/x"] = {"status": 403, "headers": {}, "text": ""}
    web["https://dead.test/"] = {"status": 404, "headers": {}, "text": ""}
    r = run(web)
    assert "technical.broken-internal@/" in ids(r, "high")
    assert "technical.broken-external@/" in ids(r, "medium")
    assert r["summary"]["links_checked"]["broken"] == 3
    external = [f for f in r["findings"] if f["id"] == "technical.broken-external@/"]
    assert len(external) == 1 and external[0]["title"].endswith("404")


def test_mixed_content_is_high():
    r = run(site({"/": {"html": page(body='<img src="http://site.test/a.png" alt="a" width="10" height="10">')}}))
    assert "technical.mixed-content@/" in ids(r, "high")


# ---------------------------------------------------------------- on page and content

def test_on_page_checks():
    bad = page(title="", desc="", h1="", lang="", extra_head="").replace('<meta name="viewport" content="width=device-width, initial-scale=1">', "").replace("<h2>Contacto</h2>", "<h3>Salto</h3>")
    r = run(site({"/": {"html": bad}}))
    for needle in ("title-missing", "description-missing", "h1-missing", "lang-missing", "viewport-missing", "heading-skip"):
        assert f"onpage.{needle}@/" in ids(r), needle
    sev = {f["id"]: f["severity"] for f in r["findings"]}
    assert sev["onpage.title-missing@/"] == "high" and sev["onpage.description-missing@/"] == "medium" and sev["onpage.viewport-missing@/"] == "high"


def test_duplicate_titles_and_texts_across_pages():
    same = page(title="El mismo título para varias páginas del sitio", words=6)
    r = run(site({"/": {"html": same}, "/b/": {"html": same.replace(ORIGIN + "/", ORIGIN + "/b/")}}))
    assert any(i.startswith("onpage.title-duplicate") for i in ids(r)) and any(i.startswith("content.duplicate") for i in ids(r))


def test_thin_content_and_generic_anchors():
    r = run(site({"/": {"html": page(words=0, body='<p>Poco.</p><a href="/acerca/">leer más</a>')}}))
    assert "content.thin@/" in ids(r) and "onpage.anchor-generic@/" in ids(r)


def test_judgement_findings_are_flagged_and_never_change_the_score():
    r = run()
    judged = [f for f in r["findings"] if f["judgement"]]
    assert {"content.eeat", "content.intent", "content.originality"} <= {f["id"] for f in judged}
    assert all(f["severity"] == "info" or f["id"].startswith("ai.") for f in judged)
    stripped = seo_audit._score([f for f in r["findings"] if not f["judgement"]], {c: True for c in seo_audit.CATEGORIES})
    full = seo_audit._score(r["findings"], {c: True for c in seo_audit.CATEGORIES})
    assert stripped == full


def test_repeating_a_check_on_many_pages_costs_at_most_twice():
    findings = [{"id": f"onpage.title-missing@/{i}", "category": "onpage", "severity": "high", "judgement": False} for i in range(6)]
    scores = seo_audit._score(findings, {c: True for c in seo_audit.CATEGORIES})
    assert scores["onpage"] == 100 - 2 * seo_audit.PENALTY["high"]


def test_an_unmeasured_category_has_no_score_and_does_not_count():
    r = run(vitals=None)
    assert r["scores"]["cwv"] is None and "cwv" in r["summary"]["categories_unmeasured"]
    assert any(f["id"] == "cwv.unavailable" for f in r["findings"])
    cwv = [c for c in r["categories"] if c["id"] == "cwv"][0]
    assert cwv["measured"] is False and cwv["score"] is None
    live = [(c["weight"], c["score"]) for c in r["categories"] if c["score"] is not None]
    assert r["score"] == round(sum(w * s for w, s in live) / sum(w for w, _ in live))


# ---------------------------------------------------------------- schema

def test_invalid_json_ld_and_missing_properties():
    bad = page().replace('{"@context"', '{"@context" "https://schema.org"', 1)
    r = run(site({"/": {"html": bad}}))
    assert "schema.invalid@/" in ids(r, "high")
    org = page().replace('"@type": "Person", "name": "Ana Ruiz", "url": "https://site.test/", ', '"@type": "Organization", ')
    r = run(site({"/": {"html": org}}))
    assert any(i.startswith("schema.props-organization") for i in ids(r))


def test_no_structured_data_on_the_home_page():
    html = page().replace('<script type="application/ld+json">', '<script type="text/plain">')
    r = run(site({"/": {"html": html}}))
    assert "schema.none@/" in ids(r, "medium")


def test_entity_without_same_as():
    html = page().replace(', "sameAs": ["https://github.com/ana"]', "")
    assert "schema.sameas@/" in ids(run(site({"/": {"html": html}})))


# ---------------------------------------------------------------- AI crawlers

def test_blocking_training_is_not_blocking_citing():
    r = run(site(robots="User-agent: GPTBot\nDisallow: /\nUser-agent: ClaudeBot\nDisallow: /\nUser-agent: *\nAllow: /\n"))
    table = {row["crawler"]: row for row in r["ai_crawlers"]}
    assert table["GPTBot"]["purpose"] == "training" and table["GPTBot"]["allowed"] is False
    assert table["OAI-SearchBot"]["purpose"] == "search" and table["OAI-SearchBot"]["allowed"] is True
    assert "ai.training-blocked" in ids(r, "info", judgement=True) and "ai.search-blocked" not in ids(r)


def test_blocking_search_crawlers_is_high():
    r = run(site(robots="User-agent: OAI-SearchBot\nDisallow: /\nUser-agent: PerplexityBot\nDisallow: /\n"))
    assert "ai.search-blocked" in ids(r, "high")
    assert any(row["crawler"] == "ChatGPT-User" and row["allowed"] for row in r["ai_crawlers"])


def test_an_empty_shell_is_judged_on_its_rendered_dom():
    shell = '<!doctype html><html lang="es"><head><title>App</title></head><body><div id="root"></div><script src="/a.js"></script><script src="/b.js"></script><script src="/c.js"></script></body></html>'
    rendered = page()
    r = run(site({"/": {"html": shell}}), vitals=lambda u: {**GOOD_VITALS, "rendered_html": rendered, "rendered_text_chars": 1500})
    assert "onpage.h1-missing@/" not in ids(r) and "content.thin@/" not in ids(r)
    assert "ai.js-dependent" in ids(r, "high")
    assert r["pages"][0].get("rendered") is True and any("DOM renderizado" in x for x in r["limits"])
    assert "rendered_html" not in json.dumps(r["vitals"])
    plain = run(site({"/": {"html": page()}}), vitals=lambda u: {**GOOD_VITALS, "rendered_html": page()})
    assert not plain["pages"][0].get("rendered")


def test_a_script_filled_inner_page_is_flagged_for_judgement_not_called_empty():
    shell = '<!doctype html><html lang="es"><head><title>Otra app del mismo sitio</title><meta name="description" content="Una aplicación aparte que se pinta con scripts en el navegador de quien la visita, sin texto inicial."></head><body><div id="root"></div><script src="/a.js"></script></body></html>'
    home = page().replace("</main>", '<a href="/app/">app</a></main>')
    r = run(site({"/": {"html": home}, "/app/": {"html": shell}}))
    assert "ai.js-dependent@/app/" in ids(r, "medium", judgement=True)
    assert "onpage.h1-missing@/app/" not in ids(r) and "content.thin@/app/" not in ids(r)


def test_llms_txt_and_javascript_dependence():
    r = run(site())
    assert r["llms_txt"]["present"] is True
    shell = '<!doctype html><html lang="es"><head><title>App</title></head><body><div id="root"></div><script src="/a.js"></script><script src="/b.js"></script><script src="/c.js"></script></body></html>'
    r = run(site({"/": {"html": shell}}), vitals=lambda u: {**GOOD_VITALS, "rendered_text_chars": 2500})
    assert "ai.js-dependent" in ids(r, "high")
    r = run(site({"/": {"html": shell}}), vitals=None)
    assert "ai.js-dependent" in ids(r, "medium", judgement=True)


# ---------------------------------------------------------------- images and vitals

def test_image_checks():
    imgs = "".join(f'<img src="/i{n}.jpg">' for n in range(6)) + '<img src="/big.jpg" alt="grande" width="9" height="9">'
    web = site({"/": {"html": page(images=imgs)}})
    web[ORIGIN + "/big.jpg"] = {"status": 200, "headers": {"content-length": "1500000"}, "text": ""}
    r = run(web)
    got = ids(r)
    assert {"images.alt-missing@/", "images.dimensions@/", "images.lazy@/", "images.format@/", "images.heavy@/"} <= got


@pytest.mark.parametrize("metric,value,rating", [("lcp_ms", 2000, "good"), ("lcp_ms", 3000, "needs-improvement"), ("lcp_ms", 4500, "poor"),
                                                 ("cls", 0.05, "good"), ("cls", 0.3, "poor"), ("inp_ms", 250, "needs-improvement"), ("inp_ms", 600, "poor")])
def test_vital_ratings_follow_the_published_thresholds(metric, value, rating):
    assert seo_audit.rate_vital(metric, value) == rating


def test_poor_vitals_become_findings_with_the_measurement():
    bad = {**GOOD_VITALS, "metrics": {**GOOD_VITALS["metrics"], "lcp_ms": 5200, "cls": 0.4, "inp_ms": 320}}
    r = run(vitals=lambda u: bad)
    got = {f["id"].split("@")[0]: f for c in r["categories"] if c["id"] == "cwv" for f in c["findings"]}
    assert got["cwv.lcp"]["severity"] == "high" and got["cwv.cls"]["severity"] == "high" and got["cwv.inp"]["severity"] == "medium"
    assert got["cwv.lcp"]["evidence"]["value"] == 5200
    assert r["vitals"]["ratings"]["lcp_ms"] == "poor" and r["scores"]["cwv"] < 100


def test_a_browser_error_leaves_the_category_unmeasured_with_the_reason():
    r = run(vitals=lambda u: {"error": "no browser", "hint": "python -m playwright install chromium"})
    assert r["scores"]["cwv"] is None and "playwright install" in r["vitals"]["reason"]


# ---------------------------------------------------------------- budget, previous run, storage

def test_request_budget_is_reported():
    r = run(max_requests=6)
    assert r["summary"]["truncated"] is True and any("límite" in x for x in r["limits"])


def test_previous_report_gives_new_and_fixed_ids(tmp_path):
    first = run(site(robots=None))
    second = run(site(), previous=first)
    assert "technical.robots-missing" in second["previous"]["fixed"] and second["previous"]["score"] == first["score"]
    third = run(site(robots=None), previous=second)
    assert "technical.robots-missing" in third["previous"]["new"]


def test_report_store_and_cached_run(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(seo_audit, "make_fetcher", lambda allow_local=False: (fetcher(site(), calls), lambda: None))
    svc = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path, allow_local_urls=False),
                          browser=SimpleNamespace(url_problem=lambda u: None, _submit=lambda kind, payload: GOOD_VITALS))
    first = seo_audit.run(svc, "site.test")
    assert first["ok"] and first["from_cache"] is False and first["id"]
    n = len(calls)
    again = seo_audit.run(svc, "https://site.test/")
    assert again["from_cache"] is True and again["id"] == first["id"] and len(calls) == n
    fresh = seo_audit.run(svc, "site.test", fresh=True)
    assert fresh["from_cache"] is False and fresh["id"] != first["id"] and fresh["previous"]["id"] == first["id"]
    store = seo_audit.ReportStore(tmp_path)
    assert [r["id"] for r in store.list(ORIGIN + "/")][0] == fresh["id"] and store.get(first["id"])["url"] == ORIGIN + "/"
    assert store.get("../../etc") is None


# ---------------------------------------------------------------- tools and API

def test_tools_are_registered_and_annotated():
    by = {t.name: t for t in TOOLS}
    assert by["site_audit"].annotations["readOnlyHint"] is False and by["site_audit"].annotations["openWorldHint"] is True and by["site_audit"].timeout_s >= 120
    assert by["site_audit_reports"].annotations["readOnlyHint"] is True
    for name in ("site_audit", "site_audit_reports"):
        first = by[name].description.splitlines()[0]
        assert len(first) <= 110 and "." in first


def test_tool_and_api_round_trip(client, monkeypatch):
    monkeypatch.setattr(seo_audit, "make_fetcher", lambda allow_local=False: (fetcher(site()), lambda: None))
    client.svc.browser._submit = lambda kind, payload: GOOD_VITALS  # the fake browser has no vitals job
    out = call_tool(client.svc, "site_audit", {"url": "site.test", "max_pages": 3})
    assert out["ok"] and out["score"] >= 90 and out["id"] and "truncated" not in out
    listing = call_tool(client.svc, "site_audit_reports", {})
    assert listing["reports"][0]["id"] == out["id"]
    whole = call_tool(client.svc, "site_audit_reports", {"id": out["id"]})
    assert whole["url"] == ORIGIN + "/" and whole["categories"]
    over_http = client.post("/api/site-audit", json={"url": "site.test", "fresh": True})
    assert over_http.status_code == 200 and over_http.json()["scores"]["total"] >= 90
    assert client.get("/api/site-audit/reports").json()["reports"]
    assert client.get(f"/api/site-audit/reports/{out['id']}").status_code == 200
    assert client.get("/api/site-audit/reports/nope-nope-nope").status_code == 404
    assert client.post("/api/site-audit", json={"url": "ftp://x"}).status_code == 400


# ---------------------------------------------------------------- the real vitals job

class _Page(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = ("<!doctype html><html lang='es'><head><meta charset='utf-8'><title>Medida</title></head><body><h1>Hola</h1>"
                "<p>" + "texto de prueba para medir " * 40 + "</p><button onclick='1'>Un botón</button></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # noqa: D401
        pass


def test_vitals_job_measures_a_real_page(tmp_path):
    from vitruvius_hoard.browser import BrowserWorker, _sync_playwright_available
    if not _sync_playwright_available():
        pytest.skip("playwright is not installed")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    worker = BrowserWorker(tmp_path, timeout_s=60, profile="operator_local")
    try:
        out = worker._submit("vitals", {"url": f"http://127.0.0.1:{server.server_address[1]}/", "profile": "mobile", "throttle": True})
    finally:
        worker.stop()
        server.shutdown()
    if out.get("error") == "no browser":
        pytest.skip("no Chromium available")
    assert "error" not in out, out
    m = out["metrics"]
    assert m["fcp_ms"] and m["fcp_ms"] > 0 and m["lcp_ms"] and m["ttfb_ms"] is not None and m["cls"] == 0.0
    assert out["rendered_text_chars"] > 500 and out["profile"] == "mobile" and out["conditions"]["cpu_slowdown"] in (1, 4)
    private = BrowserWorker(tmp_path, timeout_s=10)  # the default policy refuses a loopback address
    try:
        assert private._submit("vitals", {"url": "http://127.0.0.1:9/"})["error"] == "This URL cannot be opened."
    finally:
        private.stop()
