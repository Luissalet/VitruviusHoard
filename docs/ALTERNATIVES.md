# Design by comparable alternatives

An **alternatives study** compares options that differ in structure, on criteria fixed before anything is measured, and
keeps the decision with its reason. Tools: `design_alternatives_create`, `_list`, `_get`, `_add`, `_evaluate`, `_criteria`,
`_analyze`, `_decide`. REST: `/api/design-alternatives` (UI: **Alternatives** screen, read-only). Code: `vitruvius_hoard/alternatives.py`.

## What a study holds

- **Brief**: what is designed and for whom (at least a sentence).
- **Criteria** (1 to 12), each with a metric `source`, a `direction` (`max`/`min`; default from the source) and a `weight`.
- **Alternatives** (2 to 12): `page` (`html` or `path`), `app_project` (`project_id`, revision pinned) or `diagram_document`
  (`document_id`, revision pinned). Page source is stored with its SHA-256 so later edits of the file do not change the study.
- A **decision** (alternative, reason, trade-offs accepted) and the **history** of earlier criteria revisions.

## Criteria sources

| Source | Direction | Measured with |
| --- | --- | --- |
| `critique_score` | max | `design_critique` on the render, heuristics only (no vision model, so it is repeatable) |
| `lint_score` | max | `design_lint` score of the render |
| `page_check_failed` | min | `page_check` (failed cases; needs the browser dependency) |
| `contrast_failures`, `contrast_min_ratio` | min / max | text/background pairs of the render against WCAG AA |
| `small_tap_targets`, `dom_size`, `external_libs` | min | render probe |
| `render_ms`, `page_bytes` | min | capture time (varies between runs) and HTML size |
| `diagram_gate_failures`, `diagram_nodes`, `diagram_edges` | min | the diagram's own legibility gates and size |
| `manual` | max | a score within `params {min, max}` (default 0 to 10) **and a written rationale** per alternative |

A computed source must be applicable to every alternative's kind (web sources to pages and app projects; diagram sources to
diagrams); otherwise use `manual` criteria. Application projects are measured through their owned preview; `page_check`
checks the home page the preview serves.

## Structural diversity

Before a study is created (and whenever an alternative is added) the alternatives are fingerprinted from their markup:

- the multiset of element paths (tag, with up to three ancestors), ignoring text, class names, colours, fonts and spacing;
- landmark counts (header, nav, main, aside, section, form, table, lists, headings, controls, media...);
- layout modes found in CSS (grid with its track count, flex row/column, table, float, columns, positioned layers).

Distance = 0.5 path distance + 0.2 landmark distance + 0.3 layout-mode distance. Any pair below the threshold
(default 0.2, `diversity_threshold`) refuses the study with an explanation: three colours or three typefaces are
*variants, not alternatives* (distance 0.00, "same element structure and the same layout modes"). Changing a one-column
flow into a grid does count as structure; changing hex values does not. Application projects use their layout, pages and
stylesheets; diagrams use type, node shapes, degree distribution and size. `check_only=true` reports the distance matrix
without creating anything.

Limits: the fingerprint reads the authored markup and CSS, not the DOM after scripts run, and it cannot judge whether two
different structures are *good* alternatives. It rejects the cheap case; it does not certify the rest.

## Frozen criteria

The first measurement (computed or manual) freezes the criteria. `design_alternatives_criteria` replaces them freely
before that. Afterwards it refuses unless `new_revision=true` with a reason: the study moves to revision N+1, the old
criteria, measures and decision are kept in `history`, and measures of criteria whose definition (source, direction,
params) is unchanged carry over; the response lists what must be measured again (`remeasure`). Weight edits alone do not
invalidate any measure. Adding an alternative later is allowed (it is measured on the same frozen criteria) until a
decision exists.

## Analysis

`design_alternatives_analyze` works only from stored measures:

- each criterion is min-max normalised across alternatives with its direction (best = 1); the score is the weighted sum;
- the **Pareto frontier** is the set not dominated by another alternative (at least as good everywhere, better somewhere);
  `dominated` names the dominators;
- **trade-offs** are sentences with the numbers: "Dashboard is better on Accessibility (7.5 vs 4.6), but yields on Weight
  (900 vs 300)", and "Wizard is dominated by Dashboard: ...";
- `leads` lists, per alternative, criteria where it is best or worst.

`weights` (by criterion id) is a **what-if**: it returns the new ranking, who leads, rank changes, and an `effect` sentence;
nothing is saved and nothing is measured again. The frontier never changes with weights, only the point chosen on it.
`sensitivity_of=<criterion>` sweeps that criterion's share of the weight and reports where the leader changes.

## Decision

`design_alternatives_decide` needs every measure, a reason of at least a sentence, and refuses a dominated alternative
unless `accept_dominated=true` (then the reason should say what the criteria miss). It stores the reason, rank, whether the
choice is on the frontier, the weights used and the trade-offs that involve it. Add `weights` to decide under a what-if.

## Example

```json
{"brief": "Layout for the weekly sales dashboard used on a laptop",
 "criteria": [{"name": "Contrast", "source": "contrast_min_ratio", "weight": 3},
              {"name": "Light page", "source": "dom_size", "weight": 1},
              {"name": "Team fit", "source": "manual", "weight": 2}],
 "alternatives": [{"label": "Dashboard", "path": "C:/work/dashboard.html"},
                  {"label": "Story", "path": "C:/work/story.html"},
                  {"label": "Wizard", "path": "C:/work/wizard.html"}]}
```

Then `design_alternatives_evaluate` (with `manual_scores`), `design_alternatives_analyze`, `design_alternatives_decide`.
