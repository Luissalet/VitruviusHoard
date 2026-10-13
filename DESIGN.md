---
name: "Vitruvius's Hoard"
description: "Existing Hoard workbench: reference collections and editable HTML patterns"
colors:
  primary: "#6a8ced"
  primary-hover: "#8ea8f1"
  primary-ink: "#12151c"
  primary-soft: "rgba(106, 140, 237, 0.14)"
  neutral-bg: "#13161d"
  neutral-surface: "#1a1d26"
  neutral-elevated: "#232731"
  neutral-border: "#333845"
  neutral-border-hover: "#555b6d"
  neutral-text: "#e1e4ec"
  neutral-muted: "#b4b7be"
  neutral-dim: "#9b9ea6"
typography:
  headline:
    fontFamily: "Cinzel, Iowan Old Style, Charter, Georgia, Liberation Serif, Noto Serif, Times New Roman, serif"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.2
  body:
    fontFamily: "Source Sans 3, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Noto Sans, Liberation Sans, Arial, sans-serif"
    fontSize: "14px"
    lineHeight: 1.55
  label:
    fontSize: "12px"
    fontWeight: 600
  code:
    fontFamily: "Cascadia Mono, Consolas, ui-monospace, monospace"
    fontSize: "12px"
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
spacing:
  field: "7px 10px"
  button: "7px 14px"
  panel: "16px"
  reference-content: "12px"
  gallery-gap: "14px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-ink}"
    rounded: "{rounded.md}"
    padding: "{spacing.button}"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.neutral-text}"
    rounded: "{rounded.md}"
    padding: "{spacing.button}"
  field:
    backgroundColor: "{colors.neutral-surface}"
    textColor: "{colors.neutral-text}"
    rounded: "{rounded.md}"
    padding: "{spacing.field}"
  panel:
    backgroundColor: "{colors.neutral-surface}"
    rounded: "{rounded.lg}"
    padding: "{spacing.panel}"
  reference-card:
    backgroundColor: "{colors.neutral-surface}"
    rounded: "{rounded.lg}"
    padding: "0"
  chip:
    backgroundColor: "{colors.neutral-elevated}"
    textColor: "{colors.neutral-muted}"
    rounded: "{rounded.sm}"
    padding: "2px 8px"
---

# Vitruvius's Hoard — architecture & design system

## Architecture

```
                          ┌───────────────────────────────┐
                          │      Assistant (Faustus)      │
                          └───────────────┬───────────────┘
                                          │ stdio (MCP)
                                          ▼
                          ┌───────────────────────────────┐
                          │        mcp_server.py           │  proxies every call,
                          │  (FastMCP bridge, no DB access) │  never opens the DB
                          └───────────────┬───────────────┘
                                          │ HTTP + Bearer token
                                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          vitruvius_hoard (FastAPI)                       │
│                                                                           │
│  hoard_link.guard ── request guard (Host / Origin / Fetch Metadata)      │
│                                                                           │
│  api/  ─────────────────────────────────────────────────────────────┐   │
│  │ health.py  library.py  render.py  tokens.py  references.py       │   │
│  │ settings.py  agent.py (tools+call)                               │   │
│  └───────────────────────────────┬───────────────────────────────────┘  │
│                                  │ every route calls Services            │
│                                  ▼                                      │
│  ┌────────────────────────── services.py ───────────────────────────┐  │
│  │  Services: db, browser worker, hoard_link.Link, ingest runner     │  │
│  └──┬───────────┬───────────┬───────────┬───────────┬───────────┬────┘  │
│     │           │           │           │           │           │       │
│     ▼           ▼           ▼           ▼           ▼           ▼       │
│  library.py  browser.py   lint.py   critique.py  tokens.py  references.py│
│  (FTS5      (Playwright   (29       (lint +     (OKLCH      (capture +  │
│   search,    worker       determ-    optional    ramps,      palette +  │
│   brief)     thread)      inistic    vision)     type/motion FTS)       │
│                           checks)                 tokens)                │
│                                                                           │
│  ingest/  ── git.py  markdown.py  catalog.py  rules.py  runner.py       │
│  (background thread: clone/pull → chunk/parse → mine rules → sources)   │
│                                                                           │
│  db.py ── SQLite (WAL, FTS5) ── data/vitruvius.db                        │
│  hoard_link/ ── vendored: family bus (emit/record_call/health_block),   │
│                Link (chat/embed against Faustus or a loopback server)   │
└─────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                          data/  (db, sources/, renders/, references/,
                                 mcp-token, url, backend.json, logs/)
```

`agent_tools.py` is the single source of truth for the 25 MCP tools: it defines pydantic argument models, the
`TOOLS` table (description, `readOnlyHint`/`destructiveHint`/`idempotentHint`, the function that runs it against
a `Services` instance) and `tool_catalog()`/`call_tool()`. `api/agent.py` and `mcp_server.py` both consume that
one catalogue, so the REST bridge and the MCP bridge can never disagree about what a tool does or how it is
described.

`main.py`'s route order matters: `family.configure(...)` runs first, then the request guard, the error handlers and
`/api/health` (the shared `hoard_link.service.health_router`), then every API router and the PWA files, and the SPA
catch-all (`install_spa`) is registered **last** so it never shadows an `/api/*` route.

## Module map

| Module | Responsibility |
| --- | --- |
| `config.py` | Environment-derived process config (port, data dir, render timeout, allowed hosts, embedding backend, local-URL opt-in) through `hoard_link.appconfig`. Never touches the DB. |
| `db.py` | The ordered, idempotent schema migrations, incl. FTS5 virtual tables and their sync triggers; the connection, lock and transactions are `hoard_link.sqlkit.Database`. |
| `services.py` | Wires the DB, the browser worker, `hoard_link.Link` and the ingest runner behind one object every router and tool shares; owns the render/critique/tokens/references/sources/settings/status logic. |
| `browser.py` | The single background Chromium worker (Playwright): capture (screenshot + optional scroll video) and the in-page `PROBE_JS` evaluation. Browser discovery is `hoard_link.web.browser`, every URL, redirect and sub-request is checked with `hoard_link.web.safety` (public hosts only), the video is encoded with `hoard_link.media`. |
| `lint.py` | 29 deterministic design checks over a probe dict + raw HTML, each returning typed findings; `run_lint()` scores 0-10. |
| `critique.py` | Merges lint findings with an optional vision-model rubric; robust JSON extraction from the model's answer. |
| `tokens.py` | Pure-Python OKLCH colour math, ramps, type scale, spacing/radius/shadow/motion tokens, four export formats, the self-contained playground HTML. |
| `library.py` | FTS5 `bm25` search with citations (`hoard_link.docs.textsearch` / `citations` / `vecmath.rrf`), rule listing, deterministic brief composition. |
| `references.py` | Reference-gallery capture, Pillow palette extraction, FTS search, tag/font/palette similarity. |
| `ingest/git.py` | Shallow clone / `pull --ff-only` into `data/sources/<id>` through `hoard_link.proc`. |
| `ingest/markdown.py` | Reshapes `hoard_link.docs.chunking.chunk_markdown` (heading breadcrumbs, ~1200-char cap) into ingest rows. |
| `ingest/catalog.py` | Loose CSV/JSON → styles/palettes/font_pairings parsers, tolerant of unknown columns. |
| `ingest/rules.py` | Mines Do/Don't/Avoid/Never/Always bullets into `rules`, guessing area/severity/`check_id`. |
| `ingest/runner.py` | The one-source-at-a-time background ingest worker; `ingest_source()` is also the synchronous entry point used by `scripts/ingest.py` and by tests. |
| `dense.py` | Multilingual vectors keyed by text hash + model, background build, cosine top-k (`vecmath.topk`). `FamilyEmbedder` asks Borges through `hoard_link.fam_embed` and falls back to the in-process fastembed model; vectors of two models are never mixed. |
| `agent_tools.py` | The 25-tool MCP/REST catalogue (single source of truth). |
| `api/*` | Thin FastAPI routers that validate input and call into `Services`. |
| `hoard_link/` | Vendored family contract: `family.emit/record_call/health_block`, `Link.chat/embed` resolution against Faustus or a loopback model server. |

## Design system (for the bundled UI)

### Identity

- **Name**: Vitruvius's Hoard (no tagline anywhere: the name and what it does).
- **Glyph**: a circle inside a square with a drafting divider (the Vitruvian proportion), gold with a dark
  outline, drawn at ≈400px centred at (627, 768) on the icon canvas (`scripts/make_icon.py`).

### Colour

- **Accent (cobalt blueprint)**: ramp from `#1b2f9e` (dark) to `#6d8dff` (light); light tint `#dfe6ff`.
- **Gold** (glyph, marks, emphasis): `#f8d88c` → `#e0a242`.
- **Dark navy background**: `#0b1130` (surfaces slightly lighter, e.g. `#141b3f`).
- Generated per-design-system palettes (via `tokens.generate`) follow the same OKLCH-ramp shape: 50 (lightest) to
  950 (darkest), semantic success/warn/danger/info ramps hue-shifted from a shared recipe, not picked ad hoc.
- Every text/background pairing in the UI must clear **4.5:1** contrast (checked by `color.low-contrast` in the
  same lint the app runs on its own output).

### Typography

- **Headings**: a distinctive serif or display face (default generated pairing: Fraunces) — never the model's
  three defaults (Inter/Roboto/Arial) alone.
- **Body**: a readable sans (default: Inter) at a fluid scale (`tokens.type_scale`, `clamp()`-based, ratio
  1.2–1.333 depending on density).
- **Mono**: for cites, ids and code (default: IBM Plex Mono).

### Layout

- Sidebar navigation (Library / Critique / Tokens / Gallery / Settings) on desktop, a top tab bar on phones —
  same shape as the sibling Hoard apps, so a person moving between them keeps their bearings.
- Content constrained to a readable max-width; cards use the generated `radius`/`shadow` tokens, never a bespoke
  one-off value.
- Screenshots and video previews are shown at their captured aspect ratio, never stretched.

### Motion

- Respect `prefers-reduced-motion` everywhere the app itself renders motion (the playground, page transitions).
- Use the generated `motion` tokens (durations 120/200/320ms, `standard`/`emphasized`/`decelerate`/`accelerate`
  cubic-béziers) rather than ad hoc values — the app should not violate its own `motion.*` lint checks.

### Components

- **Result cards** (library search, references): citation/source/license badge always visible, never buried in a
  detail view.
- **Score dial** (critique): 0-10, coloured by band (red < 5, amber 5-7.9, green ≥ 8), always paired with the
  written summary — never the number alone.
- **Colour ramp swatches** (tokens): each swatch shows its hex and its contrast ratio against the chosen
  "on" colour, so a bad choice is visible before export.

### Do / Don't

- **Do** cite the library (`[vitruvius: ...]`) next to anything quoted from it, in both the UI and MCP responses.
- **Do** show lint findings grouped by area with severity, each with its concrete fix — never a bare list of ids.
- **Don't** default new design systems to the generic AI palette shapes this app itself detects
  (`color.generic-ai-palette-1/2/3`, `color.purple-blue-gradient`) — the whole point of the app is to avoid them.
- **Don't** block the UI on a render/critique call; always show the render id immediately and stream/poll for the
  critique.

### Icon recipe

1. Flat cobalt-blueprint gradient background (`#1b2f9e` → `#6d8dff`, diagonal).
2. A gold-gradient (`#f8d88c` → `#e0a242`) glyph — circle in a square with a drafting divider and a centre pivot
   dot — with a dark (`#06 0a18`) outline, ≈400px, centred at (627, 768) on a 1254² canvas.
3. Exported at 1254² (`app-icon.png`), 512²/192² (`client/public/icon-*.png`), and a multi-size `favicon.ico`.
4. Unlike the sibling apps (which recolour a shared family dragon illustration), Vitruvius's glyph is drawn
   directly with Pillow — there is no dragon source image to vendor for this app.

# Extension record: collections, patterns and editor (2026-10-13, task 501)

## Overview

**Creative North Star: "Existing Hoard workbench"**

This record preserves the incumbent Operate interface: dark tonal surfaces, serif page headings,
one blue accent, native form controls and explicit task actions. The new collection importer belongs
in Gallery; the eight original HTML patterns belong above the existing Critique editor. Imported
reference imagery and generated studies are the work being inspected, not a replacement app identity.

The frontmatter and this extension record describe the current shell used by these additions.
The earlier architecture and design notes above are retained without a general refresh; their old
palette, generated font-pairing examples and tool counts are not the authority for this extension.
The implemented sources and matching captures are authoritative. No new visual world or approved
composition was established for task 501.

The `.impeccable/design.json` sidecar records eight drop-in shell component previews, existing motion,
shadow and breakpoint extensions, and the same narrative. Its derived tonal strips are preview aids,
not additional implemented theme tokens; primitive values remain in the frontmatter.

**Key Characteristics:**
- Progressive disclosure for local import and pattern generation.
- Collection, origin and license status visible on each imported reference card.
- Generated source, explicit application and HTML download are separate actions.
- Each pattern application retains the current HTML on a draft stack during the current editing session.
- Existing URL/HTML, Render, Critique, functional assay, history and Faustus copilot remain available.

## Colors

### Primary
- **Workbench blue** (`primary`): the existing app accent for the apply-source action and Render.
- **Hover blue** (`primary-hover`): the existing brighter hover state for primary actions.
- **Accent ink** (`primary-ink`): dark text on primary action backgrounds.
- **Soft blue** (`primary-soft`): the existing accent chip treatment, including reference font metadata.

### Neutral
- **Deep ground** (`neutral-bg`): the page background around editor and gallery groups.
- **Panel charcoal** (`neutral-surface`): disclosure panels, fields and reference cards.
- **Raised charcoal** (`neutral-elevated`): metadata chips and secondary hover states.
- **Quiet borders** (`neutral-border`, `neutral-border-hover`): component separation and hover feedback.
- **Reading text** (`neutral-text`), **supporting text** (`neutral-muted`) and **field hints**
  (`neutral-dim`): the existing text hierarchy.

Generated studies have their own document-local palettes. Their default accent is editable;
it does not replace the shell accent. Elastic lettering keeps dark reading text on its pale ground
and uses the custom accent as an underline. Imported screenshots retain their source appearance.

## Typography

The shell uses the shared serif stack for page headings and shared sans stack for form/body text.
The frontmatter records the stacks, not a guarantee that their first font is installed.
HTML editing retains the app's Cascadia/Consolas monospace stack. Labels and supporting metadata
stay compact; imported cards use a semibold title (13px) and supporting provenance (12px).

Generated studies are independent editable documents: their common body is system sans (16px/1.5),
with Georgia headings in the Canvas studies and prismatic card. Common headings are fluid;
literal user text, including graphemes and HTML-like strings, remains text. Explanations follow
the title or sit beside a control; the new studies have no ornamental serials or upper kickers.

## Layout

The existing shell keeps its sidebar at desktop widths (220px from the shared theme) and horizontally
scrollable section navigation on smaller screens. At the shell's medium breakpoint (768px), main
padding changes from 16px to 32px horizontally. The Critique editor/history composition becomes
two columns at 1024px, with a 1.4:1 ratio and a 24px gap; below it, history follows the editor.

Pattern controls are vertically ordered: pattern, text, color and generation. Ready-source actions
wrap beneath them. The saved-draft status and Restore draft button sit immediately above the HTML
field. Collection import uses a native disclosure; its path field and import action wrap. Existing
URL capture remains above it, and search/tag/vibe/library/collection filters remain below it.

Gallery cards use an auto-fill grid with a 240px minimum column and a 14px gap, becoming one column
in the supplied mobile capture. Thumbnails use a fixed 16:10 viewport with cover cropping; reference
detail images retain their intrinsic ratio. The collection list loads 60 entries per cursor page,
with Load more references after the grid. Filtering applies across the collection, not just loaded cards.

Generated study content is constrained to 1100px with fluid padding (`clamp(20px,5vw,64px)`).
Canvas/SVG geometry scales to the available width. The editorial spread stacks below 650px;
its shape is then capped at 250px. Controls wrap rather than forcing a wider viewport.

## Elevation & Depth

The extension uses the existing flat panels, border separation and tonal hierarchy. Reference cards
do not acquire a new drop shadow. The existing detail drawer remains a fixed right-hand panel
(`min(560px,100vw)`) over a dark scrim; toast depth uses the shared shadow. These shell treatments
are separate from document-local effects such as the landscape frame and prismatic card shadow.

Motion in the shell retains its brief state transitions (160ms for buttons/cards) and reduced-motion
override. The studies keep their own explicit controls: replay, pause/resume, sliders, reset and
reduced-motion alternatives. A pulse is a graphic wave study; it is not an audio generator.

## Shapes

Use the incumbent rounded rectangles: 8px buttons/fields, 10px panels/cards, and 6px chips.
The reference card clips its thumbnail at the card boundary and places metadata in a 12px inset.
Disclosure panels retain the same border, radius and 16px padding as ordinary panels. Geometry
inside generated documents belongs to that study and must not become a new global component rule.

## Components

### Local collection disclosure and import receipt

A native details/summary group adds a labeled manifest path and a secondary Import button.
During import the button is disabled and names the busy state. The inline status reports the collection,
new/reused counts and per-entry errors. The normal manifest format is
`vitruvius-reference-collection/v1`; it copies captured images and metadata into private reference storage.
Repeating identical entries reuses versions; changed metadata or image content creates a new reference
version while previous material remains. This flow does not execute or incorporate third-party HTML.

### Collection filter, cursor action and reference card

The collection select lists names and stored-version counts alongside existing filters. Cursor loading
retains applied filters and appends results. Each imported card keeps its title, image and tags and adds
collection name, origin domain (or local-file label), and license or No declared license. This is provenance,
not permission inferred from a screenshot. The existing detail drawer keeps the full URL, source revision,
notes, palette, fonts, libraries and related patterns.

Structured JSON provenance remains structured in storage and API responses. License and source revision
values are converted to JSON text for display when they are not strings; related-pattern arrays render
each value as text, and other structured related-pattern values render as JSON. The card shows the license
text with the complete value in its title attribute, while the drawer shows the extended provenance.
Missing license values and strings marked unknown retain No declared license. Structured metadata does
not become a React child object or require flattening the original stored values.

### Pattern disclosure, generated source and draft notice

The selector exposes eight original studies with literal text and a six-digit hex accent parameter.
Generate source only prepares a complete editable HTML document. Use this source in the editor is the
primary action; Download HTML is a separate secondary action. Every explicit application atomically
saves the current HTML, including an empty draft, on a stack and replaces the editor source. Restore draft
returns the most recently saved HTML and removes that entry; repeated restoration walks back through
the earlier applications. For example, A → apply → edit B → apply → restore returns B, then A.
The inline status reports the retained-draft count with singular/plural text. This is page-component
state, retained until restoration or leaving the page; it is not persistent history or a general edit-undo
stack. Generation never overwrites the editor.

The existing editor then runs Render, optional Critique with vision and the functional assay, with its
widths/dark-mode controls and render history. The new forms keep the existing copilot draft context.

### Original editable studies

| Pattern | Material and real controls | Export |
| --- | --- | --- |
| Editorial grid | Heading-scale slider, asymmetric grid and geometric shape | HTML |
| Layered landscape | Own layered SVG, pointer parallax, depth slider and recenter | HTML |
| Elastic lettering | Grapheme-aware spans, replay and spacing slider | HTML |
| Radial drawing | Initially blank Canvas, pointer drawing, sector slider and clear | HTML, PNG drawing |
| Constellation map | SVG points, click/Enter/Space connections, clear and status | HTML, SVG drawing |
| Halftone field | Procedural Canvas dots with distance slider | HTML, PNG field |
| Pulse study | Canvas wave, frequency/amplitude sliders and pause/resume | HTML |
| Prismatic card | CSS perspective, pointer tilt, rotation slider and reset | HTML |

### Evidence and scope

This record follows source a5ff31e (R3), with the earlier record committed in 451928c. Evidence is in
`D:/LocalAI/research-inbox/referencias-vitruvius-20261013`: editor/gallery desktop/mobile `*-r2.png`,
the eight `r2/<pattern>-1440.png` and `r2/<pattern>-390.png` studies, and their browser receipt.
The receipt records eight control passes without page errors or overflow at those study widths.
R3 adds `editor-stack-r3.png` and `gallery-structured-r3.png` for intermediate draft recovery and JSON
provenance. The eight generated HTML sources are unchanged from R2, so their captures remain applicable.
`finish-verdict-r3.md` resolves these two additional fixes and says ship for that scope over the earlier
four resolved R2 fixes; it does not certify the whole app or replace functional review. The author's
379-test suite includes the real browser regression `test_browser_structured_provenance_and_draft_history`
(opt-in `VITRUVIUS_BROWSER_TESTS=1`), which checks the exact B/A restoration and structured Gallery/Drawer
provenance. These are author/functional-review results, not independent execution by this documenter.
The collection's 100 captured references are private source
evidence, not 100 newly implemented interactive pages. Historical source render metadata does not prove
every original control or audio function works. No arbitrary custom palette is certified by this record.

## Do's and Don'ts

### Do:
- **Do** use the existing Hoard theme and native disclosure/form controls for additions to these surfaces.
- **Do** keep collection, origin and license status visible beside every imported card's title and tags.
- **Do** keep generation, explicit application, restoration and HTML download as separate actions.
- **Do** retain every pre-application HTML value, including empty drafts, and restore in reverse order during the current editor visit.
- **Do** display structured provenance as JSON text while preserving its original structure in storage and API responses.
- **Do** keep the generated source editable and route it through the existing render/critique/assay workflow.

### Don't:
- **Don't** promote a study's palette, geometry or font choice into a new app-wide visual identity.
- **Don't** replace editor HTML when asynchronous source generation completes.
- **Don't** describe the application draft stack as persistence across navigation or a general edit-undo history.
- **Don't** hide unknown licensing behind tags or claim a source screenshot licenses its implementation.
- **Don't** turn source metadata, screenshot counts or the scoped finish verdict into whole-app certification.

# Extension record: application projects (2026-10-13, task 504)

## Overview

**Creative North Star: "Existing Hoard workbench"**

Applications extends the same Operate shell with complete editable source projects. The workbench
keeps its dark tonal surfaces, serif page heading, compact sans controls, monospace source field,
language switch and common Faustus launcher. A running application is a separate document inside
the preview, with its own editable styling; it does not establish a replacement workbench identity.
PRODUCT.md and `.impeccable/briefs/applications.md` fix this extension of the incumbent world.
There is no new approved composition or visual-world contract.

This record adds Applications to the system recorded for task 501, whose tokens, components and
earlier evidence remain intact. The sidecar adds a selected-project example and a contained table
example to its eight existing previews. Their HTML/CSS illustrate observed states, not a working
project server or authenticated production application. Derived tonal strips remain preview aids.

**Key Characteristics:**
- Creation stays available in a native disclosure, closed around an existing project.
- The selected project has visible accent treatment and a matching current-page attribute.
- Source revisions, preview lifecycle, capture, file saving and ZIP export have explicit actions.
- Unsaved source drafts are keyed by project, source revision and file during the Applications visit.
- Editable starter documents retain readable table columns through local horizontal scrolling.

## Colors

Applications uses the existing frontmatter palette. Selection uses workbench blue with accent ink,
matching the primary-button treatment and its brighter hover state. Panels, fields, source and help
text use the existing neutral hierarchy. Disabled actions retain the shared reduced-opacity state.

**The Selected Project Rule.** The project currently displayed is visibly marked with the existing
active-button treatment and `aria-current="page"`; the other project links keep their secondary state.

The three starters have document-local grounds and accents: work board uses warm paper (`#f4f3ed`)
with a blue accent (`#355c7d`), reference library uses warm parchment (`#eee8dd`) with a brown accent
(`#6b583a`), and inventory uses pale green (`#eaf0ed`) with a green accent (`#286c56`). Their common
reading text is dark (`#222d30`), links are blue (`#234a61`) and form fields are white. These are editable
starter defaults, not new global shell tokens. Reference-library tables use a warm light surface;
inventory tables carry a green top border. Changing a project's CSS changes only that application.

## Typography

The Applications page follows the shared heading override (30px serif, weight 700), even though the
component requests a smaller utility size. Project headings are compact semibold sans (16px).
Labels/help stay at 12px, controls at 13px and editable source uses the existing 12px monospace stack.
Project-name headings can break across lines. Form fields retain native input/select/textarea behavior.

Starter body text uses system sans (16px/1.6). Work-board and reference-library primary headings
use fluid Georgia (`clamp(34px,5vw,64px)`/1.1); reference-library headings are italic. Inventory has its
own fluid system-sans primary heading (`clamp(32px,5vw,58px)`, weight 650). Common section headings
are Georgia (28px/1.2), paragraphs are limited to 65ch and table headers are compact semibold text.
Header labels stay on one line; table cell content can wrap. These document-local styles remain
editable examples and do not replace the shell typography.

## Layout

The existing desktop sidebar and mobile horizontal section navigation remain. Inside Applications,
the project list and workspace form two columns at 1024px: a 240px list and a flexible workspace,
with a 20px gap. Below that breakpoint they stack. The workspace has a zero minimum width so its
preview and source editor fit the available column. Creation fields use two columns from 768px;
otherwise they stack. Action groups wrap. Native creation disclosure opens for the initial empty
state; an existing project keeps it available above the working area without dominating that area.

The selected project header holds revision, preview and capture actions. A running preview follows
in a full-width iframe (560px high), then the file/source panel, export controls and capture receipt.
The iframe uses the actual owned local preview URL. It is not an image standing in for application
behavior. Source textareas resize vertically; file/revision selects and explicit labels remain visible.

Starter headers, main content and footers are constrained to 1100px, with fluid horizontal insets
(`clamp(20px,5vw,56px)`) and 24px vertical padding. Headers wrap, then stack below 600px.
Record forms use a responsive grid with a 220px preferred minimum column and a 16px gap; search
controls wrap. Buttons and ordinary inputs/selects have a 44px minimum height; checkboxes retain
their native compact geometry.

**The Contained Table Rule.** Both overview and records pages wrap their tables in a horizontal
scroll region. Tables retain a useful minimum width (560px); headers do not break within words.
At narrow widths, the table scrolls inside the application rather than widening the outer document.
The initial visible crop does not mean offscreen columns or Open record links have been removed.

## Elevation & Depth

Applications retains flat, bordered shell panels and tonal state feedback. Selection introduces no
new shadow vocabulary. Shell state transitions and reduced-motion behavior remain the existing ones.
The preview's pale document ground is separate from the dark shell; starter tables and forms use
borders and surface contrast rather than new elevation effects. Starter focus uses an accent outline
(3px, offset 4px); shell controls retain the shared focus treatment.

## Shapes

The workspace reuses the existing rounded buttons/fields and panel borders. The preview frame has
its existing rounded boundary; project links use the shared button silhouette. Starter forms and
tables use simple squared borders. Those document-local rectangles are not a replacement for the
shell's established radii.

## Components

### Creation disclosure and selected project

The form contains name, starting point and description with native labels; Create is unavailable
while busy or the name is blank. The three starting points are work board, reference library and
inventory. Empty list/workspace states give the next action. The project list links to the selected
project, marks only that id active, and preserves the visible name. The earlier sections/functions,
language switching and the common Faustus launcher remain available.

### Source, revision and retained drafts

Each starter begins with fourteen complete editable text files: `project.json`, `server.py`,
`layout.html`, three pages (`pages/index.html`, `pages/records/index.html`, `pages/records/[id].html`),
three assets (`assets/style.css`, `assets/api.js`, `assets/client.js`), `contracts.d.ts`, `tsconfig.json`,
`Dockerfile`, `LICENSE` and `README.md`. The runtime serves filesystem HTML routes, JSON record APIs
and create/update/delete actions. The schema declares text, number, boolean and choice fields;
generated declarations and the annotated API client describe those contracts.

The file selector includes retained drafts and marks unsaved files with an asterisk. Saving the
current file creates a retained source revision; data remains separate in SQLite. Drafts survive
file, revision and project switches within this mounted page. Async responses preserve newer draft
text and later selections. Save retains other unsaved file values when moving to the new revision.
Adding a file prepares a draft path; saving performs the actual source update. Concurrent independent
file edits merge, while same-file conflicts preserve existing source and report the affected path.
This Applications draft map is distinct from task 501's HTML application/restore stack and is not
durable draft persistence across leaving the page or a general undo history.

### Owned preview, capture and standalone export

Open preview starts a real local Python process from a captured source revision. The workbench owns
that preview process and exposes Stop preview; changing the preview revision replaces only that
project's owned preview. The revision selector can inspect earlier source without erasing it. Status
distinguishes a preview of the selected revision from one showing another revision, and provides
Open in another tab. SQLite records persist through source edits and preview restarts; inspecting
an earlier source revision does not roll the database back. Data can evolve while a render runs.

Capture uses the existing render pipeline at 390px and 1440px and enters Critique history. A returned
capture publishes its receipt without replacing the user's later source selection. Export captures
source/revision bytes independently of preview; its optional data copy uses an online SQLite snapshot.
The resulting ZIP contains standalone source that runs with Python's standard library, native
HTML/CSS/JavaScript and no workbench or reference-framework runtime. Download identifies its exported
revision. The Dockerfile is editable output, not evidence of tested cloud deployment.

### Record form, status and errors

The starter server validates declared field types and rejects invalid input. Record forms expose
create/edit/delete and search/navigation with native controls; the inline live status shows server
errors. If edits arrive during submit, accepted values save while newer form text remains visible.
Valid field names that match form members (`elements`, `querySelector`, `addEventListener`, `dataset`,
`namedItem`, `title`) are read through native prototype APIs, without banning those names.
Workbench failures use the existing notification path; busy buttons name their current operation.
These behaviors describe source and reported functional evidence, not screenshots of every error,
loading, empty, export or conflict state.

### Evidence and scope

This extension reads frozen R2 source `f52496376c763b14278e30018b581c2776146836`, specifically
`client/src/pages/Projects.jsx`, shared shell CSS, `vitruvius_hoard/app_projects.py` and its runtime.
Evidence lives at `D:/LocalAI/research-inbox/vitruvius-apps-20261013`. The valid `recapture-r2/`
workspace and inventory captures have fresh contexts, three records, a visible document beginning
and `scrollY: 0`: desktop 1280×900 and mobile 390×844, with preview widths 736px and 358px.
The first R2 recapture attempt with a blank iframe was discarded and is not counted as evidence.

`finish-verdict-r2.md` says SHIP only for two visual corrections: visible selected-project treatment
and readable table columns/headers inside horizontal scrolling. It retains R1's scope limits and
does not approve the core or certify other starters/states. At this documentation checkpoint,
independent functional review has approved submission R2 with a CAS vote against revision 2.
`D:/LocalAI/research-inbox/referencias-core504-review-20261013/REVIEW-504-R2.md` records 29 independent
area tests passing with the real-browser six-name regression, the two unchanged R1 reproductions
now passing, and native R2 MCP (51 tools, three calls) with fourteen exported files matching exact
UTF-8 source bytes. This candidate approval does not claim Main integration/activation.

The author's R2 submission reports 389 tests passing with `VITRUVIUS_BROWSER_TESTS=1`, including
real Edge create/edit checks for the six form-member names, plus a passing build. The capture-race
receipt records selection B and source B surviving the completed capture of A. Earlier R1 receipts
record native MCP's 51-tool catalogue, project CRUD, retained data/drafts, exact exported source bytes,
an independently started extracted ZIP and TypeScript checking. Those earlier results are not
relabelled as fresh R2 executions. This documenter inspected code and supplied captures, and did
not repeat the browser, detector, context or functional suites.

The generated server is an ordinary local HTTP application without accounts/authentication. Editable
schema/client changes and production infrastructure belong to the exported project; no automatic
schema migration, production authentication, universal component renderer, cloud adapter, RSC,
streaming/compiler parity or benchmark superiority is established. Creating/running a starter needs
no model; global Sparks, model services and GPUs are outside this feature's preview lifecycle.

Not canonized: starter palettes, geometry and inventory's system-sans display heading remain local
editable details; the latter does not establish a system-display-face rule for future shell surfaces.
Uncaptured states and scoped SHIP are not promoted into universal quality or functional guarantees.

## Do's and Don'ts

### Do:
- **Do** reuse the incumbent shell theme, native controls and visible selected-project state in Applications.
- **Do** keep source revision, running preview revision and exported revision explicit.
- **Do** preserve newer drafts and later selections when asynchronous operations complete.
- **Do** retain source revisions separately from the evolving SQLite records.
- **Do** keep narrow tables horizontally scrollable inside their document, with intact header labels.
- **Do** keep file saving, preview start/stop, capture and standalone export as separate actions.

### Don't:
- **Don't** promote an editable starter's palette, display face or geometry into a new workbench identity.
- **Don't** describe page-visit source drafts as persistent storage or confuse them with the HTML restore stack.
- **Don't** imply that selecting earlier source also restores earlier data.
- **Don't** claim production authentication, schema migration or cloud/rendering parity from the starter output.
- **Don't** turn two visual fixes, author test results or earlier receipts into independent core approval or whole-app certification.
