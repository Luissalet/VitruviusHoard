"""/api/slop-audit*, /api/direction-brief, /api/presets*, /api/design/registry*, /api/figma*.

The handlers run the same functions as the agent tools (design_slop_audit, design_direction_brief, design_preset_list,
design_pick_themes, design_preset_apply, design_figma_import)."""

from __future__ import annotations

import base64
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .. import figma, i18n, presets, slop_audit
from .deps import services

router = APIRouter(prefix="/api")


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except PermissionError as error:
        raise HTTPException(400, str(error)) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


class AuditBody(BaseModel):
    render_id: Optional[str] = Field(None, max_length=40)
    html: Optional[str] = Field(None, max_length=2_000_000)
    url: Optional[str] = Field(None, max_length=2000)
    widths: Optional[list[int]] = None
    rerender: Optional[bool] = None
    title: str = Field("", max_length=200)
    lang: Optional[str] = Field(None, max_length=8)


def _lang(request: Request, lang: Optional[str] = None) -> str:
    """The language asked for: explicit ``lang``, else Accept-Language, else Spanish."""
    return i18n.norm_lang(lang, request.headers.get("accept-language"))


@router.post("/slop-audit")
def slop_audit_run(request: Request, body: AuditBody):
    return _run(slop_audit.run, services(request), render_id=body.render_id, html=body.html, url=body.url, widths=body.widths,
                rerender=body.rerender, title=body.title, lang=_lang(request, body.lang))


@router.get("/slop-audit")
def slop_audit_list(request: Request, limit: int = Query(20, ge=1, le=100)):
    return {"audits": slop_audit.latest(services(request), limit)}


@router.get("/slop-audit/{render_id}")
def slop_audit_get(request: Request, render_id: str, lang: Optional[str] = Query(None, max_length=8)):
    out = slop_audit.get(services(request), render_id, _lang(request, lang))
    if out is None:
        raise HTTPException(404, f"No slop audit for render '{render_id}'.")
    return out


class BriefBody(BaseModel):
    render_id: Optional[str] = Field(None, max_length=40)
    html: Optional[str] = Field(None, max_length=2_000_000)
    url: Optional[str] = Field(None, max_length=2000)
    text: Optional[str] = Field(None, max_length=20000)
    use_model: bool = True
    lang: Optional[str] = Field(None, max_length=8)


@router.post("/direction-brief")
def direction_brief(request: Request, body: BriefBody):
    return _run(slop_audit.direction_brief, services(request), render_id=body.render_id, html=body.html, url=body.url, text=body.text,
                use_model=body.use_model, lang=_lang(request, body.lang))


# ---------------- presets and the registry ----------------

@router.get("/presets")
def presets_list(request: Request, source: Optional[str] = Query(None, pattern="^(vitruvius|flexoki|hallmark|hoard)$"),
                 q: Optional[str] = Query(None, max_length=120), limit: int = Query(200, ge=1, le=400)):
    rows = presets.listing(source=source, query=q, limit=limit)
    return {"count": len(rows), "total": len(presets.catalogue()), "presets": rows}


@router.get("/presets/{name}")
def presets_get(request: Request, name: str):
    p = presets.get(name)
    if p is None:
        raise HTTPException(404, f"Unknown preset '{name}'.")
    return {"preset": p, "registry_item": presets.registry_item(p)}


class PickBody(BaseModel):
    brief: str = Field(..., min_length=3, max_length=2000)
    n: int = Field(3, ge=1, le=6)
    use_model: bool = True


@router.post("/presets/pick")
def presets_pick(request: Request, body: PickBody):
    return _run(presets.pick, services(request), body.brief, n=body.n, use_model=body.use_model)


class ApplyBody(BaseModel):
    preset: str = Field(..., max_length=80)
    tokens_id: Optional[str] = Field(None, max_length=40)
    parts: Optional[list[Literal["colors", "radius", "type", "spacing", "motion"]]] = None
    name: Optional[str] = Field(None, max_length=120)


@router.post("/presets/apply")
def presets_apply(request: Request, body: ApplyBody):
    return _run(presets.apply, services(request), body.preset, tokens_id=body.tokens_id, parts=list(body.parts) if body.parts else None,
                title=body.name)


@router.get("/design/registry.json")
def registry_index(request: Request):
    return JSONResponse(presets.registry_index(str(request.base_url).rstrip("/")))


@router.get("/design/registry/{name}.json")
def registry_item(request: Request, name: str):
    p = presets.get(name)
    if p is None:
        raise HTTPException(404, f"Unknown registry item '{name}'.")
    return JSONResponse(presets.registry_item(p))


# ---------------- Figma ----------------

class FigmaBody(BaseModel):
    link: Optional[str] = Field(None, max_length=2000)
    nodes_json: Optional[dict[str, Any]] = None
    image_base64: Optional[str] = Field(None, max_length=20_000_000)
    make_tokens: bool = True
    critique: bool = True


@router.post("/figma/import")
def figma_import(request: Request, body: FigmaBody):
    if not body.link and not body.nodes_json:
        raise HTTPException(400, "link or nodes_json is required")
    svc = services(request)
    if not body.nodes_json and not figma.read_token(svc.config.data_dir):
        raise HTTPException(400, figma.TOKEN_HELP)
    png = base64.b64decode(body.image_base64) if body.image_base64 else None
    return _run(figma.import_frame, svc, link=body.link, nodes_json=body.nodes_json, image_png=png, make_tokens=body.make_tokens,
                critique=body.critique)


@router.get("/figma/imports")
def figma_imports(request: Request, limit: int = Query(30, ge=1, le=200)):
    svc = services(request)
    return {"imports": figma.imports(svc.config.data_dir, limit), "token_set": bool(figma.read_token(svc.config.data_dir)), "help": figma.TOKEN_HELP}


@router.get("/figma/imports/{import_id}/{name}")
def figma_file(request: Request, import_id: str, name: str):
    try:
        path = figma.import_file(services(request).config.data_dir, import_id, name)
    except PermissionError as error:
        raise HTTPException(404, str(error)) from error
    if not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path)
