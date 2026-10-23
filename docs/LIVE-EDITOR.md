# Live editor command sessions

The **Binarios** section can discover an already running local Cutter editor and
send explicit Rizin command lines through its bundled Python bridge. The same
operations are available through `theseus_cutter_sessions` and
`theseus_cutter_command`. Discovery and catalogue reads never start the editor.
No project artifact is required: the observation belongs to the selected project.

Download `vitruvius_bridge.py` from **Binarios → Descargar puente Python**, put it
in the Python plugin directory reported by the chosen Cutter profile, and restart
that editor. Cutter must include its Python/PySide6 bindings. The bridge uses its
Qt event loop and the Python standard library; it does not require QtNetwork or
replacement Qt DLLs. The Windows 2.5.0 build tested here warns that its plugin
binding was rejected before calling setup hooks. The maintained module starts
its bridge idempotently during import as well, so discovery and commands still
work on that build. A warning alone does not prove the bridge is running: use
live discovery.

The plugin releases its own Python-backed Qt object during shutdown, before
the editor can finalize its embedded interpreter. A private test harness must
also release its own Python-backed timers at that point; stopping a timer alone
does not dispose it. Shutdown checks include normal native exit and descriptor
removal after command traffic, rather than treating a returned command as proof
of a clean editor shutdown.

Both processes use `Vitruvius/cutter-bridge` under the user's local application
data directory by default. Set `THESEUS_CUTTER_BRIDGE_DIR` to the same directory
in both environments to use another profile. The bridge binds only loopback and
authenticates requests with its private descriptor credential. Public sessions,
observations and evidence exports exclude that credential. Discovery reports
directory errors and capacity separately from an empty live session list. On
Windows its ACL result is explicitly unverified.

Select a session and its observed `document_generation`, then send one nonempty
line. This surface accepts arbitrary engine commands, including changes, file
writes and plugin execution. It is separate from the static read-only binary
query. The engine returns its original text, or the parsed JSON value when
requested. Failed JSON decoding preserves the original text. Empty output and
an engine return do not establish that the requested semantic effect succeeded.

Generation changes conservatively on admitted commands, native refresh events
and observed file/binary identity changes. A stale generation is rejected before
calling the engine. File names and generation remain **partial identity**, not
a digest or complete model of the editor's internal state. After a command,
refresh the sessions before deciding the next one. A lost response is marked
`unknown` if the command may have been sent; no automatic retry occurs. The
editor can still be working after the host timeout. Cancellation or closing the
host cannot undo target effects.

Each command saves a normal observation job, complete JSON document and indexed
records, including failed or unknown outcomes. Read these in **Ejecuciones**,
download them, or export/import the project's historical evidence after the
editor closes. A retained digest identifies the observation document, not the
current binary. Importing evidence never reconnects to a live editor. If the
host stops before recording a response, opening its inspection module retains
an unknown interrupted observation without replay. If local retention itself
fails after a response, the caller receives the observed completion plus a
retention error and must not resend automatically.

The original synthetic ELF checks cover ELF64 metadata, arithmetic, flag
creation/read/removal, close/reopen of the same path, stale generation, JSON
scalars and empty/non-JSON output. They do not certify every engine command,
every platform build, complete file identity, or runtime behavior of a target.

Installed W2 has independent finite acceptance for these observations. The
author made 15 MCP observations and two normal UI commands; after a normal
native exit0, 17 documents and 253 output records transferred exactly. A
separate reviewer repeated 15 observations on another original fixture,
obtained native exit0, and transferred 15 documents and 77 output records.
The UI displayed the imported output after the editor closed. HTTP deliveries
matched the saved documents; a completed browser download remains unverified.

Shutdown attribution is limited. The original offscreen startup diagnostic
reported an incompatible Qt platform DLL without loading the bridge; native
Windows startup worked. The exact cause of the earlier fast-fail exit is not
proven. A later shutdown comparison held the bridge and 15 requests constant:
changing the private QA callback from a lambda to a named function changed the
outcome to exit0. Explicit bridge disposal is retained, but its necessity and
the exact interpreter-finalization failure were not isolated by that comparison.

W2 SHA-256: `e63a58672846add8c6d6c2871ffc3aa91b1ab4c6d9b86cf0fce0e07bcf44e375`,
packaged source `a5e4c50bcfab9dac43493750117108e01a9e1b21`. Global validation
is composed: the full run retained 1910 passes, six failures and five skips;
unchanged failed cases plus retained-document oracles passed in two separate
nine-case runs. No single green full run or load-performance guarantee is claimed.
