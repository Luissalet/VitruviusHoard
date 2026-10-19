# Static Android analysis

Add a local APK or DEX artifact, choose **Análisis** and select an Android
operation. The existing `theseus_analysis_catalog`, `theseus_analysis_start`,
`theseus_analysis_records` and `theseus_analysis_record` MCP tools expose the
same operations and retained records as the browser and HTTP API. No APK is
installed, launched or attached by these operations.

| Operation | Parameters and observations |
| --- | --- |
| `android.package` | APK decoded manifest, package name, SDK attributes, permissions, class counts and resource names/types |
| `android.classes` | Literal case-sensitive `query`, `include_inner` (default false), `offset` and `limit` (default null/all); duplicates retained and reported |
| `android.class` | Exact `class_name`; raw member metadata including synthetic members, stable per-name overload indices, DEX prototypes and method locations; optional `include_code` |
| `android.method` | Exact `class_name`/`method_name`, explicit `overload_index` if ambiguous; complete Java reconstruction, declaration without body, or exact complete Smali block with fallback reason |
| `android.references` | Exact class and optional method/overload; incoming containing nodes, full direct raw DEX invokes for each method caller, optional `resolve_lines`, `offset`/`limit` selecting containing nodes |
| `android.resources` | Decode APK resources through local Apktool into the job's new directory; every output file gets a SHA-256 and a derived artifact relationship |

An overload index identifies the reader's stable raw member order for this
input and library version. Its exact descriptor/raw method identity is retained;
indices are not portable symbols across unrelated APK builds. Members are
captured before code generation can hide synthetic methods or inline members.
Class-name ambiguity fails visibly rather than selecting an arbitrary class.

Java code is inferred by JADX, not recovered original source. Static initializers
can be folded into Java fields, so method reads explicitly retain their original
Smali blocks. Native/abstract declarations have no DEX body; absence of such a
body does not establish the implementation or resolution of a native method.

Reference totals count containing nodes, not individual calls. A single caller
can contain multiple direct invoke instructions. Their offsets are DEX code
units within that method, not APK file offsets. `method_code_offset` is the
engine's code-item location within the identified DEX entry; it is not an APK
container offset. Optional Java positions are UTF-16 offsets and one-based
lines in the named decompiled top-level class. Method positions are filtered
by matching enclosing-method metadata; an inlined/omitted method can have no
resolved positions. The raw invoke observations remain independent of those
generated-code positions. Reflection, dynamic loading, JNI and runtime dispatch
can introduce further calls. Static absence is not runtime absence.
Raw-stream availability and completed instruction traversal are recorded
separately; decode failures retain partial invokes and their diagnostic.
Optional Java position failures retain the raw observations and an explicit error.

The reader creates and hashes a private input capture, checks the original
again, and deletes the capture after analysis. Full tool stdout/stderr (also
exact base64 bytes), commands, exit status, Java/JAR/reader hashes, versions and
errors/warnings remain in its records. A reader/decoder error preserves its
diagnostic and any partial decoded resource outputs; it cannot certify absent
classes, resources or references. APKTool uses a job-local framework directory,
never the user's global framework cache. Original artifacts remain unchanged.

Evidence export/import retains exact analysis JSON and indexed observations,
including derived artifact relationships. As elsewhere, originals and decoded
artifact file bodies are not embedded in that transfer; their hashes and
historical metadata remain. No live Android connection is transferred.

## Installed engines

Use Java/Javac from `THESEUS_JAVA_HOME` (or JAVA_HOME/PATH), JADX JARs from
`THESEUS_JADX_LIB`, and Apktool's JAR from `THESEUS_APKTOOL`. On the development
workstation the discovered installations are JDK21, JADX1.5.6 and Apktool3.0.3
under `D:/LocalAI/tools`. The catalogue states the missing dependency per
operation. Theseus compiles its own small reader into each analysis directory;
it never calls the CLI/MCP or session server of the reference application.

Original test sources are in `tests/fixtures/android`. The fixture compiler
uses the installed SDK35 build tools/platform36 to produce its own unsigned
APK. Tests read package/SDK/permission/resource values, two overloads, native
declarations, static-initializer Smali, synthetic members and raw repeated
invokes; they also exercise paging, ambiguity, original preservation and
evidence transfer. These are controlled format cases, not validation of every
APK, obfuscator or runtime. [ADB observations and actions](ANDROID-RUNTIME.md)
use their separate explicit runtime flow; static analysis does not run the APK.
