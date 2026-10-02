"""What a page may reach (`hoard_link.web.safety` on every URL, redirect and sub-request) and how the browser is found and the
video encoded (`hoard_link.web.browser`, `hoard_link.media`). The last tests drive a real headless browser and skip without one."""
import http.server
import threading

import pytest
from conftest import make_services

from vitruvius_hoard import browser as B
from vitruvius_hoard.browser import BrowserWorker
from vitruvius_hoard.hoard_link.web import browser as web_browser
from vitruvius_hoard.hoard_link.web import safety


def public_dns(host, port):
    return {"example.test": ["93.184.216.34"], "cdn.test": ["93.184.216.35"], "intranet.test": ["10.0.0.7"]}[host]


class FakeRoute:
    def __init__(self, url):
        self.request = type("R", (), {"url": url})()
        self.verdict = None

    def continue_(self):
        self.verdict = "continue"

    def abort(self, reason="failed"):
        self.verdict = f"abort:{reason}"


class FakeContext:
    def route(self, pattern, handler):
        self.pattern, self.handler = pattern, handler


def test_url_problem_blocks_every_non_public_target(tmp_path):
    worker = BrowserWorker(tmp_path, resolver=public_dns)
    assert worker.url_problem("https://example.test/page") is None
    assert worker.url_problem(None) is None and worker.url_problem("") is None
    for bad in ("http://127.0.0.1:5191/api/agent/call", "http://localhost/", "http://[::1]/", "http://10.1.2.3/", "http://intranet.test/",
                "http://169.254.169.254/latest/meta-data/", "http://2130706433/", "http://0x7f.1/", "file:///etc/passwd",
                "ftp://example.test/x", "http://user:pw@example.test/", "javascript:alert(1)"):
        assert worker.url_problem(bad), bad


def test_a_host_that_does_not_resolve_is_left_to_the_browser(tmp_path):
    def nothing(host, port):
        raise OSError("no such host")

    assert BrowserWorker(tmp_path, resolver=nothing).url_problem("https://nowhere.test/") is None


def test_the_operator_can_opt_in_to_local_pages(tmp_path):
    worker = BrowserWorker(tmp_path, profile=safety.OPERATOR_LOCAL, resolver=public_dns)
    assert worker.url_problem("http://127.0.0.1:3000/") is None and worker.url_problem("http://intranet.test/") is None
    assert worker.url_problem("http://169.254.169.254/")  # never, whatever the profile
    assert worker.url_problem("file:///etc/passwd")


def test_the_route_guard_refuses_sub_requests_and_redirects_to_internal_hosts(tmp_path):
    worker = BrowserWorker(tmp_path, resolver=public_dns)
    context = FakeContext()
    worker._guard(context)
    assert context.pattern == "**/*"
    verdicts = {}
    for url in ("https://cdn.test/app.js", "http://127.0.0.1:5191/api/health", "http://169.254.169.254/x", "http://intranet.test/secret",
                "data:text/plain,hi", "blob:https://example.test/1234", "about:blank", "wss://cdn.test/socket", "ws://localhost:1/x"):
        route = FakeRoute(url)
        context.handler(route)
        verdicts[url] = route.verdict
    assert verdicts["https://cdn.test/app.js"] == "continue" and verdicts["wss://cdn.test/socket"] == "continue"
    assert verdicts["data:text/plain,hi"] == "continue" and verdicts["about:blank"] == "continue" and verdicts["blob:https://example.test/1234"] == "continue"
    for blocked in ("http://127.0.0.1:5191/api/health", "http://169.254.169.254/x", "http://intranet.test/secret", "ws://localhost:1/x"):
        assert verdicts[blocked] == "abort:blockedbyclient", blocked


def test_capture_of_a_blocked_url_never_starts_a_browser(tmp_path, monkeypatch):
    worker = BrowserWorker(tmp_path, resolver=public_dns)
    monkeypatch.setattr(worker, "_ensure_browser", lambda: pytest.fail("a browser was started"))

    class Page:
        def __getattr__(self, name):
            pytest.fail("a page was opened")

    class Browser:
        def new_context(self, **kw):
            pytest.fail("a context was opened")

    result = worker._capture(Browser(), {"url": "http://127.0.0.1:5191/", "out_dir": str(tmp_path / "o")})
    assert result["error"] == "This URL cannot be opened." and "loopback" in result["hint"]


def test_launch_attempts_follow_the_family_order_then_known_browsers(monkeypatch):
    monkeypatch.setattr(web_browser, "channel_order", lambda platform=None: ["chrome", None, "msedge"])
    monkeypatch.setattr(web_browser, "find_chromium", lambda: "/pw/chromium-1/chrome-linux/chrome")
    monkeypatch.setattr(web_browser, "system_browsers", lambda: ["/usr/bin/chromium"])
    attempts = B.launch_attempts()
    assert [name for name, _ in attempts][:3] == ["chrome", "chromium", "msedge"]
    assert attempts[0][1] == {"channel": "chrome"} and attempts[1][1] == {}
    assert attempts[3][1] == {"executable_path": "/pw/chromium-1/chrome-linux/chrome"}
    assert attempts[4] == ("chromium", {"executable_path": "/usr/bin/chromium"})


def test_the_launch_loop_tries_each_browser_and_reports_the_last_failure(tmp_path, monkeypatch):
    tried = []

    class Chromium:
        def launch(self, **kw):
            tried.append(kw)
            if len(tried) < 3:
                raise RuntimeError(f"cannot start {len(tried)}\nlong stack trace")
            return "BROWSER"

    class PW:
        chromium = Chromium()

    monkeypatch.setattr(B, "launch_attempts", lambda: [("a", {"channel": "a"}), ("b", {}), ("c", {"executable_path": "/x"})])
    monkeypatch.setattr(B, "_sync_playwright_available", lambda: True)
    worker = BrowserWorker(tmp_path)
    worker._pw = PW()
    assert worker._ensure_browser() == "BROWSER" and worker.launched_with == "c" and len(tried) == 3
    assert worker.status()["ok"] is True
    failing = BrowserWorker(tmp_path)
    failing._pw = PW()
    tried.clear()
    monkeypatch.setattr(B, "launch_attempts", lambda: [("a", {})])
    assert failing._ensure_browser() is None and failing.status() == {"ok": False, "error": "cannot start 1", "playwright_installed": True}


# ---------------------------------------------------------------- the services refuse before anything is opened

def test_render_lint_reference_and_assay_refuse_internal_urls(tmp_path):
    svc = make_services(tmp_path)
    try:
        for bad in ("http://127.0.0.1:5191/api/health", "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd", "http://localhost:9/"):
            with pytest.raises(ValueError, match="cannot be opened"):
                svc.render(url=bad)
            with pytest.raises(ValueError, match="cannot be opened"):
                svc.lint_html(url=bad)
            with pytest.raises(ValueError, match="cannot be opened"):
                svc.reference_add(url=bad, video=False, analyze=False)
            with pytest.raises(ValueError, match="cannot be opened"):
                svc.assay_page(url=bad)
        assert svc.browser.calls == []
    finally:
        svc.stop()


def test_the_tools_report_a_refused_url_as_a_400_not_a_crash(client):
    auth = {"Authorization": f"Bearer {client.svc.token}"}
    response = client.post("/api/agent/call", json={"name": "render_preview", "arguments": {"url": "http://169.254.169.254/latest/"}}, headers=auth)
    assert response.status_code == 400 and "cannot be opened" in response.json()["error"]
    assert client.post("/api/renders", json={"url": "http://127.0.0.1:1/"}).status_code == 400
    assert client.post("/api/references", json={"url": "http://10.0.0.1/"}).status_code == 400


def test_local_pages_are_allowed_when_the_operator_says_so(tmp_path):
    svc = make_services(tmp_path, allow_local_urls=True)
    try:
        svc.check_url("http://127.0.0.1:3000/")
        svc.render(url="http://127.0.0.1:3000/", widths=[390])
        assert svc.browser.calls[-1]["url"] == "http://127.0.0.1:3000/"
        with pytest.raises(ValueError):
            svc.check_url("http://169.254.169.254/")
    finally:
        svc.stop()


def test_page_assay_fetches_through_the_family_web_client(tmp_path, monkeypatch):
    svc = make_services(tmp_path)
    seen = {}

    def fake_fetch(url, **kw):
        seen.update(url=url, **kw)
        return {"ok": True, "text": "<html><body><button>Go</button></body></html>", "via": "hub"}

    monkeypatch.setattr("vitruvius_hoard.services.fam_web.fetch_or_local", fake_fetch)
    monkeypatch.setattr("vitruvius_hoard.services.safety.check_url", lambda url, profile="public", resolver=None: None)
    svc.assay_runner = lambda cmd, timeout: (0, '{"works": true, "cases": []}', "")
    try:
        result = svc.assay_page(url="https://example.test/page")
        assert result["works"] is True and seen["url"] == "https://example.test/page" and seen["accept"] == "html"
        assert (tmp_path / "data" / "assay" / result["id"] / "index.html").read_text().startswith("<html>")
        monkeypatch.setattr("vitruvius_hoard.services.fam_web.fetch_or_local", lambda url, **kw: {"ok": False, "error": "HTTP 404", "error_kind": "http"})
        with pytest.raises(ValueError, match="Could not fetch https://example.test/page: HTTP 404"):
            svc.assay_page(url="https://example.test/page")
    finally:
        svc.stop()


# ---------------------------------------------------------------- a real headless browser

class Spy(http.server.BaseHTTPRequestHandler):
    hits: list = []

    def do_GET(self):  # noqa: N802
        Spy.hits.append(self.path)
        body = b"<html><head><title>Spy page</title></head><body><h1>hello</h1></body></html>" if self.path == "/" else b"x"
        self.send_response(200)
        self.send_header("Content-Type", "text/html" if self.path == "/" else "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def spy_server():
    Spy.hits = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Spy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


needs_browser = pytest.mark.skipif(not web_browser.playwright_installed() or not (web_browser.find_chromium() or web_browser.system_browsers()),
                                   reason="no Chromium for Playwright on this machine")


@needs_browser
def test_a_real_page_cannot_reach_the_local_network(tmp_path, spy_server):
    worker = BrowserWorker(tmp_path, timeout_s=60)
    try:
        html = f'<html><body><h1 id="t">Design</h1><img src="http://127.0.0.1:{spy_server}/secret.png"><script src="http://localhost:{spy_server}/x.js"></script></body></html>'
        result = worker.capture(html=html, widths=[390], wait_ms=200)
        assert "error" not in result, result
        assert result["files"][0]["w"] == 390 and result["probe"].get("dom_size")
        assert Spy.hits == []  # the sub-requests were stopped in the browser
        blocked = worker.capture(url=f"http://127.0.0.1:{spy_server}/", widths=[390])
        assert blocked["error"] == "This URL cannot be opened." and Spy.hits == []
    finally:
        worker.stop()


@needs_browser
def test_a_real_local_page_renders_when_the_operator_opts_in(tmp_path, spy_server):
    worker = BrowserWorker(tmp_path, timeout_s=60, profile=safety.OPERATOR_LOCAL)
    try:
        result = worker.capture(url=f"http://127.0.0.1:{spy_server}/", widths=[390, 1024], wait_ms=200)
        assert "error" not in result, result
        assert [f["w"] for f in result["files"]] == [390, 1024] and all(__import__("os").path.getsize(f["path"]) > 100 for f in result["files"])
        assert result["probe"]["page_meta"]["title"] == "Spy page"
        assert "/" in Spy.hits
    finally:
        worker.stop()


@needs_browser
@pytest.mark.skipif(B.ffmpeg_path() is None, reason="ffmpeg is not installed")
def test_a_real_scroll_video_is_encoded_with_the_shared_ffmpeg(tmp_path):
    worker = BrowserWorker(tmp_path, timeout_s=90)
    try:
        html = "<html><body style='height:2400px;background:linear-gradient(#fff,#36c)'><h1>Scroll</h1></body></html>"
        result = worker.capture(html=html, widths=[390], wait_ms=100, record=True)
        assert "error" not in result, result
        assert result["video"] and result["video"].endswith(".mp4") and __import__("os").path.getsize(result["video"]) > 1000
        assert result["poster"].endswith("poster.png")
    finally:
        worker.stop()
