# Android package and resource projections

This delivery addresses the package-summary and selected-resource-table gaps
found in independent research 1159, contracts 86 and 92. Existing complete
observations and decoded artifacts remain available. No ledger status is promoted.

Package analysis accepts optional summary delivery linked to the full retained
JSON by parent job, source digest and view digest. A new retained-only
`android.package_view` exposes summary or UTF-16 manifest windows from finished
or imported package analyses without Java or original APK access. Page boundaries
preserve surrogate pairs and report offsets, total units and exhaustion.

Resource analysis accepts a primary locale, additional locales or explicit string
omission. It preserves caller locale labels, shares alias reads, inventories
canonical language directories, composes raw YAML scalar metadata without
constructing objects, and retains lexical direct XML strings with occurrence
counts. Missing, malformed, unsupported-markup and decoder-error outcomes keep
their distinct uncertainty. Complete decoded files remain normal derived
artifacts. No implicit output cap was added. PyYAML is declared in project and
pinned environment requirements; the source QA environment used 6.0.3.

## Source verification

- Initial schema RED: three failures, `codex-android1162-red.xml`; after admission,
  three PASS in `codex-android1162-a.xml`.
- Projection/retained-worker checks: 17 PASS, `codex-android1162-b.xml`.
- Final area: 34 PASS, zero skips, 90.290 seconds, `codex-android1162-c.xml`:
  projection, native APK/DEX, native analysis, retained workflow and structured
  recovery. Every pytest used the mandatory no-alias wrapper and fresh basetemp.
- Actual stdio MCP on private source owner 64334: six observations, package
  summary, retained summary/window, selected resources, omitted strings and an
  imported package window. `codex-android1162-mcp22b.json` fixes source hashes.
  The first author checker incorrectly expected total class count 3 rather than
  distinguishing top-level 3 from reader-reported total 5. Its saved failure
  remains; the continuation reused that completed package and project.
- Normal UI submitted French/Spanish selection and a retained imported manifest
  window of 80 UTF-16 units. Visible records equal saved JSON and the downloaded
  window document is byte exact. `codex-android1162-ui22.json`,
  `codex-android1162-ui-verified22.json`, and both UI screenshots retain proof;
  the retained screenshot shows context/hash, with the selected text also fixed
  in the accessibility receipt. Own tab 6 closed.
- Private owner tree closed by exact process identity, 64334 free, profile and
  all results preserved: `qa-codex-android1162a-closed.json`. The original
  independently compiled APK retains digest d1699443c613f51847ba976656a0058aac50fb0bf2e1c7a173e3645ba3197da6;
  it was never installed or executed. No Sparks, model substitute, GPU, SABER,
  shared ADB or shared application was used.

Independent review, composed regression, a fresh wheel and installed MCP/UI
acceptance remain pending. Source acceptance is finite and does not establish
arbitrary APK behavior. See [semantics and usage](../docs/ANDROID-VIEWS.md).
