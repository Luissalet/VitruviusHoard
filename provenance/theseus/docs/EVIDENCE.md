# Portable investigation evidence

The project heading offers **Exportar evidencias**. The project rail offers
**Importar evidencias**, accepting the JSON file or its pasted contents and an
optional destination name. Existing projects are never overwritten. Imported
projects identify their historical receipts and link the unchanged source bundle.

`theseus/evidence-1` contains a payload and a SHA-256 manifest. The payload retains
project metadata, artifact inspection identities and original paths, findings
and source references, saved scenario definitions, every job receipt, claims and
handoffs, every indexed analysis record, and available native-analysis JSON
documents. Documents are base64 encoded so whitespace, encoding and their
recorded byte hashes survive transport exactly. The manifest explicitly lists
analysis documents that are missing or have changed since their recorded hash.
Checks establish internal consistency, not trusted authorship or correctness.

Original artifact bytes, native Ghidra project databases and running engine
sessions are excluded. A retained analysis JSON document can be downloaded and
searched after transfer without its original artifact. Reopening a native project
requires a local original artifact and a fresh analysis; an imported session is
historical. Imported source paths and command arrays are preserved as references
and may be unavailable on the destination machine.

Import validates document hashes and project/evidence/dependency relationships
before storage, assigns fresh project/artifact/finding/scenario/job/claim/handoff
identities and remaps their links. Dependency cycles and broken links are
rejected. A failed database write rolls back the project and removes only the
newly created import files. Existing investigations remain untouched. Original
raw analysis records and JSON documents remain exact; source metadata maps their
artifact identities to the imported project. Frozen builder contracts and their
hashes also stay exact; each imported handoff supplies an `id_map` for its original
claim identities. The original complete bundle and a persistent identity map
remain available separately, including for citations embedded in saved prose.

Every imported job has state `imported`, retaining its previous state in
`result.evidence_import.source_state`. It is never replayed or used as current
comparison/oracle coverage. This avoids treating a historical successful receipt
as a fresh verification on a different machine. Review command paths, create a
new handoff if the builder workspace changed, then explicitly run the desired
scenarios and oracle perturbations. No model is involved in transfer or replay.

| MCP tool | HTTP operation |
| --- | --- |
| `theseus_evidence_export(project_id)` | `GET /api/projects/{id}/evidence` |
| `theseus_evidence_import(bundle, name?)` | `POST /api/evidence/import` with `{ "bundle": ..., "name": "..." }` |
| Source bundle download | `GET /api/projects/{imported_id}/evidence/original` |
| Original-to-imported identity map | `GET /api/projects/{imported_id}/evidence/identities` |

The existing `theseus_project_export` and project-export route remain available
as the smaller project record. Portable evidence is an additional format.
