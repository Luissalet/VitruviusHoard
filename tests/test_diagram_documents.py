"""Editable sources retain independent human/agent edits and real revision history."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import sqlite3
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from vitruvius_hoard.diagrams.documents import DocumentStore, drawing, normalize
from vitruvius_hoard.diagrams.document_tools import DocumentEdit, DocumentSave, edit, save
from vitruvius_hoard.hoard_link.agentkit import AppError
from vitruvius_hoard.diagrams.exchange import drawio, import_document, mermaid


def sample():
    return {"diagram": {"type": "flowchart", "title": "Pedido", "nodes": [
        {"id": "start", "label": "Recibir"}, {"id": "end", "label": "Enviar"}],
        "edges": [{"id": "ship", "from": "start", "to": "end", "label": "sí"}]},
        "view": {"nodes": {"start": {"x": 80, "y": 100, "width": 180, "height": 70},
                           "end": {"x": 420, "y": 100, "width": 160, "height": 70}}, "edges": {}}}


def test_drawio_roundtrip_retains_group_geometry_and_overlapping_native_ids(tmp_path):
    content = sample()
    content["diagram"].update(type="architecture", groups=[{"id": "start", "label": "Equipo"}])
    content["diagram"]["nodes"][0]["group"] = "start"
    content["diagram"]["edges"][0]["id"] = "start"
    row = DocumentStore(tmp_path).save(content)
    exported = drawio(row)
    cells = ET.fromstring(exported).findall(".//mxCell")
    assert len({c.get("id") for c in cells}) == len(cells)
    imported, warnings = import_document(exported)
    assert warnings and imported["source"] == exported
    assert imported["view"]["nodes"]["start"] == row["content"]["view"]["nodes"]["start"]
    assert imported["diagram"]["nodes"][0]["group"] == "start"
    assert imported["diagram"]["edges"][0]["id"] == "start"


def test_generated_edge_ids_skip_later_explicit_ids():
    content = sample()
    content["diagram"]["edges"] = [{"from": "start", "to": "end"}, {"id": "edge-1", "from": "end", "to": "start"}]
    edges = normalize(content)["diagram"]["edges"]
    assert edges[1]["id"] == "edge-1" and edges[0]["id"] != "edge-1"


def test_mermaid_export_retains_graph_labels_and_relationships(tmp_path):
    row = DocumentStore(tmp_path).save(sample())
    text = mermaid(row)
    imported, _ = import_document(text)
    assert [n["label"] for n in imported["diagram"]["nodes"]] == ["Recibir", "Enviar"]
    assert imported["diagram"]["edges"][0]["label"] == "sí"


def test_reciprocal_routes_use_different_lanes_and_respect_manual_points(tmp_path):
    content = sample()
    content["diagram"]["edges"].append({"id": "return", "from": "end", "to": "start"})
    row = DocumentStore(tmp_path).save(content)
    outward, returning = row["rendering"]["scene"]["routes"]
    assert returning["points"] != list(reversed(outward["points"]))
    assert max(p[0] for p in returning["points"]) > 580
    content["view"]["edges"]["return"] = {"points": [[700, 250]], "source_port": "bottom"}
    row = DocumentStore(tmp_path).save(content)
    assert row["rendering"]["scene"]["routes"][1]["points"][1] == [700, 250]


def test_api_document_edit_read_export_and_conflict(client):
    initial = client.post("/api/diagrams/documents", json={"content": sample()})
    assert initial.status_code == 201, initial.text
    first = initial.json()
    endpoint = f'/api/diagrams/documents/{first["id"]}'
    changed = deepcopy(first["content"])
    changed["diagram"]["title"] = "Publicado"
    assert client.post("/api/diagrams/documents", json={"id": first["id"], "base_revision": 1, "content": changed}).status_code == 201
    changed["diagram"]["title"] = "Otro título"
    conflict = client.post("/api/diagrams/documents", json={"id": first["id"], "base_revision": 1, "content": changed})
    assert conflict.status_code == 409, conflict.text
    assert client.get(endpoint).json()["revision"] == 2
    source = client.get(endpoint + "/source.json?revision=1").json()
    assert source["content"]["diagram"]["title"] == "Pedido"
    assert client.get(endpoint + "/export.svg?mode=dark").headers["content-type"].startswith("image/svg+xml")
    assert client.get(endpoint + "/viewer").status_code == 200
    assert client.get(endpoint + "/compare?before_revision=1").json()["title_changed"]


@pytest.mark.parametrize("bad", [{"view": {"nodes": {"start": {"fill": 1}}}}, {"profile": "wrong"}, {"view": {"edges": {"ship": {"points": None}}}}])
def test_api_bad_document_is_reported_without_publishing(client, bad):
    content = sample()
    content.update(bad)
    response = client.post("/api/diagrams/documents", json={"content": content})
    assert response.status_code in (400, 422), response.text
    assert client.get("/api/diagrams/documents").json()["documents"] == []


def test_empty_document_and_discovery_do_not_create_a_database(tmp_path):
    store = DocumentStore(tmp_path)
    assert store.list() == [] and not store.path.exists()
    row = store.save({})
    assert row["content"]["diagram"]["nodes"] == []
    assert ET.fromstring(row["rendering"]["svg"]["light"]).get("viewBox") == "0 0 960 640"


def test_saved_geometry_and_connector_endpoints_survive_reopen(tmp_path):
    row = DocumentStore(tmp_path).save(sample())
    reloaded = DocumentStore(tmp_path).get(row["id"])
    assert reloaded == row
    scene = reloaded["rendering"]["scene"]
    assert scene["boxes"]["start"]["x"] == 80
    assert scene["routes"][0]["points"][0] == [260, 135]
    assert scene["routes"][0]["points"][-1] == [420, 135]
    assert 'data-node-id="start"' in reloaded["rendering"]["svg"]["light"]


def test_agent_text_and_user_geometry_merge_from_the_same_read_revision(tmp_path):
    store = DocumentStore(tmp_path)
    first = store.save(sample())
    agent = deepcopy(first["content"])
    agent["diagram"]["nodes"][0]["label"] = "Recepción verificada"
    store.save(agent, did=first["id"], base_revision=1)
    user = deepcopy(first["content"])
    user["view"]["nodes"]["start"]["x"] = 140
    saved = store.save(user, did=first["id"], base_revision=1)
    assert saved["revision"] == 3
    assert saved["content"]["diagram"]["nodes"][0]["label"] == "Recepción verificada"
    assert saved["content"]["view"]["nodes"]["start"]["x"] == 140
    assert store.get(first["id"], 1)["content"]["diagram"]["nodes"][0]["label"] == "Recibir"


def test_same_field_conflict_is_not_published_and_preserves_both_sources(tmp_path):
    store = DocumentStore(tmp_path)
    first = store.save(sample())
    a, b = deepcopy(first["content"]), deepcopy(first["content"])
    a["diagram"]["nodes"][0]["label"] = "A"
    b["diagram"]["nodes"][0]["label"] = "B"
    store.save(a, did=first["id"], base_revision=1)
    with pytest.raises(AppError) as caught:
        store.save(b, did=first["id"], base_revision=1)
    assert caught.value.code == "conflict" and "start/label" in caught.value.details["field"]
    assert store.get(first["id"])["revision"] == 2
    assert b["diagram"]["nodes"][0]["label"] == "B"


def test_selective_undo_keeps_later_unrelated_edits(tmp_path):
    store = DocumentStore(tmp_path)
    first = store.save(sample())
    a = deepcopy(first["content"])
    a["diagram"]["nodes"][0]["label"] = "Verificado"
    second = store.save(a, did=first["id"], base_revision=1)
    b = deepcopy(second["content"])
    b["diagram"]["nodes"][1]["label"] = "Despachado"
    store.save(b, did=first["id"], base_revision=2)
    undone = store.undo(first["id"], 2)
    assert [n["label"] for n in undone["content"]["diagram"]["nodes"]] == ["Recibir", "Despachado"]
    assert len(store.history(first["id"])) == 4


def test_simultaneous_independent_writers_are_serialized_without_lost_changes(tmp_path):
    store = DocumentStore(tmp_path)
    first = store.save(sample())
    def change(index):
        content = deepcopy(first["content"])
        content["diagram"]["nodes"][index]["label"] = f"Writer {index}"
        return DocumentStore(tmp_path).save(content, did=first["id"], base_revision=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(change, [0, 1]))
    current = store.get(first["id"])
    assert current["revision"] == 3
    assert [n["label"] for n in current["content"]["diagram"]["nodes"]] == ["Writer 0", "Writer 1"]


def test_invalid_edit_rolls_back_before_publishing_revision(tmp_path):
    store = DocumentStore(tmp_path)
    first = store.save(sample())
    broken = deepcopy(first["content"])
    broken["diagram"]["edges"][0]["to"] = "absent"
    with pytest.raises(ValueError):
        store.save(broken, did=first["id"], base_revision=1)
    assert store.get(first["id"])["revision"] == 1


def test_initial_geometry_overrides_merge_by_field_but_keep_conflicts(tmp_path):
    store = DocumentStore(tmp_path)
    source = sample()
    source["view"] = {"nodes": {}, "edges": {}}
    first = store.save(source)
    wide, moved = deepcopy(first["content"]), deepcopy(first["content"])
    wide["view"]["nodes"]["start"] = {"width": 240}
    moved["view"]["nodes"]["start"] = {"x": 300}
    store.save(wide, did=first["id"], base_revision=1)
    merged = store.save(moved, did=first["id"], base_revision=1)
    assert merged["content"]["view"]["nodes"]["start"] == {"width": 240, "x": 300}
    conflicting = deepcopy(first["content"])
    conflicting["view"]["nodes"]["start"] = {"width": 400}
    with pytest.raises(AppError, match="changed"):
        store.save(conflicting, did=first["id"], base_revision=1)
    assert store.get(first["id"])["revision"] == 3


def test_surgical_native_edit_deletes_only_incident_connectors(tmp_path):
    svc = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path))
    row = save(svc, DocumentSave(content=sample()))
    row = edit(svc, DocumentEdit(id=row["id"], base_revision=1, edits=[
        {"collection": "nodes", "id": "start", "values": {"label": "Nuevo", "details": "Fuente elegida por la persona"}}]))
    assert row["content"]["diagram"]["nodes"][0]["details"] == "Fuente elegida por la persona"
    row = edit(svc, DocumentEdit(id=row["id"], base_revision=2, edits=[
        {"collection": "nodes", "id": "start", "action": "remove"}]))
    assert row["content"]["diagram"]["edges"] == []
    assert row["content"]["view"]["nodes"].keys() == {"end"}
