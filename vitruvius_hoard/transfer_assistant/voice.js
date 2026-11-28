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

function voiceURL(operation, trace) {
  return API + "/" + operation + (trace ? "?trace=" + encodeURIComponent(trace) : "");
}

async function understand(body, signal, diagnostic) {
  const response = await fetch(voiceURL("understand", diagnostic?.trace), {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body), signal,
  });
  const result = await response.json();
  if (diagnostic) diagnostic.serviceMs = result.service_ms;
  if (!response.ok) throw new Error(result.code || "boltagon_failed");
  if (!validInterpretation(result, true)) throw new Error("boltagon_contract_invalid");
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
  const response = await fetch(voiceURL("end-turn", turn.traceId), {
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
  if (long) return {silenceMs};
  const provisional = verdict.interpretation;
  if (provisional == null ? !isTransferCommand(turn.text)
    : !validInterpretation(provisional, false) || provisional.raw_transcript !== turn.text) {
    return null;
  }
  return {silenceMs, result: {
    ...turn, provisionalInterpretation: provisional, understandingMs: performance.now() - started,
    understandingStartedAt: started,
  }};
}

export function finishProvisionalTransfer(turn) {
  const {provisionalInterpretation, ...final} = turn;
  return {...final, interpretation: provisionalInterpretation ? {...provisionalInterpretation, is_final: true} : null};
}

export function understandText(text, state, context, locale, signal, diagnostic) {
  const deadline = AbortSignal.timeout(1800);
  return understand({...descriptor(state, context, locale), text},
    signal ? AbortSignal.any([signal, deadline]) : deadline, diagnostic).catch(error => {
    if (diagnostic) {
      diagnostic.reason = deadline.aborted ? "boltagon_timeout"
        : error instanceof TypeError ? "boltagon_unreachable" : error.message;
    }
    return null;
  });
}

export async function transcribeTransferSpeech(blob, {partial, adaptive, signal, state, context, locale, traceId}) {
  const started = performance.now();
  const query = new URLSearchParams({language: locale.slice(0, 2), partial: String(partial)});
  if (adaptive && partial) query.set("adaptive", "true");
  if (traceId) query.set("trace", traceId);
  const prompt = vocabulary(context || undefined).join(", ").slice(0, 1000);
  if (prompt) query.set("initial_prompt", prompt);
  const response = await fetch(API + "/transcribe?" + query, {method: "POST", body: blob, signal});
  if (!response.ok) throw new Error("stt_unavailable");
  const {text: transcript, provider: transcriptionProvider, fallback_reason: fallbackReason, timing} = await response.json();
  const text = transcript.trim();
  const transcribed = performance.now();
  const turn = {text, provider: "shared", transcriptionProvider};
  if (traceId) turn.traceId = traceId;
  if (!partial || adaptive) turn.transcribedAt = transcribed;
  if (fallbackReason) turn.fallbackReason = fallbackReason;
  if (!partial || adaptive) {
    const elapsed = transcribed - started;
    turn.transcriptionStartedAt = started;
    turn.uploadMs = Math.max(0, elapsed - (timing?.gateway_ms ?? elapsed));
    turn.transcriptionMs = timing?.service_ms ?? elapsed;
    if (Number.isFinite(timing?.primary_ms)) turn.primaryMs = timing.primary_ms;
  }
  if (partial || !text || isTransferCommand(text)) return turn;
  const diagnostic = {trace: traceId};
  const interpretation = await understandText(text, state, context, locale, signal, diagnostic);
  signal.throwIfAborted();
  return {...turn, interpretation, understandingStartedAt: transcribed,
    understandingMs: performance.now() - transcribed, understandingFailure: diagnostic.reason,
    understandingServiceMs: diagnostic.serviceMs};
}

export function publishVoiceTrace(traceId, stages) {
  if (!traceId) return;
  const body = JSON.stringify({trace_id: traceId, stages: stages.map(([stage, startedAt, elapsed, outcome]) =>
    [stage, (performance.timeOrigin + startedAt) / 1000, Math.max(0, elapsed), outcome])});
  void fetch(API + "/trace", {method: "POST", headers: {"Content-Type": "application/json"},
    body, keepalive: true}).catch(() => {});
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
