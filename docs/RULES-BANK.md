# Legacy rules bank

Part of Theseus. Implemented in `theseus/rules.py` and `theseus/expressions.py`; it reuses the equivalence runner
(`theseus/equivalence.py`) for sandboxed execution, case generators and shrinking. No second executor exists.

**Scope.** `observed` means: the rule's predicate held on every applicable listed and generated case, run against the
reference program in fresh sandboxes. It is evidence on those cases, never a proof, and never a statement about Theseus
completion. A rule without an executable check stays a `hypothesis` for ever.

## Rule

| Field | Meaning |
| --- | --- |
| `statement` | The business rule in the user's own vocabulary (required). `title` is optional. |
| `status` | `hypothesis` (proposed, untested), `observed` (confirmed by executions), `contradicted`. Only `theseus_rules_check` changes it; saving can only propose hypotheses. |
| `evidence` | Code references already known to the project: `{artifact, file, lines: "120-134" or [120,134], function, note}` (at least one of artifact, file, function). |
| `examples`, `counterexamples` | Free text or objects. Entries with `source: "rules_check"` are written by checks and replaced by the next check; yours are kept. |
| `check` | Optional executable check, below. |
| `history` | Every status change with time, reason and the job that caused it. Changing the check resets the status to `hypothesis` (recorded). |

## Executable check

```json
{
  "reference": {"argv": ["python", "legacy.py"], "env": {}, "timeout_seconds": 30},
  "predicate": "int(stdout) <= int(stdin)",
  "when": "int(stdin) >= 0",
  "cases": [{"name": "small", "stdin": "50"}],
  "generators": [{"kind": "integers", "count": 30, "seed": 1, "template": {"stdin": "{value}"}}]
}
```

`cases` and `generators` are exactly the equivalence suite cases/generators (input files, SQLite seeds, multi-step
sequences, integers/decimals/strings/permutations). `when` is an optional precondition; cases where it is false are
skipped. The predicate sees `stdin`, `args`, `files` (input files as text), `exit_code`, `stdout`, `stderr`,
`output_files` (text files the program wrote), `steps` (list of per-step dicts), `value` and `index` (generated case).
Multi-step cases expose the last step as the top-level variables.

### Expression language

Parsed with `ast` and run by a whitelisting interpreter; nothing is ever passed to `eval`/`exec`. Allowed: literals,
arithmetic (`+ - * / // % **` with small exponents), comparisons, `and/or/not`, `in`, conditional expressions, indexing,
slicing, list/tuple literals and calls by plain name of: `len abs min max sum int float str bool sorted any all floor ceil
trunc sqrt round round_half_up round_half_even round_floor round_ceiling lower upper strip lstrip rstrip startswith
endswith contains replace split join lines words count regex_search regex_match regex_findall regex_sub number`. Rejected
at save time: attribute access, imports, lambdas, comprehensions, f-strings, keyword arguments, other names or calls,
oversized expressions. Data errors (for example `int("abc")`) become `error` outcomes and block promotion.

## Check semantics (`theseus_rules_check`)

A background job (`result.kind == "rules_check"`; read it with `theseus_job_read`):

1. Run the reference program per case and evaluate `when`, then `predicate`.
2. All applicable cases hold (at least one applies, none errored or timed out): `hypothesis` or `contradicted` becomes
   `observed`; up to three examples are recorded.
3. A case breaks the predicate: the check stops at the first one, shrinks it when it came from a generator (re-running
   the program at each step, accepting only values that still break the predicate), records the counterexample and sets
   `contradicted`.
4. Skipped-only, errored or timed-out runs are `inconclusive`: no status change.

## Export

`theseus_rules_export` (optionally filtered by `rule_ids` or `statuses`) returns client-ready Markdown: counts per status,
and per rule the statement, status, code evidence, examples where it holds and the counterexample, plus the status
history.

## Interfaces

Tools `theseus_rules_save`, `theseus_rules_read`, `theseus_rules_check`, `theseus_rules_export`; HTTP
`POST/GET /api/projects/{id}/rules`, `GET .../rules/{rule_id}`, `POST .../rules/checks`, `POST .../rules/export`.

## Limits

No web UI view; rules are not part of the evidence bundle export yet; shrinking only applies to generated cases (listed
cases are reported as given); checks stop at the first counterexample; regular expressions are not protected against
catastrophic backtracking beyond a pattern-length cap; no network/clock isolation beyond the sandbox directory;
`observed` covers executed cases only.
