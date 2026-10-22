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
