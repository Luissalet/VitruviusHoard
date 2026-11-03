"""Design by comparable alternatives: diversity, frozen criteria, Pareto frontier, trade-offs, weights, decision."""
import json
from pathlib import Path

import pytest
from conftest import FakeBrowser, make_services

from vitruvius_hoard import alternatives as alt
from vitruvius_hoard.agent_tools import TOOLS_BY_NAME, call_tool
from vitruvius_hoard.diagrams.documents import DocumentStore
from vitruvius_hoard.hoard_link.agentkit import AppError

class Tpl(str):
    """Literal braces stay literal; only {name} placeholders are replaced."""

    def format(self, **values):
        out = str(self)
        for key, value in values.items():
            out = out.replace("{" + key + "}", value)
        return out


DASHBOARD = Tpl("""<!doctype html><html><head><title>x</title><style>body{background:{bg};color:{fg};font-family:{font}}
.layout{display:grid;grid-template-columns:240px 1fr}</style></head><body><header><nav><a href="/">Home</a><a href="/r">Reports</a></nav></header>
<div class="layout"><aside><ul><li>Filters</li><li>Dates</li></ul></aside><main><h1>Sales</h1><table><tr><th>Region</th><th>Total</th></tr><tr><td>North</td><td>10</td></tr></table></main></div>{marker}</body></html>""")
LANDING = Tpl("""<!doctype html><html><head><style>.cards{display:flex;flex-direction:column}</style></head><body><main><section><h1>Sales</h1><p>One page story</p><button>Start</button></section>
<section class="cards"><article><h2>North</h2><p>10</p></article><article><h2>South</h2><p>12</p></article><article><h2>East</h2><p>7</p></article></section></main><footer><p>End</p></footer>{marker}</body></html>""")
WIZARD = Tpl("""<!doctype html><html><head><style>form{display:flex}</style></head><body><main><form><fieldset><legend>Step 1</legend><label>Region<input></label><label>Period<select><option>Q1</option></select></label></fieldset>
<button>Next</button></form><details><summary>Help</summary><p>Pick values.</p></details></main>{marker}</body></html>""")


def dash(bg="#fff", fg="#111", font="Inter", marker=""):
    return DASHBOARD.format(bg=bg, fg=fg, font=font, marker=marker)


class MarkerBrowser(FakeBrowser):
    """Probe depends on a <!--p:name--> marker in the page, so alternatives measure differently."""
    TABLE: dict = {}

    def capture(self, *, html=None, **kwargs):
        match = html and __import__("re").search(r"<!--p:(\w+)-->", html)
        self.probe_overrides = dict(self.TABLE.get(match.group(1), {})) if match else {}
        return super().capture(html=html, **kwargs)


def services_for(tmp_path, table=None):
    svc = make_services(tmp_path)
    browser = MarkerBrowser()
    browser.TABLE = table or {}
    svc.browser = browser
    svc.start()

    def runner(cmd, timeout):
        text = (Path(cmd[2]) / "index.html").read_text(encoding="utf-8")
        failed = text.count("BROKEN")
        cases = [{"id": "C1", "what": "open", "outcome": "passed"}] + [{"id": f"F{i}", "what": "broken control", "outcome": "failed", "detail": "x"} for i in range(failed)]
        return (1 if failed else 0), json.dumps({"cases": cases, "works": not failed, "planned": len(cases), "passed": 1, "failed": failed}), ""
    svc.assay_runner = runner
    return svc


CRITERIA = [{"name": "Accessible contrast", "source": "contrast_min_ratio", "weight": 3},
            {"name": "Light page", "source": "dom_size", "weight": 1},
            {"name": "Fits the team", "source": "manual", "weight": 2}]


# ---------------- diversity ----------------

def test_colour_and_font_only_variants_are_refused_with_the_reason(tmp_path):
    svc = services_for(tmp_path)
    variants = [{"label": "Blue", "html": dash("#eef", "#113", "Inter")}, {"label": "Green", "html": dash("#efe", "#131", "Georgia")},
                {"label": "Dark", "html": dash("#111", "#eee", "Courier")}]
    with pytest.raises(ValueError) as error:
        svc.alternatives.create("Pick a layout for the sales dashboard", CRITERIA, variants)
    text = str(error.value)
    assert "variants, not alternatives" in text and "colour, typography" in text and "0.00 apart" in text
    assert svc.alternatives.list() == []
    svc.stop()


def test_wording_changes_alone_are_not_structure(tmp_path):
    svc = services_for(tmp_path)
    other = dash().replace("Sales", "Ventas").replace("North", "Norte")
    with pytest.raises(ValueError, match="variants"):
        svc.alternatives.create("Pick a layout for the sales dashboard", CRITERIA, [{"label": "EN", "html": dash()}, {"label": "ES", "html": other}])
    svc.stop()


def test_structurally_different_alternatives_are_accepted_and_distances_reported(tmp_path):
    svc = services_for(tmp_path)
    plan = {"brief": "Pick a layout for the sales dashboard", "criteria": CRITERIA,
            "alternatives": [{"label": "Dashboard", "html": dash()}, {"label": "Story", "html": LANDING.format(marker="")}, {"label": "Wizard", "html": WIZARD.format(marker="")}]}
    checked = svc.alternatives.create(**plan, check_only=True)
    assert checked["diversity"]["ok"] and all(p["distance"] >= 0.2 for p in checked["diversity"]["pairs"]) and svc.alternatives.list() == []
    study = svc.alternatives.create(**plan)
    assert [a["id"] for a in study["alternatives"]] == ["a1", "a2", "a3"] and study["revision"] == 1 and not study["frozen"]
    assert "html" not in study["alternatives"][0] and study["alternatives"][0]["sha256"]
    svc.stop()


def test_layout_change_with_identical_markup_counts_as_structure_but_colour_does_not():
    base = dash()
    one_column = base.replace("display:grid;grid-template-columns:240px 1fr", "display:block")
    three_columns = base.replace("grid-template-columns:240px 1fr", "grid-template-columns:repeat(3,1fr)")
    recoloured = base.replace("#fff", "#000")
    fa, fb, fc, fd = (alt.fingerprint_html(x) for x in (base, one_column, three_columns, recoloured))
    assert alt.distance_parts(fa, fd)["distance"] == 0
    assert alt.distance_parts(fa, fb)["distance"] >= 0.2 and alt.distance_parts(fa, fb)["paths"] == 0
    assert alt.distance_parts(fa, fc)["distance"] >= 0.2  # 2-track vs 3-track grid


def test_adding_a_near_duplicate_later_is_refused(tmp_path):
    svc = services_for(tmp_path)
    study = svc.alternatives.create("Pick a layout for the sales dashboard", CRITERIA, [{"label": "Dashboard", "html": dash()}, {"label": "Story", "html": LANDING.format(marker="")}])
    with pytest.raises(ValueError, match="variants"):
        svc.alternatives.add_alternative(study["id"], {"label": "Dark dashboard", "html": dash("#000", "#fff")})
    added = svc.alternatives.add_alternative(study["id"], {"label": "Wizard", "html": WIZARD.format(marker="")})
    assert added["alternatives"][-1]["id"] == "a3"
    svc.stop()


def test_app_projects_of_one_template_are_variants_until_their_pages_differ(tmp_path):
    svc = services_for(tmp_path)
    a, b = svc.app_projects.create("One", "inventory"), svc.app_projects.create("Two", "inventory")
    crit = [{"name": "Judgement", "source": "manual"}]
    with pytest.raises(ValueError, match="variants"):
        svc.alternatives.create("Which inventory app structure suits the shop", crit, [{"label": "One", "project_id": a["id"]}, {"label": "Two", "project_id": b["id"]}])
    svc.app_projects.update(b["id"], {"pages/index.html": "<h1>{{name}}</h1><section><ul><li>{{count}}</li></ul></section><aside><p>Help</p></aside>",
                                      "assets/style.css": ".x{display:grid;grid-template-columns:repeat(3,1fr)}"}, b["revision"])
    study = svc.alternatives.create("Which inventory app structure suits the shop", crit, [{"label": "One", "project_id": a["id"]}, {"label": "Two", "project_id": b["id"]}])
    assert study["alternatives"][0]["kind"] == "app_project" and study["alternatives"][1]["revision"] != a["revision"]
    svc.stop()


# ---------------- Pareto, trade-offs, weights (pure, fixed measures) ----------------

def fixture():
    criteria = alt.normalise_criteria([{"name": "Accessibility", "source": "contrast_min_ratio", "weight": 2},
                                       {"name": "Weight", "source": "dom_size", "weight": 1}, {"name": "Fit", "source": "manual", "weight": 1}])
    def m(contrast, dom, fit):
        return {"accessibility": {"value": contrast}, "weight": {"value": dom}, "fit": {"value": fit}}
    alts = [{"id": "a1", "label": "Dashboard", "measures": m(7.5, 900, 6)}, {"id": "a2", "label": "Story", "measures": m(4.6, 300, 8)},
            {"id": "a3", "label": "Wizard", "measures": m(4.0, 950, 5)}]
    return criteria, alts


def test_pareto_frontier_dominance_and_tradeoff_text():
    criteria, alts = fixture()
    r = alt.analyze(criteria, alts)
    assert r["complete"] and r["frontier"] == ["a1", "a2"]
    assert r["dominated"] == {"a3": {"by": ["a1", "a2"]}}
    texts = [t["text"] for t in r["tradeoffs"]]
    assert "Dashboard is better on Accessibility (7.5 vs 4.6), but yields on Weight (900 vs 300), Fit (6 vs 8)." in texts
    assert any(t.startswith("Wizard is dominated by Dashboard") and "at least as good on every criterion" in t for t in texts)
    assert r["leads"]["a1"]["leads_on"] == ["accessibility"] and "accessibility" in r["leads"]["a3"]["yields_on"]
    assert abs(sum(r["weights"].values()) - 1) < 1e-9 and r["ranking"][-1]["id"] == "a3"


def test_weights_change_ranking_without_changing_the_frontier():
    criteria, alts = fixture()
    base = alt.analyze(criteria, alts)
    heavy_weight = alt.reweight(criteria, alts, {"weight": 10})
    assert base["leader"] != heavy_weight["leader"] and heavy_weight["leader_changed"] and "changes from" in heavy_weight["effect"]
    assert heavy_weight["frontier_unchanged"] and heavy_weight["baseline_leader"] == base["leader"]
    swept = alt.sensitivity(criteria, alts, "weight")
    assert swept["breaks"] and swept["breaks"][0]["from"] == base["leader"] and "overtakes" in swept["text"]
    with pytest.raises(ValueError, match="Unknown criteria"):
        alt.analyze(criteria, alts, {"nope": 1})


def test_incomplete_measures_give_no_ranking():
    criteria, alts = fixture()
    del alts[0]["measures"]["fit"]
    r = alt.analyze(criteria, alts)
    assert r == {"complete": False, "missing": [{"alternative": "a1", "criterion": "fit"}]}


# ---------------- end to end with the existing tools ----------------

PLAN = {"brief": "Pick a layout for the sales dashboard", "criteria": CRITERIA}


def three(svc):
    contrast = lambda ratio: {"contrast_pairs": [{"color": "rgb(%d,%d,%d)" % ((ratio,) * 3), "background": "rgb(255,255,255)", "text": "t"}]}  # noqa: E731
    return [{"label": "Dashboard", "html": dash(marker="<!--p:dash-->")}, {"label": "Story", "html": LANDING.format(marker="<!--p:story-->")},
            {"label": "Wizard", "html": WIZARD.format(marker="<!--p:wiz-->")}]


TABLE = {"dash": {"dom_size": 900, "contrast_pairs": [{"color": "rgb(0,0,0)", "background": "rgb(255,255,255)", "text": "t"}]},
         "story": {"dom_size": 300, "contrast_pairs": [{"color": "rgb(130,130,130)", "background": "rgb(255,255,255)", "text": "t"}]},
         "wiz": {"dom_size": 950, "contrast_pairs": [{"color": "rgb(150,150,150)", "background": "rgb(255,255,255)", "text": "t"}]}}


def measured_study(tmp_path):
    svc = services_for(tmp_path, TABLE)
    study = svc.alternatives.create(PLAN["brief"], CRITERIA, three(svc))
    first = svc.alternatives.evaluate(study["id"])
    assert first["measured"] == ["a1", "a2", "a3"] and len(first["awaiting_manual"]) == 3 and first["analysis"]["complete"] is False
    done = svc.alternatives.evaluate(study["id"], [{"alternative": "a1", "criterion": "fits_the_team", "score": 6, "rationale": "Familiar table, slower to learn."},
                                                 {"alternative": "a2", "criterion": "fits_the_team", "score": 8, "rationale": "Matches how the team reads reports."},
                                                 {"alternative": "a3", "criterion": "fits_the_team", "score": 4, "rationale": "Too many steps for daily use."}])
    return svc, study["id"], done


def test_evaluate_measures_with_real_tools_and_computes_the_frontier(tmp_path):
    svc, id, done = measured_study(tmp_path)
    analysis = done["analysis"]
    assert analysis["complete"] and done["frozen"] and done["measured"] == []
    values = analysis["values"]
    assert values["a1"]["accessible_contrast"] == 21.0 and values["a2"]["accessible_contrast"] < 5 and values["a1"]["light_page"] == 900
    assert set(analysis["frontier"]) == {"a1", "a2"} and "a3" in analysis["dominated"]
    detail = svc.alternatives._load(id)["alternatives"][0]["measures"]["accessible_contrast"]
    assert detail["source"] == "contrast_min_ratio" and detail["measured_ts"]
    svc.stop()


def test_weight_whatif_does_not_measure_again(tmp_path):
    svc, id, _ = measured_study(tmp_path)
    renders = len(svc.browser.calls)
    base = svc.alternatives.analyze(id)
    what_if = svc.alternatives.analyze(id, {"light_page": 20}, sensitivity_of="light_page")
    assert len(svc.browser.calls) == renders  # recomputed from stored measures
    assert what_if["leader_changed"] and what_if["leader"] != base["leader"] and what_if["sensitivity"]["breaks"]
    assert svc.alternatives._load(id)["criteria"][1]["weight"] == 1  # the frozen weight is untouched
    svc.stop()


def test_criteria_are_frozen_after_measurement_and_a_new_revision_keeps_what_still_holds(tmp_path):
    svc, id, _ = measured_study(tmp_path)
    changed = [{"name": "Accessible contrast", "source": "contrast_min_ratio", "weight": 3}, {"name": "Light page", "source": "dom_size", "weight": 5},
               {"name": "Fits the team", "source": "manual", "weight": 2}, {"name": "No broken controls", "source": "page_check_failed"}]
    with pytest.raises(ValueError, match="frozen"):
        svc.alternatives.set_criteria(id, changed)
    with pytest.raises(ValueError, match="reason"):
        svc.alternatives.set_criteria(id, changed, new_revision=True)
    revised = svc.alternatives.set_criteria(id, changed, new_revision=True, reason="The team also wants working controls.")
    assert revised["revision"] == 2 and revised["carried_over"] == ["accessible_contrast", "fits_the_team", "light_page"] and revised["remeasure"] == ["no_broken_controls"]
    assert revised["history"][0]["revision"] == 1 and revised["analysis"]["complete"] is False
    done = svc.alternatives.evaluate(id)
    assert done["measured"] == ["a1", "a2", "a3"] and done["analysis"]["complete"]
    assert done["analysis"]["values"]["a1"]["no_broken_controls"] == 0
    svc.stop()


def test_criteria_can_change_freely_before_any_measurement(tmp_path):
    svc = services_for(tmp_path)
    study = svc.alternatives.create(PLAN["brief"], CRITERIA, three(svc))
    out = svc.alternatives.set_criteria(study["id"], [{"name": "Only manual", "source": "manual"}])
    assert [c["id"] for c in out["criteria"]] == ["only_manual"] and out["revision"] == 1
    svc.stop()


def test_page_check_failures_are_a_criterion(tmp_path):
    svc = services_for(tmp_path)
    pages = [{"label": "Dashboard", "html": dash() + "BROKEN BROKEN"}, {"label": "Story", "html": LANDING.format(marker="")}]
    study = svc.alternatives.create(PLAN["brief"], [{"name": "Controls work", "source": "page_check_failed"}], pages)
    out = svc.alternatives.evaluate(study["id"])
    assert out["analysis"]["values"] == {"a1": {"controls_work": 2.0}, "a2": {"controls_work": 0.0}}
    assert out["analysis"]["leader"] == "a2"
    svc.stop()


def test_decision_keeps_reason_and_refuses_dominated_choice(tmp_path):
    svc, id, _ = measured_study(tmp_path)
    with pytest.raises(ValueError, match="dominated by"):
        svc.alternatives.decide(id, "a3", "Because the team likes wizards a lot.")
    with pytest.raises(ValueError, match="reason"):
        svc.alternatives.decide(id, "a2", "ok")
    done = svc.alternatives.decide(id, "a2", "Lightest page and best team fit; we accept lower contrast and will fix it in the theme.")
    d = done["decision"]
    assert d["alternative_id"] == "a2" and d["on_frontier"] and "lower contrast" in d["reason"] and d["tradeoffs"] and d["rank"] in (1, 2)
    assert svc.alternatives.list()[0]["decided"] == "a2"
    forced = svc.alternatives.decide(id, "a3", "Legal requires the step-by-step wizard form, which the criteria do not capture.", accept_dominated=True)
    assert forced["decision"]["dominated_by"] and not forced["decision"]["on_frontier"]
    with pytest.raises(ValueError, match="decision"):
        svc.alternatives.add_alternative(id, {"label": "More", "html": "<main><dl><dt>a</dt></dl></main>"})
    svc.stop()


def test_decide_needs_complete_measures(tmp_path):
    svc = services_for(tmp_path)
    study = svc.alternatives.create(PLAN["brief"], CRITERIA, three(svc))
    with pytest.raises(ValueError, match="Measure every alternative"):
        svc.alternatives.decide(study["id"], "a1", "I just prefer this layout today.")
    svc.stop()


def test_manual_scores_need_range_and_rationale(tmp_path):
    svc = services_for(tmp_path)
    study = svc.alternatives.create(PLAN["brief"], [{"name": "Judgement", "source": "manual", "params": {"min": 0, "max": 5}}], three(svc))
    with pytest.raises(ValueError, match="from 0 to 5"):
        svc.alternatives.evaluate(study["id"], [{"alternative": "a1", "criterion": "judgement", "score": 9, "rationale": "Far too high a score."}])
    with pytest.raises(ValueError, match="rationale"):
        svc.alternatives.evaluate(study["id"], [{"alternative": "a1", "criterion": "judgement", "score": 3, "rationale": "ok"}])
    svc.stop()


def test_diagram_alternatives_are_measured_by_gates_and_size(tmp_path):
    svc = services_for(tmp_path)
    store = DocumentStore(svc.config.data_dir)
    chain = {"diagram": {"type": "flowchart", "title": "A", "nodes": [{"id": f"n{i}", "label": f"Step {i}"} for i in range(4)],
                         "edges": [{"id": f"e{i}", "from": f"n{i}", "to": f"n{i + 1}"} for i in range(3)]}, "view": {"nodes": {}, "edges": {}}}
    hub = {"diagram": {"type": "flowchart", "title": "B", "nodes": [{"id": "h", "label": "Hub"}] + [{"id": f"s{i}", "label": f"Spoke {i}"} for i in range(5)],
                       "edges": [{"id": f"e{i}", "from": "h", "to": f"s{i}"} for i in range(5)]}, "view": {"nodes": {}, "edges": {}}}
    a, b = store.save(chain)["id"], store.save(hub)["id"]
    study = svc.alternatives.create("Chain or hub for the order flow", [{"name": "Few nodes", "source": "diagram_nodes"}, {"name": "Legible", "source": "diagram_gate_failures"}],
                                    [{"label": "Chain", "document_id": a}, {"label": "Hub", "document_id": b}])
    out = svc.alternatives.evaluate(study["id"])
    assert out["analysis"]["values"]["a1"]["few_nodes"] == 4 and out["analysis"]["values"]["a2"]["few_nodes"] == 6 and out["analysis"]["leader"] in ("a1", "a2")
    with pytest.raises(ValueError, match="cannot be measured"):
        svc.alternatives.create("Mixed kinds are not comparable", [{"name": "Contrast", "source": "contrast_min_ratio"}],
                                [{"label": "Chain", "document_id": a}, {"label": "Page", "html": dash()}])
    svc.stop()


def test_agent_tools_and_rest_follow_the_same_path(tmp_path):
    svc = services_for(tmp_path, TABLE)
    names = {n for n in TOOLS_BY_NAME if n.startswith("design_alternatives_")}
    assert names == {f"design_alternatives_{x}" for x in ("create", "list", "get", "add", "evaluate", "criteria", "analyze", "decide")}
    made = call_tool(svc, "design_alternatives_create", {"brief": PLAN["brief"], "criteria": CRITERIA, "alternatives": three(svc)})
    assert call_tool(svc, "design_alternatives_list", {})["studies"][0]["id"] == made["id"]
    call_tool(svc, "design_alternatives_evaluate", {"id": made["id"], "manual_scores": [
        {"alternative": a, "criterion": "fits_the_team", "score": s, "rationale": "Scored against the team's real workflow."} for a, s in (("a1", 6), ("a2", 8), ("a3", 4))]})
    res = call_tool(svc, "design_alternatives_analyze", {"id": made["id"], "weights": {"light_page": 30}})
    assert res["complete"] and "effect" in res
    with pytest.raises(ValueError, match="frozen"):
        call_tool(svc, "design_alternatives_criteria", {"id": made["id"], "criteria": [{"name": "X", "source": "manual"}]})
    with pytest.raises((AppError, LookupError)):
        call_tool(svc, "design_alternatives_get", {"id": "0" * 12})
    svc.stop()


def test_rest_routes(client):
    client.svc.browser = MarkerBrowser()
    client.svc.browser.TABLE = TABLE
    body = {"brief": PLAN["brief"], "criteria": [{"name": "Light", "source": "dom_size"}], "alternatives": three(client.svc)}
    bad = client.post("/api/design-alternatives", json={**body, "alternatives": [{"label": "A", "html": dash("#fff")}, {"label": "B", "html": dash("#000")}]})
    assert bad.status_code == 400 and "variants" in bad.json()["error"]
    r = client.post("/api/design-alternatives", json=body)
    assert r.status_code == 201
    id = r.json()["id"]
    assert client.post(f"/api/design-alternatives/{id}/evaluate", json={}).json()["analysis"]["complete"]
    assert client.post(f"/api/design-alternatives/{id}/analyze", json={"weights": {"light": 1}}).json()["ranking"]
    assert client.put(f"/api/design-alternatives/{id}/criteria", json={"criteria": [{"name": "X", "source": "manual"}]}).status_code == 400
    assert client.get(f"/api/design-alternatives/{id}").json()["frozen"] is True
    assert client.post(f"/api/design-alternatives/{id}/decision", json={"alternative_id": "a2", "reason": "Lightest page of the three."}).json()["decision"]["label"] == "Story"
    assert client.get("/api/design-alternatives/ffffffffffff").status_code == 404
