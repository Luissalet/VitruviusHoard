# Native application projects

The Applications page and `/api/app-projects` expose a complete source workspace. `app_templates` lists work board, reference library, inventory and booking. `app_project_create` saves pages, global layout, styles, client, typed declarations and a standalone Python server. No framework repository, external CLI, generated model or workbench installation is required to run the exported app.

## Source and data

`app_project_get` returns every source file and its selected revision. `app_project_update` accepts a file patch and `expected_revision`; unchanged files are preserved. Disjoint edits merge across newer revisions. A conflicting edit to the same file reports the affected path and preserves both the current saved revision and the caller's draft. Earlier revisions remain readable/exportable. The UI retains drafts while switching files, revisions and projects, and keeps edits made after an asynchronous save started.

Project creation and source edits return an `app_project_undo` call. Use it while the recorded update is still current. Undoing a source edit restores the earlier source and retains both revisions. Undoing creation archives a project with no retained edits and stops its preview.

`project.json` declares `name`, `description` and `fields`. Fields have an identifier `name`, human `label`, `type` (`text`, `number`, `boolean`, `choice`), optional `required`, and `choices` for a choice field. Record identity uses the reserved `id` property. The original starter supplies matching `contracts.d.ts` and an annotated client; custom schema edits should keep their custom declarations/client consistent. Runtime input validation uses the running revision's schema. Existing stored values are retained rather than silently migrated or removed when a schema changes.

The server discovers `pages/**/*.html`: `index.html` defines the containing path and `[parameter].html` defines a dynamic segment. `layout.html` wraps each page. Templates support `{{name}}`, `{{description}}`, `{{table}}`, `{{form}}`, `{{count}}`, `{{query}}`, `{{record_title}}` and escaped `{{param_name}}` values. This is HTML templating with server-rendered content; it does not execute template expressions. Source files can be edited to change the runtime itself.

Data lives separately in `app-projects/<id>/data/app.db`. It survives preview restarts and source revisions. The record API uses SQLite write transactions; independent field updates merge in one transaction. The supplied client sends changed fields for edits and retains newer form edits if an older request completes. This is source revision history, not record undo or an automatic data migration system.

## Preview, calls and inspection

`app_project_preview` starts an owned hidden Python process on a free loopback port, or stops that project's process. It reuses a healthy process for the same revision. When changing revisions, it starts the captured source and switches the proxy after the new runtime is ready. The preview keeps the same loopback URL until stopped and works in the workbench iframe or an independent browser tab. Previews stop when Vitruvius shuts down, while records and source remain saved.

The Applications page connects the App Dock bridge to the visible preview. Agents can read the open page with `app_project_canvas_view` and point at or operate its controls with `app_project_canvas_act`. See [the canvas tool and frame contract](APP_CANVAS.md).

`app_project_call` provides native access to the application's `list`, `get`, `create`, `update` and `delete` record operations. The standalone application exposes:

- `GET /api/health`, `/api/schema`, `/api/routes`.
- `GET/POST /api/records`, `GET/PATCH/DELETE /api/records/<id>`.
- `POST /actions/create`, `/actions/update`, `/actions/delete`.

Inputs are checked against the declared field types and choices; text stays literal in server-rendered pages. These are application JSON calls with a generated typed client, not component compiler transforms. Additional runtime behavior belongs to the editable project's code.

`app_project_render` captures the selected owned preview through a local browser worker into the existing render history, with project identity, source revision and source SHA in the metrics. Existing `design_critique` can inspect that render. Source is pinned for a preview process; data can change between screenshots if users continue editing it. The ordinary HTML patterns, reference gallery, tokens, diagrams, movement and criterion library remain available.

`design_critique` and `page_assay` can also open a loopback preview by URL. Assay uses the page in place so its relative assets remain available. Loopback assay reads the preview. Use the publication's synthetic form check to verify an inbox write. Set `VITRUVIUS_BROWSER_CHANNEL=chrome` to prefer the installed Chrome channel, for example on a machine with more than one supported channel.

## Selecting elements on the preview

With the preview open, **Select** (button, or `Alt+Shift+S`) turns on a selection mode over the framed page. Hovering outlines the element under the pointer with its tag and classes, and tints its margin, border and padding from `getComputedStyle`; a click selects it, `Shift`+click adds or removes one, `Tab`/`Enter` choose by keyboard, `Esc` leaves the mode. Outside the mode the page is used normally, and the overlay has no transitions under `prefers-reduced-motion`. The chips below the preview list what is selected (tag, class, text, source position, and "affects N elements" when several served elements share one source position); each chip has a remove button, and **Clear all** empties the list.

Each selected element is a card: a stable selector (`data-vid`, then `id`, then a unique `data-vsrc`, then the shortest unique `tag:nth-of-type()` path), its visible text (up to 200 characters), its HTML (up to 1200 characters), its box in page coordinates, tag and classes, a few computed styles, `same_vsrc_count`, its source position when the page carries one (`data-vsrc="file:line:column"`, or the position of the `{{marker}}` that generated it, with `data-vgen`), `own_vsrc` (whether that position is the element's own), and the revision the page was served from. A page without annotations still selects; the card then says it has no source position. A capture clip of the element is not part of the card; `app_project_render` captures the preview.

The revision comes from the served page (`<meta name="vitruvius-preview-revision">`), not from what the workbench believes, and travels in every message and card. The selection reaches the agent three ways: the copilot turn context carries a card per element (selector, source, text, HTML excerpt, styles, revision), the page's App Dock context (when the bridge is present) names the selection in its `summary` and `focus`, and the read-only tool `app_project_selection` (`id`) returns the full list of the open preview, so "change this" needs no description. An empty list says nothing is selected.

The list is kept in memory per project and is replaced on every change. It is bound to the preview process: once the preview stops (by the person, by an agent's `app_project_preview` stop, or by a crash) or restarts, reading it returns an empty list; so does a read while the preview serves another revision than the selection was taken on (the page reports again once it settles), and the server refuses a report that names another revision (`409`). It belongs to one page: following a link to another page clears it, while a reload of the same page keeps it. When a page replaces its elements, a selected element is followed only if it can still be told apart: a unique `data-vsrc` is an identity, otherwise the tag and visible text must still match; an ambiguous or missing element is dropped, never guessed (so reordering a list never moves the selection to a neighbour).

The script is `vitruvius_hoard/preview_scripts/preview-inspector.js` (also served at `/api/app-projects/preview-inspector.js`; `preview_inspector.inspector_script()` returns its text). It is loaded only into the owned preview, next to the App Dock bridge, by whatever injects scripts into the preview pages; it is never part of an export, and `server.py` does not reference it. It has no dependencies and no vendored code. Its overlay lives in a shadow root under its own element whose inline `!important` style (and re-attachment, if the page removes it) keeps project CSS from hiding it; the crosshair cursor is an adopted stylesheet, so the page's own inline styles are never touched.

Messages use the bridge's envelope, `{hoardDock: 1, type, ...}`, and only travel between the preview frame and the Vitruvius page that frames it. The host checks the source window and origin of every message. The inspector listens only to its parent window and fixes the parent's origin once, from the browser's ancestor origin or else from the first `inspect/hello`; messages from any other origin are ignored afterwards.

- page → host: `dock/inspector-ready {mode, page, revision, selection}`, and `dock/select {mode, page, revision, selection}` after every change. `selection` is the whole list of cards.
- host → page: `inspect/hello`, `inspect/mode {on}`, `inspect/clear`, `inspect/remove {index}`, `inspect/restore {items}` (identities: selector, tag, text, vsrc, own_vsrc).

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

## Booking pages

Use `design_brief` to choose the direction, then call `app_project_create` with `template: "booking"`. Supply `items` with a stable lowercase `id`, `title`, `category` and optional `description` for each entry. A text value can be shared or supplied as an `{es, en}` pair. Set `lang: "es"` for Spanish on first load, with `description_es` for the introductory text and `description` for its English version. The site preserves the active category when switching languages.

Export the booking revision with `app_project_export`. The publishable site is under `public/`, with a root `website.json` form contract. Register the ZIP and publish it with `hub_website_publish_piece`. On the published site, the form returns the reference written to the publication inbox. The owned preview uses the same page and assets for design checks. Es posible filtrar, cambiar de idioma y rellenar la solicitud en la vista previa. Envía la solicitud desde la web publicada para recibir la referencia.

## Standalone output

`app_project_export` returns a ZIP path/hash and its source revision/hash. The UI supplies a native download link. Export uses the same captured file contents as preview, with exact UTF-8 source bytes. Optional data export makes an online SQLite backup and includes it only when a database actually exists. Code-only export starts with empty data on first launch.

Extract the ZIP and run `python server.py --port 3000` from that directory. Python 3.10+ and its standard library are sufficient. The supplied Dockerfile describes a Python container; cloud deployment/authentication/billing/provider adapters are not configured or certified by this feature. The worker is an editable local application server. No parity with RSC, streaming SSR, experimental compilers or every framework renderer is implied.
