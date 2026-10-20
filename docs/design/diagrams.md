---
name: "Vitruvius diagram editor"
description: "Surface record of the native graph and editorial-page document editor inside the existing Hoard workbench"
colors:
  primary: "#6a8ced"
  primary-hover: "#8ea8f1"
  primary-ink: "#12151c"
  neutral-bg: "#13161d"
  neutral-surface: "#1a1d26"
  neutral-elevated: "#232731"
  neutral-border: "#333845"
  neutral-border-hover: "#555b6d"
  neutral-text: "#e1e4ec"
  neutral-muted: "#b4b7be"
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
  control:
    fontSize: "13px"
    fontWeight: 600
    lineHeight: "18px"
  label:
    fontSize: "12px"
rounded:
  control: "8px"
  panel: "10px"
spacing:
  field: "7px 10px"
  button: "7px 14px"
  panel: "16px"
  actions: "8px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-ink}"
    rounded: "{rounded.control}"
    padding: "{spacing.button}"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.neutral-text}"
    rounded: "{rounded.control}"
    padding: "{spacing.button}"
  field:
    backgroundColor: "{colors.neutral-surface}"
    textColor: "{colors.neutral-text}"
    rounded: "{rounded.control}"
    padding: "{spacing.field}"
  panel:
    backgroundColor: "{colors.neutral-surface}"
    rounded: "{rounded.panel}"
    padding: "{spacing.panel}"
---

# Diagram editor surface brief and design record

## Editorial extension contract — phase C

This is an Operate extension of the same workbench. The preimplementation
acceptance contract is retained in [EDITORIAL-C.txt](D:/LocalAI/research-inbox/expansiones-fusiones-20261020/EDITORIAL-C.txt).
This short scoped brief was added after the first implementation; the external
contract predates code. It is not an approved comp or an earlier visual design.
Pages and editable text/image blocks share the existing native
document, revision history and per-object operations. No new visual world.
The page controls sit above the canvas; typography and images extend the same
inspector. Mobile keeps wrapped controls and sequential inspection. The white
page is the authored artifact, not another shell surface. Four native templates
cover comparison, timeline, process and relationships. Existing graph templates
and render types remain available. Editable source, combined SVG/PNG, paginated
PDF and draw.io pages are distinct outputs with explicit format boundaries.
The earlier finish review below covers only the graph-editor phase B. The phase C
captures and its one-fix finish verdict are recorded separately below; neither
verdict establishes installed-package activation or whole-surface certification.

## Overview

**Creative North Star: "Existing Hoard workbench"**

This Operate surface lets a person edit an independent diagram document directly, with the same document available to Faustus through the native product integration. Its dark shell, restrained blue selection, serif headings and sans controls extend the incumbent workbench. The declared stacks begin with Cinzel and Source Sans 3; the captures do not prove those webfonts loaded. The drawing is editable SVG; no decorative raster asset establishes its identity. Imported raster images are authored document content.

This is a surface-specific record for `client/src/pages/Diagrams.jsx` and `client/src/components/diagram-editor/`. Root `PRODUCT.md` and `DESIGN.md` retain authority. The companion `.impeccable/surfaces/diagram-editor.json` records this surface only; neither it nor this brief replaces the root system, repairs its reported drift, or establishes automatic discovery by the current Impeccable context loader.

The code-led direction preserves the existing world without an approved comp or a replacement visual identity. The task sequence is open/create/import, edit shapes and relationships, inspect properties, save a revision, then export or open the interactive view. The first viewport prioritizes a visible working drawing; secondary controls remain available. Earlier source rendering, type suggestions, brand profiles and recent diagrams continue below the editor. Phase B established the graph editing core. Phase C extends its native document with ordered editorial pages, text and embedded raster blocks. The figures extension adds a portable source revision and PNG preview for Cicero's existing image blocks. Authored isometric states remain outside this record. This figures extension is implemented and verified in isolated worktrees; integration and installed activation are not established here.

**Key Characteristics:**
- An independent versioned document with a visible name, save state and selected revision.
- A native SVG canvas between a shape palette and selection inspector on wide screens.
- A recoverable mobile shape palette and useful drawing area in the first viewport.
- Shared shape activation for pointer and keyboard, with explicit connection and selection modes.
- Output actions save an outstanding draft and use the accepted revision.
- Ordered pages, four editable editorial templates and text/image properties extend the existing document and inspector.
- Figure with source extends the existing export row with a portable revision and the selected page's PNG preview.

## Colors

### Primary

Workbench blue marks primary actions, the active editing tool, focused objects and keyboard outlines. Its brighter sibling is the primary-action hover treatment. These are inherited shell tokens, not a new editor palette.

### Neutral

Charcoal page, panel and raised surfaces form the shell hierarchy. Fine neutral borders separate bars, palette, inspector and export region; pale text and muted helper copy preserve the existing density.

The document has its own profile, selected by Claro/Oscuro. The source fallback uses white paper (`#ffffff`), dark ink (`#1d2433`), pale shape fill (`#f3f5f9`), grey outlines (`#8a94a6`), blue connectors (`#2f5bd3`) and muted labels (`#5b6474`). A supplied profile replaces these document values. They remain document-local, editable visual material and are deliberately absent from the shell token frontmatter. Only the light profile is shown in the supplied final captures.

**The Document Ground Rule.** The drawing profile belongs to the document; changing it does not replace the surrounding Hoard theme.

## Typography

The page headline uses the inherited serif headline role. The editor heading is a smaller serif step (20px desktop, 18px at the mobile breakpoint); its implementation uses the `--font-display` override with Cinzel fallback. Body, helper and control text inherit the shared sans family. Compact status, inspector labels, export labels and canvas help use the label role; graph labels default to sans (13px), with connector labels one step smaller (12px). Multiline node labels use SVG text spans at 1.3 times their selected size. Editorial content can change size, weight, alignment and ink independently of shell type. The comparison template uses authored content sizes of 40px, 26px, 22px and 18px; these do not extend the shell type ramp.

`editorial-capture-facts.json` reports the computed Source Sans 3/system fallback stack and `faces: []` at both widths. This identifies a declared stack, not a loaded face. The visible serif/sans relationship and inherited fallback are the supported observation; no loaded Cinzel or Source Sans 3 webfont is claimed.

**The Workbench Type Rule.** Preserve the inherited serif heading and sans control relationship; document labels remain legible working content rather than a new display voice.

## Layout

Wide screens use a three-column editor: palette (144px), flexible canvas with zero minimum width, inspector (236px). Hiding the inspector releases its column. Below 1100px the palette narrows (120px) and the inspector moves below the canvas into three columns. At 650px and below the workspace becomes one column and the inspector uses two columns. The normal canvas height is 480px, becoming 390px on mobile; its SVG viewBox responds to measured available width, zoom and pan.

The editor stacks a compact heading, document/template controls, name/save/status/undo toolbar, workspace and wrapped export actions. Desktop keeps the shape palette visible. Mobile initializes it closed and exposes Formas with `aria-expanded`; opening it restores the same controls as wrapping buttons. Crossing the breakpoint resets palette availability for the new layout. The mobile heading drops its supporting sentence, name and Save share a row, and secondary toolbar actions wrap before the canvas. The existing outer sidebar becomes horizontal section navigation on narrow screens.

The phase B mobile capture is 390px wide for a 390×844 viewport; its supplied author receipt placed the white canvas at y550.78, leaving about 293px visible. Phase C adds a page band above the workspace: on mobile its selector, Add page and Duplicate page share one grid row, with 6px gaps, 4px block margins and 6px block padding. Page options stay in a native disclosure, initially closed. Expanded options use a full-width title, paired dimensions, and wrapped actions. The inspector still follows the canvas in two columns; the supplemental inspector capture is scrolled and does not represent the first viewport.

In the final phase C 390×844 capture at `scrollY: 0`, the white canvas begins around y642; the title, introduction and both comparison blocks are visible through approximately y824. This is the one corrected finish finding, not a promise of phase B's exact 293px allowance or every language/font/document state. The final desktop capture is 1440×1000 with all three working columns. At 100%, portions of a larger drawing can lie beyond the visible viewport: Ajustar/Fit, zoom and pan make them reachable. Earlier source and brand tools remain below the editor.

**The Available Canvas Rule.** Compact secondary controls on narrow screens while keeping the drawing and the Formas disclosure available; preserve desktop working columns.

## Elevation & Depth

The editor uses flat tonal surfaces and thin borders. Palette, canvas controls, inspector and exports share the enclosing panel instead of becoming floating cards. Selection and focus use outlines and stronger strokes rather than new shadows. Shell button state transitions remain short (0.16s); reduced-motion rules remove transitions. The document provides the visual contrast against its shell through its own paper ground.

## Shapes

The enclosing editor uses the panel radius and clips its contents; native buttons and fields share the control radius. The SVG graph preserves semantic shapes: rectangle, rounded rectangle, diamond, pill and cylinder. Shape outlines, arrowheads, labels and dashed group boundaries remain vector geometry. Selected nodes gain a stronger accent stroke and a resize handle; numeric dimensions provide another way to change size. These graph silhouettes describe content and do not become shell container shapes.

## Components

### Buttons, fields and navigation

Primary Save and active tool controls reuse the inherited accent/ink treatment; secondary buttons remain transparent with neutral borders and tonal hover. Disabled controls use the shared reduced opacity (0.45). Native inputs, selects, textareas, color inputs and file input remain operable with the inherited focus treatment. The import label exposes a focus-within outline. Document and template selects have accessible names; the captured pair has no separate visible captions, which is not promoted into a future labelling convention. Navigation, ES/EN switching and the common Faustus entry remain incumbent shell features.

### Canvas, selection and connections

The palette offers the five node shapes, Select, Connect, Pan and automatic arrangement. Graph types `flowchart`, `architecture`, `state`, `er` and `swimlane` enter the editable SVG path; other types use an exported preview image in this component. That fallback is not evidence of object editing for every diagram type.

Pointer drag moves nodes; a selected corner handle resizes. Enter/Space activates a focused node; Shift adds/removes it from selection through the same activation function. Arrow keys move the selection (1 unit, or 10 with Shift); Delete/Backspace removes it. Connect takes a source followed by a target; Escape returns to selection and clears the connection selection. Nodes expose button semantics and pressed state; connectors are focusable and selectable with Enter. Help text documents the principal shortcuts. This records implemented interaction, not an exhaustive assistive-technology certification.

Reciprocal relationships use a separate right-hand return lane rather than drawing opposite arrows over the same route. Explicit connection ports and authored points remain available in the view model. Fit and pan retain access to lanes outside the current crop.

**The Distinct Return Rule.** Give the reciprocal return its own visible route so each arrow can be followed independently.

### Inspector and document history

Node selection exposes text, shape, position, dimensions, pinned position, fill and explanation/sources. Connection selection exposes label, endpoints, line style and source/target anchors. Shared actions duplicate, align, group, ungroup and delete the applicable selection. The empty inspector explains how to select an object; unavailable actions remain visibly disabled.

Local edits support undo/redo. Automatic arrangement records the effective pre-arrangement draft as one checkpoint, clears redo and preserves pinned positions. The Versiones action loads retained revisions; comparison displays added, removed and changed identities. Session storage retains a per-document draft and revision; refresh/open merge it against accepted document content and report conflicts. This is scoped browser-session recovery, not a claim of cross-device draft persistence or unlimited historical undo.

### Save and output

Status distinguishes saved revision, outstanding changes and saving; errors appear in a bordered alert with wrapping text. Export actions expose SVG, PNG, PDF, DRAWIO, MMD and HTML, plus editable source and interactive view. When a draft is dirty, the output label becomes Guardar y exportar/Save and export. The handler waits for Save and builds its URL from the returned document id and accepted revision; failed saving does not continue output. The interactive view opens separately. Edits made after the submitted snapshot can remain outstanding; the accepted revision is the output's boundary.

**The Accepted Revision Rule.** Output actions with outstanding changes save first and identify the accepted revision, retaining any later edits as a draft.

### Editorial pages, text and imported images — phase C

The four native starting points are comparison, timeline, process and relationships. They create editable blocks and connectors in the existing graph document with `view.kind: infographic`, ordered pages and an asset map; they do not introduce a parallel store. Initial page geometry is 960×720. Page IDs, title, dimensions and order are retained with the same revisions and object operations exposed through API/MCP. The page band selects, adds and duplicates pages; its disclosure edits title and dimensions, moves a page earlier or deletes it with its blocks. Duplication assigns fresh page/object/group identities and copies internal connectors. Blocks can move to another page through the inspector. Automatic graph arrangement is visibly unavailable for editorial composition.

The existing text, geometry, pinning, fill and explanation/source fields are extended with text size, weight (400/500/600/700), left/centre/right alignment, text colour and a shape-background/border toggle. Full labels remain in native source; character wrapping lays them into SVG spans. A saved rendering reports page-bound and text-height findings; they do not establish automatic fitting or truncation of source text.

Import image embeds PNG, JPEG or WebP data in `view.assets` and references its identity from a block. The image fits the block while preserving aspect ratio. Import sets `show_label: false` without deleting the label; Show text over image and Remove image make the caption state explicit. Remove image now clears `asset_id` and restores `show_label` in one atomic change, so one undo restores the image and one redo removes it again; its original embedded asset bytes remain retained in source. The QA synthetic image is imported user-content evidence, not a new shipped raster or decorative shell asset. Its stored bytes are in the author receipt; no supplied capture certifies its visible rendering.

Each page draws its own blocks and internal connectors. Cross-page semantic relationships remain in native source and the full HTML reader; they are not drawn as connectors across separate page canvases. Native JSON retains pages, styles, assets and identities. Combined SVG/PNG stack ordered pages; PDF produces separate pages with their own dimensions. Draw.io exchanges the supported page/text/shape/raster subset, with explicit unsupported-style limits; it is not an arbitrary-extension round trip. MMD expresses the semantic graph and labels, retaining manual layout/styles in native JSON. These are format boundaries, not proof that every output was exercised in this documentation pass.

### Portable figure with source — figures extension

Figura con fuente / Figure with source is the first action in the existing export row after the canvas and inspector. It uses the same bordered secondary button as the adjacent formats. On mobile, the row wraps and retains the existing larger export targets; it does not change the workbench palette, typography or composition. The current page selector also selects the figure preview for an editorial document. Graph documents export their diagram preview without a page selection.

The canvas, Faustus draft context (`selected_page`) and figure export URL share `selectedPage(content, id)`: use the requested ID only if it belongs to the current document; otherwise use the first page by `order`, without mutating the stored page array. This keeps the visible page and output aligned when array order differs from page order or the document changes. After saving a dirty draft, the output handler resolves that page again against the accepted `saved.content` and uses its accepted revision.

The action downloads `export.vfigure` as `vitruvius.figure/1`: document ID, accepted revision, title, selected page ID when applicable, the full native `content`, a base64 PNG preview and origin links. Selecting one page changes the preview only; all pages, identities, text, geometry, styles and embedded assets remain in the native source. The editor link opens the originating document; the source link identifies the exported revision. These links are references, while the package itself retains the source and preview. A later edit of the origin does not rewrite an imported Cicero asset.

A dirty figure export reuses the accepted save-before-output handler: save must succeed before the download URL is built with the returned ID and revision. Later local edits may remain dirty. Native JSON import accepts the figure envelope as well as the diagram envelope and recovers its native content. The browser import selector explicitly includes `.vfigure`, so the downloaded package can be selected directly and imported as a new editable document.

**The Visible Page Rule.** Resolve the current document's page consistently for the canvas, Faustus context and figure export; resolve it again against the accepted source after saving.

### Evidence and scope — figures extension, tasks 952/1021

Ground truth for this addition is the current `DiagramEditor.jsx`, `client/src/api.js`, native exchange/document/API code, and the final R2 captures under `D:/LocalAI/research-inbox/expansiones-fusiones-20261020/qa1021/`. Opened here: Vitruvius and Cicero desktop/mobile `full-r2.png` and `viewport-r2.png`, Cicero desktop/mobile `source-r2.png`, and `vitruvius-mobile-export-controls.png`. The full captures include the header; the viewport and detail captures provide readable controls. The obstructed R1 `cicero-mobile-figure-controls.png` is excluded.

`FINISH.txt` records `disposition: ship` for this incumbent Operate extension, with persistence, fidelity, ceiling, material_fixes and keep sections. No material fixes remain within that review's scope. No formal direction contract, approved comp or new identity is inferred. The verdict covers the added export/import/provenance controls, not a global redesign, unseen states or installed activation.

Author receipts read here: `browser-results.json` records desktop/mobile without horizontal overflow, no JavaScript or HTTP errors, save/reopen, source-retaining download, retained caption/notes/crop/other blocks on replacement, and dirty-export saving. The body CSS stack starts with Source Sans 3 and system fallbacks; `document.fonts` is empty in both apps. This does not prove Source Sans 3 or Cinzel was loaded.

`native-results.json` records the native API/MCP catalogs (Vitruvius 118 tools, Cicero 68), exact retained source through API/MCP, revisions 1 and 2, identical preview with distinct source, targeted replacement and selective undo preserving manual edits. It records real PPTX (39,205 bytes), PDF (33,681 bytes) and HTML (204,816 bytes) exports. The subsequent `roundtrip.json` records native UI import through the explicit `.vfigure` file filter, all pages and native source exact in a new document, and no JavaScript errors. The last import change affects only the file input's accept attribute; the R2 visual captures remain applicable to its visible layout. These are author results, not fresh functional executions by this documenter. No model, GPU, real profile or LLM-generated figure quality was tested. The diagram/PNG is synthetic native QA content, not a stock image or newly authored illustration.

Subsequent technical review of #952 CAS9 found a P2: the export could choose a different page or retain another document's page ID. The corrected `DiagramEditor.jsx` and `editorial.js` implement the shared resolution described above. `figure-producer-pagefix-build.log` records a successful build. Author `pagefix-results.json` records four native UI cases: reversed array/order with clean and dirty documents exports the visible `second` page (800×600 PNG, revisions 1/2), and switching documents in clean and dirty states exports the visible `other-first` page (640×480 PNG, revisions 1/2). All four retain the full native source. The context receipt records `selected_page: other-first`; JavaScript/HTTP error lists are empty.

This documenter opened `pagefix-desktop.png` and `pagefix-mobile.png`: full headers, Primera selection, Primera página content, revision 2 and export controls remain visible in the document flow. `FINISH-PAGEFIX.txt` returns `disposition: ship`, with the page-selection P2 resolved and no visible regression in those captures. This verdict covers only that correction, uses functional receipts attributed to the author and does not replace the pending technical CAS vote or extend `FINISH.txt` to other states. No independent functional execution or detector rerun occurred in this documentation pass. Integration and installed activation remain unestablished.

The supplied single detector run reports no Cicero findings and three Vitruvius advisories for existing document-local shape/connector colors. Those colors are already described above and do not become shell tokens. No new detector, context scan, browser, server or functional run was performed here. Figures code remains unintegrated and uninstalled at this checkpoint; the earlier phase B/C records below retain their historical scope.

### Evidence and scope — phase B retained checkpoint

Source inspected: `DiagramEditor.jsx`, `diagram-editor.css`, `model.js`, `pages/Diagrams.jsx`, `index.css` and the Vitruvius block in `hoard-theme.css`. Existing root product/design files and the supplied `context-editor960.txt` were read without modification. Evidence directory: `D:/LocalAI/research-inbox/expansiones-fusiones-20261020/`. Both final `editor952-desktop.png` and `editor952-mobile.png` were opened by this documenter; their final file dimensions are recorded in the sidecar. No new browser, server, detector, model or functional suite was run in this documentation pass.

`finish-review960.txt` requested five material corrections. `finish-verdict960.txt` scores all five resolved and returns `ship`: save-before-output, distinct reciprocal routes, keyboard activation/multiselection, useful first mobile viewport and arrangement undo/redo. Its functional receipts are author evidence contrasted with code, not fresh independent executions by this documenter or reviewer. The verdict explicitly does not certify the whole surface, LLM inference, or the new Python connector/export routing that was not yet loaded in the QA server at that checkpoint. Subsequent activation and functional acceptance require their own evidence.

Not canonized: document-local colors/shape geometry, the adjacent selects' missing visible captions, zoom glyphs as a general icon system, and uncaptured states do not become workbench-wide rules. These are content, local implementation details or incomplete evidence, not a replacement identity or a reason to reproduce a limitation. No decorative raster asset was authored for this surface.

### Evidence and scope — phase C after mobile compaction

Current source inspected: `DiagramEditor.jsx`, `EditorialControls.jsx`, `editorial.js`, `diagram-editor.css`, and the native editorial/document/exchange/render implementation and editorial tests. Root `PRODUCT.md` and `DESIGN.md` remain unchanged by this pass. The external `EDITORIAL-C.txt` is the before-code acceptance contract; the short brief above was written after first implementation. No approved comp or new visual-world contract is invented.

Opened for this documentation pass: `editorial-final-1440.png` (1440×1000) and `editorial-final-390.png` (390×844), both at `scrollY: 0` with page options closed; `editorial-mobile-inspector.png` (390×844) is a supplemental scrolled region. Earlier `editorial-desktop.png` and `editorial-mobile.png` show expanded page options and are complementary states, not later first-viewport captures. All live evidence paths are under the same evidence directory recorded above.

`editorial-finish-review.txt` requested one material correction: recover useful mobile drawing space. `editorial-finish-verdict.txt` scores finding 1 resolved and says `ship` only for that compaction. It reports no visible regression from the fix in the final desktop/mobile captures. It does not certify the whole surface, loaded webfonts, images, exports, unseen states or model inference. The reviewer did not rerun functional tests.

Author evidence: `editorial-browser-r2.log` and `editorial-browser.json` record save/reopen, two pages, ten blocks and one embedded raster, with no recorded JavaScript errors, bad HTTP responses or horizontal overflow. `editorial-tests-r4.log` records 27 native tests passing, including two PDF page sizes and a combined PNG 1104px tall. The earlier `editorial-suite-r1.log` remains historical. The final complete Python suite on source `baa` is recorded in `editorial-suite-final.log`: 502 passed/2 skipped in 158.71s. The later correction touches only the JavaScript Remove image handler; Python source is unchanged and no subsequent Python rerun is claimed.

Independent functional review reported 69 tests passing and found the image-removal P2: two separate updates could overwrite the first value. After the atomic correction, author `editorial-build-r5.log` records a successful frontend build and `editorial-remove-r2.json`/`.log` record real Edge removal, one-step undo, one-step redo and save without the block's image reference, exact retained asset bytes and zero JavaScript errors. These checks do not constitute a new visual verdict: no CSS or layout changed, and the preceding SHIP still covers only the mobile-compaction finding. A new submission/review CAS remains pending at this checkpoint. These receipts were read, not independently rerun here. No LLM or GPU test is claimed, and no installed-package activation is established while installation coordination under task 934 remains pending.

The single supplied `editorial-detector.json` run contains ten advisories against root palette/type ramps. Its document-local colours, inherited heading/control sizes and existing error-surface fallback are scoped source facts, not new shell tokens or mandatory fixes. The finish review required no root metadata change for them. The documenter ran no new context/detector, browser, server, model or functional test. Current root drift and automatic discovery of this scoped sidecar remain outside this update.

## Do's and Don'ts

### Do:
- **Do** preserve the incumbent Hoard shell, navigation, language switch and Faustus integration.
- **Do** keep the document profile separate from the workbench palette.
- **Do** retain a useful mobile drawing area with the shape controls recoverable through Formas.
- **Do** keep pointer and keyboard activation consistent for node selection and connection creation.
- **Do** keep reciprocal routes visually distinct and preserve access through Fit and pan.
- **Do** save outstanding changes before output and use the accepted revision in its URL.
- **Do** retain the earlier diagram source, brand and recent-result tools below the editor.
- **Do** keep page controls and editorial inspection in the existing workbench, preserving full text and embedded image identity in native source.
- **Do** keep figure export in the existing output group and preserve the full source when selecting a page for its preview.

### Don't:
- **Don't** promote a graph template's palette or shape vocabulary into a new shell identity.
- **Don't** silently export the previously saved revision when the action promises to save the current draft.
- **Don't** describe every diagram type as object-editable from the graph canvas implementation.
- **Don't** turn five resolved finish findings into certification of LLM inference or untested runtime exports.
- **Don't** treat phase B's historical graph-only scope as phase C's current capability, or promote phase C's one resolved visual fix into full functional/installed acceptance.
- **Don't** imply arbitrary draw.io extension parity, loaded webfonts or installed downstream activation from these source and capture receipts.
