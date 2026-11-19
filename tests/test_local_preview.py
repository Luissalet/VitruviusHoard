"""Loopback previews and local pages with relative assets for render_preview."""
from vitruvius_hoard import agent_tools
from vitruvius_hoard.browser import loopback_preview


def test_only_loopback_urls_count_as_local_previews():
    assert loopback_preview("http://127.0.0.1:5173/")
    assert loopback_preview("http://localhost:8080/page")
    assert not loopback_preview("http://192.168.1.10/")
    assert not loopback_preview("https://example.org/")
    assert not loopback_preview(None)
    assert not loopback_preview("not a url")


def test_local_page_path_resolves_a_folder_to_its_index(tmp_path):
    (tmp_path / "index.html").write_text("<link rel=stylesheet href=style.css>", encoding="utf-8")
    assert agent_tools._local_page_path(str(tmp_path)) == (tmp_path / "index.html").resolve()
    assert "style.css" in agent_tools.read_local_page(str(tmp_path))


def test_render_preview_keeps_its_search_vocabulary():
    tool = agent_tools.TOOLS_BY_NAME["render_preview"]
    assert "Sinónimos" in tool.description
