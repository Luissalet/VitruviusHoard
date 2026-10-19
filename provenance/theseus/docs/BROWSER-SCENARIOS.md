# Explicit page scenarios

`browser.scenario` is a runtime operation in Ejecuciones, HTTP and MCP. Select an
explicit Inspector endpoint and current page target, then supply a nonempty JSON
`steps` array. Every step contains `method` and an object `parameters`; optional
`observe_ms` records notifications for that explicit interval after the reply.
For example:

```json
[{"method":"Page.getFrameTree","parameters":{},"observe_ms":100}]
```

The operation enables the same recording domains as browser observation, sends
only the caller's step commands in order, and records exact requests, command
identities, replies, protocol sequence boundaries and collection times. It does
not invent navigation, clicks, typing, evaluation or readiness checks. A caller
can explicitly request these CDP actions and bears their effects on the selected
page. Protocol errors and JavaScript exception details stop the remaining steps.
Notifications include console and exceptions during the scenario window. The
existing independent source/DOM/listener/body/PNG options and final finite
observation window remain available.

Cancellation and interrupted-worker recovery preserve the recorded prefix and
close only the owned observer. They never replay actions, reconnect, navigate,
close the target or undo effects. A reply recovered from the append-only journal
is identified separately; it does not establish completion of its observation
interval. The immutable job JSON retains both the original plan and per-step
receipts. There is no separate scenario database.

`browser.compare` and `browser.reconcile_sources` accept explicitly typed
`browser.observe` and `browser.scenario` inputs. Comparison reads retained JSON
and its bound hashes, without opening originals or live targets. Two scenarios
align steps by position and exact JSON request values, including whether
`observe_ms` was omitted. Only two completed aligned steps yield a response
comparison. It excludes the CDP envelope `id` and preserves every payload value;
capture-local payload identities are not normalized. Missing, incomplete and
unaligned steps remain unknown. Passive/scenario pairs retain their actual
types and do not acquire invented step alignment. Equal recorded responses are
not behavioral equivalence, callback execution proof or whole-process coverage.
Source reconciliation retains both input citations and its existing content
matching limits. PNG evidence and historical transfer use the same native paths
as [page observations](BROWSER-RUNTIME.md).

The owned Chromium fixture independently records HTTP side effects. Acceptance
covers explicit navigation/input/click and Unicode values, return-value
differences, protocol and JavaScript errors, cancellation, orphan recovery,
unsnapshotted reply recovery, source removal, retained comparisons and PNG
transfer. The combined scenario/browser/Inspector/inventory area passes 30 tests
in 88.75 seconds. An earlier area's three fixture-teardown failures are retained;
the owned fixture now requests graceful browser closure before its exact-process
fallback, and those same three cases pass separately. This is fixture cleanup,
not a production command added to passive observation.

Actual stdio MCP executes scenarios, reads step receipts, compares responses,
reconciles retained sources, saves a two-source finding and transfers native PNG
evidence without its original file. A fresh MCP session repeats the saved step
comparison after the owned browser and HTTP server close. The normal browser
executes a scenario, retains a protocol-error prefix without its planned second
step, and compares the MCP/UI captures with both source hashes. Desktop/mobile
form, step/error and comparison segments are independently reviewed at that scope.

Finite precise Profiler counters and UTF-16 ranges are described in
[page coverage](BROWSER-COVERAGE.md). WebSocket stream comparison, Electron
renderer/main/preload correlation and general reconstruction parity remain
separate capabilities. No LLM, model endpoint or GPU is needed for this workflow.
