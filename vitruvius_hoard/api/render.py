"""/api/renders*, /api/lint."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .deps import services

router = APIRouter(prefix="/api")


class RenderBody(BaseModel):
    html: Optional[str] = None
    url: Optional[str] = None
    widths: list[int] = Field(default_factory=lambda: [390, 1024, 1440])
    full_page: bool = True
    dark: bool = False
    wait_ms: int = 800
    lint: bool = True
    title: str = ""


def _strip(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}


@router.get("/renders")
def renders_list(request: Request, limit: int = Query(30, ge=1, le=200)):
    return {"renders": services(request).list_renders(limit=limit)}


@router.post("/renders", status_code=201)
def renders_create(request: Request, body: RenderBody):
    if not body.html and not body.url:
        raise HTTPException(400, "html or url is required")
    row = services(request).render(**body.model_dump())
    return _strip(row)


@router.get("/renders/{render_id}")
def renders_get(request: Request, render_id: str):
    row = services(request).get_render(render_id)
    if row is None:
        raise HTTPException(404, f"Unknown render '{render_id}'.")
    return row


@router.get("/renders/{render_id}/files/{name:path}")
def renders_file(request: Request, render_id: str, name: str):
    try:
        path = services(request).render_file_path(render_id, name)
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error
    if not path.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(path)


class CritiqueBody(BaseModel):
    focus: Optional[str] = None
    use_vision: bool = True


@router.post("/renders/{render_id}/critique")
def renders_critique(request: Request, render_id: str, body: CritiqueBody):
    try:
        return services(request).critique_render(render_id, focus=body.focus, use_vision=body.use_vision)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


class LintBody(BaseModel):
    html: Optional[str] = None
    url: Optional[str] = None
    render_id: Optional[str] = None


@router.post("/lint")
def lint_route(request: Request, body: LintBody):
    if not body.html and not body.url and not body.render_id:
        raise HTTPException(400, "html, url or render_id is required")
    try:
        return services(request).lint_html(html=body.html, url=body.url, render_id=body.render_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


class CompareBody(BaseModel):
    render_a: str
    render_b: str
    width: Optional[int] = None


@router.post("/renders/compare")
def renders_compare(request: Request, body: CompareBody):
    try:
        return services(request).render_compare(body.render_a, body.render_b, width=body.width)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
