# Firmware regions and extracted artifacts

Choose **Firmware · Regiones y entropía** or **Firmware · Extraer regiones y
archivos** in Análisis. The same `firmware.regions` and `firmware.extract`
operations use `theseus_analysis_start`, retained section/record tools and the
normal artifact browser. These operations do not execute the firmware.

Install free Binwalk or set `THESEUS_BINWALK`; optional additional archive
decoding uses installed 7-Zip or `THESEUS_7ZIP`. On this workstation Binwalk3.1.0
was compiled natively under `D:/LocalAI/tools/binwalk779/bin`; no Docker or WSL
service is needed. Discovery only checks local executable paths. Each actual
analysis retains engine paths, hashes, versions, commands, UTC times, exit codes
and stdout/stderr with exact base64 bytes. The product reader also records its
own source hash and Python runtime.

## Regions, selections and entropy

`offset` and `length` optionally select an interval of the original artifact.
The recording retains its full original identity, selected-byte hash and exact
root offsets. Binwalk's classification, confidence value, description and full
producer report are preserved; a signature is not an authenticated component
identity. Invalid/unknown extents remain gaps and are not used for carving.
`search_all` requests scanning all signature offsets rather than the engine's
normal selection behavior.

Entropy covers the complete selected input in windows (`entropy_window`, default
4096 bytes). Every bin records original offset, length and derived Shannon bits
per byte. Regions not classified by the scan are listed explicitly. High entropy
does not establish encryption or identify a codec.

## Extraction and source relationships

Each valid classified interval becomes a retained child artifact with its own
SHA-256 and original range. ZIP/TAR members and common compressed streams are
read with native libraries; additional formats use 7-Zip's content stream. Only
generated regular filenames are written. Original archive names, order,
duplicate names and link targets remain metadata. Archive directory names are
not turned into host paths and filesystem links/special entries are not created.
Unknown, encrypted, ambiguous or unsupported members retain an explicit gap and
their original carved bytes.

Decoded regular files can be scanned recursively. Traversal has no default depth
cap; an explicit `max_depth` produces a partial result with retained children
that can be selected for another analysis. Equal-content inputs reuse the
recorded observation rather than recursing through a content cycle. No arbitrary
file-count or output-byte ceiling is imposed.

Relations follow original → carved interval → decoded member → nested interval.
Nested offsets describe their immediate input. A compressed member's physical
root range stays unknown because decompression does not establish a linear
offset mapping. A command that streams a binary member records the output file's
hash and byte length; the actual bytes live in that linked artifact rather than
being duplicated into stdout text. Other command stdout/stderr remain complete.

Known regions being extracted successfully does not establish whole-image or
application completeness. `whole_image_completeness` remains unknown, including
when the known-region work finishes without gaps.

## Cancellation and restart

Completed observations are published as immutable checkpoints. This avoids a
Windows file-sharing race when recovery reads a snapshot while a writer publishes
the next one. Cancellation stops the job's owned host clients, retains completed
records and can freeze an unfinished output as explicitly partial bytes. The
private input capture is cleaned before the job's terminal state is published.

On restart, a still-matching orphan is identified by PID, creation time and the
exact structured-worker command for this job. Only that worker and its children
are stopped. Its latest recording is frozen and indexed without replaying any
command. A mismatched process is left alone and the cleanup outcome is recorded.
Later writes to the old recording/output cannot change the frozen partial file.

Evidence transfer retains the exact available recording, indexed observations,
citations and remapped parent/child relationships. Original firmware, carved
and decoded file bodies are excluded, as elsewhere in evidence transfer; imported
receipts are historical and do not resume extraction.

## Validation and limits

Original fixtures cover embedded gzip/XZ/bzip2 at independent known offsets,
selected intervals and entropy, native ZIP/TAR member names and duplicates,
link metadata, actual 7-Zip archives, nested parent chains, explicit depth
continuations, real cancellation and restart of an orphaned file worker.
Unit coverage separately verifies that an unfinished member prefix stays frozen
when a later writer changes the old file. Full tests, MCP and browser evidence
are recorded in SOURCE-COVERAGE.md.

Decoder support depends on installed clients and the selected format. This is
not certification of every vendor filesystem, encrypted image, damaged archive
or architecture. Retained unclassified ranges and gaps provide the next input;
they are not silently treated as recovered firmware.
