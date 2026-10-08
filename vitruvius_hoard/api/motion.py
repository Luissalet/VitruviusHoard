"""Human UI and agent use the same validated motion handlers."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from ..agent_tools import MotionSaveArgs, MotionRenderArgs, run_motion_save, run_motion_render
from ..motion import Composition, MotionStore, templates, page
from .deps import services

router = APIRouter(prefix="/api/motions")


@router.get("/templates")
def recipes():
    return {"templates": templates()}


@router.get("")
def list_motions(request: Request):
    return {"compositions": MotionStore(services(request).config.data_dir).list()}


@router.post("/preview")
def preview(body: Composition):
    return HTMLResponse(page(body, at=min(0.8, body.scenes[0].duration / 2)))


@router.post("")
def save(request: Request, body: MotionSaveArgs):
    return run_motion_save(services(request), body)


@router.post("/render")
def render(request: Request, body: MotionRenderArgs):
    return run_motion_render(services(request), body)


@router.get("/{id}")
def get(request: Request, id: str, revision: int | None = None):
    return MotionStore(services(request).config.data_dir).get(id, revision)
