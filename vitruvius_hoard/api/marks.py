"""/api/marks*: the logo (mark) audit and its test sheet, for the Marks screen. Same handlers as the `mark_*` tools."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .. import mark_audit
from ..agent_tools import MarkAuditArgs, MarkReportsArgs, MarkSheetArgs, run_mark_audit, run_mark_reports, run_mark_test_sheet
from .deps import services

router = APIRouter(prefix="/api/marks")


@router.post("/audit")
def audit(request: Request, body: MarkAuditArgs):
    try:
        return run_mark_audit(services(request), body)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.post("/sheet")
def sheet(request: Request, body: MarkSheetArgs):
    try:
        return run_mark_test_sheet(services(request), body)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("")
def reports(request: Request, limit: int = 20):
    return run_mark_reports(services(request), MarkReportsArgs(limit=max(1, min(limit, 100))))


@router.get("/{mark_id}")
def report(request: Request, mark_id: str):
    try:
        return mark_audit.get_report(services(request).config.data_dir, mark_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/{mark_id}/{which}.png")
def picture(request: Request, mark_id: str, which: str):
    try:
        file = mark_audit.file_path(services(request).config.data_dir, mark_id, which)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return FileResponse(file, media_type="image/png", headers={"Cache-Control": "no-store"})
