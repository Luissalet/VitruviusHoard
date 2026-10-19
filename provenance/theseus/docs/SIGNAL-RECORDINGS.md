# Offline signal recordings

The native operations `signal.decoders` and `signal.decode` use an installed
free sigrok-cli executable. They appear in Análisis and through the existing
`theseus_analysis_catalog`, `theseus_analysis_start` and record-reading MCP tools.
Set `THESEUS_SIGROK` to select another installed executable. No hardware scan,
acquisition, driver installation or target process is started by these operations.

Select a recorded artifact in Análisis. **Señales · Decodificadores instalados**
lists installed decoder IDs/descriptions; with `decoder` it returns literal
help lines, including required/optional channels, options and annotation classes.
`query` is a case-insensitive literal filter. `offset` and `limit` select matching
lines; null means all remaining lines. Line numbers refer to full engine output.
The full output and stderr remain retained even when the selected page is empty.

**Señales · Decodificar grabación** accepts an explicit decoder stack:

```json
{
  "decoder_stack": ["uart:rx=0:baudrate=9600"],
  "input_format": "binary:numchannels=1:samplerate=96000",
  "annotations": "uart=rx-data",
  "line_offset": 0,
  "line_limit": null
}
```

Decoder stack entries follow the installed engine's decoder/channel/option
grammar, available through discovery. `channels` optionally selects physical
recording channels. `input_format` may be omitted for a self-identifying format.
Annotation selection uses the decoder's reported class names.

The worker captures one private job-owned input with its exact original hash,
decodes it fully, then removes that capture. `line_offset`/`line_limit` page
display output after decoding; they neither shorten the input nor count samples
or annotations. The default is 50 output lines; null selects all remaining lines.
The engine's full stdout/stderr are preserved as text and exact base64 bytes,
along with command, exit code, tool hash/version and input hash. Recognized sample
ranges retain their literal decimal endpoints and the engine's endpoint convention.

`status: decoded` means the decoder completed, not that an analyst's protocol
interpretation is proven. `decoder-error` retains the failed invocation and
diagnostics; it does not establish protocol absence. An analysis job can finish
retaining that failure. Discovery can likewise report installed-decoder loading
warnings: a list is not proof that every installed decoder works.

Original synthetic UART fixtures encode `A5` as 8N1 logic at ten samples/bit.
Real installed-engine checks verify data `41`/`35`, ranges `30-110`/`130-210`,
help/filtering, full decoding with paged/empty windows, missing engine/decoder,
private capture cleanup, original preservation and portable evidence import.
MCP and normal browser flows use the same worker and retained records.

The official Windows package is extracted to its own tool directory; the
installer is not executed and no system PATH or driver settings change. The
stable 0.7.2 package's discovery exposed an unrelated signature-decoder syntax
failure. The official 0.8.0-git-f44dd91 build loads its complete decoder listing
and signature help without stderr and preserves the tested UART result. Both
package identities and observed differences are retained with the installation
receipts. sigrok is a separately installed generic decoder, not a relay to the
reference reverse-engineering application's CLI/MCP.
