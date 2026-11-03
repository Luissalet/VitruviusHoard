"""Spanish (Spain) texts for the rule catalogue, the slop audit and the direction brief, and the lang plumbing."""

from __future__ import annotations

import re
from pathlib import Path

from conftest import FakeLink, default_probe, make_services
from vitruvius_hoard import i18n, i18n_es, lint, slop_audit
from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.rules import registry

SLOPPY = (Path(__file__).resolve().parent / "fixtures" / "pages" / "sloppy.html").read_text(encoding="utf-8")
# Function words that never appear in the Spanish rows (code tokens and quoted buzzwords are not function words).
_ENGLISH = re.compile(r"\b(the|and|with|of|is|are|that|this|your|should|from|into|instead)\b")


def _rules():
    lint.ensure_rules()
    return registry.all_rules()


def test_every_rule_id_has_a_spanish_row_and_no_row_is_stale():
    ids = {r.id for r in _rules()}
    assert len(ids) >= 160
    assert ids - set(i18n_es.RULES_ES) == set(), "rules without Spanish text"
    assert set(i18n_es.RULES_ES) - ids == set(), "Spanish rows for rules that do not exist"


def test_spanish_rows_are_complete_and_do_not_leak_english():
    for rule in _rules():
        name, description, fix = i18n_es.RULES_ES[rule.id]
        assert name.strip() and description.strip() and fix.strip(), rule.id
        for text in (name, description, fix):
            assert not _ENGLISH.search(text), (rule.id, text)
        if rule.engine != "visual":
            assert description != rule.description and name != rule.name, rule.id
    texts = i18n.rule_texts("unslop/neon-border", "es")
    assert texts["name"] == "Bordes de neón" and i18n.rule_texts("unslop/neon-border", "en") is None


def test_rows_in_es_mode_come_from_the_table_and_en_keeps_the_source():
    lint.ensure_rules()
    row = registry.get_rule("slop/nested-cards").row()
    es_row = i18n.localize_rule_row(row, "es")
    assert es_row["name"] == "Tarjetas anidadas" and es_row["id"] == row["id"] and es_row["tier"] == row["tier"]
    assert i18n.localize_rule_row(row, "en")["name"] == "Nested cards"


def test_finding_localisation_keeps_numbers_and_widths():
    lint.ensure_rules()
    f = registry.make_finding("unslop/neon-border", "5 boxes are outlined in a saturated, bright border. Seen at 320, 1440px.",
                              {"items": ["div.card"], "widths": [320, 1440]})
    g = i18n.localize_finding(f, "es")
    assert g["title"] == "Bordes de neón" and g["fix"] == "Filetes tenues."
    assert "Detectados: 5" in g["detail"] and "Visto a 320, 1440 px" in g["detail"]
    assert not _ENGLISH.search(g["detail"]) and g["evidence"] == f["evidence"] and g["tier"] == f["tier"]
    assert i18n.localize_finding(f, "en") is f


def test_plan_and_audit_in_spanish_and_english():
    def finding(rid, level, scope):
        return registry.enrich({"check_id": rid, "title": rid, "detail": "2 element(s) hit", "fix": "x", "level": level, "scope": scope,
                                "pass": "color", "slop": True}, registry.get_rule(rid))
    lint.ensure_rules()
    heavy = [finding(r, "warning", "color") for r in ("unslop/neon-border", "unslop/purple-gradient-hero", "unslop/saturated-shadow")]
    audit = {"render_id": "abc123", "findings": heavy, "mode": "heavy", "credit": i18n_es.CREDIT_EN}
    es = i18n.localize_audit(audit, "es")
    assert es["lang"] == "es" and es["plan"]["summary"].startswith("Un desbarnizado completo") and "CC BY 4.0" in es["credit"]
    assert es["plan"]["passes"][0]["title"].startswith("Color:") and es["findings"][0]["title"] == "Bordes de neón"
    en = i18n.localize_audit(audit, "en")
    assert en["plan"]["summary"].startswith("A full unslop") and en["findings"][0]["title"] == "unslop/neon-border" and "CC BY 4.0" in en["credit"]
    assert audit["findings"][0]["title"] == "unslop/neon-border"          # the stored audit is not mutated
    assert slop_audit.plan([], "none", "es")["summary"].startswith("Ningún indicio")
    assert slop_audit.plan(heavy[:1], "light", "es")["summary"] == "Un pulido ligero: 1 cambios, sin rediseño."
    for name in slop_audit.PASSES:
        assert name in i18n_es.PASS_TITLES_ES and name in i18n_es.PASS_NAMES_ES


def test_norm_lang_prefers_explicit_then_accept_language_then_spanish():
    assert i18n.norm_lang("en") == "en" and i18n.norm_lang("ES-es") == "es"
    assert i18n.norm_lang(None, "en-US,en;q=0.9") == "en" and i18n.norm_lang(None, "fr-FR,es;q=0.8") == "es"
    assert i18n.norm_lang(None, None) == "es" and i18n.norm_lang("xx", "") == "es"


def test_audit_run_stores_english_and_serves_both_languages(tmp_path):
    from test_studio import _sloppy_dom
    svc = make_services(tmp_path, probe_overrides={"dom": {str(w): _sloppy_dom(w) for w in slop_audit.AUDIT_WIDTHS}})
    try:
        out = slop_audit.run(svc, html=SLOPPY)                       # default: Spanish
        assert out["lang"] == "es" and "CC BY 4.0" in out["credit"]
        stored = slop_audit.get(svc, out["render_id"])                # no lang: as stored (English)
        assert stored.get("lang") is None and stored["credit"].startswith("Sign list")
        assert all(not _ENGLISH.search(f["title"]) for f in out["findings"] if f["check_id"] in i18n_es.RULES_ES and f["pack"] != "visual")
        en = slop_audit.get(svc, out["render_id"], "en")
        assert en["lang"] == "en" and en["credit"].startswith("Sign list")
        assert [f["check_id"] for f in en["findings"]] == [f["check_id"] for f in out["findings"]]
        mcp = call_tool(svc, "design_slop_audit", {"render_id": out["render_id"], "lang": "en"})
        assert mcp["credit"].startswith("Sign list")
        mcp_es = call_tool(svc, "design_slop_audit", {"render_id": out["render_id"]})
        assert mcp_es["credit"].startswith("Lista de indicios")
        listed = call_tool(svc, "design_rules_list", {"id": "slop/echo", "lang": "es"})
        assert listed["rule"]["name"] == "El eco" and call_tool(svc, "design_rules_list", {"id": "slop/echo"})["rule"]["name"] == "The echo"
    finally:
        svc.stop()


def test_direction_brief_is_asked_for_in_the_language(tmp_path):
    sent = {}

    class Spy(FakeLink):
        def chat(self, messages, **kw):
            sent["system"] = messages[0]["content"]
            return super().chat(messages, **kw)

    reply = ("Producto: Un seguimiento de envíos para pequeños importadores.\nCarácter: Sereno y exacto, como un libro de aduanas.\n"
             "Momento brillante: El recuento de retrasos.\nFirma: Códigos de contenedor en monoespaciada.\nEvitar: degradados morados, emojis")
    svc = make_services(tmp_path, link=Spy(chat_text=reply))
    try:
        out = slop_audit.direction_brief(svc, text="SynthFlow sigue los envíos de pequeños importadores y avisa de retrasos en aduana.", lang="es")
        assert "castellano de España" in sent["system"] and out["lang"] == "es" and out["source"] == "model"
        assert out["product"].startswith("Un seguimiento") and out["text"].startswith("Producto:") and out["labels"]["avoid"] == "Evitar"
        out_en = slop_audit.direction_brief(svc, text="SynthFlow tracks shipments for small importers and flags delays at customs.", lang="en", use_model=False)
        assert out_en["text"].startswith("Product:") and out_en["source"] == "fallback"
        out_es = slop_audit.direction_brief(svc, text="SynthFlow sigue los envíos de pequeños importadores y avisa de retrasos.", use_model=False)
        assert out_es["text"].startswith("Producto:") and not _ENGLISH.search(out_es["bright_moment"] + out_es["character"] + out_es["avoid"])
    finally:
        svc.stop()
