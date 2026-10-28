"""Human UI and agent use the same validated motion handlers."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from ..agent_tools import MotionSaveArgs, MotionRenderArgs, MotionSoundArgs, run_motion_save, run_motion_render, run_motion_sound_plan, run_motion_sound_render
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


@router.get("/sound/status")
def sound_status():
    from .. import sound
    return sound.status()


@router.post("/sound/plan")
def sound_plan(request: Request, body: MotionSoundArgs):
    try:
        return run_motion_sound_plan(services(request), body)
    except (ValueError, LookupError) as error:
        raise HTTPException(400, str(error)) from error


@router.post("/sound/render")
def sound_render(request: Request, body: MotionSoundArgs):
    try:
        out = run_motion_sound_render(services(request), body)
    except (ValueError, LookupError) as error:
        raise HTTPException(400, str(error)) from error
    if out.get("available") is False:
        raise HTTPException(503, out["hint"])
    return out


@router.get("/{id}")
def get(request: Request, id: str, revision: int | None = None):
    return MotionStore(services(request).config.data_dir).get(id, revision)
