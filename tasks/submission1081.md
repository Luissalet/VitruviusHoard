# WebAssembly inspection and comparison

Delivery 1081 is independently reviewed at exact tip `175e25ed014cf8da637941d91d0a99e5ca99db00`. See
[WASM inspection](../docs/WASM-INSPECTION.md) for the observation contract.

The reader validates with the same advertised features it reads with and always
receives an exact copy of the selected bytes. Before this change, validation ran
with the reader's defaults, so valid shared, 64-bit and multiple memories were
rejected, and a view into a larger buffer exposed unrelated bytes to the reader.
Each observation also records the host runtime's `WebAssembly.validate` verdict
and whether both validators agree. A module the host accepts and the pinned
reader cannot decode fails with that disagreement recorded; it is neither called
invalid nor given an invented interface. Repeated imports are compared as ordered
occurrences.

`theseus_tests/test_wasm_features.py` encodes its modules by hand from the binary
format and checks every case against the host validator in a separate process.
Revision 1 received changes: a module the reader validates and the host
rejects finished with a job summary that only said valid. Revision 2 adds the
agreement and the host verdict to the summary, warns about disagreements in the
analysis view, records the host verdict before the section walk, resolves
Windows drive literals in glue as local paths and keeps the reader error when the
final prefix cannot be published. The independent review repeated 49 focused
tests and its own 17 hand-encoded modules against the host validator.

The author full suite at the reviewed tip passed 969 of 974 tests with five
optional skips (Ghidra enabled); `babel_tests` passed 183 tests with its
manifest test excluded (task 1097). Actual stdio MCP and the normal UI ran against
private owners: feature, invalid, disagreement and comparison observations, both
disagreement warnings, transfer of exact documents after retiring the originals,
and retained readback. Failed attempts and their
continuations remain in the research receipts.
