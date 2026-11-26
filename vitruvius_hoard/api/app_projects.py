"""Native application projects and owned local previews."""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .deps import services
from ..agent_tools import (
    AppCallArgs, AppCreateArgs, AppExportArgs, AppPreviewArgs, AppRenderArgs, AppSourceEditArgs, AppUpdateArgs,
)
from ..app_projects import templates
from ..preview_inspector import StaleSelection, inspector_script, read_selection, write_selection

router = APIRouter(prefix="/api/app-projects")


def execute(operation):
    try:
        return operation()
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except StaleSelection as error:
        raise HTTPException(409, str(error)) from error
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error


@router.get("/templates")
def template_list():
    return {"templates": templates()}


class SelectionBody(BaseModel):
    selection: list = []
    revision: str | None = None


@router.get("/preview-inspector.js")
def preview_inspector():
    return Response(inspector_script(), media_type="text/javascript", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/{id}/selection")
def selection_get(request: Request, id: str, revision: str | None = None):
    return execute(lambda: read_selection(services(request), id, revision))


@router.put("/{id}/selection")
def selection_put(request: Request, id: str, body: SelectionBody):
    return execute(lambda: write_selection(services(request), id, body.selection, body.revision))


@router.get("")
def project_list(request: Request):
    return {"projects": services(request).app_projects.list()}


@router.post("", status_code=201)
def project_create(request: Request, body: AppCreateArgs):
    return execute(lambda: services(request).app_projects.create(**body.model_dump()))


@router.get("/{id}")
def project_get(request: Request, id: str, revision: str | None = None):
    return execute(lambda: services(request).app_projects.get(id, revision))


def _encode_revision(change):
    return f'id: {change["revision"]}\nevent: revision\ndata: {json.dumps(change, separators=(",", ":"))}\n\n'


async def revision_stream(projects, id, baseline):
    with projects.revision_events.subscribe(id) as queue:
        try:
            cursor, latest, change = await run_in_threadpool(projects.revision_cursor, id, baseline)
            yield "retry: 500\n\n"
            if change:
                yield _encode_revision(change)
            # A bounded connection also lets the HTTP server drain during shutdown.
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 30
            while loop.time() < deadline:
                try:
                    notification = await asyncio.wait_for(queue.get(), min(10, deadline - loop.time()))
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if notification is None:
                    return
                sequence, change = notification
                if sequence <= cursor:
                    continue
                if change["previous_revision"] != latest:
                    # A lagging subscriber can catch up from the last snapshot it received.
                    cursor, latest, change = await run_in_threadpool(projects.revision_cursor, id, latest)
                    if change:
                        yield _encode_revision(change)
                    continue
                cursor, latest = sequence, change["revision"]
                yield _encode_revision(change)
        except LookupError:
            # Undoing creation archives the project and closes its stream.
            return


@router.get("/{id}/events")
def project_events(request: Request, id: str, revision: str | None = None):
    projects = services(request).app_projects
    execute(lambda: projects._directory(id))
    baseline = request.headers.get("last-event-id") or revision
    return StreamingResponse(revision_stream(projects, id, baseline), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.put("/{id}")
def project_update(request: Request, id: str, body: AppUpdateArgs):
    return execute(lambda: services(request).app_projects.update(id, body.files, body.expected_revision))


@router.post("/{id}/source-edit")
def project_edit_source(request: Request, id: str, body: AppSourceEditArgs):
    return execute(lambda: services(request).app_projects.edit_source(id, **body.model_dump(exclude={"id"})))


@router.get("/{id}/source-count")
def project_source_count(request: Request, id: str, vsrc: str, path: str = "/"):
    return execute(lambda: services(request).app_projects.source_count(id, vsrc, path))


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
