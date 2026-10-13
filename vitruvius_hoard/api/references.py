"""/api/references*."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .deps import services
from ..agent_tools import CollectionImportArgs, DesignPatternArgs

router = APIRouter(prefix="/api")


class ReferenceBody(BaseModel):
    url: Optional[str] = None
    html: Optional[str] = None
    tags: Optional[list[str]] = None
    note: str = ""
    video: bool = True
    analyze: bool = True


@router.get("/references")
def references_list(request: Request, query: Optional[str] = None, tags: Optional[str] = None,
                    vibe: Optional[str] = None, lib: Optional[str] = None, collection: Optional[str] = None, before: Optional[str] = None, limit: int = Query(12, ge=1, le=100)):
    tag_list = [t for t in (tags or "").split(",") if t] or None
    try:
        return services(request).reference_page(query=query, tags=tag_list, vibe=vibe, lib=lib, collection=collection, before=before, limit=limit)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.post("/references", status_code=201)
def references_add(request: Request, body: ReferenceBody):
    if not body.url and not body.html:
        raise HTTPException(400, "url or html is required")
    try:
        return services(request).reference_add(**body.model_dump())
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/references/{ref_id}")
def references_get(request: Request, ref_id: str):
    row = services(request).reference_get(ref_id)
    if row is None:
        raise HTTPException(404, f"Unknown reference '{ref_id}'.")
    return row


@router.delete("/references/{ref_id}")
def references_delete(request: Request, ref_id: str):
    if not services(request).reference_delete(ref_id):
        raise HTTPException(404, f"Unknown reference '{ref_id}'.")
    return {"ok": True}


@router.get("/references/{ref_id}/files/{name:path}")
def references_file(request: Request, ref_id: str, name: str):
    try:
        path = services(request).reference_file_path(ref_id, name)
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error
    if not path.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(path)


@router.get("/reference-collections")
def collection_list(request: Request):
    return {"collections": services(request).reference_collections()}


@router.post("/reference-collections/import")
def collection_import(request: Request, body: CollectionImportArgs):
    try:
        return services(request).reference_import_collection(body.path)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/design-patterns")
def pattern_list(request: Request):
    return {"patterns": services(request).design_patterns()}


@router.post("/design-patterns/generate")
def pattern_generate(request: Request, body: DesignPatternArgs):
    try:
        return services(request).design_pattern(**body.model_dump())
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
