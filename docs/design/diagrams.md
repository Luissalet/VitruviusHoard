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

## Isometric extension direction — task 1049

Operate and Read, within the incumbent workbench. The technical figure leads;
native state and part selectors remain beside it, with authored explanations
below and editing in the existing inspector vocabulary. On narrow screens the
inspector follows the figure. Retain the shell, palette, typography, revision
actions, Faustus and exports. State selection changes a derived drawing; base
geometry remains editable and retained. Parts are selectable on the SVG and by
a native select, including hidden parts. No new visual world, physics claims,
animation or WebGL. Acceptance uses the same saved state for UI, reading HTML,
MCP and exported figure, desktop and phone. Implementation and verification
are in progress; this direction is not a completion record.

The preceding block is retained as the historical direction. The built source
and supplied verification for task 1049 are recorded under Components below;
those initial checkpoints do not establish technical CAS approval, integration or installed activation; the subsequent acceptance addendum records them separately.

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

The code-led direction preserves the existing world without an approved comp or a replacement visual identity. The task sequence is open/create/import, edit shapes and relationships, inspect properties, save a revision, then export or open the interactive view. The first viewport prioritizes a visible working drawing; secondary controls remain available. Earlier source rendering, type suggestions, brand profiles and recent diagrams continue below the editor. Phase B established the graph editing core. Phase C extends its native document with ordered editorial pages, text and embedded raster blocks. The figures extension adds a portable source revision and PNG preview for Cicero's existing image blocks. Task 1049 adds selectable isometric parts, long explanations and authored states to the same document. Task 1049 subsequently received technical CAS2 approval, integration and installed-package acceptance in isolated QA; the chronological addendum below records their exact scope. The default user app was not started for that acceptance. Earlier phase and extension receipts retain their own scope.

**Key Characteristics:**
- An independent versioned document with a visible name, save state and selected revision.
- A native SVG canvas between a shape palette and selection inspector on wide screens.
- A recoverable mobile shape palette and useful drawing area in the first viewport.
- Shared shape activation for pointer and keyboard, with explicit connection and selection modes.
- Output actions save an outstanding draft and use the accepted revision.
- Ordered pages, four editable editorial templates and text/image properties extend the existing document and inspector.
- Figure with source extends the existing export row with a portable revision and the selected page's PNG preview.
- Reusable shape styles extend the selection inspector with a named, revisioned library shared across documents.
- Isometric parts retain original geometry and explanations while authored states derive translated, hidden and highlighted views for editing, reading and export.

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

The reusable-style disclosure keeps the local control/label scale (13px/12px), including 12px helper text at 1.5 line height. These are inherited inspector roles, not additions to the root type ramp. Its author browser receipt also reports the declared Source Sans 3/system stack with `loaded: []`.

**The Workbench Type Rule.** Preserve the inherited serif heading and sans control relationship; document labels remain legible working content rather than a new display voice.

## Layout

Wide screens use a three-column editor: palette (144px), flexible canvas with zero minimum width, inspector (236px). Hiding the inspector releases its column. Below 1100px the palette narrows (120px) and the inspector moves below the canvas into three columns. At 650px and below the workspace becomes one column and the inspector uses two columns. The normal canvas height is 480px, becoming 390px on mobile; its SVG viewBox responds to measured available width, zoom and pan.

The editor stacks a compact heading, document/template controls, name/save/status/undo toolbar, workspace and wrapped export actions. Desktop keeps the shape palette visible. Mobile initializes it closed and exposes Formas with `aria-expanded`; opening it restores the same controls as wrapping buttons. Crossing the breakpoint resets palette availability for the new layout. The mobile heading drops its supporting sentence, name and Save share a row, and secondary toolbar actions wrap before the canvas. The existing outer sidebar becomes horizontal section navigation on narrow screens.

The phase B mobile capture is 390px wide for a 390×844 viewport; its supplied author receipt placed the white canvas at y550.78, leaving about 293px visible. Phase C adds a page band above the workspace: on mobile its selector, Add page and Duplicate page share one grid row, with 6px gaps, 4px block margins and 6px block padding. Page options stay in a native disclosure, initially closed. Expanded options use a full-width title, paired dimensions, and wrapped actions. The inspector still follows the canvas in two columns; the supplemental inspector capture is scrolled and does not represent the first viewport.

In the final phase C 390×844 capture at `scrollY: 0`, the white canvas begins around y642; the title, introduction and both comparison blocks are visible through approximately y824. This is the one corrected finish finding, not a promise of phase B's exact 293px allowance or every language/font/document state. The final desktop capture is 1440×1000 with all three working columns. At 100%, portions of a larger drawing can lie beyond the visible viewport: Ajustar/Fit, zoom and pan make them reachable. Earlier source and brand tools remain below the editor.

**The Available Canvas Rule.** Compact secondary controls on narrow screens while keeping the drawing and the Formas disclosure available; preserve desktop working columns.

Reusable styles sits below the selected shape's properties and above selection actions. Its native disclosure has a thin top separator, 8px top padding and a 44px minimum summary target with 12px vertical padding. Labels/action groups gain 10px top spacing; help follows with 12px. Long button labels wrap within the inspector. At 1100px and below the group spans all inspector columns, including both mobile columns; it does not change the canvas or the surrounding working layout.

The isometric workspace replaces the graph palette/canvas arrangement with a flexible figure column and a 260px inspector. Labelled State and Part selects use two flexible columns above the figure, with an 80px Color / Colour column alongside them. The SVG scales to available width, with a 280px minimum figure area and 560px maximum SVG height. Reading text follows the figure within 75ch, preserving line breaks and wrapping long notes. Below 850px the inspector follows the figure and explanation, separated by a top border; its buttons retain 44px targets. The standalone reader uses a flexible figure and 320px reading sidebar, stacking below 700px. Its light reading ground and white figure are document presentation, not replacement shell tokens.

## Elevation & Depth

The editor uses flat tonal surfaces and thin borders. Palette, canvas controls, inspector and exports share the enclosing panel instead of becoming floating cards. Graph selection and focus use outlines and stronger strokes. Isometric part selection adds a local SVG drop shadow; keyboard focus has a visible outline. These content states do not establish a shell elevation scale. Shell button state transitions remain short (0.16s); reduced-motion rules remove transitions. The document provides the visual contrast against its shell through its own paper ground.

## Shapes

The enclosing editor uses the panel radius and clips its contents; native buttons and fields share the control radius. The SVG graph preserves semantic shapes: rectangle, rounded rectangle, diamond, pill and cylinder. Shape outlines, arrowheads, labels and dashed group boundaries remain vector geometry. Selected nodes gain a stronger accent stroke and a resize handle; numeric dimensions provide another way to change size. These graph silhouettes describe content and do not become shell container shapes.

## Components

### Buttons, fields and navigation

Primary Save and active tool controls reuse the inherited accent/ink treatment; secondary buttons remain transparent with neutral borders and tonal hover. Disabled controls use the shared reduced opacity (0.45). Native inputs, selects, textareas, color inputs and file input remain operable with the inherited focus treatment. The import label exposes a focus-within outline. Document and template selects have accessible names; the captured pair has no separate visible captions, which is not promoted into a future labelling convention. Navigation, ES/EN switching and the common Faustus entry remain incumbent shell features.

### Canvas, selection and connections

The palette offers the five node shapes, Select, Connect, Pan and automatic arrangement. Graph types `flowchart`, `architecture`, `state`, `er` and `swimlane` enter the editable SVG path. Isometric diagrams use the part/state controls documented below; remaining types use an exported preview image in this component. That fallback is not evidence of object editing for every diagram type.

Pointer drag moves nodes; a selected corner handle resizes. Enter/Space activates a focused node; Shift adds/removes it from selection through the same activation function. Arrow keys move the selection (1 unit, or 10 with Shift); Delete/Backspace removes it. Connect takes a source followed by a target; Escape returns to selection and clears the connection selection. Nodes expose button semantics and pressed state; connectors are focusable and selectable with Enter. Help text documents the principal shortcuts. This records implemented interaction, not an exhaustive assistive-technology certification.

Reciprocal relationships use a separate right-hand return lane rather than drawing opposite arrows over the same route. Explicit connection ports and authored points remain available in the view model. Fit and pan retain access to lanes outside the current crop.

**The Distinct Return Rule.** Give the reciprocal return its own visible route so each arrow can be followed independently.

### Inspector and document history

Node selection exposes text, shape, position, dimensions, pinned position, fill and explanation/sources. Connection selection exposes label, endpoints, line style and source/target anchors. Shared actions duplicate, align, group, ungroup and delete the applicable selection. The empty inspector explains how to select an object; unavailable actions remain visibly disabled.

Local edits support undo/redo. Automatic arrangement records the effective pre-arrangement draft as one checkpoint, clears redo and preserves pinned positions. The Versiones action loads retained revisions; comparison displays added, removed and changed identities. Session storage retains a per-document draft and revision; refresh/open merge it against accepted document content and report conflicts. This is scoped browser-session recovery, not a claim of cross-device draft persistence or unlimited historical undo.

### Save and output

Status distinguishes saved revision, outstanding changes and saving; errors appear in a bordered alert with wrapping text. Export actions expose SVG, PNG, PDF, DRAWIO, MMD and HTML, plus editable source and interactive view. When a draft is dirty, the output label becomes Guardar y exportar/Save and export. The handler waits for Save and builds its URL from the returned document id and accepted revision; failed saving does not continue output. The interactive view opens separately. Edits made after the submitted snapshot can remain outstanding; the accepted revision is the output's boundary.

**The Accepted Revision Rule.** Output actions with outstanding changes save first and identify the accepted revision, retaining any later edits as a draft.

### Reusable shape styles — task 1038

Estilos reutilizables / Reusable styles is a secondary native disclosure inside the existing selection inspector. The library selector shows each name and revision; its visible labels and the adjacent Style name field use the existing field treatment. Apply to selection and Refresh library form one action group. Save shape as new style, Update style from this shape and Remove from library form another, keeping application distinct from library management. Unavailable or pending actions use the incumbent disabled state; saving names its busy state. The group adds no palette, shadow, decoration or separate visual identity.

Create names the selected shape's appearance; update captures that shape's current appearance and can rename the selected library style. The Design profile library lives independently of a diagram, with immutable retained revisions, so a style can be reused across documents. Apply copies fill, stroke, ink, text size/weight/alignment, border and label visibility to all selected shapes through one local change and one undo/redo step. Text, position, dimensions, pinning, pages, images and relationships remain each shape's content. Saving then publishes those appearance values through the normal document revision. Later library updates or removal leave saved diagrams and exported figures unchanged; retained style revisions remain explicitly readable.

Refresh updates the selected style and its visible revision. It adopts a remote name and advances the draft base only while the name field still matches that base's name. A manually edited name retains its original `draftStyle` revision even when refresh advances the library head; Update submits that retained base. Divergent names therefore report a `/name` conflict and preserve both the remote revision and local draft, while independent local-name/remote-stroke changes can merge. The same library is available to Faustus through `diagram_style_list/get/save/remove/apply`, using the ordinary conflict-aware revision contract described in `docs/DIAGRAM_EDITOR.md`. The UI's single local undo and native API/MCP document save are distinct operations with the same appearance-only boundary.

### Evidence and scope — reusable styles, task 1038

This addition records `StyleControls.jsx`, its import and selected-shape placement in `DiagramEditor.jsx`, and `.de-style-library` in `diagram-editor.css`, developed on isolated branch `codex/styles1038` relative to `efb85ea`. It extends the incumbent Operate inspector without a new visual contract, approved comp or independent quality bar. Root `PRODUCT.md`, `DESIGN.md` and their tokens remain authoritative and unchanged. Technical review CAS1 requested CHANGES for the refreshed name draft's revision base. The corrected submission received CAS2 APPROVE on `715959c0b0561bf2d4d93385a8e22a1dc6f3f6bc`; that source is integrated into Main and installed. The earlier checkpoints below retain their original scope; subsequent installed acceptance is recorded separately.

Evidence is under `D:/LocalAI/research-inbox/expansiones-fusiones-20261020/`. `qa1038/FINISH.txt` returns `disposition: ship` with five sections: persistence, fidelity, ceiling, material_fixes and keep. It records no material fixes for this delta. Its reviewer opened the author-supplied full desktop/mobile captures (`desktop-r1.png`, 1440×2817; `mobile-r1.png`, 390×3714) and native-size detail crops (`desktop-r1-styles.png`, 207×533; `mobile-r1-styles.png`, 328×470). Full captures establish placement; crops show wrapping, action spacing, labels/revisions and mobile full-width treatment. SHIP covers only the new control's finish and visible inspector integration; it does not replace technical review or certify other editor states.

Author `qa1038/browser-results.json` records cross-document reuse, one-step undo/redo, preserved geometry/pages/assets/text, saved documents exact after library changes/removal, adoption of an untouched remote name and preservation of a manual name draft. The accompanying browser script and `styles1038-browser-r2.log` record 1440×1000 and 390×844 viewports without horizontal overflow, JavaScript errors or bad HTTP responses. Its CSS family begins with Source Sans 3; `loaded: []` does not establish that font's loading. `qa1038/native-results.json` records 123 MCP tools, preserved manual move/text and assets/pages, and native application at document revision 3.

Author `styles1038-build-r3.log` records a successful build. The area checks include 12 new style tests; the full completed Python run is reported as 518 passed/2 skipped in `styles1038-suite-counts.json`, counted from progress statuses because double-quiet output printed no summary. `styles1038-collected.log` independently records 520 collected tests. These are author receipts read by this documenter, not repeated functional or visual QA.

After CAS1 CHANGES, `StyleControls.jsx` retains `draftStyle` as the pending name's original base across refresh and uses its revision when updating. Author real-Edge `qa1038/conflict-results.json` and `styles1038-conflict-r3.log` report PASS: a divergent `/name` preserves remote revision 2 and the local draft, independent local-name/remote-stroke edits merge, and an untouched remote name is adopted; JavaScript errors are empty. Earlier r1/r2 failures were incorrect HTTP expectations (400/200 instead of 409/201); their receipts remain retained and are not relabelled as passing. `styles1038-build-r4.log` records the subsequent successful build. The backend is unchanged, so the earlier 518/2 Python receipt retains its original scope; no new suite run is claimed. The correction changes no UI markup or CSS, so the supplied captures and prior SHIP retain their visual scope. That finish review did not functionally review this later correction or replace the technical review still pending at that checkpoint. No detector, context scan, visual finish round or browser test was repeated by this documenter.

The one supplied `styles1038-detector.json` contains 11 advisory findings for existing document-local colours, heading/control sizes and error fallback, including the local 13px disclosure size. The 13/12 inspector convention is retained; these advisories do not establish new root tokens or require global drift repair for this addition. No new context scan, detector, browser, server, model, GPU, tests or capture was run in this documentation pass. No loaded fonts, model-generated quality, unseen states or isometric origin is claimed.

Independent `review-r1038/REPORT-R2.txt` records CAS2 APPROVE against the exact `715959c` tip. Its real Edge/MCP regression verifies that the update POST still sends `base_revision: 1` after refresh: divergent names return HTTP 409 at `/name`, leaving remote revision 2 and the local draft exact; independent local-name/remote-stroke changes return HTTP 201/revision 3 with both changes and all other values exact. A clean name adopts its remote update, saved document source stays exact, and the independent build passes. The common `formSnapshot` event exposes changed fields and can omit an unchanged revision; the POST proves the submitted base. The review does not certify that a revision travels in that event or model inference quality. Its two initial helper failures remain recorded as QA expectation/setup errors, not product failures or passing executions.

`styles1038-installed-exact.json` records the installed wheel SHA-256 `ec056497af3c7977e5d6e0036b91e9e9d3f9ffeb16e4ad09dcd174913870e971`: 3,773 installed members match the wheel's raw bytes, and 388 Python sources match the approved Git blobs after CRLF/LF normalization only. Dependency versions are unchanged and `pip check` passes. The initial additional verification failed by comparing Main's raw LF source with wheel CRLF in `motion.py`; `styles1038-installed-first-check.txt` retains that failure. A verify-only rerun passed without reinstalling. This establishes the stated normalized source comparison, not raw-byte equality between Main working sources and the wheel. The installation verification did not start Luis's actual app or access its data/settings/tokens.

Installed-package author receipts under `qa1038-installed/` (`native-results.json`, `browser-results.json`, `conflict-results.json`, `final-results.json`) record 123 MCP tools, Edge at 1440/390, cross-document reuse, one-step undo/redo, retained content/source and the corrected name-race cases. No JavaScript/HTTP errors are recorded; font loading remains unproven (`loaded: []`). The final receipt has Design, Babel and Theseus OFF, automation disabled and zero active requests, with zero model calls. Root subsequently stopped the private QA processes on ports 54574 and 54577. These are supplied installed acceptance receipts, read without repeating QA here; they do not broaden the earlier visual SHIP.

`manual-styles1038-proof.json` records the functional manual addition in paragraph 87, with the other 189 paragraphs' text, styles and links exact. The manual describes the usable style library without implementation hashes, CAS or deployment-test detail. This update concerns reusable styles only; other editor functions and their historical acceptance records remain outside this addition.

### Selectable isometric parts and authored states — task 1049

This Operate/Read extension keeps the technical SVG as the principal artifact. The Mecanismo isométrico / Isometric mechanism template creates an editable assembly. State and Part are labelled native selects; the adjacent Color / Colour select restores Claro/Oscuro / Light/Dark for the figure and mode-aware exports. Changing state retains the chosen colour mode. Visible pieces can also be selected by click or Enter/Space, with button semantics, `aria-pressed` and visible focus. Part selection is distinct from the state's authored highlight. Hidden parts remain reachable by the selector, marked as hidden in the editor; the standalone reader explicitly explains their absence. Selecting a part or state changes viewing context rather than editing the source.

The inspector edits a part's short label where its kind supports labels, and its long explanation and sources without imposing the label's 24-character limit on the explanation. Geometría original / Original geometry is a native disclosure containing applicable plan coordinates/dimensions and z/h. These fields edit the base piece. State fields instead author dx/dy/dz translations, a visibility list and an optional visible highlighted piece. Add state starts from the original view; Duplicate state copies the current state's authored values under a new stable identity; Delete state returns to the original figure. Titles and state explanations remain editable. The renderer derives each state from a copy of base geometry; it does not bake poses into that base. The source validates references, finite geometry, a visible highlighted part and at least one visible piece. These are authored positions and explanations, without simulation, forces, collision, rotation, animation or physics claims.

Pieces, part notes and states use stable IDs in the native document. The inspector uses the existing local change/undo/redo path, and saved changes use the same revision store, conflict-aware merge and selective saved-change undo as other diagram edits. API/MCP object operations extend the existing `diagram_document_edit` collections with `pieces`, `mechanism_parts` and `mechanism_states`; `diagram_document_get` accepts `state_id`, and preview accepts it without mutating source. The Faustus draft context includes selected state and piece. These are schema extensions to the existing source catalog of 123 tools, not an increase in tool count.

The source download retains original geometry, all notes and every state. Save-before-output resolves the selected state against accepted content and supplies its ID to SVG/PNG/PDF, HTML, interactive view and `.vfigure` export. A portable figure carries the selected state's PNG preview and `state_id` alongside the complete native source revision. The standalone isometric HTML embeds the full source and prerendered original/state SVG frames, with state and part selectors, authored text and keyboard selection; it requires no server or network to read those embedded states after export. Explicit invalid state requests fail rather than silently falling back. Editable draw.io and Mermaid retain their graph-format boundaries; the visible output row does not establish isometric support for those formats.

**The Authored State Rule.** Preserve original geometry, explanations and every state in source; a selected state's rendering is a derived view of the accepted document revision.

### Evidence and scope — isometric extension, task 1049

The built record follows the historical 1049 direction above. Source inspected: `IsometricControls.jsx`, `DiagramEditor.jsx`, `diagram-editor.css`, `model.js`, `mechanism.py`, `isometric_reader.py`, `document_tools.py`, `exchange.py` and the API routes. Root `PRODUCT.md` and `DESIGN.md` remain unchanged. At this initial documentation checkpoint, implementation was in the author's isolated worktree, with technical CAS approval, integration and installed activation still unestablished. No global Faustus, memory or Manual acceptance is inferred.

Supplied evidence is under `D:/LocalAI/research-inbox/expansiones-fusiones-20261020/`. `qa1049/FINISH.txt` returns `disposition: ship` for this local Operate/Read extension, with no material visual fixes. Its reviewer opened `desktop-full.png`, `mobile-full.png`, `desktop-reader-r1.png` and `mobile-reader-r1.png` in that directory. The parent author also opened those captures; this documenter read the source and receipts without reopening them. SHIP covers their visible figure, selector, inspector and reader integration only. It does not certify uncaptured states, inference, technical API/MCP/CAS approval or activation. Concrete webfont loading is not established.

Author `qa1049/native-results.json` and `qa1049-native-final.log` record 123 MCP tools, complete source retained, independent edits merged, selective undo preserving unrelated edits, selected state `inside`, a 640×420 PNG and native SVG/PNG/PDF/HTML/vfigure exports. `qa1049/browser-results.json` records selected-state save/reopen, keyboard part selection, local undo/redo, dirty-state export, Faustus selection context, standalone reader and explanation of a hidden part at widths 1440 and 390, with empty JavaScript and HTTP error lists. These are attributed author executions; the finish reviewer and documenter did not repeat functional QA.

The completed full Python receipt `isometric1049-suite-r1.log` is reported by the author as 529 passed/2 skipped (531 collected) before the final two narrow backend corrections. The subsequent `isometric1049-final-area.log` records 16 passed; the author also reports two final JavaScript area checks. This composition is not a second full run of the final code. The single supplied `isometric1049-detector.json` contains 11 advisory findings for incumbent sizes, document-local white/selection colours and an existing error fallback. No detector rerun or root token repair occurred. This documentation pass performed source/receipt inspection and documentation consistency checks only; no context scan, browser, server, build, test, model or GPU execution.

### Color correction after technical CAS1 — task 1049

The independent technical review `review-r1049/REPORT-R1.txt` read submission revision 1 before testing commit `350b3e3e6b1d3d9d370515af9a4f8ba7c76c8b30` and returned CHANGES (`review-r1049/vote-r1.txt`). Its P2 found that hiding the graph toolbar also removed the inherited Claro/Oscuro selector from isometric documents, leaving the mode change accessible only through another diagram type. This later finding is retained alongside the earlier scoped visual SHIP; that visual verdict did not establish functional acceptance of the colour control.

The reviewer independently reported 88 Python area tests passed/1 skipped, two JavaScript model checks, a build and real native/API/MCP/browser/offline-reader checks in its private environment. These are reviewer executions from `review-r1049/area-tests.log`, `js-tests.log`, `native-proof.json`, `schema-proof.json` and `browser-proof.json`, distinct from the author's earlier 529/2 full receipt and 16-test final area receipt. They belong to CAS1 and do not constitute approval of the subsequent correction.

The correction changes only three UI files: `DiagramEditor.jsx` passes `setMode`, `IsometricControls.jsx` exposes the native Color / Colour selector beside State and Part, and `diagram-editor.css` uses two flexible selector columns plus 80px for colour. It changes no Python. Author `qa1049/color-results.json` and `qa1049-color-r1.log` record a visible control at widths 1440 and 390, selected state `open` retaining its mode, dark PNG bytes exact to the API export and different from light, return to light and no JavaScript errors. This documenter read the corrected source and those receipts without repeating their checks.

`qa1049/FINISH-COLOR.txt` returns SHIP with P2 resolved and no visible material regression. The parent author and finish reviewer opened `desktop-color-full.png` and `mobile-color-full.png`; the reviewer also opened their detail captures. This documenter did not reopen captures. This later verdict covers only restoration and visible integration of Color; it does not broaden the earlier `FINISH.txt`, replace technical CAS review or establish integration/installed activation. At that checkpoint technical approval remained unestablished. No detector, context scan, browser, server, test or build was rerun by this documentation pass; the earlier single advisory detector and validation history remain unchanged.

### Final technical approval, integration and installed acceptance — task 1049

This later addendum supersedes the initial pending status without changing CAS1's CHANGES, retained failures or either visual verdict's scope. `review-r1049/REPORT-R2.txt` and `vote-r2.txt` record independent CAS2 APPROVE for `350b3e3e6b1d3d9d370515af9a4f8ba7c76c8b30`, `dc3908b7412a2b117f1ecfd329448cba2503e0f3` and `898455648122108e516beffaf73bc32b771cdf1b`. The reviewer ran its own build and two JavaScript checks, repeated native MCP discovery at 123 tools and resolved the actual Color regression across original/exploded/inspection at both 1440 and 390 widths, with selected-state dark export exact to native PNG and distinct from light. It retained the earlier independent 88/1 backend results because Python was unchanged. Its initial R2 harness failure from assuming an MCP `result` envelope remains in `color-acceptance-r2.log`; the corrected read and `color-acceptance-r2b.log` passed without product changes. These are reviewer receipts, not executions by this documenter.

Main was integrated through `a7ab5cbe748ec0999365ade6205a57230dc3b5ba`, whose final change was documentation. `isometric1049-wheel-preflight-r2.json` and `isometric1049-installed-exact.json` record the final R2 wheel SHA-256 `04aada517f3557c48bf99c8f142757bcaca112edb9cdf2bcdb18a9a6f42eb7d1`: 3,771 installed members equal the wheel's raw bytes, 390 Python sources equal the Git blobs after CRLF/LF normalization, zero cache entries, and exact native resources/UI build. Distribution/dependency versions remain identical and `pip check` passes. Normalized Python source equality is distinct from raw installed-member equality. These receipts do not assert that Luis's default app or data/settings/tokens were opened.

Acceptance then used the actually installed package with Python `-I`, an external working directory and the official MCP entry point, in private QA. `qa1049-installed/native-results.json`, `browser-results.json` and `color-results.json` report PASS: 123 tools, complete source and selected state retained through five native exports, independent merge and selective undo, 1440/390 keyboard selection, save/reopen, dirty export, offline HTML reading and Color. The supplied browser evidence records no JavaScript/HTTP errors or horizontal overflow. The original installed native helper failed with `httpx.ReadTimeout` under its five-second HTTP default; `isometric1049-installed-native.log` retains that failure. After increasing the helper timeout to 180 seconds, `isometric1049-installed-native-r2.log` passed, with observed SVG/PNG/PDF/HTML/vfigure durations of 0.010/1.466/1.148/0.007/1.289 seconds. No unobserved cause is assigned to the first timeout. Subsequent installed browser and Color logs passed.

The parent reports source and installed QA ports 54580/54584 stopped after all three modules were OFF with zero active jobs; default port 5191 was never started. `manual-isometric1049-cicero1051-proof.json` records native Manual CAS/readback updating only paragraphs 87 and 99, with the other 188 paragraphs' text, styles and links exact. Its documented consumer case is installed Cicero task 1051, product commit `1ce161f`, with captured state and 69-tool QA; this does not establish universal `state_id` consumer support. This documenter inspected supplied acceptance receipts only and performed no new QA, CPU evaluation, build, detector, browser, server or capture run. Root PRODUCT.md/DESIGN.md and the earlier 529/16, independent 88/1 and scoped FINISH history remain retained.

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
