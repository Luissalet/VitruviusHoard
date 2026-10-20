# Native firmware and installed runtime adaptation

Theseus analyses must continue inside Vitruvius without the retired checkout or
server. This change incorporates the reviewed synchronous firmware component,
packages the JavaScript runtime dependencies and native scanner, fixes the
mounted original-evidence download, and resolves the Android Java bridge within
the incorporated module. It adds the original Electron acceptance fixture and
its retained-source/IPC boundary tests. No catalogue or database schema changes.

Owner baseline: `c6f0de2a4334bb32ddd3005f22c45f612b4f1b6c`, including approved967.
Source component provenance: `afc7f5de3ec074d63985480705c5578da5ae25b4`
(legacy779 submission26, independently approved). The adaptation, build hooks and
packaging require their own review; that legacy vote does not approve972.

## Changes

- Build the pinned Binwalk3.1.0 library synchronously, retain producer identity,
  ranges and diagnostic gaps, and select the compiled/packaged executable by
  default. Explicit `THESEUS_BINWALK` and external-client fallback remain supported.
- Wheel builds use their own build directory for npm dependencies, engine build,
  production pruning and Cargo output. Include the scanner executable,
  THIRD-PARTY metadata and crate licence files. Use `py3-none-win_amd64` for the
  measured Windows package; it contains an executable independent of CPython ABI.
  Node remains an external runtime; npm/Cargo are build-time requirements for
  this complete payload. Editable development keeps its own local dependencies.
- Keep `/theseus/` in the original imported-evidence download URL. No layout or
  other frontend changes. Resolve Android's maintained Java bridge beneath
  `software_native/engine/bridge/android`.
- Exercise a hidden original Electron44.2.0 application: main Inspector,
  sandboxed/context-isolated preload, renderer CDP, exact UTF-8 sources and four
  independent IPC log results. Close the fixture before source reconciliation
  and portable evidence transfer. Poll the independent Inspector heartbeat
  baseline within its existing 2-second bound, including incomplete JSON writes.

## Author verification

All receipts below are in
`D:/LocalAI/research-inbox/blender-reverse-20261018/`.

| Check | Result | Receipt |
| --- | --- | --- |
| Firmware/scanner/Electron/Inspector area |26PASS,101.102s|`vitruvius-native-area972-20.xml`|
| Android/ELF/qlog/recordings after preparation/correction |67PASS,117.150s|`vitruvius-focal972-20b.xml`|
| Complete Theseus suite, Ghidra explicitly enabled |244PASS,2owned-emulator opt-in SKIP,612.975s|`vitruvius-native-full972-20b.xml`|
| Native owner workspace/shutdown/package/config/global mocks |23PASS,20.110s|`vitruvius-owner972-20b.xml`|
| Native TypeScript and all three frontend builds |PASS|`vitruvius-native-typecheck20.log`, `vitruvius-native-build20.log`, `vitruvius-owner-build972-20.log`, `vitruvius-babel-build972-20.log`|

Pytest used `run-pytest-no-alias779.py` with new nonexistent basetemp directories.
The global-link cases use mock transports only. No Sparks, models, GPU generation,
shared ADB daemon, emulator, real profile or real application was used.

Wheel20b SHA256:
`0aaa6458008f9ea8e195fdd0817c3184c7b668030693b9ac525b7300cb160390`.
Its isolated installation contains1882 npm runtime files,165 Cargo notice
packages and299 licence files. `python -I`, a neutral working directory and
unset `THESEUS_BINWALK`, `NODE_PATH`, `NODE_OPTIONS`, `PYTHONPATH` prove installed
module origins and default scanner selection. Real Node analysis observes the
authored source hash. The installed scanner hash is
`3a11e07081d9ccd42278e2c5b155104e6e4f75ae40fff29683ef596bf1a0bc5f`.

Installed20b real stdio110 and normal owner→Inspection UI verify firmware ranges,
six extracted artifacts/three exact decoded bodies, two-source Electron matching,
findings and historical evidence transfer after closing/removing only the
authored originals. An additional comparison is started in the UI after the
Electron fixture exits. Fresh MCP reads agree. See
`installed972-20b-proof.json`, `installed972-firmware-mcp20-proof.json`,
`installed972-electron-mcp20-proof.json`, `installed972-firmware-ui20-proof.json`,
`installed972-electron-ui20-proof.json` and corresponding PNGs.

Wheel20c SHA256:
`3b01171469b3dfac0e2642b6c7cd0614512b70d49012cfd88dc62d2d6c5c64c8`.
This adds the Android path correction and dev dependencies. A complete bytewise
wheel comparison shows only `theseus/android.py`, METADATA and RECORD differ
from20b; the Node/Rust and all other runtime files are exact. A fresh external
installation performs actual JADX package analysis through the worker, MCP and
another independently UI-started job. The package identity, original hash and
incorporated bridge hash agree. See `installed972-20c-proof.json`,
`installed972-android-mcp20c-proof.json`, `installed972-android-ui20c-proof.json`
and `installed972-android-package-ui20c-final.png`.

Both private installed instances were drained with all modules OFF, active
requests/runtime sessions0; subsequent cold stdio discovery preserved DB/token
hashes. Only recorded private PIDs were stopped after creation-time/argv checks;
port64174 was free, its lock released and both QA tabs closed. See
`installed972-finish20-proof.json`, `installed972-cleanup20.json`,
`installed972-finish20c-proof.json`, `installed972-cleanup20c.json`.
The code-tested head is `7d91b15b3eec6b574b9fe6ee5f7aebd820c4ecac`;
subsequent changes in this delivery document the results only. These receipts
do not assert adoption by the shared installed application or a newer owner head.

## Preserved failures and limits

The initial own wheel lacked npm dependencies and failed with
`ERR_MODULE_NOT_FOUND: zod` (`installed972-20a-proof.json`);20b fixes that measured
failure. The first full run has232PASS,2SKIP,12FAIL: eleven missing pyelftools/
aioquic QA dependencies and one real Android bridge relocation failure. Both
the original XML/log and the succeeding full run remain. The first owner test
run lacked pytest-asyncio; its16 failures remain separate from23PASS after
preparing the documented prerequisites. An installed20c observer initially read
the worker envelope at the wrong level; the original output was read again
without replaying the analysis. A UI observer initially counted the inventory
hash as a third citation; reference/candidate labels were checked exactly.

Theseus remains incomplete and in progress. Source matching and the authored IPC
calls do not prove whole-application equivalence, general IPC causality, firmware
completeness or all optional engines. Thread1058's retained-page-scenario oracle
is subsequent separate work. Review and root's payload/integration window remain
required before shared installation. README packaging text is coordinated with
the concurrent952 owner; no file under that owner's lock was edited here.
