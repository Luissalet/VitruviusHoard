# Compiler metadata and inferred EVM interfaces

The existing `go.build`, `rust.dependencies` and `evm.interface` operations use
the normal Análisis form, native analysis MCP operations and retained record
browser. They read local files without executing them or contacting a chain.
There are no new MCP tools or operation names in this extension.

## Go and Rust carriers

Original positive fixtures cover PE32/PE32+, ELF32/64 and thin Mach-O32/64.
ELF and Mach-O cases include both byte orders. Go fixtures exercise both inline
and pointer-based build information, preserving version/module contents and
their exact original byte ranges. An independent ELF reader validates those
fixture headers and build-info sections. Rust fixtures preserve the auditable
package graph and source locations across the same carrier cases. These are
controlled format fixtures; they do not execute those images or establish that
every compiler/version emits these sections.

A real executable compiled with the installed Rust1.90.0 MSVC toolchain exposed
a missing Windows case: a readonly string uses `/rustc/<40-hex>\library\…`.
The reader now accepts forward/backslash prefixes and the mixed separator after
the hash. Its `file_offset` identifies the beginning of the recorded path,
not the first hash byte. Partial, oversized and non-hex hashes remain unknown.
The commit remains an **inferred string observation**, not producer authentication.
Absence of an auditable section remains null, rather than an empty dependency
graph. Standard rustc output in the fixture has no auditable section.

Universal/fat Mach-O remains explicitly unsupported without selecting a thin
slice. The positive cases above do not advertise universal-image support.
Native function/type recovery still uses the binary analysis engine; these
metadata readers do not reconstruct Go or Rust functions.

## EVM inference and original compiler fixture

The original `tests/fixtures/compiler/Measure.sol` is compiled with the pinned
development-only solc0.8.30 package. Its deployed bytecode is read as raw bytes
and a hex carrier. The compiler's independent method identifiers, ABI, storage
layout and metadata validate recovered selectors, arguments, stateful function
classification, storage slots/types/read/write selectors and compiler version.
Hashes bind both the selected original carrier and its decoded bytecode.

The `read(uint256)` fixture is declared `pure` by the compiler. Static analysis
can conservatively classify it as `view`. The reader preserves that inference
and states its limit; it does not substitute the compiler ABI as recovered
source. Each function carries `evidence_kind: "inferred"` and
`state_mutability_basis: "conservative-static-inference"`; storage records carry
the same evidence-kind marker. The overall analysis records unknown discovery
completeness and `runtime_execution: "not-performed"`. Original source names,
deployment identity and behavioral equivalence are not established.

MCP and the browser expose these same records and allow SHA-bound findings with
a separate interpretation. Evidence import/export preserves those records,
markers and source references as historical observations. The compiler fixture
tests do not deploy the contract or execute its bytecode.

No model service is needed. Solidity and Rust compilation here create controlled
test artifacts; the product's static analysis flow never launches the artifact.
