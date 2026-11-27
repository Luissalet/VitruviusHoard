import {isTransferCommand, isTransferConfirmation} from "./dialogue.js";

const API = "/__vitruvius_preview__/transfer-voice";
const VERSION = "cyrano.dictation/v0";
const CONFIRMATION_SILENCE_MS = 1500;
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
  if (!validInterpretation(result, true)) throw new Error("dictation_version");
  return result;
}

function validInterpretation(value, final) {
  return value?.version === VERSION && typeof value.raw_transcript === "string"
    && value.is_final === final && value.fields && typeof value.fields === "object"
    && !Array.isArray(value.fields) && ["changed", "missing", "ambiguous"].every(key => Array.isArray(value[key]));
}

export async function assessTransferEndTurn(turn, {state, context, locale, signal}) {
  if (state.phase === "ready" && isTransferConfirmation(turn.text)) {
    // Keep listening for a correction and require a fresh transcript of the closed recording.
    return {silenceMs: CONFIRMATION_SILENCE_MS};
  }
  const started = performance.now();
  const response = await fetch(API + "/end-turn", {
    method: "POST", headers: {"Content-Type": "application/json"}, signal,
    body: JSON.stringify({...descriptor(state, context, locale), text: turn.text,
      dialogue: state.phase === "ready" ? "confirm" : "slots"}),
  });
  if (!response.ok) return null;
  const verdict = await response.json();
  signal.throwIfAborted();
  const silenceMs = verdict.silence_ms;
  const short = verdict.decision === "short" && silenceMs >= 500 && silenceMs <= 700;
  const long = verdict.decision === "long" && silenceMs >= 1500 && silenceMs <= 2500;
  if (!Number.isInteger(silenceMs) || (!short && !long)) return null;
  const provisional = verdict.interpretation;
  if (provisional == null ? !isTransferCommand(turn.text)
    : !validInterpretation(provisional, false) || provisional.raw_transcript !== turn.text) {
    return long ? {silenceMs} : null;
  }
  return {silenceMs, result: {
    ...turn, provisionalInterpretation: provisional, understandingMs: performance.now() - started,
  }};
}

export function finishProvisionalTransfer(turn) {
  const {provisionalInterpretation, ...final} = turn;
  return {...final, interpretation: provisionalInterpretation ? {...provisionalInterpretation, is_final: true} : null};
}

export function understandText(text, state, context, locale, signal) {
  const deadline = AbortSignal.timeout(3500);
  return understand({...descriptor(state, context, locale), text},
    signal ? AbortSignal.any([signal, deadline]) : deadline).catch(() => null);
}

export async function transcribeTransferSpeech(blob, {partial, adaptive, signal, state, context, locale}) {
  const started = performance.now();
  const query = new URLSearchParams({language: locale.slice(0, 2), partial: String(partial)});
  if (adaptive && partial) query.set("adaptive", "true");
  const prompt = vocabulary(context || undefined).join(", ").slice(0, 1000);
  if (prompt) query.set("initial_prompt", prompt);
  const response = await fetch(API + "/transcribe?" + query, {method: "POST", body: blob, signal});
  if (!response.ok) throw new Error("stt_unavailable");
  const {text: transcript, provider: transcriptionProvider, fallback_reason: fallbackReason} = await response.json();
  const text = transcript.trim();
  const transcribed = performance.now();
  const turn = {text, provider: "shared", transcriptionProvider};
  if (fallbackReason) turn.fallbackReason = fallbackReason;
  if (!partial || adaptive) turn.transcriptionMs = transcribed - started;
  if (partial || !text || isTransferCommand(text)) return turn;
  const interpretation = await understandText(text, state, context, locale, signal);
  signal.throwIfAborted();
  return {...turn, interpretation, understandingMs: performance.now() - transcribed};
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
