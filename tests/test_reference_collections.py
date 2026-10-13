import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from vitruvius_hoard import references


def manifest(tmp_path, count=100):
    image = tmp_path / "snapshot.png"
    Image.new("RGB", (16, 12), "orange").save(image)
    path = tmp_path / "collection.json"
    data = {"format": "vitruvius-reference-collection/v1", "id": "studies", "name": "Design studies",
            "entries": [{"key": str(i), "title": f"Composición número {i}", "tags": ["old" if i == 0 else "new"],
                         "files": {"desktop": image.name}, "metadata": {"source_revision": "revision-a"}} for i in range(count)]}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data


def test_hundred_repeat_paging_and_old_filter(services, tmp_path):
    path, _ = manifest(tmp_path)
    result = services.reference_import_collection(str(path))
    assert result["imported"] == 100 and result["ok"]
    assert services.reference_import_collection(str(path))["reused"] == 100
    assert services.reference_collections() == [{"id": "studies", "name": "Design studies", "count": 100}]
    assert len(services.reference_search(tags=["OLD"], limit=1)) == 1
    assert len(services.reference_search(query="Composición", limit=100)) == 100
    first = services.reference_page(collection="studies", limit=60)
    second = services.reference_page(collection="studies", limit=60, before=first["next_before"])
    assert len(first["references"]) == 60 and len(second["references"]) == 40
    assert len({r["id"] for r in first["references"] + second["references"]}) == 100
    row = services.reference_get(result["references"][0]["id"])
    copied = services.reference_file_path(row["id"], "desktop.png")
    assert hashlib.sha256(copied.read_bytes()).hexdigest() == row["analysis"]["collection"]["snapshot_sha256"]["desktop"]


def test_partial_retry_version_and_concurrency(services, tmp_path):
    path, data = manifest(tmp_path, 3)
    data["entries"][2]["files"]["desktop"] = "missing.png"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = services.reference_import_collection(str(path))
    assert result["imported"] == 2 and len(result["errors"]) == 1
    Image.new("RGB", (16, 12), "green").save(tmp_path / "missing.png")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: services.reference_import_collection(str(path)), range(2)))
    assert sum(r["imported"] for r in results) == 1
    assert services.reference_collections()[0]["count"] == 3
    original_ids = {r["id"] for r in services.reference_search(limit=100)}
    Image.new("RGB", (16, 12), "blue").save(tmp_path / "missing.png")
    assert services.reference_import_collection(str(path))["imported"] == 1
    assert original_ids.issubset({r["id"] for r in services.reference_search(limit=100)})
    assert not list(services.config.references_dir.glob(".import-*"))


def test_invalid_cursor_and_manifest(services, tmp_path):
    import pytest
    with pytest.raises(ValueError, match="cursor"):
        references.page(services.db, before="broken")
    path = tmp_path / "collection.json"
    path.write_text('{}', encoding="utf-8")
    with pytest.raises(ValueError, match="manifest"):
        services.reference_import_collection(str(path))


def test_native_api(client, tmp_path):
    path, _ = manifest(tmp_path, 2)
    assert client.post("/api/reference-collections/import", json={"path": str(path)}).json()["imported"] == 2
    assert client.get("/api/reference-collections").json()["collections"][0]["count"] == 2
    assert client.get("/api/references", params={"collection": "studies", "limit": 1}).json()["next_before"]
    assert client.get("/api/references", params={"before": "bad"}).status_code == 400
    assert len(client.get("/api/design-patterns").json()["patterns"]) == 8
    assert client.post("/api/design-patterns/generate", json={"id": "elastic", "text": "á 👩‍🚀"}).json()["html"]
