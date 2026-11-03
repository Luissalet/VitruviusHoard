"""/api/rules*, /api/themes*, /api/kept*: the rule registry, the theme dealer and the kept-element snapshots."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .deps import services

router = APIRouter(prefix="/api")


@router.get("/rules")
def rules_list(request: Request, engine: Optional[str] = None, scope: Optional[str] = None, severity: Optional[str] = None,
               tier: Optional[str] = None, pack: Optional[str] = None, source: Optional[str] = None, q: Optional[str] = Query(None, max_length=120),
               runnable: Optional[bool] = None, lang: Optional[str] = Query(None, max_length=8)):
    """``lang`` es|en: names, descriptions and fixes in that language (default: English, as stored)."""
    return services(request).rules_list(engine=engine, scope=scope, severity=severity, tier=tier, pack=pack, source=source, query=q, runnable=runnable,
                                        lang=lang)


@router.get("/rules/{rule_id:path}")
def rules_get(request: Request, rule_id: str, lang: Optional[str] = Query(None, max_length=8)):
    try:
        return services(request).rule_get(rule_id, lang)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/themes")
def themes_list(request: Request, genre: Optional[str] = None, q: Optional[str] = Query(None, max_length=120)):
    from .. import themes
    rows = [themes.public(t) for t in themes.load() if (not genre or t["genre"] == genre)
            and (not q or q.lower() in (t["slug"] + " " + t["name"] + " " + " ".join(t["keywords"]) + " " + t["material"]).lower())]
    return {"count": len(rows), "themes": rows}


@router.get("/themes/memory")
def themes_memory(request: Request, limit: int = Query(20, ge=1, le=100)):
    return {"memory": services(request).theme_memory(limit)}


class DealBody(BaseModel):
    prompt: str = Field("", max_length=600)
    genre: Optional[str] = None
    n: int = Field(3, ge=1, le=6)
    reroll: int = Field(0, ge=0, le=20)
    seed: Optional[str] = Field(None, max_length=200)


@router.post("/themes/deal")
def themes_deal(request: Request, body: DealBody):
    try:
        return services(request).theme_deal(**body.model_dump())
    except (ValueError, LookupError) as error:
        raise HTTPException(400, str(error)) from error


class CheckBody(BaseModel):
    axes: Optional[str] = None
    face: Optional[str] = None
    hue: Optional[float] = None


@router.post("/themes/check")
def themes_check(request: Request, body: CheckBody):
    try:
        return services(request).theme_check(**body.model_dump())
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/kept")
def kept_list(request: Request, limit: int = Query(30, ge=1, le=200)):
    return {"kept": services(request).kept_list(limit)}


@router.get("/kept/{kept_id}")
def kept_get(request: Request, kept_id: str):
    try:
        return services(request).kept_get(kept_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
