import asyncio
import json
import urllib.error
import urllib.request

import pytest

from vitruvius_hoard.app_canvas import CanvasSessions
from vitruvius_hoard.app_preview import INSPECTOR_SCRIPT, PREVIEW_SCRIPTS, SCRIPT_ROOT, inject_scripts


def test_injection_preserves_html_and_script_order():
    source = '<!doctype html>\n<HTML><body>Á<!-- </body> --><script>const example = "</body>";</script>\r\n</BODY></HTML>'
    scripts = ("app-bridge.js", *PREVIEW_SCRIPTS)
    inspector = f'<script src="{SCRIPT_ROOT}{INSPECTOR_SCRIPT}"></script>'
    deferred = "".join(f'<script defer src="{SCRIPT_ROOT}{name}"></script>' for name in ("app-bridge.js", "preview-refresh.js"))
    assert inject_scripts(source, scripts) == source.replace(
        "<body>", inspector + "<body>",
    ).replace("</BODY>", deferred + "</BODY>")
    assert inject_scripts("<p>fragment", scripts) == inspector + "<p>fragment" + deferred
    document = '<html><head><title>Sample</title></head><body><textarea></body></textarea></body></html>'
    metadata = '<meta name="vitruvius-preview-revision" content="new">'
    assert inject_scripts(document, scripts, "new") == document.replace(
        "</head>", metadata + inspector + "</head>",
    ).replace("</textarea></body>", "</textarea>" + deferred + "</body>")


@pytest.mark.parametrize("first_app_tag", [
    '<script src="/assets/listeners.js"></script>',
    '<link rel="stylesheet" href="/assets/app.css" onload="setup()">',
    '<template><script>setup()</script></template>',
])
def test_inspector_loads_before_project_markup_that_can_run_code(first_app_tag):
    prefix = ('<!doctype html><html><head><meta charset="utf-8">'
              '<meta http-equiv="Content-Security-Policy" content="script-src \'self\'">'
              '<title>Sample</title>')
    source = prefix + first_app_tag + '</head><body></body></html>'
    served = inject_scripts(source, ("app-bridge.js", *PREVIEW_SCRIPTS), "new", "session")
    assert served.startswith(prefix + f'<script src="{SCRIPT_ROOT}{INSPECTOR_SCRIPT}"></script>' + first_app_tag)
    assert served.index('content="session"') < served.index('</head>')
    assert served.index('app-bridge.js') < served.index('preview-refresh.js')


def test_listed_preview_extension_and_frame_guard(tmp_path, monkeypatch):
    from vitruvius_hoard import app_preview
    from vitruvius_hoard.app_projects import AppProjects

    for script in PREVIEW_SCRIPTS:
        (tmp_path / script).write_bytes(f"/* {script} */".encode("utf-8"))
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
        script_positions = [html.index(script) for script in (INSPECTOR_SCRIPT, "app-bridge.js", "preview-refresh.js")]
        assert script_positions == sorted(script_positions)
        assert f'<meta name="vitruvius-preview-revision" content="{preview["revision"]}">' in html
        for script in PREVIEW_SCRIPTS:
            with urllib.request.urlopen(url + SCRIPT_ROOT + script, timeout=5) as response:
                assert response.read() == (tmp_path / script).read_bytes()
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


def test_default_actor_colors_are_distinct_in_each_project_until_palette_is_full():
    canvas = CanvasSessions()
    callers = ["claude-capataz", "codex-agrimensor", "codex-astra"]
    callers.extend(f"designer-{index}" for index in range(5))
    profiles = {caller: canvas.actor_for("project", caller, {}) for caller in callers}
    palette = {actor["color"] for actor in profiles.values()}
    assert len(palette) == 8
    assert profiles[callers[0]]["color"] == "#a46114"

    last = canvas.actor_for("project", "extra-designer", {})
    assert last["color"] in palette
    assert canvas.actor_for("project", "extra-designer", {}) == last
    assert {caller: canvas.actor_for("project", caller, {}) for caller in reversed(callers)} == profiles
    assert canvas.actor_for("other", callers[1], {})["color"] == "#a46114"

    canvas.actor_for("explicit", "agent-with-color", {"color": "#A46114"})
    assert canvas.actor_for("explicit", callers[0], {})["color"] != "#a46114"


@pytest.mark.asyncio
async def test_actor_profile_follows_a_caller_across_canvas_sessions():
    canvas = CanvasSessions()
    session = canvas.attach("project", "before")
    declared = {"id": "foreman", "name": "Foreman", "color": "#5b42d3"}
    caller = "preview-foreman"
    other_caller = "preview-designer"

    assert canvas.actor_for("project", caller, declared) == declared
    other = canvas.actor_for("project", other_caller, {})
    assert other["id"] == other["name"] == other_caller
    assert other["color"] != declared["color"]
    assert canvas.actor_for("project", caller, {}) == declared

    canvas.detach(session)
    session = canvas.attach("project", "after")
    assert canvas.actor_for("project", caller, {}) == declared
    assert canvas.actor_for("project", other_caller, {}) == other
    assert canvas.actor_for("separate", caller, {})["id"] == caller

    alias = canvas.actor_for("project", other_caller, {"id": "designer", "name": "Designer"})
    assert alias == {"id": "designer", "name": "Designer", "color": other["color"]}
    retired = await asyncio.wait_for(session.next_event(), 1)
    assert retired == {"hoardDock": 1, "type": "dock/cursor", "state": "gone", "actor": {"id": other_caller}}
    assert canvas.actor_for("project", other_caller, {}) == alias
    assert canvas.actor_for("project", caller, {}) == declared


@pytest.mark.asyncio
async def test_presence_is_project_scoped_and_keeps_separate_agents():
    canvas = CanvasSessions()
    first = canvas.attach("project")
    second = canvas.attach("project")
    other = canvas.attach("other")
    actors = [{"id": "one", "name": "One"}, {"id": "two", "name": "Two", "color": "#266bb2"}]
    target = {"vsrc": "pages/index.html:1:12", "box": {"x": 10, "y": 20, "w": 30, "h": 40}}
    workers = [asyncio.create_task(asyncio.to_thread(canvas.prepare_edit, "project", "old", actor, target))
               for actor in actors]
    events = [await asyncio.wait_for(first.next_event(), 1) for _ in actors]
    assert {event["actor"]["id"] for event in events} == {"one", "two"}
    observed = {event["id"]: event for event in events}
    for _ in actors:
        event = await asyncio.wait_for(second.next_event(), 1)
        assert observed[event["id"]] == event
        assert event["type"] == "canvas/presence"
        assert event["revision"] == "old"
        assert event["target"] == target
        assert not canvas.resolve("project", other.id, event["id"], {"ok": True})
        assert canvas.resolve("project", first.id, event["id"], {"ok": True})
        assert canvas.resolve("project", second.id, event["id"], {"ok": True})
    assert other.events.empty()
    await asyncio.gather(*workers)


@pytest.mark.asyncio
async def test_unanswered_presence_expires_and_does_not_consume_the_next_call():
    canvas = CanvasSessions()
    session = canvas.attach("project")
    await asyncio.to_thread(canvas.prepare_edit, "project", "old", {"id": "leaving"}, {"box": None}, timeout=0.02)
    expired = session.events.get_nowait()
    assert expired["actor"]["id"] == "leaving"
    session.events.put_nowait(expired)
    assert not canvas.resolve("project", session.id, expired["id"], {"ok": True})
    work = asyncio.create_task(asyncio.to_thread(canvas.call, "project", "app_read", {}, {}))
    current = await asyncio.wait_for(session.next_event(), 1)
    assert current["type"] == "dock/call"
    result = {"ok": True}
    assert canvas.resolve("project", session.id, current["id"], result)
    assert await work == result


@pytest.mark.asyncio
async def test_presence_waits_for_the_visible_revision_across_preview_reconnect():
    canvas = CanvasSessions()
    old = canvas.attach("project", "old")
    canvas.attach("other", "new")
    work = asyncio.create_task(asyncio.to_thread(canvas.wait_for_revision, "project", "new"))
    await asyncio.sleep(0.03)
    assert not work.done()
    canvas.detach(old)
    canvas.attach("project", "new")
    await asyncio.wait_for(work, 0.5)


@pytest.mark.asyncio
async def test_source_presence_precedes_committed_revision(tmp_path):
    from vitruvius_hoard.app_projects import AppProjects

    projects = AppProjects(tmp_path)
    project = projects.create("Presence fixture")
    id = project["id"]
    revision = project["revision"]
    session = projects.canvas.attach(id)
    source = project["files"]["pages/index.html"]
    heading = source.index("<h2>") + 1
    vsrc = f"pages/index.html:1:{heading}"
    with projects.revision_events.subscribe(id) as changes:
        work = asyncio.create_task(asyncio.to_thread(
            projects.edit_source, id, vsrc, "h2", revision, {"kind": "text", "value": "Updated"},
            actor={"id": "one"},
        ))
        event = await asyncio.wait_for(session.next_event(), 1)
        assert event["target"] == {"vsrc": vsrc, "box": None}
        assert event["change"]["files"] == ["pages/index.html"]
        index = json.loads((projects.root / id / "project-index.json").read_text(encoding="utf-8"))
        assert index["revision"] == revision
        assert changes.empty()
        assert projects.canvas.resolve(id, session.id, event["id"], {"ok": True})
        edited = await work
        assert edited["revision"] != revision
        assert edited["undo"]["tool"] == "app_project_undo"
        _, change = await asyncio.wait_for(changes.get(), 1)
        assert change["revision"] == edited["revision"]

        replacement = edited["files"]["pages/index.html"].replace("Updated", "File patch")
        work = asyncio.create_task(asyncio.to_thread(
            projects.update, id, {"pages/index.html": replacement}, edited["revision"], actor={"id": "two"},
        ))
        event = await asyncio.wait_for(session.next_event(), 1)
        assert event["actor"]["id"] == "two"
        assert event["target"]["sources"] == [vsrc]
        assert projects.canvas.resolve(id, session.id, event["id"], {"ok": True})
        updated = await work
        assert updated["files"]["pages/index.html"] == replacement

    assert projects.update(id, {"pages/index.html": replacement}, updated["revision"],
                           actor={"id": "two"})["revision"] == updated["revision"]
    assert session.events.empty()
