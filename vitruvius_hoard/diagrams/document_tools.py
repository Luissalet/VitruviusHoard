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


class DocumentSave(BaseModel):
    id: str | None = Field(None, pattern=r"^[0-9a-f]{12}$")
    base_revision: int | None = Field(None, ge=1)
    content: dict[str, Any] = Field(default_factory=lambda: {"diagram": {"type": "flowchart", "nodes": []}})
    reason: str = "Edit diagram"


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
    collection: Literal["nodes", "edges", "groups", "view_nodes", "view_edges", "diagram"]
    id: str = ""
    action: Literal["set", "add", "remove"] = "set"
    values: dict[str, Any] = Field(default_factory=dict)


class DocumentEdit(BaseModel):
    id: str = Field(..., pattern=r"^[0-9a-f]{12}$")
    base_revision: int = Field(..., ge=1)
    edits: list[ObjectEdit]
    reason: str = "Edit selected diagram objects"


def store(services):
    return DocumentStore(services.config.data_dir)


def public(row, include_svg=False):
    result = deepcopy(row)
    if not include_svg:
        result.get("rendering", {}).pop("svg", None)
    result["files"] = {mode: f"/api/diagrams/documents/{row['id']}/export.svg?revision={row['revision']}&mode={mode}" for mode in ("light", "dark")}
    result["viewer_url"] = f"/api/diagrams/documents/{row['id']}/viewer?revision={row['revision']}"
    result["exports"] = {kind: f"/api/diagrams/documents/{row['id']}/export.{kind}?revision={row['revision']}" for kind in ("svg", "png", "pdf", "drawio", "mmd", "html")}
    result["source_url"] = f"/api/diagrams/documents/{row['id']}/source.json?revision={row['revision']}"
    return result


def get(services, args):
    return public(store(services).get(args.id, args.revision), args.include_svg)


def save(services, args):
    return public(store(services).save(args.content, did=args.id, base_revision=args.base_revision, reason=args.reason))


def edit(services, args):
    content = store(services).get(args.id, args.base_revision)["content"]
    for change in args.edits:
        if change.collection.startswith("view_"):
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
            values = content["diagram"][change.collection]
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


def tools(empty):
    return [
        Tool("diagram_document_list", "List editable diagram documents without starting models. Lista de diagramas editables.", empty, ann(True), list_documents),
        Tool("diagram_document_get", "Read source, manual layout and revision of an editable diagram. Leer diagrama editable.", DocumentGet, ann(True), get),
        Tool("diagram_document_save", "Create or save an editable diagram; unrelated edits merge from base_revision. Guardar diagrama.", DocumentSave, ann(False), save),
        Tool("diagram_document_edit", "Change selected diagram objects or geometry by stable ID. Conserva otras ediciones. Editar selección.", DocumentEdit, ann(False), edit),
        Tool("diagram_document_undo", "Reverse one saved change, preserving unrelated later edits. Deshacer una revisión.", DocumentUndo, ann(False), undo),
        Tool("diagram_document_history", "List retained revisions of an editable diagram. Versiones de diagrama.", DocumentGet, ann(True), history),
        Tool("diagram_document_compare", "Compare authored objects and layout between two saved revisions. Comparar versiones de diagrama.", DocumentCompare, ann(True), compare),
        Tool("diagram_document_import", "Import an editable native, Mermaid, draw.io or Excalidraw source; retains original and reports limits. Importar diagrama.", DocumentImport, ann(False), import_document),
    ]
