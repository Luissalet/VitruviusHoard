# Static Swift dispatch metadata

`apple.dispatch`, available in **Análisis → Apple · Metadatos Objective-C y
Swift** and the existing analysis API/MCP, reads supported Swift metadata from
64-bit little-endian ARM64 and x86_64 Mach-O bytes. It never loads an Apple
runtime or executes the inspected image.

`swift_conformances` retains type/protocol names, descriptor and witness-table
locations, decode status and source evidence. `swift_dispatch_slots` records
static witness-table slots and non-generic, non-resilient class vtable method
descriptors. A class slot index is a metadata word offset, not a source method
ordinal. An implementation address identifies an encoded static target; it
does not establish that a call occurred.

Signed relative pointers, including supported indirectable protocol/type
references, retain their field, displacement, target and resolution status in
`relative_pointers`. Evidence locations use the original file's offsets: a
selected slice inside a FAT container includes its container offset. Explicit
`architecture` selects a slice. Supported FAT32/FAT64 tables may use either
byte order; each inspected thin slice remains little-endian 64-bit.

Async, non-function, nil, external or unmapped slots retain a partial status and
unknown implementation. Generic, conditional, resilient or unresolved witness
metadata is not promoted to a decoded static table. Invalid UTF-8 names,
unmapped relative references and vtable bounds produce explicit per-facet decode
gaps. Other successfully decoded records remain available. The optional caller
`max_records` selects a recording budget and reports incomplete coverage.

The existing section/page/record browser supports exact record citations and
portable evidence export/import. Imported records retain their historical
analysis JSON, offsets and source hashes. Original image bodies are not embedded
in evidence transfer.

## Validation boundary

`tests/swift_fixture.py` constructs original inert format bytes from the public
[Swift metadata declarations](https://github.com/swiftlang/swift/blob/main/include/swift/ABI/Metadata.h)
and [ABI documentation](https://github.com/swiftlang/swift/blob/main/docs/ABI/TypeMetadata.rst).
These are synthetic ABI fixtures, not compiler output or runnable applications.
The tests independently read pointer words/displacements with Python `struct`,
verify exact descriptor/slot offsets and source hashes, and exercise both
architectures, direct/indirect pointers, both FAT widths/byte orders, malformed
and unsupported cases, citations and transfer. Existing cross-compiled
Objective-C fixtures remain separate real-compiler regressions.

This validates the listed byte layouts. It does not certify arbitrary Swift
compiler versions, generic metadata instantiation, complete type/reflection or
symbol recovery, source method names, demangling, actual dispatch, signatures,
macOS execution or live UI/call observation. Those broader cases remain open in
`SOURCE-COVERAGE.md`.
