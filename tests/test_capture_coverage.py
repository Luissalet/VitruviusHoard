import json
from unittest.mock import Mock

import pytest

from vitruvius_hoard import review
from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.render_coverage import MAX_FULL_PAGE_HEIGHT, capture_full_page


@pytest.mark.parametrize(("page_height", "png_height", "truncated"), [
    (8_000, 8_000, False),
    (21_000, MAX_FULL_PAGE_HEIGHT, True),
    (8_000, 6_000, True),
])
def test_full_page_capture_reports_the_height_written_by_chromium(tmp_path, page_height, png_height, truncated):
    page = Mock()
    page.evaluate.return_value = page_height
    ihdr = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    page.screenshot.return_value = ihdr + (390).to_bytes(4, "big") + png_height.to_bytes(4, "big")
    path = tmp_path / "390.png"

    assert capture_full_page(page, path, 390) == {
        "h": png_height, "page_height": page_height, "captured_height": png_height, "truncated": truncated,
    }
    page.screenshot.assert_called_once_with(path=str(path), full_page=True, clip={
        "x": 0, "y": 0, "width": 390, "height": min(page_height, MAX_FULL_PAGE_HEIGHT),
    })


def test_project_capture_coverage_reaches_render_consumers(services, monkeypatch):
    project = call_tool(services, "app_project_create", {"name": "Tall page", "template": "static-page"})
    capture = services.app_browser.capture

    def long_capture(**kwargs):
        result = capture(**kwargs)
        result["files"][0].update(h=16_000, page_height=17_200, captured_height=16_000, truncated=True)
        result["files"][1].update(h=4_800, page_height=4_800, captured_height=4_800, truncated=False)
        return result

    monkeypatch.setattr(services.app_browser, "capture", long_capture)
    receipt = call_tool(services, "app_project_render", {"id": project["id"], "widths": [390, 1440]})
    render_id = receipt["id"]
    warning = [{"width": 390, "truncated": True, "page_height": 17_200, "captured_height": 16_000}]
    assert receipt["files"][0]["h"] == 16_000
    assert receipt["files"][1]["truncated"] is False
    assert receipt["capture_truncation"] == warning
    assert services.get_render(render_id)["capture_truncation"] == warning
    assert call_tool(services, "design_lint", {"render_id": render_id})["capture_truncation"] == warning

    deadlines = []
    chat = review.chat_before_deadline

    def record_deadline(link, messages, images, deadline, **options):
        deadlines.append(deadline)
        return chat(link, messages, images, deadline, **options)

    monkeypatch.setattr(review, "chat_before_deadline", record_deadline)
    critique = call_tool(services, "design_critique", {"render_id": render_id, "clean_review": True, "timeout_s": 5})
    assert critique["capture_truncation"] == warning
    assert len(deadlines) == 2 and deadlines[0] is not None and deadlines[0] == deadlines[1]
    calls = services.link_sync.chat_calls
    assert len(calls) == 2
    assert all("top 16000 of 17200 px" in messages[-1]["content"] for messages, _ in calls)

    services.assay_runner = lambda *_: (0, json.dumps({"works": True, "cases": []}), "")
    check = call_tool(services, "page_check", {"render_id": render_id})
    assert check["works"] and check["capture_truncation"] == warning


def test_saved_legacy_capture_uses_the_page_height_in_its_probe(client, monkeypatch):
    services = client.svc
    capture = services.browser.capture

    def legacy_capture(**kwargs):
        result = capture(**kwargs)
        result["files"][0].update(h=6_000)
        result["files"][1].update(h=900, full_page=False)
        result["probe"]["dom"] = {"390": {"page_height": 9_205}, "834": {"page_height": 7_000}}
        return result

    monkeypatch.setattr(services.browser, "capture", legacy_capture)
    result = client.post("/api/renders", json={"html": "<h1>Long page</h1>", "widths": [390, 834, 1440]})
    assert result.status_code == 201
    saved = client.get(f"/api/renders/{result.json()['id']}").json()
    assert saved["capture_truncation"] == [
        {"width": 390, "truncated": True, "page_height": 9_205, "captured_height": 6_000},
    ]
    assert "truncated" not in saved["files"][1]
    assert "truncated" not in saved["files"][2]
