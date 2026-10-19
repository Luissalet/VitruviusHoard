# Binary navigation, call observations and offline captures

The Binarios section discovers the native session catalogue, opens an original
artifact or retained Ghidra project and executes selected operations. Every
call produces an individually readable retained analysis. The existing MCP
binary tools use this same session and background-job contract.

`current_document`, `current_address`, `current_procedure`, `goto_address`,
`next_address` and `prev_address` provide a headless selection context. Moving
by code unit uses Ghidra's mapped listing; an exhausted direction returns null.
The selected address is saved in the analysis project and survives reopening.

`comment`/`set_comment` use PRE comments, and `inline_comment`/`set_inline_comment`
use EOL comments. Empty text removes that comment. `set_bookmark`,
`list_bookmarks` and `unset_bookmark` retain typed/category annotations in the
native project. The default bookmark type/category are Note/Theseus. Source
binary bytes are preserved throughout these operations.

`get_call_graph` retains function nodes and resolved static call edges, including
external destinations. `trace_call_path` accepts exact function names/addresses
in `from_procedure` and `to_procedure`, returning the shortest observed path.
An optional `max_depth` limits traversal and reports whether that boundary was
reached. A missing static path does not establish runtime unreachability.
`batch_decompile` returns each selected function dossier or its individual error;
one absent selector does not discard the other observations. `inspect_native_api`
reads the native API facet of the decompiled function.

## Packet recordings

Install a free TShark distribution or set `THESEUS_TSHARK` to its executable.
Capinfos is discovered beside it, from PATH or `THESEUS_CAPINFOS`. The normal
catalogue reports a missing decoder before offering to run capture operations.
Theseus does not install a packet capture driver or start live acquisition.

`capture.fields` discovers registered fields or protocols. Use `kind`, an exact
`protocol` abbreviation for fields, a literal `match`, `offset` and `limit`.
No limit requests all matches. A tool registration is separate from a field
actually observed in the selected capture.

`capture.packets` reads a job-owned snapshot of PCAP/PCAPNG or another format
supported by the installed decoder. It retains TShark's protocol trees or
selected `fields`, repeated values, warnings, engine identity, original source
hash and capinfos metadata from the same snapshot. It supports `display_filter`,
`decode_as` rules, `two_pass` reassembly, input `packet_limit`, optional `raw`
bytes and output `offset`/`limit`. Output paging happens after dissection and
does not shorten two-pass processing. The private input is removed after use.

QUIC/HTTP3 decoding depends on the installed dissectors and available recorded
decryption material. No key recovery or live device traffic is inferred. qlog
is a separate structured recording format and is not accepted as PCAP input.

## PE resources

`pe.resources` reads the type/name/language directory tree with original file
offsets and RVA, UTF-16 name identities, payload sizes/digests and icon-group
relationships. It does not load or execute the PE. Byte excerpts at recorded
offsets can be saved as findings.

## Real-engine checks

Native fixtures are compiled locally with the installed C/resource compiler.
Checks cover positive/absent/depth-limited calls, per-function batch failure,
annotation/navigation persistence on reopening, exact source-byte preservation,
and the existing changed-constant/relocation byte oracle. PCAP and PCAPNG fixtures
contain an original DNS response with two repeated address records; real TShark
checks both values, false filters, paging, field and protocol discovery. A real
compiled RCDATA fixture verifies resource language and exact payload offsets.

The composed suite passes 66 tests, including both real Ghidra integration
tests (no opt-in skips). Stdio MCP35 exercises static36 and binary49 catalogues,
real Ghidra calls, PCAPNG and PE resources, then closes its session. Browser
verification reopens that native project, submits a zero-depth path query as a
number, reads its true depth-limit record and closes the session again.
