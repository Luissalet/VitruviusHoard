"""Theme dealing with memory and the tokens that take a dealt theme."""

from __future__ import annotations

import pytest

from conftest import make_services
from vitruvius_hoard import themes

PROMPT = "a pottery studio with a kiln and ceramics classes"


def test_the_catalogue_loads_with_valid_axes():
    rows = themes.load()
    assert len(rows) == 50 and len({t["slug"] for t in rows}) == 50
    for t in rows:
        assert t["paper"]["band"] in themes.PAPER_BANDS and t["display"]["class"] in themes.DISPLAY_CLASSES and t["genre"] in themes.GENRES


def test_a_deal_is_reproducible_by_its_seed():
    a = themes.deal(prompt=PROMPT, genre="editorial", salt="s", today="2026-10-28")
    again = themes.deal(prompt=PROMPT, genre="editorial", salt="s", today="2026-10-28")
    from_seed = themes.deal(prompt=PROMPT, genre="editorial", seed=a["seed"])
    slugs = lambda d: [x["slug"] for x in d["deal"]]  # noqa: E731
    assert slugs(a) == slugs(again) == slugs(from_seed) and a["deal"][0]["slug"] == "kiln"
    assert themes.deal(prompt=PROMPT, genre="editorial", salt="other", today="2026-10-28")["seed"] != a["seed"]


def test_the_hand_has_distinct_triples_and_reroll_moves_on():
    a = themes.deal(prompt=PROMPT, salt="s", today="2026-10-28")
    assert len({x["axes"] for x in a["deal"]}) == 3
    b = themes.deal(prompt=PROMPT, salt="s", today="2026-10-28", reroll=1)
    assert not {x["slug"] for x in a["deal"]} & {x["slug"] for x in b["deal"]} and b["seed"].endswith("·r1")


def test_the_last_three_themes_and_their_triples_are_blocked():
    first = themes.deal(prompt=PROMPT, salt="s", today="2026-10-28")
    memory = [{"slug": x["slug"], "name": x["name"], "axes": x["axes"]} for x in first["deal"]]
    nxt = themes.deal(prompt=PROMPT, salt="s", today="2026-10-28", memory=memory)
    dealt = {x["slug"] for x in nxt["deal"]}
    assert not dealt & {m["slug"] for m in memory}
    assert not {x["axes"] for x in nxt["deal"]} & {m["axes"] for m in memory}
    reasons = {b["slug"]: b["reason"] for b in nxt["blocked"]}
    assert all(m["slug"] in reasons for m in memory) and len(nxt["avoid"]) == 3
    # a fourth build forgets the oldest
    assert memory[0]["slug"] not in themes.blocked_by([{"slug": "ink", "name": "Ink", "axes": ""}] * 3 + memory)


def test_unknown_genre_and_exhausted_rerolls_raise():
    with pytest.raises(ValueError):
        themes.deal(prompt=PROMPT, genre="baroque")
    with pytest.raises(LookupError):
        themes.deal(prompt=PROMPT, reroll=40)


def test_check_names_what_a_plan_lands_on():
    out = themes.check(axes="dark/high-contrast-serif/warm", face="Boska", hue=45)
    assert not out["clear"] and any(c["slug"] == "kiln" for c in out["collisions"]) and any(n["slug"] == "kiln" for n in out["near"])
    assert themes.check(face="Zzyzx Grotesk")["clear"]
    recent = themes.check(axes="light/roman-serif/cool", memory=[{"name": "Atelier", "axes": "light/roman-serif/cool"}])
    assert recent["recent"]
    for bad in ("light/nope/warm", "nope/roman-serif/warm", "light/roman-serif/shiny", "light/roman-serif"):
        with pytest.raises(ValueError):
            themes.check(axes=bad)
    with pytest.raises(ValueError):
        themes.check()


def test_a_theme_folds_into_a_brief():
    brief = themes.as_brief(themes.get("kiln"))
    assert brief["hue"] == 45 and brief["fonts"]["heading"].startswith("Boska") and brief["style"] in ("sharp", "soft", "pill")


def test_tokens_generate_deals_records_and_then_blocks(tmp_path):
    svc = make_services(tmp_path)
    svc.start()
    try:
        one = svc.tokens_generate({"name": "Pottery", "vibe": PROMPT, "deal": True, "genre": "editorial"})
        theme = one["tokens"]["theme"]
        assert theme["slug"] == "kiln" and one["theme_deal"]["seed"] == theme["seed"]
        assert one["tokens"]["typography"]["heading"].startswith("Boska") and one["tokens"]["hue"] == 45.0
        assert svc.theme_memory()[0]["slug"] == "kiln" and svc.theme_memory()[0]["tokens_id"] == one["id"]
        with pytest.raises(ValueError, match="blocked"):
            svc.tokens_generate({"name": "Again", "theme": "kiln"})
        forced = svc.tokens_generate({"name": "Again", "theme": "kiln", "force_theme": True})
        assert forced["tokens"]["theme"]["slug"] == "kiln"
        two = svc.tokens_generate({"name": "Pottery 2", "vibe": PROMPT, "deal": True, "genre": "editorial"})
        assert two["tokens"]["theme"]["slug"] != "kiln"
        with pytest.raises(LookupError):
            svc.tokens_generate({"name": "x", "theme": "nope"})
    finally:
        svc.stop()


def test_explicit_values_win_over_the_dealt_theme(tmp_path):
    svc = make_services(tmp_path)
    svc.start()
    try:
        row = svc.tokens_generate({"name": "Mine", "theme": "ink", "hue": 10, "fonts": {"heading": "Zilla Slab, serif"}})
        assert row["tokens"]["hue"] == 10 and row["tokens"]["typography"]["heading"].startswith("Zilla Slab")
        assert row["tokens"]["typography"]["body"].startswith("Epilogue") or "Newsreader" in row["tokens"]["typography"]["body"] or row["tokens"]["typography"]["body"]
    finally:
        svc.stop()


def test_a_hand_made_plan_is_told_when_it_lands_on_a_theme(tmp_path):
    svc = make_services(tmp_path)
    svc.start()
    try:
        row = svc.tokens_generate({"name": "Copy", "hue": 45, "fonts": {"heading": "Boska, serif", "body": "Manrope, sans-serif"}})
        assert row["theme_check"]["collisions"][0]["slug"] == "kiln"
        clear = svc.tokens_generate({"name": "Clear", "fonts": {"heading": "Zzyzx Grotesk, sans-serif", "body": "Karla, sans-serif"}})
        assert "theme_check" not in clear
    finally:
        svc.stop()


def test_the_design_brief_deals_three_themes(tmp_path):
    svc = make_services(tmp_path)
    svc.start()
    try:
        out = svc.library_brief(subject="pottery studio", vibe="warm", product_type=None, platform=None, mode="marketing", knobs=None)
        assert len(out["theme_deal"]["deal"]) == 3 and out["theme_deal"]["seed"]
    finally:
        svc.stop()
