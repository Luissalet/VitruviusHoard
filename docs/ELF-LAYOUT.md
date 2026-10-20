# ELF layout evidence

Choose **ELF · Secciones, símbolos y relocaciones** in Inspección → Análisis,
or use `theseus_analysis_start` with `operation: "binary.layout"`, the selected
project/artifact IDs and empty parameters. The operation reads a file without
loading or executing it. Its supported scope is ELF64, little-endian, x86-64,
ET_REL/ET_EXEC/ET_DYN. Other formats produce an explicit failed receipt; existing
PE, Mach-O, WebAssembly and core-recording operations remain available separately.

Sections and segments retain producer order, indices, exact header ranges,
addresses, flags and file-backing meaning. Symbol tables retain their linked
string tables, original entry locations and extended section indices. Values
and offsets use hexadecimal strings; signed RELA addends use decimal strings.
REL implicit addends are unobserved. Names retain original bytes and ranges;
UTF-8 replacement is used only for display. Missing string mappings remain
unknown rather than an invented empty name.

REL/RELA targets distinguish object section offsets from linked virtual
addresses. A zero symbol reference means a zero symbol value. RELR preserves
the complete original table alongside ordered derived offsets; it supplies
neither individual entry source ranges nor invented addends. Invalid ranges,
table strides, positive symbol references and RELR address overflows fail the
analysis instead of publishing an apparently complete empty inventory.

`original_records` retains base64 bytes and hashes for complete file-backed
section bodies, headers, symbols, relocations, dynamic tables and interpreter
records. Original section and symbol entry bytes preserve unrecognized values
and extension bytes. These records use the normal search, record, finding,
download and evidence-transfer flows. Transferring the completed analysis keeps
its document bytes and source identity after the selected file is removed;
running a new file analysis still requires the selected file.

Dependencies and interpreters are declared names. Sectionless dynamic string
tables require an unambiguous file-backed LOAD mapping. Runtime library paths
and load base remain unknown. GOT entries are observed GLOB_DAT/JUMP_SLOT
relocation addresses with linked symbol names. No unproven PLT stub is guessed;
the PLT convenience map can be empty, and both maps and the relocation inventory
retain unknown completeness.

Mitigations are inferred indicators from headers, dynamic tags and symbol names.
ET_DYN does not prove a PIE executable. GNU_STACK flags describe an indicator;
an absent or conflicting header keeps NX unknown. Canary symbols do not prove
coverage of every function, and RELRO/binding flags do not demonstrate runtime
enforcement. These static facts do not establish behavior or equivalence.

Format references: [ELF sections](https://gabi.xinuos.com/elf/03-sheader.html),
[relocations and RELR](https://gabi.xinuos.com/elf/06-reloc.html), and
[dynamic tables](https://gabi.xinuos.com/elf/08-dynamic.html).
