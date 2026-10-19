# Reconstruction and oracle workflow

The normal workspace, HTTP API and MCP share the same persisted records. The
workflow runs local programs. It does not request a model response.

1. Inspect original artifacts and save findings with their source identity.
2. Write observed behavior in Especificación. Create obligations for required
   behavior and questions for missing evidence. Select their named scenarios,
   findings and dependencies in Reconstrucción; assign an owner when useful.
3. Create a handoff for an existing builder directory. The saved handoff freezes
   the specification, claims and revision identities. Its builder-only download
   excludes the reader findings and original artifact paths. The full reader
   receipt remains available and is included in project export. The application
   neither copies sources into that directory nor creates candidate code.
4. Build independently from the behavioral document. Save reference/candidate
   command argument arrays and boundary inputs in Escenarios. Expected stdout,
   expected exit status and an explicit duration are optional. An empty stdout
   expectation is distinct from having no expectation. JSON mode compares parsed
   values; text mode compares exact output, including newlines.
5. Supply deliberately wrong candidates to the oracle self-test, for example a
   changed constant, reversed branch and off-by-one boundary. All selected cases
   run against every variant. One observed difference detects a variant; a
   variant matching every observed case survives. Timeout or unexpected exit
   status is invalid instead of proof that the intended defect was detected.
   A variant's optional `expected_exit_code` permits testing intentional failure
   behavior; otherwise its expected exit is the reference case's exit status.
   A nonzero reference exit must be expected in the scenario.
6. Verify a reconstruction against a saved handoff. Change the candidate, retry
   and inspect both receipts. A specification edited since the handoff is
   explicitly reported; that old handoff cannot establish the new contract's
   coverage. No interrupted job is automatically replayed.

`theseus_workflow_read` reports each claim as unknown, different, verified or
resolved. Verification requires an observed current case for every linked
scenario. The latest completed comparable observation wins. A changed scenario,
specification or command-file digest invalidates the older observation's use as
current coverage. Missing originals remain missing; historic receipts survive.

The `complete` observation concerns only the recorded claim graph. Obligations
also require a finished sensitive self-test of their current reference cases;
unresolved dependencies and unknowns remain open. This does not certify behavior
outside the suite, the independence of a hand-written builder, engines/formats
not exercised, or the full source parity requirement.

| MCP tool | HTTP operation |
| --- | --- |
| `theseus_workflow_read` | `GET /api/projects/{id}/workflow` |
| `theseus_claim_save` | `POST /api/projects/{id}/claims` |
| `theseus_handoff_create` | `POST /api/projects/{id}/handoffs` |
| `theseus_handoff_read` | `GET /api/projects/{id}/handoffs/{handoff_id}?builder_only=true` |
| `theseus_oracle_selftest` | `POST /api/projects/{id}/oracle-selftests` |
| `theseus_reconstruction_verify` | `POST /api/projects/{id}/reconstructions/verify` |

All execution operations return persistent job IDs readable with
`theseus_job_read`; cancellation uses `theseus_job_cancel`. Save new/revised claims
with `claim_id` omitted/supplied. Dependencies and evidence must belong to the
same project. Dependency cycles cannot describe an evaluable claim graph.

Original local fixtures exercise integer cases -1, 0, 9 and 10; a correct
reconstruction; wrong constant/branch/boundary variants; a weak oracle that
accepts an off-by-one implementation at input 0; a reference failing its explicit
expectation; an invalid mutant; stale code; stale specification; immutable
handoffs; foreign links; cycles; restart persistence; HTTP/tool parity and the
normal desktop/mobile browser flow. Results describe those fixtures.
