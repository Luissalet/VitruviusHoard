# Local reference collections

Import a manifest from **Gallery → Import local collection**, `POST /api/reference-collections/import`, or `reference_import_collection`. The app reads snapshots and metadata, copies the images into its own gallery, extracts their palette and indexes the text. It does not execute the reference HTML or contact its origin.

```json
{
  "format": "vitruvius-reference-collection/v1",
  "id": "my-studies",
  "name": "Composition studies",
  "entries": [{
    "key": "poster-01",
    "title": "Poster composition",
    "tags": ["editorial", "typography"],
    "files": {"desktop": "images/poster.png"},
    "url": "https://example.com/reference",
    "note": "Compare spacing and heading proportions.",
    "metadata": {
      "source_revision": "historical revision",
      "license": "historical source license",
      "related_patterns": ["editorial"]
    }
  }]
}
```

`files.mobile` is optional. PNG, JPEG and WebP are supported. Missing or invalid files are reported per entry; valid entries remain available and retrying reuses them. Identical entry metadata and actual image bytes yield the same reference ID, including across concurrent imports. Changing an entry creates a new version and leaves earlier references untouched. Duplicate keys within a manifest are errors. Do not add unstable timestamps to metadata if you want identical imports to reuse a version.

`GET /api/reference-collections` and `reference_collections` return collection names and counts. Counts include retained versions. The ordinary gallery and `reference_search` can filter by collection, text, tags, vibe or library. Filters apply across the entire matching collection before pagination. Continue with the returned `next_before` value as `before`, keeping the same filters. The UI's **Load more references** uses the applied filters even when filter fields contain an unsubmitted draft.

`reference_get` returns `analysis.collection`, including source metadata and SHA-256 hashes computed from the copied images. Supplied historical source hashes and observations remain labelled metadata; they are not measurements of a current website. A screenshot does not prove every interaction or audio output works. An absent mobile screenshot is not fabricated.

# Original HTML patterns

`GET /api/design-patterns` / `design_patterns` list eight original studies. `POST /api/design-patterns/generate` / `design_pattern` accept `id`, `text` and a six-digit hex `accent`, and return the complete standalone HTML, parameters and SHA-256. The source uses inline CSS, SVG or Canvas and has no external library dependency. Parameter text remains literal, including markup characters and Unicode.

Open **Critique → Original HTML patterns**. Generate a source, then use the apply button to place it in the editor, or download it as HTML. Generating alone never replaces the editor's current draft. Existing Render, critique and functional assay controls operate on the edited source. The studies demonstrate concrete composition and interaction techniques; they do not simulate financial, acoustic or scientific measurements.

Available patterns: `editorial`, `diorama`, `elastic`, `symmetry`, `constellation`, `halftone`, `pulse`, `holographic`. Drawing and halftone export PNG; constellation mapping exports SVG. Motion studies respect the reduced-motion preference, with explicit controls for replay or playback where applicable.

Applying a pattern retains the editor draft until **Restore draft** is used or the page is left. Imported cards show collection, origin and license status.

Successive pattern applications retain every intermediate editor draft in a stack for this page visit; restore recovers them in reverse order. Structured provenance metadata is rendered as text without discarding the original JSON.
