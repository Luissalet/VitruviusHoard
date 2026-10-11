"""/api/diagrams*: the diagram tools over HTTP for the interface, and the saved SVG files."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..diagrams import DiagramStore
from ..diagrams.tools import (BrandNameArgs, BrandOnboardArgs, DiagramIdArgs, DiagramListArgs, DiagramRenderArgs,
                              DiagramTypesArgs, run_brand_delete, run_brand_onboard, run_brands, run_diagram_delete,
                              run_diagram_get, run_diagram_list, run_diagram_render, run_diagram_types)
from .deps import services as _services


def services(request: Request):
    return _services(request)


def _found(fn, *args):
    try:
        return fn(*args)
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

router = APIRouter(prefix="/api")


@router.get("/diagrams/types")
def diagram_types(request: Request, intent: str = "", type: str = ""):
    return run_diagram_types(services(request), DiagramTypesArgs(intent=intent, type=type))


@router.get("/diagrams")
def diagrams_list(request: Request, limit: int = 30):
    return run_diagram_list(services(request), DiagramListArgs(limit=limit))


@router.post("/diagrams", status_code=201)
def diagrams_create(request: Request, body: DiagramRenderArgs):
    return run_diagram_render(services(request), body)


@router.get("/diagrams/brands")
def brands(request: Request):
    return run_brands(services(request), None)


@router.post("/diagrams/brands", status_code=201)
def brand_onboard(request: Request, body: BrandOnboardArgs):
    return run_brand_onboard(services(request), body)


@router.delete("/diagrams/brands/{name}")
def brand_delete(request: Request, name: str):
    return _found(lambda: run_brand_delete(services(request), BrandNameArgs(name=name)))


@router.get("/diagrams/{diagram_id}")
def diagrams_get(request: Request, diagram_id: str, svg: bool = False):
    return _found(lambda: run_diagram_get(services(request), DiagramIdArgs(id=diagram_id, include_svg=svg)))


@router.delete("/diagrams/{diagram_id}")
def diagrams_delete(request: Request, diagram_id: str) -> dict[str, Any]:
    return _found(lambda: run_diagram_delete(services(request), DiagramIdArgs(id=diagram_id)))


@router.get("/diagrams/{diagram_id}/{mode}.svg")
def diagrams_file(request: Request, diagram_id: str, mode: str):
    path = _found(lambda: DiagramStore(services(request).config.data_dir).svg_path(diagram_id, mode))
    return FileResponse(path, media_type="image/svg+xml")
