"""/api/references*."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .deps import services

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
                    vibe: Optional[str] = None, lib: Optional[str] = None, limit: int = Query(12, ge=1, le=100)):
    tag_list = [t for t in (tags or "").split(",") if t] or None
    items = services(request).reference_search(query=query, tags=tag_list, vibe=vibe, lib=lib, limit=limit)
    return {"count": len(items), "references": items}


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
