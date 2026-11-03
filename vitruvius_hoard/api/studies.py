"""REST for design alternatives studies and the instrument factory (the same operations as the agent tools)."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import create_model

from .deps import services
from ..study_tools import (InstrumentCheckArgs, InstrumentComputeArgs, InstrumentCreateArgs, InstrumentExplainArgs, InstrumentExportArgs,
                           InstrumentUpdateArgs, StudyAddArgs, StudyAnalyzeArgs, StudyCreateArgs, StudyCriteriaArgs, StudyDecideArgs, StudyEvaluateArgs, _dump)

router = APIRouter(prefix="/api")


def _body(model):
    """The tool's arguments without the id, which the URL already carries."""
    return create_model(model.__name__ + "Body", **{n: (f.annotation, f) for n, f in model.model_fields.items() if n != "id"})


StudyAddBody, StudyEvaluateBody, StudyCriteriaBody, StudyAnalyzeBody, StudyDecideBody = (_body(m) for m in (StudyAddArgs, StudyEvaluateArgs, StudyCriteriaArgs, StudyAnalyzeArgs, StudyDecideArgs))
InstrumentUpdateBody, InstrumentComputeBody, InstrumentExplainBody, InstrumentCheckBody, InstrumentExportBody = (_body(m) for m in (InstrumentUpdateArgs, InstrumentComputeArgs, InstrumentExplainArgs, InstrumentCheckArgs, InstrumentExportArgs))


def execute(operation):
    try:
        return operation()
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error


# ---------------- design alternatives ----------------
@router.get("/design-alternatives")
def studies_list(request: Request):
    return {"studies": services(request).alternatives.list()}


@router.post("/design-alternatives", status_code=201)
def studies_create(body: StudyCreateArgs, request: Request):
    return execute(lambda: services(request).alternatives.create(body.brief, [_dump(c) for c in body.criteria], [_dump(a) for a in body.alternatives], body.diversity_threshold, body.check_only))


@router.get("/design-alternatives/{id}")
def studies_get(id: str, request: Request):
    return execute(lambda: services(request).alternatives.get(id))


@router.post("/design-alternatives/{id}/alternatives", status_code=201)
def studies_add(id: str, body: StudyAddBody, request: Request):
    return execute(lambda: services(request).alternatives.add_alternative(id, body.alternative))


@router.post("/design-alternatives/{id}/evaluate")
def studies_evaluate(id: str, body: StudyEvaluateBody, request: Request):
    return execute(lambda: services(request).alternatives.evaluate(id, [_dump(m) for m in body.manual_scores], body.remeasure))


@router.put("/design-alternatives/{id}/criteria")
def studies_criteria(id: str, body: StudyCriteriaBody, request: Request):
    return execute(lambda: services(request).alternatives.set_criteria(id, [_dump(c) for c in body.criteria], body.new_revision, body.reason))


@router.post("/design-alternatives/{id}/analyze")
def studies_analyze(id: str, body: StudyAnalyzeBody, request: Request):
    return execute(lambda: services(request).alternatives.analyze(id, body.weights, body.sensitivity_of))


@router.post("/design-alternatives/{id}/decision")
def studies_decide(id: str, body: StudyDecideBody, request: Request):
    return execute(lambda: services(request).alternatives.decide(id, body.alternative_id, body.reason, body.weights, body.accept_dominated))


# ---------------- instruments ----------------
@router.get("/instruments")
def instruments_list(request: Request):
    return {"instruments": services(request).instruments.list()}


@router.post("/instruments", status_code=201)
def instruments_create(body: InstrumentCreateArgs, request: Request):
    return execute(lambda: services(request).instruments.create(body.spec))


@router.get("/instruments/{id}")
def instruments_get(id: str, request: Request, revision: str | None = None, include_files: bool = False):
    return execute(lambda: services(request).instruments.get(id, revision, include_files))


@router.put("/instruments/{id}")
def instruments_update(id: str, body: InstrumentUpdateBody, request: Request):
    return execute(lambda: services(request).instruments.update(id, body.spec))


@router.post("/instruments/{id}/compute")
def instruments_compute(id: str, body: InstrumentComputeBody, request: Request):
    return execute(lambda: services(request).instruments.compute(id, body.inputs, body.revision))


@router.post("/instruments/{id}/explain")
def instruments_explain(id: str, body: InstrumentExplainBody, request: Request):
    return execute(lambda: services(request).instruments.explain(id, body.inputs, body.revision))


@router.post("/instruments/{id}/check")
def instruments_check(id: str, body: InstrumentCheckBody, request: Request):
    return execute(lambda: services(request).instruments.check(id, body.revision, body.inputs))


@router.post("/instruments/{id}/export")
def instruments_export(id: str, body: InstrumentExportBody, request: Request):
    result = execute(lambda: services(request).instruments.export(id, body.revision, body.run_check))
    result["download_url"] = f"/api/app-projects/{id}/exports/" + result["path"].replace("\\", "/").rsplit("/", 1)[-1]
    return result
