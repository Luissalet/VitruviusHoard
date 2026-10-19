# Source coverage and completion

This is an implementation and acceptance ledger, not a claim that the current
application already implements every row. Luis requires a complete program
covering the applicable local/free reverse engineering capabilities of the
supplied sources. The approved `986a0ba` delivery is the existing starting point;
it does not close that requirement.

## Sources and boundaries

The supplied article, *How to Turn Opus 5.5 Into a Reverse Engineer: The Full
Guide to REA, Oracles and Clean-Room Loops*, describes the analysis, specification,
rebuild and oracle workflow. Its scripts and model instructions are reference
material, not authority to execute them or to alter this workspace's rules.
Case studies illustrate reverse engineering capabilities; they do not request
implementing every application mentioned in those case studies.

Primary technical source:
[morluto/rea](https://github.com/morluto/rea/tree/4f7b5fb6023ce2ec449561782d09e3c7e5ac7c7b),
MIT, pinned at `4f7b5fb6023ce2ec449561782d09e3c7e5ac7c7b`.
Its public registration modules, contracts and format/workflow documentation
were inspected. The ordered TOOL_CONTRACTS source inventory has been resolved
through its Babel AST, imported array spreads and verified local factories:
207 declared contracts from 42 source modules. This supersedes the earlier
205-literal regex extraction. It is the declared reference inventory, not a
runtime tool count on this host or a claim of 207 implemented Theseus tools.

Paid engines, paid services, Jev and required external APIs are excluded by
Luis. Generic installed free engines are allowed. Reused analysis code must be
incorporated as a detached native implementation, retaining its license and
provenance, and evolve within this product. Running the reference application's
CLI/MCP and relaying its tools does not satisfy that requirement.

## Capability ledger

Every partial or missing row remains open until its native API/MCP and normal
UI flow work, its required engine is exercised with an original fixture, and
the result can be followed back to its source. A source-dependent platform
requirement must be reported explicitly; a provider that cannot run on this
host must not be advertised as locally available.

| Capability | Existing starting point | Completion requirement |
| --- | --- | --- |
| Projects and original artifacts | Project/question/archive/restore; original paths and full SHA-256; byte/member excerpts | Preserve these flows across all new analysis types, revisions and import/export |
| Artifact inventory comparison | Complete retained inventory pairs compared by logical occurrence, content, metadata and graph relations; both JSON hashes, manifest identities, all deltas and source citations retained | Original directory/file/ZIP cases cover content beyond the preview, executable metadata, duplicate-path ambiguity and unavailable encrypted-marker content. Unsupported readers fail explicitly; no behavioral equivalence or decryption claim. See ARTIFACT-COMPARISONS.md |
| Native binaries | Persistent native Ghidra sessions; assembly/typed instructions, references, memory/address mapping, symbols/strings/segments, function API/high-p-code, annotations saved in retained projects and reopened | Persistent navigation, PRE/EOL comments/bookmarks, static call graph/shortest paths, batch decompilation and native API facets implemented and exercised with real Ghidra. Cross-procedure high-p-code value tracing, argument/return bindings and retained source observations implemented. Broader feature tracing and architecture/format cases remain open |
| Binary comparison and byte oracle | Native function comparison preserves exact defined referenced-data extents, types and bytes; decoder masks normalize only resolved address operands, leaving literal scalars exact and unknown boundaries explicit. Real 128/256 negative case and relocated positive case pass | Whole-binary function matching and broader architecture/reference cases remain open. Selected-function observation equality is not behavioral equivalence |
| Raw binaries and firmware | Explicit raw architecture/load context and retained project, original 6502 image at0x8000; native Binwalk region/entropy observations and source-bound carving/decoding with nested artifact relationships, partial cancellation/restart recordings and explicit unknown ranges | Installed decoder/format coverage and damaged/encrypted inputs retain explicit gaps. Known-region extraction is not whole-image completeness. Broader platform-specific vendor filesystem validation is not certified |
| JavaScript recovery | Parser-based ASAR application/module and semantic graphs, source locations, retained semantic/feature queries; saved application-version and exact export-return-shape comparisons, basic source-map/ZIP observations; explicit V8 Inspector targets, finite context/script observations, optional source-text capture and saved hash/declaration reconciliation | Directory/ASAR applications, readable source/module recovery with original UTF-8 ranges and source maps, saved physical source inventories and source/distribution comparisons implemented. See JAVASCRIPT-RUNTIME.md for original Node coverage; broader browser/Electron runtime and source-map correlation remain open |
| Electron applications | ASAR member reading | Main/preload/renderer boundaries, IPC, fuses, local runtime targets/scenarios and static/runtime reconciliation |
| Browser observation | Imported HAR summary; explicit CDP page targets and finite metadata windows, independently selected script texts/DOM/listeners/completed response bodies/PNG, explicit scenarios and retained step comparisons, precise main-document coverage with UTF-16 ranges and script hashes, static source association | Original Chromium headless, portable PNG, independent action effects and incomplete/cancelled/interrupted recordings exercised. Richer source-map correlation, WebSocket stream comparison and Electron validation remain open |
| Network captures | HAR entries, native offline PCAP/PCAPNG through actual TShark/capinfos, protocol/field discovery, repeated values, filters/decode-as/two-pass selection and full retained packets; native qlog0.3 JSON/JSON-SEQ events, exact numeric tokens and recorded STREAM ranges | Broader stream/runtime correlation and saved web capture scenarios remain open; HTTP/3 depends on dissectors/recorded keys. qlog range metadata never reconstructs body bytes or proves delivery; newer qlog versions are not certified |
| Managed applications | Native metadata, types/members/signatures, complete CIL instruction bytes/offsets, exception regions, P/Invoke declarations and saved member/CIL comparisons with ambiguous matches retained | Application graph and reconstruction import bound to method signature/IL hashes implemented. Native declaration/name/module contrast against hash-bound retained Ghidra observations implemented, with exact source Evidence and explicit mismatch/unknown cases. Runtime binding, NativeAOT body mapping and behavioral verification remain open |
| Android | Native inventory/application graph, APK manifest/resources, DEX classes/members/overloads/bodies and incoming references; explicit ADB device/package/process/display/log/file/application operations with recorded sources, partial recovery and portable evidence | Broader physical/split-package fixtures and static/runtime correlation remain open. Java is reconstructed; JNI/reflection/runtime calls are not established by static references. Runtime recordings describe their capture time, not general behavioral equivalence |
| Apple application artifacts | Portable Mach-O/keyed archive/NIB readers, package graphs, Interface Builder, dylib resolution; assetutil catalogue with explicit macOS requirement | Objective-C classes/protocols/categories/properties/ivars/dispatch and XML/binary plist implemented and tested on original ARM64/x86_64 Mach-O fixtures. Swift static conformances/witness slots/non-generic class vtable descriptors validated with original synthetic ABI fixtures, direct/indirect pointers and selected FAT slices (see SWIFT-METADATA.md). These are not Swift compiler output. Complete types/reflection, compiler-version breadth and live UI/call observation remain open; codesign is exposed only on macOS and not live-tested here |
| Harmony application artifacts | Supported HAP/HSP/App Pack inventory and application graph with exact artifact identities | Broader feature tracing and runtime correlation remain open |
| Go and Rust binaries | Native compiler/module information and Rust auditable graph; positive PE32/64, ELF32/64 and thin Mach-O32/64 fixtures, supported byte orders and Go inline/pointer encodings; real Rust Windows compiler path with exact source bytes | Universal/fat Mach-O requires a selected thin slice and remains explicitly unsupported here. Native function analysis remains in Ghidra; these metadata readers do not recover language-specific functions/types or authenticate a producer |
| WebAssembly | Local WABT disassembly, preserved WAT definitions, imports/exports and signatures | Typed saved interface comparison implemented with duplicate/unresolved signatures kept unknown. Source/glue correlation remains open |
| EVM bytecode | Local selectors/arguments/mutability, storage, instructions, blocks/flow and terminal compiler metadata; original solc0.8.30 fixture read in raw/hex, independent compiler selectors/ABI/storage facts and explicit conservative inference markers | No chain API, deployment authentication or bytecode execution. Mutability can conservatively report view for pure source. Broader compiler/obfuscation and dynamic behavioral coverage is not established |
| Recorded crashes | Portable Linux ELF64 x86_64/ARM64 core notes/registers/signals/module maps, recorded/unknown/ambiguous memory and frame-pointer candidates implemented; retained through native API/MCP/UI and evidence transfer | Live GDB/pwndbg enrichment and verified current-executable correlation remain open; historical module offsets are candidates, not current identity |
| Signal recordings | Native installed sigrok decoder discovery/help and offline decode with explicit stacks/channels/options, full diagnostics, sample-range text, paged output and original identity | Original UART positive/negative cases and normal API/MCP/UI verification; no hardware acquisition is claimed. Each selected protocol still depends on its installed decoder and recording quality |
| Runtime instrumentation/debugging | Reference/candidate child processes; native free Frida SDK device/process discovery, persistent attach/paused spawn, script load/unload, resume, status/recorded events/close and finite observation windows | Windows original Rust fixture validates recorded arguments/returns/binary messages/JS errors, close without target kill and pause resumption, cancellation and historical transfer. Installed catalog is disk-only; restart freezes journals without reconnect/replay. Remote/physical-device live validation, GDB/Rizin backends and static/runtime correlation remain open; see INSTRUMENTATION.md |
| SQLite and structured artifacts | Read-only SQLite schema; ZIP/ASAR/HAR/source-map preview | Full SQLite schema/query/record observations, private WAL-family captures, BLOB/int64/nonfinite/text preservation and extracted artifact relationships implemented and portable; broader structured/runtime comparisons remain open |
| Findings and unknowns | Cited observation/interpretation, unknown lifecycle and dependencies; portable native evidence import/export retaining records, exact available analysis JSON and historical receipts | Extend static/runtime correlation and whole-package observations; original artifacts and native Ghidra project databases are explicitly excluded from evidence transfer |
| Behavioral oracle | Frozen command arrays/stdin, text or JSON output, exit/stderr, revisions, background jobs/cancellation | Extend to specified runtime/package/interface cases and observable side effects, preserving independent reference authority and expected failure cases |
| Oracle self-test | Native saved perturbation suites and complete reference/candidate receipts; original constant/branch/boundary fixtures, surviving weak-oracle defect, broken mutant and invalid reference tested without a model | Extend the same workflow to whole runtime/package observations; supplied finite mutants do not establish general oracle adequacy |
| Clean-room workflow | Immutable behavior handoff for a named builder workspace, separate reader evidence and builder-only document; linked verification/retry receipts and reported contract changes; UI/API/MCP exercised | No automatic source-independence guarantee for analyst-authored prose; broader runtime/package builder scenarios remain open |
| Reconstruction completeness | Native obligations, boundary scenarios, owners, dependency graph and unknown lifecycle; current case/specification/program identity determines observed coverage, with oracle sensitivity and unresolved dependencies retained | Completeness describes the recorded claim graph only; add whole runtime/package observations and evidence portability before claiming the complete source workflow |
| Reusable investigation knowledge | Projects retain findings/specifications | Transfer useful patterns and tested workflows across related projects and the existing Faustus skill/knowledge facilities |
| Normal product surface | Web workspace, 38 MCP tools, static/runtime discovery/start/paged records, persistent binary session/byte-comparison forms, reconstruction/oracle workflow and evidence transfer | Complete the normal UI/MCP verification for added operation families and preserve every initial tool; no ad hoc script required for product capabilities |

## Verification that must accompany completion

1. Trace each supplied capability to its native operation and UI flow, with
   source provenance and a reproducible original fixture. Do not substitute a
   tool count for behavior.
2. Exercise supported engines for real. Unit tests with fake engines establish
   orchestration behavior, not decompilation, device or runtime capabilities.
3. Test the three oracle classes separately: byte/data, behavior, and whole
   runtime/package observations. A matching hash or instruction stream alone
   does not prove referenced constants or behavior.
4. Include deliberately wrong constants, swapped branches and boundary/index
   errors. Also include the referenced-literal case in which instruction address
   normalization could otherwise hide a different floating-point value.
5. Preserve original files, source locations and project data. Record both
   partial results and failures; do not replay interrupted work automatically.
6. Verify the complete reader/specification/builder/oracle/retry flow, including
   an unresolved case, rather than only demonstrating a successful analysis.
7. Update the application documentation, family manual, plugin registration,
   knowledge graph and durable project memory to the implemented behavior.

The current initial delivery remains usable while these requirements are
implemented. Its earlier code/UI review is evidence only for that delivery's
scope; it is not approval of the completed studio.

Static extension acceptance: 61 PASS, two opt-in Ghidra SKIP; strict TypeScript/build PASS; real MCP35/operations33 and normal UI record/member/derived-artifact flows verified. See STATIC-ARTIFACTS.md. These checks cover this batch only; all remaining requirements above stay open.

Native navigation/capture extension: 49 binary session operations and 36 static operations through MCP35. Original compiled call/resource fixtures and PCAP/PCAPNG repeated DNS data verified with real installed engines. See BINARY-NAVIGATION-CAPTURES.md; remaining rows stay open.

Native values/Apple extension: binary.trace_native_values retains the exact
Ghidra observations behind nodes and call bindings, supports explicit caller
limits and full default traversal, and transfers them as historical evidence.
Static catalogue39, binary50, MCP35. See NATIVE-VALUES-APPLE.md for tested scope;
Swift positive cases and macOS live validation are not claimed.

Final batch acceptance: 74 PASS, zero SKIP (214.89s), including both real Ghidra
integration cases; strict TypeScript/build PASS. Real stdio MCP35/static39/
binary50, export/import and original-hash preservation PASS. Browser followed
an address/path-keyed trace node to its exact source Evidence record. macOS
signature and positive Swift/type cases remain unverified, as stated above.

Recorded crash extension: original synthetic format fixtures for both Linux
ABIs, independently decoded with pyelftools, exercise native worker/records and
evidence transfer. Static catalogue40/MCP35; no target execution or live attach.
See RECORDED-CRASHES.md for ABI, selection, unknowns and fixture boundaries.

Recorded-core final acceptance:86PASS zeroSKIP292.95s, including both real
Ghidra integration regressions; focal core12PASS1.31s. Real stdioMCP35/static40,
full records and evidence transfer preserve original hash. Browser started a
selected-memory/frame-limit job and read recorded/unrecorded bytes and explicit
selection-limit. Scope remains controlled synthetic ELF recordings.

Signal extension uses a separately installed generic sigrok engine, owned input
capture and original UART fixture. The catalogue exposes42 static operations
through35MCP; binary session operations remain50. See SIGNAL-RECORDINGS.md.

Signal acceptance:88PASS zeroSKIP319.42s with the initial stable engine, both
real Ghidra regressions included. After selecting the official0.8.0-git-f44dd91
engine and updating default discovery, focal signal tests2PASS validate all
decoder interactions again. Actual MCP35/static42 and browser read/start/paged
coverage pass on that engine; signature help/listing have empty stderr.

Managed/native contrast uses the incorporated native-verification algorithm with
product-owned retained-input/hash binding, source links and native UI/MCP flow.
Static catalogue43/MCP35, binary50. See MANAGED-NATIVE.md for the strictly static
meaning of verified and unresolved runtime/native-body correspondence.

Final managed/native and instance-session acceptance:91PASS zeroSKIP377.17s,
including the three real Ghidra integration cases. Focal native contrast1PASS
122.82s; cookie/record/evidence regressions15PASS16.20s. Build/typecheck, actual
MCP35/static43, browser contrast/source links/start and simultaneous Main/QA
authentication PASS. No runtime-binding or behavioral-equivalence claim.

Android static extension exposes six operations through the existing MCP35
surface (static catalogue49). Its original APK/DEX fixture verifies manifests,
permissions/SDK, raw and synthetic members, explicit overload selection,
Java/Smali/declaration representations, incoming nodes and repeated raw DEX
invokes, scoped generated-code positions, full paging and resource links.
Focal acceptance2PASS85.74s; real MCP35/static49 with evidence export/import and
original hash preservation PASS. Browser reads invoke offsets0/6 and starts a
method read that retains complete initializer Smali. See ANDROID-STATIC.md.
ADB/runtime capabilities remain open and are not part of this static batch.

Android runtime extension adds 24 explicit operations and two MCP tools (37
total; static49/binary50 unchanged). All 24 operations have been exercised on
an owned software-rendered Android36 emulator with an original compiled/signed
fixture. Broad acceptance98PASS zeroSKIP391.06s includes real Ghidra and emulator
cases; final Android focus7PASS34.25s also exercises actual host-client
cancellation with retained partial JSON and the same shared ADB server PID. Actual
MCP and browser retain recording hashes, collected-file links, citations and
portable historical observations. See ANDROID-RUNTIME.md for action semantics,
shared-server preservation, interruption recovery and fixture limits. Remaining
program rows stay open.

Offline qlog extension adds network.qlog (static50; MCP37/binary50/runtime24
unchanged), original standard-library reader and source-bound events/ranges,
with explicit partial/malformed recording diagnostics. Focal10PASS0.90s uses
the actual installed aioquic1.5.0 writer plus independent JSON/sequence cases.
Real stdio MCP37/static50, source finding and transfer PASS; the browser starts
the operation and reads contributing event pointers from a retained stream.
See QLOG-RECORDINGS.md for profile, clock, selection and completeness limits.
Broad acceptance108PASS2SKIP223.09s includes three real Ghidra cases. The two
explicit emulator opt-ins were not selected for this offline batch; both already
passed on the owned emulator in the approved Android runtime delivery.

Compiler-format extension:30 positive Go/Rust carrier/encoding cases plus
path-boundary/Windows-separator negatives, actual Rust MSVC compiler output,
original Solidity compiler raw/hex comparisons and explicit universal-image
rejection. Final affected-area59PASS109.98s; npm build/typecheck PASS. Real
stdio MCP retains exact original hashes, the corrected Rust path observation,
EVM inference markers, a source finding and historical transfer; the browser
reads the marked function and starts the same EVM operation. See COMPILER-FORMATS.md.

Firmware extension adds firmware.regions/firmware.extract (static52; MCP37,
binary50 and runtime24 unchanged). Native Binwalk3.1.0 and optional 7-Zip26.01,
with original Python region/entropy, archive and recording composition. Broad
acceptance160PASS2SKIP285.88s includes all three real Ghidra cases; explicit
emulator opt-ins remain skipped here and were exercised in R11. Final firmware
focus10PASS6.18s also verifies original-file offsets for a selected extraction
interval after the last metadata correction. Real MCP37/static52, exact derived
bytes/hashes, selected-range source links, findings and historical transfer PASS.
Browser starts extraction, reads the128..174 gzip range and opens its decoded
member with the carved parent's provenance. See FIRMWARE.md; recorded gaps and
unclassified ranges do not establish whole-image completeness. Other programme
families remain open.

V8 Inspector extension adds two runtime operations (35 total) and saved
JavaScript static/runtime reconciliation (53 static operations, MCP37/binary50
unchanged). Final affected-area44PASS2SKIP47.79s and complete acceptance
199PASS2SKIP358.11s include all three real Ghidra cases; the two owned-emulator
opt-ins were not selected. Original Node22.19.0 tests cover passive metadata,
explicit source texts, Unicode/CRLF, stale targets, cancellation, exact orphan
observer recovery without replay, immutable hash-bound reconciliation after
source removal, ambiguous content, declarations/contradictions, both changed
input receipts, cross-project rejection and abrupt interruption during atomic
final publication. Real stdio MCP and the browser
exercise saved comparisons, both source citations, record URL search, findings
and historical evidence transfer. See JAVASCRIPT-RUNTIME.md; browser/Electron
page capture and broader runtime behavior remain separate open capabilities.

Browser observation extension adds browser.targets/browser.observe (37 runtime
operations), browser.compare/browser.reconcile_sources (55 static operations)
and native PNG MCP ImageContent (38 MCP tools; binary50 unchanged). Its original
Chromium headless fixture exercises ongoing requests, POST data, binary/text
bodies, redirects/failures, dynamic scripts, selected DOM/listener metadata and
PNG. Late unsolicited notifications are excluded after the timed window;
selected optional read replies retain their later collection times. An
append-only protocol journal preserves complete unsnapshotted frames and exposes
truncated tail bytes during cancellation/orphan recovery without reconnecting.
Affected-area51PASS2SKIP109.33s; after the last comparison-name/search correction,
the selected saved-comparison test1PASS15.83s and combined browser/Inspector
area16PASS49.30s. Complete acceptance composition covers206PASS2SKIP: the second
complete run203PASS3FAIL2SKIP341.79s rejected the author's `.venv` basetemp in
all three Ghidra cases; those exact three pass3PASS170.82s in an admitted path.
This is a composition, not a single green run. The earlier full run's one
Inspector passive-reconnection failure remains in its log; that case passes
the isolated, combined-area and second complete runs without a product change.
Actual stdio MCP38/static55/runtime37 returns native ImageContent,
preserves a finding's two source references and transfers the same PNG bytes
after its original file disappears, with zero recreated live sessions. The
After the owned fixture closes, a fresh stdio MCP process again compares the
saved captures, searches six POST records, reads both source citations and
returns the same imported PNG as native ImageContent. The
normal browser starts observation and saved comparison, searches POST records,
shows both input hashes and displays the retained PNG after the owned target
and HTTP server close. See BROWSER-RUNTIME.md for incomplete/unknown semantics,
optional read scope. Subsequent scenario and precise coverage extensions are
described below; Electron validation remains separate work.

Saved artifact inventory comparison adds artifact.compare (56 static operations;
MCP38/binary50/runtime37 unchanged), exposing the already incorporated native
comparison kernel through the existing saved-pair UI/API/MCP. It preserves full
logical occurrences, metadata/relations, content identities, completeness and
two-source bindings without opening originals. Affected static acceptance
16PASS101.13s exercises original directories/files/ZIPs, change beyond the byte
preview, executable metadata, duplicate paths, unavailable encrypted-marker
content, unsupported compression rejection, both changed JSON receipts and
historical transfer. The encrypted marker is not a decryption test. Actual stdio
MCP creates both inventories, compares, searches a change, saves a two-source
finding and transfers the records after originals disappear; a fresh read-only
MCP session confirms the exact imported delta and both citations. The normal UI
starts another saved comparison, searches the Unicode path and saves a finding
with two sources. Desktop/mobile forms and record sources are exercised with no
frontend code change. See ARTIFACT-COMPARISONS.md; this does not implement whole
binary function matching or runtime behavior equivalence.

Explicit page scenarios add browser.scenario (38 runtime operations; MCP38,
static56/binary50 unchanged). Caller-authored CDP steps retain exact requests,
responses, intervals, errors and incomplete prefixes without reconnect/replay.
Saved browser comparison and source reconciliation accept both actual capture
types; literal positional step alignment preserves unknowns and both citations.
The scenario/browser/Inspector/inventory area passes30tests88.75s, including
owned-browser actions, independent HTTP effects, errors, cancellation, orphan
and journal response recovery, return-value changes and retained source matching.
See BROWSER-SCENARIOS.md. This does not certify precise Profiler coverage or
Electron/main/preload behavior.

Finite precise coverage adds browser.coverage (39 runtime operations; MCP38,
static56/binary50 unchanged), with an acknowledged armed receipt through normal
job reads, producer UTF-16 ranges/counts, source hashes, initiators and indexed
function records. Missing/lazy observations and function-only branch granularity
stay unknown. Document changes and interrupted cleanup retain incomplete scope.
Saved source reconciliation accepts the actual coverage type and historical
transfer preserves counters/sources without reconnecting. See BROWSER-COVERAGE.md;
this does not certify Electron/IPC or behavior equivalence.
The complete suite passes 226 tests with 2 owned-emulator opt-ins skipped in 434.37s,
including the explicitly enabled Ghidra cases. Earlier diagnostic runs remain
separate: the live producer returned function-only ranges, an external scenario
missed a shorter window, and a pre-existing heartbeat assertion used 250ms.
Acceptance preserves unknown granularity, checks actual action/window ordering
and polls the independent heartbeat within 2s. Real stdio MCP and desktop/mobile
UI exercise armed/cancelled receipts, indexed functions, both retained source
citations and historical transfer after the owned fixture closes.
