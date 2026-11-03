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
  tests), `pick` (choose an element of a list model variable; recorded as an index and re-bound from the live
  model on every execution), `request` template (`"{name}"` alone keeps the JSON type), `expect_status`,
  `extract` (local names from `status`/`body`/`headers`/`text`), `update`, `post`, `agree` (with `reference`).
- **invariants**: after every step, over the model, `step`, `action` and `sql` (declared queries, run on a copy
  with a read-only authoriser).
- **setup**: requests run after each start; a failure makes the chain inconclusive.
- `server_errors_fail` (default true): a 5xx fails an action without `expect_status`.

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

## Limits

- Only executed sequences are evidence; coverage shows what never ran. Not a proof of correctness.
- This executes a service; it does not check a declarative protocol model, and a model check does not certify a service.
- Oracles are written by the user. A drafted oracle (by a person or a model) is a proposal until it runs here;
  nothing is inferred from endpoint names.
- Picks are by index into values bound earlier in the same run; reduction does not re-map indices when it deletes
  the step that produced a value, so the minimum is local.
- A base URL without a reset request shares state between runs (a warning is recorded).
- The exported test runs the recorded target command; select another version with `THESEUS_TARGET_ARGV` or `THESEUS_TARGET_URL`.
