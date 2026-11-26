"""Browser relay for the Applications page hosting the preview iframe."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .deps import services

router = APIRouter(prefix="/api/app-projects/{id}/canvas")


def _require_same_origin_page(request: Request):
    site = request.headers.get("sec-fetch-site")
    origin = request.headers.get("origin")
    expected_origin = f"{request.url.scheme}://{request.url.netloc}"
    if site not in (None, "same-origin") or (origin and origin != expected_origin):
        raise HTTPException(403, "The canvas relay belongs to the Applications page")


class CanvasResult(BaseModel):
    session: str = Field(pattern=r"^[a-f0-9]{32}$")
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    ok: bool
    result: Any = None
    error: dict | None = None


@router.get("/events")
async def canvas_events(request: Request, id: str):
    _require_same_origin_page(request)
    projects = services(request).app_projects
    if projects.status(id)["state"] != "running":
        raise HTTPException(404, "No running preview")

    async def stream():
        session = projects.canvas.attach(id)
        try:
            if projects.status(id)["state"] != "running":
                return
            yield f"event: ready\ndata: {json.dumps(session.id)}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(session.events.get(), 10)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if event is None:
                    break
                yield f"event: call\ndata: {json.dumps(event)}\n\n"
        finally:
            projects.canvas.detach(session)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/result", status_code=204)
def canvas_result(request: Request, id: str, body: CanvasResult):
    _require_same_origin_page(request)
    result = {"ok": body.ok, "result" if body.ok else "error": body.result if body.ok else body.error}
    if not services(request).app_projects.canvas.resolve(id, body.session, body.id, result):
        raise HTTPException(404, "Canvas call is no longer pending")
