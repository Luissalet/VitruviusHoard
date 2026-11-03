# Equivalence workshop

Part of Theseus, extending the existing differential oracle (`Comparisons`, background jobs, the evidence store and the
constant/mutant philosophy of `theseus_oracle_selftest`). Implemented in `theseus/equivalence.py`.

**Scope.** A run compares two explicitly configured programs on the listed cases, steps and channels only, in fresh
sandboxes. Agreement is never reported as whole-program equivalence. Theseus development remains incomplete; see
`software_native/theseus-limits.md`.

## Flow (API / MCP)

1. `theseus_equivalence_suite_save` (`POST /api/projects/{id}/equivalence/suites`) stores a suite (revisioned).
   `theseus_equivalence_suite_read` reads one suite or lists them.
2. `theseus_equivalence_run` (`POST /api/projects/{id}/equivalence/runs`) starts a background job
   (`result.kind == "equivalence_run"`); poll it with `theseus_job_read`. Pass `suite_id` or an inline `suite`, plus
   `strength` (default true), `shrink` (default true) and `shrink_budget` (default 100 reruns per failing generated case).
3. Jobs are ordinary Theseus jobs, so they are cancelled with `theseus_job_cancel` and exported/imported with the
   evidence bundle (the frozen suite, per-step hashes and outputs travel with the job).

There is no dedicated UI view: the Theseus web UI has no generic tool-result pattern, so the flow above is the supported
interface (agents, MCP and HTTP).

## Suite

```json
{
  "reference": {"argv": ["python", "ref.py"], "cwd": null, "env": {}, "timeout_seconds": 30},
  "candidate": {"argv": ["python", "cand.py"]},
  "channels": ["exit_code", "timeout", "stdout", "stderr", "files", "db"],
  "normalisers": [],
  "ignore_paths": [],
  "ordered_tables": [],
  "cases": [{
    "name": "checkout",
    "files": {"in.txt": "text", "blob.bin": {"base64": "..."}},
    "db": {"path": "app.db", "seed_sql": "CREATE TABLE t(...); INSERT ..."},
    "steps": [{"args": ["add", "x"], "stdin": "", "files": {}, "env": {}}, {"args": ["list"]}]
  }],
  "generators": [], "authorized_deviations": []
}
```

* A case without `steps` is one invocation (`args`, `stdin`). Steps run in order in the same sandbox, so state left by
  step 1 is visible to step 2. Reference and candidate each get a brand-new sandbox at the same path
  (also exposed as `{sandbox}` in argv/env/cwd and as `THESEUS_SANDBOX`), so printed paths agree.
* Default cwd is the sandbox; a relative `cwd` is a sub-directory of it; an absolute `cwd` is used as is (effects there
  are not observed). Commands get `PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1` unless the suite overrides them.
* Compared per step: exit code, timeout, stdout, stderr, file effects (created/modified/deleted, content SHA-256, text
  diff) and, when a `db` is declared, the SQLite schema and rows. Rows are matched by primary key (or as a multiset when
  there is none), so order does not matter unless the table is in `ordered_tables` (`"*"` for all). The database file
  itself and its journal files are excluded from the file channel.
* Narrow channels per suite or per case with `channels`.

## Normalisers (explicit, opt-in, recorded)

`strip_trailing_spaces`, `strip`, `normalize_newlines`, `collapse_whitespace`, `sort_lines`,
`ignore_regex {pattern, replacement}`, `numeric_tolerance {abs, rel}`. Each takes `apply_to` (default `stdout`,
`stderr`; `files` compares text file contents too). The active list is stored on every case, and a channel that only
matched because of a normaliser is listed in `equal_only_after_normalisation`.

## Result

Per case: `verdict` (`equivalent`, `authorized_deviation`, `different`, `invalid` when the reference timed out),
`first_disagreement` (step, channel, path/table, kind, minimal diff, both values), every disagreement, and retained
per-step evidence for both sides (exit code, clipped output and full-output SHA-256, file effects with hashes, database
hash and row counts). Summary verdicts: `agrees_on_listed_cases`, `different`, `authorized_deviation_only`, `invalid`.

## Authorized deviations

`{case (glob), channel (or *), step, path, expected, reason, expected_candidate: {equals | regex}}`. A covered
disagreement is reported with `status: "authorized_deviation"` and its reason, never dropped. If `expected_candidate`
is given and the candidate no longer behaves as authorized, the disagreement is real and carries
`authorization_violated`. Without `expected_candidate` the authorization is accepted on trust and says
`expectation_checked: false`.

## Strength check

With `strength` on, two constant candidates run against the same cases: one echoing the reference output of the first
case's first step, one printing nothing and exiting 0. A suite that fails to reject either is flagged
(`strength.weak`, "These cases cannot distinguish a constant program"). Rejection needs a real disagreement; authorized
deviations do not count.

## Generated cases and shrinking

`generators: [{kind, count, seed, template, items, separator}]` with kinds `integers` (boundaries such as 0, +-1,
2^15, 2^31, 2^63 and random magnitudes), `decimals` (ties and binary-representation traps such as 0.5, 2.5, 2.675,
1.005, 0.30000000000000004), `strings` (empty, spaces, accents, combining marks, CJK, emoji, newlines) and
`permutations` of `items`. `template` is a case where `{value}` and `{index}` are substituted in any string. Generation
is seeded and the generated cases are listed in the job. A failing generated case is shrunk by proposing simpler values
and re-running both programs for every proposal; a reduction is accepted only if the same channel still disagrees
(`shrunk.steps[*].confirmed_by_rerun`, `shrunk.reexecuted_and_confirmed`). The minimum is local, not global.

## Open

Command normalisation of the environment beyond the defaults, network and clock isolation, process-tree effects other
than the sandbox and database, non-SQLite stores, binary diffing, UI view, concurrency/interleavings and statistical
or coverage-guided generation are not covered. Programs are executed with host privileges, as with every Theseus
command scenario.
