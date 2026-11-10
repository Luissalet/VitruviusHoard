"""/api/remake*: "Rehacer", a reference page remade round by round until visual parity. Same handlers as the `remake_*` tools."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from ..remake_tools import RemakeContinueArgs, RemakeStartArgs, run_remake_start
from .deps import services

router = APIRouter(prefix="/api/remake")


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.post("", status_code=201)
def remake_start(request: Request, body: RemakeStartArgs):
    return _guard(run_remake_start, services(request), body)


@router.get("")
def remake_list(request: Request, limit: int = Query(20, ge=1, le=200)):
    return {"remakes": services(request).remake.list(limit)}


@router.get("/{remake_id}")
def remake_get(request: Request, remake_id: str):
    return _guard(services(request).remake.get, remake_id)


@router.post("/{remake_id}/continue")
def remake_continue(request: Request, remake_id: str, body: RemakeContinueArgs):
    return _guard(services(request).remake.continue_, remake_id, rounds=body.rounds, note=body.note, wait_s=body.wait_s)


@router.post("/{remake_id}/stop")
def remake_stop(request: Request, remake_id: str):
    return _guard(services(request).remake.stop, remake_id)


@router.delete("/{remake_id}")
def remake_delete(request: Request, remake_id: str):
    return _guard(services(request).remake.delete, remake_id)


@router.get("/{remake_id}/code")
def remake_code(request: Request, remake_id: str, path: str = Query("index.html", max_length=400),
                max_chars: int = Query(200000, ge=1000, le=2000000)):
    return _guard(services(request).remake.code, remake_id, path, max_chars)


@router.get("/{remake_id}/report")
def remake_report(request: Request, remake_id: str):
    return HTMLResponse(_guard(services(request).remake.report_html, remake_id), headers={"Cache-Control": "no-store"})


@router.get("/{remake_id}/download")
def remake_download(request: Request, remake_id: str):
    name, data = _guard(services(request).remake.zip_bytes, remake_id)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/{remake_id}/site/{name:path}")
def remake_site(request: Request, remake_id: str, name: str):
    """The result as a web site (relative addresses work). Open it in a sandboxed frame: its scripts, when kept, are the original's."""
    path = _guard(services(request).remake.site_file, remake_id, name or "index.html")
    if not path.is_file():
        raise HTTPException(404, "file not found")
    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=kind, headers={"Cache-Control": "no-store"})
