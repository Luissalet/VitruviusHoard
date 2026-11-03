# Instrument factory and executable explanations

An **instrument** is a small single-purpose tool for an engagement (calculator, viewer, comparator or editor) generated from
a typed spec as an *application project* (`docs/APP_PROJECTS.md`, template `instrument`): source kept with revisions, tests
generated, standalone export, no model and no Vitruvius needed to run it. Tools: `instrument_create`, `_list`, `_get`,
`_update`, `_compute`, `_explain`, `_check`, `_export`. REST: `/api/instruments`. Code: `vitruvius_hoard/instruments.py`,
`instrument_runtime.py` (the runtime), `instrument_page.py` (the page).

## Spec

```json
{"name": "Price with VAT", "kind": "calculator", "description": "...",
 "inputs": [{"name": "net", "label": "Net price", "type": "number", "unit": "EUR", "min": 0, "max": 100000},
            {"name": "qty", "type": "integer", "min": 1, "default": 1},
            {"name": "width", "type": "number", "unit": "cm", "to_base": 0.01},
            {"name": "region", "type": "choice", "choices": ["ES", "PT"], "default": "ES"}],
 "operations": [{"name": "pct", "params": ["amount", "percent"], "formula": "amount * percent / 100"}],
 "steps":   [{"name": "subtotal", "formula": "net * qty", "unit": "EUR"}],
 "outputs": [{"name": "vat", "operation": "pct", "args": ["subtotal", "vat_rate"], "decimals": 2}],
 "invariants": [{"name": "total never below base", "expression": "total >= subtotal"}],
 "examples": [{"name": "plain", "inputs": {"net": 100}, "expected": {"total": 121}, "tolerance": 1e-9}],
 "rows": [], "views": ["form", "explainer"]}
```

- **Inputs**: `number`, `integer`, `text`, `choice`, `boolean`; `unit` is shown; `to_base` converts a numeric input to the unit
  the formulas use (cm to m: 0.01); `min`/`max`/`step`/`default`/`required`.
- **Formulas** (steps, outputs, operations, invariants): numbers, names of inputs and earlier steps/outputs, `+ - * / // %`,
  comparisons, `and or not`, `x if c else y`, `min max abs round floor ceil sqrt pow clamp log exp`, and your operations.
  `**`, attribute access, imports and any other syntax are refused when the spec is validated; `pow` exponents are bounded.
  Outputs are rounded to `decimals` (default 2); steps to 4. Division by zero is reported, not crashed.
- **Kinds**: `calculator` (form to results), `comparator` (two option columns, outputs side by side with the difference),
  `viewer` (read-only table of `rows`, outputs computed per row), `editor` (editable rows, add/remove, download JSON).

## What is generated

`instrument.json` (the spec; the only place formulas live), `server.py` (stdlib HTTP server: page, `/api/spec`,
`/api/compute`, `/api/table`, `/api/examples`, `/explain`), `pages/index.html`, `tests/test_instrument.py`, `project.json`,
`layout.html`, `README.md`, `LICENSE`. The tests (`python tests/test_instrument.py`, unittest) include one test per spec
example, one per invalid-input case derived from types and ranges (text in a number, below min, above max, not whole,
not a choice, missing required, unknown input), and one per invariant over the examples.

`instrument_create` returns `warnings` when a spec example is not satisfied by its formulas (expected versus computed per
output) or when there are no examples; the project is still created so the spec can be fixed, and the generated tests fail until then.
`instrument_list` shows each instrument with its spec and example status. `instrument_update` regenerates every generated file
from a changed spec as a new retained revision (same source gives the same revision id).

## Checking by running it

`instrument_check` exports the project, extracts the ZIP in a temporary folder, then, with `python -I` and no Vitruvius on the path:

1. runs `tests/test_instrument.py`;
2. starts `server.py`, checks the page is served and recomputes every spec example over HTTP;
3. compares the explainer with the computation (below), for every example and any `inputs` you pass.

`instrument_export` does the same check and returns the ZIP (`download_url` on REST). Nothing here uses a model.

## Executable explanations (minimal)

`/explain` in the instrument (and `instrument_explain` / `POST /api/instruments/{id}/explain`) shows a manipulable worked
example: every input, intermediate step and output with the formula that produced it, invariants (holds / violated), number
fields and sliders that recalculate. The numbers are produced by the same `compute()` as the instrument: no parallel formula.
Each number carries `data-name`, `data-kind` and `data-value`, and `instrument_check` parses the explainer served by the
exported server and requires every step and output to equal `/api/compute` of the exported server and Vitruvius's own result.

Limits: the explainer is rendered on the server and recalculates by submitting the form (no animation or step-through of
intermediate states beyond the list); invariants are checked at the inputs you try, not proved; the instrument keeps no data
(it is not the record store of `app_project_call`); the stdlib server is a local tool, not a hardened public service.
