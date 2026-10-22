# Live editor bridge — source submission

This delivery implements contracts 186/187: discovery of a live Cutter bridge and
explicit arbitrary Rizin commands in that editor. It preserves independent
Ghidra sessions and the separately reviewed static read-only query. Standalone
arbitrary command contract 189 remains a separate open feature, task 1154.

The maintained Python plugin runs in the Qt event loop using a nonblocking
standard-library socket. Authenticated discovery observes session UUID, PID,
generation, file and version without launching an editor. Commands preserve
returned text or parsed JSON, partial identity, execution status and uncertainty;
they are never automatically retried. Historical jobs, indexed records and exact
JSON documents use the existing evidence system. Interrupted command recovery
records unknown completion without reconnecting or replaying.

The ordinary Binarios UI exposes discovery, bridge download/install instructions,
selection and commands even without a project artifact. It shows the submitted
command and output, clears its session observation after sending, and requires
a fresh explicit discovery before another command. Retention/transport failures
keep completion uncertainty visible. The plugin is package data. Cold native
catalogue adds two tools, to 42 Theseus/127 owner; no factory or client runs merely
to read it. See [usage and limitations](../docs/LIVE-EDITOR.md).

## Author verification

- `codex-cutter-tests22a`: 14 PASS; final startup-recovery version
  `codex-cutter-tests22e`: 14 PASS, 8.27 s. Fresh basetemp and mandatory no-alias
  pytest wrapper throughout.
- `codex-cutter-tests22d`: 52 PASS, 17.89 s, including workbench, native owner,
  cold stdio and shutdown regression. Earlier 22b failed collection because of
  an incorrect file name; 22c retained 50 PASS/2 FAIL for obsolete 125-tool
  assertions. Expectations were updated to 127 plus explicit tool presence.
- Maintained plugin in actual private native editor, `codex-cutter-native22e`:
  ELF64, arithmetic 63, create/read/remove flag, stale generation not started,
  close/reopen verified by current file and ELF64 metadata, empty output,
  normal exit and descriptor removal. Target ELF never executed, GPU unused.
- Real stdio MCP, `codex-cutter-mcp22b`: 127 tools and eight retained commands,
  JSON object/list/scalar, empty output and requested-JSON failure. Credentials
  excluded from public observations. First helper failed on its own Python
  argument-name collision before commands; receipt remains.
- Normal private UI 64329, `codex-cutter-ui22`: two arithmetic submissions,
  zero artifacts, desktop and 390 px mobile without horizontal overflow,
  exact analysis and plugin downloads. Screenshots visually inspected; mobile
  emulation restored. The owner was initially loaded before the final
  startup-only recovery adjustment; fresh API pytest checks that path.
- After normal native editor closure, ten documents exported/imported byte
  exactly and every output record read by actual MCP. `codex-cutter-transfer22b`
  reads the already imported project; it does not repeat import. First transfer
  checker incorrectly compared the first row of array output with the whole
  array; its failure and initial ten-document exact comparison are preserved.
- Normal UI read the imported scalar 63 with its JSON-capture hash after editor
  closure, `codex-cutter-ui-retained22`. Own IAB tab closed. Private owner
  shutdown receipt `qa-codex-cutter22-closed.json`; 64329 free.

All external receipts are under the existing
`research-inbox/blender-reverse-20261018/compiled` evidence directory. No shared
application, Sparks, alternate text model, GPU, SABER, shared ADB or old server
was used. Native probe failures remain: wrong `fj` oracle, weak reopen assertion,
startup generation race, and failed plain-open assertion. The corrected native
check uses the documented `flj` and `oc` commands and verifies actual file state.

## Scope still requiring acceptance

Revision 3 adds explicit disposal of the bridge's own Qt object during close.
The original access violation and all narrowing receipts remain available.
The debugger stack enters PySide during QObject child destruction; its exact
interpreter-finalization order and the triggering object were not isolated by
that stack. The author's historical comparisons also changed the QA callback's
form, so they do not demonstrate that disposing the Bridge was necessary.

Independent controls hold the old r2 product bytes and 15 requests constant:
a named function that only deletes the QA timer exits 0, whereas a lambda with
the same body reproduces the access violation. The QA callback's form/lifetime
is therefore a demonstrated confounder. R3 with the corrected QA callback exits
0, and its explicit bridge disposal passes regression and native MCP checks;
its necessity as a fix for the original failure remains unproven. The wrapper's
timer is not part of the shipped plugin. See `review-cutter1120-r3.md` and its
four causal-controls receipts for the independent positive and negative cases.

Evidence: `codex-cutter-narrow22-status_debug/socket-control.stdout`,
`codex-cutter-narrow22-status_deletetimer/socket-control.json`,
`codex-cutter-narrow22-fixed_full/socket-control.json`, and
`codex-cutter-narrow22-fixed_full_product/socket-control.json`. The first
debugger helper timed out during discovery before its protected cleanup;
its own stop marker subsequently closed the editor and the debugger captured
the shutdown stack. This diagnostic failure is preserved, not counted as a
passing live operation. The source fix still requires independent review.

Independent source review and its own tests, combined regression as appropriate,
fresh packaged/installed MCP/UI acceptance, integration and publication have not
been claimed by this source submission. Both ledger rows stay pending. Document
identity is partial, Windows ACL verification unknown, and an engine return does
not certify a command's semantic effect. The observed Windows plugin-loader
warning is documented, not represented as successful hook registration.
