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

## Revision 2 corrections

Independent CAS1 found two defects: summary action links still selected the
exporting project after import, and physical decoded-file reads normalized CRLF
and CR before lexical projection. Both original counterexamples remain in
`review-android1162-r1/REVIEW-1162-R1.md` and its receipts. The source correction
remaps only the typed summary envelope links, recomputes and validates its view
digest, and preserves literal IDs and complete historical JSON bytes. Decoded
manifest/string files are read as UTF-8 bytes without universal-newline conversion.

New repository regressions exercise physical CRLF/CR and three consecutive
transfers with the original absent, follow exactly the delivered manifest action,
check each current view digest, preserve literal IDs and canonical bytes, and
exercise broken links/digests. External RED `codex-android1162-e-red.xml` confirms
both source defects; `-d-red.xml` additionally preserves the author's wrong
Workflow constructor. External GREEN `-f-green.xml` passes both corrected cases.
The expanded import regression `codex-android1162-g.xml` passes 40 cases.

The full run `codex-full22c` on the previous frozen source was stopped only after
these independent defects made that candidate superseded; its exact owned tree,
log, partial basetemp and interruption receipt are preserved. It is not a passing
full run and does not validate this correction.

Fresh checks on code commit `56317d1af3d01e420d2abf3ffe8d320c6997058a`:

- Expanded area H: 68 cases, 66 PASS and two failures after the test helper's
  unchanged 20-second deadline (managed artifact and JavaScript recovery).
  Their teardown cancelled still-running workers without a retained result.
  Both cases pass in isolated I, 2 PASS, 33.396 seconds, without code or deadline
  changes. H's 230.986-second failed run remains intact; this is not one green
  area run. A separate engine-only diagnostic on H's exact DLL returns exit 0
  in 2.931 seconds. The cause of the deadline overruns is not established.
- Fresh actual MCP: seven observations, including following the action delivered
  by the imported summary through two consecutive transfers. Local parent/action
  IDs, recomputed view digests and complete canonical documents match.
  `codex-android1162-mcp23a.json` fixes all three changed runtime file hashes.
- Normal UI in the twice-imported project submitted a 140-unit manifest window,
  read the destination IDs in the visible summary receipt, and read the resource
  manifest with CRLF. The latter equals the actual decoded UTF-8 file; download
  of the window is byte exact. `codex-android1162-ui23a.json` and
  `codex-android1162-ui-verified23a.json`; both screenshots visually inspected.
  Own tab 7 closed and private owner 64336 tree closed by exact identity;
  `qa-codex-android1162r2-closed.json`. All profiles and previous failures remain.

CAS2 independent review and fresh combined/installed acceptance remain required.
