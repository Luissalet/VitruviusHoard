# Retained WebSocket streams

`browser.compare` reads the two selected, hash-bound observation/scenario JSON
recordings. Its `websocket_streams` section derives ordered streams from retained
`Network.webSocket*` events. It never connects, sends messages or replays actions.
Both input citations remain attached to each native record and historical transfer.

Each stream preserves creation/closure/error observations and ordered sent or
received messages. Message opcode, mask and all reported payload fields remain
literal. Capture-local request IDs, event indices and clocks remain readable in
the source and connection records; they are excluded from the stream comparison
key. IDs inside a message payload are data and are never normalized.

Connections with the same reported URL form an unordered collection of ordered
streams, with exact multiplicities. Opening A then B can match opening B then A;
reordering messages inside A, changing a payload or adding another B changes the
recorded projection. No pairing claims stable identity between individual
connections across the two captures. An unresolved URL remains unknown.

CDP's `WebSocketFrame` abstraction describes complete messages. The result does
not certify individual wire fragments, compression, network delivery or peer
receipt. Opcode 1 payloads use the reported UTF-8 string; other numeric opcodes
use the reported Base64 binary representation. Derived byte lengths and SHA-256
require successful decoding. Malformed representations retain their original
reported value and an unavailable-byte diagnostic. Literal payload representation
still participates in comparison even when decoding succeeds.

Missing creation/closure observations, incomplete recordings and journal gaps
remain qualified unknowns. Observing both boundaries still does not establish
complete connection history. Equal retained streams describe equal recorded
projections; empty streams never prove absent traffic. Old captures can derive
the same projection from their retained events without modifying their receipts
or pretending a historical projection already existed.

WebSocket events no longer create placeholder HTTP-body records. When an old
receipt already contains such a placeholder, saved comparison excludes that
placeholder while preserving actual HTTP requests, response bodies and their
hashes. Original JSON remains unchanged.

The native record browser searches URL names and exposes both connection lists,
counts, message order and qualified unknowns. A finding retains both sources.
Transferred records remain readable after the original browser/server close,
with no recreated runtime session.

Acceptance uses an original software-rendered Chromium page and an independent
loopback WebSocket server. The server records its own received messages and
fragments its replies deliberately. Tests exercise reversed connection order,
message/payload/direction/opcode/mask differences, Unicode, binary data,
multiplicity, unknown boundaries, old HTTP placeholders and historical transfer.
The test server uses the free `websockets` package; production collection keeps
the existing `websocket-client` CDP transport.

The complete coverage/stream composition passes 236 tests with 2 owned-emulator
opt-ins skipped in 484.15s, including the explicitly enabled Ghidra cases. The
stream/browser/scenario/Inspector/inventory area passes 40 tests in 154.68s.
Real stdio MCP checks same-stream collections, changed payloads and duplicate
connections against 9 independent server connections and 18 received messages.
It compares, saves a two-source finding and transfers records after the original
browser/server close. A fresh read-only stdio session confirms the exact imported
record and both hashes. The normal UI starts another saved comparison, reads its
counts/messages and both sources on desktop/mobile, with no frontend code change.

Protocol source: [official Network domain definition](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/pdl/domains/Network.pdl).
WebSocket comparison does not include Profiler counters, Electron IPC, WebMCP
tool execution or general behavior-equivalence claims.

On20 October, the unchanged stream implementation was rebased onto the reviewed
immutable-receipt fix717a296. Its full run recorded237 passed,2 skipped and
1 firmware failure in709.68s; this is not a green full suite. The firmware case
returned an absent Binwalk recording despite exit0, with its raw result retained.
All stream cases passed. A fresh native MCP session and the ordinary record
browser again read the exact imported stream and both hashes with no original
browser/server or recreated runtime session. No frontend source changed.
