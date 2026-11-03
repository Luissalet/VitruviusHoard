"""/api/protocols/*: the bounded protocol checker, for the Protocols screen. Same handlers as the `protocol_check` tool."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..agent_tools import ProtocolArgs, run_protocol_check
from .deps import services

router = APIRouter(prefix="/api/protocols")


def _run(request: Request, **kw):
    try:
        return run_protocol_check(services(request), ProtocolArgs(**kw))
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/examples")
def examples(request: Request):
    return _run(request, action="examples")


@router.get("/examples/{example}")
def example(request: Request, example: str):
    return _run(request, action="example", example=example)


class CheckBody(BaseModel):
    spec: dict[str, Any]
    time_limit: float = Field(60, gt=0, le=3600)


@router.post("/check")
def check(request: Request, body: CheckBody):
    return _run(request, action="check", spec=body.spec, time_limit=body.time_limit)


class ReplayBody(BaseModel):
    spec: dict[str, Any]
    schedule: list[list[Any]]


@router.post("/replay")
def replay(request: Request, body: ReplayBody):
    return _run(request, action="replay", spec=body.spec, schedule=body.schedule)


class TestBody(BaseModel):
    spec: dict[str, Any]
    time_limit: float = Field(60, gt=0, le=3600)
    filename: Optional[str] = None


@router.post("/test.py")
def test_file(request: Request, body: TestBody):
    out = _run(request, action="test", spec=body.spec, time_limit=body.time_limit)
    name = body.filename or "test_contraejemplo.py"
    return Response(out["code"], media_type="text/x-python; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
