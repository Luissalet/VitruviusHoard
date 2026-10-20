"""Native document operations used by the editor, REST and MCP."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal
from pydantic import BaseModel, Field

from ..hoard_link.agentkit import Tool, ann
from .documents import DocumentStore


class DocumentGet(BaseModel):
    id: str = Field(..., pattern=r"^[0-9a-f]{12}$")
    revision: int | None = Field(None, ge=1)
    include_svg: bool = False
    include_figure: bool = Field(False, description="Include a portable vitruvius.figure/1 source revision and PNG for another Hoard.")
    page_id: str | None = Field(None, description="Select one infographic page for the figure preview; full source is retained.")
    state_id: str | None = Field(None, description="Select an authored isometric state; the complete source remains unchanged.")


class DocumentSave(BaseModel):
    id: str | None = Field(None, pattern=r"^[0-9a-f]{12}$")
    base_revision: int | None = Field(None, ge=1)
    content: dict[str, Any] = Field(default_factory=lambda: {"diagram": {"type": "flowchart", "nodes": []}})
    reason: str = "Edit diagram"
    state_id: str | None = Field(None, description="Preview only: select an authored isometric state.")


class DocumentUndo(BaseModel):
    id: str = Field(..., pattern=r"^[0-9a-f]{12}$")
    revision: int = Field(..., ge=2, description="The specific change to reverse, preserving unrelated later edits.")


class DocumentCompare(BaseModel):
    id: str = Field(..., pattern=r"^[0-9a-f]{12}$")
    before_revision: int = Field(..., ge=1)
    after_revision: int | None = Field(None, ge=1)


class DocumentImport(BaseModel):
    source: str
    format: Literal["auto", "mermaid", "drawio", "excalidraw"] = "auto"


class ObjectEdit(BaseModel):
    collection: Literal["nodes", "edges", "groups", "pieces", "mechanism_parts", "mechanism_states", "view_nodes", "view_edges", "pages", "assets", "view", "diagram"]
    id: str = ""
    action: Literal["set", "add", "remove"] = "set"
    values: dict[str, Any] = Field(default_factory=dict)


class DocumentEdit(BaseModel):
    id: str = Field(..., pattern=r"^[0-9a-f]{12}$")
    base_revision: int = Field(..., ge=1)
    edits: list[ObjectEdit]
    reason: str = "Edit selected diagram objects"


class StyleGet(BaseModel):
    id: str = Field(...,pattern=r"^[0-9a-f]{12}$")
    revision: int | None = Field(None,ge=1)


class StyleSave(BaseModel):
    id: str | None = Field(None,pattern=r"^[0-9a-f]{12}$")
    base_revision: int | None = Field(None,ge=1)
    name: str = Field(...,min_length=1,max_length=160)
    values: dict[str,Any]


class StyleRemove(BaseModel):
    id: str = Field(...,pattern=r"^[0-9a-f]{12}$")
    base_revision: int = Field(...,ge=1)


class StyleApply(BaseModel):
    id: str = Field(...,pattern=r"^[0-9a-f]{12}$",description="Document to change.")
    base_revision: int = Field(...,ge=1)
    style_id: str = Field(...,pattern=r"^[0-9a-f]{12}$")
    style_revision: int = Field(...,ge=1)
    node_ids: list[str] = Field(...,min_length=1)


def store(services):
    return DocumentStore(services.config.data_dir)


def public(row, include_svg=False):
    result = deepcopy(row)
    if not include_svg:
        result.get("rendering", {}).pop("svg", None)
        for page in result.get("rendering", {}).get("pages", []):
            page.pop("svg", None)
    result["files"] = {mode: f"/design/api/diagrams/documents/{row['id']}/export.svg?revision={row['revision']}&mode={mode}" for mode in ("light", "dark")}
    result["viewer_url"] = f"/design/api/diagrams/documents/{row['id']}/viewer?revision={row['revision']}"
    result["exports"] = {kind: f"/design/api/diagrams/documents/{row['id']}/export.{kind}?revision={row['revision']}" for kind in ("svg", "png", "pdf", "drawio", "mmd", "html", "vfigure")}
    result["source_url"] = f"/design/api/diagrams/documents/{row['id']}/source.json?revision={row['revision']}"
    result["editor_url"] = f"/design/#/diagrams?document={row['id']}"
    return result


def get(services, args):
    row = store(services).get(args.id, args.revision)
    from .mechanism import selected
    result = public(selected(row, args.state_id), args.include_svg)
    if args.state_id:
        from urllib.parse import quote
        suffix = "&state_id=" + quote(args.state_id, safe="")
        result["state_id"] = args.state_id
        for collection in ("files", "exports"):
            result[collection] = {key: url + suffix for key, url in result[collection].items()}
        result["viewer_url"] += suffix
    if args.include_figure:
        from .exchange import figure
        result["figure"] = figure(row, page_id=args.page_id, state_id=args.state_id, origin_url=f"http://127.0.0.1:{services.config.port}")
    return result


def save(services, args):
    return public(store(services).save(args.content, did=args.id, base_revision=args.base_revision, reason=args.reason))


def edit(services, args):
    content = store(services).get(args.id, args.base_revision)["content"]
    for change in args.edits:
        if change.collection in ("view", "assets"):
            target = content["view"] if change.collection == "view" else content["view"].setdefault("assets", {})
            if change.collection == "view":
                if change.action != "set":
                    raise ValueError("View properties use action=set.")
                target.update(change.values)
            elif change.action == "remove":
                target.pop(change.id, None)
            else:
                target[change.id] = {**target.get(change.id, {}), **change.values}
        elif change.collection.startswith("view_"):
            target = content["view"][change.collection[5:]]
            if change.action == "remove":
                target.pop(change.id, None)
            else:
                target[change.id] = {**target.get(change.id, {}), **change.values}
        elif change.collection == "diagram":
            if change.action != "set":
                raise ValueError("Diagram properties use action=set.")
            content["diagram"].update(change.values)
        else:
            if change.collection.startswith("mechanism_"):
                values = content.setdefault("mechanism", {}).setdefault(change.collection[10:], [])
            else:
                values = content["view"].setdefault("pages", []) if change.collection == "pages" else content["diagram"][change.collection]
            item = next((item for item in values if item["id"] == change.id), None)
            if change.action == "add":
                if item is not None:
                    raise ValueError(f"Object '{change.id}' already exists.")
                values.append({**change.values, "id": change.id})
            elif item is None:
                raise ValueError(f"Unknown object '{change.id}'.")
            elif change.action == "remove":
                values.remove(item)
                if change.collection == "nodes":
                    content["diagram"]["edges"] = [e for e in content["diagram"]["edges"] if change.id not in (e["from"], e["to"])]
            else:
                if "id" in change.values and change.values["id"] != change.id:
                    raise ValueError("Object identities are stable; add a new object instead.")
                item.update(change.values)
    return public(store(services).save(content, did=args.id, base_revision=args.base_revision, reason=args.reason))


def undo(services, args):
    return public(store(services).undo(args.id, args.revision))


def history(services, args):
    return {"id": args.id, "revisions": store(services).history(args.id)}


def list_documents(services, args):
    return {"documents": store(services).list()}


def compare(services, args):
    from .reader import compare as compare_revisions
    return compare_revisions(store(services).get(args.id, args.before_revision), store(services).get(args.id, args.after_revision))


def import_document(services, args):
    from .exchange import import_document as parse
    content, warnings = parse(args.source, args.format)
    return {**public(store(services).save(content, reason="Import diagram")), "warnings": warnings}


def style_store(services):
    from .styles import StyleStore
    return StyleStore(services.config.data_dir)


def style_save(services,args):
    return style_store(services).save(args.name,args.values,sid=args.id,base_revision=args.base_revision)


def style_apply(services,args):
    from .styles import apply
    source=store(services).get(args.id,args.base_revision)['content']
    style=style_store(services).get(args.style_id,args.style_revision)
    content=apply(source,args.node_ids,style['values'])
    return public(store(services).save(content,did=args.id,base_revision=args.base_revision,reason=f"Apply style {style['name']} r{style['revision']}"))


def tools(empty):
    return [
        Tool("diagram_style_list","List reusable named shape styles. Estilos reutilizables.\nDoes not create a store.",empty,ann(True),lambda s,a:{'styles':style_store(s).list()}),
        Tool("diagram_style_get","Read an immutable style revision. Leer estilo.\nRetained revisions remain readable after removal.",StyleGet,ann(True),lambda s,a:style_store(s).get(a.id,a.revision)),
        Tool("diagram_style_save","Create or revise a named shape style. Guardar estilo.\nSupply complete appearance values, excluding geometry, content, images and page.",StyleSave,ann(False),style_save),
        Tool("diagram_style_remove","Remove a style from the library. Retirar estilo.\nRetains its revisions and all styled documents.",StyleRemove,ann(False),lambda s,a:style_store(s).remove(a.id,a.base_revision)),
        Tool("diagram_style_apply","Copy a style onto selected shapes. Aplicar estilo.\nOne undoable document change; preserves geometry, text, resources and independent later edits.",StyleApply,ann(False),style_apply),
        Tool("diagram_document_list", "List editable diagram documents without starting models. Lista de diagramas editables.", empty, ann(True), list_documents),
        Tool("diagram_document_get", "Read source, manual layout and revision of an editable diagram. Leer diagrama editable.", DocumentGet, ann(True), get, capped=False),
        Tool("diagram_document_save", "Create or save an editable diagram; unrelated edits merge from base_revision. Guardar diagrama.", DocumentSave, ann(False), save),
        Tool("diagram_document_edit", "Change selected diagram objects or geometry by stable ID. Conserva otras ediciones. Editar selección.", DocumentEdit, ann(False), edit),
        Tool("diagram_document_undo", "Reverse one saved change, preserving unrelated later edits. Deshacer una revisión.", DocumentUndo, ann(False), undo),
        Tool("diagram_document_history", "List retained revisions of an editable diagram. Versiones de diagrama.", DocumentGet, ann(True), history),
        Tool("diagram_document_compare", "Compare authored objects and layout between two saved revisions. Comparar versiones de diagrama.", DocumentCompare, ann(True), compare),
        Tool("diagram_document_import", "Import an editable source, retaining the original and reporting limits. Importar diagrama.", DocumentImport, ann(False), import_document),
    ]
