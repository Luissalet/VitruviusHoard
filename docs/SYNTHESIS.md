# Synthesis of rules from examples

Part of Theseus. Implemented in `theseus/synthesis.py`. The target language is the safe expression language of the rules
bank (`theseus/expressions.py`); primitive operations come from its tables and every final candidate is checked through
`Expression.evaluate`. Reference programs run through the same executor as every other Theseus command. Results are
evidence on the examples and on the validation inputs that were executed, never a proof and never a completion claim.

## Flow

`theseus_synthesize` (`POST /api/projects/{id}/synthesis/runs`) starts a background job (`result.kind == "synthesis"`,
read it with `theseus_job_read`).

```json
{"examples": [{"input": {"x": 10}, "output": 12.1}, {"x": 0.5, "output": 0.61}],
 "rejected": [{"input": {"x": 4}, "output": 16}],
 "reference": {"argv": ["python", "legacy.py"], "encode": "text", "decode": "auto"},
 "domain": {"x": {"kind": "decimals", "min": 0, "max": 500, "places": 1}},
 "max_size": 8, "time_budget_seconds": 20, "max_rounds": 8, "samples": 30, "max_reference_runs": 300, "seed": 1,
 "max_splits": 1,
 "save_rule": {"statement": "Prices carry 21 percent VAT rounded half up.", "evidence": [{"file": "billing.cbl", "function": "ADD-VAT"}]}}
```

Variables are the input keys (or `variables`); they must not be helper-function names. Values are numbers, text or
booleans, and all outputs have one type. `rejected` lists outputs the expression must not produce for an input.

## Search

1. Bottom-up enumeration by expression size: variables, small constants and constants harvested from the examples (stable
   ratios, differences and integer outputs), comparison thresholds (example inputs, round numbers and midpoints between
   them), arithmetic (`+ - * / // %`), `min max abs floor ceil trunc round`, `round_half_up/even/floor/ceiling` with the
   decimal places seen in the outputs, comparisons, `and or not`, and for text `lower upper strip lstrip rstrip + replace
   len number str startswith endswith contains`.
2. Observational-equivalence pruning: of all expressions with the same values on the example inputs only the first
   (smallest, earliest) is kept. Expressions made only of constants are not generated.
3. The first size with an expression matching every example (numbers within 1e-9 relative) and none of the rejected
   outputs wins. When none exists by size 3 to 5, conditionals `a if c else b` are assembled from the simplest piece for
   each example subset (`max_splits` nesting levels, default 1). The size reported is the node count.
4. Ties are broken by enumeration order (for rounding, half-up before half-even), so examples should include ties when
   the rounding mode matters; the validation inputs also probe boundaries.

## CEGIS validation

With a `reference` (an argv command, or a Python `callable` run in a batch subprocess; `encode` `text` = one value per
line, `json`, `json_object`; `decode` `auto`, `json`, `text`), each round generates validation inputs from the `domain`
strategies (inferred from the examples and reported when not given), plus boundary points around every numeric constant of
the candidate and the domain edges, runs the reference on them and compares. Every disagreement (up to three per round)
becomes a new example and the search restarts. The loop ends with `validated_against_reference` when a round finds no
disagreement, or on the round, reference-run or time budget.

## Result

`summary.status`: `validated_against_reference`, `consistent_with_examples` (no reference), `consistent_with_examples_unvalidated`
(validation budget ended), `no_expression_found`, `budget_exhausted`, `refuted_within_budget`. Fields: `expression`, `size`,
`examples_used`, `examples_added_by_validation`, `validation` (rounds, inputs checked, reference runs, reference errors,
domain, per-variable coverage, last-round inputs, per-round log) and on failure `closest_candidates` with `matches`, `of`
and their counterexamples `{input, expected, got}`.

## Rules bank

`save_rule` stores the expression as a rules-bank `hypothesis` (tag `synthesized`, examples marked `source: synthesis`).
When the reference is an argv program with text encoding and numeric or text variables, the rule also gets an executable
check (`abs(number(stdout) - (expression with number(stdin)...)) <= 1e-9`, cases from the examples and last validation
inputs), so `theseus_rules_check` can promote it to `observed` or contradict it. Saving never sets a status other than
hypothesis.

## Limits

Only the safe expression language is searched, up to `max_size` (at most 12) within the time and 150000-candidate budgets;
conditionals are assembled from at most `max_splits` levels and are not proven smallest; harvested constants cover simple
ratios, offsets and round thresholds, so arbitrary constants must appear in the examples; text synthesis is basic (no
slicing or regular expressions); validation runs the reference once per input for argv programs; a validated expression may
still differ from the reference on inputs that were not generated.
