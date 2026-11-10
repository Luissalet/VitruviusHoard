"""Visual parity: scoring with synthetic images, then the service, REST routes and tools with the fake browser."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from vitruvius_hoard import parity
from vitruvius_hoard.agent_tools import call_tool

W, H, VH = 100, 200, 100


def page(color=(240, 240, 240), height=H, blocks=()):
    image = Image.new("RGB", (W, height), color)
    draw = ImageDraw.Draw(image)
    for (x0, y0, x1, y1, fill) in blocks:
        draw.rectangle((x0, y0, x1, y1), fill=fill)
    return image


def compare(ref_loads, cand, **kw):
    return parity.compare_widths_images(ref_loads, cand, width=W, vh=VH, **kw)


# ---------------------------------------------------------------------------------------------- scoring

def test_identical_pages_score_100_and_pass():
    result = compare([page(), page()], page())
    assert result["passed"] and result["height_pass"]
    assert result["score"] == 100.0
    assert [s["score"] for s in result["screens"]] == [100.0, 100.0]
    assert result["screens_total"] == 2 and not result["truncated"]


def test_a_different_stripe_fails_only_its_screen():
    cand = page(blocks=[(0, 120, W - 1, 139, (200, 0, 0))])  # 20 of 100 rows in the second screen
    result = compare([page(), page()], cand)
    first, second = result["screens"]
    assert first["passed"] and first["score"] == 100.0
    assert not second["passed"] and second["score"] == pytest.approx(80.0)
    assert result["failing_screens"] == [2] and not result["passed"]
    summary = parity.summarize([result])
    assert not summary["passed"] and any("pantalla 2" in f for f in summary["failures"])


def test_noise_that_differs_between_reference_loads_is_masked():
    noisy = [(10, 10, 29, 29, (0, 0, 0))]
    ref1, ref2 = page(), page(blocks=noisy)  # the block changes between the two loads of the reference
    cand = page(blocks=noisy)                # ... and the candidate shows it too
    masked = compare([ref1, ref2], cand)
    assert masked["passed"] and masked["screens"][0]["score"] == 100.0
    assert masked["screens"][0]["noise_px"] >= 20 * 20
    # without the second load the same difference counts
    unmasked = compare([ref1], cand, pass_score=99.9)
    assert unmasked["screens"][0]["score"] < 100.0 and not unmasked["screens"][0]["passed"]


def test_a_change_outside_the_noise_is_still_counted():
    ref1, ref2 = page(), page(blocks=[(10, 10, 19, 19, (0, 0, 0))])
    cand = page(blocks=[(10, 10, 19, 19, (0, 0, 0)), (50, 50, 99, 99, (0, 0, 200))])  # 50x50 = 25 % of the first screen
    result = compare([ref1, ref2], cand)
    assert result["screens"][0]["score"] < 80 and not result["screens"][0]["passed"]


def test_colour_tolerance_is_per_channel():
    near = page(color=(240 - 20, 240, 240))   # 20/255 = 7.8 %: inside 10 %
    far = page(color=(240 - 40, 240, 240))    # 15.7 %: outside
    assert compare([page()], near)["score"] == 100.0
    assert compare([page()], far)["score"] == 0.0
    assert compare([page()], far, tolerance=0.2)["score"] == 100.0


def test_taller_page_beyond_the_tolerance_fails_the_height_and_the_extra_rows():
    result = compare([page(), page()], page(height=H + 10))
    assert result["height_delta"] == 10 and not result["height_pass"] and not result["passed"]
    assert result["screens_total"] == 3 and not result["screens"][2]["passed"]  # the 10 extra rows count as different
    assert any("altura" in f for f in parity.summarize([result])["failures"])


def test_height_within_the_tolerance_passes_and_extra_rows_are_not_scored():
    result = compare([page(), page()], page(height=H + 4))
    assert result["height_pass"] and result["passed"] and result["screens_total"] == 2
    shorter = compare([page(), page()], page(height=H - 4))
    assert shorter["height_pass"] and shorter["passed"]
    assert not compare([page()], page(height=H - 5))["height_pass"]


def test_max_screens_limits_the_check_and_is_reported():
    result = compare([page(height=500)], page(height=500), max_screens=2)
    assert result["screens_checked"] == 2 and result["screens_total"] == 5 and result["truncated"]
    assert any("2 de 5" in f for f in parity.summarize([result])["failures"])


def test_a_fully_unstable_screen_cannot_pass():
    ref1 = page(color=(0, 0, 0), height=VH)
    ref2 = page(color=(255, 255, 255), height=VH)
    result = compare([ref1, ref2], page(color=(0, 0, 0), height=VH))
    assert result["screens"][0]["score"] is None and not result["screens"][0]["passed"]


def test_diff_pictures_are_red_where_different_blue_where_noise_and_dimmed_elsewhere(tmp_path):
    ref1 = page(height=VH)
    ref2 = page(height=VH, blocks=[(0, 0, 19, 19, (0, 0, 0))])                       # noise top-left
    cand = page(height=VH, blocks=[(60, 60, 79, 79, (0, 0, 0))])                      # difference lower-right
    result = compare([ref1, ref2], cand, out_dir=tmp_path)
    img = Image.open(tmp_path / result["screens"][0]["diff_image"]).convert("RGB")
    assert img.getpixel((70, 70)) == parity.DIFF_RED
    assert img.getpixel((5, 5)) == parity.DIFF_BLUE
    dimmed = img.getpixel((90, 10))
    assert dimmed != parity.DIFF_RED and min(dimmed) > 240   # a faded version of the page
    assert (tmp_path / "diff-100.png").is_file()


def test_freeze_script_covers_clock_random_frames_transitions_and_video():
    for needle in ("Math.random", "performance.now", "requestAnimationFrame", "transition:none", "caret-color:transparent", "HTMLMediaElement"):
        assert needle in parity.FREEZE_JS
    assert "getAnimations" in parity.SETTLE_JS and "scrollTo" in parity.SETTLE_JS and "fonts.ready" in parity.SETTLE_JS


# ---------------------------------------------------------------------------------------------- service + REST + tools

PAGE_A = "<html><body><h1>Uno</h1></body></html>"
PAGE_B = "<html><body><h1>Dos</h1></body></html>"


def test_a_page_against_itself_passes_and_is_stored(services):
    run = services.visual_parity(PAGE_A, PAGE_A)
    assert run["passed"] and run["summary"]["failures"] == []
    assert [w["width"] for w in run["widths"]] == [1440, 390]
    assert all(w["passed"] and w["score"] == 100.0 for w in run["widths"])
    # reference twice, candidate once, at both widths
    calls = [c for c in services.browser.calls if "parity" in c]
    assert [(c["parity"], c["loads"]) for c in calls] == [("reference", 2), ("candidate", 1)]
    assert services.parity_get(run["id"])["passed"] is True
    assert [r["id"] for r in services.parity_list()] == [run["id"]]
    assert services.parity_file_path(run["id"], "diff-1440.png").is_file()
    assert services.parity_file_path(run["id"], "compare.html").is_file()


def test_a_changed_page_fails_with_a_list_of_what_fails(services):
    run = services.visual_parity(PAGE_A, PAGE_B, label="cambio")
    assert not run["passed"] and run["label"] == "cambio"
    assert run["summary"]["failures"] and all(not w["passed"] for w in run["widths"])
    assert run["widths"][0]["screens"][0]["diff_url"].endswith("/files/diff-1440-1.png")


def test_reference_noise_is_masked_in_the_service(services):
    services.browser.parity_noise = True
    run = services.visual_parity(PAGE_A, PAGE_A)
    assert run["passed"] and run["widths"][0]["noise_px"] > 0


def test_a_render_id_can_be_the_reference(services):
    row = services.render(html=PAGE_A, lint=False)
    run = services.visual_parity(row["id"], PAGE_A, widths=[1024])
    assert run["passed"] and run["reference"]["render_id"] == row["id"] and run["reference"]["kind"] == "render"
    with pytest.raises(LookupError):
        services.visual_parity("nope", PAGE_A)


def test_bad_arguments_and_unsafe_urls_are_refused(services):
    with pytest.raises(ValueError):
        services.visual_parity(PAGE_A, PAGE_A, widths=[50])
    with pytest.raises(ValueError):
        services.visual_parity(PAGE_A, PAGE_A, max_screens=0)
    with pytest.raises(ValueError, match="cannot be opened"):
        services.visual_parity("http://127.0.0.1:9/", PAGE_A)


def test_no_browser_is_an_error_and_leaves_nothing_behind(tmp_path):
    from conftest import make_services
    svc = make_services(tmp_path, browser_fail=True)
    with pytest.raises(ValueError, match="no browser"):
        svc.visual_parity(PAGE_A, PAGE_A)
    assert svc.parity_list() == []
    svc.stop()


def test_rest_roundtrip_and_the_side_by_side_page(client):
    created = client.post("/api/parity", json={"reference": PAGE_A, "candidate": PAGE_A, "widths": [1024, 390]})
    assert created.status_code == 201
    run = created.json()
    assert run["passed"] and run["report_url"] == f"/api/parity/{run['id']}/report"
    listed = client.get("/api/parity").json()["runs"]
    assert [r["id"] for r in listed] == [run["id"]]
    assert client.get(f"/api/parity/{run['id']}").json()["widths"][0]["image_urls"]["reference"].endswith("reference-1024.png")
    report = client.get(run["report_url"])
    assert report.status_code == 200 and "text/html" in report.headers["content-type"]
    assert "Deslizador" in report.text and 'type="range"' in report.text and run["id"] in report.text
    image = client.get(run["widths"][0]["image_urls"]["candidate"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert client.get(f"/api/parity/{run['id']}/files/run.json").status_code == 404   # only the pictures are served
    assert client.get(f"/api/parity/{run['id']}/files/../../vitruvius.db").status_code in (403, 404)
    assert client.delete(f"/api/parity/{run['id']}").json() == {"ok": True, "id": run["id"]}
    assert client.get(f"/api/parity/{run['id']}").status_code == 404
    assert client.delete(f"/api/parity/{run['id']}").status_code == 404
    assert client.get("/api/parity").json()["runs"] == []


def test_rest_validation(client):
    assert client.post("/api/parity", json={"reference": PAGE_A, "candidate": PAGE_A, "widths": [10]}).status_code in (400, 422)
    assert client.post("/api/parity", json={"reference": "nope", "candidate": PAGE_A}).status_code == 404
    assert client.get("/api/parity/zzzz").status_code == 404


def test_tools_visual_parity_get_list_delete(services):
    assert {"visual_parity", "visual_parity_get", "visual_parity_list", "visual_parity_delete"} <= {t["name"] for t in __import__("vitruvius_hoard.agent_tools", fromlist=["x"]).tool_catalog()}
    run = call_tool(services, "visual_parity", {"reference": PAGE_A, "candidate": PAGE_B, "widths": [1440]})
    assert run["passed"] is False and run["summary"]["failures"]
    assert call_tool(services, "visual_parity_get", {"id": run["id"]})["id"] == run["id"]
    assert call_tool(services, "visual_parity_list", {})["runs"][0]["id"] == run["id"]
    assert call_tool(services, "visual_parity_delete", {"id": run["id"]})["ok"] is True
    from vitruvius_hoard.hoard_link.agentkit import AppError
    with pytest.raises(AppError):
        call_tool(services, "visual_parity_get", {"id": run["id"]})


def test_report_page_escapes_labels(services):
    run = services.visual_parity(PAGE_A, PAGE_A, widths=[1024], label="<script>alert(1)</script>")
    html = services.parity_file_path(run["id"], "compare.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
