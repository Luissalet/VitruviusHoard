# Property and business-sequence tests

Part of Theseus. Implemented in `theseus/properties.py` and `theseus/strategies.py`. It reuses the equivalence runner
(`theseus/equivalence.py`: fresh sandbox per run, `observe`, cancellation) and the rules-bank expression language
(`theseus/expressions.py`). There is no second executor or evaluator.

**Scope.** `no_counterexample_found` means the properties held on the generated inputs and sequences that were executed,
with the seed and run counts shown in the job. It is evidence, not a proof, and says nothing about Theseus completion
(see `software_native/theseus-limits.md`).

## Flow

`theseus_property_run` (`POST /api/projects/{id}/properties/runs`, body `{suite, shrink, shrink_budget}`) starts a
background job (`result.kind == "property_run"`); read it with `theseus_job_read`. `shrink_budget` (default 100) is the
number of re-executions allowed per failure. Suites are inline; they are not stored.

## Suite

```json
{
  "target": {"argv": ["python", "export.py"], "decode": "text"},
  "input": {"kind": "lists", "max_size": 5, "of": {"kind": "dicts", "fields": {"id": {"kind": "integers"}}}},
  "runs": 30, "seed": 1,
  "properties": [...], "stateful": [...]
}
```

A program spec is a command (`argv`, `cwd`, `env`, `timeout_seconds`, extra `args`) or a Python callable
`{"callable": "module:function", "path": "dir"}` run in a subprocess (JSON in, JSON out, one value per call). Commands
read the value on stdin encoded by `encode` (`json` default, `text`, `lines`) and their stdout is decoded by `decode`
(`json` default, `text` = output without trailing newline, `lines`). A non-zero exit, timeout or undecodable output is a
`crash` failure.

## Strategies

JSON objects, composable and seeded: `integers {min,max}`, `decimals {min,max,places}`, `text {min_len,max_len,alphabet}`,
`lists {of,min_size,max_size}`, `dicts {fields,optional}`, `one_of {options}`, `tuples {items}`, `constant {value}`,
`booleans`, `sampled_from {values}`. Size grows over the run (edge values such as bounds, 0, +-1 are mixed in). Shrinking
proposes simpler conforming values (towards 0, empty, fewer elements, earlier options); every proposal is re-executed.

## Properties

Common: `name`, `when` (precondition over `input`; false means skipped), `input` (own strategy), `expr`.

| kind | what runs | expression variables | default `expr` |
| --- | --- | --- | --- |
| `invariant` | target on the input | `input output exit_code stdout stderr` | required |
| `roundtrip` | target, then `then` fed the raw stdout of the first step (export then import) | + `first` (decoded step 1; `output` is step 2) | `output == input` |
| `idempotent` | target, then `then` (default the target) on its raw stdout: f(f(x)) | `first`, `output` | `output == first` |
| `metamorphic` | target on `input` and on `transform` (expression over `input`, for example `sorted(input)`) | + `follow_input follow_output` | `follow_output == output` |
| `model` | target and `reference` on the same input | + `expected` | `output == expected` |

Expressions use the safe language of the rules bank (no attribute access, imports or arbitrary calls).

### Warnings

A property whose oracle only compares the program with itself carries a `warnings` entry and the job summary lists it
under `self_comparison_warnings`: a `model` reference with the same command or identical script bytes, an identity
metamorphic transform, a round trip whose second step is the same program, and comparisons whose two sides are the same
expression (`tautology`). The property still runs, but it can only catch defects that differ between the two sides.

## Stateful sequences

```json
{"name": "editor", "program": {"argv": ["python", "editor.py"]}, "init": {"doc": "", "hist": []},
 "files": {}, "db": null, "runs": 30, "max_length": 8, "seed": 1,
 "commands": [
  {"name": "save", "args": ["save", "{text}"], "stdin": "", "params": {"text": {"kind": "text", "min_len": 1}},
   "pre": "true expression over model and params", "update": {"hist": "hist + [doc]", "doc": "text"},
   "post": [{"name": "shows the saved text", "expr": "rstrip(stdout) == doc"}]}]}
```

* The model is a set of JSON variables (`init`). `pre` (model and params) selects applicable commands; `update` assigns
  model variables from the old model and params simultaneously.
* A random sequence of applicable commands is generated, then executed in order in one fresh sandbox; state is carried by
  the program's own files or SQLite database (`files`, `db` seed as in equivalence cases).
* `post` expressions see the updated model variables, `old_<var>`, the params, `exit_code stdout stderr`, `output_files`
  (text of files the step created or modified) and `index`. The first false post (or a timeout) is the violation.
* Shrinking: truncate to the failing step, remove chunks of commands, then shrink parameters. Each candidate must keep
  its preconditions, is re-executed in a fresh sandbox, and is accepted only if the same command violates the same
  postcondition. The result lists `original`, `minimal`, the rendered argv/stdin of each command, the failing step and
  `reexecuted_and_confirmed`.

## Result

`properties[*]` and `stateful[*]` each give `status` (`held`, `violated`, `crash`, `error`, `inconclusive`), run and skip
counts, warnings and `counterexample` `{original, minimal, reruns, budget_exhausted, reexecuted_and_confirmed, failure,
observed}`. Summary verdicts: `counterexample_found`, `inconclusive`, `no_counterexample_found`.

## Limits

No web UI view; no concurrency or interleavings; no clock or network isolation (programs run with host privileges);
callable targets take and return JSON; generation is random, not coverage-guided; minima are local; the stateful model is
updated only by expressions, so behaviour that needs richer models must be written as several commands; `no counterexample
found` covers the executed runs only.
