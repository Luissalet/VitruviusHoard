"""Floor / Reflex / Finish tiers, validated waivers, the tier gate and the clean-context review."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import FakeLink, default_probe, make_services
from vitruvius_hoard import critique as critique_mod, review as review_mod, waivers as waivers_mod
from vitruvius_hoard.lint import ensure_rules, run_lint

AI = (Path(__file__).parent / "fixtures" / "pages" / "generic_ai.html").read_text(encoding="utf-8")
REASON = "The gradient is the brand mark the client supplied, used once."
REASON2 = "A mono face carries the build numbers shown in this footer."


@pytest.fixture(autouse=True)
def _rules():
    ensure_rules()


def findings():
    return run_lint(default_probe(), AI)["findings"]


def test_findings_carry_their_tier():
    by = {f["check_id"]: f["tier"] for f in findings()}
    assert by["slop/gradient-text"] == "reflex" and by["slop/bounce-easing"] == "finish" and by["craft/hero-vh"] == "floor"


def test_waiver_needs_a_real_reason():
    out = waivers_mod.validate([{"rule": "slop/gradient-text", "reason": "on purpose"}], findings())
    assert not out["accepted"] and "at least 24" in out["rejected"][0]["why"]
    out = waivers_mod.validate([{"rule": "slop/gradient-text", "reason": REASON}], findings())
    assert out["accepted"] == [{"rule": "slop/gradient-text", "reason": REASON}]


def test_floor_rules_are_never_waived_and_finish_needs_none():
    out = waivers_mod.validate([{"rule": "craft/hero-vh", "reason": REASON}, {"rule": "slop/bounce-easing", "reason": REASON2}], findings())
    assert not out["accepted"]
    assert "never waived" in out["rejected"][0]["why"] and "nothing to waive" in out["rejected"][1]["why"]


def test_a_reason_cannot_be_reused_for_another_rule():
    out = waivers_mod.validate([{"rule": "slop/gradient-text", "reason": REASON}, {"rule": "slop/mono-costume", "reason": REASON.upper()}], findings())
    assert len(out["accepted"]) == 1 and "already given" in out["rejected"][0]["why"]
    prior = {"slop/gradient-text": REASON}
    out = waivers_mod.validate([{"rule": "slop/mono-costume", "reason": REASON}], findings(), prior)
    assert not out["accepted"]
    out = waivers_mod.validate([{"rule": "slop/gradient-text", "reason": REASON}], findings(), prior)  # the same rule again is fine
    assert out["accepted"]


def test_a_waiver_for_a_rule_that_did_not_fire_or_does_not_exist_is_refused():
    out = waivers_mod.validate({"slop/side-tab": REASON, "slop/nope": REASON2}, findings())
    assert not out["accepted"] and len(out["rejected"]) == 2


def test_a_reason_that_restates_the_rule_is_refused():
    from vitruvius_hoard.rules.registry import get_rule
    f = findings()
    out = waivers_mod.validate([{"rule": "slop/gradient-text", "reason": get_rule("slop/gradient-text").description}], f)
    assert not out["accepted"] and "restates" in out["rejected"][0]["why"]


def test_waivers_apply_to_reflex_and_the_gate_counts_them():
    f = findings()
    ok = waivers_mod.validate([{"rule": "slop/gradient-text", "reason": REASON}], f)["accepted"]
    waivers_mod.apply(f, ok)
    waived = [x for x in f if x.get("waived")]
    assert [x["check_id"] for x in waived] == ["slop/gradient-text"] and waived[0]["waiver_reason"] == REASON
    gate = waivers_mod.gate(f)
    assert gate["state"] == "fix" and gate["floor"] >= 1 and gate["reflex_waived"] == 1 and "craft/hero-vh" in gate["blocking"]


def test_gate_passes_with_only_finish_and_waived_findings():
    f = [{"check_id": "a", "tier": "finish"}, {"check_id": "b", "tier": "reflex", "waived": True}]
    assert waivers_mod.gate(f)["state"] == "pass"
    assert waivers_mod.gate([{"check_id": "c", "tier": "reflex"}])["state"] == "fix"


def test_a_waived_finding_is_out_of_the_score_sum():
    f = findings()
    before = critique_mod.score_of(f)
    waivers_mod.apply(f, [{"rule": "slop/gradient-text", "reason": REASON}])
    assert critique_mod.score_of(f) >= before


def test_critique_applies_waivers_and_reports_the_gate():
    out = critique_mod.critique(probe=default_probe(), html=AI, use_vision=False, waivers=[{"rule": "slop/gradient-text", "reason": REASON}])
    assert out["waivers"]["accepted"] and out["gate"]["reflex_waived"] == 1 and out["ship_ready"] is False
    clean = critique_mod.critique(probe=default_probe(), html="<html lang='en'><head><title>t</title><meta name='description' content='d'></head><body><p>ok</p></body></html>", use_vision=False)
    assert clean["gate"]["state"] in ("pass", "fix") and "review" in clean


# ---------------------------------------------------------------- clean-context review

def test_review_parses_the_verdict_from_the_first_word():
    out = review_mod.parse("Rebuild\n- hierarchy: no focal point -> make the headline the largest thing\n- copy: filler -> say what it does")
    assert out["verdict"] == "rebuild" and len(out["findings"]) == 2 and out["verdict_parsed"]
    assert review_mod.parse("ship")["verdict"] == "ship"
    assert review_mod.parse("**Recapture**: blank")["verdict"] == "recapture"
    unparsed = review_mod.parse("Looks mostly fine but the hero needs work")
    assert unparsed["verdict"] == "fix" and not unparsed["verdict_parsed"]


def test_review_keeps_at_most_eight_findings():
    text = "fix\n" + "\n".join(f"- a{n}: x -> y" for n in range(12))
    assert len(review_mod.parse(text)["findings"]) == 8


def test_review_is_a_fresh_call_with_only_screenshots_html_and_findings():
    link = FakeLink(chat_text="fix\n- type: flat -> add a scale")
    out = review_mod.run(link, images=[b"png1", b"png2"], html="<h1>Hi</h1>", findings=[{"check_id": "slop/gradient-text", "tier": "reflex", "title": "Gradient text", "detail": "d"}])
    assert out["verdict"] == "fix" and out["images"] == 2
    messages, images = link.chat_calls[0]
    assert [m["role"] for m in messages] == ["system", "user"] and images == [b"png1", b"png2"]
    body = messages[1]["content"]
    assert "<h1>Hi</h1>" in body and "slop/gradient-text" in body
    assert "recapture" in messages[0]["content"] and "conversation" not in body.lower()


def test_review_without_images_asks_for_a_recapture_and_without_a_link_says_so():
    assert review_mod.run(FakeLink(), images=[], html="", findings=[])["verdict"] == "recapture"
    assert review_mod.run(None, images=[b"x"], html="", findings=[])["verdict"] is None


def test_a_recapture_or_rebuild_verdict_blocks_a_page_that_otherwise_passes():
    link = FakeLink(chat_text="rebuild\n- concept: no idea -> start over")
    html = "<html lang='en'><head><title>t</title><meta name='description' content='d'><style>main{max-width:60ch}</style></head><body><main><p>ok</p></main></body></html>"
    out = critique_mod.critique(probe=default_probe(), html=html, images=[b"png"], link=link, use_vision=False, clean_review=True)
    assert out["review"]["verdict"] == "rebuild" and out["gate"]["state"] == "fix" and "review:rebuild" in out["gate"]["blocking"]


def test_the_vision_prompt_lists_the_judged_rules_and_a_cited_one_becomes_a_registry_finding():
    assert "visual/ai-template" in critique_mod.vision_prompt()
    reply = json.dumps({"score": 6, "summary": "s", "findings": [{"rule": "visual/ai-template", "detail": "hero, three cards, cta, footer", "fix": "change the shape"},
                                                               {"area": "copy", "severity": "warn", "title": "Vague", "detail": "d", "fix": "f"}]})
    out = critique_mod.critique(probe=default_probe(), html="<p>x</p>", images=[b"png"], link=FakeLink(chat_text=reply))
    cited = next(f for f in out["findings"] if f["check_id"] == "visual/ai-template")
    assert cited["engine"] == "visual" and cited["tier"] == "reflex"
    free = next(f for f in out["findings"] if f["title"] == "Vague")
    assert free["tier"] == "finish" and free["judged"]


def test_service_persists_waivers_and_enforces_non_repetition_per_render(tmp_path):
    svc = make_services(tmp_path)
    svc.start()
    try:
        row = svc.render(html=AI)
        out = svc.critique_render(row["id"], use_vision=False, waivers=[{"rule": "slop/gradient-text", "reason": REASON}])
        assert out["waivers"]["accepted"]
        again = svc.critique_render(row["id"], use_vision=False, waivers=[{"rule": "slop/mono-costume", "reason": REASON}])
        assert again["waivers"]["rejected"] and "already given" in again["waivers"]["rejected"][0]["why"]
        assert [f for f in again["findings"] if f["check_id"] == "slop/gradient-text"][0].get("waived") is None  # not re-sent: not waived this time
        review = svc.critique_render(row["id"], use_vision=False, clean_review=True)
        assert review["review"]["verdict"] in review_mod.VERDICTS
        assert svc.db.one("SELECT COUNT(*) AS n FROM reviews")["n"] == 1
    finally:
        svc.stop()
