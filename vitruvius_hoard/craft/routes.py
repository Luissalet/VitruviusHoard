"""REST and bundled pages for the craft library and the web guides (cold: no engine, no data store)."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from .. import webguide
from ..webguide import legacy
from . import ROOT, dashboard, heroes, page, pages, read, scenes, search, ui_sets

router = APIRouter()


class ScanBody(BaseModel):
    path: str | None = Field(None, max_length=1000)
    sources: list[dict] | None = None
    include_vendor: bool = False
    max_files: int = Field(600, ge=1, le=5000)


def _html(doc: dict) -> HTMLResponse:
    return HTMLResponse(doc["html"])


@router.get("/api/craft")
def craft_search(query: str = Query("", max_length=300), kind: str | None = Query(None, max_length=30), limit: int = Query(10, ge=1, le=60)):
    try:
        return search(query, kind, limit)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/api/craft/{kind}/{item_id:path}/page")
def craft_page(kind: str, item_id: str):
    try:
        return _html(page(kind, item_id))
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/api/craft/{kind}/{item_id:path}")
def craft_read(kind: str, item_id: str):
    try:
        return read(kind, item_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/api/webguide")
def guide_search(query: str = Query("", max_length=300), category: str | None = Query(None, max_length=40), limit: int = Query(8, ge=1, le=50)):
    return webguide.search(query, category, limit) if query else webguide.listing(category)


@router.get("/api/webguide/legacy-rules")
def guide_rules():
    return {"rules": legacy.rules()}


@router.get("/api/webguide/{guide_id}")
def guide_read(guide_id: str):
    try:
        return webguide.read(guide_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/api/webguide/scan")
def guide_scan(body: ScanBody):
    try:
        if body.sources:
            return legacy.scan_sources(body.sources)
        if not body.path:
            raise HTTPException(400, "Give a path or inline sources")
        return legacy.scan_path(body.path, max_files=body.max_files, include_vendor=body.include_vendor)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/craft/")
def home():
    return FileResponse(ROOT / "library.html")


@router.get("/craft/scenes.js")
def scenes_js():
    return Response((ROOT / "scenes.js").read_bytes(), media_type="text/javascript")


@router.get("/craft/textures/")
def textures():
    return _html(pages.textures_page())


@router.get("/craft/heroes/{hero_id}/index.html")
def hero(hero_id: str):
    try:
        return _html(heroes.page(hero_id))
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/craft/scenes/{scene_id}/index.html")
def scene(scene_id: str):
    try:
        return _html(scenes.page(scene_id))
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/craft/dashboard/index.html")
def calm_dashboard():
    return _html(dashboard.calm_dashboard())


@router.get("/craft/ui-sets/")
def ui_sets_board():
    return _html(ui_sets.board_page())


@router.get("/craft/ui-sets/{set_id}/index.html")
def ui_set_board(set_id: str):
    try:
        return _html(ui_sets.set_page(set_id))
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/craft/ui-sets/{set_id}/{control_id}/index.html")
def ui_set_control(set_id: str, control_id: str):
    try:
        return _html(ui_sets.control_page(set_id, control_id))
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/craft/ui-sets/{set_id}/{filename}")
def ui_set_file(set_id: str, filename: str):
    try:
        data = ui_sets.asset(set_id, filename)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return Response(data, media_type="text/plain; charset=utf-8" if filename == "LICENSE" else "text/javascript")
