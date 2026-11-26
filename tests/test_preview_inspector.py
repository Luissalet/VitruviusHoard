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


def test_tool_is_read_only_and_reports_the_selection(services):
    tool = TOOLS_BY_NAME["app_project_selection"]
    assert tool.annotations["readOnlyHint"] is True and not tool.annotations.get("destructiveHint")
    project = services.app_projects.create("Selector", "work-board")
    empty = call_tool(services, "app_project_selection", {"id": project["id"]})
    assert empty["selection"] == [] and "Nothing is selected" in empty["note"]
    services.preview_selections.set(project["id"], [element()], project["revision"])
    found = call_tool(services, "app_project_selection", {"id": project["id"]})
    assert found["count"] == 1 and found["selection"][0]["line"] == 1 and found["revision"] == project["revision"]
    with pytest.raises(LookupError):
        preview_inspector.read_selection(services, "0" * 16)


def test_api_stores_the_selection_and_serves_the_script(client):
    project = client.svc.app_projects.create("Selector", "work-board")
    base = f"/api/app-projects/{project['id']}/selection"
    assert client.get(base).json()["selection"] == []
    stored = client.put(base, json={"selection": [element(), {"selector": ""}], "revision": project["revision"]})
    assert stored.status_code == 200 and stored.json()["count"] == 1
    assert client.get(base).json()["selection"][0]["tag"] == "h1"
    assert client.put(base, json={"selection": "nope"}).status_code == 400
    assert client.put("/api/app-projects/" + "0" * 16 + "/selection", json={"selection": []}).status_code == 404
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
