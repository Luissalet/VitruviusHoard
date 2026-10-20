# Editable diagrams

Design → Diagrams contains a visual graph editor alongside the existing structured renderer. A diagram is an independent document: it does not require an application-source project. The original renderer, formats, brand profiles and diagram types remain available.

## Shared document

`diagram_document_list/get/save/edit/undo/history/compare/import` are native MCP tools, also exposed through the owner catalog. REST lives under `/design/api/diagrams/documents` in the combined application. The design module must be explicitly enabled; discovering its tools never starts it.

The native source export has `format: "vitruvius.diagram/1"`, a captured revision, and `content`:

- `diagram`: existing semantic structure, persistent node/edge/group IDs, labels and authored node explanations.
- `view.nodes`: positions, dimensions, pinning and optional fill/stroke/ink, keyed by node ID.
- `view.edges`: source/target ports and intermediate points, keyed by connection ID.
- `profile`: the existing light/dark brand roles and font; `source` retains imported material.

Documents and immutable render/source revisions are published together in `diagrams/documents.sqlite3`, within the existing design data directory. Legacy saved SVGs remain untouched. Empty discovery does not create the database.

An edit supplies the revision it actually read. Independent fields merge; a conflicting field returns HTTP409 and its path, without publishing a partial revision. Object edits can add/remove/update nodes, groups, connections and geometry. Deleting a node removes incident edges. Undo reverses a specific published change while preserving unrelated later fields. The editor additionally maintains undo/redo for its local draft; session drafts survive navigation within the same browser session.

Example native operation:

```json
{"id":"012345abcdef","base_revision":3,"edits":[{"collection":"nodes","id":"review","values":{"label":"Review the source"}},{"collection":"view_nodes","id":"review","values":{"x":260,"pinned":true}}]}
```

The common Faustus panel receives document identity/revision, selection and the current draft. Its refresh merges independent published changes into the draft. Manual drawing, saved revisions and exports do not require a model. LLM requests use the configured family service; this feature does not start another text model.

## Visual operations

The first visual surface edits graph types: flowcharts, architecture, state, ER and swimlane graphs. Templates cover review processes, architecture, organisation charts, concept maps and comparison. Shape creation, pointer dragging/resizing, labels, connections and their endpoints/ports, styles, multi-selection with Shift, arrow-key nudging, duplication, grouping/alignment, zoom, pan and automatic layout are available. Pinned boxes survive automatic layout. Native source and previous structured render controls remain available for all diagram types.

100% uses document pixels. **Fit** shows the whole drawing; large diagrams otherwise extend beyond the viewport and can be panned. The mobile inspector moves below the canvas. This is the first graph delivery: multipage infographic composition, authored isometric states and linked insertion into other Hoards are subsequent work, not implemented by these controls.

## Interchange

| Format | Preserved/tested scope | Limit |
|---|---|---|
| Native JSON | Source, IDs, profile, manual layout, ports/points and captured revision | Import creates a new document; it does not copy server-side revision history |
| draw.io | Graph nodes, group membership, labels, shape subset, geometry, edge identity and intermediate points | Full draw.io style vocabulary, nested container semantics and arbitrary extensions are not claimed; original retained and warning returned |
| Mermaid | Graph labels and relationships on export; existing import types | Layout, stable native IDs, profile and authored explanations remain in native JSON |
| Excalidraw | Existing supported shape/arrow import subset | Original retained; no general style/layout fidelity claim |
| SVG | Frozen light/dark revision and manual geometry | Vector output, not native semantic source |
| PNG/PDF | Browser render of frozen SVG with no remote asset/model request | Requires the render extra and an available Chromium browser |
| HTML | Self-contained frozen SVG plus keyboard/clickable authored graph traversal | Authored relations do not establish measured runtime dependencies |

Exports always name a revision. Editing the document does not alter already exported figures. MCP reads return source, export and viewer URLs for the same revision. No source, runtime, CLI or service from the research reference projects is required.

## Acceptance evidence

Area tests cover immutable reopening, simultaneous writers, same-field rollback, selective undo, object deletion, graph exchange (including colliding IDs across object kinds), malformed inputs and REST revisions. Existing diagram tests remain included. The isolated Chromium/MCP acceptance uses a synthetic twelve-node document: pointer and keyboard edit, native stdio edit concurrent with a manual size change, exact deep-link reopening, revision history, five export formats and interactive reading. Desktop1440 and mobile390 have no page overflow or JavaScript errors in that run.

Evidence is recorded under `D:/LocalAI/research-inbox/expansiones-fusiones-20261020/`. It does not certify LLM reasoning quality, infographic workflows or insertion into all other Hoards. Main-app activation and live profile migration are coordinated separately with the installation owner.
