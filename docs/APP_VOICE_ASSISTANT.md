# Voice assistant for app forms

Call `app_project_add_voice_assistant` once for an existing application page. Supply the project ID, current source revision, HTML source path and a JSON Schema object. `form_selector` is a CSS selector that matches one rendered form and defaults to `form`. Property names match the form controls’ `name` values.

```json
{
  "id": "<project id>",
  "expected_revision": "<current revision>",
  "page": "pages/index.html",
  "form_selector": "#booking",
  "schema": {
    "type": "object",
    "properties": {
      "room": {"type": "string", "title": "Sala", "enum": ["terraza", "patio"]},
      "seats": {"type": "integer", "title": "Plazas", "minimum": 1}
    },
    "required": ["room", "seats"]
  }
}
```

Use field titles and optional `aliases` in the page’s language to give Boltagon words to listen for. For a select or radio group, supply enum values that match the controls’ values. The tool saves a regular source revision and returns an `app_project_undo` call. Repeating the same installation leaves the revision as it is.

Open the project through `app_project_preview` and use **Speak** or type in the panel. Vitruvius takes the current values from the form each turn. It applies validated, cited values through the controls’ usual input and change events. The panel asks about missing or unclear fields. A correction such as “no, mejor cincuenta” can revise the most recently changed field. Set `allow_submit` to enable native form submission after a separate “I confirm” or “sí, confirmo” turn and successful form validation. The project owns submission and its result.

On a new preview, Vitruvius discovers the voice service as part of the first request and reuses the discovered route for later turns. The same behaviour applies to assistants already saved in projects.

For generated forms, Vitruvius can give the configured family model up to three seconds to extract required values left open by the dictation rules. It checks proposed values against the form's types and options and looks for their evidence in the current instruction. For multiple possible choices it asks which one to use. When the model is unavailable, the assistant still asks for the missing fields and says that model interpretation was unavailable. The turn trace shows separate timings for rules and model. Existing project copies can pick up this change with `app_project_refresh_voice_assistant` and its undo receipt.

In Canvas and Applications, the embedded preview can request microphone access for the origin serving the project. Grant access if the browser prompts you when you choose **Speak**.

The reply reads back the values cited and validated by dictation that are still in the form, including a value the person repeats. It keeps the project’s option labels, uses the page’s language for dates and says a field title once when the option begins with it. Boltagon synthesizes the complete reply, including the values, as requested by the turn.

The panel keeps the whole written reply visible and streams the same reply from Boltagon’s configured Qwen voice. **Turn processing** shows the service, elapsed time and any fallback for the steps used in each turn. The first-audio figure measures from the browser’s detected end of speech to the scheduled first audio at the output device. It is also available locally in the `voice-assistant:latency` event as `detail.firstAudioMs`. It includes the pause used to recognise the end of the turn. The trace stays in the current page session.

The owned preview resolves Boltagon through the family configuration. Set `CYRANO_URL` on the Vitruvius process to use an explicit loopback Boltagon for transcription, dictation and synthesis. The Qwen voice profile and text preparation live in the voice service. If synthesis is unavailable, the full reply stays in writing. If dictation is unavailable, the original form can still be filled manually. Exported projects retain the form and panel source. Their voice and dictation calls need Vitruvius’s preview relay.

## Uso en castellano

La herramienta añade el panel al formulario que coincida con `form_selector`. Usa los nombres `name` de sus campos como claves del esquema y sus títulos o alias para indicar cómo se nombran en voz alta. Abre la vista previa, pulsa **Hablar** o escribe la instrucción. En Lienzo y Aplicaciones, la vista previa puede solicitar el micrófono para el origen del proyecto. Si el navegador pide permiso, concédelo para hablar. Puedes dar varios datos juntos, contestar a una pregunta por el campo que falta y corregir un valor. **Procesamiento por turno** muestra quién transcribe, entiende, ejecuta y habla, así como los tiempos y las reservas. El español y el inglés siguen el idioma de la página.
