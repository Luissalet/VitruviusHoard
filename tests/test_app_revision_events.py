import asyncio
import json

import pytest

from vitruvius_hoard.api.app_projects import revision_stream
from vitruvius_hoard.app_projects import AppProjects


def decode(chunk):
    lines = chunk.splitlines()
    assert lines[1] == "event: revision"
    event = json.loads(lines[2].removeprefix("data: "))
    assert lines[0] == "id: " + event["revision"]
    return event


@pytest.mark.asyncio
async def test_update_and_undo_reach_each_project_subscriber(tmp_path):
    projects = AppProjects(tmp_path)
    start = projects.create("First")
    unrelated = projects.create("Second")
    project_id = start["id"]
    one = revision_stream(projects, project_id, start["revision"])
    two = revision_stream(projects, project_id, start["revision"])
    other = revision_stream(projects, unrelated["id"], unrelated["revision"])
    for stream in (one, two, other):
        assert await anext(stream) == "retry: 500\n\n"

    original = start["files"]["pages/index.html"]
    same = await asyncio.to_thread(projects.update, project_id, {"pages/index.html": original}, start["revision"])
    assert same["revision"] == start["revision"]
    changed = await asyncio.to_thread(
        projects.update, project_id, {"pages/index.html": original + "\n<p>New</p>\n"}, start["revision"])
    expected = {
        "revision": changed["revision"], "previous_revision": start["revision"],
        "files": ["pages/index.html"], "global_styles": [],
        "ranges": {"pages/index.html": {"before": [1, 1], "after": [1, 2]}},
    }
    for stream in (one, two):
        assert decode(await asyncio.wait_for(anext(stream), 1)) == expected

    await one.aclose()
    assert len(projects.revision_events._subscribers[project_id]) == 1
    restored = await asyncio.to_thread(projects.undo, **changed["undo"]["arguments"])
    event = decode(await asyncio.wait_for(anext(two), 1))
    assert restored["revision"] == event["revision"] == start["revision"]
    assert event["previous_revision"] == changed["revision"]
    assert event["files"] == ["pages/index.html"]
    projects.close()
    for stream in (two, other):
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), 1)
    assert not projects.revision_events._subscribers


@pytest.mark.asyncio
async def test_subscription_replays_snapshot_differences_and_closes_on_archive(tmp_path):
    projects = AppProjects(tmp_path)
    original = projects.create("Board")
    project_id = original["id"]
    changed = projects.update(project_id, {"assets/style.css": "body { color: blue; }"}, original["revision"])
    stream = revision_stream(projects, project_id, original["revision"])
    assert await anext(stream) == "retry: 500\n\n"
    change = decode(await anext(stream))
    assert change["revision"] == changed["revision"] and change["previous_revision"] == original["revision"]
    assert change["files"] == change["global_styles"] == ["assets/style.css"]

    missed = projects.update(project_id, {"pages/index.html": "<h1>Latest</h1>"}, changed["revision"])
    await stream.aclose()
    resumed = revision_stream(projects, project_id, changed["revision"])
    assert await anext(resumed) == "retry: 500\n\n"
    assert decode(await anext(resumed))["revision"] == missed["revision"]
    await resumed.aclose()

    disposable = projects.create("Archive me")
    archived = revision_stream(projects, disposable["id"], disposable["revision"])
    assert await anext(archived) == "retry: 500\n\n"
    assert projects.undo(**disposable["undo"]["arguments"])["archived"]
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(archived), 1)
    projects.close()
