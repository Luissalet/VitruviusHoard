# Native application projects

The Applications page and `/api/app-projects` expose a complete source workspace. `app_templates` lists the three original starting points: work board, reference library and inventory. `app_project_create` saves pages, global layout, styles, client, typed declarations and a standalone Python server. No framework repository, external CLI, generated model or workbench installation is required to run the exported app.

## Source and data

`app_project_get` returns every source file and its selected revision. `app_project_update` accepts a file patch and `expected_revision`; unchanged files are preserved. Disjoint edits merge across newer revisions. A conflicting edit to the same file reports the affected path and preserves both the current saved revision and the caller's draft. Earlier revisions remain readable/exportable. The UI retains drafts while switching files, revisions and projects, and keeps edits made after an asynchronous save started.

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

## Standalone output

`app_project_export` returns a ZIP path/hash and its source revision/hash. The UI supplies a native download link. Export uses the same captured file contents as preview, with exact UTF-8 source bytes. Optional data export makes an online SQLite backup and includes it only when a database actually exists. Code-only export starts with empty data on first launch.

Extract the ZIP and run `python server.py --port 3000` from that directory. Python 3.10+ and its standard library are sufficient. The supplied Dockerfile describes a Python container; cloud deployment/authentication/billing/provider adapters are not configured or certified by this feature. The worker is an editable local application server. No parity with RSC, streaming SSR, experimental compilers or every framework renderer is implied.
