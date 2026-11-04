"""Logo (mark) audit: scores, checks, the test sheet, REST and the agent tools."""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageDraw

from vitruvius_hoard import agent_tools, mark_audit


def _png(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def circle(colour=(20, 60, 200, 255), size=512) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((96, 96, size - 96, size - 96), fill=colour)
    return img


def colour_only() -> Image.Image:
    """Four touching squares that differ only by colour: in one colour they melt into one block."""
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, c in enumerate([(220, 30, 30), (30, 160, 60), (30, 60, 220), (240, 200, 20)]):
        x, y = 96 + (i % 2) * 160, 96 + (i // 2) * 160
        d.rectangle((x, y, x + 159, y + 159), fill=c + (255,))
    return img


def hairlines() -> Image.Image:
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for x in range(96, 416, 24):
        d.line((x, 96, x, 416), fill=(0, 0, 0, 255), width=2)
    return img


def by_id(report):
    return {c["id"]: c for c in report["checks"]}


def test_solid_circle_is_ready(tmp_path):
    r = mark_audit.audit(tmp_path, data=_png(circle()))
    checks = by_id(r)
    assert r["verdict"] == "lista" and r["score"] >= 85
    assert checks["one_colour"]["status"] == "pass"
    assert checks["small_32"]["status"] == "pass" and checks["small_16"]["status"] == "pass"
    assert checks["background"]["status"] == "pass" and checks["aspect"]["status"] == "pass"
    assert (tmp_path / "marks" / r["id"] / "sheet.png").is_file()


def test_colour_only_mark_fails_one_colour(tmp_path):
    r = mark_audit.audit(tmp_path, data=_png(colour_only()))
    assert by_id(r)["one_colour"]["status"] in ("fail", "warn")
    assert by_id(r)["colours"]["value"] == 4


def test_hairlines_break_at_small_sizes(tmp_path):
    r = mark_audit.audit(tmp_path, data=_png(hairlines()))
    assert by_id(r)["small_32"]["status"] in ("fail", "warn")
    assert by_id(r)["small_16"]["status"] in ("warn", "note")


def test_flat_ground_is_removed_and_contrast_noted(tmp_path):
    img = Image.new("RGB", (400, 300), (255, 255, 255))
    ImageDraw.Draw(img).ellipse((120, 70, 280, 230), fill=(250, 240, 120))
    path = tmp_path / "pale.jpg"
    img.save(path, quality=95)
    r = mark_audit.audit(tmp_path, path=str(path))
    assert r["metrics"]["background"] == "removed"
    assert by_id(r)["background"]["status"] == "note"
    assert by_id(r)["contrast"]["status"] == "note"          # pale yellow needs a dark version on light grounds


def test_bad_sources(tmp_path):
    import pytest
    with pytest.raises(mark_audit.MarkError):
        mark_audit.audit(tmp_path)
    with pytest.raises(mark_audit.MarkError):
        mark_audit.audit(tmp_path, data=_png(Image.new("RGBA", (64, 64), (0, 0, 0, 0))))
    with pytest.raises(mark_audit.MarkError):
        mark_audit.audit(tmp_path, data=base64.b64encode(b"not an image").decode())
    with pytest.raises(mark_audit.MarkError):
        mark_audit.audit(tmp_path, svg="<svg xmlns='http://www.w3.org/2000/svg'/>")   # no browser given


def test_rest_audit_sheet_and_history(client):
    r = client.post("/api/marks/audit", json={"data": "data:image/png;base64," + _png(circle()), "name": "círculo"})
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["name"] == "círculo" and report["sheet_url"] == f"/api/marks/{report['id']}/sheet.png"
    pic = client.get(report["sheet_url"])
    assert pic.status_code == 200 and pic.headers["content-type"] == "image/png"
    wide = Image.open(io.BytesIO(pic.content)).width
    assert [row["id"] for row in client.get("/api/marks").json()["reports"]] == [report["id"]]
    again = client.post("/api/marks/sheet", json={"id": report["id"], "backgrounds": ["#ff0066", "0a2540", "#00aa55"]})
    assert again.status_code == 200 and again.json()["backgrounds"] == ["#ff0066", "0a2540", "#00aa55"]
    assert Image.open(io.BytesIO(client.get(report["sheet_url"]).content)).width > wide      # three more grounds: the first row outgrows the sizes row
    assert client.get(f"/api/marks/{report['id']}").json()["backgrounds"] == ["#ff0066", "0a2540", "#00aa55"]
    assert client.post("/api/marks/sheet", json={"id": report["id"], "backgrounds": ["red"]}).status_code in (400, 422)
    assert client.post("/api/marks/audit", json={}).status_code == 400
    assert client.get("/api/marks/000000000000").status_code == 404
    assert client.get(f"/api/marks/{report['id']}/other.png").status_code == 404


def test_agent_tools(services):
    names = {t["name"] for t in agent_tools.tool_catalog()}
    assert {"mark_audit", "mark_test_sheet", "mark_reports"} <= names
    out = agent_tools.call_tool(services, "mark_audit", {"data": _png(circle())})
    assert out["verdict"] == "lista" and out["sheet_path"].endswith("sheet.png")
    listed = agent_tools.call_tool(services, "mark_reports", {})
    assert listed["reports"][0]["id"] == out["id"]
    sheet = agent_tools.call_tool(services, "mark_test_sheet", {"data": _png(colour_only()), "backgrounds": ["#222244"]})
    assert sheet["id"] != out["id"] and sheet["backgrounds"] == ["#222244"]


def test_gradient_is_one_colour_family(tmp_path):
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for x in range(96, 416):
        t = (x - 96) / 320
        d.line((x, 96, x, 416), fill=(int(40 + 60 * t), int(50 + 90 * t), int(150 + 100 * t), 255))
    r = mark_audit.audit(tmp_path, data=_png(img))
    colours = by_id(r)["colours"]
    assert colours["value"] == 1 and colours["status"] == "note" and "degradado" in colours["detail"]


def test_catalog_lists_the_mark_tools():
    import json
    from pathlib import Path
    rows = json.loads((Path(mark_audit.__file__).parent / "software" / "catalog.json").read_text(encoding="utf8"))
    native = {t["name"]: t for t in agent_tools.tool_catalog()}
    for name in ("mark_audit", "mark_test_sheet", "mark_reports"):
        row = next(r for r in rows if r["name"] == name)
        assert row["module"] == "design" and row["inputSchema"] == native[name]["inputSchema"]


def test_a_failed_audit_leaves_no_folder_behind(tmp_path):
    """Empty, unreadable and missing sources are user errors: they must not pile up empty report folders."""
    import pytest

    blank = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    for kwargs in ({"data": _png(blank)}, {"data": base64.b64encode(b"not an image").decode("ascii")},
                   {"path": str(tmp_path / "missing.png")}):
        with pytest.raises(mark_audit.MarkError):
            mark_audit.audit(tmp_path, **kwargs)
    assert not list(mark_audit._marks_dir(tmp_path).iterdir())
    ok = mark_audit.audit(tmp_path, data=_png(circle()))
    assert [p.name for p in mark_audit._marks_dir(tmp_path).iterdir()] == [ok["id"]]
