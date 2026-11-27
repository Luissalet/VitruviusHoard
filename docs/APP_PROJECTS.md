# Native application projects

The Applications page and `/api/app-projects` expose a complete source workspace. `app_templates` lists work board, reference library, inventory and booking. `app_project_create` saves pages, global layout, styles, client, typed declarations and a standalone Python server. No framework repository, external CLI, generated model or workbench installation is required to run the exported app.

`page_check` checks an owned preview in a browser. Writes blocked while the page loads and before the case acts appear in `startup_blocked_writes`. A case that hits the read-only preview boundary after acting names the blocked request and stays unverified. When this blocks an explicit criterion, the checker still runs the other requested criteria and marks automatic cases as unchecked. A run that reaches its deadline returns completed cases and `stopped_at` with the current phase, case and action when available.

## Source and data

`app_project_get` returns every source file and its selected revision. `app_project_update` accepts a file patch and `expected_revision`; unchanged files are preserved. Disjoint edits merge across newer revisions. A conflicting edit to the same file reports the affected path and preserves both the current saved revision and the caller's draft. Earlier revisions remain readable/exportable. The UI retains drafts while switching files, revisions and projects, and keeps edits made after an asynchronous save started.

Project creation and source edits return an `app_project_undo` call. Use it while the recorded update is still current. Undoing a source edit restores the earlier source and retains both revisions. The creation receipt only applies while the project has had no saved source edits. If you save a revision and then undo it, the history stays and the creation receipt cannot be used to retire the project.

### Archive and restore

Use **Archive project** in Applications and confirm. The preview closes and the project moves from **Active** to **Archived**. The project ID, saved revisions, records and existing exports are kept. Use **Restore** on its archived row to make the project available again. Open the preview when you want to resume.

Use `app_project_archive` with the project ID, `expected_revision`, `operation: "archive" or "restore"` and `confirm: true`. For a receipt that also checks whether the archive state has changed, pass `expected_updated_ts` from the current project or archived listing. A change returns an `undo` call for the opposite operation with both checks set. The HTTP equivalent is `POST /api/app-projects/{id}/archive`. Both interfaces reject stale checks. The HTTP API returns 409 for a conflict. An already applied operation with the current checks returns `changed: false`.

Use `app_project_list` to list active projects or use `archived: true` to find archived ones with their revision and update timestamp. The HTTP archive list is `GET /api/app-projects?archived=true`. Restore an archived project before reading or editing its source.

A single-record-type `project.json` declares `name`, `description` and `fields`. Fields have an identifier `name`, human `label`, `type` (`text`, `number`, `boolean`, `choice`), optional `required`, and `choices` for a choice field. Record identity uses the reserved `id` property. The original starter supplies matching `contracts.d.ts` and an annotated client; custom schema edits should keep their custom declarations/client consistent. Runtime input validation uses the running revision's schema. Existing stored values are retained rather than silently migrated or removed when a schema changes.

The server discovers `pages/**/*.html`: `index.html` defines the containing path and `[parameter].html` defines a dynamic segment. `layout.html` wraps each page. Templates support `{{name}}`, `{{description}}`, `{{table}}`, `{{form}}`, `{{count}}`, `{{query}}`, `{{record_title}}` and escaped `{{param_name}}` values. This is HTML templating with server-rendered content; it does not execute template expressions. Source files can be edited to change the runtime itself.

Data lives separately in `app-projects/<id>/data/app.db`. It survives preview restarts and source revisions. The record API uses SQLite write transactions; independent field updates merge in one transaction. The supplied client sends changed fields for edits and retains newer form edits if an older request completes. Source revision history is independent of data. The single-record-type API retains its existing data operations.

## Collections and declared actions

A `vitruvius-app/v2` project declares named `collections` and `actions` in `project.json`. Create a custom project with `app_project_create` using `template: "custom"` and a `files` map with `project.json`, `layout.html`, `pages/index.html` and any other pages or assets. Omit `server.py` to save the current built-in standalone runtime with the project. To upgrade an existing project, save the new specification and the current `vitruvius_hoard/app_runtime.py` as `server.py` in the same source revision. Earlier source versions and their data are retained. The legacy starter reads its original single-type records, and the v2 runtime uses separate tables for named collections.

Each collection has `fields` and optional initial `records` with explicit string IDs. Identifiers for collections, actions and fields start with a letter or underscore and can contain ASCII letters, digits and underscores. Record IDs also allow hyphens and can start with a digit. A new collection's records are inserted together on its first start, including references between collections declared in either order. Editing initial records after the first start leaves the stored records intact. A source-only export loads the stated initial records on first start. An export with data keeps the captured records and action receipts.

Fields are required by default. In addition to the v1 field types, `integer` accepts integers in the range from −(2⁵³−1) to 2⁵³−1 and optional inclusive `min` and `max`. Use it for money in minor units. A `ref` field names a target `collection` and takes an existing record ID. A `text` field with `format: "iban"` normalises whitespace and case and checks the generic IBAN form and MOD97 checksum. Declare that format on stored and input fields used in the same lookup.

Actions validate the `input` field list. `exactly_one` can require one of the named optional inputs. Omit an absent field. `confirmable_by_voice` is metadata for clients that gather and confirm data before submitting it.

- An expression is a scalar literal, `{"input":"field"}`, `{"record":"lookup_alias","field":"field"}`, `{"negate":expression}` for an integer, or `{"coalesce":[expression,...]}` to select the first present value.
- An optional named `lookups` object resolves records by exact field value. Each entry uses `collection`, `field` (including `id`) and `equals` (an expression). A missing match yields no value. Multiple matches reject the action with `ambiguous_reference`. Lookups run in declaration order and can use earlier aliases.
- An optional `different` pair of expressions rejects equal values when both are present. An effect's optional `when` runs it when the expression is present, including a present zero or false.
- An `adjust` effect names `collection`, `id`, integer `field` and `amount` (a signed integer expression). A debit below the field minimum returns HTTP 409 with `insufficient_balance`. A `create` effect names `collection` and a `values` object of field expressions. An absent evaluated value is omitted and required fields still apply.

The following action deducts units from a seeded stock record and logs the change.

```json
{
  "format": "vitruvius-app/v2",
  "name": "Stock room",
  "collections": {
    "stock": {
      "fields": [{"name": "units", "type": "integer", "min": 0}],
      "records": [{"id": "shelf-1", "units": 12}]
    },
    "entries": {
      "fields": [
        {"name": "stock_id", "type": "ref", "collection": "stock"},
        {"name": "units", "type": "integer"}
      ]
    }
  },
  "actions": {
    "take": {
      "input": [
        {"name": "stock_id", "type": "ref", "collection": "stock"},
        {"name": "units", "type": "integer", "min": 1}
      ],
      "effects": [
        {"op": "adjust", "collection": "stock", "id": {"input": "stock_id"},
         "field": "units", "amount": {"negate": {"input": "units"}}},
        {"op": "create", "collection": "entries",
         "values": {"stock_id": {"input": "stock_id"}, "units": {"input": "units"}}}
      ]
    }
  }
}
```

These declarations run the fixed operations in order inside a single SQLite write transaction. If any effect fails, the transaction rolls back every change and no receipt is committed. On success the response contains `ok`, `action`, `undo_token` and an ordered `changes` array with each effect's `collection`, `operation` and resulting `record`. Undo reverses the receipt atomically and returns 409 if newer changes or references would be lost. The app can supply an idempotency key per confirmed operation. A retry with the same key and normalised input returns the original receipt, and a different input or already undone receipt returns 409.

| Operation | Owned preview and standalone HTTP | `app_project_call` arguments besides `id` |
| --- | --- | --- |
| Discover schema and actions | `GET /api/schema` | `operation: "schema"` |
| List or search records | `GET /api/collections/{collection}?q=...` | `operation: "list", collection, query?` |
| Read one record | `GET /api/collections/{collection}/{record_id}` | `operation: "get", collection, record_id` |
| Execute an action | `POST /api/actions/{action}` with the input object as JSON and optional `Idempotency-Key` header | `operation: "invoke", action, data, request_key?` |
| Undo an action | `POST /api/action-receipts/{undo_token}/undo` | Apply the returned `undo` call or use `operation: "undo_action", undo_token` |

The native `POST /api/app-projects/{id}/call` accepts the same arguments as the tool. V2 runtime errors use an `error` message and a stable `code`. Custom pages can use relative API URLs and present translations based on those codes. V2 HTML templates provide `{{name}}`, `{{description}}`, `{{query}}`, `{{param_name}}` and `{{content}}`. Use a custom client to render or act on collections.

For step-by-step transfer entry by text and local microphone, see the [transfer assistant](APP_TRANSFER_ASSISTANT.md).

## Preview, calls and inspection

`app_project_preview` starts an owned hidden Python process on a free loopback port, or stops that project's process. It reuses a healthy process for the same revision. When changing revisions, it starts the captured source and switches the proxy after the new runtime is ready. The preview keeps the same loopback URL until stopped and works in the workbench iframe or an independent browser tab. Previews stop when Vitruvius shuts down, while records and source remain saved.

In Applications, **Open preview** starts the saved revision in the workbench. **Open in tab** opens that running preview at the full width of the browser. Copy the button's link to reuse it across preview restarts. The workbench host accepts both `/design/api/app-projects/{id}/preview/open` and `/api/app-projects/{id}/preview/open`. An optional URL-encoded `path` query parameter opens a page such as `/transferir?lang=en`. Set `lang=es` on the stable link for Spanish error messages. Both links redirect to the current preview origin with a non-cached 307. They return 503 with instructions while the preview is stopped and 404 for an archived or unknown project. The `app_project_preview` start result supplies the short `open_path` alongside the current `url`.

The Applications page connects the App Dock bridge to the visible preview. Agents can read the open page with `app_project_canvas_view` and point at or operate its controls with `app_project_canvas_act`. See [the canvas tool and frame contract](APP_CANVAS.md).

For single-record-type projects, `app_project_call` provides `list`, `get`, `create`, `update` and `delete`. Their standalone application exposes the following routes.

- `GET /api/health`, `/api/schema`, `/api/routes`.
- `GET/POST /api/records`, `GET/PATCH/DELETE /api/records/<id>`.
- `POST /actions/create`, `/actions/update`, `/actions/delete`.

Inputs are checked against the declared field types and choices; text stays literal in server-rendered pages. These are application JSON calls with a generated typed client, not component compiler transforms. Additional runtime behavior belongs to the editable project's code.

`app_project_render` captures the selected owned preview through a local browser worker into the existing render history, with project identity, source revision and source SHA in the metrics. Existing `design_critique` can inspect that render. Source is pinned for a preview process; data can change between screenshots if users continue editing it. The ordinary HTML patterns, reference gallery, tokens, diagrams, movement and criterion library remain available.

`design_critique` and `page_assay` can also open a loopback preview by URL. Assay uses the page in place so its relative assets remain available. Loopback assay reads the preview. Use the publication's synthetic form check to verify an inbox write. Set `VITRUVIUS_BROWSER_CHANNEL=chrome` to prefer the installed Chrome channel, for example on a machine with more than one supported channel.

## Selecting elements on the preview

With the preview open, **Select** (button, or `Alt+Shift+S`) turns on a selection mode over the framed page. Hovering shows a thin outline with the element name. The outline clears when the pointer leaves the preview, and a chosen element keeps its own outline and label. A click selects it, `Shift`+click adds or removes one, `Tab`/`Enter` choose by keyboard, `Esc` leaves the mode. Outside the mode the page is used normally, and the overlay has no transitions under `prefers-reduced-motion`. The chips below the preview list what is selected (tag, class, text, source position, and "affects N elements" when several served elements share one source position); each chip has a remove button, and **Clear all** empties the list.

Each selected element is a card: a stable selector (`data-vid`, then `id`, then a unique `data-vsrc`, then the shortest unique `tag:nth-of-type()` path), its visible text (up to 200 characters), its HTML (up to 1200 characters), its box in page coordinates, tag and classes, a few computed styles, `same_vsrc_count`, its source position when the page carries one (`data-vsrc="file:line:column"`, or the position of the `{{marker}}` that generated it, with `data-vgen`), `own_vsrc` (whether that position is the element's own), and the revision the page was served from. A page without annotations still selects; the card then says it has no source position. The card also carries `clip`, a small image of the element made by the page (an SVG `foreignObject` drawn to a canvas, up to 150 KB). Pictures the page has already loaded (`<img>`, `<canvas>`, CSS background images) are drawn into the clip from their own pixels, including a project's own SVG and PNG assets, also when the selected element is itself the picture; one the browser will not hand over (another origin) or that is not loaded is left out of the clip, and the card says so (`clip.omitted`, `clip_note`): the tool returns its size and, with `clips: true`, its pixels as a data URL; the copilot and App Dock contexts carry only its description.

The revision comes from the served page (`<meta name="vitruvius-preview-revision">`), not from what the workbench believes, and travels in every message and card. The selection reaches the agent three ways: the copilot turn context carries a card per element (selector, source, text, HTML excerpt, styles, revision), the page's App Dock context (when the bridge is present) carries the whole card of each element in its `view` (`kind: preview-selection`, with the revision) and names them in `summary` and `focus`, and the read-only tool `app_project_selection` (`id`) returns the full list of the open preview, so "change this" needs no description. An empty list says nothing is selected.

The list is kept in memory per project and is replaced on every change. It is bound to the preview process: once the preview stops (by the person, by an agent's `app_project_preview` stop, or by a crash) or restarts, reading it returns an empty list; so does a read while the preview serves another revision than the selection was taken on (the page reports again once it settles), and the server refuses a report that names another revision (`409`). It belongs to one page: following a link to another page clears it, while a reload of the same page keeps it. Each element is remembered as what it was when chosen: tag, visible text, source position, place among its siblings and the names it declares (`data-vid`, `id`, `href`, `name`). A `data-vid` or `id` is the element's own name: the element that still has it is the same element wherever it moved (two rows with the same text and different ids keep their own selection when swapped), and when nothing has it any more the selection expires; `href` and `name` tell lookalikes apart. After a new revision is served (a live refresh patches the page in place), or when the page replaces the element, it is matched again by tag and text; several lookalikes are told apart by source position and then by place, and a source position alone is never an identity across revisions (editing the source reassigns positions, so swapping two rows moves the selection with the row's text, not with the position). An element whose text changed at the same place and whose old text appears nowhere else is the same element edited in place, unless the new text used to belong to a neighbour. Otherwise the element is kept in the list as **expired**: flagged in the chips, listed apart by the tool (`expired`, never in `selection`), and removable by the person; it is never handed to a neighbour. A frame the live refresh swaps in (after an edit of `layout.html`, for instance) is greeted by the workbench, which gives it the selection back, so chips, highlight and tool agree again. A report needs the served revision: the store refuses a non-empty selection without one, and one whose cards name another revision than the report.

The script is `vitruvius_hoard/preview_scripts/preview-inspector.js` (also served at `/api/app-projects/preview-inspector.js`; `preview_inspector.inspector_script()` returns its text). It is loaded only into the owned preview, next to the App Dock bridge, by whatever injects scripts into the preview pages; it is never part of an export, and `server.py` does not reference it. It has no dependencies and no vendored code. Its overlay lives in a shadow root under its own element whose inline `!important` style (and re-attachment, if the page removes it) keeps project CSS from hiding it; the crosshair cursor is an adopted stylesheet, so the page's own inline styles are never touched.

Messages use the bridge's envelope, `{hoardDock: 1, type, ...}`, and only travel between the preview frame and the Vitruvius page that frames it. The host checks the source window and origin of every message. The inspector listens only to its parent window and fixes the parent's origin once, from the browser's ancestor origin or else from the first `inspect/hello`; messages from any other origin are ignored afterwards.

- page → host: `dock/inspector-ready {mode, page, revision, selection}`, and `dock/select {mode, page, revision, selection}` after every change. `selection` is the whole list of cards.
- host → page: `inspect/hello`, `inspect/mode {on}`, `inspect/clear`, `inspect/remove {index}`, `inspect/dismiss {index}` (an expired item), `inspect/restore {items}` (identities: selector, tag, text, vsrc, own_vsrc, parent, index, near, revision, expired).

`GET`/`PUT /api/app-projects/<id>/selection` read and store the list (the Vitruvius page stores it; the tool reads it).

### Source positions in the preview

The owned preview maps each served opening tag in `layout.html` and `pages/**/*.html` to a `data-vsrc` value such as `pages/index.html:1:49`. Lines and columns start at 1 and count Unicode code points, including an initial BOM. The offset points to the opening angle bracket. The preview preserves the original newlines and source files. The static `public/` site follows its own client and asset paths.

`app_project_source_count` takes id, vsrc and an optional preview path (including its query). It returns `same_vsrc_count` for that rendered response, with the preview's revision. Reusing `{{content}}` in a layout can serve the same source tag several times. The table and form fragments mark their existing top-level elements with `data-vgen` and the marker's source position. For a generated descendant, use the closest `data-vgen` ancestor.

`app_project_edit_source` takes id, vsrc, tag, `expected_revision` and a change. Use the revision from the preview that supplied the selection. A mismatch in revision, tag or position requires a fresh selection. The tool saves through `app_project_update` and returns its undo call after a material edit.

- `{"kind":"text","value":"New label"}` replaces a single direct literal text node, preserving surrounding source indentation.
- `{"kind":"attribute","name":"aria-label","value":"New label"}` sets a literal attribute. A null value removes it.
- `{"kind":"class","operation":"add","value":"emphasis"}` adds one class. Use remove to remove it.

A marker-generated fragment, a text node with template bindings or an attribute bound to a marker identifies the marker in the error. Edit the corresponding project fields, records or styles. The position tool also reports ambiguous text when an element has multiple direct text nodes and leaves script and style bodies to the source editor. Use `lang: "es"` for Spanish edit messages.

The HTTP equivalents are `POST /api/app-projects/{id}/source-edit` and `GET /api/app-projects/{id}/source-count`. The packaged starter runtime applies the map only when launched by the owned preview. Exported source and the ordinary standalone server contain no preview markup. Earlier stock starters get the source map in preview while retaining their exact saved runtime on export. Custom runtimes can use the starter's optional template-rendering hook. The preview reserves the `data-vsrc` and `data-vgen` attribute names.

### Live preview

An open Applications preview follows project source changes saved in the editor or by `app_project_update` and `app_project_edit_source`. Undo through `app_project_undo` follows the same path. Unsaved drafts and an explicitly selected historical revision remain available in the source editor.

`GET /api/app-projects/{id}/events` streams `revision` events with the current and previous revision IDs, changed `files`, and inclusive before/after line spans for page HTML. A span with no lines ends before its start. `global_styles` lists changed stylesheets linked by the layout. The event ID is the new revision. A reconnect can use `Last-Event-ID` or the initial `revision` query parameter to recover changes since a saved snapshot.

When the preview has source annotations, a page-only change can replace the affected DOM nodes while preserving the rest of the page. A changed page stylesheet can load in place. Layout, layout stylesheets and client code load in a replacement frame prepared while the previous page remains visible. The new frame opens on the same route and restores its scroll position when the preview bridge can report them. It opens the project's entry page if the old route has gone away. Custom or older runtimes without source positions use the replacement frame. The preview highlights the changed elements with a short outline and uses a static outline when reduced motion is enabled.
## Comments pinned on the preview

Next to **Select** the preview bar has **Comment** (button, or `Alt+Shift+C`). In the mode a click picks one element (a link is not followed), a note box opens with a crop of the element, and **Save comment** pins the note on it: a compact numbered pin sits at the element's top-right corner. The draft shows a dashed outline and the element name while the person writes. `Esc` leaves the mode. The comment keeps `{vsrc, own_vsrc, vgen, selector, tag, classes, box, element text, page}`, the note, **the revision the page was served from when the element was picked** and the crop. A draft keeps the revision of the page it was picked on: if the preview serves another revision when it is saved, the draft is dropped with a message (the server answers 409), never saved as the newer one. A revision the project does not have is refused with a message.

A comment moves through these states, and the pin shows each one by colour and glyph (and the list by name):

| State | Pin | Moved by |
| --- | --- | --- |
| pending | orange, number | the person saved it |
| seen by the agent | blue ring | the agent acknowledged it (the only step from pending) |
| answered | purple, `?` | the agent replied with a question or explanation (from seen); the person's reply makes it pending again |
| resolved | green, `✓` | the agent resolved it with a summary of what changed (from seen); the project revision holding the change is recorded and must be a real one |
| dismissed | grey, `×` | the agent (from seen) or the person (from pending, seen or answered), with an optional reason |

The agent cannot skip "seen". A batch acknowledgement is all or nothing: if one id cannot move, nothing is written. A resolved or dismissed comment can be reopened by the person, and every step can be undone (the last step of a comment, repeatedly, back to its creation). Nothing is deleted; a project keeps up to 1000 comments.

**Anchors.** The preview paints a pin by the identity recorded when the comment was made: tag, visible text and the attributes that tell look-alikes apart (`id`, `href`, `data-vid`, `name`, `src`, `for`). A changed identity attribute means another element, whatever its text says: a link with the same text but another id or address is not the pin's link. On the revision the pin was made on, a unique `data-vsrc` with the same tag and attributes finds it. On any other revision source positions mean other lines, so only an element with the same tag, the same non-empty text (or an identity attribute) and attributes, found alone on the page or singled out by its place among its siblings, is the same element. If it is ambiguous or changed, the pin is **without anchor**: it keeps its place in a separate **Without anchor** list with its note, state and crop, and is never moved to a neighbour. It is found again if the element returns. The page reports anchors with the revision it serves and the preview session it was served from (`<meta name="vitruvius-preview-session">`, stamped by the preview proxy once per opening of the preview, so it survives live refreshes that swap the process behind it and changes when the preview is stopped and opened again); the server refuses a report that has no session, when the preview is not running, when it serves another revision, or when the session is not the open one, so a late report never revives a lost pin. A long attribute (an address of hundreds of characters) is recorded as its start plus a hash of the whole value, so it is compared in full. Comments made on an earlier revision say so (`stale`).

**Limits.** A project keeps up to 1000 comments and a page up to 300, the same number of pins the preview paints per page: the 301st comment on a page is refused with that reason, so no comment is left without its pin.

**Crop.** When the pin is made, the page draws the element with its computed styles into a PNG or JPEG (the clip the selection makes; at most 300 KB; none when the element is too large or too busy or the browser refuses), and the comment keeps it, as it looked on that revision, in `app-projects/<id>/comment-crops/<comment>.png` (`GET /api/app-projects/<id>/comments/<comment>/crop`). It appears in the editor and in the list.

Comments are stored in the project's own data folder (`app-projects/<id>/comments.json`, written atomically). They are not in the source files, the revisions or an export; the exported application carries no trace of them, crops included.

The agent works them through short tools: `app_project_comments` (`id`, `status`: `open` by default = pending + seen, or `pending`, `seen`, `answered`, `resolved`, `dismissed`, `lost`, `all`; read-only; lists counts too), `app_project_comment_ack` (`comment_ids`), `app_project_comment_resolve` (`comment_id`, `summary`, optional `revision`), `app_project_comment_reply` (`comment_id`, `text`), `app_project_comment_dismiss` (`comment_id`, `reason`) and `app_project_comment_undo` (`comment_id`). The comments waiting for the agent reach the copilot turn context in the same card as the selection (`app-preview-selection`, fields `selection` and `comments`), so selecting an element does not hide them. The list refreshes by polling, so the agent's steps change the pins within seconds.

The page side adds to the inspector's contract: host → page `inspect/mode {on, kind: "comment"}`, `inspect/pins {pins: [{id, n, status, selector, vsrc, own_vsrc, tag, text, revision, attrs, parent, index}]}`, `inspect/draft-clear`, `inspect/pin-focus {id}`; page → host `dock/comment-target {page, revision, element, crop, attrs}`, `dock/comment-anchors {page, revision, session, anchors: [{id, state: "ok"|"lost", vsrc, box}]}` and `dock/comment-focus {id}`. `dock/select` and `dock/inspector-ready` also carry `comment_mode`. The API under `/api/app-projects/<id>/comments` lists (`GET ?status=`), adds (`POST`, with the picked revision and the crop), stores anchors (`PUT /anchors`, with the revision and the preview session the page came from) and takes the person's steps (`POST /<comment>/respond|dismiss|reopen|undo`).

`app_project_update`, `app_project_edit_source` and `app_project_canvas_edit` accept an optional `actor` with `id`, `name` and `color`. The project remembers a caller's declared actor across canvas actions and edits. With no declaration, the caller ID gives the cursor its name and a stable color. In an open preview the agent cursor uses a colored arrow and a contrasting name label with the same color swatch. It travels to the target and pulses before a source revision is saved. Pass `target` with a `vsrc`, a stable CSS `selector` or a document-relative `box` (`x`, `y`, `w`, `h`) when available. The position edit already knows its `vsrc`. A file patch can infer the position of the first edit in changed HTML from the previous source. For changes without a visible anchor, the cursor points to the page. The live preview outlines the change and the edit returns its usual undo call.

The session allows a short window for the animation. A closed preview, an unavailable target or an expired message still allows a valid source edit to save. With reduced motion, the preview shows a static outline after the edit.

### Editing on the canvas

In **Select** mode, select one sourced element to show its width, height, margin and padding handles. Margin and padding have a handle on each side. Dragging previews the change on the page. The value snaps within three pixels of a length token and shows its name. Hold Alt while dragging to bypass snapping. Releasing restores the temporary style and plans the source edit. The preview refresh displays the saved result once the new revision is served.

Press Alt+Enter to focus the first handle and Tab to move through the handles. Use the arrows on the handle's axis to change the value one pixel at a time, or ten with Shift. Enter saves and Esc cancels. Double-click a literal run of text to edit it in place. Enter saves and Esc cancels. Form, table and other marker-generated text remains editable through its project fields, records or source styling.

Canvas style edits use a matching length token from the linked local stylesheets as a CSS variable. The planner reads plain top-level class rules, including grouped class selectors with an optional tag or ID. It confirms the number of matching instances on the open page and warns that the shared stylesheet may affect other pages. If none matches, it adds a stable class at the source position and a rule in the last local stylesheet. The rule also uses the element's literal ID when present, so it can take precedence over a rule for that ID alone. The editor creates and links a project stylesheet when needed. A dedicated rule uses CSS priority to override a normal inline value on the edited property, while keeping existing inline declarations. Edit an inline priority declaration in the source editor first. Other styles and the template sources stay in the retained revision. Use the source editor for conditional or more complex rules.

The browser and the agent use the same planner and write through the normal revision update. The companion tool `app_project_canvas_edit` accepts `id`, `vsrc`, `tag`, `expected_revision`, `path`, and a change. Call with `operation: "plan"` to see the destination, matching token, scale and affected count. A shared-class plan marks the count with `affects_scope: "page"` and `shared_stylesheet: true`. If `confirmation_required` is true, pass its `affects` as `expected_count` with `operation: "apply"`. A changed result includes an `app_project_undo` call. A stale revision requires a fresh selection. The native HTTP route is `POST /api/app-projects/{id}/canvas-edit`.

- `{"kind":"style","property":"padding-left","pixels":24}` sets a dimension or physical spacing property. Pass `root_font_px` if the preview root font size differs from 16 pixels and the project uses rem tokens.
- `{"kind":"text","index":1,"original":"Old label","value":"New label"}` replaces the second direct nonblank text node. Use its exact original text without surrounding HTML whitespace.

Canvas style editing loads the declared tinycss2 dependency when needed. If it is unavailable, the style edit explains how to restore it and the other preview and text operations remain available.

The inspector uses the existing preview bridge and reported source revision. Canvas requests are `dock/commit` for styles and `dock/text` for text. The host validates the sender and returns `inspect/canvas-edit-result` to the same frame. The overlay lives in the inspector's shadow tree and stays out of standalone exports.

### Canvas screen

The Canvas screen (`#/canvas/<project>` in the workbench, `/design/#/canvas/<project>` from the Vitruvius root) shows one project's preview across the page, with a mode toolbar and a side panel. It uses the same preview, live refresh and App Dock frame bridge as Applications (`client/src/canvas/projectPreview.jsx`) and the same selection panel (`PreviewSelection`), so agent tools, the selection and its restoration after a frame swap behave the same on both screens. The toolbar always offers Navigate. Select and Comment appear only after the inspector in the visible frame announces them in `dock/inspector-ready`; a stopped, reopened or swapped frame starts again with Navigate alone. In Select mode a chosen element shows its resize and spacing handles, which save through the same in-place edit path as Applications. Comments are written, listed and stepped in the same panel. Each mode change is sent to the inspector as `inspect/mode`, and Esc returns to Navigate. While the screen is open the shared copilot opens on the left (`data-hoard-copilot-position="left"`), leaving the right to the preview.

While the Canvas screen is open, Vitruvius reports it to the Dock host through `HoardApp.setContext`: `view: "canvas"`, `focus` with the project, and a `summary` of at most 400 characters naming the revision, the mode, the selected elements with their source positions and any open comments. `selected N` counts only the elements that are active on the revision on screen, as the panel shows them; elements that are gone from that revision are listed apart as expired, without a source position. Comments keep their share of the summary; the active selection fills the rest and says how many elements it left out. When Vitruvius is docked in Faustus, `app_open` with `route: "/design/#/canvas/<project>"` opens this screen beside the chat, and the summary reaches the turn context through the Dock bridge. Agents use the project tools for the complete selection.

## Booking pages

For a new design, take the three directions from `design_brief` through [Alternatives](ALTERNATIVES.md#art-direction-before-building), then call `app_project_create` with `art_direction_study_id` and `template: "booking"`. Supply `items` with a stable lowercase `id`, `title`, `category` and optional `description` for each entry. A text value can be shared or supplied as an `{es, en}` pair. Set `lang: "es"` for Spanish on first load, with `description_es` for the introductory text and `description` for its English version. The site preserves the active category when switching languages.

Export the booking revision with `app_project_export`. The publishable site is under `public/`, with a root `website.json` form contract. Register the ZIP and publish it with `hub_website_publish_piece`. On the published site, the form returns the reference written to the publication inbox. The owned preview uses the same page and assets for design checks. Es posible filtrar, cambiar de idioma y rellenar la solicitud en la vista previa. Envía la solicitud desde la web publicada para recibir la referencia.

## Standalone output

`app_project_export` returns a ZIP path/hash and its source revision/hash. The UI supplies a native download link. Export uses the same captured file contents as preview, with exact UTF-8 source bytes. Optional data export makes an online SQLite backup and includes it only when a database actually exists. A code-only export starts with the initial records declared by its collections. A single-record-type export starts with an empty database.

Extract the ZIP and run `python server.py --port 3000` from that directory. Python 3.10+ and its standard library are sufficient. The supplied Dockerfile describes a Python container; cloud deployment/authentication/billing/provider adapters are not configured or certified by this feature. The worker is an editable local application server. No parity with RSC, streaming SSR, experimental compilers or every framework renderer is implied.
