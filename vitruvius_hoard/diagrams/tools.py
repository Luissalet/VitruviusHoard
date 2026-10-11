"""The diagram tools of the shared catalogue (``agent_tools.TOOLS``): pick a type, draw, read back, and onboard a brand."""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, model_validator

from ..hoard_link.agentkit import Tool, ann
from . import DEFAULT_PROFILE, Diagram, DiagramStore, ProfileStore, catalogue, from_folder, from_probe, import_source, make, \
    pick_type, profile_from_colors, profile_from_tokens, type_card


class DiagramTypesArgs(BaseModel):
    intent: str = Field("", max_length=400, description="What the diagram should show; returns the pattern, the type and only that type's card.")
    type: str = Field("", max_length=30, description="A type name: returns its card (fields, rules, example).")


class DiagramRenderArgs(BaseModel):
    diagram: Optional[dict[str, Any]] = Field(None, description="Structure: {type, title, direction, nodes, edges, groups, messages, events, tasks}. See diagram_types.")
    source: str = Field("", max_length=200_000, description="Instead of diagram: Mermaid text, an Excalidraw scene (JSON) or a draw.io file (XML).")
    format: Literal["auto", "mermaid", "excalidraw", "drawio"] = "auto"
    profile: str = Field("", max_length=60, description="Brand profile name (diagram_brands), a design-system id (tokens_list) or empty for the neutral default.")
    colors: Optional[dict[str, Any]] = Field(None, description="Inline roles over the profile: paper, ink, muted, accent, surface, border, series (flat = light, or {light:{}, dark:{}}).")
    modes: list[Literal["light", "dark"]] = Field(default_factory=lambda: ["light", "dark"])
    save: bool = Field(True, description="Keep it (id, /api/diagrams/<id>/<mode>.svg).")
    browser_check: bool = Field(False, description="Also open it in the real browser and keep a screenshot (render id).")
    include_svg: bool = Field(True, description="Return the SVG text.")

    @model_validator(mode="after")
    def _one(self):
        if not self.diagram and not self.source.strip():
            raise ValueError("give diagram (structure) or source (Mermaid, Excalidraw or draw.io)")
        return self


class DiagramIdArgs(BaseModel):
    id: str = Field(..., pattern=r"^[0-9a-f]{12}$")
    include_svg: bool = False


class DiagramListArgs(BaseModel):
    limit: int = Field(30, ge=1, le=200)


class BrandOnboardArgs(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    url: str = Field("", max_length=2000, description="A website: rendered in the real browser, colours read from what it shows.")
    folder: str = Field("", max_length=1000, description="A local folder with CSS / token files (custom properties, tokens JSON).")
    tokens_id: str = Field("", max_length=40, description="A design system made with tokens_generate.")
    colors: Optional[dict[str, Any]] = Field(None, description="Roles given directly (paper, ink, muted, accent, surface, border, series).")

    @model_validator(mode="after")
    def _one(self):
        if sum(bool(x) for x in (self.url, self.folder, self.tokens_id, self.colors)) != 1:
            raise ValueError("give exactly one of url, folder, tokens_id or colors")
        return self


class BrandNameArgs(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)


def resolve_profile(services, name: str, colors: Optional[dict] = None) -> tuple[dict, str]:
    profile, label = DEFAULT_PROFILE, "default"
    if name:
        stored = ProfileStore(services.config.data_dir).get(name)
        if stored:
            profile, label = stored, name
        elif re.fullmatch(r"[0-9a-f]{12}", name):
            row = services.tokens_get(name)
            if row is None:
                raise LookupError(f"Unknown profile or design system '{name}'.")
            profile, label = profile_from_tokens(row["tokens"]), f"tokens:{name}"
        else:
            raise LookupError(f"Unknown profile '{name}'. List them with diagram_brands or onboard one with diagram_brand_onboard.")
    if colors:
        profile = profile_from_colors(colors, base=profile)
        label += "+colors"
    return profile, label


def run_diagram_types(services, args: DiagramTypesArgs) -> dict:
    if args.type:
        return type_card(args.type)
    if args.intent:
        pick = pick_type(args.intent)
        return {**pick, "card": type_card(pick["type"])}
    return catalogue()


def _page(svg_text: str, dark: bool) -> str:
    bg = "#11151c" if dark else "#ffffff"
    return f"<!doctype html><html><head><meta charset='utf-8'><title>diagram</title></head><body style='margin:0;background:{bg}'>{svg_text}</body></html>"


def run_diagram_render(services, args: DiagramRenderArgs) -> dict:
    try:
        diagram = Diagram.model_validate(args.diagram) if args.diagram else import_source(args.source, args.format)
    except ValidationError as error:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()[:6])
        raise ValueError(f"the diagram does not fit its type: {problems}") from error
    profile, label = resolve_profile(services, args.profile, args.colors)
    result = make(diagram, profile, tuple(dict.fromkeys(args.modes)) or ("light",))
    out: dict[str, Any] = {"type": diagram.type, "title": diagram.title, "profile": label, "ok": result["ok"],
                           "failed": result["failed"], "gates": result["gates"]}
    if args.save:
        meta = DiagramStore(services.config.data_dir).save(diagram, result, label, source=args.format if args.source else "structure")
        out["id"] = meta["id"]
        out["files"] = {m: f"/api/diagrams/{meta['id']}/{m}.svg" for m in result["svg"]}
    if args.browser_check:
        mode = "light" if "light" in result["svg"] else next(iter(result["svg"]))
        render = services.render(html=_page(result["svg"][mode], mode == "dark"), widths=[1280], full_page=True, lint=False,
                                 title=f"diagram:{out.get('id', diagram.type)}")
        out["browser"] = {"render_id": render["id"], "files": [f"/api/renders/{render['id']}/files/{f}" if isinstance(f, str) else f
                                                                for f in render.get("files") or []],
                          "error": (render.get("metrics") or {}).get("error")}
    if args.include_svg:
        out["svg"] = result["svg"]
    if not result["ok"]:
        out["hint"] = "Fix the structure the failed gates name (shorter labels, fewer crossings, split the diagram) and draw it again."
    return out


def run_diagram_get(services, args: DiagramIdArgs) -> dict:
    return DiagramStore(services.config.data_dir).get(args.id, with_svg=args.include_svg)


def run_diagram_list(services, args: DiagramListArgs) -> dict:
    rows = DiagramStore(services.config.data_dir).list(args.limit)
    return {"count": len(rows), "diagrams": rows}


def run_diagram_delete(services, args: DiagramIdArgs) -> dict:
    return {"ok": DiagramStore(services.config.data_dir).delete(args.id)}


def run_brand_onboard(services, args: BrandOnboardArgs) -> dict:
    store = ProfileStore(services.config.data_dir)
    if args.url:
        render = services.render(url=args.url, widths=[1280], full_page=False, lint=False, title=f"brand:{args.name}")
        if (render.get("metrics") or {}).get("error"):
            raise ValueError(f"the page could not be opened: {render['metrics']['error']} {render['metrics'].get('hint') or ''}".strip())
        profile = from_probe(render.get("_probe") or {}, args.name)
        profile["source"] = f"url:{args.url}"
    elif args.folder:
        profile = from_folder(args.folder, args.name)
        profile["source"] = f"folder:{args.folder}"
    elif args.tokens_id:
        row = services.tokens_get(args.tokens_id)
        if row is None:
            raise LookupError(f"Unknown design system '{args.tokens_id}'.")
        profile = {**profile_from_tokens(row["tokens"]), "source": f"tokens:{args.tokens_id}"}
    else:
        profile = {**profile_from_colors(args.colors or {}), "source": "colors"}
    saved = store.save(args.name, profile)
    result = make(Diagram.model_validate(type_card("architecture")["example"]), saved, ("light",))
    contrast = [g for g in result["gates"] if g["id"].startswith("contrast")]
    return {**saved, "contrast": contrast, **({"evidence": profile["evidence"]} if profile.get("evidence") else {})}


def run_brands(services, args) -> dict:
    return {"profiles": ProfileStore(services.config.data_dir).list(), "default": {k: DEFAULT_PROFILE[k] for k in ("light", "dark")}}


def run_brand_delete(services, args: BrandNameArgs) -> dict:
    if not ProfileStore(services.config.data_dir).delete(args.name):
        raise LookupError(f"Unknown profile '{args.name}'.")
    return {"ok": True}


def tools(empty_model) -> list[Tool]:
    return [
        Tool("diagram_types",
             "Pick a diagram: pattern first, then type; returns only that type's card. Elegir tipo de diagrama.\n"
             "8 types: flowchart, architecture, state, er, swimlane, sequence, timeline, gantt.\n"
             "Sinónimos: diagrama, esquema, flujo, arquitectura, secuencia, entidad relación, cronología, gantt.",
             DiagramTypesArgs, ann(True), run_diagram_types),
        Tool("diagram_render",
             "Draw a diagram as SVG with brand colours, light and dark, and check it. Dibujar diagrama.\n"
             "You give structure (or Mermaid / Excalidraw / draw.io); layout and orthogonal routing are code. Gates: contrast,\n"
             "overlaps, edges through boxes, labels that do not fit, groups, canvas. Sinónimos: diagrama, dibujar, redibujar mermaid.",
             DiagramRenderArgs, ann(False, idempotent=False), run_diagram_render),
        Tool("diagram_get", "A saved diagram: structure, gates, optionally the SVG. Leer diagrama.\nSinónimos: abrir diagrama, svg.",
             DiagramIdArgs, ann(True), run_diagram_get),
        Tool("diagram_list", "Saved diagrams, newest first. Lista de diagramas.\nSinónimos: mis diagramas, historial.",
             DiagramListArgs, ann(True), run_diagram_list),
        Tool("diagram_delete", "Delete a saved diagram. Borrar diagrama.\nOnly when the user asks.", DiagramIdArgs,
             ann(False, destructive=True), run_diagram_delete),
        Tool("diagram_brand_onboard",
             "Save a brand profile for diagrams from a website, a folder of CSS/tokens, a design system or colours. Marca.\n"
             "Reads paper, ink, muted, accent, surface, border and series; derives the other mode; checks contrast.\n"
             "Sinónimos: perfil de marca, colores corporativos, branding, onboard brand.",
             BrandOnboardArgs, ann(False, idempotent=True, open_world=True), run_brand_onboard),
        Tool("diagram_brands", "Brand profiles saved for diagrams, plus the default roles. Perfiles de marca.\nSinónimos: marcas, paletas de diagramas.",
             empty_model, ann(True), run_brands),
        Tool("diagram_brand_delete", "Delete a brand profile. Borrar perfil de marca.\nOnly when the user asks.", BrandNameArgs,
             ann(False, destructive=True), run_brand_delete),
    ]
