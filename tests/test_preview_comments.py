"""Comments pinned on the application preview: life cycle, storage, tools and API."""
import json
import zipfile

import pytest

from vitruvius_hoard import preview_comments
from vitruvius_hoard.agent_tools import TOOLS_BY_NAME, call_tool
from vitruvius_hoard.hoard_link.agentkit import AppError

COMMENT_TOOLS = ("app_project_comments", "app_project_comment_ack", "app_project_comment_resolve",
                 "app_project_comment_reply", "app_project_comment_dismiss", "app_project_comment_undo")


def element(**fields):
    base = {"selector": "main > h1", "tag": "H1", "classes": ["title"], "text": "Board", "vsrc": "pages/index.html:3:5",
            "box": {"x": 8, "y": 16, "w": 300, "h": 40}, "same_vsrc_count": 1}
    base.update(fields)
    return base


@pytest.fixture
def project(services):
    return services.app_projects.create("Commented", "work-board")


def add(services, project, note="Make the title bigger", **fields):
    return services.preview_comments.add(project["id"], note, fields.pop("revision", project["revision"]), fields.pop("page", "/"), element(**fields))


def test_a_comment_keeps_the_note_the_element_and_the_revision_it_was_made_on(services, project):
    comment = add(services, project)
    assert comment["id"] == "c1" and comment["status"] == "pending" and comment["revision"] == project["revision"]
    assert (comment["vsrc"], comment["selector"], comment["tag"], comment["page"]) == ("pages/index.html:3:5", "main > h1", "h1", "/")
    assert comment["box"] == {"x": 8, "y": 16, "w": 300, "h": 40} and comment["element_text"] == "Board"
    assert comment["anchor"]["state"] == "ok" and comment["stale"] is False
    assert [entry["status"] for entry in comment["history"]] == ["pending"]
    assert add(services, project, "Another")["id"] == "c2"


def test_a_comment_needs_a_note_an_element_and_a_real_revision(services, project):
    store = services.preview_comments
    with pytest.raises(ValueError, match="note"):
        store.add(project["id"], "   ", project["revision"], "/", element())
    with pytest.raises(ValueError, match="revision"):
        store.add(project["id"], "x", None, "/", element())
    with pytest.raises(ValueError, match="Unknown revision"):
        store.add(project["id"], "x", "r-nope", "/", element())
    with pytest.raises(ValueError, match="element"):
        store.add(project["id"], "x", project["revision"], "/", {"selector": ""})
    assert store.list(project["id"], "all")["count"] == 0


def test_the_life_cycle_pending_seen_resolved_with_a_summary(services, project):
    store = services.preview_comments
    add(services, project)
    seen = store.acknowledge(project["id"], ["c1"])["comments"][0]
    assert seen["status"] == "seen" and seen["history"][-1]["by"] == "agent"
    assert store.acknowledge(project["id"], ["c1"])["comments"][0]["status"] == "seen"  # acknowledging twice changes nothing
    assert len(store._load(project["id"])["comments"][0]["history"]) == 2
    with pytest.raises(ValueError, match="needs a text"):
        store.resolve(project["id"], "c1", " ")
    done = store.resolve(project["id"], "c1", "Raised the title to 2rem in the stylesheet")
    assert done["status"] == "resolved" and done["summary"].startswith("Raised") and done["resolved_in"] == project["revision"]
    with pytest.raises(ValueError, match="resolved"):
        store.acknowledge(project["id"], ["c1"])
    assert store.list(project["id"])["count"] == 0 and store.list(project["id"], "resolved")["count"] == 1


def test_the_agent_can_answer_and_the_person_replies_back_to_pending(services, project):
    store = services.preview_comments
    add(services, project)
    answered = store.reply(project["id"], "c1", "Bigger than the heading in the header?")
    assert answered["status"] == "answered" and answered["reply"].startswith("Bigger")
    assert store.list(project["id"])["count"] == 0  # waiting for the person, not for the agent
    back = store.respond(project["id"], "c1", "Yes, the same size")
    assert back["status"] == "pending" and back["history"][-1]["by"] == "person" and back["history"][-1]["text"] == "Yes, the same size"
    with pytest.raises(ValueError, match="pending"):
        store.respond(project["id"], "c1", "again")


def test_dismissed_and_resolved_comments_stay_listed_and_can_be_reopened(services, project):
    store = services.preview_comments
    add(services, project)
    add(services, project, "Second")
    store.dismiss(project["id"], "c1", "Already so in the print styles")
    store.resolve(project["id"], "c2", "Done")
    assert store.list(project["id"], "all")["counts"] == {"pending": 0, "seen": 0, "answered": 0, "resolved": 1, "dismissed": 1, "lost": 0}
    reopened = store.reopen(project["id"], "c1")
    assert reopened["status"] == "pending" and reopened["summary"] is None
    with pytest.raises(ValueError):
        store.reopen(project["id"], "c1")


def test_undo_restores_the_state_before_the_last_step_and_not_the_creation(services, project):
    store = services.preview_comments
    add(services, project)
    store.acknowledge(project["id"], ["c1"])
    store.resolve(project["id"], "c1", "Done")
    assert store.undo(project["id"], "c1")["status"] == "seen"
    restored = store.undo(project["id"], "c1")
    assert restored["status"] == "pending" and restored["summary"] is None and len(restored["history"]) == 1
    with pytest.raises(ValueError, match="Nothing to undo"):
        store.undo(project["id"], "c1")
    store.reply(project["id"], "c1", "Which one?")
    store.respond(project["id"], "c1", "This one")
    assert store.undo(project["id"], "c1")["status"] == "answered"
    assert store.list(project["id"], "answered")["comments"][0]["reply"] == "Which one?"


def test_an_element_that_left_the_page_leaves_the_pin_without_anchor_but_keeps_the_comment(services, project):
    store = services.preview_comments
    add(services, project)
    add(services, project, "Second", selector="footer")
    assert store.set_anchors(project["id"], project["revision"], [{"id": "c1", "state": "lost"}, {"id": "c2", "state": "ok", "vsrc": "pages/index.html:9:1", "box": {"x": 1, "y": 2, "w": 3, "h": 4}}, {"id": "zz", "state": "ok"}, "junk"])["changed"] == 2
    lost = store.list(project["id"], "lost")
    assert [c["id"] for c in lost["comments"]] == ["c1"] and lost["counts"]["lost"] == 1
    assert lost["comments"][0]["note"] == "Make the title bigger" and lost["comments"][0]["status"] == "pending"
    moved = store.list(project["id"], "all")["comments"][1]
    assert moved["vsrc"] == "pages/index.html:3:5" and moved["anchor"]["vsrc"] == "pages/index.html:9:1" and moved["box"]["w"] == 3
    assert store.set_anchors(project["id"], project["revision"], [{"id": "c1", "state": "lost"}])["changed"] == 0  # same report: nothing rewritten
    assert store.set_anchors(project["id"], project["revision"], [{"id": "c1", "state": "ok", "vsrc": "pages/index.html:3:5"}])["changed"] == 1
    assert store.list(project["id"], "lost")["count"] == 0


def test_a_comment_made_on_an_older_revision_says_it_is_stale(services, project):
    add(services, project)
    newer = services.app_projects.update(project["id"], {"pages/index.html": "<h1>Changed</h1>\n"}, project["revision"])
    comment = services.preview_comments.list(project["id"])["comments"][0]
    assert comment["revision"] == project["revision"] != newer["revision"] and comment["stale"] is True
    assert services.preview_comments.resolve(project["id"], "c1", "Done")["resolved_in"] == newer["revision"]


def test_comments_are_saved_in_the_project_data_and_survive_a_restart(services, project, tmp_path):
    add(services, project)
    services.preview_comments.acknowledge(project["id"], ["c1"])
    path = services.app_projects._directory(project["id"]) / "comments.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["format"] == preview_comments.FORMAT and saved["comments"][0]["status"] == "seen" and saved["next"] == 2
    reread = preview_comments.PreviewComments(services.app_projects)
    assert reread.list(project["id"])["comments"][0]["status"] == "seen"
    assert reread.add(project["id"], "After restart", project["revision"], "/", element())["id"] == "c2"


def test_comments_are_never_in_the_source_or_in_an_export(services, project):
    add(services, project, "Secret note about the title")
    saved = services.app_projects.get(project["id"])
    assert "Secret note" not in json.dumps(saved["files"]) and "comments.json" not in saved["files"]
    out = services.app_projects.export(project["id"])
    with zipfile.ZipFile(out["path"]) as bundle:
        names = bundle.namelist()
        text = "\n".join(bundle.read(name).decode("utf-8", "replace") for name in names)
    assert "comments.json" not in names and "Secret note" not in text
    assert "preview-comments" not in text and "dock/comment" not in text


def test_the_number_of_comments_is_bounded(services, project, monkeypatch):
    monkeypatch.setattr(preview_comments, "MAX_COMMENTS", 2)
    add(services, project)
    add(services, project)
    with pytest.raises(ValueError, match="at most 2"):
        add(services, project)


def test_tools_are_short_and_the_reader_is_read_only(services, project):
    for name in COMMENT_TOOLS:
        assert name in TOOLS_BY_NAME and not TOOLS_BY_NAME[name].annotations["destructiveHint"]
    assert TOOLS_BY_NAME["app_project_comments"].annotations["readOnlyHint"] is True
    assert all(TOOLS_BY_NAME[name].annotations["readOnlyHint"] is False for name in COMMENT_TOOLS[1:])
    empty = call_tool(services, "app_project_comments", {"id": project["id"]})
    assert empty["count"] == 0 and "Nobody has commented" in empty["note"]


def test_an_agent_works_a_comment_through_the_tools(services, project):
    pid = project["id"]
    add(services, project)
    add(services, project, "Which colour?", selector="button")
    listed = call_tool(services, "app_project_comments", {"id": pid})
    assert listed["count"] == 2 and listed["comments"][0]["status"] == "pending"
    assert call_tool(services, "app_project_comment_ack", {"id": pid, "comment_ids": ["c1", "c2"]})["comments"][1]["status"] == "seen"
    assert call_tool(services, "app_project_comments", {"id": pid, "status": "pending"})["count"] == 0
    assert call_tool(services, "app_project_comments", {"id": pid, "status": "seen"})["count"] == 2
    assert call_tool(services, "app_project_comment_reply", {"id": pid, "comment_id": "c2", "text": "Which one: red or blue?"})["status"] == "answered"
    resolved = call_tool(services, "app_project_comment_resolve", {"id": pid, "comment_id": "c1", "summary": "Title is 2rem now"})
    assert resolved["status"] == "resolved" and resolved["resolved_in"] == project["revision"]
    assert call_tool(services, "app_project_comment_undo", {"id": pid, "comment_id": "c1"})["status"] == "seen"
    assert call_tool(services, "app_project_comment_dismiss", {"id": pid, "comment_id": "c1", "reason": "Not needed"})["status"] == "dismissed"
    assert call_tool(services, "app_project_comments", {"id": pid, "status": "all"})["counts"]["dismissed"] == 1
    with pytest.raises(AppError):
        call_tool(services, "app_project_comment_resolve", {"id": pid, "comment_id": "c9", "summary": "x"})
    with pytest.raises(AppError):
        call_tool(services, "app_project_comments", {"id": "0" * 16})


def test_api_covers_what_the_person_does(client):
    project = client.svc.app_projects.create("Commented", "work-board")
    base = f"/api/app-projects/{project['id']}/comments"
    assert client.get(base).json()["count"] == 0
    body = {"note": "Tighter spacing", "revision": project["revision"], "page": "/", "element": element()}
    created = client.post(base, json=body)
    assert created.status_code == 200 and created.json()["id"] == "c1"
    assert client.post(base, json={**body, "note": ""}).status_code == 400
    assert client.post(base, json={**body, "revision": "r-nope"}).status_code == 400
    client.svc.preview_comments.reply(project["id"], "c1", "How tight?")
    assert client.post(f"{base}/c1/respond", json={"text": "8px"}).json()["status"] == "pending"
    assert client.post(f"{base}/c1/dismiss", json={"text": "changed my mind"}).json()["status"] == "dismissed"
    assert client.post(f"{base}/c1/undo").json()["status"] == "pending"
    assert client.post(f"{base}/c1/reopen", json={}).status_code == 400  # it is pending again, nothing to reopen
    assert client.put(f"{base}/anchors", json={"anchors": [{"id": "c1", "state": "lost"}], "revision": project["revision"]}).json()["changed"] == 1
    assert client.get(base, params={"status": "lost"}).json()["count"] == 1
    assert client.get(base, params={"status": "bogus"}).status_code == 400
    assert client.post(f"{base}/c7/undo").status_code == 404
    assert client.get("/api/app-projects/" + "0" * 16 + "/comments").status_code == 404
