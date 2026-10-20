# Retained page observations in reconstruction verification

Previously, reconstruction obligations and oracle sensitivity used executable
command cases. Inspection can now select two saved `browser.scenario` captures,
verify their exact selected responses and test explicitly mapped defective
captures after the original pages have closed. HTTP, MCP and the normal
Reconstruction interface share the same handlers and saved identities.

Base: `254255b8ccd22a50de329c477a6ab765391a4cf4` (approved972 rebased onto936,
plus README documentation). Product/test head:
`115d81ea06392452aa8cf660b92d495272911a68`; subsequent submission edits document
these results only. No dependency or license additions. Two existing tool
schemas change; discovery remains118 tools with all modules OFF and no profile
creation on cold discovery. Preserve the later954 design tool descriptions when
composing onto newer Main.

## Implementation and limits

`retained_scenarios.py` validates hash-bound project-local jobs and complete
literal requests/responses. Comparison, workflow and sensitivity use that
observation without connecting or replaying. Invalid observations remain unknown,
including after a previously missing document is restored. Typed references
alone are remapped on transfer; imported receipts remain historical. Current
candidate changes invalidate verification but preserve unchanged reference
sensitivity. A newer surviving/invalid self-test supersedes an older pass.

The interface retains existing command controls and adds capture selection,
full hashes, typed perturbation selection and two-source recorded responses.
Project reads collect jobs before computing workflow so a rapidly completed
verification cannot expose finished jobs alongside an older workflow snapshot.
No CSS or layout system changes. The bounded interface detector returned `[]`.
See [the user/API contract](../docs/RETAINED-SCENARIO-ORACLE.md).

Matching responses do not prove whole-program equivalence. Selected CDP payloads
remain literal, including clocks/local IDs inside them. Incomplete, altered,
broken and unaligned observations cannot certify coverage or sensitivity.
Theseus remains incomplete and in progress. No Sparks, model or GPU generation,
shared application restart, shared profile/data/environment write, ADB operation
or retired Theseus server was used.

## Verification

Receipts live in `D:/LocalAI/research-inbox/blender-reverse-20261018/`.

| Check | Result | Receipt |
| --- | --- | --- |
| Retained cases, workflow and existing reconstruction/evidence area |40PASS,15.044s|`oracle993-area4.xml`|
| Complete Theseus suite, Ghidra explicitly enabled |269PASS,2owned-emulator opt-in SKIP,451.334s|`oracle993-full1.xml`|
| Dependency consistency |PASS|`python -m pip check`|
| Original browser captures |8 retained captures from7 original applications; independent HTTP result logs; original apps closed and authored source files removed before verification|`oracle993-captures20b-proof.json`|
| Real stdio MCP and owner HTTP |118 schemas, strong3 mutants detected, weak survivor, broken/unaligned invalid, fresh verification and self-test after double transfer|`oracle993-mcp20-proof.json`|
| Normal desktop UI on115d81e |Saved typed case and perturbation, candidate changed, new verification finished and claim updated without reload;2cases and2sources|`oracle993-ui20c-proof.json`, `oracle993-ui20c.png`|
| Private instance closure |All modules OFF, requests/sessions0; cold MCP preserves DB/token hashes; exact owned PIDs stopped, port64176 released and QA tabs closed|`oracle993-before-race-fix-close20c.json`, `oracle993-before-race-fix-process-close20c.json`|

Pytest used `run-pytest-no-alias779.py` with new nonexistent basetemp directories.
The full run includes the incorporated firmware scanner and original Electron
runtime cases. These measurements do not certify the shared installed payload,
mobile layout or a newer owner composition. Mobile viewport control was not
available through the documented browser capabilities; no mobile claim is made.

The independent original rule was observed at[-1,0,3,128] with results
[0,0,21,896]. Constant, branch and boundary defects changed those results. A
latent129-only defect survived those four inputs, demonstrating the finite
oracle's limit. The original broken case raised a real JavaScript exception.
Requests with an additional explicit zero-valued field remain unaligned.
Retained source files and opaque strings equal to internal IDs survive two
imports without substitution. Builder documents exclude capture IDs/hashes.

## Preserved failures

The first schema test rejects retained definitions before implementation
(`oracle993-red1.xml`). A deterministic project-read witness reproduces finished
jobs with stale unknown claims (`oracle993-race-red.xml`), then passes after
ordering the read (`oracle993-race-green.xml`). Restoring a missing capture
initially changed an invalid receipt into a difference; that failure and its
correction remain in `oracle993-invalid-red.xml` and the final area suite.

An initial HTTP test used owner port5191 against the raw Theseus host guard and
received401; the test was corrected to that host's5217 base URL without changing
authentication. The first original-capture driver incorrectly required HTTP
arrival order to equal Promise.all input order and did not retain its independent
HTTP log before failing. That run cannot establish its independent HTTP oracle.
The new-project second run saves raw logs first and checks HTTP effects by
unique input, while retaining positional comparison of the actual CDP response.
Both runs and their partial records remain. A syntax preparation error was fixed
before test execution. None of these failures was removed or reclassified as a
successful product run.
