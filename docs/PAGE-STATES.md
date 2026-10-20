# Page checks by browser state

`page_check` and the retained `page_assay` alias use the same native checker.
Explicit `criteria` can select a viewport and browser media conditions for
each fresh case. Automatic coverage remains available; no model grades it.
REST uses the existing `/design/api/page-check` route in the combined owner.

## Gap comparison

| Check | Existing behaviour | Added explicit behaviour |
| --- | --- | --- |
| Static desktop/mobile render | render_preview already supports multiple widths and lint | Retained; it does not establish the state of an open menu |
| Functional click/fill/keyboard press | Existing derived cases and explicit criteria | Retained |
| Focus | Keyboard press without an explicit focus target/assertion | `focus` action and `expect.focused` selector |
| Hover | Unsupported action and pointer removed before measurement | `hover` action keeps the pointer through the measurement |
| Responsive state | Functional cases always opened at1100×760 | Per-case viewport; `no_overflow` checks the document in that state |
| Reduced motion | Render lint detects a CSS media query's presence | Emulate reduce; `no_motion` checks actual running animations |
| Dialog/menu | Generic controls and visible-text criteria | Those same cases can run at the requested viewport/media state |
| Load/layout stability | Render observations already available | Per-case local navigation/paint timing and observed layout-shift sum |

The comparison was informed by the visual/state-check workflow in
`juliobsz/skills` at `ea8f1455` (MIT). No external skill, framework, script
or grading service is required by this implementation.

## Case contract

```json
{
  "id": "mobile-menu",
  "what": "The open menu fits the mobile viewport",
  "environment": {
    "viewport": {"width": 390, "height": 844},
    "reduced_motion": "reduce",
    "color_scheme": "dark"
  },
  "acts": [{"click": "#menu"}],
  "expect": {"want": "Options", "no_overflow": true, "no_motion": true}
}
```

For keyboard testing, use `focus` followed by `press` or a sequence of Tab
presses, and require the actual destination with `focused`. A focus match
alone does not prove that its visual indicator is adequate. Hover cases
can require visible text; purely visual changes still need image inspection.
The checker assigns its normal execution IDs; `what` and `environment`
identify the requested case in its report.

Each returned case includes its environment. Measured state records the
actual viewport, reduced-motion preference, requested focus match, browser
focus-visible state, horizontal overflow, running-animation count, local
DOMContentLoaded/load/first-contentful-paint timings and the sum of observed
layout-shift entries. Missing browser measurements remain unknown, rather
than successful. These observations have no automatic score or performance
threshold; a local layout-shift sum is not a certified Web Vitals result.

`no_motion` means no running animation at the sampled moment. It does not
prove that no animation existed earlier or that all changes in the page
are motion. `no_overflow` concerns the document, not every internal scroll
container or intentional canvas. State checks supplement requested outcomes,
not a claim that every interactive behaviour has been inferred.

## Verification scope

The browser fixture opens five explicit states: keyboard focus, hover help,
mobile panel, reduced motion and a dialog. Its faulty version misses the
keyboard destination, overflows after opening the mobile panel and keeps
animating under reduce. Correcting those three defects makes the five
explicit cases pass. The same fixture exercises the owned subprocess and
normal checker facade. Native API/MCP acceptance is recorded separately;
the fixture does not certify arbitrary pages or LLM visual judgement.
