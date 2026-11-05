# Native inventory compositions

Use these operations through the existing `theseus_binary_call` tool or the
normal session operation form. Both return retained background analysis jobs.
The numeric `xrefs` and raw `read_binary_inventory_summary` operations remain
available. Discovery marks the new operations as product compositions that do
not write the native analysis database.

`resolve_name_references` accepts an exact nonempty `name` and an optional
`document` (null selects the bound program). It reads the complete name inventory,
preserving qualified names, Unicode, case and every matching symbol occurrence.
Equivalent numeric address forms in the same observed address space count as
one target. One target produces `status: resolved`, even with zero references.
No target produces `status: unresolved, reason: name_not_found`; distinct targets
produce `reason: ambiguous_name` without guessing one. Provider errors and
invalid observations remain failed observations, rather than name absence.

`binary_overview` takes no parameters. It retains the complete raw summary and
segments, adds `segment_count`, and projects `image_base` with its separate
`image_base_address_space` only when every observed base and space agree.
Equivalent hexadecimal forms compare numerically. Unqualified addresses require
the default space actually observed in the session; a segment name or minimum
start address cannot supply it. Empty, incomplete and conflicting observations
produce a null base with an explicit reason.
Malformed encoded addresses remain failed observations with their retained
diagnostic; a missing default-space observation remains unknown.

Both compositions retain their parsed provider envelopes, parameters, observation
order and native session/artifact/revision binding. These are static analysis
observations bound to the revision held when the session lock is acquired, so a
previously admitted annotation is reflected if it completes before the reading.
They remain sequential provider
observations, with the provider's discovery limits; they do not establish runtime
behavior or completeness of recovered symbols. Their documents and records use
the existing evidence transfer, preserving historical bytes without reopening a
provider or consulting the original artifact.

This is the first slice of task1157, tracked as1307 for contracts47 and48.
Ordinary reopen continuity, neutral snapshots, FIFO lifecycle ordering and cold
server/client status remain separate pending requirements. Validation and release
status are recorded in [the submission](../tasks/submission1307.md); implementation
alone does not advance the coverage ledger.
