# Verification from retained page scenarios

Inspection can use two saved `browser.scenario` captures as a reconstruction
case. Verification reads their retained JSON documents; it never reconnects to
the pages, executes commands or replays the steps. Close the original programs
before verifying or transferring the evidence if they are no longer needed.

In Reconstruction, choose the retained-page scenario type, select the reference
and candidate captures and save the case. The interface displays their complete
SHA-256 identities. Link the case to an obligation and use the existing builder
handoff, verification and retry controls. Changing the candidate makes an older
verification inapplicable; changing the reference also invalidates sensitivity
measured against that reference. Editing only the name preserves frozen hashes.

The same flow is available through HTTP and MCP. `theseus_scenario_save` accepts
this definition, with actual capture job IDs and full lowercase SHA-256 values:

```json
{
  "kind": "retained-page-scenarios",
  "reference_job_id": "reference-capture-job",
  "reference_sha256": "<64 lowercase hexadecimal characters>",
  "candidate_job_id": "candidate-capture-job",
  "candidate_sha256": "<64 lowercase hexadecimal characters>"
}
```

Both jobs must belong to the project and identify retained `browser.scenario`
analysis. The saved definition has exactly these five fields. Existing command
cases without `kind`, their text/JSON modes, input and command arrays continue
to work. A self-test selects either command cases or retained cases in one run.

## What a matching case establishes

Each capture must have finished, or have been imported as historical evidence.
The analysis file, metadata and artifact identities must agree. Its document
must contain a successful observation and a nonempty, complete sequence of
completed steps, without protocol/JavaScript errors or a journal recovery gap.
Every completed receipt must match its planned request and command response ID.

Reference and candidate requests must align literally by position: method,
parameters, absent fields, values and array order remain significant. Object
key order is immaterial. Responses are compared literally after removing only
the outer CDP response `id`; payload IDs, clocks, object IDs and nested values
remain unchanged. Select stable primitive responses explicitly in the original
capture when that is the intended observation. There is no general output
normalization, time tolerance or interpretation of equivalent JavaScript.

The receipt includes both source citations, hashes, requests and responses.
A missing, altered, incomplete or unaligned capture is unknown, rather than a
successful match or a detected defect. Restoring a missing file does not turn an
already invalid receipt into a difference: run a new verification. Matching
selected responses establishes only those recorded observations. It does not
establish whole-page, whole-process, side-effect or general behavior equivalence.

## Check the oracle with independently captured defects

The normal interface can create a named perturbation from a selected case and
a saved candidate capture. MCP `theseus_oracle_selftest` accepts variants of
this shape, with exactly one capture for every selected scenario:

```json
{
  "name": "wrong boundary result",
  "captures": [{
    "scenario_id": "saved-scenario-id",
    "candidate_job_id": "defective-capture-job",
    "candidate_sha256": "<64 lowercase hexadecimal characters>"
  }]
}
```

A complete, aligned capture with different responses is a detected defect.
A complete matching capture survives. Broken or unaligned observations are
invalid and cannot certify sensitivity. The latest applicable self-test is
authoritative; an older successful receipt cannot hide a newer surviving or
invalid perturbation. Retained mutant files must still be available and valid.
Candidate-only changes preserve reference sensitivity, while verification must
be repeated against the new candidate. Finite supplied defects do not establish
that an oracle will detect every possible defect.

## Evidence transfer and builder handoff

Export includes the retained analysis documents. Import remaps only the new
typed reference/candidate capture ID fields, including typed perturbation
references. Literal requests, responses, hashes, local protocol IDs and opaque
text are preserved. Imported verification and self-test receipts stay historical
and do not certify the destination. A new verification/self-test can read the
imported captures without the original applications or their files.

The builder document remains the existing behavior-only handoff. Capture IDs,
hashes and retained observations belong to reader evidence and are not inserted
into that document. Analyst-authored prose still requires source-independent
specification discipline; this feature cannot guarantee that automatically.

See [the acceptance record](../tasks/submission993.md) for the measured original
browser, MCP, interface, transfer and regression cases. Theseus remains
incomplete; the [coverage ledger](../software_native/theseus-limits.md) retains
the other platform, runtime and reconstruction gaps.
