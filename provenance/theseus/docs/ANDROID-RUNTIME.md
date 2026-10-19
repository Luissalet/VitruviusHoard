# Android runtime observations

The **Ejecuciones → Android conectado** form, HTTP API and MCP share 24
operations. These are explicit live observations or actions against a selected
Android device, separate from execution-free artifact analysis.

`GET /api/runtime/catalog` and `theseus_runtime_catalog` report the installed
client and each operation's input schema and mutation flag. Discovery only checks
local files; it does not start a server or connect to a device. Configure
`THESEUS_ADB` or install Android platform-tools in PATH or the usual Windows SDK
directory. Running device discovery or an observation may start the SDK's shared
ADB server normally. Theseus never kills that shared server.

Start with `POST /api/projects/{project_id}/runtime` or
`theseus_runtime_start`, passing `operation` and `parameters`. Every device
operation requires its exact `serial`; there is no implicit first device.

| Operations | Recorded result |
| --- | --- |
| `adb.client`, `adb.devices`, `adb.device` | Client path/hash/version, connected serials/states, selected device's build/SDK/ABI properties |
| `adb.packages`, `adb.resolve_packages`, `adb.package` | Declared package paths, substring search and full dumpsys package output; unrecognized fields remain unknown |
| `adb.pull_package`, `adb.pull_file`, `adb.screen`, `adb.bugreport` | Collected base/split APKs, file, PNG dimensions or system report; each available file has its own SHA-256 and source link |
| `adb.logcat`, `adb.processes`, `adb.directory` | Log buffer dump without clearing it, full process table, selected directory's names/types/sizes/link targets |
| `adb.features`, `adb.services`, `adb.display`, `adb.window`, `adb.setting` | Device-declared features, Binder services, physical/override display values, focus context and a named setting |
| `adb.push_file`, `adb.install`, `adb.uninstall` | File transfer/verification, installer or user0 uninstaller verdict, complete diagnostics |
| `adb.start_app`, `adb.start_activity`, `adb.stop_app` | Resolved launcher or explicit intent with typed extras and full `am start -W` report; force-stop result |

The last two rows modify the selected device. The form explains this and labels
its submit button **Ejecutar en el dispositivo**. Install/push use a private
local input capture whose original identity is checked again; it is removed
before publishing the owned job's terminal state, including cancellation and
client failures. If the operating system refuses removal, the terminal receipt
retains `cleanup_error`; an otherwise successful observation becomes failed,
with its recorded observations still available. Push requires explicit
`overwrite` when its initial destination check finds a file. That check is not
an atomic reservation against other device writers. A missing device hash stays
unknown. An install's `replace_requested` records the requested flag, while
`replaced` remains unknown without an independent prior-state observation.
An uninstall requests user0 removal without retaining application data.

## Recordings, partial results and citations

Each job records UTC times, commands, durations, exit status, stdout/stderr text
and exact base64 bytes, client identity and the selected device's fingerprint
when available. Directory entries and link targets use the official local ADB
server's shell-v2 raw protocol, preserving NUL-separated names and separate
stderr/exit frames without Windows newline translation. This raw reader requires
a TCP ADB server socket; unsupported transports and partial permission failures
remain explicit diagnostics. Non-UTF-8 names retain their bytes and are flagged
instead of silently being used as substituted lookup paths.

Read these observations using the existing analysis section/page/record tools or
the browser's **Consultar registros**. **Usar registro como observación** cites
the saved JSON capture as an artifact. Its SHA-256 identifies the recording,
not the APK or the device. Collected files have separate hashes and derived
artifact relationships. Generated local names preserve exact remote origins in
the recording even when the remote filename cannot be represented on Windows.

Every completed command checkpoints a partial recording. Cancellation stops
owned host clients and retains completed observations; it neither undoes device
changes nor certifies that a device-side command stopped. On application restart,
an interrupted job's available recording is frozen and indexed without replaying
the operation. Missing or changed collected files are reported unavailable.

Portable evidence export/import preserves the exact recording JSON, indexed
records, citations, historical receipts and artifact relationships. It does not
embed collected file bodies, original APKs or a live device connection, and does
not replay actions after import. Imported observations describe their capture
time, not the device's present state.

## Validation and limits

The original fixture in `tests/fixtures/android` is compiled with the installed
SDK and signed with a temporary test-only key. Opt-in integration tests require
`THESEUS_TEST_ADB_SERIAL` and verify the AVD name is exactly `Theseus779` before
any mutation. They exercise all 24 operations on that owned emulator, including
actual install/launch/typed intent/stop/uninstall, pull/push, screen, bugreport,
newline/quote directory entries and partial permission failures. The emulator
uses software graphics; no model service is needed. Unit tests separately cover
shared-server preservation and interrupted/cancelled recording retention.

These fixtures do not certify every physical device, Android release or split
installation. Static JNI/reflection resolution, static/runtime reconciliation
and whole-application behavioral equivalence remain separate open work.
