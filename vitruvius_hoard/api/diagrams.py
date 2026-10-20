"""/api/diagrams*: the diagram tools over HTTP for the interface, and the saved SVG files."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, HTMLResponse

from ..diagrams import DiagramStore, document_tools as documents
from ..diagrams.tools import (BrandNameArgs, BrandOnboardArgs, DiagramIdArgs, DiagramListArgs, DiagramRenderArgs,
                              DiagramTypesArgs, run_brand_delete, run_brand_onboard, run_brands, run_diagram_delete,
                              run_diagram_get, run_diagram_list, run_diagram_render, run_diagram_types)
from .deps import services as _services


def services(request: Request):
    return _services(request)


def _found(fn, *args):
    try:
        return fn(*args)
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

router = APIRouter(prefix="/api")


@router.get("/diagrams/styles")
def styles_list(request: Request):
    return {"styles":documents.style_store(services(request)).list()}


@router.get("/diagrams/styles/{sid}")
def style_get(request: Request,sid: str,revision: int | None=None):
    return _found(lambda:documents.style_store(services(request)).get(sid,revision))


@router.post("/diagrams/styles",status_code=201)
def style_save(request: Request,body: documents.StyleSave):
    return documents.style_save(services(request),body)


@router.post("/diagrams/styles/remove")
def style_remove(request: Request,body: documents.StyleRemove):
    return documents.style_store(services(request)).remove(body.id,body.base_revision)


@router.post("/diagrams/styles/apply")
def style_apply(request: Request,body: documents.StyleApply):
    return documents.style_apply(services(request),body)


@router.post("/diagrams/documents/preview")
def document_preview(request: Request, body: documents.DocumentSave):
    from ..diagrams.documents import normalize, drawing
    return {"rendering": drawing(normalize(body.content), body.state_id)}


@router.post("/diagrams/documents/import", status_code=201)
def document_import(request: Request, body: documents.DocumentImport):
    return documents.import_document(services(request), body)


@router.get("/diagrams/documents")
def documents_list(request: Request):
    return documents.list_documents(services(request), None)


@router.post("/diagrams/documents", status_code=201)
def documents_save(request: Request, body: documents.DocumentSave):
    return documents.save(services(request), body)


@router.get("/diagrams/documents/{did}")
def document_get(request: Request, did: str, revision: int | None = None, svg: bool = False, state_id: str | None = None):
    return _found(lambda: documents.get(services(request), documents.DocumentGet(id=did, revision=revision, include_svg=svg, state_id=state_id)))


@router.post("/diagrams/documents/{did}/edit")
def document_edit(request: Request, did: str, body: documents.DocumentEdit):
    if did != body.id:
        raise HTTPException(status_code=400, detail="Document identities differ.")
    return documents.edit(services(request), body)


@router.post("/diagrams/documents/{did}/undo")
def document_undo(request: Request, did: str, body: documents.DocumentUndo):
    if did != body.id:
        raise HTTPException(status_code=400, detail="Document identities differ.")
    return documents.undo(services(request), body)


@router.get("/diagrams/documents/{did}/history")
def document_history(request: Request, did: str):
    return _found(lambda: documents.history(services(request), documents.DocumentGet(id=did)))


@router.get("/diagrams/documents/{did}/export.svg")
def document_svg(request: Request, did: str, revision: int | None = None, mode: str = "light", state_id: str | None = None):
    row = _found(lambda: documents.store(services(request)).get(did, revision))
    if mode not in ("light", "dark"):
        raise HTTPException(status_code=400, detail="Unknown colour mode.")
    from ..diagrams.mechanism import selected
    row = _found(lambda: selected(row, state_id))
    return Response(row["rendering"]["svg"][mode], media_type="image/svg+xml")


@router.get("/diagrams/documents/{did}/viewer")
def document_viewer(request: Request, did: str, revision: int | None = None, state_id: str | None = None):
    from ..diagrams.reader import reader
    row = _found(lambda: documents.store(services(request)).get(did, revision))
    return HTMLResponse(_found(lambda: reader(row, state_id)))


@router.get("/diagrams/documents/{did}/compare")
def document_compare(request: Request, did: str, before_revision: int, after_revision: int | None = None):
    return _found(lambda: documents.compare(services(request), documents.DocumentCompare(id=did, before_revision=before_revision, after_revision=after_revision)))


@router.get("/diagrams/documents/{did}/source.json")
def document_source(request: Request, did: str, revision: int | None = None):
    import json
    row = _found(lambda: documents.store(services(request)).get(did, revision))
    return Response(json.dumps({"format": "vitruvius.diagram/1", "revision": row["revision"], "content": row["content"]}, ensure_ascii=False, indent=2),
                    media_type="application/json", headers={"Content-Disposition": f'attachment; filename="diagram-{did}.json"'})


@router.get("/diagrams/documents/{did}/export.{kind}")
def document_export(request: Request, did: str, kind: str, revision: int | None = None, mode: str = "light", page_id: str | None = None, state_id: str | None = None):
    from ..diagrams import exchange
    from ..diagrams.reader import reader
    if mode not in ("light", "dark"):
        raise HTTPException(status_code=400, detail="Unknown colour mode.")
    row = _found(lambda: documents.store(services(request)).get(did, revision))
    if kind in ("png", "pdf"):
        from ..diagrams.mechanism import selected
        captured = _found(lambda: selected(row, state_id))
        payload, mime = exchange.image(captured, kind, mode), {"png": "image/png", "pdf": "application/pdf"}[kind]
    elif kind == "vfigure":
        import json
        try:
            payload = json.dumps(exchange.figure(row, mode, page_id, str(request.base_url), state_id), ensure_ascii=False)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        mime = "application/json"
    elif kind == "drawio":
        payload, mime = exchange.drawio(row), "application/xml"
    elif kind == "html":
        payload, mime = _found(lambda: reader(row, state_id)), "text/html"
    elif kind == "mmd":
        payload, mime = exchange.mermaid(row), "text/plain"
    else:
        raise HTTPException(status_code=400, detail="Unknown diagram export format.")
    return Response(payload, media_type=mime, headers={"Content-Disposition": f'attachment; filename="diagram-{did}-r{row["revision"]}.{kind}"'})


@router.get("/diagrams/types")
def diagram_types(request: Request, intent: str = "", type: str = ""):
    return run_diagram_types(services(request), DiagramTypesArgs(intent=intent, type=type))


@router.get("/diagrams")
def diagrams_list(request: Request, limit: int = 30):
    return run_diagram_list(services(request), DiagramListArgs(limit=limit))


@router.post("/diagrams", status_code=201)
def diagrams_create(request: Request, body: DiagramRenderArgs):
    return run_diagram_render(services(request), body)


@router.get("/diagrams/brands")
def brands(request: Request):
    return run_brands(services(request), None)


@router.post("/diagrams/brands", status_code=201)
def brand_onboard(request: Request, body: BrandOnboardArgs):
    return run_brand_onboard(services(request), body)


@router.delete("/diagrams/brands/{name}")
def brand_delete(request: Request, name: str):
    return _found(lambda: run_brand_delete(services(request), BrandNameArgs(name=name)))


@router.get("/diagrams/{diagram_id}")
def diagrams_get(request: Request, diagram_id: str, svg: bool = False):
    return _found(lambda: run_diagram_get(services(request), DiagramIdArgs(id=diagram_id, include_svg=svg)))


@router.delete("/diagrams/{diagram_id}")
def diagrams_delete(request: Request, diagram_id: str) -> dict[str, Any]:
    return _found(lambda: run_diagram_delete(services(request), DiagramIdArgs(id=diagram_id)))


@router.get("/diagrams/{diagram_id}/{mode}.svg")
def diagrams_file(request: Request, diagram_id: str, mode: str):
    path = _found(lambda: DiagramStore(services(request).config.data_dir).svg_path(diagram_id, mode))
    return FileResponse(path, media_type="image/svg+xml")
