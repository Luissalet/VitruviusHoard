# Software workspace API/MCP

GET /api/agent/tools exposes a cold static catalogue:65 design,10 API-documentation and38 existing reverse-engineering tools, plus10 software-workspace controls (123 total). POST /api/agent/call accepts {name,arguments} with the existing root or migrated native bearer; POST /api/ui/call uses identical handlers. Discovery starts no host, engine, database, factory, recovery or worker. Native operations require an explicitly enabled module. Routes and complete native editors remain under /design/, /babel/ and /theseus/.

Native schemas/annotations are retained in vitruvius_hoard/software/catalog.json. Theseus HTTP/MCP keeps its {ok,result} envelope and artifact-image MCP ImageContent. Babel keeps its native result/error shape and explicit environment IDs. Native API/format behavior remains authoritative; do not infer that a catalogue operation means its optional engine is installed.

Shared controls: software_modules, software_module_set, software_projects, software_project_read, software_references, software_environment_link, software_check, software_inspect, software_analysis_start and software_result_retain. Inspect file='.' to associate the complete retained source tree; other file values address a native project file. Source revision, native tree digest, file digest and retained-result digest are distinct identities. A selected environment must be linked to that exact revision before software_check. Stored analysis documents are checked against the native analysis_sha256 and retained with their job, so they remain readable while modules are OFF. No automatic reader-to-builder handoff is introduced; native Theseus builder_only handoffs remain separate from original reader evidence.

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
| `theseus_evidence_export` | theseus |
| `theseus_evidence_import` | theseus |
