# Static artifacts and retained comparisons

The Análisis tab and the native MCP catalogue expose the same operations.
Select a project artifact, choose an operation and start it. Its saved sections
can be searched, paged and cited as findings. Downloading the complete analysis
retains the input identity, execution receipt and limitations.

## Directories and extraction

An artifact may be a regular file or a physical directory. Directory identity
uses sorted relative paths, entry kinds, file SHA-256 values and sizes. Links
are recorded without following their targets. The artifact view shows the
inventory and reads selected regular members at their original paths.

`artifact.inventory` inspects supported containers and application packages.
`artifact.extract` writes into a new job-owned directory and registers each
derived file as an artifact. Parent/child links preserve the original member
location. These links also survive evidence transfer; the original and derived
file bytes are still excluded from portable evidence bundles.

## Source observations

`javascript.application` accepts ASAR or a directory and retains application
and semantic graphs. `source.graph` records an immutable physical source
inventory; it does not infer import relationships. `javascript.compare_source`
compares that observation with a saved application graph. Different graph
roles at the same physical path are not counted as duplicate files. Exact
bytes, changed bytes, ambiguous paths and unknown coverage remain distinct.

`javascript.recover` uses the local Babel parser and generator. Structural
extraction recognizes module function tables; heuristic extraction accepts
looser shapes; inspection retains the whole program. Minimal, standard and
aggressive rewrites are explicit. Aggressive rewriting folds finite numeric
arithmetic only. It never executes the supplied script. Readable output,
module functions and source maps become derived artifacts. Ranges preserve
the original UTF-8 bytes, including a BOM. Recovered names and readable code
do not establish original source or runtime equivalence.

## Structured and application artifacts

`sqlite.database` captures the database and available WAL/SHM sidecars into a
private job directory before opening SQLite. Source bytes are never opened
for writing. It retains schema, columns, foreign keys, indexes and selected
read queries with bindings, offset and optional limit. No limit retains all
rows. BLOBs use base64, large integers use decimal strings, and nonfinite
reals or invalid UTF-8 text use explicit tagged values. A changing capture
fails visibly; a partial family is not silently treated as a stable snapshot.

`managed.graph` relates metadata, CIL calls and native declarations from the
same bytes. `managed.reconstruction` imports analyst/decompiler text against
an exact saved method signature and normalized IL hash. It records inference
and does not execute or verify reconstructed behavior.

`apple.application`, `android.application` and `harmony.application` project
package inventories with artifact identities and explicit unknowns. These
graphs do not establish runtime calls or decoded DEX/Ark semantics.
`apple.interface_builder` decodes supported NIB/storyboard connections.
`apple.dylibs` resolves recorded library loads. `apple.assets` uses assetutil
on macOS and is unavailable on Windows. Its platform requirement is exposed
by the catalogue and the UI.

`wasm.compare_interfaces` compares retained typed imports/exports, with a
both/imports/exports selector. Duplicate entries and unresolved signatures
remain unknown. Matching declared interfaces do not verify module behavior.

## Acceptance evidence

The static extension batch passes 61 tests with two opt-in Ghidra tests skipped,
plus strict TypeScript checking and the production engine build. New fixtures
include real compiled managed code, WABT-compiled type changes, a directory
packed into ASAR with a deliberate 128-to-256 change, mobile package inventories,
NIB connections, SQLite WAL/BLOB/int64/nonfinite/text cases and JavaScript with
non-ASCII byte ranges. MCP exercises the actual workers through stdio; the UI
reads directory members, saved records and derived artifacts. This batch does
not close the remaining runtime/debugger/device families in SOURCE-COVERAGE.md.
