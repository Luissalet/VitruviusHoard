# Reader and native-session scope

The reviewed source is `b5b5f0d74562bbc54dfc4193c8100962af326833`.
Production code is identical to `8eafeb6`; the later changes update the
obsolete catalogue-count test and mount the opt-in design browser test at its
current `/design` path. No product assertion was weakened.
Source review does not certify installation or publication. The coverage ledger
keeps those stages separate and keeps the overall completion claim false.

| Flow | Verified observations | Limits |
| --- | --- | --- |
| Go/Rust | Original multi-platform compiler metadata, module replacements and auditable dependencies; universal slices retain their own offsets and identities | Metadata does not authenticate the producer or recover all types/functions; Go pointer encodings use synthetic fixtures |
| SQLite | Independent SQLite queries, schema/FTS5, WAL capture, exact BLOB/int64/text values | Selected read-only observations do not establish application semantics |
| EVM | Original solc optimization variants, selectors, storage facts and CBOR metadata | Conservative bytecode argument/mutability inference; no blockchain execution |
| Firmware | Actual encoded images, signature ranges, extracted byte identities and ISO/archive readers | Unsupported extractors and partial/interrupted regions remain gaps |
| Managed/PE | Original assemblies and resource builds; independent tables, signatures, full CIL opcode/exception data, P/Invoke and resource leaves | Declarations do not prove runtime binding; resource payloads remain raw bytes |
| Mach-O | Independent original arm64/x86_64/universal metadata and bundle-scoped dylib resolution | Missing/system dependencies and signature authentication remain unknown |
| Artifacts | Original directory/archive inventory, exact member bytes and occurrence-aware comparisons | Duplicate or encrypted occurrences retain ambiguity; no behavioral equivalence |
| Plist/keyed archives | XML/binary values, object tables, roots and references against independent construction | Boolean CF$UID is a dictionary; expansion above 1,000,000 values or 512 levels fails explicitly |
| Packet captures | Original packet endpoints, quoted/tunnel boundaries, answer-only DNS and multiple messages, separated URI observations | Selected packet bounds stay partial; no recovery of encrypted or uncaptured traffic |
| Flutter/Dart | APK engine build-id, actual Dart AOT ELF, split/unified layouts, feature string and defined symbol extents | Synthetic engine build-id fixture; no recovered Dart object graph, complete string pool or app behavior. Tiny/missing/undefined symbols remain partial |
| Symbol demangling | Official engine via stdin, literal inputs retained, matched classification with complete diagnostic streams | Unrecognized symbols stay unchanged; no argv expansion |
| Private binary query | Supported read-only command grammar, numeric formats, raw output, timeout/cancellation on a selected private artifact | No live debugger or Cutter session is certified by this backend |
| Native sessions | Original ELF/PE/AArch64 container/disassembly oracles, navigation, annotations, bytes/mappings, references, graphs, typed dossiers and selected call paths | Computed destinations remain unresolved; rewritten memory has no original file offset unless bytes match. Installed objdump lacks AArch64, checked separately through instruction words |

Use the normal project/artifact analysis picker for retained readers, the native
session controls for Ghidra and the symbol form for demangling. Results retain
reader diagnostics, artifact identities, coverage states and exact saved JSON.
Export/import preserves saved evidence after the synthetic originals are retired.
Original files and live analysis databases are not transferred as evidence.

The source acceptance includes actual stdio MCP and the private normal browser
flow. Catalogue counts are 72 static, 52 binary-session and 40 runtime operations,
behind 40 Theseus and 125 owner MCP tools; those counts are not semantic parity.
Cutter sessions, arbitrary binary-command execution, GDB/Rizin debugger sessions, broader feature/UI tracing and the
remaining individually marked ledger contracts stay open. Platform-only native
UI/call observations retain their explicit platform requirements.

Reviewed revisions: 1100r3, 1102r2, 1104r2, 1106r3, 1107r1, 1109r3,
1110r1, 1115r2, 1118r2, 1119r4, 1122r2, 1123r2, 1132r1, 1133r2,
1135r1, 1145r1, 1150r2 and 1158r1. The last four cover browser-test cleanup,
previously omitted test-only commits, the obsolete catalogue-count expectation
and the opt-in design test mount.
Historical failed checks are preserved separately.
See [batch acceptance](../tasks/submission-reader-batch.md).
