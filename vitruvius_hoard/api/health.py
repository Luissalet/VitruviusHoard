"""/api/status (the shared `health_router` serves /api/health; its extra block is `health_extra`)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from .deps import services
from ..ingest.git import git_available
from ..services import ffmpeg_available

router = APIRouter(prefix="/api")


@router.get("/status")
def status(request: Request):
    return services(request).status()


def health_extra(request: Request) -> dict:
    """What /api/health adds to the shared answer. Cheap on purpose: the launcher, the hub and the MCP bridge poll it. Model
    resolution (network probes) lives in /api/status."""
    svc = services(request)
    return {"dataDirConfigured": request.app.state.config.data_dir_configured, "browser": svc.browser_status(),
            "ffmpeg": ffmpeg_available(), "git": git_available(), "counts": svc.counts()}
