# Retained managed/native verification

`managed.verify_native` compares saved P/Invoke declarations with selected native observations. It reads retained JSON rather than reopening assemblies, native files or engine sessions. A verified result means that the supplied static name and module labels match; it does not demonstrate CLR binding, a call occurring, executable equivalence or a managed-token-to-native-address mapping.

Choose a finished or imported `managed.native_boundaries` analysis as `source_job_id`. Supply one or both native input forms:

- `native_job_ids`: finished or imported `binary.analyze_function` jobs from the same project. Their historical session context is read from storage without connecting to that session. Available profile hashes are checked; absent context stays unknown.
- `query.native_observations`: complete saved Evidence objects supplied by the caller. The maintained Evidence parser authenticates their semantic IDs. The verifier supports native function dossiers and `inspect_macho` export observations; a Mach-O container/header result is a different schema and cannot be relabelled as an export inventory.

For example, the normal MCP analysis call can use these parameters after selecting the project's retained job IDs:

```json
{
  "source_job_id": "managed-boundary-job-id",
  "native_job_ids": ["native-function-job-id"]
}
```

For externally retained Evidence, place the complete objects in `query.native_observations` instead of inventing or editing their hashes. The same parameters are available in the normal analysis form's JSON field. At least one native observation is required. A valid unsupported Evidence operation remains unsupported; an invalid supported payload fails validation. Neither becomes an empty export inventory.

The output preserves complete source observations, exact bytes and SHA-256 for job documents, and serialized values plus hashes for caller-supplied Evidence. Serialization describes the received JSON value, not the original bytes of a file that the caller did not provide. The projection's derived historical carriers remain separate from the recorded producer/profile/revision. Missing producer context is not filled with a guessed identity.

Job inputs must also agree with their registered artifact and any known session's artifact ID and hashes. A file can legitimately change after registration and before native admission: that case requires retained session continuity linking the registered and admitted SHA-256 values for the same artifact. `historical_context` keeps `recorded_artifact_sha256` separately from the observed `artifact_sha256`, with `artifact_binding` equal to `registered-content` or `admitted-source-change`. An incompatible binding, including one delivered in an otherwise valid imported bundle, is rejected before dispatch. Missing session history remains unknown when the registered and observed content agree; it cannot establish a source-change link. These checks use retained metadata without reading the original path.

Evidence's semantic ID excludes the subject's display name and local path. Both labels influence module matching, so the composition also preserves and hashes the complete value. This binds the received labels to the receipt; it does not prove that they describe a real module. Import does not relocate those labels. Two supplied values with the same semantic ID are rejected even if only their labels differ; IDs duplicated between job-derived and supplied inputs are also rejected. Repeated jobs for the same document and context may group their explicit occurrence IDs.

Matching receives job observations first, then supplied Evidence, preserving caller order within each group. The maintained matcher prefers an exact compatible name, then a compatible decorated candidate, then a candidate with unknown module identity, then its first remaining candidate. All candidates remain visible. Ties can depend on input order. A Mach-O leading underscore is normalized once; a Unicode `W` suffix is a decorated candidate only when mangling is permitted. No new consensus rule is inferred from the number of inputs.

Direct result citations resolve through `source_observations`. Original Evidence links remain intact; external citations not included among the supplied sources are listed as unresolved rather than fabricated. `input_scope` preserves declared export coverage separately from the helper's `complete-within-inputs`. Empty partial exports, unsupported Evidence and missing module identity remain different states. None establishes absence of a function from a complete binary.

Task1253 revision2 has independent source and W4 installed acceptance, following research1250. Fresh independent fixtures exercise real registered/admitted native hashes, exact retained records and two transfers without originals; invalid imported bindings fail before job creation. The author also created both input forms and displayed exact records through the installed normal UI. Source, full-suite, package and publication identities remain separate. See [W4 acceptance](../tasks/submission-release23f.md) for the wheel, receipts and finite limits. The original comparison, reconstruction, graph and native-session capabilities remain available; the remaining programme is incomplete.
