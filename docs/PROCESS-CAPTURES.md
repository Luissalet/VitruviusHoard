# Process scenarios and retained comparisons

`process.capture` is a native runtime operation, available from **Ejecuciones**,
`theseus_runtime_start` and the normal API. It starts the selected local program.
Its effects persist. No LLM, reference application, paid engine or external API
is required. Capture does not restore files or undo communications.

Choose an argument array, working directory and optional explicit environment.
Pipe mode preserves separate stdout/stderr byte streams. Windows pseudoterminal
mode uses ConPTY and keeps its combined UTF-8 VT output, real resize operations,
and terminal frames interpreted by xterm-headless. Raw bytes remain authoritative;
the rendered screen is a separate representation, with its engine versions.
There is no implicit target runtime limit. An optional `timeout_seconds` is an
execution deadline; observer service setup and command compilation happen first.

```json
{
  "argv": ["C:/Python313/python.exe", "C:/work/original.py"],
  "cwd": "C:/work",
  "mode": "pipes",
  "steps": [
    {"kind": "input", "text": "[-1,0,3,128]"},
    {"kind": "close_stdin"}
  ],
  "files": [{"label": "output", "path": "output.bin"}],
  "timeout_seconds": 30
}
```

Steps execute in order. Optional `at_seconds` is measured from target startup.
`wait_output` waits for literal text or strict base64 bytes in the chosen stream;
`wait_event` waits for an explicit event-field subset. `resize` needs a terminal.
Input runs on a separate writer so a target that does not read cannot block
cancellation. Accepted input bytes do not prove the program consumed them.

`signal` accepts `interrupt`, `terminate` and `kill`. Windows terminal interrupt
sends ETX through ConPTY; the target console input mode determines its handling.
Windows pipe capture cannot send console Ctrl+C and reports that limitation.
Windows terminate/kill use TerminateProcess, rather than claiming POSIX behavior.
Pseudoterminal stdin has no separate EOF: use input or an explicit signal.

Selected files/directories retain before/after bytes, length and SHA-256,
including absence, unreadable or unstable entries. Links and reparse points are
reported without following them. The observer's own output folder is excluded
explicitly. Program file arguments are hashed; changes during the run remain
visible. Ambient imports, configuration and concurrent outside changes are not
automatically bound to those hashes.

Windows starts the target suspended, attaches an owned Job, then resumes it.
Normal CreateProcess descendants stay in that Job even if the parent exits
between polling intervals. Completion requires root exit, no active Job members
and real stream EOF; timeout/cancellation closes the owned processes. No CPU,
memory or autonomous execution budget is added. External brokers, WMI-created
processes and other independent services lie outside that lifetime boundary.

## Declared services and commands

`services` starts private loopback scenario services and injects each declared
base URL into its `environment_key`. It supports literal HTTP responses and
WebSocket send/receive/close steps. Bodies and messages may be text or base64.
Captures keep duplicate headers, binary bodies, request metadata, WebSocket
text/binary representation, observed message order and close codes. The layer
is ASGI HTTP bodies and complete WebSocket messages, rather than TCP/TLS packets,
frame fragmentation or proof of the remote program's internal processing.

```json
{
  "services": [{
    "name": "gauge", "environment_key": "GAUGE_BASE_URL",
    "http": [{"method": "POST", "path": "/read",
      "response": {"status": 200, "text": "ready"}}],
    "websocket": [{"path": "/socket", "steps": [
      {"kind": "send", "text": "Ready"},
      {"kind": "receive"}, {"kind": "close", "code": 1000}
    ]}]
  }],
  "commands": [{"name": "gauge_read", "response": {
    "stdout": {"text": "21"}, "stderr": {"text": ""}, "exit_code": 0
  }}]
}
```

Declared commands use a first-party compiled Windows command shim, with the
installed .NET Framework compiler. They retain CLR argument arrays, working
directory and binary stdin/stdout/stderr without `.cmd` shell interpolation.
The executable/source hashes and compiler path are recorded. These are configured
scenario responses, not executions of the original external command. Only
PATH-resolved calls are covered; absolute paths and current-directory programs
can bypass the shim. Other platforms report this backend unavailable.

## Compare and verify retained evidence

`process.compare` takes two saved capture jobs and an explicit query. It verifies
retained document and selected byte identities, without starting either program
or reading their old paths. Partial, altered or unaligned observations remain
unknown. A complete input-step receipt is required; missing steps or accepted
byte counts cannot silently pass.

Dimensions are `stdout`, `stderr`, `exit`, `terminal`, `files`, `http`,
`websocket`, `commands` and `trace`. Files compare both snapshots by unique
caller labels. Terminal defaults to its final rendered screen; `terminal_view`
may select `raw`. HTTP/WebSocket compare declared-service occurrences as a bag,
keeping duplicates and order inside each WebSocket. Only names in explicit
`http_headers` / `websocket_headers` are compared. Command working directories
are compared unless `command_working_directory:false` is declared.

Literal UTF-8 normalization rules select a stream dimension and side, `from`
and `to`. Their counts and before/after hashes are retained. No volatile data is
silently removed. Trace queries select named event predicates and explicit
`before` relations. Missing, ambiguous, invalid or cyclic order remains unknown;
collection timestamps never create causal edges between independent producers.

In **Escenarios**, choose **Capturas de procesos guardadas**, select reference
and reconstruction captures and enter the comparison query. Both document hashes
are bound to that scenario. Comparison, reconstruction verification and the
oracle use those saved observations without replaying the target. Deliberately
wrong capture variants test sensitivity. A transferred receipt stays historical;
fresh verification and oracle results are required in the receiving project.
Changes to a selected mutant invalidate its sensitivity evidence instead of
falling back to an older successful receipt.

Cancellation or interrupted-observer recovery freezes the available prefix and
marks it incomplete. Recovery stops only the old job-bound observer and never
restarts the target. Complete equality describes selected observations of one
run, not equivalence for every input or environment. Windows behavior is tested
with native ConPTY, Jobs, loopback services and original programs; this does not
certify live operation on Linux or macOS.
