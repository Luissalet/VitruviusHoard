---
name: "Vitruvius diagram editor"
description: "Surface record of the native graph document editor inside the existing Hoard workbench"
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

## Overview

**Creative North Star: "Existing Hoard workbench"**

This Operate surface lets a person edit an independent diagram document directly, with the same document available to Faustus through the native product integration. Its dark shell, restrained blue selection, Cinzel headings and Source Sans 3 controls extend the incumbent workbench. The drawing is editable SVG; no raster asset establishes its identity.

This is a surface-specific record for `client/src/pages/Diagrams.jsx` and `client/src/components/diagram-editor/`. Root `PRODUCT.md` and `DESIGN.md` retain authority. The companion `.impeccable/surfaces/diagram-editor.json` records this surface only; neither it nor this brief replaces the root system, repairs its reported drift, or establishes automatic discovery by the current Impeccable context loader.

The code-led direction preserves the existing world without an approved comp or a replacement visual identity. The task sequence is open/create/import, edit shapes and relationships, inspect properties, save a revision, then export or open the interactive view. The first viewport prioritizes a visible working drawing; secondary controls remain available. Earlier source rendering, type suggestions, brand profiles and recent diagrams continue below the editor. This delivery records the first graph editing core; infographic composition, page/state work and downstream consumers remain later scope.

**Key Characteristics:**
- An independent versioned document with a visible name, save state and selected revision.
- A native SVG canvas between a shape palette and selection inspector on wide screens.
- A recoverable mobile shape palette and useful drawing area in the first viewport.
- Shared shape activation for pointer and keyboard, with explicit connection and selection modes.
- Output actions save an outstanding draft and use the accepted revision.

## Colors

### Primary

Workbench blue marks primary actions, the active editing tool, focused objects and keyboard outlines. Its brighter sibling is the primary-action hover treatment. These are inherited shell tokens, not a new editor palette.

### Neutral

Charcoal page, panel and raised surfaces form the shell hierarchy. Fine neutral borders separate bars, palette, inspector and export region; pale text and muted helper copy preserve the existing density.

The document has its own profile, selected by Claro/Oscuro. The source fallback uses white paper (`#ffffff`), dark ink (`#1d2433`), pale shape fill (`#f3f5f9`), grey outlines (`#8a94a6`), blue connectors (`#2f5bd3`) and muted labels (`#5b6474`). A supplied profile replaces these document values. They remain document-local, editable visual material and are deliberately absent from the shell token frontmatter. Only the light profile is shown in the supplied final captures.

**The Document Ground Rule.** The drawing profile belongs to the document; changing it does not replace the surrounding Hoard theme.

## Typography

The page headline uses the inherited serif headline role. The editor heading is a smaller serif step (20px desktop, 18px at the mobile breakpoint); its implementation uses the `--font-display` override with Cinzel fallback. Body, helper and control text inherit the shared sans family. Compact status, inspector labels, export labels and canvas help use the label role; graph labels use regular sans (13px), with connector labels one step smaller (12px). Multiline node labels use separate SVG text spans (17px line steps).

**The Workbench Type Rule.** Preserve the inherited serif heading and sans control relationship; document labels remain legible working content rather than a new display voice.

## Layout

Wide screens use a three-column editor: palette (144px), flexible canvas with zero minimum width, inspector (236px). Hiding the inspector releases its column. Below 1100px the palette narrows (120px) and the inspector moves below the canvas into three columns. At 650px and below the workspace becomes one column and the inspector uses two columns. The normal canvas height is 480px, becoming 390px on mobile; its SVG viewBox responds to measured available width, zoom and pan.

The editor stacks a compact heading, document/template controls, name/save/status/undo toolbar, workspace and wrapped export actions. Desktop keeps the shape palette visible. Mobile initializes it closed and exposes Formas with `aria-expanded`; opening it restores the same controls as wrapping buttons. Crossing the breakpoint resets palette availability for the new layout. The mobile heading drops its supporting sentence, name and Save share a row, and secondary toolbar actions wrap before the canvas. The existing outer sidebar becomes horizontal section navigation on narrow screens.

The final mobile capture is 390px wide for a 390×844 viewport; the supplied author receipt places the white canvas at y550.78, leaving about 293px visible before the viewport ends. This is evidence for the captured state, not an invariant coordinate for every language, font or document. At 100%, portions of a larger drawing can lie beyond the visible viewport: Ajustar/Fit, zoom and pan make them reachable. The desktop capture retains all three columns. The earlier source and brand tools stack below on mobile.

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

### Evidence and scope

Source inspected: `DiagramEditor.jsx`, `diagram-editor.css`, `model.js`, `pages/Diagrams.jsx`, `index.css` and the Vitruvius block in `hoard-theme.css`. Existing root product/design files and the supplied `context-editor960.txt` were read without modification. Evidence directory: `D:/LocalAI/research-inbox/expansiones-fusiones-20261020/`. Both final `editor952-desktop.png` and `editor952-mobile.png` were opened by this documenter; their final file dimensions are recorded in the sidecar. No new browser, server, detector, model or functional suite was run in this documentation pass.

`finish-review960.txt` requested five material corrections. `finish-verdict960.txt` scores all five resolved and returns `ship`: save-before-output, distinct reciprocal routes, keyboard activation/multiselection, useful first mobile viewport and arrangement undo/redo. Its functional receipts are author evidence contrasted with code, not fresh independent executions by this documenter or reviewer. The verdict explicitly does not certify the whole surface, LLM inference, or the new Python connector/export routing that was not yet loaded in the QA server at that checkpoint. Subsequent activation and functional acceptance require their own evidence.

Not canonized: document-local colors/shape geometry, the adjacent selects' missing visible captions, zoom glyphs as a general icon system, and uncaptured states do not become workbench-wide rules. These are content, local implementation details or incomplete evidence, not a replacement identity or a reason to reproduce a limitation. No raster asset was authored for this surface.

## Do's and Don'ts

### Do:
- **Do** preserve the incumbent Hoard shell, navigation, language switch and Faustus integration.
- **Do** keep the document profile separate from the workbench palette.
- **Do** retain a useful mobile drawing area with the shape controls recoverable through Formas.
- **Do** keep pointer and keyboard activation consistent for node selection and connection creation.
- **Do** keep reciprocal routes visually distinct and preserve access through Fit and pan.
- **Do** save outstanding changes before output and use the accepted revision in its URL.
- **Do** retain the earlier diagram source, brand and recent-result tools below the editor.

### Don't:
- **Don't** promote a graph template's palette or shape vocabulary into a new shell identity.
- **Don't** silently export the previously saved revision when the action promises to save the current draft.
- **Don't** describe every diagram type as object-editable from the graph canvas implementation.
- **Don't** turn five resolved finish findings into certification of LLM inference or untested runtime exports.
- **Don't** represent future infographics, page/state work or downstream consumers as delivered by this first graph core.
