from conftest import FakeBrowser

from vitruvius_hoard.browser import BrowserWorker, PROBE_JS, _sync_playwright_available


def test_probe_js_is_a_single_function_expression():
    assert PROBE_JS.strip().startswith("()")
    assert "return out" in PROBE_JS


def test_probe_js_wraps_every_metric_in_try_catch():
    assert PROBE_JS.count("safe(") >= 15


def test_fake_browser_capture_writes_files(tmp_path):
    fb = FakeBrowser()
    result = fb.capture(html="<html></html>", widths=[390, 1024], out_dir=tmp_path / "r1")
    assert len(result["files"]) == 2
    for f in result["files"]:
        assert __import__("pathlib").Path(f["path"]).is_file()


def test_fake_browser_capture_failure_mode(tmp_path):
    fb = FakeBrowser(fail=True)
    result = fb.capture(html="<html></html>", out_dir=tmp_path / "r2")
    assert result["error"] == "no browser"
    assert "hint" in result


def test_fake_browser_status():
    fb = FakeBrowser()
    status = fb.status()
    assert status["ok"] is True
    fb2 = FakeBrowser(fail=True)
    assert fb2.status()["ok"] is False


def test_playwright_availability_probe_does_not_raise():
    # Whatever the answer, calling this must never raise.
    assert isinstance(_sync_playwright_available(), bool)


def test_browser_worker_returns_no_browser_error_when_playwright_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("vitruvius_hoard.browser._sync_playwright_available", lambda: False)
    worker = BrowserWorker(tmp_path, timeout_s=5.0)
    result = worker.capture(html="<html></html>", out_dir=tmp_path / "out")
    assert result["error"] == "no browser"
    worker.stop()


def test_browser_worker_capture_needs_html_or_url(tmp_path):
    worker = BrowserWorker(tmp_path, timeout_s=5.0)

    def fake_ensure(self):
        class FakeBrowserHandle:
            def new_context(self, **kw):
                raise AssertionError("should not reach context creation without html/url")

        return FakeBrowserHandle()

    worker._ensure_browser = fake_ensure.__get__(worker)
    result = worker.capture(out_dir=tmp_path / "out2")
    assert result.get("error")
    worker.stop()
