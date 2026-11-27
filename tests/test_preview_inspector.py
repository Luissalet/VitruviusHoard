"""The element selection kept for the agent, its tool, API and the inspector script."""
import json
import zipfile
from pathlib import Path

import pytest

from vitruvius_hoard import preview_inspector
from vitruvius_hoard.agent_tools import TOOLS_BY_NAME, call_tool


def element(**fields):
    base = {"selector": "main > h1", "tag": "H1", "classes": ["title", 7], "text": "x" * 400, "vsrc": "pages/index.html:1:1",
            "box": {"x": 8, "y": 16.5, "w": 300, "h": "wide"}, "computed": {"color": "rgb(0, 0, 0)"}, "same_vsrc_count": 1}
    base.update(fields)
    return base


def test_normalise_bounds_and_types_what_the_page_reports():
    [item] = preview_inspector.normalise([element(), {"selector": ""}, {"tag": "p"}, "junk", None])
    assert item["tag"] == "h1" and item["classes"] == ["title"]
    assert len(item["text"]) == preview_inspector.MAX_TEXT
    assert item["box"] == {"x": 8, "y": 16.5, "w": 300, "h": 0}
    assert (item["file"], item["line"], item["column"]) == ("pages/index.html", 1, 1)
    assert "affects" not in item and "note" not in item
    assert len(preview_inspector.normalise([element() for _ in range(80)])) == preview_inspector.MAX_SELECTION
    with pytest.raises(ValueError):
        preview_inspector.normalise({"selector": "a"})


def test_repeated_generated_and_unannotated_elements_say_so():
    repeated, generated, plain = preview_inspector.normalise([
        element(same_vsrc_count=5), element(vsrc="pages/index.html:4:3", vgen="table", selector="#t"), element(vsrc=None, selector="p")])
    assert repeated["affects"] == "5 elements share this source position"
    assert generated["generated_by"] == "{{table}}" and "project fields or styles" in generated["note"]
    assert "file" in generated and "no source position" in plain["note"].lower()


def test_selection_is_per_project_replaced_and_cleared():
    store = preview_inspector.PreviewSelections()
    assert store.get("a")["count"] == 0
    store.set("a", [element()], "r1")
    store.set("b", [element(selector="p"), element(selector="h2")])
    assert store.get("a")["selection"][0]["selector"] == "main > h1" and store.get("a")["revision"] == "r1"
    assert store.get("b")["count"] == 2
    store.set("b", [element(selector="li")])
    assert [i["selector"] for i in store.get("b")["selection"]] == ["li"]
    assert store.set("a", [])["count"] == 0 and store.get("a")["updated_ts"] is None


class Preview:
    """Stands in for the project's preview process: the tool and the routes only read its status."""
    def __init__(self, services):
        self.state, self.revision, self.pid = "running", "rev1", 100
        services.app_projects.status = lambda id: {"state": self.state, "revision": self.revision, "pid": self.pid if self.state == "running" else None}

    def restart(self, revision=None):
        self.state, self.pid = "running", self.pid + 1
        self.revision = revision or self.revision


def test_tool_is_read_only_and_reports_the_selection(services):
    tool = TOOLS_BY_NAME["app_project_selection"]
    assert tool.annotations["readOnlyHint"] is True and not tool.annotations.get("destructiveHint")
    project = services.app_projects.create("Selector", "work-board")
    preview = Preview(services)
    empty = call_tool(services, "app_project_selection", {"id": project["id"]})
    assert empty["selection"] == [] and "Nothing is selected" in empty["note"]
    preview_inspector.write_selection(services, project["id"], [element(revision="rev1", html="<h1>x</h1>", own_vsrc=True)], "rev1")
    found = call_tool(services, "app_project_selection", {"id": project["id"]})
    assert found["count"] == 1 and found["selection"][0]["line"] == 1 and found["revision"] == "rev1"
    assert found["selection"][0]["html"] == "<h1>x</h1>" and found["selection"][0]["own_vsrc"] is True and found["selection"][0]["revision"] == "rev1"
    assert "_session" not in found
    with pytest.raises(LookupError):
        preview_inspector.read_selection(services, "0" * 16)
    assert preview.pid == 100


def test_the_selection_dies_with_the_preview_however_it_was_stopped(services):
    project = services.app_projects.create("Selector", "work-board")
    id = project["id"]
    preview = Preview(services)
    preview_inspector.write_selection(services, id, [element()], "rev1")
    # an agent (or anything else) stops the preview: the next read is empty, with no help from the page
    preview.state = "stopped"
    stopped = call_tool(services, "app_project_selection", {"id": id})
    assert stopped["selection"] == [] and "not running" in stopped["note"]
    # starting it again does not bring the old selection back
    preview.restart()
    assert call_tool(services, "app_project_selection", {"id": id})["selection"] == []
    # a restart without a read in between is a new session too
    preview_inspector.write_selection(services, id, [element()], "rev1")
    preview.restart()
    restarted = call_tool(services, "app_project_selection", {"id": id})
    assert restarted["selection"] == [] and "restarted" in restarted["note"]
    # a report that arrives for a stopped preview is dropped
    preview.state = "stopped"
    assert preview_inspector.write_selection(services, id, [element()], "rev1")["selection"] == []


def test_the_agent_reads_the_visible_browser_without_storing_its_selection(services, monkeypatch):
    project = services.app_projects.create("Live selector", "work-board")
    project_id = project["id"]
    preview = Preview(services)
    snapshot = {"selection": [element(revision="rev1")], "revision": "rev1", "updated_ts": 123}
    monkeypatch.setattr(services.app_projects.canvas, "selection",
                        lambda id: {"ok": True, "result": snapshot} if id == project_id else None)

    live = call_tool(services, "app_project_selection", {"id": project_id})
    assert live["count"] == 1 and live["updated_ts"] == 123
    assert services.preview_selections.entry(project_id) is None

    preview.revision = "rev2"
    stale = preview_inspector.read_selection(services, project_id)
    assert stale["count"] == 0 and stale["stale_revision"] == "rev1" and stale["preview_revision"] == "rev2"
    snapshot.update(selection=[], revision="rev2")
    assert preview_inspector.read_selection(services, project_id)["count"] == 0
    assert services.preview_selections.entry(project_id) is None


def test_the_selection_is_tied_to_the_revision_the_preview_serves(services):
    project = services.app_projects.create("Selector", "work-board")
    id = project["id"]
    preview = Preview(services)
    with pytest.raises(preview_inspector.StaleSelection):
        preview_inspector.write_selection(services, id, [element()], "old")
    assert preview_inspector.write_selection(services, id, [element()], "rev1")["count"] == 1
    preview.revision = "rev2"  # a live refresh moved the preview on; the page has not reported yet
    stale = call_tool(services, "app_project_selection", {"id": id})
    assert stale["selection"] == [] and stale["stale_revision"] == "rev1" and stale["preview_revision"] == "rev2"
    assert preview_inspector.write_selection(services, id, [element()], "rev2")["revision"] == "rev2"
    assert call_tool(services, "app_project_selection", {"id": id})["count"] == 1


def test_a_selection_needs_the_served_revision_and_expired_items_are_not_the_selection(services):
    project = services.app_projects.create("Selector", "work-board")
    id = project["id"]
    Preview(services)
    with pytest.raises(ValueError):  # the old behaviour filled in the backend's revision for the page
        preview_inspector.write_selection(services, id, [element()], None)
    with pytest.raises(preview_inspector.StaleSelection):  # a card that names another revision than the report
        preview_inspector.write_selection(services, id, [element(revision="rev0")], "rev1")
    clip = {"data_url": "data:image/png;base64," + "A" * 40, "w": 10, "h": 5}
    expired = element(selector="li", expired=True, revision="rev0", text="First revised row")
    saved = preview_inspector.write_selection(services, id, [element(revision="rev1", clip=clip), expired], "rev1")
    assert saved["count"] == 1 and len(saved["expired"]) == 1 and saved["expired"][0]["expired"] is True
    assert "Expired" in saved["expired"][0]["note"] and "affects" not in saved["expired"][0]
    found = preview_inspector.read_selection(services, id)
    assert found["selection"][0]["clip"] == {"mime": "image/png", "w": 10, "h": 5, "bytes": len(clip["data_url"]) * 3 // 4, "omitted": []}  # pixels only on request
    assert preview_inspector.read_selection(services, id, clips=True)["selection"][0]["clip"]["data_url"] == clip["data_url"]
    assert [i["text"] for i in found["expired"]] == ["First revised row"]
    # only expired items left: nothing is selected, and revision is not required to say so
    only = preview_inspector.write_selection(services, id, [expired], None)
    assert only["count"] == 0 and only["selection"] == []
    # a clip that could not draw everything says what it left out, in the card
    partial = {"data_url": "data:image/png;base64," + "A" * 40, "w": 10, "h": 5, "omitted": ["img /x.png: not readable (another origin)", 7]}
    saved = preview_inspector.write_selection(services, id, [element(revision="rev1", clip=partial)], "rev1")
    card = preview_inspector.read_selection(services, id)["selection"][0]
    assert card["clip"]["omitted"] == ["img /x.png: not readable (another origin)"] and "leaves out img /x.png" in card["clip_note"]
    assert "data_url" not in card["clip"]
    # a clip that is not an image or is too big is dropped, the card stays
    big = element(clip={"data_url": "data:image/png;base64," + "A" * (preview_inspector.MAX_CLIP + 1)})
    assert "clip" not in preview_inspector.normalise([big])[0]
    assert "clip" not in preview_inspector.normalise([element(clip={"data_url": "javascript:alert(1)"})])[0]


def test_api_stores_the_selection_and_serves_the_script(client):
    project = client.svc.app_projects.create("Selector", "work-board")
    preview = Preview(client.svc)
    base = f"/api/app-projects/{project['id']}/selection"
    assert client.get(base).json()["selection"] == []
    stored = client.put(base, json={"selection": [element(), {"selector": ""}], "revision": "rev1"})
    assert stored.status_code == 200 and stored.json()["count"] == 1
    assert client.get(base).json()["selection"][0]["tag"] == "h1"
    assert client.put(base, json={"selection": [element()], "revision": "other"}).status_code == 409
    assert client.put(base, json={"selection": "nope"}).status_code == 400
    assert client.put("/api/app-projects/" + "0" * 16 + "/selection", json={"selection": []}).status_code == 404
    preview.state = "stopped"
    assert client.get(base).json()["selection"] == []
    script = client.get("/api/app-projects/preview-inspector.js")
    assert script.status_code == 200 and script.headers["content-type"].startswith("text/javascript")
    assert script.text == preview_inspector.inspector_script() and "dock/select" in script.text


def test_the_inspector_is_never_part_of_an_exported_application(services):
    project = services.app_projects.create("Selector", "work-board")
    out = services.app_projects.export(project["id"])
    with zipfile.ZipFile(out["path"]) as bundle:
        text = "\n".join(bundle.read(name).decode("utf-8", "replace") for name in bundle.namelist())
    assert "preview-inspector" not in text and "dock/select" not in text and "data-vitruvius-inspector" not in text
    source = Path(preview_inspector.__file__).with_name("app_runtime.py").read_text(encoding="utf-8")
    assert "preview-inspector" not in source
