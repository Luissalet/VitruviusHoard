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


def serving(services, project, monkeypatch, revision=None, session="opening-1"):
    """Make the project's preview look like it is running the given revision, as process ``pid``."""
    monkeypatch.setattr(services.app_projects, "status", lambda id: {"state": "running", "revision": revision or project["revision"], "url": "http://127.0.0.1:1", "pid": 7, "session": session})


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


@pytest.mark.parametrize("undo_step", [False, True])
def test_source_undo_reopens_its_resolved_comment_and_keeps_the_summary(services, project, undo_step):
    projects, store = services.app_projects, services.preview_comments
    pid = project["id"]
    add(services, project, "Add the year to the introduction")
    add(services, project, "Checked by the person")
    add(services, project, "Already there")
    store.acknowledge(pid, ["c1", "c3"])
    store.resolve(pid, "c3", "Already present")

    changed = projects.update(pid, {"pages/index.html": project["files"]["pages/index.html"] + "<p>1911</p>"}, project["revision"])
    store.resolve(pid, "c1", "Added 1911 to the introduction")
    store.resolve_person(pid, "c2")
    assert store.list(pid, "resolved")["count"] == 3

    if undo_step:
        # Undo the edit after a later change to a different file.
        later = projects.update(pid, {"layout.html": changed["files"]["layout.html"] + "\n<!-- retained -->"}, changed["revision"])
        undone = projects.undo_change(pid, changed["history"][-1]["id"], later["revision"], later["updated_ts"])
        assert undone["files"]["layout.html"].endswith("<!-- retained -->")
    else:
        undone = projects.undo(pid, changed["revision"], changed["updated_ts"], project["revision"])
    assert undone["files"]["pages/index.html"] == project["files"]["pages/index.html"]

    result = call_tool(services, "app_project_comments", {"id": pid})
    [reopened] = result["comments"]
    assert reopened["id"] == "c1" and reopened["status"] == "pending" and reopened["resolved_in"] is None
    assert reopened["history"][-1]["source_undo"] is True
    assert reopened["history"][-1]["text"] == "Added 1911 to the introduction"
    assert reopened["history"][-1]["before"]["status"] == "resolved"
    assert store.list(pid)["comments"] == [reopened]
    assert [item["id"] for item in store.list(pid, "resolved")["comments"]] == ["c2", "c3"]

    # Explicitly undoing the comment step remains possible and does not replay it on the next read.
    assert store.undo(pid, "c1")["status"] == "resolved"
    assert store.list(pid)["count"] == 0


def test_rolling_back_an_unrelated_edit_does_not_reopen_the_comment(services, project):
    projects, store = services.app_projects, services.preview_comments
    pid = project["id"]
    add(services, project)
    store.acknowledge(pid, ["c1"])
    fixed = projects.update(pid, {"pages/index.html": project["files"]["pages/index.html"] + "<p>Fixed</p>"}, project["revision"])
    store.resolve(pid, "c1", "Fixed the introduction")
    later = projects.update(pid, {"layout.html": fixed["files"]["layout.html"] + "\n<!-- later -->"}, fixed["revision"])
    restored = projects.undo(pid, later["revision"], later["updated_ts"], fixed["revision"])
    assert store.list(pid, "resolved")["count"] == 1
    undone = projects.undo(pid, restored["revision"], restored["updated_ts"], project["revision"])
    projects.update(pid, {"layout.html": undone["files"]["layout.html"] + "\n<!-- after undo -->"}, undone["revision"])
    assert store.list(pid)["comments"][0]["status"] == "pending"


def test_undoing_a_save_between_the_fix_and_resolution_keeps_the_comment_resolved(services, project):
    projects, store = services.app_projects, services.preview_comments
    pid = project["id"]
    add(services, project, "Add the year to the introduction")
    store.acknowledge(pid, ["c1"])
    fixed = projects.update(pid, {"pages/index.html": project["files"]["pages/index.html"] + "<p>1911</p>"}, project["revision"])
    other = projects.update(pid, {"layout.html": fixed["files"]["layout.html"] + "\n<!-- unrelated -->"}, fixed["revision"])
    assert store.resolve(pid, "c1", "Added 1911")["resolved_in"] == other["revision"]
    restored = projects.undo_change(pid, other["history"][-1]["id"], other["revision"], other["updated_ts"])
    assert "1911" in restored["files"]["pages/index.html"]
    [comment] = call_tool(services, "app_project_comments", {"id": pid, "status": "resolved"})["comments"]
    assert comment["status"] == "resolved" and "source_undo" not in comment["history"][-1]

    projects.undo_change(pid, fixed["history"][-1]["id"], restored["revision"], restored["updated_ts"])
    [comment] = call_tool(services, "app_project_comments", {"id": pid, "status": "open"})["comments"]
    assert comment["status"] == "pending" and comment["history"][-1]["source_undo"]


def test_explicit_resolution_identifies_a_fix_in_another_file(services, project):
    projects, store = services.app_projects, services.preview_comments
    pid = project["id"]
    add(services, project)
    store.acknowledge(pid, ["c1"])
    fixed = projects.update(pid, {"assets/style.css": project["files"]["assets/style.css"] + "\nh1{font-size:2rem}"}, project["revision"])
    store.resolve(pid, "c1", "Adjusted the stylesheet", revision=fixed["revision"])
    projects.undo_change(pid, fixed["history"][-1]["id"], fixed["revision"], fixed["updated_ts"])
    assert store.list(pid)["comments"][0]["status"] == "pending"


def test_the_agent_can_answer_and_the_person_replies_back_to_pending(services, project):
    store = services.preview_comments
    add(services, project)
    store.acknowledge(project["id"], ["c1"])
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
    store.acknowledge(project["id"], ["c1", "c2"])
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
    store.acknowledge(project["id"], ["c1"])
    store.reply(project["id"], "c1", "Which one?")
    store.respond(project["id"], "c1", "This one")
    assert store.undo(project["id"], "c1")["status"] == "answered"
    assert store.list(project["id"], "answered")["comments"][0]["reply"] == "Which one?"


def test_an_element_that_left_the_page_leaves_the_pin_without_anchor_but_keeps_the_comment(services, project, monkeypatch):
    serving(services, project, monkeypatch)
    store = services.preview_comments
    add(services, project)
    add(services, project, "Second", selector="footer")
    assert store.set_anchors(project["id"], project["revision"], [{"id": "c1", "state": "lost"}, {"id": "c2", "state": "ok", "vsrc": "pages/index.html:9:1", "box": {"x": 1, "y": 2, "w": 3, "h": 4}}, {"id": "zz", "state": "ok"}, "junk"], "opening-1")["changed"] == 2
    lost = store.list(project["id"], "lost")
    assert [c["id"] for c in lost["comments"]] == ["c1"] and lost["counts"]["lost"] == 1
    assert lost["comments"][0]["note"] == "Make the title bigger" and lost["comments"][0]["status"] == "pending"
    moved = store.list(project["id"], "all")["comments"][1]
    assert moved["vsrc"] == "pages/index.html:3:5" and moved["anchor"]["vsrc"] == "pages/index.html:9:1" and moved["box"]["w"] == 3
    assert store.set_anchors(project["id"], project["revision"], [{"id": "c1", "state": "lost"}], "opening-1")["changed"] == 0  # same report: nothing rewritten
    assert store.set_anchors(project["id"], project["revision"], [{"id": "c1", "state": "ok", "vsrc": "pages/index.html:3:5"}], "opening-1")["changed"] == 1
    assert store.list(project["id"], "lost")["count"] == 0


def test_a_comment_made_on_an_older_revision_says_it_is_stale(services, project):
    add(services, project)
    newer = services.app_projects.update(project["id"], {"pages/index.html": "<h1>Changed</h1>\n"}, project["revision"])
    comment = services.preview_comments.list(project["id"])["comments"][0]
    assert comment["revision"] == project["revision"] != newer["revision"] and comment["stale"] is True
    services.preview_comments.acknowledge(project["id"], ["c1"])
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
    client.svc.preview_comments.acknowledge(project["id"], ["c1"])
    client.svc.preview_comments.reply(project["id"], "c1", "How tight?")
    assert client.post(f"{base}/c1/respond", json={"text": "8px"}).json()["status"] == "pending"
    assert client.post(f"{base}/c1/dismiss", json={"text": "changed my mind"}).json()["status"] == "dismissed"
    assert client.post(f"{base}/c1/undo").json()["status"] == "pending"
    assert client.post(f"{base}/c1/reopen", json={}).status_code == 400  # it is pending again, nothing to reopen
    assert client.put(f"{base}/anchors", json={"anchors": [{"id": "c1", "state": "lost"}], "revision": project["revision"]}).status_code == 409  # no preview is running
    serving(client.svc, project, pytest.MonkeyPatch())
    assert client.put(f"{base}/anchors", json={"anchors": [{"id": "c1", "state": "lost"}], "revision": project["revision"], "session": "opening-1"}).json()["changed"] == 1
    assert client.get(base, params={"status": "lost"}).json()["count"] == 1
    assert client.get(base, params={"status": "bogus"}).status_code == 400
    assert client.post(f"{base}/c7/undo").status_code == 404
    assert client.get("/api/app-projects/" + "0" * 16 + "/comments").status_code == 404


def test_the_agent_cannot_skip_seen_and_only_the_person_dismisses_what_is_not_seen(services, project):
    store, pid = services.preview_comments, project["id"]
    add(services, project)
    for step in (lambda: store.resolve(pid, "c1", "Done"), lambda: store.reply(pid, "c1", "Which?"), lambda: store.dismiss(pid, "c1", "no")):
        with pytest.raises(ValueError, match="only from seen"):
            step()
    assert store.list(pid, "pending")["count"] == 1
    store.acknowledge(pid, ["c1"])
    store.reply(pid, "c1", "Which one?")
    with pytest.raises(ValueError, match="only from seen"):
        store.resolve(pid, "c1", "Done")  # answered: the person has to reply first
    with pytest.raises(ValueError, match="only from seen"):
        store.dismiss(pid, "c1", "no", "agent")
    assert store.dismiss(pid, "c1", "changed my mind", "person")["status"] == "dismissed"


def test_a_batch_of_acknowledgements_is_all_or_nothing(services, project):
    store, pid = services.preview_comments, project["id"]
    add(services, project)
    add(services, project, "Second")
    store.acknowledge(pid, ["c2"])
    store.resolve(pid, "c2", "Done")
    before = (services.app_projects._directory(pid) / "comments.json").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="resolved"):
        store.acknowledge(pid, ["c1", "c2"])
    with pytest.raises(LookupError):
        store.acknowledge(pid, ["c1", "c9"])
    assert (services.app_projects._directory(pid) / "comments.json").read_text(encoding="utf-8") == before
    assert store.list(pid, "pending")["count"] == 1
    mixed = store.acknowledge(pid, ["c1", "c1"])  # a repeated id counts once
    assert [c["status"] for c in mixed["comments"]] == ["seen"]


def test_revisions_named_in_writes_must_be_revisions_of_the_project(services, project):
    store, pid = services.preview_comments, project["id"]
    add(services, project)
    store.acknowledge(pid, ["c1"])
    with pytest.raises(ValueError, match="Unknown revision"):
        store.resolve(pid, "c1", "Done", "unknown-revision")
    assert store.list(pid, "seen")["comments"][0]["resolved_in"] is None
    with pytest.raises(ValueError, match="Unknown revision"):
        store.set_anchors(pid, "invented-anchor-revision", [{"id": "c1", "state": "lost"}])
    with pytest.raises(ValueError, match="needs the source revision"):
        store.set_anchors(pid, None, [{"id": "c1", "state": "lost"}])
    assert store.list(pid, "lost")["count"] == 0


def test_a_comment_or_anchor_from_a_revision_the_preview_no_longer_serves_is_refused(services, project, monkeypatch):
    from vitruvius_hoard.preview_inspector import StaleSelection
    newer = services.app_projects.update(project["id"], {"pages/index.html": "<h1>Changed</h1>\n"}, project["revision"])
    monkeypatch.setattr(services.app_projects, "status", lambda id: {"state": "running", "revision": newer["revision"], "url": "http://127.0.0.1:1"})
    with pytest.raises(StaleSelection, match="pick the element again"):
        add(services, project)  # the element was picked on the older revision
    with pytest.raises(StaleSelection):
        services.preview_comments.set_anchors(project["id"], project["revision"], [])
    made = services.preview_comments.add(project["id"], "On what is shown", newer["revision"], "/", element())
    assert made["revision"] == newer["revision"] and made["stale"] is False


PNG = "data:image/png;base64," + __import__("base64").b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 40).decode()


def test_the_crop_is_kept_with_the_revision_it_was_taken_on_and_not_exported(services, project):
    store, pid = services.preview_comments, project["id"]
    made = store.add(pid, "Look", project["revision"], "/", element(), PNG)
    assert made["has_crop"] is True and made["crop"] == {"revision": project["revision"], "bytes": 48}
    assert store.crop(pid, "c1").read_bytes().startswith(b"\x89PNG")
    assert add(services, project, "No crop")["has_crop"] is False
    with pytest.raises(LookupError):
        store.crop(pid, "c2")
    for bad in ("data:image/jpeg;base64,AAAA", "data:image/png;base64,!!!", "data:image/png;base64," + "QUFB", PNG + "A"):
        with pytest.raises(ValueError):
            store.add(pid, "bad", project["revision"], "/", element(), bad)
    with pytest.raises(ValueError, match="at most"):
        store.add(pid, "big", project["revision"], "/", element(), "data:image/png;base64," + __import__("base64").b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 400_000).decode())
    with pytest.raises(LookupError):
        store.crop(pid, "../comments")
    out = services.app_projects.export(pid, include_data=True)
    with zipfile.ZipFile(out["path"]) as bundle:
        assert not [name for name in bundle.namelist() if "crop" in name or "comment" in name]
    assert "x" * 40 not in json.dumps(services.app_projects.get(pid)["files"])


def test_api_serves_the_crop(client):
    project = client.svc.app_projects.create("Cropped", "work-board")
    base = f"/api/app-projects/{project['id']}/comments"
    body = {"note": "Look", "revision": project["revision"], "page": "/", "element": element(), "crop": PNG}
    assert client.post(base, json=body).json()["has_crop"] is True
    served = client.get(f"{base}/c1/crop")
    assert served.status_code == 200 and served.headers["content-type"] == "image/png" and served.content.startswith(b"\x89PNG")
    assert client.get(f"{base}/c2/crop").status_code == 404
    assert client.post(base, json={**body, "crop": "data:text/html;base64,AAAA"}).status_code == 400


def test_a_late_anchor_report_is_dropped_once_the_preview_stopped_or_was_replaced(services, project, monkeypatch):
    from vitruvius_hoard.preview_inspector import StaleSelection
    store, pid = services.preview_comments, project["id"]
    add(services, project)
    report = [{"id": "c1", "state": "lost"}]
    with pytest.raises(StaleSelection, match="not running"):
        store.set_anchors(pid, project["revision"], report)  # stopped: the stub preview is not running
    serving(services, project, monkeypatch)
    assert store.set_anchors(pid, project["revision"], report, "opening-1")["changed"] == 1
    with pytest.raises(ValueError, match="needs the preview session"):
        store.set_anchors(pid, project["revision"], [{"id": "c1", "state": "ok", "vsrc": "pages/index.html:3:5"}])  # no session: nothing is revalidated
    with pytest.raises(ValueError, match="needs the preview session"):
        store.set_anchors(pid, project["revision"], [{"id": "c1", "state": "ok", "vsrc": "pages/index.html:3:5"}], "")
    with pytest.raises(StaleSelection, match="earlier opening"):
        store.set_anchors(pid, project["revision"], [{"id": "c1", "state": "ok", "vsrc": "pages/index.html:3:5"}], "opening-0")  # an earlier opening of the preview
    assert store.list(pid, "lost")["count"] == 1  # still without anchor
    monkeypatch.setattr(services.app_projects, "status", lambda id: {"state": "stopped"})
    with pytest.raises(StaleSelection):
        store.set_anchors(pid, project["revision"], [{"id": "c1", "state": "ok", "vsrc": "pages/index.html:3:5"}], "opening-1")
    assert store.list(pid, "lost")["count"] == 1  # a report after the stop does not bring the pin back


def test_a_page_keeps_as_many_comments_as_the_preview_paints(services, project, monkeypatch):
    monkeypatch.setattr(preview_comments, "MAX_PER_PAGE", 2)
    add(services, project)
    add(services, project)
    with pytest.raises(ValueError, match="A page keeps at most 2"):
        add(services, project)
    assert add(services, project, page="/about")["page"] == "/about"  # another page has its own room


def test_the_page_limit_matches_the_one_in_the_inspector_script():
    import re
    from pathlib import Path
    script = (Path(preview_comments.__file__).parent / "preview_scripts" / "preview-inspector.js").read_text(encoding="utf-8")
    assert int(re.search(r"const MAX_PINS = (\d+)", script).group(1)) == 300
    assert preview_comments.MAX_PER_PAGE == 300


def test_identity_attributes_are_kept_with_the_comment(services, project):
    made = services.preview_comments.add(project["id"], "Details", project["revision"], "/", element(tag="a", parent="ul|pages/index.html:3:1", index=2),
                                         None, {"id": "details-archive", "href": "/records?view=archive", "class": "x", "name": 5})
    assert made["attrs"] == {"id": "details-archive", "href": "/records?view=archive"}
    assert (made["parent"], made["index"]) == ("ul|pages/index.html:3:1", 2)
    assert add(services, project, "No attrs")["attrs"] == {}


def test_a_jpeg_crop_is_kept_too(services, project):
    jpeg = "data:image/jpeg;base64," + __import__("base64").b64encode(bytes([0xFF, 0xD8, 0xFF]) + b"x" * 40).decode()
    made = services.preview_comments.add(project["id"], "Look", project["revision"], "/", element(), jpeg)
    assert made["has_crop"] and services.preview_comments.crop(project["id"], "c1").suffix == ".jpg"


def test_the_preview_session_survives_a_live_refresh_and_changes_with_a_new_opening(tmp_path):
    import re
    from urllib.request import urlopen
    from vitruvius_hoard.app_projects import AppProjects
    projects = AppProjects(tmp_path)
    try:
        project = projects.create("Session", "work-board")
        first = projects.preview(project["id"])

        def served(preview):
            with urlopen(preview["url"], timeout=5) as response:
                html = response.read().decode("utf-8")
                return re.search(r'name="vitruvius-preview-session" content="([^"]+)"', html).group(1), response.headers["X-Vitruvius-Session"]
        assert served(first) == (first["session"], first["session"])
        newer = projects.update(project["id"], {"pages/index.html": "<h1>Changed</h1>\n"}, project["revision"])
        refreshed = projects.preview(project["id"], newer["revision"])  # what the live refresh does: another process, the same opening
        assert refreshed["revision"] == newer["revision"] and refreshed["pid"] != first["pid"] and refreshed["session"] == first["session"]
        projects.stop(project["id"])
        assert projects.status(project["id"]).get("session") is None
        reopened = projects.preview(project["id"], newer["revision"])
        assert reopened["session"] and reopened["session"] != first["session"]
    finally:
        projects.close()


def test_person_can_resolve_pending_comment_and_undo_from_preview(client, services, project):
    comment = add(services, project)
    route = f"/api/app-projects/{project['id']}/comments/{comment['id']}"
    resolved = client.post(route + "/resolve")
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["history"][-1]["by"] == "person"
    assert client.post(route + "/undo").json()["status"] == "pending"
