import json

import pytest
from conftest import make_services


def test_render_html_creates_row_with_lint(tmp_path):
    svc = make_services(tmp_path)
    row = svc.render(html="<html lang='en'><body><h1>Hi</h1></body></html>")
    assert row["id"]
    assert row["kind"] == "html"
    assert "findings" in row["lint"]
    fetched = svc.get_render(row["id"])
    assert fetched["id"] == row["id"]


def test_render_url_kind(tmp_path):
    svc = make_services(tmp_path)
    row = svc.render(url="https://example.com")
    assert row["kind"] == "url"


def test_render_requires_html_or_url(tmp_path):
    svc = make_services(tmp_path)
    with pytest.raises(ValueError):
        svc.render()


def test_render_browser_failure_is_recorded(tmp_path):
    svc = make_services(tmp_path, browser_fail=True)
    row = svc.render(html="<html></html>")
    assert "error" in row["metrics"]


def test_list_renders_ordered_desc(tmp_path):
    svc = make_services(tmp_path)
    a = svc.render(html="<html>a</html>")
    b = svc.render(html="<html>b</html>")
    rows = svc.list_renders()
    assert rows[0]["id"] == b["id"]


def test_render_file_path_blocks_traversal(tmp_path):
    svc = make_services(tmp_path)
    row = svc.render(html="<html></html>")
    with pytest.raises(PermissionError):
        svc.render_file_path(row["id"], "../../etc/passwd")


def test_lint_html_direct(tmp_path):
    svc = make_services(tmp_path)
    result = svc.lint_html(html="<html></html>")
    assert "findings" in result


def test_lint_by_render_id(tmp_path):
    svc = make_services(tmp_path)
    row = svc.render(html="<html></html>")
    result = svc.lint_html(render_id=row["id"])
    assert "findings" in result


def test_lint_unknown_render_id_raises(tmp_path):
    svc = make_services(tmp_path)
    with pytest.raises(LookupError):
        svc.lint_html(render_id="nope")


def test_critique_render_merges_vision_and_lint(tmp_path):
    svc = make_services(tmp_path)
    row = svc.render(html="<html></html>")
    result = svc.critique_render(row["id"], use_vision=True)
    assert 0 <= result["score"] <= 10
    assert result["vision_model"] == "fake-vision-model"


def test_critique_render_without_vision(tmp_path):
    svc = make_services(tmp_path)
    row = svc.render(html="<html></html>")
    result = svc.critique_render(row["id"], use_vision=False)
    assert result["vision_model"] is None


def test_critique_unknown_render_raises(tmp_path):
    svc = make_services(tmp_path)
    with pytest.raises(LookupError):
        svc.critique_render("nope")


def test_render_compare(tmp_path):
    svc = make_services(tmp_path)
    a = svc.render(html="<html>a</html>", widths=[1024])
    b = svc.render(html="<html>b</html>", widths=[1024])
    result = svc.render_compare(a["id"], b["id"], width=1024)
    assert "diff_pct" in result


def test_render_compare_unknown_id(tmp_path):
    svc = make_services(tmp_path)
    a = svc.render(html="<html>a</html>")
    with pytest.raises(LookupError):
        svc.render_compare(a["id"], "nope")


def test_tokens_generate_and_get(tmp_path):
    svc = make_services(tmp_path)
    row = svc.tokens_generate({"name": "Demo", "base_color": "#3355ff"})
    assert row["id"]
    fetched = svc.tokens_get(row["id"])
    assert fetched["name"] == "Demo"


def test_tokens_list_and_delete(tmp_path):
    svc = make_services(tmp_path)
    row = svc.tokens_generate({"name": "Demo2"})
    assert len(svc.tokens_list()) == 1
    assert svc.tokens_delete(row["id"]) is True
    assert svc.tokens_delete(row["id"]) is False


def test_tokens_export_formats(tmp_path):
    svc = make_services(tmp_path)
    row = svc.tokens_generate({"name": "Demo3"})
    assert svc.tokens_export(row["id"], "css").startswith(":root")
    assert svc.tokens_export(row["id"], "tailwind").startswith("@theme")
    assert "color" in svc.tokens_export(row["id"], "w3c")
    assert isinstance(svc.tokens_export(row["id"], "json"), dict)


def test_tokens_export_unknown_format_raises(tmp_path):
    svc = make_services(tmp_path)
    row = svc.tokens_generate({"name": "Demo4"})
    with pytest.raises(ValueError):
        svc.tokens_export(row["id"], "yaml")


def test_tokens_preview_creates_render(tmp_path):
    svc = make_services(tmp_path)
    row = svc.tokens_generate({"name": "Demo5"})
    preview = svc.tokens_preview(row["id"])
    assert preview["id"]
    updated = svc.tokens_get(row["id"])
    assert updated["preview_render_id"] == preview["id"]


def test_sources_add_list_status(tmp_path):
    svc = make_services(tmp_path)
    svc.source_add(id="mysrc", url="https://example.com/repo", kind="git")
    sources = svc.sources_list()
    assert any(s["id"] == "mysrc" for s in sources)
    status = svc.source_status("mysrc")
    assert status["status"] == "idle"


def test_source_status_unknown_raises(tmp_path):
    svc = make_services(tmp_path)
    with pytest.raises(LookupError):
        svc.source_status("nope")


def test_source_ingest_sync_local(tmp_path):
    svc = make_services(tmp_path)
    folder = tmp_path / "localsrc"
    folder.mkdir()
    (folder / "README.md").write_text("# Hi\nText.")
    svc.source_add(id="loc", url=str(folder), kind="local")
    result = svc.source_ingest("loc", sync=True)
    assert result["ok"] is True
    status = svc.source_status("loc")
    assert status["status"] == "ready"


def test_seed_sources_idempotent(tmp_path):
    svc = make_services(tmp_path)
    seeds = {"sources": [{"id": "seed1", "url": "https://x", "kind": "git"}]}
    n1 = svc.seed_sources(seeds)
    n2 = svc.seed_sources(seeds)
    assert n1 == 1
    assert n2 == 0


def test_get_and_update_settings(tmp_path):
    svc = make_services(tmp_path)
    settings = svc.get_settings()
    assert settings["vision_enabled"] is True
    updated = svc.update_settings({"vision_enabled": False, "language": "es"})
    assert updated["vision_enabled"] is False
    assert updated["language"] == "es"


def test_update_settings_writes_backend_json(tmp_path):
    svc = make_services(tmp_path)
    svc.update_settings({"backend": {"only_resident": False}})
    assert svc.config.backend_json_path.is_file()
    data = json.loads(svc.config.backend_json_path.read_text())
    assert data["only_resident"] is False


def test_status_shape(tmp_path):
    svc = make_services(tmp_path)
    status = svc.status()
    assert status["service"] == "vitruvius-hoard"
    assert "counts" in status and "browser" in status and "models" in status


def test_catalog_styles_palettes_fonts(tmp_path):
    svc = make_services(tmp_path)
    svc.db.execute("INSERT INTO sources(id, kind, url, status) VALUES ('s','git','u','ready')")
    svc.db.execute("INSERT INTO styles(source_id, name, slug) VALUES ('s','Glass','glass')")
    svc.db.execute("INSERT INTO palettes(source_id, name) VALUES ('s','Ocean')")
    svc.db.execute("INSERT INTO font_pairings(source_id, heading, body) VALUES ('s','Fraunces','Inter')")
    assert len(svc.catalog_styles()) == 1
    assert len(svc.catalog_palettes()) == 1
    assert len(svc.catalog_fonts()) == 1


def test_import_demos_from_local_source(tmp_path):
    svc = make_services(tmp_path)
    folder = svc.config.sources_dir / "demoset"
    folder.mkdir(parents=True)
    (folder / "one.html").write_text("<html><title>One</title></html>")
    (folder / "two.html").write_text("<html><title>Two</title></html>")
    result = svc.import_demos("demoset")
    assert result["ok"] is True
    assert result["count"] == 2
    assert len(svc.reference_search(limit=10)) == 2
