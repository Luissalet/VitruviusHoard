"""/api/tokens*."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from .deps import services

router = APIRouter(prefix="/api")


class TokensBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    base_color: Optional[str] = None
    hue: Optional[float] = None
    style: Optional[str] = None
    vibe: Optional[str] = None
    mode: str = "both"
    knobs: Optional[dict[str, Any]] = None
    fonts: Optional[dict[str, str]] = None
    radius: Optional[str] = None
    density: Optional[str] = None


@router.get("/tokens")
def tokens_list(request: Request, limit: int = Query(30, ge=1, le=200)):
    rows = services(request).tokens_list(limit=limit)
    return {"design_systems": [{k: v for k, v in r.items() if k != "tokens"} for r in rows]}


@router.post("/tokens", status_code=201)
def tokens_create(request: Request, body: TokensBody):
    brief = {k: v for k, v in body.model_dump().items() if v is not None}
    if body.knobs:
        brief.update(body.knobs)
    return services(request).tokens_generate(brief)


@router.get("/tokens/{tokens_id}")
def tokens_get(request: Request, tokens_id: str):
    row = services(request).tokens_get(tokens_id)
    if row is None:
        raise HTTPException(404, f"Unknown design system '{tokens_id}'.")
    return row


@router.delete("/tokens/{tokens_id}")
def tokens_delete(request: Request, tokens_id: str):
    if not services(request).tokens_delete(tokens_id):
        raise HTTPException(404, f"Unknown design system '{tokens_id}'.")
    return {"ok": True}


@router.get("/tokens/{tokens_id}/export")
def tokens_export(request: Request, tokens_id: str, format: str = Query("json", pattern="^(json|css|tailwind|w3c)$")):
    try:
        content = services(request).tokens_export(tokens_id, format)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    if format in ("css", "tailwind"):
        return Response(content=content, media_type="text/css")
    return {"format": format, "content": content}


class PreviewBody(BaseModel):
    dark: bool = False


@router.post("/tokens/{tokens_id}/preview")
def tokens_preview(request: Request, tokens_id: str, body: PreviewBody):
    try:
        row = services(request).tokens_preview(tokens_id, dark=body.dark)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return {k: v for k, v in row.items() if not k.startswith("_")}


@router.get("/tokens/{tokens_id}/playground")
def tokens_playground(request: Request, tokens_id: str, dark: bool = False):
    try:
        html = services(request).tokens_playground_html(tokens_id, dark=dark)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return Response(content=html, media_type="text/html")
