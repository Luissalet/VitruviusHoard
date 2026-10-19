# Offline QUIC qlog recordings

Choose **QUIC · Grabación qlog** in Análisis, or call
`theseus_analysis_start` with `operation: "network.qlog"`. The operation reads a
local artifact using the standard static workflow and never executes its producer
or opens a network connection. No external engine is required.

The reader supports qlog0.3 JSON trace arrays and JSON-SEQ with a header and
record-separated events. Other versions remain explicitly unsupported for
transport fact derivation; readable events still retain their original values.
JSON-SEQ can retain valid records around a malformed or truncated record, with
its exact byte location and diagnostic. An invalid header never promotes the
following event into a header. Duplicate keys, invalid UTF-8 and non-JSON numeric
constants are explicit errors, rather than silently overwritten values.

Sections include the header, trace metadata, complete event records, declared
losses, observed STREAM ranges, diagnostics and selection coverage. JSON
pointers identify events in ordinary JSON. Sequence events retain record ordinal,
byte offset and byte length in the original file. Numeric tokens are represented
as `{ "type": "json-number", "lexeme": "..." }`, preserving their exact
spelling, exponent and negative zero independently of JavaScript number precision.
Unknown fields remain in the retained records.

`trace_index`, `event_name` (case-sensitive substring), `offset` and `limit` select
event records. Omit `limit`, or use null, for all matching events. Trace metadata,
diagnostics and transport facts describe all valid recorded events before this
selection; coverage states both the total and matching/returned counts.

For valid `transport:packet_sent`/`packet_received` STREAM frames, ranges are
grouped by original trace index, direction and exact stream ID. The reader
unions overlapping ranges and reports unique bytes, frame-length sum, repeated
bytes, contributing event/frame locations and all declared FIN end offsets.
Invalid fields or values outside QUIC's variable-length integer range are kept
raw with a diagnostic and excluded from arithmetic. Conflicting FIN sizes remain
visible. Gaps, retransmitted ranges and FIN metadata never establish delivery or
HTTP-body completeness. This reader does not reconstruct packet or body bytes.
`recovery:packet_lost` is a producer's loss declaration, not an independently
verified network fact.

The default profile leaves clock unit/domain unknown. Explicitly selecting
`profile: "aioquic-json-0.3"` describes the selected producer convention of
milliseconds since the Unix epoch. It does not authenticate the producer,
identify the current process, or correlate the recording to a PCAP/runtime.

The existing record browser, **Usar registro como observación**, SHA-bound
findings and evidence export/import work unchanged. The original artifact hash
binds every record; exact saved analysis JSON and indexed records travel as
historical evidence. Original qlog file bodies are not embedded in the transfer.

## Sources and validation

The implementation is an original reader for the documented format, informed by
the pinned capability inventory and these primary specifications:

- [qlog main schema03, version0.3](https://datatracker.ietf.org/doc/html/draft-ietf-quic-qlog-main-schema-03).
- [aioquic producer source](https://aioquic.readthedocs.io/en/latest/_modules/aioquic/quic/logger.html).

Tests use the installed aioquic1.5.0 writer to emit original fixture events and
independently supplied JSON/sequence cases. They verify overlapping and separated
ranges, exact integers beyond 2^53, numeric lexemes, send/receive separation,
declared loss, inconsistent FINs, invalid protocol fields, malformed records,
trace-index preservation, paging, source citation and historical transfer. The
producer is a development-only dependency; the product reader uses Python's
standard library. These are format and recorded-range tests, not live QUIC,
HTTP/3, browser or application-equivalence certification.
