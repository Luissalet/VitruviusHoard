# Stateful sequences against a real HTTP service (Theseus)

Request this enables: "This quote service fails when editing, confirming and retrying. Find a minimal sequence that
breaks its rules and give me an executable regression."

## Recipe

```json
{
  "name": "quotes",
  "target": {"argv": ["{python}", "/abs/path/quotes_v1.py", "--db", "{sandbox}/quotes.db", "--port", "{port}"],
             "ready": "/health"},
  "watch": {"sqlite": "quotes.db", "tables": ["quotes", "lines", "charges"]},
  "queries": {"charges": "SELECT COUNT(*) FROM charges"},
  "model": {"quote_id": null, "state": "none", "line_ids": [], "key": "", "charge_id": "", "charges": 0},
  "actions": [
    {"name": "create_quote", "pre": "quote_id == None", "params": {"customer": {"kind": "text", "min_len": 1}},
     "request": {"method": "POST", "path": "/quotes", "body": {"customer": "{customer}"}},
     "expect_status": 201, "extract": {"new_id": "body['id']"}, "update": {"quote_id": "new_id", "state": "'draft'"}},
    {"name": "remove_line", "pre": "state == 'draft' and len(line_ids) > 0", "pick": {"line": "line_ids"},
     "request": {"method": "DELETE", "path": "/quotes/{quote_id}/lines/{line}"}, "expect_status": 200,
     "update": {"line_ids": "line_ids[:line_index] + line_ids[line_index + 1:]"}, "post": ["..."]},
    {"name": "retry_confirm", "pre": "state == 'confirmed'",
     "request": {"method": "POST", "path": "/quotes/{quote_id}/confirm", "headers": {"Idempotency-Key": "{key}"}},
     "expect_status": 200, "post": [{"name": "same charge on retry", "expr": "body['charge_id'] == charge_id"}]}
  ],
  "invariants": [{"name": "one charge per confirmation", "expr": "sql['charges'][0][0] == charges"}],
  "runs": 25, "max_length": 8, "seed": 5
}
```

The full demo recipe is `theseus_tests/stateful_fixture.py` (`quotes_recipe("v1")`).

- **target**: a command started per run in a fresh sandbox on a free port (`{python}`, `{sandbox}`, `{port}`;
  the port is also in `PORT`), optional `files` and `db` seed; or `{"base_url", "reset"}` for a running service.
- **model**: named variables with initial values. Names `status`, `body`, `headers`, `text`, `sql`, `step`,
  `action` are reserved.
- **actions**: `pre` (safe expression over model, params and picks), `params` (seeded strategies, as in property
  tests), `pick` (choose an element of a list model variable; recorded as an index, or as the producer of the
  value, and re-bound from the live model on every execution), `request` template (`"{name}"` alone keeps the JSON type), `expect_status`,
  `extract` (local names from `status`/`body`/`headers`/`text`), `update`, `post`, `agree` (with `reference`).
- **invariants**: after every step, over the model, `step`, `action` and `sql` (declared queries, run on a copy
  with a read-only authoriser).
- **setup**: requests run after each start; a failure makes the chain inconclusive.
- `server_errors_fail` (default true): a 5xx fails an action without `expect_status`.

## Picks by producer step

Every generated step carries a stable `id` (`s1`, `s2`, ...; it does not change when reduction removes steps). When
a pick chooses a value that an earlier response produced (an extracted value that entered a model list in its own
step), the sequence records `{"picks": {"line": {"from": "s2", "var": "line_id"}}}`: the value extracted as
`line_id` by step `s2`, whatever its position in the list is now. Any other element is recorded as an index, as
before. Both forms are accepted everywhere; sequences without ids (recipes, stored jobs and exports of earlier
versions) replay unchanged. A hand-written sequence may add `id` to its steps and use producer picks.

- Execution resolves the pick from this lane's own responses (target and reference separately), so a replay on another
  version binds that version's identifiers. If the producer did not run or its value is no longer in the list, the
  step is `invalid` with the reason (`pick line: the line_id produced by step s2 is no longer in line_ids`); a
  malformed or forward reference is refused before running (`replay` answers 400 / `ValueError`).
- Reduction re-maps picks when it removes the producing step: the pick is rebound to the nearest earlier surviving
  producer of the same pool and, separately, to the earliest one; both candidates are run and either may be kept. If no
  producer survives before the picking step the candidate is discarded without running. Parameter reduction also tries
  earlier producers, the analogue of lowering an index. A second route drops steps from the end before ddmin and the
  shorter result wins, because a removal order can strand ddmin in a local minimum.
- Quotes demo, seed 5, `max_length` 8: the original has 6 steps. Index picks reduced it to 5 (after one line was
  removed, index 0 pointed at the other, cheap line and rounding hid the defect); producer picks reduce it to 4
  (`create_quote`, `apply_discount`, `add_line`, `remove_line` with the pick on the line step), which is the true
  minimum for the signature `remove_line / total after edit`: it needs a draft quote, a line, a discount and the
  removal, since without a discount the v1 arithmetic gives the expected total.

## Outcomes and evidence

`passed`, `failed` (kinds `http_status`, `crash`, `timeout`, `transport`, `extraction`, `postcondition`,
`invariant`, `reference`), `invalid` (a precondition no longer holds: the candidate is discarded), `inconclusive`
(start, reset, setup or reference preparation failed) and `error` (an oracle could not be evaluated). Each
violation states its evidence (`http`, `sqlite`, `reference`, `model`, `process`) and the value of every operand.
Each step records the HTTP request and response separately from SQLite row changes (added/removed/changed per
table) and file effects (`watch.files` globs).

## Tools, REST and demo

| Tool | REST |
| --- | --- |
| `theseus_stateful_recipe_save` | `POST /api/projects/{id}/stateful/recipes` |
| `theseus_stateful_recipe_read` | `GET /api/projects/{id}/stateful/recipes[/{recipe_id}]` |
| `theseus_stateful_run` | `POST /api/projects/{id}/stateful/runs` (job; read with `theseus_job_read`) |
| `theseus_stateful_replay` | `POST /api/projects/{id}/stateful/replay` |
| `theseus_stateful_export` | `POST /api/projects/{id}/stateful/export` |

1. `theseus_stateful_recipe_save {project_id, recipe}`; 2. `theseus_stateful_run {project_id, recipe_id}` and poll
`theseus_job_read` until `summary.verdict`; the counterexample gives `original`, `minimal`, `signature`,
`explanation`, `trace`, `reproduce.seed` (seed with `runs: 1` regenerates the original sequence) and `coverage`;
3. `theseus_stateful_replay {project_id, job_id, target: {"argv": [... quotes_v2.py ...]}}` reports
`reproduces_original_signature: false` on the fixed version with fresh identifiers; 4. `theseus_stateful_export
{project_id, job_id, output_dir}` writes `test_quotes_regression.py`, `regression.json`,
`theseus_stateful_adapter.py` and `theseus_expressions.py`; `python -m pytest -q test_quotes_regression.py` fails
on v1 and passes with `THESEUS_TARGET_ARGV='["{python}", ".../quotes_v2.py", "--db", "{sandbox}/quotes.db", "--port", "{port}"]'`.

## Language

All five tools and REST routes take `lang` (`en` by default, or `es` for Spanish of Spain); GET routes take it as a
query parameter. It applies to every human-readable text: validation errors, setup and inconclusive reasons,
violation details, explanations, notes and scope. Machine fields (verdicts, outcomes, kinds, evidence, signatures,
JSON field paths) never change. Raw process stderr and expression-evaluator details are data and stay verbatim inside
the translated sentence. The *Secuencias* tab requests Spanish. The exported regression's own messages are English.

## Limits

- Only executed sequences are evidence; coverage shows what never ran. Not a proof of correctness.
- This executes a service; it does not check a declarative protocol model, and a model check does not certify a service.
- Oracles are written by the user. A drafted oracle (by a person or a model) is a proposal until it runs here;
  nothing is inferred from endpoint names.
- A pick of a value that no extractor produced (initial model values, computed ones) stays an index into the model
  list; reduction does not re-map such indices, so the minimum is local for them.
- Reduction is delta debugging plus a drop-from-the-end route, not an exhaustive search: the minimum is local
  (no single step, and no step removable on the two routes, can go), not proven global.
- A base URL without a reset request shares state between runs (a warning is recorded).
- The exported test runs the recorded target command; select another version with `THESEUS_TARGET_ARGV` or `THESEUS_TARGET_URL`.
