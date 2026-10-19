# Saved artifact inventory comparisons

In Análisis, choose Artefactos · Inventario completo for each input. Then choose
Artefactos · Comparar inventarios guardados and select the saved reference and
candidate. The native API/MCP operation is `artifact.compare`, with
`reference_job_id` and `candidate_job_id` through the existing analysis tools.
Both inventories must belong to this project and retain their full JSON.

The comparison checks both saved document hashes before reading their complete
inventories. It does not open the original directories, archives or files.
Logical occurrence paths, content identities, kind/format/size, executable
metadata, other recorded metadata and graph relationships are compared. The
result retains manifest IDs, every recorded change and both source documents.
Changes are searchable by their full logical path and can become cited findings.

`retained_inputs` binds the comparison kernel's internal inventory evidence IDs
to the exact source JSON hashes and their recorded artifact/root identities.
Those internal IDs describe a carrier assembled from the already retained
inventory, not a new scan or an authenticated physical artifact. The normal
record view additionally provides the reference and candidate source citations.

An `unchanged` result concerns the recorded inventory dimensions. It does not
establish behavioral equivalence, execution coverage, a source's authenticity or
that an unobserved member is absent. Duplicate logical paths cannot be paired
automatically and remain unknown. Unavailable content and incomplete traversal
remain unknown or truncated even when the available bytes match.

If the installed reader cannot produce an inventory, its analysis retains the
engine error and cannot be selected as a completed input. A ZIP compression
method unsupported by the reader is an error, not an equal or empty inventory.
This operation does not add a new archive decoder or certify decryption.

The existing evidence transfer preserves the two inventory documents, comparison,
records and source references without copying the original files or replaying
analysis. Changes to either retained JSON invalidate its original receipt.

Verification uses original directories, a change after the byte preview range,
ZIP member executable metadata, distinct duplicate directory occurrences and
a synthetic encrypted-header marker whose member content remains unavailable.
The marker fixture is metadata-only, not ciphertext or a decryption test.
Unsupported compression is tested as a rejected input. Other format/platform
coverage follows the corresponding inventory reader and is not inferred from
these fixtures. Whole-function/binary matching and runtime behavior are separate
operations and remain outside this comparison's verdict.
