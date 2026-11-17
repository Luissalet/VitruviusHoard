"""Clone fidelity: the shared web-fidelity score for every remake round, the zones that differ on the capture, checks of the
reference's headings, links, buttons and fields, a fidelity target that keeps the loop going, and the REST route and tool."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from PIL import Image

from conftest import _fake_parity_page, make_services
from test_remake import Scripted, folder, ref
from vitruvius_hoard import fidelity, remake
from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.main import create_app

OUTLINE_REF = {"items": [{"t": "h1", "tx": "Hola  mundo", "y": 10}, {"t": "a", "tx": "Precios", "y": 40}, {"t": "button", "tx": "Comprar", "y": 900},
                         {"t": "input", "y": 950}, {"t": "a", "tx": "Precios", "y": 1000}, {"t": "div", "tx": "texto", "y": 5}]}
OUTLINE_CAND = {"items": [{"t": "h1", "tx": "hola mundo", "y": 12}, {"t": "a", "tx": "Precios", "y": 40}, {"t": "input", "y": 960}]}


def nudged(w):
    """The reference with one block changed: the parity check passes (under 2 % of pixels), the fidelity check does not."""
    image = ref(w).copy()
    r, g, b = image.getpixel((0, 0))
    image.paste(tuple(0 if v > 127 else 255 for v in (r, g, b)), (0, 0, int(w * 0.075), 72))
    return image


def test_checks_compare_headings_links_buttons_and_fields():
    found = fidelity.checks(OUTLINE_REF, OUTLINE_CAND)
    assert [(c["kind"], c["ok"]) for c in found] == [("heading", True), ("link", True), ("button", False), ("field", True), ("link", False)]
    assert found[2]["detail"] == "missing button: comprar"
    assert fidelity.checks(None, OUTLINE_CAND) == [] and all(not c["ok"] for c in fidelity.checks(OUTLINE_REF, None))


def test_screens_are_cases_with_their_own_checks_and_the_zones_are_drawn(tmp_path):
    def page(blocks, h=1700, w=400):
        img = Image.new("RGB", (w, h), (250, 250, 250))
        for x, y, bw, bh, c in blocks:
            img.paste(c, (x, y, x + bw, y + bh))
        return img
    blocks = [(20, 20, 300, 40, (20, 20, 20)), (20, 300, 200, 200, (40, 90, 200)), (20, 1000, 300, 300, (200, 40, 40))]
    page(blocks).save(tmp_path / "ref.png")
    page(blocks).save(tmp_path / "same.png")
    page(blocks[:2]).save(tmp_path / "less.png")
    same = fidelity.score_widths({400: tmp_path / "ref.png"}, {400: tmp_path / "same.png"}, {400: OUTLINE_REF}, {400: OUTLINE_REF},
                                 viewport_height=lambda w: 844, out_dir=tmp_path / "a")
    assert same["score"] == 1.0 and same["cases"] == 3 and same["functional_rate"] == 1.0 and not same["failing_screens"]
    w = same["widths"][0]
    assert [s["checks"] for s in w["screens"]] == [2, 3, 0] and (tmp_path / "a" / "zones-400.png").is_file()
    less = fidelity.score_widths({400: tmp_path / "ref.png"}, {400: tmp_path / "less.png"}, {400: OUTLINE_REF}, {400: OUTLINE_CAND},
                                 viewport_height=lambda w: 844, out_dir=tmp_path / "b")
    screens = less["widths"][0]["screens"]
    assert screens[0]["passed"] and screens[0]["score"] == 1.0 and screens[0]["checks_ok"] == 2
    assert not screens[1]["passed"] and screens[1]["checks_ok"] == 1                # a button and a link are missing in the second screen ...
    assert screens[1]["score"] < 0.99 and screens[1]["regions"] and screens[1]["regions"][0]["y"] >= 844      # ... and the red block is gone
    assert screens[2]["passed"] and less["score"] == round(2 / 3, 4) and [f["index"] for f in less["failing_screens"]] == [1]
    assert "missing button: comprar" in less["widths"][0]["missing"]
    zones = Image.open(tmp_path / "b" / "zones-400.png")
    r = screens[1]["regions"][0]
    assert zones.size == (400, 1700) and zones.getpixel((r["x"] + 1, r["y"] + 20)) == (229, 57, 53)        # outlined on the clone's picture


def test_every_round_has_its_fidelity_and_the_rest_and_tool_read_it(tmp_path):
    svc = make_services(tmp_path / "s")
    try:
        svc.browser.parity_hook = lambda tag, w, load, html, url: ref(w) if tag == "candidate" else None
        out = svc.remake.start(url="https://site.test/", wait_s=30)
        assert out["passed"] and out["fidelity"]["score"] == 1.0 and out["rounds"][0]["fidelity"]["cases"] >= 2
        assert out["rounds"][0]["fidelity_url"].endswith("/fidelity?round=0")
        full = call_tool(svc, "remake_fidelity", {"id": out["id"]})
        assert full["round"] == 0 and full["best"] and full["score"] == 1.0 and [w["width"] for w in full["widths"]] == [1440, 390]
        assert full["widths"][0]["zones_url"] == f"/api/remake/{out['id']}/fidelity/0/zones-1440.png"
        with TestClient(create_app(svc.config, svc), base_url="http://127.0.0.1") as c:
            r = c.get(f"/api/remake/{out['id']}/fidelity")
            assert r.status_code == 200 and r.json()["score"] == 1.0
            pic = c.get(full["widths"][1]["zones_url"])
            assert pic.status_code == 200 and pic.content[:4] == b"\x89PNG"
            assert c.get(f"/api/remake/{out['id']}/fidelity/0/..%2Fproject.json").status_code == 404
            assert c.get(f"/api/remake/{out['id']}/fidelity?round=7").status_code == 404
        # a round scored before fidelity existed is scored on demand from its stored pictures
        (folder(svc, out["id"]) / "rounds" / "0" / "fidelity.json").unlink()
        again = svc.remake.fidelity(out["id"], 0)
        assert again["score"] == 1.0 and (folder(svc, out["id"]) / "rounds" / "0" / "fidelity.json").is_file()
    finally:
        svc.stop()


def test_a_fidelity_target_keeps_repairing_after_parity_passes(tmp_path):
    def hook(tag, w, load, html, url):
        if tag != "candidate":
            return None
        return ref(w) if "margin-top:0" in html else nudged(w)

    plain = make_services(tmp_path / "a")
    try:
        plain.browser.parity_hook = hook
        out = plain.remake.start(url="https://site.test/", wait_s=30)
        assert out["passed"] and len(out["rounds"]) == 1 and out["fidelity"]["score"] < 1.0      # parity passes: without a target it stops here
    finally:
        plain.stop()
    link = Scripted(["```css\nh1{margin-top:0!important}\n```"])
    svc = make_services(tmp_path / "b", link=link)
    try:
        svc.browser.parity_hook = hook
        out = svc.remake.start(url="https://site.test/", wait_s=30, fidelity_target=1.0)
        assert [r["kind"] for r in out["rounds"]] == ["copy", "model"] and out["rounds"][1]["kept"]
        assert out["fidelity"]["score"] == 1.0 and out["fidelity_target"] == 1.0 and "objetivo" in (out.get("stop_reason") or "")
        assert "SCREEN 1 at 1440 px" in link.chat_calls[0][0][1]["content"]       # the screen that failed fidelity was the focus
        saved = json.loads((folder(svc, out["id"]) / "project.json").read_text(encoding="utf-8"))
        assert saved["fidelity_target"] == 1.0
        try:
            svc.remake.start(url="https://site.test/", fidelity_target=0.2)
            raise AssertionError("a target under 0.5 must be refused")
        except ValueError as error:
            assert "fidelity_target" in str(error)
    finally:
        svc.stop()


def test_remake_report_widths_without_pictures_are_skipped(tmp_path):
    _fake_parity_page(390, "reference", 1, False).save(tmp_path / "r.png")
    out = fidelity.score_widths({390: tmp_path / "r.png", 1440: tmp_path / "missing.png"}, {390: tmp_path / "r.png"}, {}, {},
                                viewport_height=lambda w: 844)
    assert [w["width"] for w in out["widths"]] == [390] and out["score"] == 1.0 and out["functional_rate"] is None
    assert remake._fidelity_target(None) is None and remake._fidelity_target(0.9) == 0.9
