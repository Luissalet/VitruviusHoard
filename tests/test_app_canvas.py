import asyncio
import urllib.error
import urllib.request

import pytest

from vitruvius_hoard.app_canvas import CanvasSessions
from vitruvius_hoard.app_preview import PREVIEW_SCRIPTS, SCRIPT_ROOT, inject_scripts


def test_injection_preserves_html_and_script_order():
    source = '<!doctype html>\n<HTML><body>Á<!-- </body> --><script>const example = "</body>";</script>\r\n</BODY></HTML>'
    scripts = ("app-bridge.js", *PREVIEW_SCRIPTS)
    expected = "".join(f'<script defer src="{SCRIPT_ROOT}{name}"></script>' for name in scripts)
    assert inject_scripts(source, scripts) == source.replace("</BODY>", expected + "</BODY>")
    assert inject_scripts("<p>fragment", scripts) == "<p>fragment" + expected
    document = '<html><head><title>Sample</title></head><body><textarea></body></textarea></body></html>'
    metadata = '<meta name="vitruvius-preview-revision" content="new">'
    assert inject_scripts(document, scripts, "new") == document.replace(
        "</head>", metadata + "</head>",
    ).replace("</textarea></body>", "</textarea>" + expected + "</body>")


def test_listed_preview_extension_and_frame_guard(tmp_path, monkeypatch):
    from vitruvius_hoard import app_preview
    from vitruvius_hoard.app_projects import AppProjects

    inspector = b'window.inspectorInPreview = true;'
    (tmp_path / PREVIEW_SCRIPTS[0]).write_bytes(inspector)
    monkeypatch.setattr(app_preview, "SCRIPT_DIR", tmp_path)
    projects = AppProjects(tmp_path, host_port=59249)
    project = projects.create("Nested preview")
    preview = projects.preview(project["id"])
    url = preview["url"]
    try:
        headers = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate",
                   "Sec-Fetch-Dest": "iframe", "Referer": "http://localhost:59249/"}
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=5) as response:
            html = response.read().decode("utf-8")
            assert response.headers["X-Vitruvius-Revision"] == preview["revision"]
        assert html.index("app-bridge.js") < html.index(PREVIEW_SCRIPTS[0])
        assert f'<meta name="vitruvius-preview-revision" content="{preview["revision"]}">' in html
        with urllib.request.urlopen(url + SCRIPT_ROOT + PREVIEW_SCRIPTS[0], timeout=5) as response:
            assert response.read() == inspector
        headers["Referer"] = "http://localhost:59248/"
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=5)
        assert rejected.value.code == 403
    finally:
        projects.close()


@pytest.mark.asyncio
async def test_canvas_routes_only_to_connected_project_and_exact_call():
    canvas = CanvasSessions()
    assert canvas.call("a", "app_read", {}, {})["error"]["code"] == "no_preview"
    a = canvas.attach("a")
    b = canvas.attach("b")
    extra = canvas.attach("a")
    assert canvas.call("a", "app_read", {}, {})["error"]["code"] == "multiple_previews"
    canvas.detach(extra)

    actor = {"id": "designer", "name": "Designer"}
    work = asyncio.create_task(asyncio.to_thread(canvas.call, "a", "app_highlight", {"ref": "e1"}, actor))
    event = await asyncio.wait_for(a.events.get(), 2)
    assert event == {"hoardDock": 1, "type": "dock/call", "id": event["id"],
                     "tool": "app_highlight", "args": {"ref": "e1"}, "actor": actor}
    assert b.events.empty()
    result = {"ok": True, "result": {"highlighted": "Example"}}
    assert not canvas.resolve("a", b.id, event["id"], result)
    assert not canvas.resolve("b", a.id, event["id"], result)
    assert canvas.resolve("a", a.id, event["id"], result)
    assert not canvas.resolve("a", a.id, event["id"], result)
    assert await work == result

    work = asyncio.create_task(asyncio.to_thread(canvas.call, "a", "app_read", {}, {}))
    await asyncio.wait_for(a.events.get(), 2)
    canvas.detach_project("a")
    assert (await work)["error"]["code"] == "preview_closed"
    assert canvas.call("a", "app_read", {}, {})["error"]["code"] == "no_preview"
    canvas.detach(b)


def test_cross_origin_relay_prohibited(client):
    response = client.get("/api/app-projects/project/canvas/events",
                          headers={"Origin": "http://localhost:59248", "Sec-Fetch-Site": "same-site"})
    assert response.status_code == 403
