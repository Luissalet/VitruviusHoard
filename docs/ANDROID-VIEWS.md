# Android package and resource views

`android.package` retains the complete decoded manifest, reader observations,
resources and class counts. Set `detail` to `summary` to receive a compact job
delivery with declarations, SDK, permissions, counts, reader identity and manifest
availability. The delivery links to its complete retained document by job ID and
SHA-256. Counts keep the reader's distinction between all and top-level classes;
they are not a claim that every reported class was declared in the original DEX.
Signature metadata does not establish signature verification.

`android.package_view` reads a finished or imported package analysis using
`source_job_id`. It does not reopen the APK or require Java. Select `facet:
"summary"` or `facet: "manifest"`. Manifest `offset` and `limit` count UTF-16 code
units; a page never splits a surrogate pair. A starting offset inside a pair is
rejected, and a limit too small for the next character must be increased. The
result records the parent document digest, total size, next offset and exhaustion.
After evidence import, the summary's action links identify jobs in the receiving
project and its view digest covers that remapped envelope. The complete historical
analysis bytes and original evidence bundle remain unchanged. IDs inside the
summary's literal reader data are not action links and are preserved.

`android.resources` preserves complete decoded files and adds manifest text,
package/version/SDK metadata, available locale directories and normalized string
tables. Use `locale` for the primary table and `locales` for additional tables.
With no primary locale, the default `values/strings.xml` table comes first.
Repeated identical selections are deduplicated; aliases such as `pt-BR` and
`pt-rBR` share the same physical table and retain their requested labels.
Configuration directories such as `values-night` are not language tables.

Plain direct string values retain whitespace and literal entity spelling;
comments are omitted. Empty strings and duplicate names remain occurrences.
Physical UTF-8 reads preserve CRLF and CR in decoded manifests and string values.
Nested markup, CDATA, processing instructions and missing names are counted as
unparsed rather than silently treated as plain strings. Malformed tables have
unknown counts. Missing tables have a known zero count only after successful
decoding; a failed decoder leaves availability and completeness uncertain.

Set `include_strings` to `false` to omit string values and tables while retaining
metadata, the manifest, locale inventory and complete decoded-file observations.
No additional implicit output cap is applied. Metadata uses PyYAML node composition
without constructing tagged objects and preserves numeric scalar spelling.

Use the ordinary **Análisis** form or `theseus_analysis_start` over MCP. Retained
views select **Análisis de origen**; all resulting sections, full downloads and
portable evidence use the existing analysis flow. The APK is inspected statically,
never installed or executed by these operations.

Source acceptance for task 1162 covers 34 area tests, six actual MCP observations,
explicit locale selection and an imported manifest window submitted through the
normal UI. The first author MCP checker confused total with top-level class count;
its failure remains, and the continuation reused that saved package analysis.
Source revision 2 and the installed W2 package have independent acceptance.
The installed check made seven MCP observations and two evidence transfers;
the normal UI selected the second destination's package and displayed a new
140-unit UTF-16 manifest window with exact CRLF, then its Spanish string table.
An independent installed oracle passed four tests, including 90 UTF-16 windows,
lexical XML cases and two transfers while its own original APK was absent.
Full private HTTP documents match the retained bytes. A completed browser
download is not established by this installed check. These finite observations
do not establish general application behavior.

W2 SHA-256: `e63a58672846add8c6d6c2871ffc3aa91b1ab4c6d9b86cf0fce0e07bcf44e375`,
packaged source `a5e4c50bcfab9dac43493750117108e01a9e1b21`. The complete
validation retained 1910 passes, six failures and five skips. The six failed
cases and three retained-document oracles passed unchanged in separate author
and independent nine-case runs. This is composed validation, without a single
green full run or a proven explanation of the original deadline failures.
