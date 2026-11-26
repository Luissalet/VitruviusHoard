# Native application projects

The Applications page and `/api/app-projects` expose a complete source workspace. `app_templates` lists work board, reference library, inventory and booking. `app_project_create` saves pages, global layout, styles, client, typed declarations and a standalone Python server. No framework repository, external CLI, generated model or workbench installation is required to run the exported app.

## Source and data

`app_project_get` returns every source file and its selected revision. `app_project_update` accepts a file patch and `expected_revision`; unchanged files are preserved. Disjoint edits merge across newer revisions. A conflicting edit to the same file reports the affected path and preserves both the current saved revision and the caller's draft. Earlier revisions remain readable/exportable. The UI retains drafts while switching files, revisions and projects, and keeps edits made after an asynchronous save started.

Project creation and source edits return an `app_project_undo` call. Use it while the recorded update is still current. Undoing a source edit restores the earlier source and retains both revisions. Undoing creation archives a project with no retained edits and stops its preview.

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

## Preview, calls and inspection

`app_project_preview` starts an owned hidden Python process on a free loopback port, or stops that project's process. It reuses a healthy process for the same revision. When changing revisions, it starts the captured source and switches the proxy after the new runtime is ready. The preview keeps the same loopback URL until stopped and works in the workbench iframe or an independent browser tab. Previews stop when Vitruvius shuts down, while records and source remain saved.

The Applications page connects the App Dock bridge to the visible preview. Agents can read the open page with `app_project_canvas_view` and point at or operate its controls with `app_project_canvas_act`. See [the canvas tool and frame contract](APP_CANVAS.md).

For single-record-type projects, `app_project_call` provides `list`, `get`, `create`, `update` and `delete`. Their standalone application exposes the following routes.

- `GET /api/health`, `/api/schema`, `/api/routes`.
- `GET/POST /api/records`, `GET/PATCH/DELETE /api/records/<id>`.
- `POST /actions/create`, `/actions/update`, `/actions/delete`.

Inputs are checked against the declared field types and choices; text stays literal in server-rendered pages. These are application JSON calls with a generated typed client, not component compiler transforms. Additional runtime behavior belongs to the editable project's code.

`app_project_render` captures the selected owned preview through a local browser worker into the existing render history, with project identity, source revision and source SHA in the metrics. Existing `design_critique` can inspect that render. Source is pinned for a preview process; data can change between screenshots if users continue editing it. The ordinary HTML patterns, reference gallery, tokens, diagrams, movement and criterion library remain available.

`design_critique` and `page_assay` can also open a loopback preview by URL. Assay uses the page in place so its relative assets remain available. Loopback assay reads the preview. Use the publication's synthetic form check to verify an inbox write. Set `VITRUVIUS_BROWSER_CHANNEL=chrome` to prefer the installed Chrome channel, for example on a machine with more than one supported channel.

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

`app_project_export` returns a ZIP path/hash and its source revision/hash. The UI supplies a native download link. Export uses the same captured file contents as preview, with exact UTF-8 source bytes. Optional data export makes an online SQLite backup and includes it only when a database actually exists. A code-only export starts with the initial records declared by its collections. A single-record-type export starts with an empty database.

Extract the ZIP and run `python server.py --port 3000` from that directory. Python 3.10+ and its standard library are sufficient. The supplied Dockerfile describes a Python container; cloud deployment/authentication/billing/provider adapters are not configured or certified by this feature. The worker is an editable local application server. No parity with RSC, streaming SSR, experimental compilers or every framework renderer is implied.
