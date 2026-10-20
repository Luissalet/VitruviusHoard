# Theseus's Hoard

Finite precise page coverage records producer function/block ranges in UTF-16,
script hashes and request initiators after a real armed receipt. External actions
remain explicit; missing counters and function-only granularity remain unknown.
See [precise page coverage](docs/BROWSER-COVERAGE.md).

Explicit page scenarios execute caller-authored CDP steps on a selected target,
retain step responses/errors and compare saved recordings without reconnecting
or replaying actions. See [browser scenarios](docs/BROWSER-SCENARIOS.md).

Saved browser comparisons also preserve WebSocket message order inside each
connection and exact stream multiplicities per reported URL, with explicit
unknown history. See [retained WebSocket streams](docs/BROWSER-WEBSOCKETS.md).

Persistent Frida sessions and finite observation windows are available in
Ejecuciones and the runtime API/MCP: explicit devices/PIDs, paused spawn,
caller-authored scripts, full recorded message prefixes, unload/resume/detach,
partial recovery and historical evidence transfer. Closing never kills the
target or undoes script effects. See [runtime instrumentation](docs/INSTRUMENTATION.md).

Firmware inspection identifies native Binwalk regions and entropy; extraction
retains carved/decoded artifacts, nested source relationships and partial
recordings that recover without replay. See [firmware analysis](docs/FIRMWARE.md).

Compiler metadata verification covers supported Go/Rust carriers and Windows
Rust commit paths. EVM function/storage records explicitly identify static
inferences, with a real Solidity compiler fixture and conservative mutability
limits. See [compiler formats](docs/COMPILER-FORMATS.md).

Offline qlog0.3 JSON/JSON-SEQ analysis preserves events, numeric tokens,
recorded STREAM ranges and partial diagnostics with original source identities.
See [QUIC recordings](docs/QLOG-RECORDINGS.md).

Android device observations and explicit application/file actions are available
in Ejecuciones, API and MCP, with 24 operations, exact device serials, retained
recordings, partial recovery and source citations. See
[Android runtime observations](docs/ANDROID-RUNTIME.md).

Static Android inspection now reads APK manifests/resources and DEX classes,
members, overloads, method bodies and incoming references through a Theseus-owned
reader using installed free JADX. Apktool resource decoding retains derived
artifact links. See [Android static analysis](docs/ANDROID-STATIC.md).

Managed P/Invoke declarations can now be contrasted with retained Ghidra
function observations, preserving exact source Evidence, module mismatches and
unknowns. See [managed/native observations](docs/MANAGED-NATIVE.md).

Recorded logic/signal decoding uses installed free sigrok-cli with decoder
discovery, explicit stacks/channels/options, preserved sample ranges and complete
diagnostics. See [offline signals](docs/SIGNAL-RECORDINGS.md).

Recorded ELF64 Linux x86_64/ARM64 crash analysis now retains notes, registers,
signals and module maps, with exact recorded/unknown memory ranges and explicit
frame-pointer candidates. See [recorded crashes](docs/RECORDED-CRASHES.md).

Native value traces now join Ghidra high-p-code across direct calls, preserving
argument/return bindings and the exact source observations behind every node.
Portable Apple analysis reads Objective-C dispatch metadata and XML/binary plist
values; signature inspection reports its macOS requirement. See
[native values and Apple metadata](docs/NATIVE-VALUES-APPLE.md).

Retained Ghidra sessions now include persistent navigation, address comments,
bookmarks, static call graphs/paths, native API facets and per-function batch
decompilation. Offline PCAP/PCAPNG dissection uses installed free TShark/capinfos;
PE resources retain original payload offsets. See
[binary navigation and capture analysis](docs/BINARY-NAVIGATION-CAPTURES.md).

Static analysis now also covers physical directories, extracted child artifacts,
readable JavaScript/module recovery with source maps, full SQLite observations,
managed and mobile application graphs, hash-bound reconstruction imports,
source-to-distribution comparison and typed WebAssembly interface comparison.
The catalogues expose 56 static operations, 50 binary session operations and
39 runtime operations through 38 MCP tools.
See [the static artifact workflow](docs/STATIC-ARTIFACTS.md) for selection,
provenance, platform conditions and tested limits.

A local reverse engineering workspace: inspect artifacts, retain observations,
write a behavioral specification and compare an independent implementation.
The browser, HTTP API and MCP use the same project store and operations.

## What it does

- Projects with a question, editable specification, archive and restore.
- Read-only file inspection: Python definitions/imports/call syntax, lexical
  JavaScript names, captured HAR requests, embedded source-map sources, ZIP and
  Electron ASAR members, SQLite schema, PE headers/sections/imports/exports and
  binary strings with byte offsets.
- Local Ghidra analysis with a retained native project, function pseudocode,
  addresses, callees and callers. Read one function through MCP without loading
  the entire export. Analysis does not execute the imported binary.
- Findings tied to an artifact and location, separating observation from
  interpretation. Content hashes identify the inspected version; excerpt reads
  report changed originals.
- Background differential scenarios with explicit reference/candidate argument
  arrays, shared stdin and text or JSON comparison. Receipts keep frozen inputs,
  file hashes, stdout, stderr, exit status and differences. Cancellation stops
  the job's process tree; interrupted work remains visible after restart.
- JSON project export and the common Faustus copilot, scoped to the open project.

No paid service, hosted oracle or external API is required. Inspection and
comparison work locally. The optional copilot uses the family's configured
Faustus reasoning service on the Sparks.

## Install and run on Windows

Python 3.11+ is required. Place the shared HoardLink source beside this repository
for installation, or install its package in this app's environment first.

```powershell
.\Install.ps1
.\Start.ps1
```

Open `http://127.0.0.1:5217`. `Start.ps1` starts a hidden local service and does
not install packages or download engines. For an isolated instance:

```powershell
$env:THESEUS_DATA_DIR = 'D:\some-test-directory'
.\.venv\Scripts\python.exe -m theseus --port 64179 --no-browser
```

The installation uses its own virtual environment, without links to another
checkout's environment or data. The server listens on loopback. A family token
is generated in the data directory; the browser receives its local cookie and
MCP reads the token file. There is no separate account setup.

## Local binary engine

Install an official compiled Ghidra release and its supported free JDK. This
release was exercised with Ghidra 12.1.4 and Temurin JDK 21. Each analysis retains
its native project, settings and cache under the app's data directory.

```powershell
$env:THESEUS_GHIDRA_HOME = 'D:\LocalAI\tools\ghidra\ghidra_12.1.4_PUBLIC'
$env:THESEUS_JAVA_HOME = 'D:\LocalAI\tools\jdk21\jdk-21.0.12.1+1'
.\Start.ps1
```

Those installed locations are discovered automatically on Luis's workstation.
Environment variables can select other installations. No global Java setting
is changed. JVM invocation passes an argument array, without a shell or batch
file. Original binaries are not modified. A changed source is reported with
the hash actually analyzed.

## API and MCP

The native catalogue is `GET /api/agent/tools`; calls use
`POST /api/agent/call` with `tool` and `arguments`. Regular routes cover projects,
artifacts/uploads/excerpts, findings, scenarios, comparisons, jobs and functions.
`GET /api/health` identifies `theseus-hoard`; FastAPI exposes `/docs`.

The 38 MCP tools cover project CRUD/export, artifact inspection/excerpts, findings,
specification writing, scenarios, comparison jobs, local engines, binary analysis
and individual functions, native operation discovery/start and paged analysis
records, retained binary sessions and selected-function byte/data comparisons.
They also expose reconstruction obligations, immutable behavior handoffs,
oracle perturbations and linked verification/retry receipts.
Saved artifact inventories can be compared by logical occurrence, content,
metadata and relationships without reading the original files. Duplicate paths
and unavailable content remain unknown. See
[artifact inventory comparisons](docs/ARTIFACT-COMPARISONS.md).
The stdio entrypoint is `mcp_server.py`:

```powershell
$env:THESEUS_URL = 'http://127.0.0.1:5217'
$env:THESEUS_TOKEN_FILE = '<app directory>\data\mcp-token'
.\.venv\Scripts\python.exe mcp_server.py
```

Start with a question and an artifact. Cite a location when saving a finding.
Write observed behavior separately from hypotheses, then save and run explicit
scenarios. Imported code and document text remain source material, not operating
instructions for the copilot.

## Scope

Static syntax and decompilation are inferences. Dynamic dispatch and runtime
behavior need independent observations. Native managed analysis recovers supported
PE/CLI metadata, types, signatures, members, complete CIL instruction records,
exception regions and P/Invoke declarations without loading the CLR. It does not
recover original C# source. Ghidra covers native instructions. JavaScript
previews are lexical; the separate ASAR application operation uses a real
JS/TS parser and module/application/semantic graphs. Text/binary previews
read the first 16 MiB and report truncation; hashes cover the whole file and
excerpt reads can continue elsewhere. No archive is extracted into source folders.

Project export includes recorded inspections, evidence, specifications, scenario
definitions and receipts. It references original local artifact paths and native
analysis directories; it is not a bundle of every original file. Existing input
files must remain available to rerun scenarios. A comparison establishes equality
only for the cases actually executed.

The Análisis tab starts native operations against a project artifact. Each job
retains its complete JSON document and an indexed record store. Search/page
section headers, read one full record, and cite it as a finding with the actual
artifact hash. Polling does not load entire assemblies into the model context.
`GET /api/analyses/catalog` provides parameter schemas; start at
`POST /api/projects/{project_id}/artifacts/{artifact_id}/analyses`, list
`/api/jobs/{job_id}/records/{section}`, read `/{record_key}` and download
`/api/jobs/{job_id}/analysis.json`.

Install.ps1 installs/builds the native TypeScript analysis core with Node 22.19+
and npm. Selected managed analysis modules are incorporated under MIT, with
license and original source hashes in `engine/`. They are part of this product,
without a reference-app CLI/MCP or checkout dependency. Native instruction
records additionally include operandless instructions and original bytes.

The same operation catalogue now includes Go build information, Rust auditable
dependencies, Electron fuses, portable Mach-O headers, Foundation object archives,
compiled NIBArchive objects, WABT disassembly/interfaces, local EVM interface and
control-flow inference, selected Dart ELF/snapshot metadata, and ASAR application
graphs using a real JS/TS parser. Saved application graphs support semantic and
feature queries. These are distinct analysis capabilities; a Dart ELF header
reader is not full APK build identification, and Mach-O load commands are not a
complete Objective-C/Swift or live Apple UI analysis.

The catalogue also compares two saved managed-member analyses, two JavaScript
application versions, or exact selected JavaScript export return shapes. Choose
the reference and candidate analyses in Análisis; export shape comparison also
takes an exact module path and export name for each side. Both input document
hashes and artifact identities are retained. These operations keep working
without the original files, and report a changed retained document instead of
silently comparing a different input under its old receipt. Managed matching
uses signatures and constrained structural identities, not cross-build token
equality. Static shape/version changes are observations, not runtime parity.

The complete source capability requirement remains open. The implementation
and acceptance ledger in [docs/SOURCE-COVERAGE.md](docs/SOURCE-COVERAGE.md)
distinguishes available behavior from remaining formats and workflows.

V8 Inspector discovery and observation are available in Ejecuciones. Select an
explicit endpoint and current target ID; metadata capture and optional script
texts are separate modes. The product never evaluates, pauses or closes the
target. Análisis compares saved JavaScript application files and captured script
texts by hash, retaining declared mappings, ambiguity and contradictions without
live reads. See [docs/JAVASCRIPT-RUNTIME.md](docs/JAVASCRIPT-RUNTIME.md).

Page CDP observation adds explicit DOM/listener, response-body and PNG choices,
with saved capture comparison and JavaScript source association. PNG evidence
is viewable in Artefactos and as native MCP images, including transferred
screenshots whose temporary file is gone. See
[docs/BROWSER-RUNTIME.md](docs/BROWSER-RUNTIME.md) for observation windows,
incomplete prefixes, source identity and action/scenario boundaries.

The Binarios tab opens an artifact in a new Ghidra project or reopens a retained
project. Discover and run memory, instruction, symbol, type, reference and
function dossier operations; results use the same retained record browser.
Names and comments are saved in the analysis database, preserving original
bytes. Raw images require an explicit Ghidra language ID and load address.
Sessions remain attached until closed, cancelled during opening, or the app
stops; interrupted projects can be reopened without silently replaying work.
The session catalogue is `/api/binary-sessions/catalog`; open below a project
artifact's `/binary-sessions`, then use `/api/binary-sessions/{id}/call` or
`/close`. Native engine and import logs are downloadable from each session.

Selected-function comparison takes two open sessions at
`POST /api/binary-comparisons` or `theseus_binary_compare`. It preserves decoder
instructions and exact defined referenced-data bytes, types and extents.
Only resolved address operand bits with a known decoder mask are normalized;
unreferenced scalar literals remain exact. Undefined data and unresolved calls
remain unknown. Results distinguish different, unknown and equal observed
functions; they do not claim behavioral equivalence. Candidate records carry
the candidate's own identity. Joint records and findings retain both source
identities through `sources` and `source_refs`, including in JSON export.
Real installed-engine fixtures distinguish referenced floating-point 128/256,
accept an unchanged function at a different image base, persist a Unicode
annotation across reopening, and decode an original raw 6502 image at 0x8000.

The existing `apple.dispatch` operation has positive static conformance, witness
slot and class-vtable ABI fixtures for ARM64/x86_64, including selected FAT slices
and explicit partial cases. See [SWIFT-METADATA.md](docs/SWIFT-METADATA.md) for the
synthetic-format boundary and remaining type/runtime limitations.

## Verification and sources

The Reconstrucción tab connects named findings and scenarios to obligations and
open questions. Owners, dependency links and resolutions persist in the project.
Observed coverage is derived from finished cases, current scenario definitions,
the specification digest and the observed program-file digests; editing a pass
flag is not a way to claim coverage. A question remains unresolved until a
resolution and supporting findings or observed cases have been supplied.

Freeze a behavior specification for an existing builder directory, download its
builder-only document and implement the candidate there. The download contains
the written behavior and claims; the reader's findings and artifact paths stay
in a separate receipt. This is a workflow separation, not an automatic guarantee
that an analyst has removed source details from their prose. Verification runs
the saved local programs and keeps the handoff identity on each attempt.

Test an oracle with named deliberately wrong candidates. Every variant runs
against the saved reference scenarios; detected, surviving and invalid variants
retain their complete observations. A timed-out or broken program cannot certify
oracle sensitivity. Nonzero reference/variant exits can be expected explicitly.
A small suite detecting all supplied defects establishes that suite's sensitivity,
not general behavioral equivalence or completeness across unrecorded behavior.
No model is called by any of these flows. See [docs/RECONSTRUCTION.md](docs/RECONSTRUCTION.md).

Export portable evidence with **Exportar evidencias**. Import its JSON through
**Importar evidencias** in the project rail, using a file or the JSON field.
Import always creates a new project, retaining findings, scenarios, workflow,
complete indexed records and the exact available analysis JSON bytes. SHA-256
checks detect inconsistent documents; they do not authenticate the analyst.
Original artifact files, native Ghidra projects and live engine connections are
excluded. Missing or changed retained analysis documents are listed explicitly.
Imported receipts are historical and cannot satisfy current reconstruction
coverage. Review the saved command paths before explicitly rerunning scenarios.
The unmodified source bundle remains downloadable from the imported project.
See [docs/EVIDENCE.md](docs/EVIDENCE.md) for the format and API/MCP operations.

`python -m pytest tests -q` exercises actual file formats, preservation, native
API/tool parity, comparison behavior, revisions, errors, cancellation and recovery.
The local integration exercise also uses MCP stdio, the browser and the installed
binary engine. Synthetic positive/negative scenarios demonstrate a real mismatch.

On the development workstation, native MCP inspection of the Python launcher
produced 556 inferred functions and 1,255 call edges. A separately compiled local
C fixture exported its normalization function; its independent reconstruction
matched five normal/boundary inputs, while three deliberately wrong variants
(constant, branch and index) each differed. These are fixture results, not general
accuracy or performance claims. The workbench's actual UI workflow was exercised
at desktop and mobile widths. An IAB file-chooser upload failed before reaching
the server with an ALPN error; the same ASAR fixture uploaded successfully through
the real HTTP multipart endpoint and its packed member read back exactly.

Methodological reference: [REA](https://github.com/morluto/rea), inspected at
`4f7b5fb6023ce2ec449561782d09e3c7e5ac7c7b` (MIT). This implementation owns its
store, formats, API and workflow and does not execute the REA CLI.
[ASAR format](https://github.com/electron/asar#format),
[Ghidra](https://github.com/NationalSecurityAgency/ghidra) and
[Temurin](https://adoptium.net/) are primary engine/format references. Dependency
licenses remain with their installed distributions. The common family SDK is
[HoardLink](https://github.com/Luissalet/HoardLink).
