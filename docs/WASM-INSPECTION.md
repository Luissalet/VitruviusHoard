# Native WASM observations

The `wasm.artifact` operation reads a selected local core module with the bundled
WABT JavaScript library. It validates the module before producing decoded WAT.
Its optional `glue_paths` and `candidate_paths` arrays select additional local
files explicitly. The same operation is available through the static-analysis
catalogue, `theseus_analysis_start`, the HTTP API and the analysis form.

The observation records the actual library version, Node runtime, enabled
advertised features, package and implementation file identities, and the selected
module's path, SHA-256 and byte count. These identities describe the reader used;
they do not certify another WABT release or a target execution environment.
The engine enables all features advertised by its bundled reader for both reading
and validation, including threads and shared memories, memory64, multiple
memories, exception tags, SIMD and reference types. The reader always receives an
exact copy of the selected bytes, also when the caller passes a view into a larger
buffer.

`host_validation` records the separate verdict of `WebAssembly.validate` in the
Node runtime that runs the reader, with its Node and V8 versions. The module is
decoded and validated only; nothing is instantiated or executed.
`validators_agree` compares that verdict with the bundled reader's. A module that
the host accepts but the reader cannot decode, such as a typed reference parameter
outside the pinned reader, fails the inspection with `validation:
not-established` and `validators_agree: false`; it is not reported invalid and no
interface is invented for it. `validation: valid` remains the bundled reader's
claim.

`module_header` and `sections` preserve the selected bytes as base64, with each
section's original header, payload range, length and SHA-256. Section `start`
and `end` delimit the payload, with an exclusive end; the separate `header`
range precedes it. Concatenating the module header and every section header and
payload reconstructs a complete observation's original bytes. This also
preserves custom sections that do not appear in the decoded WAT.

Existing `wat`, `forms`, `definitions`, `imports`, `exports` and typed
`interface` fields remain available. `wat_sha256`, `wat_bytes` and
`wat_representation` identify the UTF-8 decoded representation. WAT and generated
names do not establish original source names or binary round-trip identity.
Unsupported typed forms remain partial facts with explicit issues.

The first candidate is the selected module; further candidates retain the
caller's order and file identities without claiming those files are valid WASM.
JavaScript glue observations retain their file identities, parser status,
issues, and visible string or expression-free template literals ending in
`.wasm`, including literals in directive positions. References have source line
and column coordinates. Relative paths are associated with explicitly selected
candidates when their resolved paths match. Otherwise a basename association
retains every matching selected candidate, including ambiguity. Missing matches
remain unresolved. URLs, inferred paths, imports and modules are never fetched,
followed, instantiated or executed. These are literal associations, not loading
or data-flow evidence. `glue_complete` means every selected file was visited;
each file's `parse_status` still determines whether its reference facts are
complete, partial or unavailable.

## Failure, cancellation and restart

The worker publishes atomic observation prefixes separately from its completed
analysis document. A failed validation has a nonzero exit and no completed
analysis. Its last prefix can still contain the original identity, reader
profile, section bytes, failure phase and diagnostic. Missing selected glue or
candidates similarly preserve facts observed before the read failed. A prefix
does not turn a failed or cancelled job into a successful inspection.

Cancellation stops the owned reader and retains its last published prefix.
After an owner restart, recovery uses the recorded PID, actual process creation
time and exact command before stopping that worker. It freezes the existing
observation bytes and indexes them without reopening the original module or
relaunching the reader. Missing or contradictory worker identity is reported
without stopping another process. Historical jobs with incomplete recovery
metadata remain interrupted with their recovery diagnostic.

Windows publication retries only replacement of the same already written
prefix when a concurrent reader temporarily denies delete sharing. It never
repeats the analysis. Persistent denial leaves the previous prefix intact and
reports the publication error.

Retained documents and their indexed sections are downloadable and portable
through the normal evidence export/import operations, including observations
from failed, cancelled or interrupted analyses. Engine diagnostics and original
job state remain separate from observation completeness.

## Retained interface comparison

`wasm.compare_interfaces` reads the two selected retained analysis documents,
with `query.scope` set to `imports`, `exports` or `both`. It does not reopen the
original artifacts. `retained_inputs` binds both document hashes and byte
counts to their original artifact identities and recorded completion status.
Historical documents without an internal artifact identity report that identity
as unavailable; an internal identity contradicting the document's bound
artifact SHA-256 is rejected.

Comparison groups preserve import module and name separately, interface kind,
all repeated occurrences and producer-owned typed signatures. Repeated imports of
one module and name are compared as their ordered occurrences, because the order
defines their indices: the same kinds and signatures in the same order are
unchanged, any other sequence is changed, and `occurrences` reports both counts.
Missing typed facts, partial interfaces and unresolved signatures yield unknown
results instead of proving equality or absence. Empty partial interfaces keep
partial coverage even when there are no rows. An observed complete empty module
has a complete empty interface. Interface equality describes declared facts
within the retained inputs, not successful linking or behavioral equivalence.

## Verification and provenance

`theseus_tests/test_wasm_inspection.py` exercises original section bytes, an
independent host-validation oracle, actual reader identities, glue coordinates,
ambiguous candidates, malformed glue, retained comparisons after original
retirement, failed-reader transfer, actual worker cancellation and restart,
process-identity mismatch, startup recovery diagnostics and real Windows file
sharing contention. `theseus_tests/test_wasm_features.py` encodes its modules
by hand from the binary format and checks them against the host validator in a
separate process: exact function, multi-value, SIMD, table, shared and 64-bit
memory, multiple-memory, global and tag signatures with their indices; invalid
modules rejected while reading and while validating; a host-valid module outside
the reader; a view into a larger buffer; repeated imports and changed limits,
sharing and mutability in retained comparisons. The broader native-format and
retained-extension tests cover existing typed interface behavior. Area tests
alone do not establish final installed acceptance or independent review.

The incorporated MIT WAT/interface and JavaScript parser modules retain their
licence and pinned provenance in `software_native/engine/NOTICE.md`,
`LICENSE-MANAGED-CORE` and `PROVENANCE.json`. Observation envelopes, original
section-byte preservation, worker recovery and product persistence are maintained
inside Vitruvius. No reference CLI or application is needed at runtime.
