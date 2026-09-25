"""/api/library/*, /api/catalog/*, /api/sources*."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .deps import services

router = APIRouter(prefix="/api")


@router.get("/library/search")
def library_search(request: Request, query: str = Query(..., min_length=1), kind: Optional[str] = None,
                   source: Optional[str] = None, area: Optional[str] = None, limit: int = Query(8, ge=1, le=50),
                   mode: str = Query("auto", pattern="^(auto|hybrid|bm25|dense)$")):
    svc = services(request)
    items = svc.library_search(query, kind=kind, source=source, area=area, limit=limit, mode=mode)
    return {"count": len(items), "items": items, "dense": svc.dense.usable()}


@router.get("/library/embeddings")
def embeddings_status(request: Request):
    return services(request).dense.status()


@router.post("/library/embeddings")
def embeddings_build(request: Request):
    return services(request).embeddings_build()


class BriefBody(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    vibe: Optional[str] = None
    product_type: Optional[str] = None
    platform: Optional[str] = None
    mode: str = "marketing"
    knobs: Optional[dict[str, Any]] = None
    use_model: bool = False


@router.post("/library/brief")
def library_brief(request: Request, body: BriefBody):
    return services(request).library_brief(**body.model_dump())


@router.get("/library/rules")
def library_rules(request: Request, area: Optional[str] = None, severity: Optional[str] = None,
                  source: Optional[str] = None, limit: int = Query(30, ge=1, le=200)):
    items = services(request).library_rules(area=area, severity=severity, source=source, limit=limit)
    return {"count": len(items), "rules": items}


@router.get("/catalog/styles")
def catalog_styles(request: Request, limit: int = Query(100, ge=1, le=500)):
    return {"styles": services(request).catalog_styles(limit=limit)}


@router.get("/catalog/palettes")
def catalog_palettes(request: Request, limit: int = Query(100, ge=1, le=500)):
    return {"palettes": services(request).catalog_palettes(limit=limit)}


@router.get("/catalog/fonts")
def catalog_fonts(request: Request, limit: int = Query(100, ge=1, le=500)):
    return {"fonts": services(request).catalog_fonts(limit=limit)}


class SourceAddBody(BaseModel):
    id: Optional[str] = None
    url: str = Field(..., min_length=1)
    kind: str = "git"
    license: str = ""
    category: str = ""
    paths: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    structured: bool = False


@router.get("/sources")
def sources_list(request: Request):
    return {"sources": services(request).sources_list()}


@router.post("/sources", status_code=201)
def sources_add(request: Request, body: SourceAddBody):
    source_id = body.id or body.url.rstrip("/").rsplit("/", 1)[-1].lower().replace(".git", "")
    return services(request).source_add(id=source_id, url=body.url, kind=body.kind, license=body.license,
                                        category=body.category, paths=body.paths, tags=body.tags,
                                        structured=body.structured)


@router.post("/sources/{source_id}/ingest")
def sources_ingest(request: Request, source_id: str):
    try:
        return services(request).source_ingest(source_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
