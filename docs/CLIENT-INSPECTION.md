# Inspect installed decoder clients

Open **Lectores instalados** in Inspección, select Android or captures, and choose
**Consultar versiones**. This is available without a project or selected file.
The result shows each selected reader, its path, selection source and observed
version output. **Descargar consulta completa** retains file hashes, exact output
bytes, command, exit status and diagnostics as JSON.

The native API is `POST /theseus/api/engines/inspect` with
`{"family":"apktool"}` or `{"family":"pcap"}`. MCP exposes the same action as
`theseus_client_inspect`. It requires the Inspección module to be explicitly ON.
Cold discovery and operation catalogs only inspect availability; they do not run
version commands or start the module.

Android uses the same Java and Apktool selection as resource decoding. Java's
configured home may fall back to PATH; an unavailable configured Apktool JAR is
reported unavailable. PCAP uses the same TShark selection as packet decoding.
capinfos selection is explicit `THESEUS_CAPINFOS`, a companion beside the selected
TShark, PATH, then the system default. The full candidate list records which
source actually supplied the selected file.

Only version commands are executed, in an empty temporary working directory with
no stdin or target path. The selected files are hashed before and after the
observation. Missing clients, nonzero exits, timeout prefixes and files that change
during inspection remain explicit states. Output display may replace invalid
UTF-8; base64 bytes and SHA-256 preserve the exact output. A version probe does
not establish successful artifact decoding or authenticate the publisher.
