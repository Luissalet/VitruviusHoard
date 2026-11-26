# Native application projects

The Applications page and `/api/app-projects` expose a complete source workspace. `app_templates` lists work board, reference library, inventory and booking. `app_project_create` saves pages, global layout, styles, client, typed declarations and a standalone Python server. No framework repository, external CLI, generated model or workbench installation is required to run the exported app.

## Source and data

`app_project_get` returns every source file and its selected revision. `app_project_update` accepts a file patch and `expected_revision`; unchanged files are preserved. Disjoint edits merge across newer revisions. A conflicting edit to the same file reports the affected path and preserves both the current saved revision and the caller's draft. Earlier revisions remain readable/exportable. The UI retains drafts while switching files, revisions and projects, and keeps edits made after an asynchronous save started.

Project creation and source edits return an `app_project_undo` call. Use it while the recorded update is still current. Undoing a source edit restores the earlier source and retains both revisions. Undoing creation archives a project with no retained edits and stops its preview.

`project.json` declares `name`, `description` and `fields`. Fields have an identifier `name`, human `label`, `type` (`text`, `number`, `boolean`, `choice`), optional `required`, and `choices` for a choice field. Record identity uses the reserved `id` property. The original starter supplies matching `contracts.d.ts` and an annotated client; custom schema edits should keep their custom declarations/client consistent. Runtime input validation uses the running revision's schema. Existing stored values are retained rather than silently migrated or removed when a schema changes.

The server discovers `pages/**/*.html`: `index.html` defines the containing path and `[parameter].html` defines a dynamic segment. `layout.html` wraps each page. Templates support `{{name}}`, `{{description}}`, `{{table}}`, `{{form}}`, `{{count}}`, `{{query}}`, `{{record_title}}` and escaped `{{param_name}}` values. This is HTML templating with server-rendered content; it does not execute template expressions. Source files can be edited to change the runtime itself.

Data lives separately in `app-projects/<id>/data/app.db`. It survives preview restarts and source revisions. The record API uses SQLite write transactions; independent field updates merge in one transaction. The supplied client sends changed fields for edits and retains newer form edits if an older request completes. This is source revision history, not record undo or an automatic data migration system.

## Preview, calls and inspection

`app_project_preview` starts an owned hidden Python process on a free loopback port, or stops that project's process. It reuses a healthy process for the same revision. Switching revision stops only that owned process and starts a frozen copy of the captured source. The app URL works in the workbench iframe or an independent browser tab. Previews stop when Vitruvius shuts down; records and source remain saved.

`app_project_call` provides native access to the application's `list`, `get`, `create`, `update` and `delete` record operations. The standalone application exposes:

- `GET /api/health`, `/api/schema`, `/api/routes`.
- `GET/POST /api/records`, `GET/PATCH/DELETE /api/records/<id>`.
- `POST /actions/create`, `/actions/update`, `/actions/delete`.

Inputs are checked against the declared field types and choices; text stays literal in server-rendered pages. These are application JSON calls with a generated typed client, not component compiler transforms. Additional runtime behavior belongs to the editable project's code.

`app_project_render` captures the selected owned preview through a local browser worker into the existing render history, with project identity, source revision and source SHA in the metrics. Existing `design_critique` can inspect that render. Source is pinned for a preview process; data can change between screenshots if users continue editing it. The ordinary HTML patterns, reference gallery, tokens, diagrams, movement and criterion library remain available.

`design_critique` and `page_assay` can also open a loopback preview by URL. Assay uses the page in place so its relative assets remain available. Loopback assay reads the preview. Use the publication's synthetic form check to verify an inbox write. Set `VITRUVIUS_BROWSER_CHANNEL=chrome` to prefer the installed Chrome channel, for example on a machine with more than one supported channel.

## Live preview

An open Applications preview follows project source changes saved in the editor or by `app_project_update`. Undo through `app_project_undo` follows the same path. Unsaved drafts and an explicitly selected historical revision remain available in the source editor.

`GET /api/app-projects/{id}/events` streams `revision` events with the current and previous revision IDs, changed `files`, and inclusive before/after line spans for page HTML. A span with no lines ends before its start. `global_styles` lists changed stylesheets linked by the layout. The event ID is the new revision. A reconnect can use `Last-Event-ID` or the initial `revision` query parameter to recover changes since a saved snapshot.

When the preview has source annotations, a page-only change can replace the affected DOM nodes while preserving the rest of the page. A changed page stylesheet can load in place. Layout, layout stylesheets and client code load in a replacement frame prepared while the previous page remains visible. The new frame opens on the same route and restores its scroll position when the preview bridge can report them. Custom or older runtimes without source positions use the replacement frame. The preview highlights the changed elements with a short outline and uses a static outline when reduced motion is enabled.

## Booking pages

Use `design_brief` to choose the direction, then call `app_project_create` with `template: "booking"`. Supply `items` with a stable lowercase `id`, `title`, `category` and optional `description` for each entry. A text value can be shared or supplied as an `{es, en}` pair. Set `lang: "es"` for Spanish on first load, with `description_es` for the introductory text and `description` for its English version. The site preserves the active category when switching languages.

Export the booking revision with `app_project_export`. The publishable site is under `public/`, with a root `website.json` form contract. Register the ZIP and publish it with `hub_website_publish_piece`. On the published site, the form returns the reference written to the publication inbox. The owned preview uses the same page and assets for design checks. Es posible filtrar, cambiar de idioma y rellenar la solicitud en la vista previa. Envía la solicitud desde la web publicada para recibir la referencia.

## Standalone output

`app_project_export` returns a ZIP path/hash and its source revision/hash. The UI supplies a native download link. Export uses the same captured file contents as preview, with exact UTF-8 source bytes. Optional data export makes an online SQLite backup and includes it only when a database actually exists. Code-only export starts with empty data on first launch.

Extract the ZIP and run `python server.py --port 3000` from that directory. Python 3.10+ and its standard library are sufficient. The supplied Dockerfile describes a Python container; cloud deployment/authentication/billing/provider adapters are not configured or certified by this feature. The worker is an editable local application server. No parity with RSC, streaming SSR, experimental compilers or every framework renderer is implied.
