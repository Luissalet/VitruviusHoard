# Native values and Apple metadata

In Binarios, open an artifact's retained Ghidra session and select **Trazar
valores entre funciones**. Supply the root procedure and optional query JSON. The same
operation is `trace_native_values` through `theseus_binary_call`; discovery
includes its parameters. No target code or model runs during this analysis.

The analysis follows high-p-code definitions/uses and direct call argument and
return bindings. Nodes, edges, procedures, unknowns and limitations are retained
as separate record sections. Every source observation includes its exact Evidence
identity, original artifact hash, provider and complete observed DTO. In Análisis,
open a trace node and choose **Consultar evidencia de origen** to read that DTO.
Record identities containing `/` or `#` remain addressable through HTTP and MCP.

The default requests the full available traversal. Explicit `max_depth`,
`max_functions`, `max_call_sites`, `max_nodes`, `max_edges`, `offset` and `limit`
select a smaller result; inspect the reported truncation and next offset. An
unknown indirect call, missing decompilation or unsupported flow stays unknown.
Decompiler data flow does not prove runtime behavior or exact memory aliasing.
Cancelling the composed job terminates its owned Ghidra and Node process families.
The retained native project can subsequently be reopened in a new session.

Evidence export/import preserves the trace and source observations. Imported
records describe their historical observation; they do not restore a live
Ghidra process or certify the present machine. Original binaries and native
project databases remain excluded from the portable bundle.

In Análisis, **Apple · Metadatos Objective-C y Swift** reads supported ARM64 or
x86_64 Mach-O slices. Choose `architecture` explicitly for a universal image;
otherwise the first supported slice is selected. `max_records` is an optional
caller selection. Objective-C output includes classes, protocols, categories,
properties, ivars and dispatch locations with original offsets/addresses.
Truncated metadata and unresolved pointers retain their coverage limitations.
The incorporated Swift conformance/vtable decoder is present, but positive
Swift compiler/type fixtures have not yet been validated in this delivery.

**Apple · Property list XML/binaria** reads either plist encoding through the
same saved analysis API. Binary values, UID references, large integers, dates
and nonfinite/negative-zero reals have explicit tagged JSON forms. Date output
is limited to Python datetime precision, as reported with the result.

**Apple · Firma y entitlements** uses installed `codesign` on macOS for display,
entitlements and static verification. It retains command, exit code and both
outputs; verification describes that host's trust context. The catalogue reports
unavailable on other operating systems. This Windows delivery does not claim a
live macOS signature test.

Acceptance fixtures include an original compiled C DLL with two procedures and
cross-call arithmetic, an absent root, depth-zero and paged selections, exact
source-evidence lookup after legacy import, process-tree cancellation, XML/binary
plist values and original Objective-C dylibs cross-compiled for both architectures.
The portable readers require no Apple SDK/runtime; Zig is only a fixture compiler.

