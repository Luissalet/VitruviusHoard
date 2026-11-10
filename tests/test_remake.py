"""Rehacer: the pure helpers, then the whole job with the fake browser and a scripted model, the REST routes and the tools."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from conftest import FakeChatResult, FakeLink, _fake_parity_page, make_services
from vitruvius_hoard import remake
from vitruvius_hoard.agent_tools import TOOLS_BY_NAME, call_tool


def ref(w):
    return _fake_parity_page(w, "reference", 1, False)


def half(w):
    """Matches the reference in its top half only."""
    image = ref(w)
    image.paste((3, 200, 9), (0, 150, w, 300))
    return image


class Scripted(FakeLink):
    """A model that answers from a list, in order."""

    def __init__(self, answers):
        super().__init__()
        self.answers = list(answers)
        self.kwargs = []

    def chat(self, messages, images=None, **kwargs):
        self.chat_calls.append((messages, images))
        self.kwargs.append(kwargs)
        return FakeChatResult(text=self.answers.pop(0) if self.answers else "nothing", model="fake-code-model")


@pytest.fixture
def make(tmp_path):
    made = []

    def build(link=None):
        svc = make_services(tmp_path / f"s{len(made)}", link=link)
        made.append(svc)
        return svc

    yield build
    for svc in made:
        svc.stop()


def folder(svc, project_id):
    return remake.project_dir(svc.config.data_dir, project_id)


# ---------------------------------------------------------------------------------------------------- helpers

def test_bot_walls_and_trackers():
    assert remake.looks_like_bot_wall(403, "<html><title>Just a moment...</title></html>")
    assert remake.looks_like_bot_wall(200, "<html><head><title>Attention Required! | Cloudflare</title></head></html>")
    assert not remake.looks_like_bot_wall(200, "<html><title>Inicio</title><p>hola</p></html>")
    html = ('<head><script async src="https://www.googletagmanager.com/gtag/js?id=G-X"></script>'
            "<script>(function(w,d,s,l,i){w[l]=w[l]||[];})(window,document,'script','dataLayer','GTM-1');</script>"
            '<script src="/app.js"></script><link rel="preconnect" href="https://www.google-analytics.com"></head>')
    out, removed = remake.strip_trackers(html)
    assert "googletagmanager" not in out and "GTM-1" not in out and "google-analytics" not in out
    assert '<script src="/app.js"></script>' in out and len(removed) == 3


def test_clean_html_drops_scripts_keeps_data_and_marks_the_copy():
    html = ('<!DOCTYPE html><html><head><meta http-equiv="Content-Security-Policy" content="x"><base href="/x/">'
            '<link rel="modulepreload" href="/m.js"><link rel="stylesheet" href="/a.css" integrity="sha384-abc">'
            '<script type="application/ld+json">{"@type":"Org"}</script><script>alert(1)</script>'
            '<style data-parity-freeze="">*{transition:none}</style></head><body><script src="/b.js"></script></body></html>')
    out, _ = remake.clean_html(html, source_url="https://site.test/")
    assert "alert(1)" not in out and "/b.js" not in out and "modulepreload" not in out
    assert "ld+json" in out and "integrity" not in out and "Content-Security-Policy" not in out and "<base" not in out
    assert "data-parity-freeze" not in out and 'name="robots" content="noindex, nofollow"' in out
    assert "Rehecho por Vitruvius's Hoard a partir de https://site.test/" in out and out.startswith("<!DOCTYPE html>")
    kept, _ = remake.clean_html(html, keep_scripts=True)
    assert "alert(1)" in kept and "/b.js" in kept


def test_local_paths_stay_inside_assets():
    taken = {}
    assert remake.local_path("https://a.com/../../etc/passwd", "", taken) == "assets/a.com/etc/passwd.bin"
    assert remake.local_path("https://a.com/img/x.png?v=2", "image/png", taken).startswith("assets/a.com/img/x__")
    assert remake.local_path("https://cdn.b.org/font", "font/woff2", taken) == "assets/cdn.b.org/font.woff2"
    assert remake.local_path("https://a.com/", "text/css", taken) == "assets/a.com/index.css"
    first = remake.local_path("https://a.com/p/IMG.PNG", "", taken)
    second = remake.local_path("https://a.com/p/img.png", "", taken)
    assert first == "assets/a.com/p/IMG.png" and second == "assets/a.com/p/img.png"
    assert remake.local_path("data:image/png;base64,xx", "", taken) is None


def test_rewrite_urls_is_relative_and_exact():
    mapping = {"https://a.com/img/x.png": "assets/a.com/img/x.png", "https://a.com/q?a=1&b=2": "assets/a.com/q__1.json"}
    css = 'body{background:url("https://a.com/img/x.png")} .b{background:url(https://a.com/img/x.png2)}'
    out = remake.rewrite_urls(css, mapping, "assets/a.com/css")
    assert 'url("../img/x.png")' in out and "https://a.com/img/x.png2" in out
    html = '<img src="//a.com/img/x.png"><a href="https://a.com/q?a=1&amp;b=2">q</a>'
    assert remake.rewrite_urls(html, mapping, "") == '<img src="assets/a.com/img/x.png"><a href="assets/a.com/q__1.json">q</a>'


def test_absolutize_markup_and_css():
    html = '<img src="img/a.png" srcset="img/a.png 1x, /img/b.png 2x"><div style="background:url(\'bg.jpg\')"></div><a href="#top">t</a>'
    out = remake.absolutize_markup(html, "https://s.com/blog/post")
    assert 'src="https://s.com/blog/img/a.png"' in out and "https://s.com/img/b.png 2x" in out
    assert 'url("https://s.com/blog/bg.jpg")' in out and 'href="#top"' in out
    assert remake.absolutize_css('@import "x.css"; a{b:url(data:image/png;base64,AA)}', "https://s.com/c/") == '@import "https://s.com/c/x.css"; a{b:url(data:image/png;base64,AA)}'


def test_font_faces_parse():
    faces = remake.font_faces('@font-face{font-family:"Acme Sans";font-weight:700;font-style:italic;src:url("https://f.com/a.woff2") format("woff2"),url(https://f.com/a.woff)}')
    assert faces == [{"family": "Acme Sans", "weight": "700", "style": "italic", "unicode_range": "",
                      "src": [{"url": "https://f.com/a.woff2", "format": "woff2"}, {"url": "https://f.com/a.woff", "format": ""}]}]


def test_answers_full_file_or_edits():
    assert remake.extract_block("Here:\n```html\n<!doctype html><p>a</p>\n```\nbye", "html") == "<!doctype html><p>a</p>"
    assert remake.extract_block("<html><body>x</body></html>", "html") == "<html><body>x</body></html>"
    assert remake.extract_block("```\nh1{a:b}\n```", "css") == "h1{a:b}"
    assert remake.extract_block("no code", "css") is None
    current = "<main>\n    <h1>Hola</h1>\n    <p>uno</p>\n</main>\n"
    answer = ("<<<<<<< SEARCH\n<h1>Hola</h1>\n=======\n<h1>Adiós</h1>\n>>>>>>> REPLACE\n"
              "<<<<<<< SEARCH\n  <p>uno</p>\n</main>\n=======\n<p>dos</p>\n</main>\n>>>>>>> REPLACE\n"
              "<<<<<<< SEARCH\n<p>no está</p>\n=======\n<p>x</p>\n>>>>>>> REPLACE")
    out, applied, failed = remake.apply_edits(current, answer)
    assert (applied, failed) == (2, 1) and "<h1>Adiós</h1>" in out and "<p>dos</p>" in out and "uno" not in out
    assert remake.has_edits(answer) and not remake.has_edits("```html\n<p></p>\n```")
    fixed = remake.insert_fixes(remake.insert_fixes("<body><p>a</p></body>", "p{color:red}"), "p{color:blue}")
    assert fixed.count('id="vitruvius-remake-fixes"') == 1 and "blue" in fixed and fixed.index("blue") < fixed.index("</body>")


def test_screen_diff_names_moves_misses_and_extras():
    ref_o = {"items": [{"t": "h1", "s": "h1", "x": 0, "y": 10, "w": 300, "h": 40, "d": 1, "tx": "Hola", "f": "32px 700 Acme", "c": "#111111"},
                       {"t": "p", "s": "p", "x": 0, "y": 60, "w": 300, "h": 20, "d": 1, "tx": "Texto", "f": "16px 400 Acme"},
                       {"t": "p", "s": "p.lejos", "x": 0, "y": 2000, "w": 300, "h": 20, "d": 1, "tx": "Abajo"}]}
    cand_o = {"items": [{"t": "h1", "s": "h1.t", "x": 0, "y": 30, "w": 300, "h": 40, "d": 1, "tx": "Hola", "f": "30px 700 Arial", "c": "#111111"},
                        {"t": "span", "s": "span", "x": 0, "y": 90, "w": 50, "h": 20, "d": 1, "tx": "Sobra"}]}
    lines = remake.screen_diff(ref_o, cand_o, 0, 900)
    text = "\n".join(lines)
    assert "MISSING in candidate" in text and "Texto" in text and "Abajo" not in text
    assert "EXTRA in candidate" in text and "Sobra" in text
    assert "y 10→30 (+20)" in text and "font 32px 700 Acme → 30px 700 Arial" in text


def test_focus_is_the_first_failing_screen_of_each_width():
    widths = [{"width": 1440, "viewport_height": 900, "height_pass": True, "screens": [
                  {"index": 0, "y": 0, "height": 900, "score": 99, "passed": True},
                  {"index": 1, "y": 900, "height": 900, "score": 80, "passed": False},
                  {"index": 2, "y": 1800, "height": 900, "score": 50, "passed": False}]},
              {"width": 390, "viewport_height": 844, "height_pass": False, "screens": [{"index": 0, "y": 0, "height": 844, "score": 100, "passed": True}]}]
    focus = remake.focus_screens(widths)
    assert [(f["width"], f["index"]) for f in focus] == [(1440, 1), (390, 0)]
    assert remake.round_score([{"score": 90}, {"score": 80}]) == 85.0


# ---------------------------------------------------------------------------------------------------- the job

def test_copy_mode_passes_in_the_first_round(make):
    svc = make()
    svc.browser.parity_hook = lambda tag, w, load, html, url: ref(w) if tag == "candidate" else None
    out = svc.remake.start(url="https://site.test/", wait_s=30)
    assert out["status"] == "done" and out["passed"] and out["best_round"] == 0
    assert [r["kind"] for r in out["rounds"]] == ["copy"] and out["rounds"][0]["score"] == 100.0
    base = folder(svc, out["id"])
    page = (base / "site" / "index.html").read_text(encoding="utf-8")
    assert "googletagmanager" not in page and "window.app" not in page and "noindex" in page
    assert 'href="assets/site.test/css/a.css"' in page and 'src="assets/site.test/img/x.png"' in page
    css = (base / "site" / "assets" / "site.test" / "css" / "a.css").read_text(encoding="utf-8")
    assert 'url("../img/bg.png")' in css and 'url("../fonts/acme.woff2")' in css
    assert not (base / "site" / "assets" / "site.test" / "js").exists()   # scripts are not kept in a static copy
    ledger = json.loads((base / "assets.json").read_text(encoding="utf-8"))
    assert {r["kind"] for r in ledger} == {"styles", "images", "fonts"} and all("Pertenece al sitio original" in r["licence"] for r in ledger)
    slots = out["slots"]
    assert slots["resumen"]["imagenes"] == 1 and slots["enlaces"]["redes"][0]["href"] == "https://twitter.com/site"
    assert slots["enlaces"]["correo"] and slots["enlaces"]["paginas_no_rehechas"] and slots["resumen"]["formularios"] == 1
    assert out["assets"]["count"] == 4 and out["files"][0]["path"]
    assert svc.parity_get(out["rounds"][0]["parity_id"])["passed"]
    assert any(c.get("mount") for c in svc.browser.calls)
    name, data = svc.remake.zip_bytes(out["id"])
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert name.startswith("site.test-") and {"site/index.html", "assets.json", "slots.json", "paridad.json", "creditos.md"} <= set(names)
    assert "Ronda" in svc.remake.report_html(out["id"])


def test_copy_mode_repairs_with_css_from_the_model(make):
    link = Scripted(["```css\nh1{margin-top:0!important}\n```"])
    svc = make(link)
    svc.browser.parity_hook = lambda tag, w, load, html, url: (ref(w) if "margin-top:0" in html else half(w)) if tag == "candidate" else None
    out = svc.remake.start(url="https://site.test/", wait_s=30, note="respeta el logo")
    assert out["passed"] and [r["kind"] for r in out["rounds"]] == ["copy", "model"]
    assert out["rounds"][0]["score"] < 98 and out["rounds"][1]["kept"] and out["model"] == "fake-code-model"
    messages, images = link.chat_calls[0]
    user = messages[1]["content"]
    assert "SCREEN 1 at 1440 px" in user and "SCREEN 1 at 390 px" in user and "respeta el logo" in user
    assert "You cannot edit the HTML" in messages[0]["content"] and len(images) == 4 and link.kwargs[0]["task"] == "code"
    page = (folder(svc, out["id"]) / "site" / "index.html").read_text(encoding="utf-8")
    assert '<style id="vitruvius-remake-fixes">' in page and (folder(svc, out["id"]) / "rounds" / "1" / "fixes.css").is_file()


def test_rebuild_mode_undoes_a_worse_round_and_keeps_the_best(make):
    first = "```html\n<!doctype html><html><head><title>t</title></head><body><p>v1</p><script>x()</script></body></html>\n```"
    worse = "<<<<<<< SEARCH\n<p>v1</p>\n=======\n<p>v2</p>\n>>>>>>> REPLACE"
    better = "<<<<<<< SEARCH\n<p>v1</p>\n=======\n<p>v3</p>\n>>>>>>> REPLACE"
    link = Scripted([first, worse, better])
    svc = make(link)

    def hook(tag, w, load, html, url):
        if tag != "candidate":
            return None
        return ref(w) if "v3" in html else half(w) if "v1" in html else _fake_parity_page(w, "other", 1, False)

    svc.browser.parity_hook = hook
    out = svc.remake.start(url="https://site.test/", mode="rebuild", max_rounds=4, wait_s=30)
    rounds = out["rounds"]
    assert [r["kept"] for r in rounds] == [True, False, True] and out["passed"] and out["best_round"] == 2
    assert rounds[1]["score"] < rounds[0]["score"]
    base = folder(svc, out["id"])
    page = (base / "site" / "index.html").read_text(encoding="utf-8")
    assert "<p>v3</p>" in page and "x()" not in page and 'href="assets/fonts.css"' in page
    fonts = (base / "site" / "assets" / "fonts.css").read_text(encoding="utf-8")
    assert 'font-family:"Acme"' in fonts and 'url("site.test/fonts/acme.woff2")' in fonts
    first_prompt = link.chat_calls[0][0][1]["content"]
    assert "LAYOUT AT 1440 px" in first_prompt and "LAYOUT AT 390 px" in first_prompt and "assets/site.test/img/x.png" in first_prompt
    assert "lowered the score" in link.chat_calls[2][0][1]["content"] and "CURRENT FILE" in link.chat_calls[2][0][1]["content"]


def test_missing_files_are_fetched_before_asking_the_model(make):
    svc = make()
    browser = svc.browser
    browser.remake_missing = ["assets/site.test/img/late.png"]
    browser.fetch_bodies = {"https://site.test/img/late.png": ("image/png", b"\x89PNG-late")}

    def hook(tag, w, load, html, url):
        if tag != "candidate":
            return None
        root = Path(browser.calls[-1]["mount"]["root"])
        return ref(w) if (root / "assets/site.test/img/late.png").is_file() else half(w)

    browser.parity_hook = hook
    out = svc.remake.start(url="https://site.test/", wait_s=30)
    assert out["passed"] and [r["kind"] for r in out["rounds"]] == ["copy", "fetch"]
    assert {"fetch": ["https://site.test/img/late.png"]} in browser.calls
    assert any(f["local"] == "assets/site.test/img/late.png" for f in out["assets"]["files"])


@pytest.mark.parametrize("extra,words", [({"error": "bot check", "wall": True}, "anti-robots"),
                                         ({"sensitive": {"password": 1, "card": 0}}, "inicio de sesión"),
                                         ({"sensitive": {"password": 0, "card": 2}}, "pago")])
def test_bot_walls_and_sign_in_pages_are_not_remade(make, extra, words):
    svc = make()
    svc.browser.remake_extra = extra
    out = svc.remake.start(url="https://site.test/", wait_s=30)
    assert out["status"] == "failed" and words in out["error"] and out["rounds"] == []


def test_a_screenshot_is_rebuilt_by_the_model(make):
    link = Scripted(["```html\n<html><body style='margin:0'><div>captura</div></body></html>\n```"])
    svc = make(link)
    svc.browser.parity_hook = lambda tag, w, load, html, url: ref(w).resize((w, 600)) if tag == "candidate" else None
    buf = io.BytesIO()
    ref(720).save(buf, format="PNG")  # taken at another size: scaled to the width asked for
    image = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    out = svc.remake.start(image=image, image_width=1440, mode="copy", wait_s=30)
    assert out["mode"] == "rebuild" and out["widths"] == [1440] and out["source"]["kind"] == "image" and out["passed"]
    messages, images = link.chat_calls[0]
    assert "attached screenshot" in messages[1]["content"] and images and out["reference"]["heights"] == {"1440": 600}
    assert not any(c.get("remake_capture") for c in svc.browser.calls)


def test_continue_with_a_note_then_delete(make):
    link = Scripted(["```css\np{color:red}\n```", "```css\np{color:blue}\n```"])
    svc = make(link)
    svc.browser.parity_hook = lambda tag, w, load, html, url: half(w) if tag == "candidate" else None
    out = svc.remake.start(url="https://site.test/", max_rounds=2, wait_s=30)
    assert out["status"] == "done" and not out["passed"] and len(out["rounds"]) == 2 and "mejor es la ronda 0" in out["phase"]
    more = svc.remake.continue_(out["id"], rounds=1, note="usa el azul", wait_s=30)
    assert len(more["rounds"]) == 3 and "INSTRUCTIONS FROM THE USER: usa el azul" in link.chat_calls[1][0][1]["content"]
    assert svc.remake.list()[0]["id"] == out["id"]
    code = svc.remake.code(out["id"])
    assert code["path"] == "index.html" and "<h1>Hola mundo</h1>" in code["text"]
    with pytest.raises(PermissionError):
        svc.remake.code(out["id"], "../project.json")
    parity_ids = [r["parity_id"] for r in more["rounds"] if r.get("parity_id")]
    assert svc.remake.delete(out["id"])["ok"]
    assert not folder(svc, out["id"]).exists()
    for pid in parity_ids:
        with pytest.raises(LookupError):
            svc.parity_get(pid)


class ConnectError(Exception):
    pass


def test_an_unreachable_model_is_asked_again(make, monkeypatch):
    class Flaky(Scripted):
        def chat(self, messages, images=None, **kwargs):
            if not self.chat_calls:
                self.chat_calls.append((messages, images))
                raise ConnectError("All connection attempts failed")
            return super().chat(messages, images, **kwargs)

    link = Flaky(["```css\nh1{margin-top:0}\n```"])
    svc = make(link)
    monkeypatch.setattr(svc.remake, "retry_pause", 0)
    svc.browser.parity_hook = lambda tag, w, load, html, url: (ref(w) if "margin-top:0" in html else half(w)) if tag == "candidate" else None
    out = svc.remake.start(url="https://site.test/", wait_s=30)
    assert out["passed"] and len(link.chat_calls) == 2 and [r["kind"] for r in out["rounds"]] == ["copy", "model"]


def test_an_answer_that_runs_out_of_room_is_asked_again_shorter(make):
    class Long(Scripted):
        def chat(self, messages, images=None, **kwargs):
            if not self.chat_calls:
                self.chat_calls.append((messages, images))
                self.kwargs.append(kwargs)
                raise ValueError("Global generation did not complete normally")
            return super().chat(messages, images, **kwargs)

    link = Long(["```html\n<html><body><p>v</p></body></html>\n```"])
    svc = make(link)
    svc.browser.parity_hook = lambda tag, w, load, html, url: ref(w) if tag == "candidate" else None
    out = svc.remake.start(url="https://site.test/", mode="rebuild", wait_s=30)
    assert out["passed"] and [k["effort"] for k in link.kwargs] == ["medium", "low"]
    assert "ran out of room" in link.chat_calls[1][0][1]["content"]


def test_start_validates_its_input(make):
    svc = make()
    with pytest.raises(ValueError):
        svc.remake.start()
    with pytest.raises(ValueError):
        svc.remake.start(url="https://site.test/", image="AAAA")
    with pytest.raises(ValueError):
        svc.remake.start(url="https://site.test/", widths=[100])
    with pytest.raises(ValueError):
        svc.remake.start(url="http://127.0.0.1:5191/")
    with pytest.raises(ValueError):
        svc.remake.start(image="bm90IGFuIGltYWdl")
    with pytest.raises(LookupError):
        svc.remake.get("abcdef123456")


def test_a_job_left_running_is_marked_interrupted(make, tmp_path):
    svc = make()
    project = {"id": "abc123abc123", "created_ts": 1, "source": {"kind": "url", "url": "https://site.test/"}, "status": "running",
               "rounds": [], "mode": "copy", "widths": [1440]}
    remake.save(svc.config.data_dir, project)
    runner = remake.RemakeRunner(svc)
    assert runner.get("abc123abc123")["status"] == "interrupted"


# ---------------------------------------------------------------------------------------------------- REST and tools

def test_rest_routes(client):
    client.svc.browser.parity_hook = lambda tag, w, load, html, url: ref(w) if tag == "candidate" else None
    created = client.post("/api/remake", json={"url": "https://site.test/", "wait_s": 30})
    assert created.status_code == 201
    body = created.json()
    rid = body["id"]
    assert body["passed"] and body["site_url"] == f"/api/remake/{rid}/site/index.html"
    assert client.get("/api/remake").json()["remakes"][0]["id"] == rid
    assert client.get(f"/api/remake/{rid}").json()["best_round"] == 0
    assert "Hola mundo" in client.get(f"/api/remake/{rid}/code").json()["text"]
    site = client.get(body["site_url"])
    assert site.status_code == 200 and "text/html" in site.headers["content-type"]
    assert client.get(f"/api/remake/{rid}/site/assets/site.test/css/a.css").status_code == 200
    assert client.get(f"/api/remake/{rid}/site/..%2Fproject.json").status_code in (403, 404)
    zipped = client.get(body["download_url"])
    assert zipped.status_code == 200 and zipped.headers["content-type"] == "application/zip"
    assert "Ronda" in client.get(body["report_url"]).text
    assert client.post(f"/api/remake/{rid}/stop").json()["id"] == rid
    assert client.post(f"/api/remake/{rid}/continue", json={"id": rid, "rounds": 1, "wait_s": 30}).status_code == 200
    assert client.delete(f"/api/remake/{rid}").json()["ok"]
    assert client.get(f"/api/remake/{rid}").status_code == 404
    assert client.post("/api/remake", json={"url": "https://site.test/", "widths": [50]}).status_code in (400, 422)
    assert client.post("/api/remake", json={}).status_code == 400


def test_tools(services):
    services.browser.parity_hook = lambda tag, w, load, html, url: ref(w) if tag == "candidate" else None
    out = call_tool(services, "remake_start", {"url": "https://site.test/", "wait_s": 30})
    rid = out["id"]
    assert call_tool(services, "remake_get", {"id": rid})["passed"]
    assert call_tool(services, "remake_list", {})["remakes"][0]["id"] == rid
    assert "Hola mundo" in call_tool(services, "remake_code", {"id": rid})["text"]
    assert call_tool(services, "remake_stop", {"id": rid})["id"] == rid
    assert call_tool(services, "remake_delete", {"id": rid})["ok"]
    assert TOOLS_BY_NAME["remake_delete"].annotations["destructiveHint"] is True
    assert TOOLS_BY_NAME["remake_get"].annotations["readOnlyHint"] is True
    assert TOOLS_BY_NAME["remake_start"].timeout_s >= 900
