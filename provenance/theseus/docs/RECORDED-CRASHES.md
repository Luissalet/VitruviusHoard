# Recorded ELF crashes

In Análisis, select **Fallos · Volcado ELF guardado** and an original core file.
The native operation is `crash.recording`, through `theseus_analysis_start`.
Its saved sections use the existing record browser, citations, HTTP API and
portable evidence transfer. No target, debugger attach or current host-file
resolution is performed. The reader works on Windows as well as Linux.

Supported profiles are ELF64 little-endian Linux/System V ET_CORE for x86_64
and ARM64. Results preserve program headers, exact note owner/descriptor bytes
and offsets, note padding, every supported PRSTATUS thread/register, SIGINFO,
NT_FILE module maps and AUXV pairs. Extended program-header counts are supported.
Unknown note owners retain their bytes; a display name cannot select the Linux
ABI. Unsupported containers and truncated/reversed ranges fail explicitly.

The optional parameters are:

```json
{
  "memory_reads": [{"address": "0x7000", "bytes": 16}],
  "frame_limit": 1
}
```

Memory observations split the requested range into recorded, unrecorded or
ambiguous chunks. Recorded bytes include their original file offsets. Undumped
memory is never filled with zeros or read from the current machine. Overlapping
PT_LOAD ranges remain ambiguous. Overlapping note segments cannot establish
unique thread identities and are rejected.

Frame-pointer chains are **candidates**, with exact recorded pointer/return
bytes and matching historical module offset candidates. They are not verified
unwinding: optimized code, omitted frame pointers and pointer authentication can
invalidate the interpretation. Cycles, unavailable memory and an explicit
`frame_limit` are visible records. Omit that limit or use null to follow the full
available finite chain. Historical PID/pathnames never establish current identity.
SIGINFO is not assigned to a thread; only SIGSEGV codes 1/2 interpret its fault
address union. No current executable pairing or GDB/pwndbg enrichment is claimed.

The format implementation belongs to Theseus and uses Python's struct/file
reader; it does not invoke the reference CLI or its Python decoder. The ABI was
checked against the incorporated MIT contract inventory and Linux's
[x86 ELF register order](https://github.com/torvalds/linux/blob/master/arch/x86/include/asm/elf.h)
and [ARM64 register structure](https://github.com/torvalds/linux/blob/master/arch/arm64/include/uapi/asm/ptrace.h).
Those headers were consulted as format documentation, not copied into the product.

Acceptance uses original synthetic format recordings for both architectures,
independently parsed with pyelftools 0.33, plus corrupt/truncated descriptors,
unknown owners, extended counts, overlap, frame cycles, explicit selections and
portable evidence import. These are controlled format fixtures, not a claim of
a captured production crash. Real stdio MCP and normal browser start/read flows
exercise the worker and retained records; original file hashes remain unchanged.
Install `requirements-dev.txt` for the independent format-verification tests;
the product reader needs no additional runtime package.
