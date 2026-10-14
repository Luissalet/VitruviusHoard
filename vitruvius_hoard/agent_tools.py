"""Tools exposed to the assistant. One catalogue drives /api/agent/* and mcp_server.py."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Any, Optional

from pydantic import BaseModel, Field, model_validator

from .hoard_link.agentkit import AppError, Empty, Tool, ann, call_tool as run_tool, tool_catalog as catalog_of
from .services import Services
from .app_projects import templates as app_templates
from .motion import Composition, MotionStore, page as motion_page, templates as motion_templates

AGENT_INSTRUCTIONS = """Vitruvius's Hoard is a design workbench: a cited library of design criterion, a render -> capture -> critique
loop on real Chromium, a design-system (tokens) generator with a playground, and a gallery of captured websites.
Always cite `[vitruvius: ...]` when quoting the library (design_search, design_brief, design_rules).
Loop: write HTML -> render_preview -> design_critique -> fix -> render again; stop at score >= 8 or after 3 rounds,
then page_assay it (drives every control in a real browser and reports what does not work).
Use design_brief before a page from scratch; styles_search / palettes_search / fonts_search for quick lookups.
Diagrams: diagram_types, then diagram_render (structure, Mermaid, Excalidraw, draw.io; isometric = one object); fix gates.
reference_add, source_add, source_ingest, tokens_delete and reference_delete change things: only when the user asks."""


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
    path: Optional[str] = Field(None, max_length=1000, description="A local .html file (or a folder holding index.html) already written to disk: use it instead of pasting the whole page into html.")
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
    path: Optional[str] = Field(None, max_length=1000, description="A local .html file (or a folder holding index.html) already written to disk: use it instead of pasting the whole page into html.")
    render_id: Optional[str] = Field(None, max_length=40)


class AssayArgs(BaseModel):
    html: Optional[str] = Field(None, max_length=2_000_000, description="The page to check (a complete HTML document).")
    url: Optional[str] = Field(None, max_length=2000, description="A URL whose HTML is downloaded and checked as a single page.")
    render_id: Optional[str] = Field(None, max_length=40, description="A previous render_preview of raw HTML (its saved source is reused).")
    path: Optional[str] = Field(None, max_length=1000, description="A local .html file or a folder holding index.html.")
    timeout_s: int = Field(300, ge=30, le=900)
    criteria: list[dict[str, Any]] = Field(default_factory=list, description="Optional explicit cases: id, what, acts (click/fill/press), expect (want/unchanged/painted), control. These supplement measured coverage with the requested behavior.")


class CritiqueArgs(BaseModel):
    render_id: Optional[str] = Field(None, max_length=40)
    html: Optional[str] = Field(None, max_length=2_000_000)
    url: Optional[str] = Field(None, max_length=2000)
    path: Optional[str] = Field(None, max_length=1000, description="A local .html file (or a folder holding index.html) already written to disk: use it instead of pasting the whole page into html.")
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

    @model_validator(mode="before")
    @classmethod
    def _accept_tokens_id(cls, data: Any) -> Any:
        """Other apps of the family say `tokens_id`; the catalogue keeps `id`."""
        if isinstance(data, dict) and "id" not in data and data.get("tokens_id"):
            return {**data, "id": data["tokens_id"]}
        return data


class TokensListArgs(BaseModel):
    limit: int = Field(30, ge=1, le=200)
    compact: bool = Field(False, description="Only id, name, created_ts and the colour/font/radius roles (no CSS or Tailwind text).")


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


class AppCreateArgs(BaseModel):
    name: str
    template: str = "work-board"
    description: str = ""
    accent: Optional[str] = None
    fields: Optional[list[dict]] = None


class AppIdArgs(BaseModel):
    id: str = ""
    revision: Optional[str] = None


class AppUpdateArgs(BaseModel):
    id: str = ""
    files: dict[str, str]
    expected_revision: str


class AppPreviewArgs(AppIdArgs):
    operation: Literal["start", "stop"] = "start"


class AppExportArgs(AppIdArgs):
    include_data: bool = False


class AppRenderArgs(AppIdArgs):
    widths: Optional[list[int]] = None


class AppCallArgs(BaseModel):
    id: str = ""
    operation: Literal["list", "get", "create", "update", "delete"]
    data: Optional[dict] = None
    record_id: Optional[str] = None
    query: str = ""


class CollectionImportArgs(BaseModel):
    path: str = Field(..., min_length=1, description="Local path to a portable reference collection JSON manifest.")


class DesignPatternArgs(BaseModel):
    id: str
    text: str = "FORM / FIELD"
    accent: str = Field("#e36a39", pattern="^#[0-9a-fA-F]{6}$")


class ReferenceSearchArgs(BaseModel):
    collection: Optional[str] = None
    before: Optional[str] = None
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


MAX_LOCAL_PAGE = 2_000_000


def read_local_page(path: str) -> str:
    """The HTML of a page the assistant already wrote to disk (a file, or a folder's index.html),
    so it does not have to paste the whole document again into html (slow for a local model)."""
    target = Path(path).expanduser()
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        raise ValueError(f"No such page: {path}")
    if target.suffix.lower() not in (".html", ".htm"):
        raise ValueError(f"Not an HTML file: {target.name}")
    if target.stat().st_size > MAX_LOCAL_PAGE:
        raise ValueError(f"{target.name} is larger than {MAX_LOCAL_PAGE // 1_000_000} MB")
    return target.read_text(encoding="utf-8", errors="replace")


def _page_html(args) -> Optional[str]:
    if args.html:
        return args.html
    if getattr(args, "path", None):
        return read_local_page(args.path)
    return None


def run_render_preview(services: Services, args: RenderArgs) -> dict:
    row = services.render(html=_page_html(args), url=args.url, widths=args.widths, full_page=args.full_page, dark=args.dark,
                          wait_ms=args.wait_ms, lint=args.lint, title=args.title)
    out = _strip_html(row)
    if not args.include_images:
        out["files"] = [{k: v for k, v in f.items() if k != "bytes"} for f in out["files"]]
    return out


def run_design_lint(services: Services, args: LintArgs) -> dict:
    return services.lint_html(html=_page_html(args), url=args.url, render_id=args.render_id)


def run_page_assay(services: Services, args: AssayArgs) -> dict:
    if not (args.html or args.url or args.render_id or args.path):
        raise ValueError("page_assay needs html, url, render_id or path")
    return services.assay_page(html=args.html, url=args.url, render_id=args.render_id, path=args.path, timeout_s=args.timeout_s, criteria=args.criteria)


def run_design_critique(services: Services, args: CritiqueArgs) -> dict:
    render_id = args.render_id
    if render_id is None:
        row = services.render(html=_page_html(args), url=args.url, widths=[390, 1024, 1440], full_page=True)
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
    keep = ("id", "name", "created_ts", "roles")
    return {"count": len(rows),
            "design_systems": [{k: v for k, v in r.items() if (k in keep if args.compact else k != "tokens")} for r in rows]}


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
    return services.reference_page(**args.model_dump())


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
        SearchArgs, ann(True), run_design_search),
    Tool("design_brief",
        "Design brief for a page/app: style, palette, fonts, rules, motion, anti-patterns. Brief de diseño.\n"
        "Deterministic composition (2-3 styles, one palette, one font pairing, rules by area, anti-patterns, checklist), all cited.\n"
        "Sinónimos: brief, dirección de arte, vibe, paleta, tipografía, para una landing, para una app.",
        BriefArgs, ann(True), run_design_brief),
    Tool("design_rules",
        "List design rules by area (typography, color, layout, motion, a11y, forms). Reglas de diseño.\n"
        "Filter by area/severity/source; rules with a check_id are enforced deterministically by design_lint.\n"
        "Sinónimos: reglas, buenas prácticas, do and don't, checklist.",
        RulesArgs, ann(True), run_design_rules),
    Tool("styles_search",
        "Find UI styles (glass, brutalist, swiss, aurora...) with tokens and when to use them. Estilos de UI.\n"
        "Catalog lookup over the ingested style library (colors, typography, effects, best_for, avoid).\n"
        "Sinónimos: estilo visual, brutalist, glassmorphism, swiss, aurora, retro-futurista.",
        StylesSearchArgs, ann(True), run_styles_search),
    Tool("palettes_search",
        "Find catalogued colour palettes by name or product type. Buscar paletas de color.\n"
        "Reads the palettes table (role/hex pairs) ingested from the catalog source.\n"
        "Sinónimos: paleta, colores, esquema de color.",
        PalettesSearchArgs, ann(True), run_palettes_search),
    Tool("fonts_search",
        "Find catalogued font pairings by mood or query. Buscar combinaciones de tipografías.\n"
        "Reads the font_pairings table (heading/body/mono, mood, Google Fonts URL).\n"
        "Sinónimos: tipografía, fuente, pareja de fuentes, mood tipográfico.",
        FontsSearchArgs, ann(True), run_fonts_search),
    Tool("render_preview",
        "Render HTML or a URL in Chromium, screenshot at widths, run lint. Renderiza y captura.\n"
        "Returns render id, absolute file paths, size, lint summary and metrics (fonts, colours, libs). Never returns "
        "image bytes unless include_images=true. A page already written to disk goes as path, not pasted into html.\nSinónimos: renderizar, capturar, screenshot, previsualizar.",
        RenderArgs, ann(False, False, False), run_render_preview),
    Tool("design_lint",
        "Deterministic design checks on HTML/URL (fonts, contrast, motion, a11y, generic-AI patterns). Lint de diseño.\n"
        "29 checks with stable ids; each finding has area, severity, evidence and a concrete fix.\n"
        "Sinónimos: lint, revisar diseño, patrones genéricos de IA, contraste, accesibilidad.",
        LintArgs, ann(True), run_design_lint),
    Tool("design_critique",
        "Critique a rendered page: score 0-10, findings with fixes, using lint + local vision model. Crítica de diseño.\n"
        "Merges deterministic lint with an optional vision-model rubric (hierarchy, typography, colour, motion, a11y, copy).\n"
        "Sinónimos: criticar, evaluar diseño, puntuación, feedback visual.",
        CritiqueArgs, ann(False, False, False), run_design_critique),
    Tool("page_assay",
        "Check observable page behavior in a real browser. Comprobar controles de una página.\n"
        "Uses Vitruvius's incorporated page checker: measures controls, derives a test plan, drives it and reports contradictions\n"
        "Explicit criteria verify requested effects; generic coverage cannot infer every intended effect. Takes ~15-60 s.\n"
        "Sinónimos: probar la página, comprobar botones, test funcional, assay, ¿funciona?, smoke test de UI.",
        AssayArgs, ann(True, False, False), run_page_assay),
    Tool("render_compare",
        "Pixel-diff two renders at a given width: percent changed + a diff image. Comparar dos renders.\n"
        "Sinónimos: comparar, diff visual, antes y después.",
        CompareArgs, ann(True), run_render_compare),
    Tool("tokens_generate",
        "Generate a design system: OKLCH palettes, type scale, spacing, motion tokens. Genera design system.\n"
        "Pure-Python OKLCH ramps (50-950), fluid type scale, spacing/radius/shadow/motion tokens, four export formats.\n"
        "Sinónimos: sistema de diseño, tokens, paleta OKLCH, tailwind theme.",
        TokensGenerateArgs, ann(False, False, False), run_tokens_generate),
    Tool("tokens_get",
        "Get a generated design system in json, css, tailwind or w3c format. Obtener design system.\n"
        "The json format also carries `roles`: colours per mode, font families and radii (other apps read these). "
        "Sinónimos: exportar tokens, css variables, tailwind theme, w3c tokens.",
        TokensGetArgs, ann(True), run_tokens_get),
    Tool("tokens_list",
        "List generated design systems. Listar design systems.\n"
        "Each carries its `roles` (colours, fonts, radii); compact=true returns only that. Sinónimos: listar tokens, sistemas guardados.",
        TokensListArgs, ann(True), run_tokens_list),
    Tool("tokens_preview",
        "Render the design system's live playground and lint it. Previsualizar design system.\n"
        "Sinónimos: preview, playground, ver el sistema de diseño.",
        TokensPreviewArgs, ann(False, False, False), run_tokens_preview),
    Tool("tokens_delete",
        "Delete a generated design system (only when the user asks). Eliminar design system.\n"
        "Sinónimos: borrar tokens, eliminar sistema de diseño.",
        TokensDeleteArgs, ann(False, True, True), run_tokens_delete),
    Tool("app_templates", "List original full application starters. Plantillas de aplicaciones completas.",
        Empty, ann(True), lambda services, args: {"templates": app_templates()}),
    Tool("app_project_create", "Create an editable application project with pages, typed data and its own server. Crear aplicación.",
        AppCreateArgs, ann(False, False, True), lambda services, args: services.app_projects.create(**args.model_dump()), capped=False),
    Tool("app_project_list", "List application projects, saved revisions and owned preview state. Listar aplicaciones.",
        Empty, ann(True), lambda services, args: {"projects": services.app_projects.list()}, capped=False),
    Tool("app_project_get", "Read a complete application source revision. Leer archivos y revisión de aplicación.",
        AppIdArgs, ann(True), lambda services, args: services.app_projects.get(args.id, args.revision), capped=False),
    Tool("app_project_update", "Save selected source files as a retained project revision. Editar archivos de aplicación.",
        AppUpdateArgs, ann(False, False, True), lambda services, args: services.app_projects.update(args.id, args.files, args.expected_revision), capped=False),
    Tool("app_project_preview", "Start or stop this project's owned local preview. Previsualizar aplicación.",
        AppPreviewArgs, ann(False, False, True), lambda services, args: services.app_projects.stop(args.id) if args.operation == "stop" else services.app_projects.preview(args.id, args.revision)),
    Tool("app_project_export", "Export a standalone source ZIP, optionally with SQLite data. Exportar aplicación autónoma.",
        AppExportArgs, ann(False, False, True), lambda services, args: services.app_projects.export(args.id, args.revision, args.include_data)),
    Tool("app_project_render", "Capture the exact owned preview into the usual render and critique workflow. Capturar aplicación.",
        AppRenderArgs, ann(False, False, True), lambda services, args: services.app_project_render(args.id, args.revision, args.widths)),
    Tool("app_project_call", "Use a project's typed record API: list, get, create, update or delete. Operar datos de aplicación.",
        AppCallArgs, ann(False, True, True), lambda services, args: services.app_project_call(args.id, args.operation, args.data, args.record_id, args.query)),
    Tool("reference_collections", "List imported local reference collections and their counts. Colecciones de referencias.",
        Empty, ann(True), lambda services, args: {"collections": services.reference_collections()}),
    Tool("reference_import_collection", "Import a local snapshot collection into the gallery. Importar colección local.\nRetains provenance and reuses identical versions; no source HTML is executed.",
        CollectionImportArgs, ann(False, False, True), lambda services, args: services.reference_import_collection(args.path), capped=False),
    Tool("design_patterns", "List eight original editable HTML design studies. Patrones de diseño propios.",
        Empty, ann(True), lambda services, args: {"patterns": services.design_patterns()}),
    Tool("design_pattern", "Generate editable standalone HTML from an original pattern. Generar patrón propio.\nLiteral text and accent colour; use render_preview, page_assay and design_critique to check the source.",
        DesignPatternArgs, ann(True), lambda services, args: services.design_pattern(**args.model_dump()), capped=False),
    Tool("reference_add",
        "Capture a website into the reference gallery: screenshots, video, fonts, palette. Guardar referencia.\n"
        "Desktop+mobile capture, optional 6s scroll video, Pillow palette, detected libs/motion, optional vision vibe tagging.\n"
        "Sinónimos: guardar web, referencia visual, galería, inspiración.",
        ReferenceAddArgs, ann(False, False, False), run_reference_add),
    Tool("reference_search",
        "Search the reference gallery by text, tags, vibe or library. Buscar referencias.\n"
        "Sinónimos: buscar referencias, galería, por tag, por vibe, por librería.",
        ReferenceSearchArgs, ann(True), run_reference_search, capped=False),
    Tool("reference_get",
        "Get one reference's full detail (files, palette, fonts, motion, analysis). Ver referencia.\n"
        "Sinónimos: detalle de referencia, ver captura.",
        ReferenceIdArgs, ann(True), run_reference_get),
    Tool("reference_delete",
        "Delete a reference from the gallery (only when the user asks). Eliminar referencia.\n"
        "Sinónimos: borrar referencia, quitar de la galería.",
        ReferenceIdArgs, ann(False, True, True), run_reference_delete),
    Tool("sources_list",
        "List every ingested design-criterion source and its status. Listar fuentes.\n"
        "Sinónimos: fuentes, repos ingeridos, estado de ingesta.",
        Empty, ann(True), run_sources_list),
    Tool("source_add",
        "Add a new source to ingest: a git repo, a local folder or a single page URL. Añadir fuente.\n"
        "Only when the user asks to add a new source; call source_ingest afterwards to actually ingest it.\n"
        "Sinónimos: añadir repositorio, nueva fuente, importar skill.",
        SourceAddArgs, ann(False, False, True), run_source_add),
    Tool("source_ingest",
        "Ingest (or re-ingest) one source or every source; runs in the background. Ingerir fuente.\n"
        "embeddings=true (re)builds the multilingual vectors (CPU, about a minute for the whole library).\n"
        "Sinónimos: ingerir, actualizar fuente, reindexar, clonar de nuevo.",
        SourceIngestArgs, ann(False, False, True), run_source_ingest),
    Tool("source_status",
        "Status of one source's ingest (idle, cloning, ingesting, ready, error). Estado de una fuente.\n"
        "Sinónimos: estado de ingesta, progreso, error de clonado.",
        SourceStatusArgs, ann(True), run_source_status),
    Tool("vitruvius_status",
        "Health: browser, ffmpeg, git, library counts, model resolution for vision/chat/embeddings. Estado del sistema.\n"
        "Sinónimos: estado, salud, ¿funciona el navegador?, modelos disponibles.",
        Empty, ann(True), run_vitruvius_status),
]

class MotionSaveArgs(BaseModel):
    composition: Composition
    id: Optional[str] = Field(None, pattern=r"^[0-9a-f]{32}$")
    expected_revision: Optional[int] = Field(None, ge=1)


class MotionGetArgs(BaseModel):
    id: str = Field(..., pattern=r"^[0-9a-f]{32}$")
    revision: Optional[int] = Field(None, ge=1)
    format: str = Field("json", pattern="^(json|html)$")
    at: float = Field(0, ge=0, le=60, allow_inf_nan=False)


class MotionRenderArgs(BaseModel):
    id: str = Field(..., pattern=r"^[0-9a-f]{32}$")
    revision: Optional[int] = Field(None, ge=1)
    at: float = Field(1, ge=0, le=60, allow_inf_nan=False)
    video: bool = False


def run_motion_save(services: Services, args: MotionSaveArgs):
    return MotionStore(services.config.data_dir).save(args.composition, args.id, args.expected_revision)


def run_motion_get(services: Services, args: MotionGetArgs):
    row = MotionStore(services.config.data_dir).get(args.id, args.revision)
    if args.format == "html":
        row["html"] = motion_page(Composition.model_validate(row["composition"]), at=args.at)
    return row


def run_motion_render(services: Services, args: MotionRenderArgs):
    import uuid
    row = MotionStore(services.config.data_dir).get(args.id, args.revision)
    composition = Composition.model_validate(row["composition"])
    if not args.video:
        return services.render(html=motion_page(composition, at=args.at), title=composition.title, lint=False)
    export_id = uuid.uuid4().hex
    output = services.config.renders_dir / export_id
    result = services.browser._submit("motion", {"composition": composition.model_dump(), "out_dir": str(output)})
    return {"export_id": export_id, "composition_id": row["id"], "revision": row["revision"], **result,
            "download": f"/api/renders/{export_id}/files/motion.mp4" if "error" not in result else None}


TOOLS.extend([
    Tool("motion_templates", "Editable motion templates. Plantillas de movimiento.\nKeywords: launch, portrait caption, comparison, anuncios, escenas.", Empty, ann(True), lambda svc, args: {"templates": motion_templates()}),
    Tool("motion_save", "Save a versioned composition. Guardar composición animada.\nUpdates require expected_revision. Keywords: animación, montaje, motion graphics.", MotionSaveArgs, ann(False, False, False), run_motion_save),
    Tool("motion_list", "List saved editable motion compositions. Keywords: proyectos, animaciones, motion.", Empty, ann(True), lambda svc, args: {"compositions": MotionStore(svc.config.data_dir).list()}),
    Tool("motion_get", "Read a composition or export HTML. Leer o exportar animación.\nKeywords: timeline, previsualización, motion, frame seeking.", MotionGetArgs, ann(True), run_motion_get),
    Tool("motion_render", "Capture motion frames or export silent MP4. Renderizar vídeo.\nChromium and ffmpeg; may take minutes. Keywords: render, vídeo, fotogramas, motion.", MotionRenderArgs, ann(False, False, False), run_motion_render),
])
from .diagrams.tools import tools as _diagram_tools  # noqa: E402

TOOLS.extend(_diagram_tools(Empty))
TOOLS.append(Tool("page_check", "Measure and test a page using Vitruvius's incorporated browser checker. Comprobar controles de una página.\nAccepts HTML, URL, a captured render or a local path. Reports actual cases, measurements and failures without a model or external application.",
                  AssayArgs, ann(True, False, False), run_page_assay))
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def tool_catalog() -> list[dict]:
    return catalog_of(TOOLS)


# Results that are the payload itself (a stylesheet, a page, image bytes) and must never be cut to the shared 20 KB cap.
UNCAPPED_TOOLS = frozenset({"tokens_get", "tokens_preview", "motion_get", "diagram_render", "diagram_get"})


def call_tool(services: Services, name: str, arguments: dict | None, *, cap: bool = True) -> Any:
    """Run one tool through the shared agent kit (argument validation, result cap). An expected "not found"
    (`LookupError`) keeps the 404 it always had; a bare `ValueError` is a 400 `invalid`."""
    if name in UNCAPPED_TOOLS or (name == "render_preview" and (arguments or {}).get("include_images")):
        cap = False
    try:
        return run_tool(TOOLS_BY_NAME, services, name, arguments, cap=cap)
    except LookupError as error:
        if isinstance(error, KeyError):  # an unknown tool: the router answers 404 unknown_tool itself
            raise
        raise AppError("not_found", str(error), status=404) from error
