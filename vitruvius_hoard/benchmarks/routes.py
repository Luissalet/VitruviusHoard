"""REST entry points for the versioned reconstruction corpus."""

import json
from fastapi import APIRouter, Request
from fastapi.responses import Response
from ..api.deps import services
from ..api.remake import _guard
from .tools import Compare, Start

router = APIRouter(prefix="/api/benchmarks")


@router.get("/catalog")
def catalog(request: Request):
    return services(request).benchmarks.catalog()


@router.get("/runs")
def runs(request: Request):
    return services(request).benchmarks.list()


@router.post("/runs", status_code=201)
def start(request: Request, body: Start):
    return _guard(services(request).benchmarks.start, **body.model_dump())


@router.post("/compare")
def compare(request: Request, body: Compare):
    return _guard(services(request).benchmarks.compare, body.before, body.after)


@router.get("/runs/{run_id}")
def read(request: Request, run_id: str):
    return _guard(services(request).benchmarks.get, run_id)


@router.post("/runs/{run_id}/stop")
def stop(request: Request, run_id: str):
    return _guard(services(request).benchmarks.stop, run_id)


@router.post("/runs/{run_id}/resume")
def resume(request: Request, run_id: str):
    return _guard(services(request).benchmarks.resume, run_id)


@router.get("/runs/{run_id}/export")
def export(request: Request, run_id: str):
    result = _guard(services(request).benchmarks.get, run_id)
    return Response(
        json.dumps(result, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="evaluation-{run_id}.json"',
            "Cache-Control": "no-store",
        },
    )
