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

100% uses document pixels. **Fit** shows the whole drawing or current editorial page; large diagrams otherwise extend beyond the viewport and can be panned. The mobile inspector moves below the canvas. Authored isometric states and linked insertion into other Hoards remain separate work.

## Editorial pages

### Reusable shape styles

The inspector's **Reusable styles / Estilos reutilizables** disclosure saves the
selected shape's appearance in the Design profile, independently of any document.
The library retains names and immutable revisions in the diagram SQLite store.
Choose a preset and apply it to all selected shapes in one local undo step;
saving publishes the same values in the normal document revision. Text, position,
size, pinning, page, image and relationships remain on each shape. Library updates
and removal never modify previously styled documents or exported figures.

`diagram_style_list/get/save/remove/apply` expose the same functions. REST uses
`/design/api/diagrams/styles`: GET lists; POST saves `{name,values,id?,base_revision?}`;
GET `/{id}?revision=N` reads an exact revision; POST `/remove` requires
`{id,base_revision}`; POST `/apply` takes `{id,base_revision,style_id,style_revision,node_ids}`.
Style values are fill/stroke/ink, font_size/font_weight/align, border/show_label;
save supplies the complete appearance object. Updating a style merges independent
fields from the revision read; conflicting fields retain the existing source and
return the same conflict contract as document edits. Removed style revisions stay
readable explicitly, and saving from the retained head restores it to the library.
Application copies that exact style revision into a normal conflict-aware document
save. An assistant's independent text/position edits survive; a conflicting color
change remains a conflict. Listing an empty library creates no store.

Four infographic templates cover comparison, timeline, process and relationships.
They use the same graph source with `view.kind="infographic"`. `view.pages` holds
stable IDs, title, order and pixel width/height. Each `view.nodes[id].page_id`
chooses a page; font_size, font_weight, align, ink, border and show_label control
its text and appearance. Labels in editable documents can hold longer body copy;
legacy structured render requests keep their existing short-label contract.
`view.assets` retains PNG/JPEG/WebP as embedded data URIs. Blocks refer to these
assets by ID; native JSON and exports do not require the original image file.

Page selection, creation, duplication, order, title, dimensions and deletion use
the existing editor. Page options hold less frequent settings. Deleting a page
in the UI deletes its blocks and incident links; native object edits can instead
move blocks to another page first. Local and saved undo share the existing
history. Object-edit collections also include pages, assets and view. A page
object uses set/add/remove; view properties use set, and assets use keyed IDs.
Each page draws its own nodes and internal links. Cross-page relationships stay
in the semantic source and interactive reader. Automatic graph layout remains
available for graphs; editorial templates retain their manually authored layout.

Text remains editable. The renderer uses approximate character wrapping, not
font shaping or desktop-publishing line layout. Saved renders report blocks
outside page bounds and text that needs a larger box. These findings inform
correction without blocking a save. Fit can make small-page labels small on a
phone; zoom, pan and the inspector remain available.

## Interchange

| Format | Preserved/tested scope | Limit |
|---|---|---|
| Native JSON | Source, IDs, profile, manual layout, ports/points and captured revision | Import creates a new document; it does not copy server-side revision history |
| draw.io | Graph nodes, group membership, labels, shape subset, geometry, edge identity and intermediate points; editorial pages, text styles and embedded raster images | Full draw.io style vocabulary and arbitrary external extensions are not claimed; cross-page links use native extension metadata; original retained and warning returned |
| Mermaid | Graph labels and relationships on export; existing import types | Layout, stable native IDs, profile and authored explanations remain in native JSON |
| Excalidraw | Existing supported shape/arrow import subset | Original retained; no general style/layout fidelity claim |
| SVG | Frozen light/dark revision and manual geometry; editorial pages stacked vertically | Vector output, not native semantic source |
| PNG/PDF | Browser render with no remote asset/model request; PNG stacks pages, PDF uses one page per authored page with its own size | Requires the render extra and an available Chromium browser |
| HTML | Self-contained frozen SVG plus keyboard/clickable authored graph traversal | Authored relations do not establish measured runtime dependencies |

Exports always name a revision. Editing the document does not alter already exported figures. MCP reads return source, export and viewer URLs for the same revision. No source, runtime, CLI or service from the research reference projects is required.

## Acceptance evidence

Area tests cover immutable reopening, simultaneous writers, same-field rollback, selective undo, object deletion, graph exchange (including colliding IDs across object kinds), malformed inputs and REST revisions. Existing diagram tests remain included. The isolated Chromium/MCP acceptance uses a synthetic twelve-node document: pointer and keyboard edit, native stdio edit concurrent with a manual size change, exact deep-link reopening, revision history, five export formats and interactive reading. Desktop1440 and mobile390 have no page overflow or JavaScript errors in that run.

Editorial area tests also cover independent page edits, selective undo, long
Spanish text, retained raster bytes, page dimensions and actual PNG/PDF output.
The synthetic browser case saves/reopens two pages, ten blocks and an image at
1440/390 without JavaScript errors or overflow. Evidence is recorded under
`D:/LocalAI/research-inbox/expansiones-fusiones-20261020/`. It does not certify LLM
reasoning quality or insertion into all other Hoards. Main-app activation and
live profile migration are coordinated separately with the installation owner.
