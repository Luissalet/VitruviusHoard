"""Tools exposed to the assistant. One catalogue drives /api/agent/* and mcp_server.py."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from .services import Services

AGENT_INSTRUCTIONS = """Vitruvius's Hoard is a design workbench: a cited library of design criterion, a render -> capture -> critique
loop on real Chromium, a design-system (tokens) generator with a playground, and a gallery of captured websites.
Always cite `[vitruvius: ...]` when quoting the library (design_search, design_brief, design_rules).
Loop: write HTML -> render_preview -> design_critique -> fix -> render again; stop at score >= 8 or after 3 rounds,
then page_assay it (drives every control in a real browser and reports what does not work).
Use design_brief before a page from scratch; styles_search / palettes_search / fonts_search for quick lookups.
reference_add, source_add, source_ingest, tokens_delete and reference_delete change things: only when the user asks."""


class Empty(BaseModel):
    pass


# ---------------- library ----------------

class SearchArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    kind: Optional[str] = Field(None, max_length=40, description="Document kind: skill, guide, rule, catalog, reference, readme, other.")
    source: Optional[str] = Field(None, max_length=80, description="Only this source id.")
    area: Optional[str] = Field(None, max_length=40, description="Rule area: typography, color, layout, motion, a11y, forms, performance, content.")
    limit: int = Field(8, ge=1, le=50)
    mode: str = Field("auto", pattern="^(auto|hybrid|bm25|dense)$", description="auto = keywords + multilingual meaning when the vectors exist; bm25 = keywords only; dense = meaning only.")


class BriefArgs(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    vibe: Optional[str] = Field(None, max_length=120)
    product_type: Optional[str] = Field(None, max_length=120)
    platform: Optional[str] = Field(None, max_length=60)
    mode: str = Field("marketing", pattern="^(marketing|product)$")
    knobs: Optional[dict[str, Any]] = None
    use_model: bool = False


class RulesArgs(BaseModel):
    area: Optional[str] = Field(None, max_length=40)
    severity: Optional[str] = Field(None, pattern="^(info|warn|error)$")
    source: Optional[str] = Field(None, max_length=80)
    limit: int = Field(30, ge=1, le=200)


class StylesSearchArgs(BaseModel):
    query: Optional[str] = Field(None, max_length=200)
    tags: Optional[list[str]] = None
    limit: int = Field(10, ge=1, le=100)


class PalettesSearchArgs(BaseModel):
    query: Optional[str] = Field(None, max_length=200)
    product_type: Optional[str] = Field(None, max_length=120)
    limit: int = Field(10, ge=1, le=100)


class FontsSearchArgs(BaseModel):
    query: Optional[str] = Field(None, max_length=200)
    mood: Optional[str] = Field(None, max_length=120)
    limit: int = Field(10, ge=1, le=100)


# ---------------- render / lint / critique ----------------

class RenderArgs(BaseModel):
    html: Optional[str] = Field(None, max_length=2_000_000)
    url: Optional[str] = Field(None, max_length=2000)
    widths: list[int] = Field(default_factory=lambda: [390, 1024, 1440])
    full_page: bool = True
    dark: bool = False
    wait_ms: int = Field(800, ge=0, le=20000)
    lint: bool = True
    include_images: bool = False
    title: str = Field("", max_length=200)


class LintArgs(BaseModel):
    html: Optional[str] = Field(None, max_length=2_000_000)
    url: Optional[str] = Field(None, max_length=2000)
    render_id: Optional[str] = Field(None, max_length=40)


class AssayArgs(BaseModel):
    html: Optional[str] = Field(None, max_length=2_000_000, description="The page to check (a complete HTML document).")
    url: Optional[str] = Field(None, max_length=2000, description="A URL whose HTML is downloaded and checked as a single page.")
    render_id: Optional[str] = Field(None, max_length=40, description="A previous render_preview of raw HTML (its saved source is reused).")
    path: Optional[str] = Field(None, max_length=1000, description="A local .html file or a folder holding index.html.")
    timeout_s: int = Field(300, ge=30, le=900)


class CritiqueArgs(BaseModel):
    render_id: Optional[str] = Field(None, max_length=40)
    html: Optional[str] = Field(None, max_length=2_000_000)
    url: Optional[str] = Field(None, max_length=2000)
    focus: Optional[str] = Field(None, max_length=200)
    use_vision: bool = True


class CompareArgs(BaseModel):
    render_a: str = Field(..., max_length=40)
    render_b: str = Field(..., max_length=40)
    width: Optional[int] = Field(None, ge=100, le=4000)


# ---------------- tokens ----------------

class TokensGenerateArgs(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    base_color: Optional[str] = Field(None, max_length=10)
    hue: Optional[float] = Field(None, ge=0, le=360)
    style: Optional[str] = Field(None, max_length=120, description="Radius/shadow style (sharp, soft, pill, flat, hard-offset) or a catalog style name such as 'brutalism', 'glassmorphism', 'swiss'.")
    vibe: Optional[str] = Field(None, max_length=120)
    mode: str = Field("both", pattern="^(light|dark|both)$")
    knobs: Optional[dict[str, Any]] = None
    fonts: Optional[dict[str, str]] = None
    radius: Optional[str] = Field(None, max_length=20)
    density: Optional[str] = Field(None, pattern="^(compact|comfortable|spacious)$")


class TokensGetArgs(BaseModel):
    id: str = Field(..., max_length=40)
    format: str = Field("json", pattern="^(json|css|tailwind|w3c)$")


class TokensListArgs(BaseModel):
    limit: int = Field(30, ge=1, le=200)


class TokensPreviewArgs(BaseModel):
    id: str = Field(..., max_length=40)
    dark: bool = False


class TokensDeleteArgs(BaseModel):
    id: str = Field(..., max_length=40)


# ---------------- references ----------------

class ReferenceAddArgs(BaseModel):
    url: Optional[str] = Field(None, max_length=2000)
    html: Optional[str] = Field(None, max_length=2_000_000)
    tags: Optional[list[str]] = None
    note: str = Field("", max_length=2000)
    video: bool = True
    analyze: bool = True


class ReferenceSearchArgs(BaseModel):
    query: Optional[str] = Field(None, max_length=200)
    tags: Optional[list[str]] = None
    vibe: Optional[str] = Field(None, max_length=120)
    lib: Optional[str] = Field(None, max_length=60)
    limit: int = Field(12, ge=1, le=100)


class ReferenceIdArgs(BaseModel):
    id: str = Field(..., max_length=40)


# ---------------- sources ----------------

class SourceAddArgs(BaseModel):
    url: str = Field(..., min_length=1, max_length=2000, description="Git URL, local folder path, or a single page URL.")
    id: Optional[str] = Field(None, max_length=80)
    kind: str = Field("git", pattern="^(git|local|url)$")
    license: str = Field("", max_length=80)
    category: str = Field("", max_length=80)
    paths: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    structured: bool = False


class SourceIngestArgs(BaseModel):
    id: Optional[str] = Field(None, max_length=80)
    all: bool = False
    embeddings: bool = Field(False, description="(Re)build the multilingual vectors (so Spanish questions find English criterion); alone = only that.")


class SourceStatusArgs(BaseModel):
    id: str = Field(..., max_length=80)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    annotations: dict[str, bool]
    run: Callable[[Services, Any], Any]


def _ann(read_only: bool, destructive: bool = False, idempotent: bool | None = None) -> dict[str, bool]:
    return {"readOnlyHint": read_only, "destructiveHint": destructive, "idempotentHint": read_only if idempotent is None else idempotent, "openWorldHint": False}


def _strip_html(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def run_design_search(services: Services, args: SearchArgs) -> dict:
    items = services.library_search(args.query, kind=args.kind, source=args.source, area=args.area, limit=args.limit,
                                    mode=args.mode)
    return {"count": len(items), "items": items, "dense": services.dense.usable()}


def run_design_brief(services: Services, args: BriefArgs) -> dict:
    return services.library_brief(subject=args.subject, vibe=args.vibe, product_type=args.product_type,
                                  platform=args.platform, mode=args.mode, knobs=args.knobs, use_model=args.use_model)


def run_design_rules(services: Services, args: RulesArgs) -> dict:
    items = services.library_rules(area=args.area, severity=args.severity, source=args.source, limit=args.limit)
    return {"count": len(items), "rules": items}


def _filter_query(rows: list[dict], query: Optional[str], fields: list[str]) -> list[dict]:
    if not query:
        return rows
    needle = query.lower()
    from .library import _tokens, _rank
    tokens = _tokens(needle)
    if not tokens:
        return rows
    ranked = _rank(rows, tokens, fields, None, len(rows))
    return [r for r in ranked if any(t in " ".join(str(r.get(f, "")) for f in fields).lower() for t in tokens)]


def run_styles_search(services: Services, args: StylesSearchArgs) -> dict:
    rows = services.catalog_styles(limit=500)
    rows = _filter_query(rows, args.query, ["name", "description", "keywords"])
    if args.tags:
        wanted = set(t.lower() for t in args.tags)
        rows = [r for r in rows if wanted & set(k.lower() for k in r.get("keywords", []))]
    return {"count": len(rows[: args.limit]), "styles": rows[: args.limit]}


def run_palettes_search(services: Services, args: PalettesSearchArgs) -> dict:
    rows = services.catalog_palettes(limit=500)
    rows = _filter_query(rows, args.query, ["name", "notes"])
    if args.product_type:
        rows = [r for r in rows if args.product_type.lower() in (r.get("product_type") or "").lower()]
    return {"count": len(rows[: args.limit]), "palettes": rows[: args.limit]}


def run_fonts_search(services: Services, args: FontsSearchArgs) -> dict:
    rows = services.catalog_fonts(limit=500)
    rows = _filter_query(rows, args.query, ["heading", "body", "mood", "notes"])
    if args.mood:
        rows = [r for r in rows if args.mood.lower() in (r.get("mood") or "").lower()]
    return {"count": len(rows[: args.limit]), "fonts": rows[: args.limit]}


def run_render_preview(services: Services, args: RenderArgs) -> dict:
    row = services.render(html=args.html, url=args.url, widths=args.widths, full_page=args.full_page, dark=args.dark,
                          wait_ms=args.wait_ms, lint=args.lint, title=args.title)
    out = _strip_html(row)
    if not args.include_images:
        out["files"] = [{k: v for k, v in f.items() if k != "bytes"} for f in out["files"]]
    return out


def run_design_lint(services: Services, args: LintArgs) -> dict:
    return services.lint_html(html=args.html, url=args.url, render_id=args.render_id)


def run_page_assay(services: Services, args: AssayArgs) -> dict:
    if not (args.html or args.url or args.render_id or args.path):
        raise ValueError("page_assay needs html, url, render_id or path")
    return services.assay_page(html=args.html, url=args.url, render_id=args.render_id, path=args.path, timeout_s=args.timeout_s)


def run_design_critique(services: Services, args: CritiqueArgs) -> dict:
    render_id = args.render_id
    if render_id is None:
        row = services.render(html=args.html, url=args.url, widths=[390, 1024, 1440], full_page=True)
        render_id = row["id"]
    return services.critique_render(render_id, focus=args.focus, use_vision=args.use_vision)


def run_render_compare(services: Services, args: CompareArgs) -> dict:
    return services.render_compare(args.render_a, args.render_b, width=args.width)


_STYLE_SHAPES = {"sharp", "soft", "pill", "flat", "hard-offset"}
_STYLE_HINTS = [  # catalog style words → radius/shadow shape, and optional knob nudges
    (("brutal", "swiss", "industrial", "terminal", "editorial", "typographic"), "sharp", {}),
    (("neubrutal", "memphis", "pop"), "hard-offset", {"design_variance": 8}),
    (("glass", "aurora", "mesh", "neumorph", "clay", "soft", "organic", "pastel"), "soft", {}),
    (("playful", "bubbly", "candy", "kids", "rounded", "pill"), "pill", {"motion_intensity": 7}),
    (("flat", "minimal", "mono"), "flat", {}),
]


def _resolve_style(services: Services, style: Optional[str], brief: dict) -> Optional[str]:
    if not style:
        return None
    low = style.lower().strip()
    if low in _STYLE_SHAPES:
        return low
    # A catalog style name: keep the reference and derive the shape from its words + keywords.
    words = low
    for row in services.catalog_styles(limit=500):
        if low in (row.get("name") or "").lower() or low in (row.get("slug") or "").lower():
            brief["catalog_style"] = {"id": row["id"], "name": row["name"], "source_id": row["source_id"]}
            words = " ".join([row.get("name") or "", " ".join(row.get("keywords") or [])]).lower()
            if not brief.get("fonts") and (row.get("typography") or {}).get("heading"):
                brief["fonts"] = {"heading": row["typography"].get("heading"), "body": row["typography"].get("body") or ""}
            break
    for keys, shape, nudges in _STYLE_HINTS:
        if any(k in words for k in keys):
            for k, v in nudges.items():
                brief.setdefault(k, v)
            return shape
    return "soft"


def run_tokens_generate(services: Services, args: TokensGenerateArgs) -> dict:
    brief = {"name": args.name, "base_color": args.base_color, "hue": args.hue, "vibe": args.vibe,
            "mode": args.mode, "fonts": args.fonts, "density": args.density}
    if args.knobs:
        brief.update(args.knobs)
    brief = {k: v for k, v in brief.items() if v is not None}
    shape = _resolve_style(services, args.style, brief)
    if shape:
        brief["style"] = shape
        brief["style_requested"] = args.style
    return services.tokens_generate(brief)


def run_tokens_get(services: Services, args: TokensGetArgs) -> dict:
    if args.format == "json":
        row = services.tokens_get(args.id)
        if row is None:
            raise LookupError(f"Unknown design system '{args.id}'.")
        return row
    return {"id": args.id, "format": args.format, "content": services.tokens_export(args.id, args.format)}


def run_tokens_list(services: Services, args: TokensListArgs) -> dict:
    rows = services.tokens_list(limit=args.limit)
    return {"count": len(rows), "design_systems": [{k: v for k, v in r.items() if k != "tokens"} for r in rows]}


def run_tokens_preview(services: Services, args: TokensPreviewArgs) -> dict:
    row = services.tokens_preview(args.id, dark=args.dark)
    return _strip_html(row)


def run_tokens_delete(services: Services, args: TokensDeleteArgs) -> dict:
    ok = services.tokens_delete(args.id)
    if not ok:
        raise LookupError(f"Unknown design system '{args.id}'.")
    return {"ok": True}


def run_reference_add(services: Services, args: ReferenceAddArgs) -> dict:
    return services.reference_add(url=args.url, html=args.html, tags=args.tags, note=args.note, video=args.video,
                                  analyze=args.analyze)


def run_reference_search(services: Services, args: ReferenceSearchArgs) -> dict:
    items = services.reference_search(query=args.query, tags=args.tags, vibe=args.vibe, lib=args.lib, limit=args.limit)
    return {"count": len(items), "references": items}


def run_reference_get(services: Services, args: ReferenceIdArgs) -> dict:
    row = services.reference_get(args.id)
    if row is None:
        raise LookupError(f"Unknown reference '{args.id}'.")
    return row


def run_reference_delete(services: Services, args: ReferenceIdArgs) -> dict:
    ok = services.reference_delete(args.id)
    if not ok:
        raise LookupError(f"Unknown reference '{args.id}'.")
    return {"ok": True}


def run_sources_list(services: Services, args: Empty) -> dict:
    rows = services.sources_list()
    return {"count": len(rows), "sources": rows}


def run_source_add(services: Services, args: SourceAddArgs) -> dict:
    source_id = args.id or args.url.rstrip("/").rsplit("/", 1)[-1].lower().replace(".git", "")
    return services.source_add(id=source_id, url=args.url, kind=args.kind, license=args.license,
                               category=args.category, paths=args.paths, tags=args.tags, structured=args.structured)


def run_source_ingest(services: Services, args: SourceIngestArgs) -> dict:
    if args.embeddings and not args.id and not args.all:
        return {"embeddings": services.embeddings_build()}
    result = services.source_ingest(args.id, all=args.all)
    if args.embeddings:
        result = {**result, "embeddings": "rebuilt after the ingest finishes (when the model is on disk)"}
    return result


def run_source_status(services: Services, args: SourceStatusArgs) -> dict:
    return services.source_status(args.id)


def run_vitruvius_status(services: Services, args: Empty) -> dict:
    return services.status()


TOOLS: list[Tool] = [
    Tool("design_search",
        "Search the design library: rules, skills, styles, motion recipes with citations. Busca criterio de diseño.\n"
        "Keywords (bm25) fused with multilingual meaning (a Spanish question finds English criterion) over the ingested\n"
        "design-skill repos; every hit carries a `[vitruvius: source/path § heading]` cite and how it matched.\n"
        "Sinónimos: buscar, criterio, reglas de diseño, motion, tipografía, contraste, biblioteca.",
        SearchArgs, _ann(True), run_design_search),
    Tool("design_brief",
        "Design brief for a page/app: style, palette, fonts, rules, motion, anti-patterns. Brief de diseño.\n"
        "Deterministic composition (2-3 styles, one palette, one font pairing, rules by area, anti-patterns, checklist), all cited.\n"
        "Sinónimos: brief, dirección de arte, vibe, paleta, tipografía, para una landing, para una app.",
        BriefArgs, _ann(True), run_design_brief),
    Tool("design_rules",
        "List design rules by area (typography, color, layout, motion, a11y, forms). Reglas de diseño.\n"
        "Filter by area/severity/source; rules with a check_id are enforced deterministically by design_lint.\n"
        "Sinónimos: reglas, buenas prácticas, do and don't, checklist.",
        RulesArgs, _ann(True), run_design_rules),
    Tool("styles_search",
        "Find UI styles (glass, brutalist, swiss, aurora...) with tokens and when to use them. Estilos de UI.\n"
        "Catalog lookup over the ingested style library (colors, typography, effects, best_for, avoid).\n"
        "Sinónimos: estilo visual, brutalist, glassmorphism, swiss, aurora, retro-futurista.",
        StylesSearchArgs, _ann(True), run_styles_search),
    Tool("palettes_search",
        "Find catalogued colour palettes by name or product type. Buscar paletas de color.\n"
        "Reads the palettes table (role/hex pairs) ingested from the catalog source.\n"
        "Sinónimos: paleta, colores, esquema de color.",
        PalettesSearchArgs, _ann(True), run_palettes_search),
    Tool("fonts_search",
        "Find catalogued font pairings by mood or query. Buscar combinaciones de tipografías.\n"
        "Reads the font_pairings table (heading/body/mono, mood, Google Fonts URL).\n"
        "Sinónimos: tipografía, fuente, pareja de fuentes, mood tipográfico.",
        FontsSearchArgs, _ann(True), run_fonts_search),
    Tool("render_preview",
        "Render HTML or a URL in Chromium, screenshot at widths, run lint. Renderiza y captura.\n"
        "Returns render id, absolute file paths, size, lint summary and metrics (fonts, colours, libs). Never returns "
        "image bytes unless include_images=true.\nSinónimos: renderizar, capturar, screenshot, previsualizar.",
        RenderArgs, _ann(False, False, False), run_render_preview),
    Tool("design_lint",
        "Deterministic design checks on HTML/URL (fonts, contrast, motion, a11y, generic-AI patterns). Lint de diseño.\n"
        "29 checks with stable ids; each finding has area, severity, evidence and a concrete fix.\n"
        "Sinónimos: lint, revisar diseño, patrones genéricos de IA, contraste, accesibilidad.",
        LintArgs, _ann(True), run_design_lint),
    Tool("design_critique",
        "Critique a rendered page: score 0-10, findings with fixes, using lint + local vision model. Crítica de diseño.\n"
        "Merges deterministic lint with an optional vision-model rubric (hierarchy, typography, colour, motion, a11y, copy).\n"
        "Sinónimos: criticar, evaluar diseño, puntuación, feedback visual.",
        CritiqueArgs, _ann(False, False, False), run_design_critique),
    Tool("page_assay",
        "Functional check of a page in a real browser: does every control work? No tests needed. ¿Funciona la página?\n"
        "Runs assay (pip install assay-ui): measures every control, derives a test plan, drives it and reports contradictions\n"
        "(dead buttons, `undefined` shown, a control answering differently to the same input). Takes ~15-60 s.\n"
        "Sinónimos: probar la página, comprobar botones, test funcional, assay, ¿funciona?, smoke test de UI.",
        AssayArgs, _ann(True, False, False), run_page_assay),
    Tool("render_compare",
        "Pixel-diff two renders at a given width: percent changed + a diff image. Comparar dos renders.\n"
        "Sinónimos: comparar, diff visual, antes y después.",
        CompareArgs, _ann(True), run_render_compare),
    Tool("tokens_generate",
        "Generate a design system: OKLCH palettes, type scale, spacing, motion tokens. Genera design system.\n"
        "Pure-Python OKLCH ramps (50-950), fluid type scale, spacing/radius/shadow/motion tokens, four export formats.\n"
        "Sinónimos: sistema de diseño, tokens, paleta OKLCH, tailwind theme.",
        TokensGenerateArgs, _ann(False, False, False), run_tokens_generate),
    Tool("tokens_get",
        "Get a generated design system in json, css, tailwind or w3c format. Obtener design system.\n"
        "Sinónimos: exportar tokens, css variables, tailwind theme, w3c tokens.",
        TokensGetArgs, _ann(True), run_tokens_get),
    Tool("tokens_list",
        "List generated design systems. Listar design systems.\nSinónimos: listar tokens, sistemas guardados.",
        TokensListArgs, _ann(True), run_tokens_list),
    Tool("tokens_preview",
        "Render the design system's live playground and lint it. Previsualizar design system.\n"
        "Sinónimos: preview, playground, ver el sistema de diseño.",
        TokensPreviewArgs, _ann(False, False, False), run_tokens_preview),
    Tool("tokens_delete",
        "Delete a generated design system (only when the user asks). Eliminar design system.\n"
        "Sinónimos: borrar tokens, eliminar sistema de diseño.",
        TokensDeleteArgs, _ann(False, True, True), run_tokens_delete),
    Tool("reference_add",
        "Capture a website into the reference gallery: screenshots, video, fonts, palette. Guardar referencia.\n"
        "Desktop+mobile capture, optional 6s scroll video, Pillow palette, detected libs/motion, optional vision vibe tagging.\n"
        "Sinónimos: guardar web, referencia visual, galería, inspiración.",
        ReferenceAddArgs, _ann(False, False, False), run_reference_add),
    Tool("reference_search",
        "Search the reference gallery by text, tags, vibe or library. Buscar referencias.\n"
        "Sinónimos: buscar referencias, galería, por tag, por vibe, por librería.",
        ReferenceSearchArgs, _ann(True), run_reference_search),
    Tool("reference_get",
        "Get one reference's full detail (files, palette, fonts, motion, analysis). Ver referencia.\n"
        "Sinónimos: detalle de referencia, ver captura.",
        ReferenceIdArgs, _ann(True), run_reference_get),
    Tool("reference_delete",
        "Delete a reference from the gallery (only when the user asks). Eliminar referencia.\n"
        "Sinónimos: borrar referencia, quitar de la galería.",
        ReferenceIdArgs, _ann(False, True, True), run_reference_delete),
    Tool("sources_list",
        "List every ingested design-criterion source and its status. Listar fuentes.\n"
        "Sinónimos: fuentes, repos ingeridos, estado de ingesta.",
        Empty, _ann(True), run_sources_list),
    Tool("source_add",
        "Add a new source to ingest: a git repo, a local folder or a single page URL. Añadir fuente.\n"
        "Only when the user asks to add a new source; call source_ingest afterwards to actually ingest it.\n"
        "Sinónimos: añadir repositorio, nueva fuente, importar skill.",
        SourceAddArgs, _ann(False, False, True), run_source_add),
    Tool("source_ingest",
        "Ingest (or re-ingest) one source or every source; runs in the background. Ingerir fuente.\n"
        "embeddings=true (re)builds the multilingual vectors (CPU, about a minute for the whole library).\n"
        "Sinónimos: ingerir, actualizar fuente, reindexar, clonar de nuevo.",
        SourceIngestArgs, _ann(False, False, True), run_source_ingest),
    Tool("source_status",
        "Status of one source's ingest (idle, cloning, ingesting, ready, error). Estado de una fuente.\n"
        "Sinónimos: estado de ingesta, progreso, error de clonado.",
        SourceStatusArgs, _ann(True), run_source_status),
    Tool("vitruvius_status",
        "Health: browser, ffmpeg, git, library counts, model resolution for vision/chat/embeddings. Estado del sistema.\n"
        "Sinónimos: estado, salud, ¿funciona el navegador?, modelos disponibles.",
        Empty, _ann(True), run_vitruvius_status),
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def tool_catalog() -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "annotations": t.annotations,
         "inputSchema": t.input_model.model_json_schema(by_alias=True)}
        for t in TOOLS
    ]


def call_tool(services: Services, name: str, arguments: dict | None) -> Any:
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        raise KeyError(f"Unknown tool: {name}")
    args = tool.input_model.model_validate(arguments or {})
    return tool.run(services, args)
