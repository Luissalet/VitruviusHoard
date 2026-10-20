# GNU binary inspection

In Inspección, **Lectores instalados → GNU objdump · Formatos binarios** explicitly
queries the selected free GNU reader's version and advertised BFD targets before
choosing an artifact or creating a project. The report records selected paths,
selection sources, executable identities, exact output bytes and diagnostics.
Its JSON download retains both queries and any identity change between them.
Advertised targets describe the reader; they do not certify a particular file.

For an artifact, choose **Análisis → Binarios · Inspección GNU**. Its `facet` is
`file_headers`, `section_headers`, `symbols`, `relocations`, `dwarf`, `disassemble`
or `disassemble_all`. The same operation is `theseus_analysis_start` with
`operation: "binary.objdump"`; subjectless discovery uses
`theseus_client_inspect` with `family: "objdump"`. Normal analysis records,
citations and complete JSON downloads remain available.

Configure `THESEUS_OBJDUMP` or install GNU objdump on PATH. This Windows setup
also discovers the separately installed free reader under `tools/binutils1076`.
Catalog discovery checks availability without invoking it. Each explicit query
retains its selected executable identity and the owned utility process's exact
arguments, raw stdout/stderr, text with invalid UTF-8 replacement flags, exit
status, stream closure and completed/unknown state. Nonzero exit diagnostics
remain observations rather than fabricated empty inventories. Full collected
streams are retained, without a delivery cap; an interrupted stream remains a
partial observation even when its current bytes are readable.
Reader and artifact identities retain hashes, sizes and metadata, without
duplicating their binary bodies. Normal process-capture file observations keep
their existing content-preserving default; this reader selects identity-only
file observations while retaining every stdout/stderr byte.
Observed POSIX signals and unobserved exit codes keep completion unknown even
when all pipe bytes reached EOF; the original return code remains in the process
observation and a signal name is reported separately when available.

The product invokes the utility reader and never executes the selected artifact.
Before/after artifact hashes identify observed endpoint states; they cannot rule
out transient concurrent changes. Reader identity does not bind every dynamic
library or ambient input. Its raw output is authoritative, with no promise of a
stable normalized GNU text format. BFD support belongs to the selected GNU build;
other disassemblers do not stand in for this reader's advertised target list.

DWARF leaves debug links unfollowed by default. Set `follow_debug_links: true`
explicitly for the DWARF facet to permit them; external debug file identities
remain outside the recorded artifact identity. `DEBUGINFOD_URLS` is cleared and
GNU's do-not-use-debuginfod option is selected for that facet. The option is
recorded but has no effect on non-DWARF facets.

The existing owned-process recorder retains a prefix while the reader runs.
Cancel stops only that job's utility processes. Recovery validates saved process
identities, freezes retained bytes and never repeats a reader invocation. Evidence
transfer preserves completed or partial JSON after original files are removed;
reading imported analysis records does not reopen the utility or original file.
Brief Windows sharing conflicts retry publication of the same checkpoint bytes;
persistent publication denials remain errors and retain the previous prefix.

GNU binutils and its required runtime libraries are separate free installed tools,
with their original licenses and distribution provenance retained alongside them.
No reference application, model service or GPU is involved in these inspections.
