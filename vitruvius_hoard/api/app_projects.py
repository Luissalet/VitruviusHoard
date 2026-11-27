"""Native application projects and owned local previews."""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .deps import services
from ..agent_tools import (
    AppArchiveArgs, AppCallArgs, AppCanvasEditArgs, AppChangeUndoArgs, AppCreateArgs, AppCritiqueRoundBody,
    AppCritiqueUndoBody, AppExportArgs, AppPreviewArgs, AppRenderArgs, AppSourceEditArgs, AppUndoArgs, AppUpdateArgs,
    run_app_project_create,
)
from ..app_projects import templates
from ..preview_inspector import StaleSelection, inspector_script, read_selection, write_selection
from ..hoard_link.agentkit import AppError
from ..preview_comments import list_comments

router = APIRouter(prefix="/api/app-projects")


def execute(operation):
    try:
        return operation()
    except AppError as error:
        return JSONResponse(error.to_dict(), status_code=error.status)
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


class CommentBody(BaseModel):
    note: str = ""
    revision: str | None = None
    page: str = "/"
    element: dict = {}
    crop: str | None = None
    attrs: dict = {}


class CommentTextBody(BaseModel):
    text: str = ""


class AnchorsBody(BaseModel):
    anchors: list = []
    revision: str | None = None
    session: str | int | None = None


def _comments(request, id):
    services(request).app_projects._directory(id)
    return services(request).preview_comments


@router.get("/{id}/comments")
def comments_get(request: Request, id: str, status: str = "all"):
    return execute(lambda: list_comments(services(request), id, status))


@router.post("/{id}/comments")
def comment_add(request: Request, id: str, body: CommentBody):
    return execute(lambda: _comments(request, id).add(id, body.note, body.revision, body.page, body.element, body.crop, body.attrs))


@router.put("/{id}/comments/anchors")
def comment_anchors(request: Request, id: str, body: AnchorsBody):
    return execute(lambda: _comments(request, id).set_anchors(id, body.revision, body.anchors, body.session))


@router.get("/{id}/comments/{comment_id}/crop")
def comment_crop(request: Request, id: str, comment_id: str):
    path = execute(lambda: _comments(request, id).crop(id, comment_id))
    return FileResponse(path, media_type="image/jpeg" if path.suffix == ".jpg" else "image/png", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/{id}/comments/{comment_id}/respond")
def comment_respond(request: Request, id: str, comment_id: str, body: CommentTextBody):
    return execute(lambda: _comments(request, id).respond(id, comment_id, body.text))


@router.post("/{id}/comments/{comment_id}/dismiss")
def comment_dismiss(request: Request, id: str, comment_id: str, body: CommentTextBody):
    return execute(lambda: _comments(request, id).dismiss(id, comment_id, body.text, "person"))


@router.post("/{id}/comments/{comment_id}/resolve")
def comment_resolve(request: Request, id: str, comment_id: str):
    return execute(lambda: _comments(request, id).resolve_person(id, comment_id))


@router.post("/{id}/comments/{comment_id}/reopen")
def comment_reopen(request: Request, id: str, comment_id: str, body: CommentTextBody):
    return execute(lambda: _comments(request, id).reopen(id, comment_id, body.text))


@router.post("/{id}/comments/{comment_id}/undo")
def comment_undo(request: Request, id: str, comment_id: str):
    return execute(lambda: _comments(request, id).undo(id, comment_id))


@router.get("")
def project_list(request: Request, archived: bool = False):
    return {"projects": services(request).app_projects.list(archived)}


@router.post("", status_code=201)
def project_create(request: Request, body: AppCreateArgs):
    return execute(lambda: run_app_project_create(services(request), body, author={"kind": "person"}))


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
            # An archived project closes its stream.
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
    return execute(lambda: services(request).app_projects.update(
        id, body.files, body.expected_revision, examples=body.examples, tokens_id=body.tokens_id))


@router.post("/{id}/undo-change")
def project_undo_change(request: Request, id: str, body: AppChangeUndoArgs):
    return execute(lambda: services(request).app_projects.undo_change(
        id, body.change_id, body.expected_revision, body.expected_updated_ts, author={"kind": "person"}))


@router.post("/{id}/undo")
def project_undo(request: Request, id: str, body: AppUndoArgs):
    if body.revision is None:
        raise HTTPException(400, "Choose a source revision to restore")
    return execute(lambda: services(request).app_projects.undo(
        id, body.expected_revision, body.expected_updated_ts, body.revision, author={"kind": "person"}))


@router.post("/{id}/archive")
def project_archive(request: Request, id: str, body: AppArchiveArgs):
    return execute(lambda: services(request).app_projects.archive(id, **body.model_dump(exclude={"id"})))


@router.post("/{id}/source-edit")
def project_edit_source(request: Request, id: str, body: AppSourceEditArgs):
    return execute(lambda: services(request).app_projects.edit_source(id, **body.model_dump(exclude={"id"})))


@router.post("/{id}/canvas-edit")
def project_canvas_edit(request: Request, id: str, body: AppCanvasEditArgs):
    return execute(lambda: services(request).app_projects.canvas_edit(id, **body.model_dump(exclude={"id"})))


@router.get("/{id}/canvas-edit/scale")
def project_canvas_scale(request: Request, id: str, revision: str, path: str = "/",
                         root_font_px: float = Query(16, gt=0, le=1000)):
    return execute(lambda: services(request).app_projects.canvas_scale(id, revision, path, root_font_px))


@router.get("/{id}/source-count")
def project_source_count(request: Request, id: str, vsrc: str, path: str = "/"):
    return execute(lambda: services(request).app_projects.source_count(id, vsrc, path))


@router.post("/{id}/preview")
def project_preview(request: Request, id: str, body: AppPreviewArgs):
    return execute(lambda: services(request).app_projects.stop(id) if body.operation == "stop" else services(request).app_projects.preview(id, body.revision))


@router.get("/{id}/preview/open")
def project_preview_open(request: Request, id: str, path: str = "/", lang: str = "en"):
    es = lang.lower().startswith("es")
    headers = {"Cache-Control": "no-store"}
    if not path.startswith("/") or path.startswith("//") or "\\" in path or any(ord(char) < 32 for char in path):
        message = "Indica una ruta de la aplicación, como /transferir." if es else "Enter an application path, such as /transferir."
        return PlainTextResponse(message, status_code=400, headers=headers)
    try:
        url = services(request).app_projects.open_preview_url(id)
    except LookupError:
        message = "No se encuentra el proyecto." if es else "Application project not found."
        return PlainTextResponse(message, status_code=404, headers=headers)
    except (OSError, ValueError):
        message = ("No se pudo iniciar la vista previa. Vuelve a cargar este enlace o consulta el proyecto en Aplicaciones."
                   if es else "The preview could not start. Reload this link or check the project in Applications.")
        return PlainTextResponse(message, status_code=503, headers=headers)
    return RedirectResponse(url + path, status_code=307, headers=headers)


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


@router.get("/{id}/critique-loop")
def project_critique_loop(request: Request, id: str, lang: str = "en"):
    return execute(lambda: services(request).app_projects.critique_loop(id, lang))


@router.post("/{id}/critique-loop/round")
def project_critique_round(request: Request, id: str, body: AppCritiqueRoundBody):
    return execute(lambda: services(request).app_project_critique_round(id, **body.model_dump()))


@router.post("/{id}/critique-loop/undo")
def project_critique_undo(request: Request, id: str, body: AppCritiqueUndoBody):
    return execute(lambda: services(request).app_projects.undo_critique_round(id, **body.model_dump()))


@router.post("/{id}/render")
def project_render(request: Request, id: str, body: AppRenderArgs):
    return execute(lambda: services(request).app_project_render(id, body.revision, body.widths))


@router.post("/{id}/call")
def project_call(request: Request, id: str, body: AppCallArgs):
    return execute(lambda: services(request).app_project_call(id, **body.model_dump(exclude={"id"})))
