import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from vitruvius_hoard import brief_content, slop_audit
from vitruvius_hoard.agent_tools import AppCreateArgs, BriefArgs, run_app_project_create, run_design_brief
from vitruvius_hoard.alternatives import AlternativeStudies
from vitruvius_hoard.showcase import library as showcase
from vitruvius_hoard.software.host import catalog
from vitruvius_hoard.study_tools import StudyCreateArgs


COMMISSIONS = [
    ("lighting", "Hacemos una lámpara de sobremesa de latón y vidrio soplado, fabricada en un taller pequeño. Quiero una página para presentarla y que la gente pueda reservarla antes de que salga a la venta.", "38 cm"),
    ("weather", "Llevo una red de doce estaciones meteorológicas en la sierra. Necesito un panel donde ver las lecturas de hoy, compararlas por estación y ver enseguida cuáles están fallando.", "47 min"),
    ("ceramics", "Vendo cerámica hecha a mano: tazas, cuencos y platos, cada pieza un poco distinta. Quiero una tienda con la ficha de cada pieza y un carrito que funcione.", "1.240 °C"),
    ("physiotherapy", "Tengo un centro de fisioterapia con cuatro profesionales. Quiero que los pacientes reserven cita desde el móvil eligiendo tratamiento, profesional y hora.", "45 min"),
    ("photography", "Soy fotógrafa documental y quiero un portfolio para enseñar mis series, cada una con su texto. Que se lea como una revista y no como una cuadrícula de miniaturas.", "Cuaderno de bajamar"),
    ("registration", "Somos una gestoría y queremos que los clientes soliciten el alta de autónomo por internet. Son bastantes datos (personales, actividad, domicilio fiscal, cuenta bancaria) y tienen que llegar bien a la primera.", "15 de abril"),
    ("invoicing", "Vendemos un programa de facturación para pequeños negocios con tres planes y descuento si se paga al año. Necesitamos la página de precios con la comparativa y las preguntas frecuentes.", "108,90 €"),
    ("plants", "Estamos sacando una app para llevar el cuidado de las plantas de casa: riego, luz y abono. Queremos la bienvenida de tres pantallas que explica qué hace antes de crear la cuenta.", "calatea"),
    ("restaurant", "Tenemos un restaurante de cocina de mercado en un barrio de Valencia, con menú del día y una carta que cambia cada temporada. Queremos la web con la carta, los horarios y cómo reservar.", "Benicarló"),
    ("banking", "Quiero un banco personal: ver mis cuentas con su saldo y hacer transferencias. Que lleve un asistente de voz al que pueda decirle la transferencia de una vez, por pasos, o dejándome datos para que me los pregunte.", "36,50 €"),
]


@pytest.mark.parametrize("domain,commission,detail", COMMISSIONS, ids=[row[0] for row in COMMISSIONS])
def test_battery_content_and_structurally_distinct_references(tmp_path, domain, commission, detail):
    brief = brief_content.build(commission)
    assert brief["domain"] == domain and brief["content_status"] == "draft"
    assert len(brief["content_sections"]) >= 2
    copy = " ".join(s["title"] + " " + s["copy"] for s in brief["content_sections"])
    assert detail in copy and not re.search(r"lorem|datos ficticios|datos simulados", copy, re.I)
    assert brief["simulation_notice"] == {"show": False, "placement": None, "text": None}
    for section in brief["content_sections"]:
        assert showcase.read(section["recipe"]["id"])["title"] == section["recipe"]["title"]
    plan = brief["art_direction"]
    assert plan["required_before_build"]
    assert len(plan["directions"]) == 3
    assert sum(d["typical"] for d in plan["directions"]) == 1
    assert not next(d for d in plan["directions"] if d["id"] == plan["recommended_id"])["typical"]
    for key in ("composition", "typography", "color", "motion"):
        assert len({d[key] for d in plan["directions"]}) == 3
    args = StudyCreateArgs(**plan["create"]["arguments"])
    args.check_only = True
    engine = AlternativeStudies(SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path)))
    receipt = engine.create(**args.model_dump())
    assert receipt["diversity"]["ok"] and not engine.list()


def test_simulation_notice_requires_an_explicit_request_and_is_localised():
    commission = COMMISSIONS[-1][1]
    assert not brief_content.build(commission + " Marcas y datos inventados.")["simulation_notice"]["show"]
    assert not brief_content.build(commission + " No muestres un aviso de datos simulados.")["simulation_notice"]["show"]
    assert brief_content.build(commission + " Quiero que pongas un aviso de datos ficticios.")["simulation_notice"]["show"]
    assert brief_content.build(commission + " Incluye un aviso de datos simulados.")["simulation_notice"] == {
        "show": True, "placement": "footer", "text": "Datos simulados",
    }
    assert brief_content.build("Banking app with accounts. Add a notice for simulated data.", lang="en")["simulation_notice"] == {
        "show": True, "placement": "footer", "text": "Simulated data",
    }
    assert not brief_content.build(commission + " Incluye un aviso de datos simulados.",
                                   show_simulation_notice=False)["simulation_notice"]["show"]
    tesela = Path(__file__).resolve().parents[1] / "docs/examples/app-projects/personal-banking/layout.html"
    assert ">Datos simulados</span>" in tesela.read_text(encoding="utf-8")


@pytest.mark.parametrize("allows_typical", [False, True])
def test_real_alternatives_decision_and_project_receipt(tmp_path, allows_typical):
    from conftest import FakeLink
    from vitruvius_hoard.config import Config
    from vitruvius_hoard.services import Services

    services = Services(Config(data_dir=tmp_path, port=56129, embed_backend="none"), link=FakeLink())
    response = run_design_brief(services, BriefArgs(subject=COMMISSIONS[2][1], lang="es",
                                                     allow_typical_direction=allows_typical))
    plan = response["art_direction"]
    args = StudyCreateArgs(**plan["create"]["arguments"])
    study = services.alternatives.create(**args.model_dump())
    for extra in ({"label": "Custom form", "html": "<form><input><button>Send</button></form>"},
                  {"label": "Fourth pattern", "pattern_id": "pulse"}):
        with pytest.raises(ValueError, match="keeps its three library patterns"):
            services.alternatives.add_alternative(study["id"], extra)
    assert len(services.alternatives.get(study["id"])["alternatives"]) == 3
    submitted = AppCreateArgs(name="Taller", art_direction_study_id=study["id"])
    with pytest.raises(ValueError, match="Choose an art direction"):
        run_app_project_create(services, submitted)
    typical = next(a for a in study["alternatives"] if a["typical"])
    assert "Típica de la categoría" in typical["label"]
    criterion = study["criteria"][0]["id"]
    services.alternatives.evaluate(study["id"], [
        {"alternative": a["id"], "criterion": criterion, "score": 8,
         "rationale": "La composición permite presentar las dos piezas por separado."}
        for a in study["alternatives"]
    ])
    reason = "Conserva la ficha de cada pieza y el contexto del taller."
    if not allows_typical:
        with pytest.raises(ValueError, match="typical direction"):
            services.alternatives.decide(study["id"], typical["id"], reason)
    chosen = next(a for a in study["alternatives"] if a["pattern_id"] == plan["recommended_id"])
    chosen_study = services.alternatives.decide(study["id"], chosen["id"], reason)
    project = run_app_project_create(services, submitted)
    assert json.loads(project["files"]["project.json"])["art_direction"] == {
        "study_id": study["id"], "study_revision": 1, "pattern_id": chosen["pattern_id"], "reason": reason,
    }
    valid = services.alternatives._load(study["id"])
    legacy = json.loads(json.dumps(valid))
    next(a for a in legacy["alternatives"] if a["id"] == chosen["id"]).pop("pattern_id")
    services.alternatives._save(legacy)
    with pytest.raises(ValueError, match="three distinct patterns"):
        services.alternatives.decide(study["id"], chosen["id"], reason)
    with pytest.raises(ValueError, match="three distinct patterns"):
        run_app_project_create(services, submitted)
    services.alternatives._save(valid)
    reverted = services.alternatives.set_criteria(**chosen_study["undo_call"]["arguments"])
    assert reverted["decision"] is None and reverted["history"][0]["decision"]["alternative_id"] == chosen["id"]


def test_direction_brief_shares_content_contract_without_a_model():
    text = COMMISSIONS[4][1]
    report = slop_audit.direction_brief(SimpleNamespace(), text=text, use_model=False, lang="en")
    assert report["source"] == "fallback" and report["product"]
    assert report["content_sections"][0]["title"] == "Low-tide notebook"
    assert report["art_direction"]["required_before_build"]


def test_cold_mcp_schema_exposes_the_whole_commission_and_direction_fields():
    schemas = {item["name"]: item["inputSchema"]["properties"] for item in catalog()
               if item["name"] in {"design_brief", "design_direction_brief", "design_alternatives_create", "app_project_create"}}
    for name in ("design_brief", "design_direction_brief"):
        assert {"lang", "show_simulation_notice", "allow_typical_direction"} <= schemas[name].keys()
    assert schemas["design_brief"]["subject"]["maxLength"] >= max(len(row[1]) for row in COMMISSIONS)
    assert {"art_direction", "allow_typical"} <= schemas["design_alternatives_create"].keys()
    assert "art_direction_study_id" in schemas["app_project_create"]
