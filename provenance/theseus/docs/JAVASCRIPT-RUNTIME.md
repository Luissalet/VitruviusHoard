# JavaScript Inspector observations and saved-source comparison

In Ejecuciones, select JavaScript destinations, enter the explicit HTTP(S)
Inspector endpoint, and inspect its recorded targets. Discovery does not attach
or start an application. Select the exact current target ID for observation.
The product connects to that target's reported WebSocket on the selected
endpoint. Discovery metadata and URLs do not authenticate a physical executable.

`javascript.observe` enables Runtime and Debugger metadata notifications for a
finite observation window. It records execution contexts and parsed scripts,
protocol messages, UTC collection times and client diagnostics. It never sends
evaluate, pause, resume or target-close commands. Other event kinds are excluded
and counted. A default capture contains metadata only, not script texts.

The separate “Leer también los textos de los scripts” choice sends
`Debugger.getScriptSource` for the scripts inventoried at the end of the window.
The result explicitly identifies this mode. Captured text preserves characters
and CRLF, with UTF-8 bytes/SHA-256 and UTF-16 code-unit counts. Original source
encoding, browser transformations and a generated wrapper may differ from a
file's bytes. Failed source reads stay unavailable. Scripts first seen during
source collection remain recorded but are not recursively chased. The server
retains derived source artifacts with recording links and generated regular
filenames, without following reported paths or fetching source-map URLs.

Cancellation closes only the observation client. Immutable checkpoints retain
the collected prefix; restart verifies and stops its own orphan observer when
possible, freezes the available JSON, and never reconnects or repeats commands.
The selected target is not terminated. Its final state and any events outside
the observed window remain unknown. Evidence transfer preserves these historical
records, citations and relationships without connecting to the endpoint.

## Compare two saved observations

In Análisis, choose “JavaScript · Comparar fuentes y scripts observados”, a saved
`javascript.application` reference and a completed `javascript.observe` candidate
from this project. Both document hashes and source identities are retained and
verified. Original source files need not remain available. No live endpoint or
source path is read by reconciliation.

Exact captured UTF-8 source hashes take priority. Identical files at multiple
paths remain ambiguous; this is a content association, not a location verdict.
Optional parameters can contain `mappings` declarations:

```json
{"mappings":[{"runtime_url":"file:///app/main.cjs","source_path":"main.cjs"}]}
```

A URL/path mapping is a caller declaration. With metadata-only capture it remains
unverified; captured content can contradict it. Missing paths and contradicted
declarations remain explicit even when another path has an exact hash match.
URLs are not automatically treated as local file identities. Unobserved static
files may have executed outside the capture window. A script's presence proves
neither calls, imports, IPC, callbacks nor behavioral equivalence.

## Implementation and validation scope

The native product uses the generic free websocket-client1.9.0 library for CDP
transport. Its catalog reads installed metadata without importing the WebSocket
client or connecting. API/MCP use the existing runtime and analysis tools;
the runtime catalog has35 operations, static catalog53 and MCP37 tools.

Tests use only an original Node22.19.0 process started by the test, with an
isolated Inspector, original Unicode/CRLF module, heartbeat and dynamic VM
context. They exercise discovery, passive metadata, selected source collection,
stale IDs, cancellation, interrupted-client recovery, hash-bound comparison,
ambiguous content, declarations/contradictions and historical transfer. The
process continues after observation disconnects. No external model is used.

Primary protocol documentation: [Node Inspector](https://nodejs.org/api/inspector.html).
This tranche certifies the tested V8 Inspector flow; browser/Electron renderer
DOM, listeners, requests, screenshots, scenarios and source maps remain separate
open capabilities. It does not certify all CDP implementations or remote devices.
