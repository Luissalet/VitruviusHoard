# Runtime instrumentation

The free Frida SDK is installed with Theseus. Nine `frida.*` operations extend
the same **Ejecuciones → Observaciones en ejecución** form and runtime API/MCP
as the existing 24 Android operations. Static analysis continues to inspect
inert artifacts without executing them. Runtime discovery checks the installed
dependency without importing its SDK, connecting to a device or starting a
server. Explicit device/process discovery may start the SDK's local helpers.

| Operation | Effect and recording |
| --- | --- |
| `frida.devices` | Available device IDs, names and kinds; no process attachment |
| `frida.processes` | PID, name and device-provided process metadata for the exact device ID |
| `frida.start` | `attach` requires an exact PID; `spawn` requires an argv array and optionally cwd. A spawned process stays paused until resumed or closed |
| `frida.load` | Execute caller-authored JavaScript in the attached target, with a name and optional qjs/v8 runtime; record its source SHA-256, byte count, messages and errors |
| `frida.resume` | Resume only the still-paused process created by this session |
| `frida.unload` | Unload a selected script; earlier effects are not undone |
| `frida.status` | Freeze the current lifecycle, script identities and complete prefix of recorded events |
| `frida.close` | Unload scripts, resume a still-paused spawn, detach instrumentation and close its owned SDK connection. It never kills the target |
| `frida.observe` | Attach a selected PID, load its supplied script for a finite `duration_seconds` window (default1) and detach when it ends or is cancelled |

Use `device_id: "local"` for this host. Other device IDs come from explicit
device discovery. A caller-selected `remote_endpoint` uses `device_id: "remote"`;
an optional remote `token` is passed only to that SDK connection. It is excluded
from saved parameters, capture JSON and diagnostic text. The browser never stores
it in its draft map. No remote server or external API is required for local work.

Session IDs belong to the project and current backend. `theseus_project_read`
and the normal project API expose actual `runtime_sessions`, separate from
historical jobs. The form selects these connections and their script IDs.
Imported captures do not populate these selectors. A closed session's historical
records remain readable without reopening a connection.

## Evidence and lifecycle

Each operation saves an immutable JSON artifact and ordinary paged analysis
records, with SDK version/binary SHA-256, UTC capture times and target selection.
Asynchronous events append to an owned journal with sequence numbers and capture
times. Message JSON is retained directly; binary message bytes are base64 with
their length. Status and close freeze the prefix recorded at their capture time.
They do not promise that every event inside the target was instrumented or that
an SDK message still in transit had already arrived. Source hashes identify the
caller script's text; that text itself is not stored. SDK identity and PID are
not authentication of an executable, device or remote server.

Record citations, findings and evidence export/import use the existing product
flow. Transfer includes saved JSON snapshots and their exact recorded events,
not live connections, source script text, unsnapshotted future messages or target
memory. Imported receipt session states are historical. Close or capture status
before exporting to include the latest journal prefix.

Scripts can change memory, files and behavior using the target's capabilities.
Cancelling an operation or unloading/detaching does not undo these effects.
Cancelling a persistent-session operation leaves its connection available for
status or close; cancelling an ephemeral observation detaches it. Application
shutdown joins owned work, closes its sessions and retains final captures. It
does not kill targets. A disconnected or exited process may already be gone;
the target's final state is reported unknown rather than inferred from detach.

After restart, available journals are frozen and indexed as interrupted
observations without importing the SDK, attaching, spawning, resuming or loading
scripts again. Malformed/truncated journal lines retain their raw bytes as gaps.
A lost backend connection does not certify what happened to the target, including
a process previously recorded as paused; inspect it explicitly before further
actions. Capture/write or cleanup failures remain diagnostics.

## Tested boundary

The original Rust fixture exports `measure`; its own controller supplies normal
and boundary inputs. Real Windows SDK tests verify attach/spawn, argument/return
messages and binary bytes, JavaScript errors, unloading, explicit resume,
resume-before-close, target survival after detach, an ephemeral window's
cancellation, record citations and historical transfer. Separate tests verify
disk-only catalog discovery, credential exclusion and journal recovery without
replay. These tests attach exclusively to their own fixture processes.

The SDK is a generic native dependency, not a reference application's CLI/MCP.
Primary API references: [messages](https://frida.re/docs/messages/),
[JavaScript API](https://frida.re/docs/javascript-api/) and the installed
Frida17.24.2 Python bindings. Remote authentication and physical devices are not
live-certified by these local tests. GDB/Rizin commands, OS-specific debugger
backends, static/runtime correlation and general behavioral equivalence remain
separate open capabilities in `SOURCE-COVERAGE.md`.
