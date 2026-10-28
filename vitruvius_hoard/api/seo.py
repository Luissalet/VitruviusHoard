"""/api/site-audit*: the deterministic SEO and GEO audit, for the Audit screen. Same handlers as the `site_audit` tools."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..agent_tools import SiteAuditArgs, SiteAuditReportsArgs, run_site_audit, run_site_audit_reports
from .deps import services

router = APIRouter(prefix="/api/site-audit")


@router.post("")
def audit(request: Request, body: SiteAuditArgs):
    try:
        return run_site_audit(services(request), body)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/reports")
def reports(request: Request, url: str = "", limit: int = 20):
    try:
        return run_site_audit_reports(services(request), SiteAuditReportsArgs(url=url or None, limit=max(1, min(limit, 100))))
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/reports/{report_id}")
def report(request: Request, report_id: str):
    try:
        return run_site_audit_reports(services(request), SiteAuditReportsArgs(id=report_id))
    except Exception as error:  # noqa: BLE001 - the pydantic pattern and the store's not-found both become a 404
        raise HTTPException(404, "No hay un informe con ese id.") from error
