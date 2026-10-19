# Managed declarations and retained native observations

`managed.verify_native` contrasts a retained `managed.native_boundaries` analysis
with completed `binary.analyze_function` observations from the same project.
It is available in Análisis as **.NET · Contrastar declaraciones con nativo**
and through the existing native analysis MCP tools. No CLR load, library load,
target execution or model call is required.

First save the .NET native-boundary analysis. Open each selected original native
artifact in Binarios and run `analyze_function` for the relevant export/function.
The native session may then be closed: the contrast uses its retained document.
Choose the managed source analysis in the contrast form and supply its native
observation job IDs through Parámetros de la operación:

```json
{"native_job_ids": ["the-completed-native-function-job-id"]}
```

MCP additionally passes `source_job_id` to `theseus_analysis_start`, alongside
the managed `project_id`, `artifact_id` and operation name. The normal operation
catalogue describes this schema; no external script or reference CLI is needed.

Both managed and native JSON documents are checked against their receipt hashes.
Native documents must also match their saved original artifact hash and operation.
Each observation becomes deterministic Evidence with its actual artifact path,
hash and provider version. Identical native Evidence from separate jobs is
deduplicated while retaining all source job IDs. The result preserves every
candidate and the managed/native Evidence links. Records and original source
observations remain individually readable and portable through evidence transfer.

Within this static name/module comparison, `verified` means the selected native
observation contains the exact declared function/export name in a compatible
module name. It does **not** prove that the operating system loaded that file,
that the application called it, that its ABI/body matches, or that its behavior
is equivalent. A same-named library is still only the explicitly selected artifact
with its own hash. Decorated candidates are inferred; a module mismatch is
contradicted; missing names or module identity remain unresolved.

No build-local metadata token is inferred to be a native address. Unsupported
native-body/NativeAOT mapping remains unresolved. The result's coverage and
limitations describe only the supplied observations, not all application calls.
Imported results describe historical evidence and do not restore a live engine.

Acceptance compiles an original C# declaration and an original C function into
two synthetic DLL modules. One fixture deliberately has the declared module
basename; it is never substituted for or loaded as a Windows system DLL. Real
Ghidra observes the functions, and positive/module-mismatch cases, duplicate
observations, wrong-operation inputs, modified retained JSON, original-byte
preservation and evidence import are exercised. This establishes the contrast
workflow rather than runtime binding or behavioral equivalence.

Multiple local Theseus instances keep independent browser sessions by port.
Opening production and an isolated instance on localhost no longer overwrites
their browser authentication. Existing bearer clients and legacy cookies remain
accepted; tokens, HttpOnly/SameSite settings and stored project data are unchanged.
