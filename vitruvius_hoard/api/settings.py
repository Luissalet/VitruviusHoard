"""/api/settings."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .deps import services

router = APIRouter(prefix="/api")


class SettingsBody(BaseModel):
    backend: Optional[dict[str, Any]] = None
    vision_enabled: Optional[bool] = None
    widths: Optional[list[int]] = None
    video_enabled: Optional[bool] = None
    language: Optional[str] = None
    figma_token: Optional[str] = Field(None, max_length=400, description="Figma personal access token; empty string removes it.")


@router.get("/settings")
def settings_get(request: Request):
    return services(request).get_settings()


@router.put("/settings")
def settings_put(request: Request, body: SettingsBody):
    patch = body.model_dump(exclude_none=True)
    return services(request).update_settings(patch)
