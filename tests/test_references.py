import io

from vitruvius_hoard import references as R
from vitruvius_hoard.db import Database


def make_db(tmp_path):
    return Database(tmp_path / "t.db")


def test_extract_palette_on_synthetic_image(tmp_path):
    from PIL import Image

    path = tmp_path / "swatch.png"
    img = Image.new("RGB", (60, 60), (255, 255, 255))
    for x in range(0, 30):
        for y in range(30):
            img.putpixel((x, y), (200, 30, 30))
    img.save(path)
    palette = R.extract_palette(str(path), n=4)
    assert isinstance(palette, list)
    assert any(p.startswith("#") for p in palette)


def test_extract_palette_missing_file_returns_empty():
    assert R.extract_palette("/no/such/file.png") == []


def test_meta_from_html():
    html = '<html><head><title>My Page</title><meta name="description" content="A nice page"></head></html>'
    meta = R._meta_from_html(html)
    assert meta["title"] == "My Page"
    assert meta["description"] == "A nice page"


def test_add_and_get_reference(tmp_path, services):
    row = services.reference_add(html="<html><title>Demo</title><body>hi</body></html>", tags=["glass"], note="test",
                                 video=False, analyze=False)
    assert row["id"]
    fetched = services.reference_get(row["id"])
    assert fetched is not None
    assert fetched["tags"] == ["glass"]


def test_reference_search_by_tag(tmp_path, services):
    services.reference_add(html="<html></html>", tags=["brutalist"], video=False, analyze=False)
    services.reference_add(html="<html></html>", tags=["swiss"], video=False, analyze=False)
    results = services.reference_search(tags=["brutalist"])
    assert len(results) == 1
    assert results[0]["tags"] == ["brutalist"]


def test_reference_search_fts_by_note(tmp_path, services):
    services.reference_add(html="<html></html>", note="a very distinctive aurora vibe", video=False, analyze=False)
    results = services.reference_search(query="aurora")
    assert len(results) == 1


def test_reference_delete(tmp_path, services):
    row = services.reference_add(html="<html></html>", video=False, analyze=False)
    assert services.reference_delete(row["id"]) is True
    assert services.reference_get(row["id"]) is None
    assert services.reference_delete(row["id"]) is False


def test_reference_similar_by_shared_tags(tmp_path, services):
    a = services.reference_add(html="<html></html>", tags=["editorial", "serif"], video=False, analyze=False)
    b = services.reference_add(html="<html></html>", tags=["editorial"], video=False, analyze=False)
    c = services.reference_add(html="<html></html>", tags=["brutalist"], video=False, analyze=False)
    sims = services.reference_similar(a["id"])
    ids = [s["id"] for s in sims]
    assert ids.index(b["id"]) < ids.index(c["id"])


def test_reference_add_with_video_records_capture(tmp_path, services):
    row = services.reference_add(html="<html></html>", video=True, analyze=False)
    assert "video" in row["files"] or row["files"].get("desktop")


def test_reference_add_requires_url_or_html(services):
    import pytest
    with pytest.raises(ValueError):
        services.reference_add(video=False, analyze=False)
