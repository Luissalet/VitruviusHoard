# Native navigation and address context

Open a native binary session in Inspección → Binarios. **Contexto de navegación**
reads the selected document, current address and procedure containing that
observed address. **Contexto de una dirección** requires an explicit address and
reads its analyzed name, containing procedure, PRE/EOL comments and every
matching bookmark. The same operations are available through
`theseus_binary_call` as `get_navigation_context` and `inspect_address_context`.
Optional `document` selects the bound program by its exact observed identity;
null uses the session's program.

The product composes existing provider reads under the session request lock. It
does not move the cursor, edit annotations, increment the analysis revision or
execute target code. An explicit address lookup leaves the current cursor alone.
Navigation resolves the address actually observed, rather than inferring a
function from a later cursor value. The result is explicitly a sequence of
provider observations, not an atomic cursor snapshot.

`facets` separates an available null from an unavailable observation. A mapped
address outside any function returns `procedure: null` with its observed absence
reason. An absent comment can be available with value null; an unsupported comment
reader remains unavailable with its original provider error. Unknown canonical
address resolution cannot produce an invented empty list of matching bookmarks;
the full observed bookmark inventory remains in its source observation.

`observations` preserves ordered operation names, exact parameter values and
parsed protocol responses, including producer nulls, errors and original IDs.
It does not retain private transport credentials or claim byte-exact wire frames.
Each facet identifies its source observation. Binding records preserve the
observed session, original artifact hash, analysis revision and available profile
hash; a missing profile hash is not invented. Analysis names, comments and
bookmarks describe the selected analysis database, not runtime behavior.

Malformed selectors and primary document/address failures stay failed receipts.
Completed observations before a primary provider failure remain in that receipt.
Interrupted queries remain incomplete; no provider request is automatically
replayed. Unsupported optional facets remain readable alongside available ones.

Use normal analysis records, source citations and JSON downloads to retain a
completed context. Evidence transfer preserves its exact historical JSON after
the native session closes and original files are removed. Import does not open
a provider or certify a current cursor. A new context observation requires a live
explicitly opened native session.
