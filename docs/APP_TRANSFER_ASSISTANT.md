# Transfer assistant in application projects

The assistant collects a contact or IBAN, an amount in euro cents, a reference and a source account. It asks for the first missing field, presents choices for an ambiguous contact, and checks the current known balance before presenting a review. A correction updates the draft and produces a new review. An explicit confirmation in a later turn sends the validated draft to the project's atomic action. Cancellation clears the draft before any write. The action validates the balance again in its write transaction.

## Add the panel

Call read-only agent tool `app_transfer_assistant_assets`. Save its `files` through `app_project_update` with the current `expected_revision`, along with the layout and transfer page. Keep the returned `app_project_undo` call to revert the edit. Add the returned `stylesheet` and `script` tags to the layout and place `mount` outside the manual transfer form.

Put `data-transfer-scope` on their shared container. Mark the existing controls with `data-transfer-slot` values `source`, `recipient`, `iban`, `amountCents`, and `concept`. Account and contact selectors use record IDs as option values. Text inputs can opt into a contact ID with `data-transfer-value="id"`. Amount inputs show euros with a decimal point in number inputs and the locale separator in text; `data-transfer-value="cents"` selects an integer. The preview cursor points at each changed control and the panel dispatches its normal input and change events. The panel exposes the ready phase after those fields settle so a project's confirmation view sees the same draft.

The project exposes `GET /api/schema`, `GET /api/collections/accounts` and `GET /api/collections/contacts`. An account includes `id`, `name` and `balance_cents`; a contact has `id` and `name`. `POST /api/actions/transfer` accepts `source_account_id`, either `destination_contact_id` or `destination_iban`, `amount_cents` and `concept`. Set `confirmable_by_voice: true` on the action to allow a spoken confirmation. The panel attaches an idempotency key to the confirmed draft. Its `transfer-assistant:receipt` event carries the action receipt so the page can refresh balances, display the receipt or use its undo token.

For a custom integration, set `data-transfer-assistant="manual"`, import `mountTransferAssistant` and pass the container with optional `language`, `loadContext`, `execute` and `onDraft` options. Use `onDraft` to switch a legacy form to the matching recipient mode before its fields are filled. The default language comes from the page. Use `es` for Spain Spanish or `en` for English. The inherited text styles and the CSS variables `--transfer-assistant-accent`, `--transfer-assistant-on-accent` and `--transfer-assistant-radius` match the project theme.

## Local audio

Open the project preview on loopback to grant the microphone. The opt-in Applications iframe allows it from that preview origin. The microphone control starts capture on a click and stops when it detects a pause or when the user chooses **Finish**. It shows provisional transcription separately and only processes a final turn. Typing uses the same dialogue. The browser never invokes browser speech recognition.

In owned previews with the assistant asset, the same-origin `/__vitruvius_preview__/transfer-voice/` route uses the local family transport. It selects the common `dictation` service when it is registered, or uses the Cyrano app contract when the service is absent from the registry. Both routes use the final, validated and cited fields for typed and spoken turns. The panel retains earlier values across turns, applies reported changes, and asks about missing or ambiguous values. When that call fails, the local parser handles the input. Audio in that case uses the common transcription service first. The page identifies the active route. Contact and account names prime transcription in the current session.

The panel displays each reply immediately. Set `VITRUVIUS_TRANSFER_VOICE_MODE` to `cache-natural` (the default), `piper` or `off`. Both audio modes read the fixed Spanish lines from the `frases.json` file in the folder set by `VITRUVIUS_VOICE_CACHE`. Cache mode reads the WAV files in that folder and leaves the turn in writing when a clip is missing. Piper mode requests the shared voice service with the same fixed lines and uses `es_ES-davefx-medium`. Names, amounts and IBANs stay in the written reply and form. The page leaves browser speech synthesis switched off. The exported project carries the panel and written dialogue, and the owned preview supplies audio.

Open **How this reply was processed** to see which services handled the latest turn, how long the recorded steps took and when the page fell back to local parsing or written replies.

The `transfer-assistant:latency` event reports the input and output provider and milliseconds from the detected speech end to capture stop and final text, from final text to reply, from reply to audio and from speech end to audio playback. The event is local to the page. The preview does not save audio in the project. The microphone control source is shared with the local dictation service so its controls, pause detection and cancellation match across consumers.

## Uso en castellano

Abre la página de transferencias del proyecto y usa **Hablar** o el campo escrito. Indica una persona o un IBAN, el importe, el concepto y la cuenta de origen, en una frase o por pasos. Antes de confirmar, revisa el resumen y los campos rellenados. Puedes cambiar un dato con «no, mejor sesenta» o «a Marta no, a María», elegir uno de los contactos propuestos o pulsar **Cancelar**. Para ejecutar la transferencia simulada, confirma en el resumen o di «sí, confirmo» si el proyecto admite la confirmación por voz. El saldo se comprueba de nuevo al confirmar.

Si faltan los servicios de audio, los avisos indican que puedes escribir y leer la respuesta. Usa **Escuchar respuesta** para pedir la lectura en voz alta.
