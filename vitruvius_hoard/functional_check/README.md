# Vitruvius functional page checker

The measuring, planning, execution and report core is maintained inside Vitruvius. Its initial source is the installed `assay-ui` 0.1.4 distribution, carrying the MIT notice retained in `LICENSE-MIT`; `PROVENANCE.json` records the original module hashes. No external Assay package, executable, repository checkout or future compatibility is needed.

`page_check` and the historical `page_assay` tool share the same normal service. REST uses `/api/page-check` with `/api/assay` retained as an alias. The owned Python worker launches the browser through Vitruvius's existing family browser selection. Playwright and an available Chromium/Edge/Chrome remain ordinary browser dependencies.

Inputs can be HTML, a URL, a local page or a saved render. The derived cases describe observable behavior. Optional `criteria` add explicit requested outcomes with `id`, `what`, `acts`, `expect` and `control`: `expect.want` requires visible text, `expect.unchanged` checks stable state and `expect.painted` checks canvas output. Case origins remain explicit. A counter that is supposed to increase can therefore fail when its button does nothing, even though a generic coverage case cannot infer that requirement.

Results include measured controls, executed cases, failures and an unchecked count. Unchecked cases do not produce a successful `works` verdict. A successful run proves only the reported cases; automatic coverage alone cannot establish every control's intended behavior. No model generates or grades these cases.

The worker runs in the existing process boundary and retains the prior timeout, source recovery and UI flow. Caller source files remain unchanged. Explicit criteria are stored in the Hoard's data directory, including when the checked page lives elsewhere.
