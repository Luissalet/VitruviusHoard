# Incorporated analysis code

The selected managed metadata/CIL, Go/Rust container/build metadata, Apple
serialized objects/Mach-O, Electron fuse, Dart/ELF and WAT interface readers in
`src/` are incorporated from
morluto/rea at `4f7b5fb6023ce2ec449561782d09e3c7e5ac7c7b`, copyright 2026 morluto,
under the MIT license in `LICENSE-MANAGED-CORE`. `PROVENANCE.json` identifies each
original module and its source SHA-256.

This is a detached implementation maintained inside Theseus. It does not run the
reference CLI or MCP server, install that application, fetch its repository at
runtime or depend on its future compatibility. The worker entry point, process
contract, product persistence, API/MCP and UI belong to Theseus.

Native changes add complete CIL instruction listings with original byte ranges
and file offsets, alongside the original filtered anchors; metadata projection
does not stop at the reference implementation's arbitrary 64 MiB quota. Invalid
physical bounds and malformed metadata are still diagnosed. Zod is a normal
installed library dependency; esbuild and TypeScript are local build tools.

Additional native adaptations expose preserved WAT forms for record-level
inspection, use explicit Node TextDecoder types and URL bases, and retain the
trailing-zlib-data feature probe with Node 22-compatible types. The native
dispatcher separates managed PE parsing from other formats and unwraps Go's
module framing before projecting records. Serialized NIB decoding uses the
actual artifact bounds rather than a fixed projection quota. Some incorporated
readers retain explicit format/resource limits, reported in their diagnostics;
those are not claims of unlimited format coverage.

WABT and EVMole are installed free local analysis libraries. Their compiled
engines run inside the native worker, without their CLI/MCP, a hosted API,
target execution or a chain connection. Their licenses remain in node_modules.
The build excludes dependency declaration checking because the installed saxes
declarations contain unconstrained generic parameters; native source remains
strictly type-checked.

Selected JavaScript/TypeScript parsing, module/application reconstruction and
semantic query/feature traversal implementations are also incorporated under
the same MIT license. The source-analysis port is maintained as a direct native
parser inside Theseus's already isolated job process; it does not launch the
reference application's entrypoint or source-worker protocol. Retained graphs
can be queried after originals become unavailable. Derived receipts bind the
input analysis document hash and keep the original artifact identity.

The selected headless Java analysis scripts and optional NativeAOT source are
listed in the same provenance manifest. Theseus owns their session transport,
process lifetime and persisted per-call results. Native adaptations support
retained project mutations on Windows, save a fresh import before opening a
mutable session, and preserve complete high-p-code observations. They do not
inherit the reference application's Windows-only artificial mutation gate.
The byte-evidence operation and comparison are original product functionality:
exact defined referenced data accompanies decoder operand masks, so normalizing
addresses cannot silently erase a changed floating-point constant. Optional
NativeAOT extension code is incorporated but is not yet wired or advertised as
available by the product.

Pure managed-member, JavaScript application-version and export-shape comparison
algorithms are incorporated with the same historical MIT provenance. Theseus
adds its own paired retained-input contract, exact document hash binding,
per-side artifact attribution, record indexing and normal UI/MCP operations.
The managed comparison algorithm name is maintained under the product's name.

Additional artifact inventory/extraction, mobile application projection,
Interface Builder, Apple library resolution and managed reconstruction code is
incorporated under the same historical MIT provenance. ArtifactExtraction's
input format type now includes the inventory's directory format. Source-to-bundle
comparison groups multiple graph roles at one exact physical location before
classifying duplicate/split sources, while retaining their node identities.
The original upstream digests remain recorded in PROVENANCE.json.

Theseus owns its directory identity/excerpt contract, SQLite capture/query
worker, execution-free Babel recovery and typed WebAssembly comparison adapter.
@babel/generator is an installed free local library with its package license.

The native Ghidra bridge additionally maintains headless selection context,
PRE/EOL comments and typed bookmarks in retained projects, and exposes static
call graph/path observations, per-function batch decompilation and API facets.
The PE resource parser is now exposed through the native analysis catalogue.
TShark/capinfos remain independently installed free generic analysis engines;
Theseus owns their offline snapshot, field selection, retained results and UI.

NativeValueTrace and Apple dispatch/fixup readers are incorporated under the
same MIT provenance. Theseus owns the stdio composition with its retained
Ghidra session, cancellation of both worker families, source observation storage
and record navigation. Full traversal replaces arbitrary hard maxima while
explicit caller limits and unknown/truncated results remain visible. Python
plist and macOS codesign observations are product-owned workers.

The incorporated managed/native verification algorithm is now exposed with the
product algorithm identifier. Theseus owns retained document/hash binding, native
Evidence creation, duplicate observation provenance and source record navigation.
A static name/module correspondence is not runtime binding or body equivalence.

TheseusAndroidBridge.java is an original product-owned reader against the
separately installed JADX library API, with no dependency on the reference
application's Android transport/session/MCP server. JADX and Apktool retain
their Apache-2.0 licenses in their installed distributions. Android SDK tools
build tools are fixture compilers only; they are not needed by the static
product reader. The separate explicit runtime worker uses installed platform-tools.

Go/Rust carrier fixtures and Solidity/Rust compiler fixture sources are original
tests. The incorporated Rust reader now recognizes Windows and mixed path
separators while retaining inferred string provenance and exact path offsets.
EVM interface composition marks function/storage records as static inferences;
the separately installed development-only Solidity compiler supplies independent
fixture ABI, selector and storage facts, not recovered source truth.

Firmware orchestration, immutable recording checkpoints and source relationship
publication are original Python product code. Installed generic Binwalk (MIT)
and 7-Zip retain their licenses in their separate distributions. No firmware
transport, CLI/MCP or server from the reference application is invoked.

Runtime instrumentation uses the separately installed generic Frida SDK
(wxWindows Library Licence3.1, with its bundled dependency notices). The Python
session lifecycle, journal/snapshot publication and normal Theseus UI/API/MCP
integration are original product code. No reference application's Frida CLI,
MCP contracts or session implementation is executed or imported.

V8 Inspector capture and saved static/runtime source reconciliation are original
Python product code. The separately installed generic websocket-client1.9.0
transport retains its Apache-2.0 license and distribution notices. No reference
application's Inspector runtime or CLI/MCP is executed or imported.

Page DOM/listener/network/screenshot composition, selected-protocol JSONL
journals, saved-capture projections and source-bound PNG delivery are original
product code over the same generic free CDP transport. Chromium/Playwright is
an independently installed test engine, not a reference-app runtime dependency.
