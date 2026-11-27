# Software workspace API/MCP

GET /api/agent/tools exposes a cold catalogue. The native manifest has 216 entries across Design (145), API documentation (11) and reverse engineering (60). The host adds its workspace controls and separately registered tools. POST /api/agent/call accepts {name,arguments} with the existing root or migrated native bearer; POST /api/ui/call uses identical handlers. Discovery starts no host, engine, database, factory, recovery or worker. Native operations require an explicitly enabled module. Routes and complete native editors remain under /design/, /babel/ and /theseus/.

Native schemas/annotations are retained in vitruvius_hoard/software/catalog.json. Theseus HTTP/MCP keeps its {ok,result} envelope and artifact-image MCP ImageContent. Babel keeps its native result/error shape and explicit environment IDs. Native API/format behavior remains authoritative; do not infer that a catalogue operation means its optional engine is installed.

`app_project_create` accepts a partial UTF-8 `files` map, such as `pages/index.html` and `assets/style.css`. If the map lacks `project.json`, `layout.html` or `pages/index.html`, missing files are filled in from the selected starter. With `template: "custom"`, the work-board starter fills those gaps. Explicit files take precedence, and omitting `server.py` uses the built-in standalone runtime.

`page_check` accepts the `render_id` returned by `app_project_render`. It checks the source revision recorded in the capture through an internal preview, with a snapshot of the current project data and the usual browser checks and time budget. The editor's live preview keeps serving its current revision. If the captured revision is unavailable, the tool reports the render and revision in a `not_found` error. A render made from HTML still uses its saved HTML.

En `page_check`, pasa el `render_id` de `app_project_render` para comprobar la revisión de la captura. La herramienta usa una vista previa interna con una copia temporal de los datos actuales y conserva el plazo y los resultados parciales habituales. Si la revisión ya no está disponible, la respuesta `not_found` identifica la captura y la revisión.

`design_critique` accepts a captured `render_id` as before. The default model budget is 110 seconds so the tool can return a report before the Hub's 120-second deadline. Set `timeout_s` below your transport's deadline when you need a different budget. Vision and `clean_review` share that budget. The usual deterministic findings, score and gate still return when a model pass is missing. `score_source` is `heuristic` for a deterministic score and `vision_blend` when the model score contributed. `partial`, `vision.status`, `missing` and `next_action` describe which checks completed.

Para una crítica determinista, llama a `design_critique` con `{"render_id":"…","use_vision":false,"clean_review":false}`. Con solo `render_id`, se aplica el plazo predeterminado. Si `vision.status` es `timed_out`, usa los hallazgos y la puntuación deterministas. `missing` indica qué revisión del modelo quedó pendiente y `next_action` ofrece una llamada que funciona sin modelo.

In an open canvas, `app_project_canvas_act` with `action: "highlight"` can find a visible figure or image by name. For example, set `args.label` to the text of an SVG's `<title>` or its `aria-labelledby` reference.

If an edit advances the live preview before an anchor report from the same preview session arrives, `PUT /api/app-projects/{id}/comments/anchors` returns HTTP 200 with `changed: 0` and `stale: true`. Stored anchors stay as they are. A report for an earlier preview session, a stopped preview or a newer source revision that the preview has yet to serve still returns HTTP 409.

When linting supplied HTML with `engines: ["static"]`, `design_lint` reads the document's `<html lang>` from the source without opening a browser.

`tokens_generate` accepts a preset and a partial `fonts` map together. The supplied `heading`, `body` or `mono` overrides that preset role. The other font roles, palette, radius, spacing and motion still come from the preset.

Shared controls: software_modules, software_module_set, software_projects, software_project_read, software_references, software_environment_link, software_check, software_inspect, software_analysis_start and software_result_retain. Inspect file='.' to associate the complete retained source tree; other file values address a native project file. Source revision, native tree digest, file digest and retained-result digest are distinct identities. A selected environment must be linked to that exact revision before software_check. Stored analysis documents are checked against the native analysis_sha256 and retained with their job, so they remain readable while modules are OFF. No automatic reader-to-builder handoff is introduced; native Theseus builder_only handoffs remain separate from original reader evidence.

`software_module_set` atomically saves the requested `enabled` and `automatic` values in `software-modules.json` under `VITRUVIUS_PROFILE_DIR` before applying them. It returns the module status and `previous` with both previous settings. To undo, pass the same `module` and the two `previous` values back to `software_module_set`. An omitted `automatic` defaults to false. The host restores saved settings on start, with unsaved modules off and automatic work disabled. An empty profile prepares the local Design library on first start. An interrupted first preparation resumes on the next start. An explicit Design OFF preference keeps the module off until it is enabled or preparation is requested. An existing profile with missing, malformed or unsupported settings keeps unsaved modules off. Valid entries can be restored alongside invalid ones. A native startup failure leaves `state: "error"` with an `error` reason in `software_modules`. The saved preference is available for the next start.

Use `design_library_prepare` from the agent or **Prepare library** in the workbench. It enables Design when needed and adds the package's preset styles, swatches and font combinations, searchable guide and recipe text, gallery references with local image files and editable motion examples. It reports available counts, additions and individual import errors. Neither preparing nor enabling Design this way starts automatic work. The other modules retain their saved state. Existing user items are reused or kept. Network source registrations can still be imported through the existing tools when needed.

On a preparation that writes, the returned `undo` invokes `design_library_undo` with the preparation token. It removes that preparation's bundled data and restores the previous Design setting if the preparation changed it and the setting still matches. A seeded motion example with edits is preserved. The undo token identifies the last preparation that added data or enabled Design. An unchanged recheck keeps that token valid.

References append immutable revisions; expected_revision prevents stale edits. Changing a source revision does not update historical findings or hashes. A sent bridge mutation without a response returns outcome_unknown and read_current_state_before_retry, without replay. OFF stops admission, cancels readers once, waits outstanding admitted operations and async cleanup, then closes owned resources. Pending stopping is not advertised as OFF. Native binary/media bytes, Range responses and source/result JSON pass through unchanged; only known native launcher/PWA HTML contracts are adapted. UI resource URL prefixes are resolved by the native client.

| Native tool | Module |
|---|---|
| `design_search` | design |
| `design_brief` | design |
| `design_rules` | design |
| `styles_search` | design |
| `palettes_search` | design |
| `fonts_search` | design |
| `render_preview` | design |
| `design_lint` | design |
| `design_critique` | design |
| `page_assay` | design |
| `render_compare` | design |
| `tokens_generate` | design |
| `tokens_get` | design |
| `tokens_list` | design |
| `tokens_preview` | design |
| `tokens_delete` | design |
| `app_templates` | design |
| `app_project_create` | design |
| `app_project_list` | design |
| `app_project_get` | design |
| `app_project_update` | design |
| `app_project_patch` | design |
| `app_project_preview` | design |
| `app_project_export` | design |
| `app_project_render` | design |
| `app_project_call` | design |
| `reference_collections` | design |
| `reference_import_collection` | design |
| `design_patterns` | design |
| `design_pattern` | design |
| `reference_add` | design |
| `reference_search` | design |
| `reference_get` | design |
| `reference_delete` | design |
| `sources_list` | design |
| `source_add` | design |
| `source_ingest` | design |
| `source_status` | design |
| `vitruvius_status` | design |
| `motion_templates` | design |
| `motion_save` | design |
| `motion_list` | design |
| `motion_get` | design |
| `motion_render` | design |
| `diagram_types` | design |
| `diagram_render` | design |
| `diagram_get` | design |
| `diagram_list` | design |
| `diagram_delete` | design |
| `diagram_brand_onboard` | design |
| `diagram_brands` | design |
| `diagram_brand_delete` | design |
| `page_check` | design |
| `docs_libraries` | babel |
| `docs_search` | babel |
| `api_lookup` | babel |
| `api_check_code` | babel |
| `api_upgrade_rehearsal` | babel |
| `docs_read` | babel |
| `docs_add_environment` | babel |
| `docs_catalog` | babel |
| `docs_install_docset` | babel |
| `docs_index_folder` | babel |
| `docs_check_locales` | babel |
| `theseus_runtime_catalog` | theseus |
| `theseus_runtime_start` | theseus |
| `theseus_projects` | theseus |
| `theseus_project_create` | theseus |
| `theseus_project_read` | theseus |
| `theseus_project_update` | theseus |
| `theseus_artifact_add` | theseus |
| `theseus_artifact_read` | theseus |
| `theseus_artifact_excerpt` | theseus |
| `theseus_artifact_image` | theseus |
| `theseus_finding_add` | theseus |
| `theseus_specification_write` | theseus |
| `theseus_scenario_save` | theseus |
| `theseus_comparison_start` | theseus |
| `theseus_job_read` | theseus |
| `theseus_job_cancel` | theseus |
| `theseus_project_export` | theseus |
| `theseus_local_engines` | theseus |
| `theseus_binary_analysis` | theseus |
| `theseus_function_read` | theseus |
| `theseus_analysis_catalog` | theseus |
| `theseus_analysis_start` | theseus |
| `theseus_analysis_records` | theseus |
| `theseus_analysis_record` | theseus |
| `theseus_binary_catalog` | theseus |
| `theseus_binary_sessions` | theseus |
| `theseus_binary_open` | theseus |
| `theseus_binary_call` | theseus |
| `theseus_binary_close` | theseus |
| `theseus_binary_compare` | theseus |
| `theseus_workflow_read` | theseus |
| `theseus_claim_save` | theseus |
| `theseus_handoff_create` | theseus |
| `theseus_handoff_read` | theseus |
| `theseus_oracle_selftest` | theseus |
| `theseus_reconstruction_verify` | theseus |
| `theseus_equivalence_suite_save` | theseus |
| `theseus_equivalence_suite_read` | theseus |
| `theseus_equivalence_run` | theseus |
| `theseus_rules_save` | theseus |
| `theseus_rules_read` | theseus |
| `theseus_rules_check` | theseus |
| `theseus_rules_export` | theseus |
| `theseus_property_run` | theseus |
| `theseus_synthesize` | theseus |
| `theseus_repro_create` | theseus |
| `theseus_repro_verify` | theseus |
| `theseus_stateful_recipe_save` | theseus |
| `theseus_stateful_recipe_read` | theseus |
| `theseus_stateful_run` | theseus |
| `theseus_stateful_replay` | theseus |
| `theseus_stateful_export` | theseus |
| `theseus_perf_profile` | theseus |
| `theseus_perf_compare` | theseus |
| `theseus_evidence_export` | theseus |
| `theseus_evidence_import` | theseus |
