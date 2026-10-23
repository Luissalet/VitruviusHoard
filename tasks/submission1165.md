# Reuse imported member observations

Comparison and reconstruction previously rejected imported managed.members jobs
although their retained documents remained readable. Both operations now accept
finished and imported sources, preserving project, artifact, operation, document
hash and exact method locks. Both are declared retained-only: their normal API,
MCP and UI flows do not inspect the original assembly's availability or bytes.
The UI consumes the same catalogue source states without another filter list.

Two original C# assemblies return17 and19 in Changed and7 in Stable. Their
recorded CIL is checked against the actual original file bytes and expected
ldc.i4.s/ret instructions, without executing either assembly. After evidence
import and parking both originals, comparison identifies the change and stable
method; reconstruction preserves Unicode/CRLF and all three supported kinds.
Second transfers preserve complete documents and their source links. Deliberate
token/signature/IL/text-hash errors and changed source/candidate documents still
fail. Foreign projects, wrong operations and failed/cancelled sources remain
rejected before creating work. An original-path availability trap covers the
successful retained workflows and transfers.

Validation: codex-managed1165-area-b.xml has20PASS,0SKIP/FAIL/ERROR in61.251s,
including existing retained comparisons and extensions. All pytest used the
mandatory wrapper with a fresh basetemp. The first RED run retained four HTTP400
failures; a separate one-case diagnostic run records the exact completed-source
rejection. The first corrected run had9PASS/1FAIL because its test expected a
shorter error string; the product correctly rejected the changed document.
That failed test run remains preserved, and the corrected oracle distinguishes
the exact reference/candidate diagnostics.

Primary contracts at4f7b5fb were read without copying/executing reference code:
managedWorkflowToolContracts3fcdbae9, managedMemberComparison4f58590a and
managedReconstruction9600166a. The original research1163 and its counterexamples
remain available. This change does not alter the CIL comparison/reconstruction
algorithms, execute the target, or complete graph task1166/native verification.
Build-local tokens and inferred reconstruction do not prove target equivalence.

Actual private MCP/UI, independent review, installed acceptance and publication
are pending. W3/main b959769 is the previous reviewed release. Theseus207 remains
incomplete; no ledger acceptance is promoted by this source change alone.
