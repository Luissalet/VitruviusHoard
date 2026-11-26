const API = "/__vitruvius_preview__/transfer-voice";
const VERSION = "cyrano.dictation/v0";
const WIRE_FIELDS = {
  recipient: "destination_contact_id",
  amountCents: "amount_cents",
  concept: "concept",
  source: "source_account_id",
};

function vocabulary({accounts = [], contacts = []} = {}) {
  return [...new Set([...accounts, ...contacts].map(row => row.name.slice(0, 128)))].slice(0, 90);
}

function descriptor(state, context, locale) {
  const {accounts = [], contacts = []} = context || {};
  const rows = collection => collection.slice(0, 60).map(({id, name}) => ({id, name}));
  const {slots} = state;
  const draft = {
    source_account_id: slots.source, amount_cents: slots.amountCents, concept: slots.concept,
    destination_contact_id: slots.recipient?.id, destination_iban: slots.recipient?.iban,
  };
  return {
    version: VERSION, language: locale,
    vocabulary: vocabulary(context || undefined),
    schema: {
      type: "object",
      properties: {
        source_account_id: {type: "string", format: "account", enum: accounts.map(row => row.id)},
        destination_contact_id: {type: "string", format: "contact", enum: contacts.map(row => row.id)},
        destination_iban: {type: "string", format: "iban"},
        amount_cents: {type: "integer", format: "amount_cents", minimum: 1, maximum: Number.MAX_SAFE_INTEGER},
        concept: {type: "string", minLength: 1, maxLength: 140},
      },
      required: ["source_account_id", "amount_cents", "concept"],
    },
    context: {
      field: WIRE_FIELDS[state.next] || "auto",
      contacts: rows(contacts), accounts: rows(accounts), draft,
    },
  };
}

export async function voiceAvailability() {
  const response = await fetch(API + "/capabilities", {signal: AbortSignal.timeout(7000)});
  if (!response.ok) throw new Error("voice_unavailable");
  return response.json();
}

async function understand(body, signal) {
  const response = await fetch(API + "/understand", {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body), signal,
  });
  if (!response.ok) throw new Error("dictation_unavailable");
  const result = await response.json();
  if (result.version !== VERSION || typeof result.raw_transcript !== "string"
      || result.is_final !== true || !result.fields || Array.isArray(result.fields)
      || !["changed", "missing", "ambiguous"].every(key => Array.isArray(result[key]))) throw new Error("dictation_version");
  return result;
}

export function understandText(text, state, context, locale, signal) {
  const deadline = AbortSignal.timeout(3500);
  return understand({...descriptor(state, context, locale), text},
    signal ? AbortSignal.any([signal, deadline]) : deadline).catch(() => null);
}

function audioBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",", 2)[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

export async function transcribeTransferSpeech(blob, {partial, signal, state, context, locale, dictation}) {
  const started = performance.now();
  if (dictation && !partial) {
    const audio = {mime_type: blob.type, data_base64: await audioBase64(blob)};
    try {
      const result = await understand({...descriptor(state, context, locale), audio}, signal);
      const {transcription, rules, validation} = result.timings_ms || {};
      return {text: result.raw_transcript.trim(), interpretation: result, provider: "dictation",
        transcriptionMs: transcription, understandingMs: Number.isFinite(rules) ? rules + (validation || 0) : undefined};
    } catch {
      signal.throwIfAborted();
    }
  }
  const query = new URLSearchParams({language: locale.slice(0, 2), partial: String(partial)});
  const prompt = vocabulary(context || undefined).join(", ").slice(0, 1000);
  if (prompt) query.set("initial_prompt", prompt);
  const response = await fetch(API + "/transcribe?" + query, {method: "POST", body: blob, signal});
  if (!response.ok) throw new Error("stt_unavailable");
  const text = (await response.json()).text.trim();
  if (partial || !text) return {text, provider: "shared"};
  const transcribed = performance.now();
  const interpretation = await understandText(text, state, context, locale, signal);
  signal.throwIfAborted();
  return {text, interpretation, provider: "shared",
    transcriptionMs: transcribed - started, understandingMs: performance.now() - transcribed};
}


export async function speakTransferReply(phraseId, {locale, signal, onFallback, onStart}) {
  try {
    const response = await fetch(API + "/speak", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({phrase_id: phraseId, language: locale.slice(0, 2)}),
      signal: AbortSignal.any([signal, AbortSignal.timeout(14000)]),
    });
    if (!response.ok) throw new Error("tts_unavailable");
    const url = URL.createObjectURL(await response.blob());
    const player = new Audio(url);
    function release() {
      player.pause();
      URL.revokeObjectURL(url);
      signal.removeEventListener("abort", release);
    }
    signal.addEventListener("abort", release, {once: true});
    player.addEventListener("ended", release, {once: true});
    player.addEventListener("error", release, {once: true});
    try {
      signal.throwIfAborted();
      await player.play();
    } catch (error) {
      release();
      throw error;
    }
    const provider = response.headers.get("content-type")?.includes("source=cache-natural") ? "cache-natural" : "shared";
    if (!signal.aborted) onStart(provider);
  } catch {
    if (!signal.aborted) onFallback();
  }
}
