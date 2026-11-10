"""/api/parity*: visual parity of a candidate page against a reference. Same handlers as the `visual_parity*` tools."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

from ..parity_tools import VisualParityArgs, run_visual_parity
from .deps import services

router = APIRouter(prefix="/api/parity")


@router.post("", status_code=201)
def parity_create(request: Request, body: VisualParityArgs):
    try:
        return run_visual_parity(services(request), body)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("")
def parity_list(request: Request, limit: int = Query(20, ge=1, le=200)):
    return {"runs": services(request).parity_list(limit)}


@router.get("/{run_id}")
def parity_get(request: Request, run_id: str):
    try:
        return services(request).parity_get(run_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.delete("/{run_id}")
def parity_delete(request: Request, run_id: str):
    try:
        return services(request).parity_delete(run_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/{run_id}/report")
def parity_report(request: Request, run_id: str):
    """The side-by-side test page with the slider. It reads its images from `files/` next to it."""
    try:
        path = services(request).parity_file_path(run_id, "compare.html")
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    if not path.is_file():
        raise HTTPException(404, "report not found")
    return HTMLResponse(path.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/{run_id}/files/{name:path}")
def parity_file(request: Request, run_id: str, name: str):
    try:
        path = services(request).parity_file_path(run_id, name)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error
    if not path.is_file() or path.suffix.lower() != ".png":
        raise HTTPException(404, "file not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})
