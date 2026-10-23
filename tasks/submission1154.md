# Explicit command execution with retained observations

The existing read-only query rejects writes and preserves its snapshot/profile.
A new `rizin.execute` operation accepts the caller's literal line against the
original artifact, with settings/scripts suppressed and plugins retained. It
records effects and stream uncertainty without closing a native analysis session.
The same operation appears in MCP discovery and the normal analysis form.

The two stream readers enforce one 16 MiB raw budget before buffering. Exactly
the limit plus EOF is complete; an excess byte, read error or imposed stop stays
unknown. UTF-8 replacement is measured by strict decoding, including a control
with a genuine U+FFFD character. Owned Windows processes start suspended, enter
their Job and then resume. Parent exit, stream EOF and descendant cleanup remain
separate observations. POSIX group code is implemented; this delivery's runtime
acceptance is on Windows.

Launch intent is persisted before creating the command. Prefixes, worker/child
identities and natural completion survive the relevant cancellation/recovery
paths. An unexpected transport error also preserves the observed document.
Retained reads never inspect the original or launch a command. Endpoint artifact
hashes are observations; disappearance, replacement and external inputs retain
their uncertainty. Command return does not establish semantic success.

Source checks:

- `codex-rizin1154-area-c.xml`: 114 PASS, no skips, 70.265 seconds. Includes
  original byte and arithmetic oracles, actual 16 MiB continuous output, EOF and
  injected reader errors, natural nonzero exit, cancellation/descendants,
  before-launch intent, failed transport retention, evidence transfer and a
  separate Ghidra session that remains open and reads its expected image.
- `codex-rizin1154-catalog-a.xml`: 10 PASS. Cold discovery remains 127 tools,
  without HTTP/autostart, and the updated API/catalogue descriptions agree.
- `codex-rizin1154-mcp23.json`: five actual private stdio observations, long
  Unicode preserved, original-file write verified, diagnostic retained despite
  engine exit0, cancellation retains20 bytes, all five documents imported exact
  while the original is parked. Native code is source1d85571; subsequent source
  changes are confined to the normal form's introduction/button text.
- `codex-rizin1154-ui23.json`: root operated the normal private UI on e9dc265,
  submitting one command that returns899 and reading an imported unknown receipt
  and its prefix. HTTP documents and served JS match their saved/source bytes;
  390px has no horizontal overflow. Screenshots/DOM have hashes in the receipt.

Historical failures remain: the missing operation's RED test, unsupported echo
spelling in the first real-engine oracle, missing parent directory in the
launch-intent fixture, and the UI's static-analysis introduction before its
correction. The first empty QA owner was closed before using corrected MCP
descriptions; the completed source QA owner and browser tab are also closed.
No browser download was attempted or claimed; private HTTP delivery is separate.

Reference behavior was read at revision
`4f7b5fb6023ce2ec449561782d09e3c7e5ac7c7b`: RizinCommand.ts blob
`5f6bc69b6ee958153a2ab00da2d35055435c0bed`, reverseEngineering.ts blob
`fb0cc9a08c01f497ca86169c6ff2279b37d1a2cd`, and reverseEngineeringToolContracts.ts
blob `7b6542be1aa1b5fec5b6922a4820230293a48156`. This is maintained product code,
not a relay to that reference application. Luis's requirement to preserve Ghidra
sessions overrides its incidental session-closing behavior.

Independent revision 1 requested changes after reproducing a suspended child
surviving a failed Windows Job assignment. Its report and failed receipt remain
in `review-rizin1154-r1`. The correction distinguishes Job creation from confirmed
assignment: before assignment, it terminates the actual suspended child through
its process handle and confirms exit; after assignment, normal Job cleanup
continues. Cleanup success now describes the child actually stopped.

Three real-process fault oracles exercise Job creation, assignment and resume.
The initial RED run preserved two failures and one pass; its cleanup checked
the exact identity before stopping the leaked oracle child. The corrected area
run `codex-rizin1154-area-r2a.xml` passed 117 tests without skips in 87.94 seconds,
including the existing Ghidra preservation control. The setup faults retain
unknown completion, never run their marker code and leave no original child.
Earlier MCP/UI evidence remains attributed to its original source revisions;
this cleanup-only correction requires independent revision 2 before acceptance.

Independent revision 2, full validation, installed acceptance and main
publication remain pending. No shared owner/MCP, old5217, Sparks, substitute
text model, GPU, SABER or shared ADB was used. Existing W2/main fac005a remains
unchanged. This submission does not close the remaining 207-contract programme.
