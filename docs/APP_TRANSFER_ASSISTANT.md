# Transfer assistant in application projects

The assistant collects a contact or IBAN, an amount in euro cents, a reference and a source account. It asks for the first missing field, presents choices for an ambiguous contact, and checks the current known balance before presenting a review. A correction updates the draft and produces a new review. An explicit confirmation in a later turn sends the validated draft to the project's atomic action. Cancellation clears the draft before any write. The action validates the balance again in its write transaction.

## Add the panel

Call read-only agent tool `app_transfer_assistant_assets`. Save its `files` through `app_project_update` with the current `expected_revision`, along with the layout and transfer page. Keep the returned `app_project_undo` call to revert the edit. Add the returned `stylesheet` and `script` tags to the layout and place `mount` outside the manual transfer form.

Put `data-transfer-scope` on their shared container. Mark the existing controls with `data-transfer-slot` values `source`, `recipient`, `iban`, `amountCents`, and `concept`. Account and contact selectors use record IDs as option values. Text inputs can opt into a contact ID with `data-transfer-value="id"`. Amount inputs show euros with a decimal point in number inputs and the locale separator in text; `data-transfer-value="cents"` selects an integer. The preview cursor points at each changed control and the panel dispatches its normal input and change events. The panel exposes the ready phase after those fields settle so a project's confirmation view sees the same draft.

The project exposes `GET /api/schema`, `GET /api/collections/accounts` and `GET /api/collections/contacts`. An account includes `id`, `name` and `balance_cents`; a contact has `id` and `name`. `POST /api/actions/transfer` accepts `source_account_id`, either `destination_contact_id` or `destination_iban`, `amount_cents` and `concept`. Set `confirmable_by_voice: true` on the action to allow a spoken confirmation. The panel attaches an idempotency key to the confirmed draft. Its `transfer-assistant:receipt` event carries the action receipt so the page can refresh balances, display the receipt or use its undo token.

For a custom integration, set `data-transfer-assistant="manual"`, import `mountTransferAssistant` and pass the container with optional `language`, `loadContext`, `execute` and `onDraft` options. Use `onDraft` to switch a legacy form to the matching recipient mode before its fields are filled. The default language comes from the page. Use `es` for Spain Spanish or `en` for English. The inherited text styles and the CSS variables `--transfer-assistant-accent`, `--transfer-assistant-on-accent` and `--transfer-assistant-radius` match the project theme.

## Update an embedded assistant / Actualizar un asistente incrustado

Use `app_project_get` to read the current source revision. Then call
`app_project_refresh_voice_assistant` with `{"id":"<project id>","expected_revision":"<current revision>"}`.
It replaces the product assets for the assistants already embedded in the project and creates a source revision when
a file changes. The page and its existing mount, configuration, action declarations and data are preserved. For forms
created with `app_project_add_voice_assistant`, the same refresh keeps the configured selector, schema and submission policy.

Open the returned revision with `app_project_preview` using `{"id":"<project id>","operation":"start","revision":"<new revision>"}`.
Verify that the panel displays the full reply and, with voice available, starts playback while the reply streams. Run the
returned `undo.tool` with its exact `undo.arguments` to restore the previous sources, then open the restored revision.
An up-to-date assistant returns `changed: false` and leaves the revision unchanged.

Lee la revisión vigente con `app_project_get` y pásala como `expected_revision` a
`app_project_refresh_voice_assistant`. Abre la revisión que devuelve la herramienta y comprueba la respuesta escrita, el
audio de Boltagon y la traza del turno. Para volver a la versión anterior, ejecuta la herramienta de `undo`
con los argumentos de ese resultado y abre de nuevo la vista previa. La actualización conserva la página y los datos.

## Local audio

Open the project preview on loopback to grant the microphone. The opt-in Applications iframe allows it from that preview origin. The microphone control starts capture on a click and stops when it detects a pause or when the user chooses **Finish**. It shows provisional transcription separately and only processes a final turn. Typing uses the same dialogue. The browser never invokes browser speech recognition.

In owned previews, the same-origin voice relay discovers the local Boltagon address from the Hub app catalogue when capabilities are first requested. It caches the address, tool capabilities and visible name for the preview and refreshes the snapshot in the background. Requests then use the versioned loopback endpoints for transcription, end-of-turn decisions, interpretation and reply streaming. A configured `CYRANO_URL` takes precedence. The relay only accepts HTTP loopback addresses and never follows redirects.

The panel retains earlier fields, applies validated and cited changes, and asks about missing or ambiguous values. The local parser takes over if Boltagon cannot complete an interpretation. The trace shows the reason. Names in the current accounts and contacts prime transcription. If the resident cannot transcribe a final recording, the relay can submit one job directly to the discovered Funes reserve. The adaptive partial never starts a reserve job.

The panel shows the full reply immediately and asks Boltagon to read that same text in Spanish or English. The owned preview relays the resident `cyrano.voice/v0` job from the loopback address registered for the voice app, or from `CYRANO_URL` when configured. Each conversation uses the worker's default voice and pins the first engine. The worker normalizes the complete text and uses its own cache for an exact repeated or preloaded line, so cached and freshly generated speech use the same engine and voice. Web Audio starts as soon as the stream has its initial playable buffer and schedules later PCM blocks in order.

If the first audio is still pending at 1.5 seconds, the panel shows that the reply is available in writing while it continues to wait for audio. Late audio plays while that reply is current. A new turn supersedes the previous reply as soon as it is accepted, including while the previous turn is still being interpreted. Each voice request has a browser-generated identifier so the preview can cancel it before stream headers arrive or as soon as the worker sends its job receipt. Microphone capture and leaving the page also stop active playback. After an unavailable service or a change of engine, the reply remains available in writing. **Read reply aloud** replays the full current message. The exported project carries the written dialogue and the owned preview supplies audio.

Set `VITRUVIUS_TRANSFER_VOICE_MODE=off` to keep replies in writing. Earlier saved assets use the fixed-phrase `/speak` route with the existing `cache-natural` or `piper` settings and the manifest in `<VITRUVIUS_PROFILE_DIR>/voice-cache` (or `VITRUVIUS_VOICE_CACHE`). Use `app_project_refresh_voice_assistant` to enable streaming in those projects.

Open **How this reply was processed** to see the endpoint delay, estimated audio upload and local round trip, transcription, interpretation, first audio, cache and any execution. Cutoff and provisional processing can overlap. The relay does not wait for the Hub during the turn.

The preview cursor points to each field as the assistant fills it, expires 2.5 seconds after the move, and clears when the draft reaches review. With reduced motion enabled the fields still fill and scroll into view without a cursor.

The local `transfer-assistant:latency` event reports the providers and the elapsed times in milliseconds. `captureStopToTranscriptMs` is zero when the provisional transcript was already available at cutoff. `hubWaitMs` is zero for the direct route. The preview does not save the audio in the project.

When the turn completes, the preview queues content-free `hoard.trace/v1` spans for the Hub bus. It makes one bounded background submission, with support for the older event endpoint. An unavailable Hub does not delay the reply. Trace data contains stage names, application IDs, outcomes and timings. Set `HOARD_TRACE=0` to disable this export.

## Uso en castellano

Abre la página de transferencias del proyecto y usa **Hablar** o el campo escrito. Indica una persona o un IBAN, el importe, el concepto y la cuenta de origen, en una frase o por pasos. Antes de confirmar, revisa el resumen y los campos rellenados. Puedes cambiar un dato con «no, mejor sesenta» o «a Marta no, a María», elegir uno de los contactos propuestos o pulsar **Cancelar**. Para ejecutar la transferencia simulada, confirma en el resumen o di «sí, confirmo» si el proyecto admite la confirmación por voz. El saldo se comprueba de nuevo al confirmar.

Boltagon lee la respuesta completa en el idioma de la página. Si el audio tarda más de 1,5 segundos, puedes seguir leyendo y oír la respuesta cuando el audio esté listo. Usa **Escuchar respuesta** para volver a oír el mensaje.


Tesela consulta el catálogo del Hub al abrir la vista y guarda la dirección y las capacidades de Boltagon. Durante el turno habla con Boltagon por bucle local. **Cómo se procesó esta respuesta** muestra el corte, la subida y vuelta, la transcripción, la interpretación, el primer audio y la caché. Si falla la interpretación, muestra el motivo del análisis local. Al acabar, la vista envía al bus los identificadores y los tiempos de cada etapa en segundo plano.

## Corte adaptativo / Adaptive cutoff

Tesela activa el corte adaptativo cuando el catálogo anuncia `dictation_end_turn`. Tras 150 ms de silencio obtiene una instantánea provisional del audio capturado y pide a Boltagon la duración del corte y, cuando procede, una interpretación local. Una orden completa, un importe esperado o un contacto inequívoco pueden cerrar a los 650 ms. Una respuesta afirmativa al resumen espera al menos 1500 ms de silencio y se verifica con la grabación final para que dé tiempo a rectificar. Las frases abiertas o incompletas conservan la ventana de 1650 ms. Si vuelve la voz, se cancela la petición y se descarta su resultado, aunque el servidor ya lo hubiera calculado. Una propuesta corta que llega tarde espera el plazo largo. Las consultas provisionales reutilizan la ruta anunciada por el catálogo. El contexto y la versión del formulario quedan fijados al iniciar la captura.

El corte confirmado sólo reutiliza la instantánea del mismo tramo de voz. Terminar manualmente, agotar el tiempo o perder la respuesta provisional siguen usando la transcripción final íntegra. Un catálogo anterior conserva el corte de 1500 ms. Los parciales adaptativos no encolan una transcripción en la reserva. Los comandos locales finales de confirmación y cancelación omiten la petición de interpretación. No se ejecuta ni se reproduce una respuesta provisional. La traza muestra el motivo de la reserva junto al proveedor cuando Boltagon lo comunica.

Tesela enables adaptive cutoff when the catalogue exposes `dictation_end_turn`. After 150 ms of silence it requests a decision and a provisional interpretation for the captured audio. A complete command or an unambiguous requested value can close at 650 ms. An affirmative reply to the review waits for at least 1500 ms of silence and is verified against the final recording to leave time for a correction. Incomplete or open text uses a 1650 ms pause. Resumed speech invalidates the outstanding request. The browser applies the interpretation only after the same recording and form revision are final.
