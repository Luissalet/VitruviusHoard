"""Native application projects and owned local previews."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .deps import services
from ..agent_tools import AppCreateArgs, AppUpdateArgs, AppPreviewArgs, AppExportArgs, AppRenderArgs, AppCallArgs
from ..app_projects import templates

router = APIRouter(prefix="/api/app-projects")


def execute(operation):
    try:
        return operation()
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error


@router.get("/templates")
def template_list():
    return {"templates": templates()}


@router.get("")
def project_list(request: Request):
    return {"projects": services(request).app_projects.list()}


@router.post("", status_code=201)
def project_create(request: Request, body: AppCreateArgs):
    return execute(lambda: services(request).app_projects.create(**body.model_dump()))


@router.get("/{id}")
def project_get(request: Request, id: str, revision: str | None = None):
    return execute(lambda: services(request).app_projects.get(id, revision))


@router.put("/{id}")
def project_update(request: Request, id: str, body: AppUpdateArgs):
    return execute(lambda: services(request).app_projects.update(id, body.files, body.expected_revision))


@router.post("/{id}/preview")
def project_preview(request: Request, id: str, body: AppPreviewArgs):
    return execute(lambda: services(request).app_projects.stop(id) if body.operation == "stop" else services(request).app_projects.preview(id, body.revision))


@router.post("/{id}/export")
def project_export(request: Request, id: str, body: AppExportArgs):
    result = execute(lambda: services(request).app_projects.export(id, body.revision, body.include_data))
    from pathlib import Path
    result["download_url"] = f'/api/app-projects/{id}/exports/{Path(result["path"]).name}'
    return result


@router.get("/{id}/exports/{filename}")
def project_bundle(request: Request, id: str, filename: str):
    import re
    if not re.fullmatch(r"[a-f0-9]{32}\.zip", filename):
        raise HTTPException(404, "Bundle not found")
    root = execute(lambda: services(request).app_projects._directory(id))
    path = root / "exports" / filename
    if not path.is_file():
        raise HTTPException(404, "Bundle not found")
    return FileResponse(path, media_type="application/zip", filename="application.zip")


@router.post("/{id}/render")
def project_render(request: Request, id: str, body: AppRenderArgs):
    return execute(lambda: services(request).app_project_render(id, body.revision, body.widths))


@router.post("/{id}/call")
def project_call(request: Request, id: str, body: AppCallArgs):
    return execute(lambda: services(request).app_project_call(id, body.operation, body.data, body.record_id, body.query))
