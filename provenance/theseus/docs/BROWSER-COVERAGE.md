# Precise page coverage

`browser.coverage` selects an explicit Inspector endpoint, current page target
and finite `observation_ms` window (default 10,000). Ejecuciones, HTTP and MCP
share the same operation. It resets execution counters and temporarily disables
optimized execution through CDP PreciseCoverage. It never supplies navigation,
clicks, typing, evaluation, a browser or a profile.

Wait for the actual **Armada** job receipt before performing external actions.
It is published only after a successful `Profiler.startPreciseCoverage` reply,
with its collection time and protocol sequence. The normal job and project
reads expose that receipt while the window runs; no separate session database
or replacement connection is created. The UI distinguishes collection, retained
results and interruption. A driver using an explicit `browser.scenario` needs
enough window time for that separate job to connect and execute its steps.
An action outside the recorded window establishes no in-window counter claim.

The final recording preserves nested producer ranges/counts, `isBlockCoverage`,
sample timestamps and independently hashed script texts. Offsets are **UTF-16
code units**, with exclusive ends. Bounds are checked against that captured
text, never interpreted as UTF-8 bytes or Python code points. Nested counts are
not summed. `coverage.scripts` indexes selected main-document source records;
`coverage_functions` searches function names and retains script ID, source hash,
raw ranges, bound status and explicit branch granularity beside each record.
Anonymous producer functions keep their empty raw function name and a display
label; they are not merged into a guessed function identity.

An absent script or function is **unknown**, including omitted lazy functions.
When the producer returns `isBlockCoverage=false`, branch coverage remains
`unknown-function-level`; Theseus does not synthesize zero-count branches. An
owned fresh-browser fixture measures executed and untouched branches, while a
reused live fixture also produced function-only observations. Neither case is
promoted into a guarantee that every function has block detail.

Request initiator stacks preserve their reported coordinates and async parent
IDs. Source associations use script IDs inside this CDP session. They do not
authenticate a URL, source path or UI causality. Workers and child frames are
outside the selected main-document claim. A main-frame document change ends
collection with an incomplete transition scope; the sample may contain
transition effects and does not certify complete coverage of either document.

The observer requests one resetting sample and stops precise coverage before
reading retained source texts. Acknowledged cleanup is recorded separately from
the job outcome. Abrupt cancellation or orphan recovery preserves the journal
and last receipt without reconnecting, replaying actions or claiming cleanup was
confirmed. The external target stays outside observer ownership. A received raw
reply can survive in the journal even when its derived summary is incomplete.

`browser.reconcile_sources` accepts the actual `browser.coverage` type beside
passive observations and scenarios, preserving both saved input hashes/citations.
It reads retained JSON after originals disappear. Historical evidence transfer
preserves function records and source text without live sessions. The existing
`browser.compare` still compares observation/scenario captures; it does not
silently turn these coverage counters into behavior-equivalence comparisons.

Acceptance uses original software-rendered Chromium fixtures and independent
HTTP effects. It exercises armed ordering, Unicode/CRLF source identities,
executed/untouched ranges, initiators, cancellation, orphan recovery, document
change, indexed function reads, source reconciliation and historical transfer.
Real stdio MCP drives explicit scenarios only after arming and retains producer
granularity. Desktop/mobile UI reads armed/cancelled jobs, ranges and both source
citations after the fixture closes. No model or GPU generation is required.
Electron, IPC, whole-process coverage and general reconstruction parity remain
separate capabilities.
