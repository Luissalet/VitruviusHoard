"""Design galleries as references (catalogue, search by word or area, fragments, sample capture, brief citations) and the Flexoki preset."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_services
from vitruvius_hoard import design_galleries as G
from vitruvius_hoard import presets
from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.tokens import contrast_ratio

EIGHT = {"scrolltide", "scrollshaders", "footer-design", "cta-gallery", "refero-styles", "supahero", "3dicons", "glass-ui"}

PAGE = """<!doctype html><html><head><title>Footers</title><style>.card{backdrop-filter: blur(12px)} .bar{position: sticky}</style></head>
<body><header><nav><a href="/">Home</a><a href="/browse">Browse</a></nav></header>
<main><h1>The only footer gallery</h1><p>Hundreds of real website footers, sorted by layout and style for designers.</p>
<a class="btn btn-primary" href="/join">Get started</a><button>Subscribe</button><h2>Latest</h2><script>var x = "<h1>no</h1>";</script></main>
<footer><a href="/about">About</a><a href="/privacy">Privacy</a><a href="/terms">Terms</a><p>© 2026 Footer</p><svg><path d="M0 0"/></svg></footer>
</body></html>"""


def test_the_eight_galleries_are_first_class():
    rows = {g["id"]: g for g in G.load()}
    assert EIGHT <= set(rows)
    for gid in EIGHT:
        g = rows[gid]
        assert g["curated"] and g["url"].startswith("http") and g["sample_url"].startswith("http")
        assert g["provides"] and g["provides_es"] and g["when"] and g["when_es"] and g["license"] and g["keywords"]
        assert g["areas"] and set(g["areas"]) <= set(G.AREAS)
        assert g["cite"] == f"[vitruvius: gallery/{gid}]"
    assert [g["id"] for g in G.load()][:8] == [g["id"] for g in G.load() if g["curated"]]
    assert rows["godly"]["curated"] is False  # the older galleries stay listed


@pytest.mark.parametrize("query,first", [
    ("referencias de footers", "footer-design"), ("pie de página", "footer-design"), ("ejemplos de CTA", "cta-gallery"),
    ("llamada a la acción", "cta-gallery"), ("call to action buttons", "cta-gallery"), ("heroes", "supahero"),
    ("iconos 3D", "3dicons"), ("glassmorphism", "glass-ui"), ("cristal esmerilado", "glass-ui"), ("webgl shaders", "scrollshaders"),
    ("scrollytelling", "scrolltide"), ("DESIGN.md estilos de producto", "refero-styles"),
])
def test_search_by_word_in_either_language(query, first):
    assert G.search(query=query, samples=False)[0]["id"] == first


def test_search_by_area_and_no_match():
    motion = {g["id"] for g in G.search(area="motion", samples=False)}
    assert {"scrolltide", "scrollshaders"} <= motion and "footer-design" not in motion
    assert {g["id"] for g in G.search(area="iconography", samples=False)} == {"3dicons"}
    assert G.search(query="zzzz", samples=False) == []
    assert len(G.search(query="referencias de", samples=False, limit=50)) == len(G.load())  # filler words list everything
    assert G.search(query="referencias de", samples=False, require_match=True) == []


def test_fragments_of_a_page():
    f = G.extract_fragments(PAGE)
    assert f["hero"]["headline"] == "The only footer gallery" and f["hero"]["lede"].startswith("Hundreds")
    assert [h["text"] for h in f["headings"]] == ["The only footer gallery", "Latest"]
    assert "Get started" in f["ctas"] and "Subscribe" in f["ctas"]
    assert f["nav_links"] == ["Home", "Browse"]
    assert f["footer"]["links"] == ["About", "Privacy", "Terms"] and "© 2026" in f["footer"]["text"]
    assert f["footer"]["html"].startswith("<footer") and "<path" not in f["footer"]["html"]
    assert f["signals"]["backdrop_filter"] == 1 and f["signals"]["sticky"] == 1
    assert G.extract_fragments("<div><p>unclosed")["headings"] == []


def test_ingest_stores_capture_and_fragments_and_replaces_the_old_sample(tmp_path):
    svc = make_services(tmp_path, probe_overrides={"html_text": PAGE, "css_text": ""})
    try:
        out = call_tool(svc, "design_gallery_ingest", {"ids": ["footer-design"]})
        r = out["results"][0]
        assert out["ok"] == 1 and r["ok"] and r["fragments"]["footer_links"] == 3 and r["cite"].startswith("[vitruvius: gallery/footer-design § ")
        ref = svc.reference_get(r["reference_id"])
        assert "gallery:footer-design" in ref["tags"] and "footer" in ref["tags"] and Path(ref["files"]["desktop"]).is_file()
        assert ref["analysis"]["gallery"]["id"] == "footer-design" and ref["analysis"]["fragments"]["ctas"]
        assert any(x["id"] == ref["id"] for x in svc.reference_search(query="footer"))
        found = call_tool(svc, "design_galleries", {"query": "referencias de footers"})["galleries"][0]
        assert found["id"] == "footer-design" and found["samples"][0]["id"] == ref["id"]
        again = svc.galleries_ingest(["footer-design"])["results"][0]
        assert again["replaced"] == [ref["id"]] and svc.reference_get(ref["id"]) is None
        assert not (svc.config.references_dir / ref["id"]).exists()
        assert len(G.sample_rows(svc.db, "footer-design")) == 1
        brief = svc.library_brief(subject="footer for a bakery site")
        assert brief["galleries"][0]["id"] == "footer-design" and "[vitruvius: gallery/footer-design]" in brief["cites"]
        with pytest.raises(Exception):
            svc.galleries_ingest(["nope"])
    finally:
        svc.stop()


def test_failed_capture_leaves_nothing(tmp_path):
    svc = make_services(tmp_path, browser_fail=True)
    try:
        r = svc.galleries_ingest(["cta-gallery"])["results"][0]
        assert r["ok"] is False and r["error"]
        assert G.sample_rows(svc.db, "cta-gallery") == [] and svc.reference_search() == []
    finally:
        svc.stop()


def test_galleries_rest(client):
    rows = client.get("/api/galleries", params={"q": "ejemplos de CTA"}).json()["galleries"]
    assert rows[0]["id"] == "cta-gallery" and rows[0]["samples"] == []
    assert {g["id"] for g in client.get("/api/galleries", params={"area": "effects"}).json()["galleries"]} >= {"glass-ui", "scrollshaders"}
    assert client.post("/api/galleries/ingest", json={"ids": ["nope"]}).status_code == 404


# ---------------------------------------------------------------- Flexoki

OFFICIAL = {  # stephango.com/flexoki: 400 / 600 of every accent
    "red": ("#d14d41", "#af3029"), "orange": ("#da702c", "#bc5215"), "yellow": ("#d0a215", "#ad8301"), "green": ("#879a39", "#66800b"),
    "cyan": ("#3aa99f", "#24837b"), "blue": ("#4385be", "#205ea6"), "purple": ("#8b7ec8", "#5e409d"), "magenta": ("#ce5d97", "#a02f6f"),
}
BASE = {"paper": "#fffcf0", "50": "#f2f0e5", "100": "#e6e4d9", "150": "#dad8ce", "200": "#cecdc3", "300": "#b7b5ac", "400": "#9f9d96",
        "500": "#878580", "600": "#6f6e69", "700": "#575653", "800": "#403e3c", "850": "#343331", "900": "#282726", "950": "#1c1b1a", "black": "#100f0f"}


def test_flexoki_palette_is_exact_and_licensed():
    p = presets.get("flexoki")
    assert p["source"] == "flexoki" and p["license"]["name"] == "MIT" and "stephango.com/flexoki" in p["license"]["url"]
    assert p["palette"]["base"] == BASE
    for hue, (c400, c600) in OFFICIAL.items():
        assert p["palette"][hue]["400"] == c400 and p["palette"][hue]["600"] == c600
    light, dark = p["tokens"]["colors"]["light"], p["tokens"]["colors"]["dark"]
    assert (light["background"], light["foreground"], light["muted"], light["secondary"]) == ("#fffcf0", "#100f0f", "#f2f0e5", "#e6e4d9")
    assert (dark["background"], dark["foreground"], dark["muted"], dark["secondary"]) == ("#100f0f", "#cecdc3", "#1c1b1a", "#282726")
    assert (light["primary"], dark["primary"], light["destructive"]) == ("#205ea6", "#4385be", "#af3029")
    assert p["flexoki_theme"]["light"]["tx-2"] == "#6f6e69" and p["flexoki_theme"]["dark"]["ui"] == "#282726"
    assert {r["name"] for r in presets.listing(source="flexoki")} == {"flexoki", *(f"flexoki-{h}" for h in OFFICIAL if h != "blue")}


def test_every_flexoki_text_pair_passes_aa():
    for row in presets.listing(source="flexoki"):
        p = presets.get(row["name"])
        assert p["aa"] and row["aa"], p["name"]
        for pair in p["contrast_pairs"]:
            assert contrast_ratio(pair["fg"], pair["bg"]) >= 4.5 and pair["level"] in ("AA", "AAA"), (p["name"], pair)
        accent = p["accent"]
        assert p["tokens"]["colors"]["light"]["primary"] in (p["palette"][accent]["600"], p["palette"][accent]["700"])
        assert p["tokens"]["colors"]["dark"]["primary"] in (p["palette"][accent]["400"], p["palette"][accent]["300"], p["palette"][accent]["500"])


def test_tokens_generate_from_the_flexoki_preset(tmp_path):
    svc = make_services(tmp_path)
    try:
        row = call_tool(svc, "tokens_generate", {"name": "Notes", "preset": "flexoki"})
        t = row["tokens"]
        assert row["name"] == "Notes" and t["preset"]["name"] == "flexoki" and t["preset"]["license"]["name"] == "MIT"
        assert t["color"]["neutral"]["50"] == "#f2f0e5" and t["color"]["primary"]["600"] == "#205ea6"
        assert t["color"]["semantic"]["danger"]["600"] == "#af3029" and t["color"]["semantic"]["success"]["400"] == "#879a39"
        assert t["color"]["surfaces"]["light"]["bg"] == "#fffcf0" and t["color"]["surfaces"]["dark"]["bg"] == "#100f0f"
        assert "--palette-red-400: #d14d41;" in row["css"] and "--color-bg: #fffcf0;" in row["css"]
        warn = presets.get("flexoki")["states"]["light"]["warning"]["text"]
        assert f"--color-warning-text: {warn};" in row["css"] and warn == "#664d01"  # yellow-800: 700 drops under AA on bg-2
        assert all(c["level"] != "fail" for c in row["contrast_pairs"])
        total = len(presets.get("flexoki")["contrast_pairs"])
        assert row["contrast"]["aa"] == row["contrast"]["pairs"] == total and row["contrast"]["lowest"]["ratio"] >= 4.5
        for mode in ("light", "dark"):
            roles = row["roles"][mode]
            assert contrast_ratio(roles["text"], roles["background"]) >= 4.5 and contrast_ratio(roles["muted"], roles["background"]) >= 4.5
        orange = call_tool(svc, "design_preset_apply", {"preset": "flexoki-orange", "tokens_id": row["id"], "parts": ["colors"]})
        assert svc.tokens_get(orange["tokens_id"])["tokens"]["color"]["primary"]["400"] == "#da702c"
    finally:
        svc.stop()


def test_flexoki_rest(client):
    listed = client.get("/api/presets", params={"source": "flexoki"}).json()
    assert listed["count"] == 8 and listed["presets"][0]["license"]["holder"].startswith("Steph Ango")
    item = client.get("/api/design/registry/flexoki.json").json()
    assert item["meta"]["hex"]["light"]["background"] == "#fffcf0" and item["meta"]["license"]["name"] == "MIT"
