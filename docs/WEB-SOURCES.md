# Retained web sources

These operations use browser captures already stored in Vitruvius. They do not
connect to the original browser, fetch a URL, read the old artifact paths or
execute captured code. They are available from **Inspección → Análisis**, the
native REST analysis endpoint and `theseus_analysis_start`; discover schemas
through `theseus_analysis_catalog`.

## Export

Select **Web · Exportar fuentes guardadas** and an observation, scenario or
coverage capture. The source may be finished, failed, cancelled, interrupted or
imported, provided its retained JSON document is available and matches its
receipt hash.

The orchestrator also avoids querying the old artifact path when retaining these
results. Its receipt marks the current original-file availability and freshness
as unqueried (`null`), with `original_source_check` set to
`not-performed-retained-input`. The stored artifact and retained JSON identities
remain explicit; absence and freshness are not inferred from a path that was not
consulted.

`browser.export_scripts` accepts `{"source_job_id":"…"}`. It creates a new job
with a `vitruvius.web-sources/1` manifest and individually registered derived
artifacts. Each script and network response occurrence retains its original URL,
capture-local ID, capture index and availability state. Captured content includes
base64 bytes, full SHA-256, byte length and representation. Inline data-URL maps
are separate occurrences linked to the declaring script. Incomplete, excluded,
missing, altered or ambiguously associated content is never published as captured
bytes. Other verified occurrences remain usable.

Debugger texts and text-mode CDP responses are encoded as UTF-8; they are not
claims about original HTTP wire bytes. Binary-mode responses preserve the bytes
returned by CDP. A response is bound to its unique retained command/reply ID and
request occurrence, then checked against its recorded representation and identity.

Unambiguous HTTP(S) URL paths retain their directory structure under a per-origin
namespace. Query/fragment variants, unsafe Windows path components, inline
content, duplicate paths, case collisions and file/directory collisions use
isolated occurrence paths. The manifest records every mapping. URL metadata never
becomes an unchecked filesystem path. The output directory is new; existing
exports are not overwritten.

The manifest embeds the verified bytes as well as naming derived files. Evidence
transfer can therefore retain it without copying original files or reopening
their paths. An imported capture can be newly exported, and an imported export
can be newly queried. Imported jobs remain historical observations.

## Generated positions

Select **Web · Trazar posición original**, choose an exported analysis and load
its sources. Select the script and a map/response occurrence, then enter a
generated line from **1** and a generated UTF-16 column from **0**.

`javascript.trace_source` accepts:

```json
{"source_job_id":"…","query":{"script_id":"script-000000","map_id":"inline-map-000000","line":1,"column":0}}
```

The worker verifies both selected byte identities. It reads version-3 maps,
including inline indexed sections with composed line/column offsets, sourceRoot,
duplicate source declarations, optional source content, BOM and XSSI framing.
External section URLs are not fetched and fail explicitly. Invalid segments and
indices fail instead of manufacturing a location; the pinned codec uses unsigned
32-bit VLQ representations.

The result preserves **all** mappings at the greatest generated position at or
before the request, including preceding lines. It distinguishes no mapping,
generated-only unmapped segments and mapped segments, and retains each leaf
section path and source occurrence index. Original lines start at1; columns are
UTF-16 units. Declared/resolved source URLs, sourceRoot, original position,
optional name and sourcesContent remain individually readable records.

The script/map pairing is caller-declared. It does not authenticate a deployment
or prove that a source file ran. Inline maps resolve source declarations against
the script's URL; an explicit `importer_url` can supply context for an inline or
otherwise unnamed script.

## Imports

Select **Web · Trazar imports guardados**, load an export and select its script.
`javascript.trace_imports` accepts the source job and a query with `script_id`.
Optional `importer_url`, `import_map` and `import_map_base_url` are explicit
interpretation context. The map base defaults to the importer URL; supply the
document/map base when it differs. Context can be entered in the additional JSON
parameters in the same form.

The native parser records static imports, reexports, literal dynamic imports and
their UTF-16 source positions. URL and import-map resolution preserves query and
fragment components, scope fallback, exact/prefix matching, null blocking and
prefix backtracking failures. Every captured occurrence with the resolved URL
is listed; duplicate observations are not collapsed. Computed imports and
CommonJS `require` retain unknown runtime resolution. A resolved literal and a
matching captured URL do not prove a module was loaded or executed.

The interpretation follows the [HTML module resolution algorithm](https://html.spec.whatwg.org/multipage/webappapis.html#resolve-a-module-specifier).
Map transport and position semantics are described by [ECMA-426](https://tc39.es/ecma426/).
The selected context is retained; it is not reported as an observed browser
import map. Syntax or context errors remain failed jobs with diagnostics.

Original fixtures in `theseus_tests/test_web_sources.py` cover byte identity,
partial content, protocol ambiguity, portable evidence, URL layout, Unicode,
duplicate/unmapped/indexed source positions and imports compared with a real
owned Chromium resolver. They execute only original fixture code and a constant
resolver stub, with no captured target code execution by these readers.
