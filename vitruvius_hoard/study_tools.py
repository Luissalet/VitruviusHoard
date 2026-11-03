"""Agent tools for design alternatives (frozen criteria, Pareto trade-offs) and the instrument factory."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from .hoard_link.agentkit import Empty, Tool, ann



class CriterionIn(BaseModel):
    name: str = Field(..., max_length=80)
    source: str = Field(..., description="critique_score, lint_score, page_check_failed, contrast_failures, contrast_min_ratio, small_tap_targets, dom_size, "
                        "external_libs, render_ms, page_bytes (pages, apps); diagram_gate_failures, diagram_nodes, diagram_edges (diagrams); manual (any, needs a rationale per score).")
    direction: Optional[str] = Field(None, pattern="^(max|min)$", description="Default comes from the source (critique_score max, dom_size min...).")
    weight: float = Field(1, ge=0, le=1000)
    params: Optional[dict[str, Any]] = Field(None, description="manual: {min, max} scale, default 0 to 10.")
    why: str = Field("", max_length=400)


class AlternativeIn(BaseModel):
    label: str = Field(..., max_length=80)
    kind: Optional[str] = Field(None, pattern="^(page|app_project|diagram_document)$")
    html: Optional[str] = Field(None, description="page: the HTML.")
    path: Optional[str] = Field(None, description="page: a local .html file or folder.")
    project_id: Optional[str] = Field(None, max_length=40, description="app_project: the application project (its revision is pinned).")
    document_id: Optional[str] = Field(None, max_length=40, description="diagram_document: the editable diagram (its revision is pinned).")
    revision: Optional[str | int] = None
    intent: str = Field("", max_length=400, description="What structural idea this alternative tests.")


class StudyCreateArgs(BaseModel):
    brief: str = Field(..., max_length=2000, description="What is being designed and for whom (at least a sentence).")
    criteria: list[CriterionIn] = Field(..., max_length=12)
    alternatives: list[AlternativeIn] = Field(..., max_length=12, description="2 to 12 alternatives.")
    diversity_threshold: float = Field(0.2, gt=0, lt=1, description="Minimum structural distance between any two alternatives.")
    check_only: bool = Field(False, description="Only report structural distances; create nothing.")


class StudyIdArgs(BaseModel):
    id: str = Field(..., max_length=40)


class StudyAddArgs(BaseModel):
    id: str = Field(..., max_length=40)
    alternative: dict[str, Any] = Field(..., description="label, kind (page|app_project|diagram_document), html | path | project_id | document_id, revision, intent.")


class ManualScore(BaseModel):
    alternative: str = Field(..., max_length=8)
    criterion: str = Field(..., max_length=60)
    score: float
    rationale: str = Field(..., max_length=600)


class StudyEvaluateArgs(BaseModel):
    id: str = Field(..., max_length=40)
    manual_scores: list[ManualScore] = Field(default_factory=list)
    remeasure: bool = Field(False, description="Measure again values that already exist (criteria stay frozen).")


class StudyCriteriaArgs(BaseModel):
    id: str = Field(..., max_length=40)
    criteria: list[CriterionIn] = Field(..., max_length=12)
    new_revision: bool = Field(False, description="Required once anything is measured: creates a study revision, keeps the old one in history.")
    reason: str = Field("", max_length=400)


class StudyAnalyzeArgs(BaseModel):
    id: str = Field(..., max_length=40)
    weights: Optional[dict[str, float]] = Field(None, description="What-if weights by criterion id; nothing is measured again and nothing is saved.")
    sensitivity_of: Optional[str] = Field(None, max_length=60, description="Criterion id: at which share of the weight does the leader change?")


class StudyDecideArgs(BaseModel):
    id: str = Field(..., max_length=40)
    alternative_id: str = Field(..., max_length=8)
    reason: str = Field(..., max_length=1000)
    weights: Optional[dict[str, float]] = None
    accept_dominated: bool = False


class InstrumentCreateArgs(BaseModel):
    spec: dict[str, Any] = Field(..., description="name, kind (calculator|viewer|comparator|editor), inputs [{name,label,type number|integer|text|choice|boolean,unit,min,max,step,default,choices,to_base}], "
                                 "operations [{name,params,formula}], steps and outputs [{name,label,unit,decimals,formula | operation+args}], invariants [{name,expression}], "
                                 "examples [{name,inputs,expected,tolerance}], rows (viewer/editor/comparator), views. Formulas: + - * / // %, comparisons, and/or/not, x if c else y, "
                                 "min max abs round floor ceil sqrt pow clamp log exp, your operations. Use pow(x, n), not **.")


class InstrumentIdArgs(BaseModel):
    id: str = Field(..., max_length=40)
    revision: Optional[str] = None
    include_files: bool = False


class InstrumentUpdateArgs(BaseModel):
    id: str = Field(..., max_length=40)
    spec: dict[str, Any]


class InstrumentComputeArgs(BaseModel):
    id: str = Field(..., max_length=40)
    inputs: dict[str, Any] = Field(default_factory=dict)
    revision: Optional[str] = None


class InstrumentExplainArgs(BaseModel):
    id: str = Field(..., max_length=40)
    inputs: Optional[dict[str, Any]] = Field(None, description="Default: the first example of the spec.")
    revision: Optional[str] = None


class InstrumentCheckArgs(BaseModel):
    id: str = Field(..., max_length=40)
    revision: Optional[str] = None
    inputs: Optional[dict[str, Any]] = Field(None, description="Also compare the explainer with the exported instrument for these inputs.")


class InstrumentExportArgs(BaseModel):
    id: str = Field(..., max_length=40)
    revision: Optional[str] = None
    run_check: bool = True


def _dump(model):
    return model.model_dump(exclude_none=True) if hasattr(model, "model_dump") else model


def tools() -> list[Tool]:
    S = lambda s: s.alternatives  # noqa: E731
    I = lambda s: s.instruments  # noqa: E731
    return [
        Tool("design_alternatives_create",
             "Compare structurally different alternatives on frozen criteria. Crear estudio de alternativas.\n"
             "Brief + criteria (each with a measurable source, direction and weight) + 2..12 pages, app projects or diagrams. Refuses colour-only variants: "
             "structural fingerprints of the DOM/outline must differ in element structure or layout. check_only reports distances without creating.\n"
             "Sinónimos: alternativas, comparar diseños, opciones, variantes, criterios, decisión de diseño.",
             StudyCreateArgs, ann(False, False, True),
             lambda s, a: S(s).create(a.brief, [_dump(c) for c in a.criteria], [_dump(x) for x in a.alternatives], a.diversity_threshold, a.check_only)),
        Tool("design_alternatives_list", "List alternatives studies with state and decision. Listar estudios de alternativas.",
             Empty, ann(True), lambda s, a: {"studies": S(s).list()}),
        Tool("design_alternatives_get", "Read a study: criteria, alternatives, diversity, measures, frontier and trade-offs. Leer estudio.",
             StudyIdArgs, ann(True), lambda s, a: S(s).get(a.id)),
        Tool("design_alternatives_add", "Add an alternative that is structurally different from the others. Añadir alternativa.",
             StudyAddArgs, ann(False, False, True), lambda s, a: S(s).add_alternative(a.id, a.alternative)),
        Tool("design_alternatives_evaluate",
             "Measure alternatives on the frozen criteria; record manual scores. Evaluar alternativas.\n"
             "Uses render, lint, critique (heuristics), page_check and contrast measures. Manual criteria need a score and a rationale per alternative. "
             "The first measurement freezes the criteria.",
             StudyEvaluateArgs, ann(False, False, True), lambda s, a: S(s).evaluate(a.id, [_dump(m) for m in a.manual_scores], a.remeasure), timeout_s=300),
        Tool("design_alternatives_criteria",
             "Replace criteria before measuring, or open a new study revision after. Cambiar criterios (congelados).\n"
             "Frozen once measured: new_revision=true with a reason keeps the old revision and carries over unchanged measures.",
             StudyCriteriaArgs, ann(False, False, True), lambda s, a: S(s).set_criteria(a.id, [_dump(c) for c in a.criteria], a.new_revision, a.reason)),
        Tool("design_alternatives_analyze",
             "Rank, Pareto frontier, trade-off text; try other weights without measuring again. Analizar compromisos.\n"
             "weights = what-if by criterion id (not saved); sensitivity_of = share of weight at which the leader changes.",
             StudyAnalyzeArgs, ann(True), lambda s, a: S(s).analyze(a.id, a.weights, a.sensitivity_of)),
        Tool("design_alternatives_decide",
             "Record the chosen alternative with its reason and the trade-offs it accepts. Decidir alternativa.\n"
             "A dominated alternative is refused unless accept_dominated=true and the reason says what the criteria miss.",
             StudyDecideArgs, ann(False, False, True), lambda s, a: S(s).decide(a.id, a.alternative_id, a.reason, a.weights, a.accept_dominated)),
        Tool("instrument_create",
             "Generate a calculator, viewer, comparator or editor from a typed spec. Crear instrumento.\n"
             "Source kept, tests generated (validation + your examples), stdlib-only standalone export, explainer page. Spec examples the formulas do not satisfy are reported.\n"
             "Sinónimos: calculadora, herramienta pequeña, comparador, visor, editor, fórmula, unidades.",
             InstrumentCreateArgs, ann(False, False, True), lambda s, a: I(s).create(a.spec)),
        Tool("instrument_list", "List instruments with their spec and example status. Listar instrumentos.",
             Empty, ann(True), lambda s, a: {"instruments": I(s).list()}),
        Tool("instrument_get", "Read an instrument: spec, examples status and files. Leer instrumento.",
             InstrumentIdArgs, ann(True), lambda s, a: I(s).get(a.id, a.revision, a.include_files), capped=False),
        Tool("instrument_update", "Regenerate an instrument from a changed spec as a new retained revision. Actualizar instrumento.",
             InstrumentUpdateArgs, ann(False, False, True), lambda s, a: I(s).update(a.id, a.spec)),
        Tool("instrument_compute", "Compute an instrument's steps and outputs for given inputs. Calcular con un instrumento.",
             InstrumentComputeArgs, ann(True), lambda s, a: I(s).compute(a.id, a.inputs, a.revision)),
        Tool("instrument_explain",
             "Explain a result: inputs, intermediate states, outputs, formulas, invariants. Explicar resultado.\n"
             "Same computation as the instrument; the instrument serves it at /explain with editable inputs.",
             InstrumentExplainArgs, ann(True), lambda s, a: I(s).explain(a.id, a.inputs, a.revision)),
        Tool("instrument_check",
             "Run the exported instrument and compare it with the spec and the explainer. Comprobar instrumento.\n"
             "Extracts the export, runs its tests and server, recomputes every spec example over HTTP and checks the explainer shows the same numbers.",
             InstrumentCheckArgs, ann(False, False, True), lambda s, a: I(s).check(a.id, a.revision, a.inputs), timeout_s=120),
        Tool("instrument_export", "Export an instrument as a standalone ZIP, checked by running it. Exportar instrumento.",
             InstrumentExportArgs, ann(False, False, True), lambda s, a: I(s).export(a.id, a.revision, a.run_check), timeout_s=120),
    ]
