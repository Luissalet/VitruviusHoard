import pytest
from pydantic import ValidationError
from vitruvius_hoard.motion import Composition, MotionStore, templates, page


def test_revision_conflict_and_history_survive_restart(tmp_path):
    store = MotionStore(tmp_path)
    original = Composition.model_validate(templates()["launch"])
    first = store.save(original)
    changed = original.model_copy(update={"title": "Otra versión"})
    second = store.save(changed, first["id"], 1)
    with pytest.raises(ValueError, match="conflict"):
        store.save(original, first["id"], 1)
    reopened = MotionStore(tmp_path)
    assert reopened.get(first["id"], 1)["composition"]["title"] == original.title
    assert reopened.get(first["id"])["revision"] == second["revision"] == 2


def test_invalid_timing_and_nonfinite_geometry_rejected():
    recipe = templates()["caption"]
    recipe["scenes"][0]["layers"][0]["delay"] = 4
    with pytest.raises(ValidationError):
        Composition.model_validate(recipe)
    recipe["scenes"][0]["layers"][0].update(delay=0, x=float("nan"))
    with pytest.raises(ValidationError):
        Composition.model_validate(recipe)


def test_script_like_text_is_only_scene_data():
    recipe = templates()["caption"]
    recipe["scenes"][0]["layers"][0]["text"] = '</script><script>window.stolen=true</script>'
    html = page(Composition.model_validate(recipe))
    assert '</script><script>' not in html
    assert "textContent=text" in html


def test_motion_contract_in_agent_and_http(client):
    from vitruvius_hoard.agent_tools import call_tool
    created = client.post('/api/motions', json={"composition": templates()["caption"]})
    assert created.status_code == 200
    row = created.json()
    fetched = call_tool(client.svc, 'motion_get', {"id": row['id'], "format": "html"})
    assert fetched['composition'] == row['composition']
    assert 'window.motionSeek' in fetched['html']
    invalid = client.post('/api/motions', json={"id": row['id'], "expected_revision": 99, "composition": row['composition']})
    assert invalid.status_code == 400
    assert client.get('/api/motions/' + row['id']).json()['revision'] == 1
