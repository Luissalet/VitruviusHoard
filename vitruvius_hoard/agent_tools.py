"""Tools exposed to the assistant. One catalogue drives /api/agent/* and mcp_server.py."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Any, Optional

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
    tokens_id: Optional[str] = Field(None, max_length=40, description="A tokens_generate system: the page is also compared with it (ds/* rules).")


class LintArgs(BaseModel):
    html: Optional[str] = Field(None, max_length=2_000_000)
    url: Optional[str] = Field(None, max_length=2000)
    path: Optional[str] = Field(None, max_length=1000, description="A local .html file (or a folder holding index.html) already written to disk: use it instead of pasting the whole page into html.")
    render_id: Optional[str] = Field(None, max_length=40)
    tokens_id: Optional[str] = Field(None, max_length=40, description="A tokens_generate system: switches on the ds/* rules (fonts, colours, radii, type scale and spacing against the system).")
    packs: Optional[list[str]] = Field(None, description="Only these rule packs: core, slop, unslop, quality, craft, ds (design_rules_list shows them).")
    engines: Optional[list[str]] = Field(None, description="Only rules of these engines: static, browser, visual. [\"static\"] with html or path reads the source alone and starts no browser (fast; use it after each edit).")


class AssayArgs(BaseModel):
    html: Optional[str] = Field(None, max_length=2_000_000, description="The page to check (a complete HTML document).")
    url: Optional[str] = Field(None, max_length=2000, description="A URL whose HTML is downloaded and checked as a single page.")
    render_id: Optional[str] = Field(None, max_length=40, description="A previous render_preview of raw HTML (its saved source is reused).")
    path: Optional[str] = Field(None, max_length=1000, description="A local .html file or a folder holding index.html.")
    timeout_s: int = Field(300, ge=30, le=900)
    before: bool = Field(False, description="Before a redesign: also save the page's links, form fields, event handlers and titles; the result carries kept_saved.id.")
    kept: Optional[str] = Field(None, max_length=40, description="After a redesign: the id saved by an earlier `before`. The check fails when any saved link, field, handler or title is missing.")
    snapshot_only: bool = Field(False, description="With before: save the snapshot and skip driving the page.")
    label: str = Field("", max_length=200)
    criteria: list[dict[str, Any]] = Field(default_factory=list, description="Optional cases: id, what, acts (click/fill/press/hover/focus), expect (want/unchanged/painted/focused/no_overflow/no_motion), control. environment accepts viewport {width,height}, reduced_motion (reduce/no-preference), color_scheme (light/dark). Each case opens fresh and reports its measured state; local load/shift observations are not design certification.")


class CritiqueArgs(BaseModel):
    render_id: Optional[str] = Field(None, max_length=40)
    html: Optional[str] = Field(None, max_length=2_000_000)
    url: Optional[str] = Field(None, max_length=2000)
    path: Optional[str] = Field(None, max_length=1000, description="A local .html file (or a folder holding index.html) already written to disk: use it instead of pasting the whole page into html.")
    focus: Optional[str] = Field(None, max_length=200)
    use_vision: bool = True
    tokens_id: Optional[str] = Field(None, max_length=40, description="A tokens_generate system to compare the page with (ds/* rules).")
    waivers: list[dict[str, str]] = Field(default_factory=list, description="[{rule, reason}]: Reflex-tier (warning) rules left standing on purpose. The reason needs 24+ characters and may not repeat another waiver's; Floor (error) rules cannot be waived.")
    clean_review: bool = Field(False, description="Final review in a clean context: a fresh call to the global model with only the screenshots, the HTML and the findings. The verdict (recapture | rebuild | fix | ship) comes first; at most 8 findings.")


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
    theme: Optional[str] = Field(None, max_length=60, description="A theme slug (theme_list). Refused when it is one of the last three built or shares their paper/display/accent triple, unless force_theme.")
    deal: Optional[bool] = Field(None, description="Deal a theme from the memory of recent builds (reproducible: the result's theme.seed gives the same hand back) and fold its hue, fonts, radius style and density into whatever you left unsaid.")
    genre: Optional[str] = Field(None, pattern="^(editorial|modern-minimal|atmospheric|playful)$")
    seed: Optional[str] = Field(None, max_length=200)
    reroll: Optional[int] = Field(None, ge=0, le=20)
    force_theme: Optional[bool] = None
    preset: Optional[str] = Field(None, max_length=80, description="Build the whole system from a preset instead (design_preset_list), e.g. 'flexoki' or 'flexoki-orange'; the other fields except name are ignored.")


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


class GalleriesArgs(BaseModel):
    query: Optional[str] = Field(None, max_length=200, description="Words in English or Spanish: footer, CTA, hero, scroll, shader, glass, 3D icons, styles... Empty lists them all.")
    area: Optional[Literal["layout", "motion", "color", "typography", "components", "effects", "imagery", "iconography", "content"]] = None
    limit: int = Field(8, ge=1, le=30)


class GalleriesIngestArgs(BaseModel):
    ids: Optional[list[str]] = Field(None, description="Gallery ids from design_galleries; omit to capture every curated gallery.")
    video: bool = Field(False, description="Also record the 6 s scroll video of each sample (slower).")


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
                          wait_ms=args.wait_ms, lint=args.lint, title=args.title, tokens_id=args.tokens_id)
    out = _strip_html(row)
    if not args.include_images:
        out["files"] = [{k: v for k, v in f.items() if k != "bytes"} for f in out["files"]]
    return out


def run_design_lint(services: Services, args: LintArgs) -> dict:
    return services.lint_html(html=_page_html(args), url=args.url, render_id=args.render_id, tokens_id=args.tokens_id, packs=args.packs, engines=args.engines)


def run_page_assay(services: Services, args: AssayArgs) -> dict:
    if not (args.html or args.url or args.render_id or args.path):
        raise ValueError("page_assay needs html, url, render_id or path")
    return services.assay_page(html=args.html, url=args.url, render_id=args.render_id, path=args.path, timeout_s=args.timeout_s, criteria=args.criteria,
                              before=args.before, kept=args.kept, snapshot_only=args.snapshot_only, label=args.label)


def run_design_critique(services: Services, args: CritiqueArgs) -> dict:
    render_id = args.render_id
    if render_id is None:
        row = services.render(html=_page_html(args), url=args.url, widths=[390, 1024, 1440], full_page=True, tokens_id=args.tokens_id)
        render_id = row["id"]
    return services.critique_render(render_id, focus=args.focus, use_vision=args.use_vision, tokens_id=args.tokens_id,
                                    waivers=args.waivers, clean_review=args.clean_review)


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
    if args.preset:
        from . import presets
        applied = presets.apply(services, args.preset, title=args.name)
        row = services.tokens_get(applied["tokens_id"])
        out = {**row, "preset": applied["preset"]}
        pairs = applied.get("contrast_pairs")
        if pairs:
            worst = min(pairs, key=lambda c: c["ratio"])
            # a dict survives the result cap even when the pair list is shortened
            out["contrast"] = {"pairs": len(pairs), "aa": sum(1 for c in pairs if c["level"] != "fail"), "lowest": worst}
            out["contrast_pairs"] = pairs
        return out
    brief = {"name": args.name, "base_color": args.base_color, "hue": args.hue, "vibe": args.vibe, "theme": args.theme, "deal": args.deal,
             "genre": args.genre, "seed": args.seed, "reroll": args.reroll, "force_theme": args.force_theme,
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
        "Every rule is a row of data with a stable id (design_rules_list): core, slop, quality, craft and, with tokens_id, ds/* against a design system. Each finding has area, severity, tier (floor/reflex/finish), evidence and a concrete fix.\n"
        "Sinónimos: lint, revisar diseño, patrones genéricos de IA, contraste, accesibilidad.",
        LintArgs, ann(True), run_design_lint),
    Tool("design_critique",
        "Critique a rendered page: score 0-10, findings with fixes, using lint + local vision model. Crítica de diseño.\n"
        "Merges deterministic lint with an optional vision-model rubric (hierarchy, typography, colour, motion, a11y, copy). Tiers: Floor errors always block, Reflex warnings block unless waived on the record (waivers=[{rule, reason}], reason 24+ characters, never repeated), Finish advisories never block. gate.state is pass or fix. clean_review=true adds a fresh-context verdict: recapture, rebuild, fix or ship.\n"
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
        "preset='flexoki' (or another design_preset_list name) builds the system from that preset with its exact palette and contrast report.\n"
        "Sinónimos: sistema de diseño, tokens, paleta OKLCH, tailwind theme, flexoki.",
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
    Tool("design_galleries",
        "Find design galleries as references (footers, CTAs, heroes, scroll, glass...). Galerías de referencia.\n"
        "Covers scroll templates, scroll shaders, footers, CTAs, product styles, heroes, 3D icons and glass UI. "
        "Search by word (English or Spanish) or area (layout, motion, color, typography, components, effects, imagery, iconography, content). "
        "Each gallery gives its URL, what it provides, when to use it, its licence note and its captured sample pages (screenshots, palette and "
        "fragments: headings, CTA texts, footer links, glass/scroll/sticky signals) with a `[vitruvius: gallery/<id>]` cite.\n"
        "Sinónimos: referencias de footers, ejemplos de CTA, pies de página, llamadas a la acción, botones, heros, portadas, iconos 3D, "
        "glassmorphism, cristal, shaders, animación con scroll, estilos de producto, inspiración.",
        GalleriesArgs, ann(True), lambda services, args: {"galleries": services.galleries(query=args.query, area=args.area, limit=args.limit)}, capped=False),
    Tool("design_gallery_ingest",
        "Capture each design gallery's sample page into the reference gallery. Capturar muestras de galerías.\n"
        "Opens the sample page in Chromium (desktop and mobile), keeps screenshots, palette and fonts, and stores fragments (headings, hero text, "
        "CTA texts, nav and footer links, an excerpt of the footer HTML, glass/scroll/sticky/WebGL signals). Capturing again replaces that "
        "gallery's previous sample. About 10-30 s per gallery.\n"
        "Sinónimos: ingerir galerías, capturar referencias, actualizar muestras.",
        GalleriesIngestArgs, ann(False, False, True), lambda services, args: services.galleries_ingest(args.ids, video=args.video), capped=False, timeout_s=900),
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
    audio: Optional[bool] = Field(None, description="Sound in the MP4 (mixed to -14 LUFS). Default: whatever the composition's sound.enabled says.")


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
    payload: dict = {"composition": composition.model_dump(), "out_dir": str(output)}
    sound = None
    if args.audio if args.audio is not None else composition.sound.enabled:
        from . import sound as sound_mod
        try:
            sound = sound_mod.mix(composition, services.config.data_dir, output / "soundtrack.wav")
        except sound_mod.SoundUnavailable as error:
            return {"error": "sound engine unavailable", "hint": str(error), "composition_id": row["id"], "revision": row["revision"]}
        if sound.get("file"):
            payload["audio"] = sound["file"]
    result = services.browser._submit("motion", payload)
    out = {"export_id": export_id, "composition_id": row["id"], "revision": row["revision"], **result,
           "download": f"/api/renders/{export_id}/files/motion.mp4" if "error" not in result else None}
    if sound is not None:
        out["sound"] = {k: sound.get(k) for k in ("preset", "events", "skipped", "loudness", "max_error_ms", "silent", "reason") if k in sound}
        out["soundtrack"] = f"/api/renders/{export_id}/files/soundtrack.wav" if sound.get("file") else None
    return out


class MotionSoundArgs(BaseModel):
    id: Optional[str] = Field(None, pattern=r"^[0-9a-f]{32}$", description="A saved composition (with revision) ...")
    revision: Optional[int] = Field(None, ge=1)
    composition: Optional[Composition] = Field(None, description="... or the composition itself, not saved.")
    preset: Optional[str] = Field(None, pattern="^(calm|crisp|minimal|launch)$", description="Override the composition's sound preset.")


def _sound_composition(services: Services, args: MotionSoundArgs) -> tuple[Composition, Optional[dict]]:
    if args.composition is not None:
        composition, row = args.composition, None
    elif args.id:
        row = MotionStore(services.config.data_dir).get(args.id, args.revision)
        composition = Composition.model_validate(row["composition"])
    else:
        raise ValueError("Give id (a saved composition) or composition")
    if args.preset:
        composition = composition.model_copy(update={"sound": composition.sound.model_copy(update={"preset": args.preset})})
    return composition, row


def run_motion_sound_plan(services: Services, args: MotionSoundArgs):
    """What would be sounded, with no rendering: the engine status, the roles of the preset and the cues in time order."""
    from . import sound as sound_mod
    composition, row = _sound_composition(services, args)
    state = sound_mod.status()
    out = {"engine": state, "preset": composition.sound.preset, "enabled": composition.sound.enabled, "auto": composition.sound.auto,
           "duration_s": round(sum(s.duration for s in composition.scenes), 3), "events": sound_mod.plan(composition)}
    if row:
        out.update(id=row["id"], revision=row["revision"])
    if state["available"]:
        out["roles"] = sound_mod.roles(composition.sound.preset)
    return out


def run_motion_sound_render(services: Services, args: MotionSoundArgs):
    """Render the mix to a WAV at -14 LUFS and measure where each sound landed (no video, no browser)."""
    import uuid
    from . import sound as sound_mod
    composition, row = _sound_composition(services, args)
    export_id = uuid.uuid4().hex
    try:
        result = sound_mod.mix(composition, services.config.data_dir, services.config.renders_dir / export_id / "soundtrack.wav")
    except sound_mod.SoundUnavailable as error:
        return {"available": False, "error": "sound engine unavailable", "hint": str(error)}
    result["export_id"] = export_id
    result["download"] = f"/api/renders/{export_id}/files/soundtrack.wav" if result.get("file") else None
    if row:
        result.update(composition_id=row["id"], revision=row["revision"])
    return result


TOOLS.extend([
    Tool("motion_templates", "Editable motion templates. Plantillas de movimiento.\nKeywords: launch, portrait caption, comparison, anuncios, escenas.", Empty, ann(True), lambda svc, args: {"templates": motion_templates()}),
    Tool("motion_save", "Save a versioned composition. Guardar composición animada.\nUpdates require expected_revision. Keywords: animación, montaje, motion graphics.", MotionSaveArgs, ann(False, False, False), run_motion_save),
    Tool("motion_list", "List saved editable motion compositions. Keywords: proyectos, animaciones, motion.", Empty, ann(True), lambda svc, args: {"compositions": MotionStore(svc.config.data_dir).list()}),
    Tool("motion_get", "Read a composition or export HTML. Leer o exportar animación.\nKeywords: timeline, previsualización, motion, frame seeking.", MotionGetArgs, ann(True), run_motion_get),
    Tool("motion_render", "Capture motion frames or export MP4 (sound if enabled). Renderizar vídeo.\nChromium and ffmpeg; may take minutes. With sound.enabled the MP4 carries a -14 LUFS mix of code-made effects placed on the cues. Keywords: render, vídeo, fotogramas, motion, audio, sonido.", MotionRenderArgs, ann(False, False, False), run_motion_render),
    Tool("motion_sound_plan", "Plan the sound of a composition. Planificar sonido.\nWhich cues get which effect (scene changes, text, shapes and your {t, rol} events), the preset's roles and the engine status; renders nothing. Keywords: sonido, efectos, audio, motion, eventos.", MotionSoundArgs, ann(True), run_motion_sound_plan),
    Tool("motion_sound_render", "Mix the sound of a composition to a WAV. Mezclar sonido.\nPlaces each effect by its measured onset or peak, masters to -14 LUFS (-1 dBTP) and reports where every sound landed and the error in ms. Keywords: sonido, mezcla, LUFS, audio, motion.", MotionSoundArgs, ann(False, False, False), run_motion_sound_render),
])
class SiteAuditArgs(BaseModel):
    url: str = Field(..., min_length=3, max_length=2000, description="The site to audit (its home page); https:// is assumed when missing.")
    max_pages: int = Field(10, ge=1, le=40, description="Pages to read: the home page, then those of the sitemap and of its links.")
    check_links: bool = Field(True, description="Also request the internal and external links found (up to 40 and 15) to find broken ones.")
    vitals: bool = Field(True, description="Measure LCP, CLS, INP, FCP, TTFB and TBT in a real Chromium load (lab data). Off: that category is left unmeasured.")
    fresh: bool = Field(False, description="Audit again even when a report of this url younger than 10 minutes exists.")


class SiteAuditReportsArgs(BaseModel):
    id: Optional[str] = Field(None, max_length=60, pattern=r"^[0-9a-z-]{8,40}$", description="A report id: returns that whole report. Omit it to list the latest ones.")
    url: Optional[str] = Field(None, max_length=2000, description="Only the reports of this url (list).")
    limit: int = Field(20, ge=1, le=100)


def run_site_audit(services: Services, args: SiteAuditArgs):
    from . import seo_audit
    try:
        return seo_audit.run(services, args.url, max_pages=args.max_pages, check_links=args.check_links, vitals=args.vitals, fresh=args.fresh)
    except seo_audit.AuditError as error:
        raise ValueError(str(error)) from error


def run_site_audit_reports(services: Services, args: SiteAuditReportsArgs):
    from . import seo_audit
    store = seo_audit.ReportStore(services.config.data_dir)
    if args.id:
        report = store.get(args.id)
        if report is None:
            raise AppError("not_found", f"No hay informe {args.id}.", hint="Lista los informes con site_audit_reports sin id.")
        return report
    url = seo_audit.normalize_url(args.url) if args.url else None
    return {"reports": store.list(url, args.limit)}


TOOLS.extend([
    Tool("site_audit", "Audit a site for SEO and AI search. Auditoría SEO/GEO determinista.\nIndexability, robots, sitemap, canonicals, security headers, broken links, JSON-LD, Core Web Vitals in a real browser, AI crawlers (training vs citing), images. Returns score, categories with findings, action plan; judgement items are flagged and not scored. Takes 30-90 s. Keywords: SEO, GEO, posicionamiento, rastreadores IA, sitemap, robots, vitals.",
         SiteAuditArgs, ann(False, False, True, True), run_site_audit, timeout_s=240),
    Tool("site_audit_reports", "List or read saved site audits. Informes de auditoría SEO.\nWithout id: the latest reports (url, date, score). With id: the whole report, to compare runs. Keywords: auditoría, informe, deriva, vigilancia.",
         SiteAuditReportsArgs, ann(True), run_site_audit_reports),
])


# ---------------- marks (logos) ----------------

_HEX = r"^#?[0-9a-fA-F]{6}$"


class MarkAuditArgs(BaseModel):
    path: Optional[str] = Field(None, max_length=2000, description="A local image file: PNG, JPG, WebP, GIF, BMP, ICO or SVG.")
    data: Optional[str] = Field(None, max_length=22_000_000, description="The image as base64 or a data: URL (what the screen uploads).")
    svg: Optional[str] = Field(None, max_length=2_000_000, description="SVG markup, drawn at 512 px on white by the local browser.")
    name: str = Field("", max_length=120, description="A label for the history (defaults to the file name).")
    backgrounds: list[Annotated[str, Field(pattern=_HEX)]] = Field(default_factory=list, max_length=6, description="Extra grounds for the test sheet, #rrggbb (brand colours).")


class MarkSheetArgs(BaseModel):
    id: Optional[str] = Field(None, pattern=r"^[0-9a-f]{12}$", description="An audited mark: redraw its sheet with these grounds.")
    path: Optional[str] = Field(None, max_length=2000)
    data: Optional[str] = Field(None, max_length=22_000_000)
    svg: Optional[str] = Field(None, max_length=2_000_000)
    backgrounds: list[Annotated[str, Field(pattern=_HEX)]] = Field(default_factory=list, max_length=6, description="Extra grounds, #rrggbb.")


class MarkReportsArgs(BaseModel):
    id: Optional[str] = Field(None, pattern=r"^[0-9a-f]{12}$", description="A mark audit id: the whole report. Omit to list the latest.")
    limit: int = Field(20, ge=1, le=100)


def run_mark_audit(services: Services, args: MarkAuditArgs):
    from . import mark_audit
    return mark_audit.audit(services.config.data_dir, getattr(services, "browser", None), path=args.path, data=args.data,
                            svg=args.svg, name=args.name, backgrounds=args.backgrounds)


def run_mark_test_sheet(services: Services, args: MarkSheetArgs):
    from . import mark_audit
    return mark_audit.test_sheet(services.config.data_dir, getattr(services, "browser", None), mark_id=args.id, path=args.path,
                                 data=args.data, svg=args.svg, backgrounds=args.backgrounds)


def run_mark_reports(services: Services, args: MarkReportsArgs):
    from . import mark_audit
    if args.id:
        return mark_audit.get_report(services.config.data_dir, args.id)
    return {"reports": mark_audit.list_reports(services.config.data_dir, args.limit)}


TOOLS.extend([
    Tool("mark_audit", "Audit a logo or brand mark. Auditoría de logotipo.\nScores 0-100 (100 - 25 per fail, 8 per warning, 1 per note): works in one colour, contrast on light and dark grounds, legible at 32 and 16 px (favicon), number of colours, aspect ratio, margin and centring, transparent background, excess detail. Saves a test sheet PNG (sheet_path). Pass path, data (base64) or svg. Keywords: logo, marca, favicon, monocromo, invertido, identidad.",
         MarkAuditArgs, ann(False, False, False), run_mark_audit, timeout_s=90),
    Tool("mark_test_sheet", "Draw a logo test sheet. Hoja de prueba de logotipo.\nThe mark on light, dark and grey grounds, in one colour, inverted, at 128/64/32/16 px and magnified; add brand grounds with backgrounds. With id it redraws an audited mark. Keywords: hoja de prueba, fondos, tamaños, favicon.",
         MarkSheetArgs, ann(False, False, True), run_mark_test_sheet, timeout_s=90),
    Tool("mark_reports", "List or read logo audits. Auditorías de logotipo guardadas.\nWithout id: latest audits (name, score, verdict). With id: the whole report. Keywords: historial, logos, marcas.",
         MarkReportsArgs, ann(True), run_mark_reports),
])

from .diagrams.tools import tools as _diagram_tools  # noqa: E402

TOOLS.extend(_diagram_tools(Empty))
TOOLS.append(Tool("page_check", "Measure and test a page using Vitruvius's incorporated browser checker. Comprobar controles de una página.\nAccepts HTML, URL, a captured render or a local path. Reports actual cases, measurements and failures without a model or external application.",
                  AssayArgs, ann(True, False, False), run_page_assay))
# ---------------- rules as data, themes with memory, what a redesign keeps ----------------

class RulesListArgs(BaseModel):
    id: Optional[str] = Field(None, max_length=80, description="One rule by id (or alias): returns its full row.")
    engine: Optional[str] = Field(None, pattern="^(static|browser|visual)$")
    scope: Optional[str] = Field(None, max_length=20)
    severity: Optional[str] = Field(None, pattern="^(error|warning|advisory)$")
    tier: Optional[str] = Field(None, pattern="^(floor|reflex|finish)$")
    pack: Optional[str] = Field(None, max_length=24, description="core, slop, unslop, quality, craft, visual or ds.")
    source: Optional[str] = Field(None, max_length=24, description="Where the idea comes from: vitruvius, impeccable, hallmark or unslop.")
    query: Optional[str] = Field(None, max_length=120)
    runnable: Optional[bool] = Field(None, description="false = the judged (visual) rules the vision model decides.")
    limit: int = Field(300, ge=1, le=400)
    compact: bool = Field(False, description="Only id, engine, scope, severity, tier and name.")
    lang: Optional[Literal["es", "en"]] = Field(None, description="es = names, descriptions and fixes in Spanish (Spain); en or omitted = English.")


def run_design_rules_list(services: Services, args: RulesListArgs) -> dict:
    if args.id:
        return {"rule": services.rule_get(args.id, args.lang)}
    out = services.rules_list(engine=args.engine, scope=args.scope, severity=args.severity, tier=args.tier, pack=args.pack, source=args.source,
                              query=args.query, runnable=args.runnable, lang=args.lang)
    rows = out["rules"][: args.limit]
    if args.compact:
        rows = [{k: r[k] for k in ("id", "engine", "scope", "severity", "tier", "name")} for r in rows]
    return {"count": out["count"], "shown": len(rows), "summary": out["summary"], "rules": rows}


class ThemeListArgs(BaseModel):
    genre: Optional[str] = Field(None, pattern="^(editorial|modern-minimal|atmospheric|playful)$")
    query: Optional[str] = Field(None, max_length=120)


def run_theme_list(services: Services, args: ThemeListArgs) -> dict:
    from . import themes
    q = (args.query or "").lower()
    rows = [themes.public(t) for t in themes.load() if (not args.genre or t["genre"] == args.genre)
            and (not q or q in (t["slug"] + " " + t["name"] + " " + " ".join(t["keywords"]) + " " + t["material"]).lower())]
    return {"count": len(rows), "themes": rows}


class ThemeDealArgs(BaseModel):
    prompt: str = Field("", max_length=600, description="What the page is for, in the user's words.")
    genre: Optional[str] = Field(None, pattern="^(editorial|modern-minimal|atmospheric|playful)$")
    n: int = Field(3, ge=1, le=6)
    reroll: int = Field(0, ge=0, le=20, description="1 = the next hand, 2 = the one after...")
    seed: Optional[str] = Field(None, max_length=200, description="A seed a previous deal printed: the same hand comes back.")


class ThemeCheckArgs(BaseModel):
    axes: Optional[str] = Field(None, max_length=120, description="paper/display/accent, e.g. light/roman-serif/warm. paper: light|mid|dark.")
    face: Optional[str] = Field(None, max_length=80, description="The display face you plan to use.")
    hue: Optional[float] = Field(None, ge=0, le=360, description="The accent hue.")


class ThemeMemoryArgs(BaseModel):
    limit: int = Field(10, ge=1, le=50)


class KeptArgs(BaseModel):
    id: Optional[str] = Field(None, max_length=40, description="One saved snapshot (with its links, fields, handlers and titles); omit to list.")
    limit: int = Field(30, ge=1, le=200)


def run_kept(services: Services, args: KeptArgs) -> dict:
    if args.id:
        return services.kept_get(args.id)
    rows = services.kept_list(args.limit)
    return {"count": len(rows), "kept": rows}


TOOLS.extend([
    Tool("design_rules_list",
        "Design rules as data (id, engine, severity, tier). Reglas de diseño como datos.\n"
        "Each row: id, engine, scope, severity, tier, name, description, reference.\n"
        "Engines: static (HTML/CSS text), browser (what Chromium measured), visual (judged from screenshots). Severity maps to a tier: "
        "error = Floor, warning = Reflex, advisory = Finish. Packs: core, slop, quality, craft, visual, ds (against a design system). "
        "Each row says where the idea comes from (source, source_id).\nSinónimos: catálogo de reglas, lint rules, qué comprueba el lint, packs.",
        RulesListArgs, ann(True), run_design_rules_list, capped=False),
    Tool("theme_list", "List art-direction themes. Temas de dirección de arte.\nPaper, display face, accent, posture and material per theme.\nSinónimos: temas, estilos de página, catálogo de temas.",
        ThemeListArgs, ann(True), run_theme_list, capped=False),
    Tool("theme_deal",
        "Deal themes clear of the last three builds. Repartir temas.\n"
        "Blocks the last 3 themes and any sharing their paper/display/accent triple; reproducible by seed; reroll for another hand.\n"
        "Sinónimos: elegir tema, dirección de arte, evitar repetir, semilla.",
        ThemeDealArgs, ann(True), lambda services, args: services.theme_deal(**args.model_dump())),
    Tool("theme_check",
        "Check a plan against catalogue themes and recent builds. Comprobar un tema.\nAxes, display face and accent hue; says what it lands on.\nSinónimos: colisión de tipografía, parecido con otro tema, ¿es original?",
        ThemeCheckArgs, ann(True), lambda services, args: services.theme_check(**args.model_dump())),
    Tool("theme_memory", "Themes built recently, which theme_deal avoids. Memoria de temas.\nSinónimos: historial de temas, qué se usó, últimos temas.",
        ThemeMemoryArgs, ann(True), lambda services, args: {"memory": services.theme_memory(args.limit)}),
    Tool("page_kept",
        "Snapshots of what a redesign must keep. Lo que un rediseño debe conservar.\n"
        "Links, form fields, event handlers and titles.\n"
        "Create one with page_check/page_assay before=true; compare after the redesign with kept=<id>.\nSinónimos: antes y después, conservar enlaces, no perder campos.",
        KeptArgs, ann(True), run_kept, capped=False),
])

# ---------------- slop audit, direction brief, presets, Figma import ----------------

class SlopAuditArgs(BaseModel):
    render_id: Optional[str] = Field(None, max_length=40, description="Audit a stored render (re-rendered at 8 widths when it has fewer than 5 and its source is kept).")
    html: Optional[str] = Field(None, max_length=2_000_000)
    url: Optional[str] = Field(None, max_length=2000)
    path: Optional[str] = Field(None, max_length=1000, description="A local .html file or a folder holding index.html.")
    widths: Optional[list[int]] = Field(None, description="Default 320, 375, 414, 768, 1024, 1280, 1440, 1920.")
    rerender: Optional[bool] = Field(None, description="With render_id: force (true) or skip (false) the 8-width re-render.")
    full: bool = Field(False, description="Return every finding with its boxes (large); default is the compact plan.")
    lang: Optional[Literal["es", "en"]] = Field(None, description="Language of titles, details, fixes, pass names and summaries: es (Spanish, Spain; default) or en.")


def run_design_slop_audit(services: Services, args: SlopAuditArgs) -> dict:
    from . import slop_audit
    if not (args.render_id or args.html or args.url or args.path):
        raise ValueError("design_slop_audit needs render_id, html, url or path")
    out = slop_audit.run(services, render_id=args.render_id, html=_page_html(args), url=args.url, widths=args.widths, rerender=args.rerender,
                         lang=args.lang)
    if args.full:
        return out
    shots = {s["width"]: str(services.config.renders_dir / out["render_id"] / s["file"]) for s in out["screenshots"]}
    findings = [{"rule": f["check_id"], "title": f["title"], "pass": f["pass"], "tier": f.get("tier"), "slop": f["slop"],
                 "widths": (f.get("evidence") or {}).get("widths") if isinstance(f.get("evidence"), dict) else None} for f in out["findings"]]
    return {k: out[k] for k in ("render_id", "slop_score", "mode", "signs", "sign_ids", "by_pass", "plan", "rules_run", "ms", "credit", "lang")} | {
        "findings": findings, "screenshots": shots, "ui": f"/design/#/critique/{out['render_id']}"}


class DirectionBriefArgs(BaseModel):
    render_id: Optional[str] = Field(None, max_length=40)
    html: Optional[str] = Field(None, max_length=2_000_000)
    url: Optional[str] = Field(None, max_length=2000)
    path: Optional[str] = Field(None, max_length=1000)
    text: Optional[str] = Field(None, max_length=20000, description="The page's text, when you already have it.")
    use_model: bool = Field(True, description="false = the deterministic brief from the theme catalogue, no model call.")
    lang: Optional[Literal["es", "en"]] = Field(None, description="Language the brief is written in: es (Spanish, Spain; default) or en.")


def run_design_direction_brief(services: Services, args: DirectionBriefArgs) -> dict:
    from . import slop_audit
    return slop_audit.direction_brief(services, render_id=args.render_id, html=_page_html(args), url=args.url, text=args.text, use_model=args.use_model,
                                      lang=args.lang)


class PresetListArgs(BaseModel):
    name: Optional[str] = Field(None, max_length=80, description="One preset in full (tokens light/dark, radius, fonts, spacing, motion) plus its shadcn registry item.")
    source: Optional[Literal["vitruvius", "flexoki", "hallmark", "hoard"]] = None
    query: Optional[str] = Field(None, max_length=120)
    limit: int = Field(60, ge=1, le=200)


def run_design_preset_list(services: Services, args: PresetListArgs) -> dict:
    from . import presets
    if args.name:
        p = presets.get(args.name)
        if p is None:
            raise LookupError(f"Unknown preset '{args.name}'.")
        return {"preset": p, "registry_item": presets.registry_item(p), "registry_url": f"/api/design/registry/{p['name']}.json"}
    rows = presets.listing(source=args.source, query=args.query, limit=args.limit)
    return {"count": len(rows), "total": len(presets.catalogue()), "presets": rows}


class PickThemesArgs(BaseModel):
    brief: str = Field(..., min_length=3, max_length=2000, description="What the design is for, in the user's words.")
    n: int = Field(3, ge=1, le=6)
    use_model: bool = Field(True, description="false = keyword ranking only.")


def run_design_pick_themes(services: Services, args: PickThemesArgs) -> dict:
    from . import presets
    return presets.pick(services, args.brief, n=args.n, use_model=args.use_model)


class PresetApplyArgs(BaseModel):
    preset: str = Field(..., max_length=80, description="A preset name from design_preset_list or design_pick_themes.")
    tokens_id: Optional[str] = Field(None, max_length=40, description="The design system to change; omit to create a new one from the whole preset.")
    parts: Optional[list[Literal["colors", "radius", "type", "spacing", "motion"]]] = Field(None, description="Which parts to apply (default colors, radius, type).")
    name: Optional[str] = Field(None, max_length=120, description="Name of the new design system (when tokens_id is omitted).")


def run_design_preset_apply(services: Services, args: PresetApplyArgs) -> dict:
    from . import presets
    return presets.apply(services, args.preset, tokens_id=args.tokens_id, parts=list(args.parts) if args.parts else None, title=args.name)


class FigmaImportArgs(BaseModel):
    link: Optional[str] = Field(None, max_length=2000, description="Link to a Figma frame (https://www.figma.com/design/<key>/...?node-id=12-34). Needs the token saved in Settings.")
    nodes_json: Optional[dict[str, Any]] = Field(None, description="Instead of fetching: the JSON answer of GET /v1/files/:key/nodes (works without a token).")
    image_base64: Optional[str] = Field(None, max_length=20_000_000, description="With nodes_json: Figma's PNG of the frame, to compare.")
    make_tokens: bool = Field(True, description="Also create a design system from the frame's colours, fonts and radii.")
    critique: bool = Field(True, description="Run the critique on the rendered import.")


def run_design_figma_import(services: Services, args: FigmaImportArgs) -> dict:
    import base64
    from . import figma
    if not (args.link or args.nodes_json):
        raise ValueError("design_figma_import needs link or nodes_json")
    png = base64.b64decode(args.image_base64) if args.image_base64 else None
    try:
        return figma.import_frame(services, link=args.link, nodes_json=args.nodes_json, image_png=png, make_tokens=args.make_tokens, critique=args.critique)
    except PermissionError as error:
        raise AppError("not_configured", str(error), hint=figma.TOKEN_HELP) from error


TOOLS.extend([
    Tool("design_slop_audit",
        "Audit a page for the generated look and plan the fix. Auditoría de slop.\n"
        "Renders at 8 widths (320-1920), runs the slop, unslop, craft, quality and core rules, scores the slop 0-100 (0 = clean) and decides "
        "the mode: heavy = ordered fix passes (spacing, color, icons, copy, type, layout, details, visuals, motion), light = a short polish list, "
        "none = leave it. Each finding names its pass, tier and the widths where it fired. Sign list: unslop by Damir Sokolovsky (CC BY 4.0).\n"
        "Sinónimos: slop, parece hecho por IA, genérico, plantilla, unslop, desgenerizar, plan de arreglo.",
        SlopAuditArgs, ann(False, False, False), run_design_slop_audit, timeout_s=240),
    Tool("design_direction_brief",
        "Write the five-line design direction of a page from its own text. Dirección de diseño.\n"
        "Product / Character / Bright moment / Signature / Avoid, by the family model; falls back to the theme catalogue when no model answers. "
        "Avoid lists the slop signs already found on that render.\nSinónimos: dirección de arte, carácter, brief de rediseño, qué evitar.",
        DirectionBriefArgs, ann(True, False, False), run_design_direction_brief, timeout_s=180),
    Tool("design_preset_list",
        "List design presets, or read one in full. Presets de diseño.\n"
        "120+ presets: authored ones, Flexoki (ink on paper, MIT: exact palette, one preset per accent, every text pair AA), one per hallmark theme "
        "and the Hoard family palettes; each with light/dark colour roles (shadcn names), "
        "radius, fonts, spacing, motion and character. name=... returns the preset and its shadcn registry-item.json.\n"
        "Sinónimos: temas, paletas, presets, registry, shadcn, estilo base, flexoki, tinta sobre papel.",
        PresetListArgs, ann(True), run_design_preset_list, capped=False),
    Tool("design_pick_themes",
        "Pick three presets for a brief, one recommended. Elegir tema para un brief.\n"
        "Keyword ranking over the catalogue, re-ranked with reasons by the family model when it answers.\n"
        "Sinónimos: qué estilo usar, elegir paleta, propuesta de temas, tres opciones.",
        PickThemesArgs, ann(True, False, False), run_design_pick_themes, timeout_s=120),
    Tool("design_preset_apply",
        "Apply a preset (all, or only colours / radius / type / spacing / motion) to a design system. Aplicar preset.\n"
        "Without tokens_id a new design system is created from the whole preset; CSS and Tailwind exports are rebuilt.\n"
        "Sinónimos: aplicar tema, cambiar colores, cambiar tipografía, cambiar radios.",
        PresetApplyArgs, ann(False, False, True), run_design_preset_apply),
    Tool("design_figma_import",
        "Import a Figma frame as spec, HTML/CSS and design project, compared with Figma. Importar de Figma.\n"
        "Auto-layout becomes flex, repeated styles become named style ids; the page is rendered, a design system is extracted, the "
        "critique runs and the pixel difference with Figma's PNG is measured. Needs the Figma token in Settings, or pass nodes_json.\n"
        "compare.diff_pct covers the canvas of both images: rows only one has (truncated render, extra footer) count as different. "
        "compare.scope is full, normalized (render scaled to the frame width: render_scale; flat padding of the 900px capture "
        "viewport below a shorter frame dropped: viewport_fill_rows) or partial (heights differ: coverage, "
        "missing_rows, extra_rows, overlap_diff_pct); both sizes are given. A pixel measure, not semantic equivalence.\n"
        "Sinónimos: figma, importar diseño, frame, de diseño a código.",
        FigmaImportArgs, ann(False, False, True, True), run_design_figma_import, timeout_s=240),
])

TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def tool_catalog() -> list[dict]:
    return catalog_of(TOOLS)


# Results that are the payload itself (a stylesheet, a page, image bytes) and must never be cut to the shared 20 KB cap.
UNCAPPED_TOOLS = frozenset({"tokens_get", "tokens_preview", "motion_get", "diagram_render", "diagram_get",
                            "diagram_document_get", "diagram_document_save", "diagram_document_edit", "diagram_document_undo", "diagram_document_import", "diagram_document_compare",
                            "site_audit", "site_audit_reports"})


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


# ---------------- protocols ----------------

class ProtocolArgs(BaseModel):
    action: Literal["examples", "example", "check", "replay", "test"] = Field(
        "check", description="examples: list bundled protocols; example: get one (example=id); check: explore every interleaving "
        "of spec (bounded) and return the shortest counterexample; replay: run a schedule step by step; test: pytest file that "
        "replays the counterexample against the real system (hooks to fill in).")
    spec: Optional[dict[str, Any]] = Field(None, description="Protocol: vars (shared state), const, processes [{name, count, locals, "
        "steps [{label, when, set {var: expr}, goto | choose [...]}], crash {max, restart, keep_locals}}], invariants "
        "[{name, check}], at_end [{name, check}], deadlock, max_states. Expressions: Python-like subset (and/or/not, "
        "comparisons, in, + - * // %, x if c else y, literals, len/min/max/abs/sorted/append/put/without/set_add/set_remove).")
    example: Optional[str] = Field(None, max_length=60)
    schedule: Optional[list[list[Any]]] = Field(None, description="replay: [[process, label, 'step'|'crash', branch?], ...] as returned by check; branch is zero-based")
    time_limit: float = Field(60, gt=0, le=3600, description="check/test: seconds of exploration")


def run_protocol_check(services: Services, args: ProtocolArgs):
    from .protocols import SpecError, counterexample_test, explore, load_spec, replay
    from .protocols.examples import EXAMPLES
    if args.action == "examples":
        return {"examples": [{"id": k, "name": f()["name"], "doc": (f.__doc__ or "").strip()} for k, f in EXAMPLES.items()]}
    if args.action == "example":
        if args.example not in EXAMPLES:
            raise ValueError(f"no existe el ejemplo {args.example!r}; disponibles: {', '.join(EXAMPLES)}")
        return {"id": args.example, "spec": EXAMPLES[args.example]()}
    if not args.spec:
        raise ValueError("falta spec")
    try:
        spec = load_spec(args.spec)
        if args.action == "check":
            return explore(spec, time_limit=args.time_limit)
        if args.action == "replay":
            if args.schedule is None:
                raise ValueError("falta schedule")
            return replay(spec, args.schedule)
        result = explore(spec, time_limit=args.time_limit)
        if not result["violation"]:
            raise ValueError("no hay contraejemplo que convertir en test: " + result["status"])
        return {"code": counterexample_test(spec, result["violation"]), "violation": result["violation"]}
    except SpecError as error:
        raise ValueError(str(error)) from error


TOOLS.append(Tool(
    "protocol_check",
    "Explore every interleaving of a bounded protocol and find the shortest counterexample. Comprobar un protocolo.\n"
    "Shared state, processes of atomic labelled steps, nondeterministic choices, bounded crashes with restart, invariants, "
    "end conditions and deadlock. Breadth-first: a violation comes with the shortest schedule, a replay and a pytest file to "
    "reproduce it on the real system; 'holds' means every reachable state within the bounds was checked, under the listed "
    "assumptions (the model, not the code).\n"
    "Sinónimos: verificar protocolo, condición de carrera, doble cobro, idempotencia, reintentos, interbloqueo, deadlock, "
    "intercalaciones, contraejemplo, model checking, comprobar concurrencia.",
    ProtocolArgs, ann(True), run_protocol_check))
TOOLS_BY_NAME[TOOLS[-1].name] = TOOLS[-1]

from .study_tools import tools as _study_tools  # noqa: E402

TOOLS.extend(_study_tools())

from .parity_tools import tools as _parity_tools  # noqa: E402

TOOLS.extend(_parity_tools())

from .remake_tools import tools as _remake_tools  # noqa: E402

TOOLS.extend(_remake_tools())
TOOLS_BY_NAME.update({t.name: t for t in TOOLS})
