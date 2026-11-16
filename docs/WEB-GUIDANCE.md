# Web guidance

A vendored library of modern web platform guides, with search, a reader and a legacy-pattern scan. It is cold: it reads files,
needs no engine or data store, and works with every module OFF.

## Guides

`vitruvius_hoard/webguide/guides/<category>/<id>.md` holds 210 guides in 17 categories (accessibility, built-in-ai, css, forms, html,
js, performance, privacy, pwa, security, ui-atoms, ui-behaviors, ui-components, user-experience, visual-design, wasm, webmcp). The id of
a guide is its file name; its title is the first heading and its summary the first paragraph. The files are an unchanged copy of an
Apache-2.0 collection (see `UPSTREAM.md`, `LICENSE-Apache-2.0.txt`).

| Tool | What it does |
| --- | --- |
| `web_guide_search` | `query` (2-5 words, English or Spanish), optional `category`, `limit`. An empty query lists all guides with the categories. |
| `web_guide_read` | `ids`: one or several comma-separated ids. Returns each guide's Markdown; unknown ids are reported in `missing`. |
| `web_legacy_scan` | `path` (folder or file) or `sources` (`[{name, text}]`), optional `include_vendor` and `max_files`. |

Search ranks by words in the id (6), title (4) and opening paragraph (2), with a table of Spanish words (diálogo, tabla, paralaje...).
The reader rewrites the command-line cross-references of the guides into `web_guide_read` calls.

## Legacy scan

`webguide/legacy.py` holds 30 rules as data: a pattern, the kinds of file it reads (html, css, js), optional file-level conditions
(`present`, `absent`, `min`), the guide with the native alternative (English and Spanish) and `keep_when`, the case in which the old
pattern is the right call. A page with `<dialog>` is not flagged for div modals; `min-height:100dvh` suppresses the `100vh` finding.
Folders skip `node_modules`, virtual environments, build output, `vendor` folders, minified and bundled files and files over 800 KB.
Findings are candidates to confirm, not defects.

## In the critique

`webcraft/legacy-pattern` runs the same rules over the page HTML and its CSS. Each finding names the guide in its fix and cite
(`[vitruvius: webguide/<id>]`), and `design_critique` returns `web_guidance` with the guides to read.

## REST and screen

`GET /api/webguide?query=&category=&limit=`, `GET /api/webguide/{id}`, `GET /api/webguide/legacy-rules`, `POST /api/webguide/scan`.
The screen is `/craft/` (tabs *Guías web* and *Buscar patrones antiguos*).
