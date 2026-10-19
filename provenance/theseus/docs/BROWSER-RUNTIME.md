# Page observations, portable PNGs and saved comparisons

Ejecuciones exposes `browser.targets` and `browser.observe` through the existing
runtime tools. Enter an explicit HTTP(S) CDP endpoint, list its destinations and
choose the exact current page target ID. Listing does not attach or launch a
browser. Theseus connects only to the reported WebSocket on that endpoint.
Producer URLs, target IDs and metadata do not authenticate a physical process.

Observation enables Page/Network and Runtime/Debugger metadata. Initial script
and context inventory precedes the timed notification window; both boundaries
are recorded. The default page window is 1000 ms. Notifications after its end are
excluded and counted, while replies to selected snapshot commands remain
recorded with their later collection times. A page can keep changing between
the window, DOM reads and the PNG; these are not one atomic target snapshot.
No navigate, click, type, evaluate, pause, resume or target-close command is sent.

The independent choices in the form are:

- Script texts: read the selected script inventory with `getScriptSource`.
  Preserve original characters/CRLF, UTF-8 hashes and UTF-16 counts. New source
  outside the selected inventory is not recursively chased. Source-map URLs are
  recorded without fetching them. A script's presence does not prove a call.
- DOM: retain the full reported document tree. A CSS selector can separately
  select all matching nodes for listener metadata, without evaluating JavaScript
  or invoking the callbacks. Node/object IDs are capture-local; released observer
  handles are not target termination.
- Response bodies: read only completed requests in the selected event inventory.
  Missing, unfinished, failed or evicted bodies remain unknown. Base64 replies
  preserve returned bytes; text replies are explicitly UTF-8 representations,
  not proof of original wire encoding. Network notifications can themselves
  include producer-reported request headers and POST data in metadata mode.
- PNG: save one reported page viewport image at its collection time. Generated
  regular artifact names, hashes and source links identify the stored bytes.

The capture is an immutable product JSON with indexed records, protocol bytes,
collector UTC, producer timestamps and source references. Its hash identifies
the recording, not a device, executable, complete history or behavioral parity.

## Cancellation and incomplete captures

Selected protocol frames are appended to a sequence-numbered JSONL journal.
Full immutable checkpoints are coalesced rather than rewritten for every frame;
this is an I/O schedule, not a limit on recorded observations. Normal completion
publishes the complete JSON atomically. Cancellation stops only the owned host
observer and freezes the available checkpoint plus complete journal tail.
Restart checks PID, creation time, command and job paths before stopping a
matching orphan; it never reconnects or repeats commands. Truncated tail bytes
are retained as an explicit gap. Higher-level optional snapshot summaries can
remain incomplete even when their raw replies survive. This is a recoverable
recorded prefix, not a guarantee against OS/storage failure or missing events.

## Saved comparisons and source association

Análisis offers `browser.compare` for two saved page observations and
`browser.reconcile_sources` for a saved `javascript.application` and page capture.
Complete and incomplete page captures with retained documents are selectable;
their terminal states remain visible. Both input document hashes are checked.
No original path or live endpoint is read by these operations.

Capture comparison retains script/source-map metadata, network headers and
literal POST/response content identities, selected listener tuples, DOM and PNG
projections. Counts and caller-selected scopes are observations, not identities
or a verdict that an event never happened. Missing content stays unknown. DOM
projection removes only capture-local nodeId/parentId/backendNodeId/frameId keys;
attributes, text and child order remain exact. PNG comparison is of recorded
hashes, not semantic or visual equivalence. Listener metadata proves no callback
invocation. Original frames remain available beside each projection.

Source reconciliation uses captured UTF-8 content hashes first. Identical content
at different static paths stays ambiguous. Optional URL/path `mappings` are
caller declarations; missing paths and contradictions remain visible. URLs alone
are not file identity. Wrappers or encoding transformations can prevent a match.

## Images and evidence transfer

Artefactos displays registered PNGs with their hash and a download link.
`theseus_artifact_image` returns identity metadata plus native MCP ImageContent;
the HTTP agent tool returns PNG base64, and the artifact `/image` route serves
its bytes with an X-Content-SHA256 header. Other image formats are not certified.

When a PNG came from a page recording, the reader can use its already retained
`Page.captureScreenshot` reply and artifact link, verifying the recording and
image hashes. This works after transfer without the temporary PNG, a browser
connection or recreating files. A standalone registered PNG requires its exact
recorded file bytes; changed/unavailable data returns an error. Transfer moves
historical records and references, without replaying observation or target actions.

This tranche uses generic free websocket-client and an original Chromium 153
headless fixture with its own profile/loopback server and software-rendering flag.
It is not a reference application's runtime/CLI/MCP. Explicit page actions and
saved step-response comparison are described in [browser scenarios](BROWSER-SCENARIOS.md).
Finite precise Profiler coverage is described in [page coverage](BROWSER-COVERAGE.md).
Richer source-map correlation and Electron renderer-specific validation remain
separate work; Chromium alone does not certify Electron.
Primary protocol references: [DOM](https://chromedevtools.github.io/devtools-protocol/tot/DOM/),
[Network](https://chromedevtools.github.io/devtools-protocol/tot/Network/) and
[DOMDebugger](https://chromedevtools.github.io/devtools-protocol/tot/DOMDebugger/).
