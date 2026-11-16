"""Legacy-pattern scan: deterministic rules that point at older code a web platform feature now replaces.

Each rule is data: a pattern, the kinds of file it reads, optional file-level conditions (``present`` must also match somewhere in
the file, ``absent`` must not, ``min`` is the number of hits that makes it worth saying) and the guide that holds the native
alternative. A finding is a *candidate*: ``keep_when`` says when the old pattern is the right call (a fallback, a library that
does more than the native feature), so a person or an agent confirms it before editing. Original rules; the guides they cite are
the vendored Apache-2.0 collection (see ``UPSTREAM.md``).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from . import CITE

KIND_OF_EXT = {".html": "html", ".htm": "html", ".css": "css", ".scss": "css", ".less": "css", ".js": "js", ".mjs": "js", ".cjs": "js",
               ".jsx": "js", ".ts": "js", ".tsx": "js", ".vue": "html", ".svelte": "html", ".php": "html", ".jinja": "html", ".j2": "html"}
SKIP_DIRS = {"node_modules", "venv", ".venv", "env", "dist", "build", ".git", "__pycache__", ".next", ".nuxt", "coverage", "site-packages",
             "vendor", "vendors", "third_party", "bower_components", ".faustus", "data", "dist-icons"}
SKIP_NAME = re.compile(r"(\.min\.|\.bundle\.|-bundle\.|\.chunk\.|three\.module|jquery[-.\d]|\.map$)", re.I)
MAX_BYTES = 800_000

ALL = {"html", "css", "js"}

# id, kinds, pattern, extras, guide, native (en), native_es, keep_when, name_es
RULES: list[dict] = [
    {"id": "float-layout", "kinds": {"css", "html"}, "pattern": r"\bfloat\s*:\s*(?:left|right)\b", "guide": "css-layout", "min": 3,
     "native": "Grid or flexbox for page and component layout; keep float only to wrap text around an image.",
     "native_es": "Grid o flexbox para la maquetación; deja float solo para que el texto rodee una imagen.",
     "keep_when": "The float wraps running text around a figure.", "name_es": "Maquetación con float"},
    {"id": "clearfix", "kinds": {"css", "html"}, "pattern": r"\.clearfix\b|\bclear\s*:\s*both\b|:after\s*\{[^}]*clear\s*:\s*both", "guide": "css-layout",
     "native": "A flex or grid container (or display: flow-root) contains its children without a clearfix.",
     "native_es": "Un contenedor flex o grid (o display: flow-root) contiene a sus hijos sin clearfix.",
     "keep_when": "Only while an old float layout stays.", "name_es": "Clearfix"},
    {"id": "table-display-layout", "kinds": {"css", "html"}, "pattern": r"\bdisplay\s*:\s*table(?:-cell|-row)?\b", "guide": "css-layout",
     "native": "Grid for two-dimensional layout and flexbox for one row; centre with place-items.",
     "native_es": "Grid para la maquetación en dos dimensiones y flexbox para una fila; centra con place-items.",
     "keep_when": "The content really is a table.", "name_es": "Maquetación con display: table"},
    {"id": "padding-ratio-hack", "kinds": {"css", "html"}, "pattern": r"\bpadding-(?:top|bottom)\s*:\s*\d+(?:\.\d+)?%", "guide": "responsive-design",
     "native": "aspect-ratio keeps a box in proportion without the percentage-padding trick.",
     "native_es": "aspect-ratio mantiene la proporción de una caja sin el truco del relleno en porcentaje.",
     "keep_when": "The percentage is real spacing, not a ratio box.", "name_es": "Proporción con relleno porcentual"},
    {"id": "viewport-height", "kinds": {"css", "html"}, "pattern": r"\b(?:min-)?height\s*:\s*100vh\b", "absent": r"\b\d+\s*[sdl]vh\b", "guide": "css-layout",
     "native": "dvh / svh units follow the mobile browser bars; 100vh leaves content under them.",
     "native_es": "Las unidades dvh / svh siguen las barras del navegador móvil; 100vh deja contenido bajo ellas.",
     "keep_when": "A fallback line precedes a dvh declaration.", "name_es": "Altura 100vh"},
    {"id": "max-height-transition", "kinds": {"css", "html"}, "pattern": r"\btransition\s*:[^;{}]*\bmax-height\b|\btransition-property\s*:[^;{}]*\bmax-height\b",
     "guide": "animate-to-intrinsic-sizes",
     "native": "Animate to auto or intrinsic sizes with interpolate-size / calc-size instead of guessing a max-height.",
     "native_es": "Anima hacia auto o tamaños intrínsecos con interpolate-size / calc-size en lugar de adivinar un max-height.",
     "keep_when": "The browser support target excludes interpolate-size and no fallback is wanted.", "name_es": "Transición de max-height"},
    {"id": "z-index-ceiling", "kinds": {"css", "html"}, "pattern": r"\bz-index\s*:\s*(?:9{4,}|2147483\d+)\b", "guide": "persistent-top-layer-ui",
     "native": "Dialogs and popovers render in the top layer, above every z-index, with no number war.",
     "native_es": "Los diálogos y popovers se dibujan en la capa superior, sobre cualquier z-index, sin guerra de números.",
     "keep_when": "The element is not an overlay (a stacking order among siblings).", "name_es": "z-index disparatado"},
    {"id": "individual-transform", "kinds": {"css", "html"}, "pattern": r"@keyframes[^{]*\{[^@]*?transform\s*:\s*(?:translate|scale|rotate)\w*\([^)]*\)\s*;?\s*\}", "guide": "individual-transform-properties",
     "native": "translate, scale and rotate are separate properties: animate one without rewriting the whole transform.",
     "native_es": "translate, scale y rotate son propiedades separadas: anima una sin reescribir todo el transform.",
     "keep_when": "Several transform functions must be applied in one fixed order.", "name_es": "Transform único en animaciones", "min": 2},
    {"id": "px-font-sizes", "kinds": {"css", "html"}, "pattern": r"\bfont-size\s*:\s*\d+(?:\.\d+)?px\b", "guide": "respect-os-text-scale", "min": 6,
     "native": "rem or clamp() sizes follow the person's text-size setting; pixel sizes ignore it.",
     "native_es": "Los tamaños en rem o clamp() siguen el ajuste de texto de la persona; los de píxeles lo ignoran.",
     "keep_when": "Icon fonts or fixed artwork that must not scale.", "name_es": "Tamaños de fuente en píxeles"},
    {"id": "legacy-html-elements", "kinds": {"html"}, "pattern": r"<(?:center|font|marquee|blink|big|strike)\b", "guide": "html",
     "native": "CSS for alignment and typography; semantic elements for structure.",
     "native_es": "CSS para alineación y tipografía; elementos semánticos para la estructura.",
     "keep_when": "Never in new markup.", "name_es": "Elementos HTML obsoletos"},
    {"id": "modal-div", "kinds": {"html", "css", "js"}, "pattern": r"class=[\"'][^\"']*\bmodal(?:-(?:overlay|backdrop|dialog|container))?\b|\.modal-(?:overlay|backdrop)\b|role=[\"']dialog[\"']",
     "absent": r"<dialog\b|showModal\s*\(", "guide": "dialog",
     "native": "<dialog> with showModal() gives focus trapping, Escape, the backdrop and the top layer for free.",
     "native_es": "<dialog> con showModal() da atrapado de foco, Escape, fondo y capa superior sin código.",
     "keep_when": "A framework component already wraps <dialog>.", "name_es": "Modal construido con div"},
    {"id": "alert-confirm", "kinds": {"js", "html"}, "pattern": r"(?<![\w.$])(?:window\.)?(?:alert|confirm|prompt)\s*\(", "guide": "dialog", "min": 2,
     "native": "A <dialog> styled with the page: it does not block the thread and can carry real content.",
     "native_es": "Un <dialog> con el estilo de la página: no bloquea el hilo y admite contenido real.",
     "keep_when": "A throwaway debugging line.", "name_es": "alert / confirm del navegador"},
    {"id": "click-outside-close", "kinds": {"js", "html"}, "pattern": r"\.contains\s*\(\s*(?:e|ev|event|evt)\.target\s*\)|closest\s*\(\s*['\"][.#][\w-]*(?:menu|dropdown|popover|modal)", "guide": "declarative-dialog-popover-control",
     "absent": r"\bpopover\b", "native": "popover (and <dialog>) close on outside click and Escape by themselves (light dismiss).",
     "native_es": "popover (y <dialog>) se cierran al pulsar fuera y con Escape por sí solos (descarte ligero).",
     "keep_when": "The outside click does something other than close.", "name_es": "Cierre al pulsar fuera, a mano"},
    {"id": "dropdown-div", "kinds": {"html"}, "pattern": r"class=[\"'][^\"']*\b(?:dropdown|dropdown-menu|menu-dropdown)\b", "absent": r"\bpopover\b|anchor-name|position-anchor", "guide": "menu",
     "native": "A popover anchored with anchor positioning, with a menu role and arrow-key focus group.",
     "native_es": "Un popover anclado con anchor positioning, con rol de menú y grupo de foco con flechas.",
     "keep_when": "A design-system component already provides keyboard support.", "name_es": "Menú desplegable con div"},
    {"id": "tooltip-by-hand", "kinds": {"html", "css", "js"}, "pattern": r"\.tooltip\b|data-tooltip|class=[\"'][^\"']*\btooltip\b", "absent": r"\bpopover\b|anchor-name|position-anchor|interestfor", "guide": "position-aware-tooltips",
     "native": "Anchor positioning places a tooltip next to its trigger and flips it at the viewport edge.",
     "native_es": "El anclaje posiciona un tooltip junto a su disparador y lo voltea en el borde de la ventana.",
     "keep_when": "A plain title attribute is enough.", "name_es": "Tooltip colocado a mano"},
    {"id": "bounding-rect-positioning", "kinds": {"js"}, "pattern": r"getBoundingClientRect\s*\(\s*\)", "present": r"(?i)tooltip|dropdown|popover|menu", "guide": "viewport-aware-dropdowns", "min": 2,
     "native": "position-try-fallbacks flip an anchored element at the viewport edge; no measuring in JavaScript.",
     "native_es": "position-try-fallbacks voltea un elemento anclado en el borde de la ventana; sin medir en JavaScript.",
     "keep_when": "The measurement feeds something other than positioning.", "name_es": "Posición calculada con getBoundingClientRect"},
    {"id": "accordion-div", "kinds": {"html"}, "pattern": r"class=[\"'][^\"']*\baccordion(?:-(?:item|header|button|panel))?\b", "absent": r"<details\b", "guide": "accordion",
     "native": "Adjacent <details> elements; add a shared name to make them exclusive.",
     "native_es": "Elementos <details> contiguos; con un name común se vuelven exclusivos.",
     "keep_when": "Panels need a heading of their own per item.", "name_es": "Acordeón con div"},
    {"id": "carousel-library", "kinds": {"html", "js"}, "pattern": r"\b(?:slick-carousel|slick\.min|swiper|owl\.carousel|owl-carousel|flickity|glide\.js|tiny-slider)\b", "guide": "carousel",
     "native": "scroll-snap with ::scroll-button and ::scroll-marker covers most carousels with no library.",
     "native_es": "scroll-snap con ::scroll-button y ::scroll-marker cubre la mayoría de carruseles sin librería.",
     "keep_when": "Looping, virtualised or heavily customised sliders.", "name_es": "Librería de carrusel"},
    {"id": "select-library", "kinds": {"html", "js", "css"}, "pattern": r"\b(?:select2|chosen\.jquery|chosen-container|selectize)\b", "guide": "custom-select-picker-layouts",
     "native": "A customisable <select> (appearance: base-select) can be styled and laid out without a library.",
     "native_es": "Un <select> personalizable (appearance: base-select) se estiliza y maqueta sin librería.",
     "keep_when": "Remote search or tagging that a select cannot do.", "name_es": "Librería de select"},
    {"id": "jquery-animation", "kinds": {"js", "html"}, "pattern": r"\.(?:fadeIn|fadeOut|fadeToggle|slideDown|slideUp|slideToggle)\s*\(|\.animate\s*\(\s*\{", "guide": "animate-element-entry-exit",
     "native": "CSS transitions with @starting-style and transition-behavior: allow-discrete animate entry and exit.",
     "native_es": "Las transiciones CSS con @starting-style y transition-behavior: allow-discrete animan entrada y salida.",
     "keep_when": "A page that depends on jQuery for other reasons and no animation rewrite is planned.", "name_es": "Animaciones de jQuery"},
    {"id": "scroll-listener-effects", "kinds": {"js", "html"}, "pattern": r"addEventListener\s*\(\s*['\"]scroll['\"]|\.on\s*\(\s*['\"]scroll['\"]|window\.onscroll", "present": r"(?i)parallax|reveal|progress|sticky|header|fade|opacity|translate", "guide": "scroll-entry-exit-effects",
     "native": "Scroll-driven animations (animation-timeline: scroll() / view()) run off the main thread with no listener.",
     "native_es": "Las animaciones guiadas por scroll (animation-timeline: scroll() / view()) corren fuera del hilo principal sin listener.",
     "keep_when": "The handler computes data, not a visual effect.", "name_es": "Efectos con listener de scroll"},
    {"id": "parallax-by-script", "kinds": {"js", "html"}, "pattern": r"(?i)parallax", "present": r"scrollY|pageYOffset|scrollTop|addEventListener\s*\(\s*['\"]scroll", "guide": "parallax-scroll-effects",
     "native": "Parallax with animation-timeline: scroll() and a transform, not a scroll handler writing styles.",
     "native_es": "Paralaje con animation-timeline: scroll() y un transform, no un handler que escribe estilos.",
     "keep_when": "The effect needs physics or pointer input.", "name_es": "Paralaje con script"},
    {"id": "dark-class-toggle", "kinds": {"js", "html"}, "pattern": r"classList\.(?:toggle|add)\s*\(\s*['\"](?:dark|dark-mode|dark-theme|theme-dark)['\"]", "absent": r"prefers-color-scheme|color-scheme|light-dark\s*\(", "guide": "dark-mode",
     "native": "color-scheme with light-dark() follows the system and the person's choice, with no flash.",
     "native_es": "color-scheme con light-dark() sigue al sistema y a la elección de la persona, sin parpadeo.",
     "keep_when": "A stored choice must override the system and no system default is wanted.", "name_es": "Modo oscuro por clase"},
    {"id": "clipboard-exec-command", "kinds": {"js", "html"}, "pattern": r"document\.execCommand\s*\(\s*['\"](?:copy|cut|paste)['\"]", "guide": "copy-button",
     "native": "navigator.clipboard.writeText() in a click handler.",
     "native_es": "navigator.clipboard.writeText() dentro de un manejador de clic.",
     "keep_when": "A fallback for contexts without the Clipboard API.", "name_es": "execCommand de copiado"},
    {"id": "set-timeout-yield", "kinds": {"js", "html"}, "pattern": r"new\s+Promise\s*\(\s*\(?\s*(?:r|res|resolve)\s*\)?\s*=>\s*setTimeout\s*\(\s*(?:r|res|resolve)\s*,\s*0\s*\)", "guide": "break-up-long-tasks",
     "native": "scheduler.yield() resumes with priority instead of going to the back of the task queue.",
     "native_es": "scheduler.yield() reanuda con prioridad en lugar de ir al final de la cola de tareas.",
     "keep_when": "Support for browsers without scheduler.yield with this line as the fallback.", "name_es": "Ceder el hilo con setTimeout"},
    {"id": "unload-beacon", "kinds": {"js", "html"}, "pattern": r"addEventListener\s*\(\s*['\"](?:unload|beforeunload)['\"]|window\.on(?:before)?unload", "guide": "batch-analytics-events",
     "native": "visibilitychange with sendBeacon (or fetchLater) is reliable; unload handlers are skipped and block the back-forward cache.",
     "native_es": "visibilitychange con sendBeacon (o fetchLater) es fiable; los manejadores de unload se ignoran y bloquean la caché de retroceso.",
     "keep_when": "A confirmation prompt for unsaved work (beforeunload).", "name_es": "Envío en unload"},
    {"id": "inner-html-assignment", "kinds": {"js", "html"}, "pattern": r"\.innerHTML\s*\+?=\s*(?![`'\"]\s*[`'\";]|['\"]['\"])", "guide": "sanitize-untrusted-html", "min": 3,
     "native": "setHTML() / the Sanitizer API, or textContent, instead of assigning markup built from data.",
     "native_es": "setHTML() / la API Sanitizer, o textContent, en lugar de asignar marcado construido con datos.",
     "keep_when": "The string is a trusted constant of your own.", "name_es": "Asignación a innerHTML"},
    {"id": "lazy-image-library", "kinds": {"html", "js"}, "pattern": r"\b(?:lazysizes|lozad|lazyload\.js|vanilla-lazyload)\b|class=[\"'][^\"']*\blazyload\b", "guide": "optimize-image-priority",
     "native": "loading=\"lazy\" and fetchpriority cover lazy loading and the hero image priority natively.",
     "native_es": "loading=\"lazy\" y fetchpriority cubren la carga diferida y la prioridad de la imagen principal.",
     "keep_when": "Art-direction or placeholder effects the attribute cannot do.", "name_es": "Librería de carga diferida"},
    {"id": "moment-library", "kinds": {"html", "js"}, "pattern": r"\bmoment(?:\.min)?\.js\b|require\s*\(\s*['\"]moment['\"]|from\s+['\"]moment['\"]", "guide": "support-global-calendar-systems",
     "native": "Intl.DateTimeFormat, Intl.RelativeTimeFormat and Temporal handle locales and calendars in the platform.",
     "native_es": "Intl.DateTimeFormat, Intl.RelativeTimeFormat y Temporal gestionan locales y calendarios en la plataforma.",
     "keep_when": "Heavy date arithmetic that Temporal does not support yet in your targets.", "name_es": "Moment.js"},
    {"id": "css-scroll-spy-script", "kinds": {"js"}, "pattern": r"IntersectionObserver", "present": r"(?i)nav|toc|scrollspy|active-link", "guide": "scrollspy", "min": 1,
     "native": ":target-current and scroll-marker-group highlight the section in view without an observer.",
     "native_es": ":target-current y scroll-marker-group resaltan la sección visible sin observador.",
     "keep_when": "The observer also loads data or tracks views.", "name_es": "Scrollspy con observador"},
]

_COMPILED: list[tuple[dict, re.Pattern, re.Pattern | None, re.Pattern | None]] = []


def _compiled():
    if not _COMPILED:
        for rule in RULES:
            _COMPILED.append((rule, re.compile(rule["pattern"], re.I | re.S if rule["id"] == "individual-transform" else re.I),
                              re.compile(rule["absent"], re.I) if rule.get("absent") else None,
                              re.compile(rule["present"]) if rule.get("present") else None))
    return _COMPILED


def rules() -> list[dict]:
    """The rules as data, without the compiled patterns."""
    return [{k: v if k != "kinds" else sorted(v) for k, v in rule.items()} | {"cite": CITE.format(id=rule["guide"])} for rule in RULES]


def scan_text(text: str, name: str = "", kind: str = "html", max_per_rule: int = 5) -> list[dict]:
    """Findings for one document. ``kind`` is ``html`` (inline style and script count too), ``css`` or ``js``."""
    findings = []
    lines = None
    for rule, pattern, absent, present in _compiled():
        if kind != "html" and kind not in rule["kinds"]:
            continue  # a document of markup also carries inline style and script, so it takes every rule
        if absent and absent.search(text):
            continue
        if present and not present.search(text):
            continue
        hits = list(pattern.finditer(text))
        if len(hits) < rule.get("min", 1):
            continue
        if lines is None:
            lines = text.splitlines()
        shown = []
        for match in hits[:max_per_rule]:
            line_no = text.count("\n", 0, match.start()) + 1
            snippet = (lines[line_no - 1] if line_no <= len(lines) else match.group(0)).strip()
            shown.append({"line": line_no, "snippet": snippet[:200]})
        findings.append({"rule": rule["id"], "file": name, "count": len(hits), "locations": shown, "guide": rule["guide"],
                         "cite": CITE.format(id=rule["guide"]), "native": rule["native"], "native_es": rule["native_es"],
                         "keep_when": rule["keep_when"], "name_es": rule["name_es"]})
    return findings


def iter_files(root: Path, skip_dirs: set[str] | None = None) -> Iterable[Path]:
    skip = SKIP_DIRS if skip_dirs is None else skip_dirs
    if root.is_file():
        yield root
        return
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in skip and not d.startswith(".git"))
        for name in sorted(files):
            if Path(name).suffix.lower() in KIND_OF_EXT and not SKIP_NAME.search(name):
                yield Path(current) / name


def scan_path(path: str, *, max_files: int = 600, include_vendor: bool = False) -> dict:
    """Scan a file or a folder of front-end sources and group the findings by rule and by file."""
    root = Path(path).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"Not found: {path}")
    findings: list[dict] = []
    scanned = skipped = 0
    for file in iter_files(root, set() if include_vendor else None):
        if scanned >= max_files:
            skipped += 1
            continue
        try:
            if file.stat().st_size > MAX_BYTES:
                skipped += 1
                continue
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped += 1
            continue
        scanned += 1
        rel = file.name if root.is_file() else file.relative_to(root).as_posix()
        findings.extend(scan_text(text, rel, KIND_OF_EXT[file.suffix.lower()]))
    return _report(findings, scanned, skipped, str(root))


def scan_sources(sources: list[dict]) -> dict:
    """Scan inline documents: ``[{name, text}]``. The kind comes from the extension of ``name`` (html by default)."""
    findings = []
    for item in sources:
        name = str(item.get("name") or "inline.html")
        findings.extend(scan_text(str(item.get("text") or ""), name, KIND_OF_EXT.get(Path(name).suffix.lower(), "html")))
    return _report(findings, len(sources), 0, "inline")


def _report(findings: list[dict], scanned: int, skipped: int, root: str) -> dict:
    by_rule: dict[str, dict] = {}
    for finding in findings:
        row = by_rule.setdefault(finding["rule"], {"rule": finding["rule"], "guide": finding["guide"], "cite": finding["cite"],
                                                    "native": finding["native"], "native_es": finding["native_es"],
                                                    "keep_when": finding["keep_when"], "files": 0, "hits": 0})
        row["files"] += 1
        row["hits"] += finding["count"]
    return {"root": root, "files_scanned": scanned, "files_skipped": skipped, "rules": len(RULES), "findings": findings,
            "summary": sorted(by_rule.values(), key=lambda row: (-row["hits"], row["rule"])),
            "note": "Findings are candidates: check keep_when before changing code, then read the guide with web_guide_read."}
