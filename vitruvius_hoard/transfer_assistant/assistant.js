import {initialTransfer, isTransferCommand, transferTurn} from "./dialogue.js";
import {
  assessTransferEndTurn, finishProvisionalTransfer, publishVoiceTrace, transcribeTransferSpeech, understandText, voiceAvailability,
} from "./voice.js";
import {mountDictationMicrophone} from "./microphone.js";
import {createTransferReplyVoice} from "./reply_audio.js";

const STT_FALLBACK = {
  es: {
    resident_prewarming: "El residente se está calentando",
    resident_lease_timeout: "Se agotó la espera del arriendo de GPU",
    resident_lease_rejected: "Se denegó el arriendo de GPU",
    resident_lease_error: "Falló la solicitud de arriendo de GPU",
    resident_lease_not_granted: "No se concedió el arriendo de GPU",
    resident_queue_timeout: "Se agotó la espera en la cola del residente",
    resident_timeout: "Se agotó la espera de la transcripción",
    resident_model_load_failed: "No se pudo cargar el modelo principal",
    resident_inference_failed: "Falló el reconocimiento residente",
    unavailable: "El residente no respondió",
  },
  en: {
    resident_prewarming: "The resident engine is warming up",
    resident_lease_timeout: "Waiting for a GPU lease timed out",
    resident_lease_rejected: "The GPU lease was denied",
    resident_lease_error: "The GPU lease request failed",
    resident_lease_not_granted: "The GPU lease was not granted",
    resident_queue_timeout: "Waiting for the resident queue timed out",
    resident_timeout: "Transcription timed out",
    resident_model_load_failed: "The primary model could not load",
    resident_inference_failed: "Resident recognition failed",
    unavailable: "The resident engine did not respond",
  },
};

const DICTATION_FAILURE = {
  es: {
    boltagon_undiscovered: "Falta descubrir la dirección de Boltagon",
    boltagon_unreachable: "Boltagon no está accesible",
    boltagon_timeout: "Boltagon no respondió a tiempo",
    boltagon_contract_missing: "Boltagon aún no ofrece este contrato",
    boltagon_contract_invalid: "La respuesta de Boltagon no coincide con el contrato",
    boltagon_invalid_request: "Boltagon rechazó los datos del turno",
    boltagon_busy: "Boltagon está ocupado",
    boltagon_failed: "Falló el dictado de Boltagon",
  },
  en: {
    boltagon_undiscovered: "Boltagon's address is pending discovery",
    boltagon_unreachable: "Boltagon is unreachable",
    boltagon_timeout: "Boltagon did not respond in time",
    boltagon_contract_missing: "Boltagon does not offer this contract yet",
    boltagon_contract_invalid: "Boltagon's response did not match the contract",
    boltagon_invalid_request: "Boltagon rejected the turn data",
    boltagon_busy: "Boltagon is busy",
    boltagon_failed: "Boltagon dictation failed",
  },
};

const COPY = {
  es: {
    title: "Boltagon · Asistente de transferencias", start: "¿A quién quieres hacer una transferencia simulada?",
    input: "Escribe lo que quieres hacer", placeholder: "Escribe un mensaje", send: "Enviar", mic: "Hablar", stop: "Terminar",
    listen: "Escuchar respuesta", confirm: "Confirmar transferencia", cancel: "Cancelar",
    getting_mic: "Solicitando acceso al micrófono…", recording: "Escuchando…", transcribing: "Transcribiendo…",
    mic_unavailable: "No se puede usar el micrófono aquí. Puedes escribir.",
    stt_unavailable: "El servicio de transcripción local no responde. Puedes escribir.",
    written_replies: "Respuestas por escrito.",
    written_pending: "Respuesta por escrito mientras se prepara el audio.",
    dictation_remote: name => `Lo entiende ${name}.`,
    dictation_fallback: name => `El dictado de ${name} no responde. Se usa el análisis local de la página.`,
    empty: "No se ha entendido la frase. Prueba de nuevo o escríbela.",
    data: "No se han podido cargar las cuentas y los contactos. Vuelve a enviar el mensaje.",
    executing: "Confirmando la transferencia…", success: "Transferencia simulada realizada.",
    rejected: "Revisa los datos y vuelve a confirmar la transferencia.",
    balance: "El saldo es insuficiente para este importe.",
    trace: "Cómo se procesó esta respuesta", stages: ["Transcribe", "Entiende", "Habla", "Ejecuta", "Corte", "Subida y vuelta", "Caché"],
    local_parser: "Análisis local", text_only: "Respuesta escrita",
    fields: ["Destinatario", "Importe", "Concepto", "Origen"], pending: "Pendiente",
  },
  en: {
    title: "Boltagon · Transfer assistant", start: "Who would you like to make a simulated transfer to?",
    input: "Type what you want to do", placeholder: "Type a message", send: "Send", mic: "Speak", stop: "Finish",
    listen: "Read reply aloud", confirm: "Confirm transfer", cancel: "Cancel",
    getting_mic: "Requesting microphone access…", recording: "Listening…", transcribing: "Transcribing…",
    mic_unavailable: "The microphone is unavailable here. You can type your reply.",
    stt_unavailable: "The local transcription service is unavailable. You can type your reply.",
    written_replies: "Written replies.",
    written_pending: "Written reply while audio is prepared.",
    dictation_remote: name => `Interpreted by ${name}.`,
    dictation_fallback: name => `${name} dictation is unavailable. This page is interpreting your input locally.`,
    empty: "The speech was unclear. Try again or type your reply.",
    data: "Accounts and contacts could not load. Send the message again.",
    executing: "Confirming the transfer…", success: "Simulated transfer complete.",
    rejected: "Review the details and try confirming the transfer again.",
    balance: "The balance is too low for this amount.",
    trace: "How this reply was processed", stages: ["Transcribes", "Interprets", "Speaks", "Executes", "Endpoint", "Upload and round trip", "Cache"],
    local_parser: "Local parser", text_only: "Written reply",
    fields: ["Recipient", "Amount", "Reference", "From"], pending: "Pending",
  },
};

function dictationLabel(name = "") {
  const label = name.replace(/['’]s Hoard$/iu, "").trim();
  return !label || label.toLowerCase() === "cyrano" ? "Boltagon" : label;
}

async function json(path, options) {
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw Object.assign(new Error(result.error || response.statusText), {code: result.code});
  return result;
}

async function loadProjectData() {
  const [accounts, contacts, schema] = await Promise.all([
    json("/api/collections/accounts"), json("/api/collections/contacts"), json("/api/schema"),
  ]);
  return {
    accounts: accounts.records.map(item => ({
      id: item.id, name: item.name, iban: item.iban, balanceCents: item.balance_cents,
      aliases: [item.name.replace(/^(?:cuenta|account)\s+/iu, ""), ...(item.aliases || [])],
    })),
    contacts: contacts.records,
    allowConfirm: schema.actions?.transfer?.confirmable_by_voice === true,
  };
}

function performTransfer(draft, key) {
  const destination = draft.recipient.id ? {destination_contact_id: draft.recipient.id} : {destination_iban: draft.recipient.iban};
  return json("/api/actions/transfer", {
    method: "POST",
    headers: {"Content-Type": "application/json", "Idempotency-Key": key},
    body: JSON.stringify({source_account_id: draft.source, ...destination, amount_cents: draft.amountCents, concept: draft.concept}),
    signal: AbortSignal.timeout(12000),
  });
}

function add(parent, tag, attrs = {}, text = "") {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) element.setAttribute(name, value);
  element.textContent = text;
  parent.append(element);
  return element;
}

function controlValue(field, key, slots, locale) {
  if (key === "recipient") {
    return field instanceof HTMLSelectElement || field.dataset.transferValue === "id" ? slots.recipient?.id : slots.recipient?.name;
  }
  if (key === "iban") return slots.recipient?.iban;
  if (key === "amountCents" && slots.amountCents !== undefined) {
    const euros = (slots.amountCents / 100).toFixed(2);
    if (field.dataset.transferValue === "cents") return String(slots.amountCents);
    return field.type === "number" || locale.startsWith("en") ? euros : euros.replace(".", ",");
  }
  return slots[key];
}

export function mountTransferAssistant(root, options = {}) {
  const lang = (options.language || document.documentElement.lang).startsWith("en") ? "en" : "es";
  const locale = lang === "es" ? "es-ES" : "en-IE";
  const copy = COPY[lang];
  const loadContext = options.loadContext || loadProjectData;
  const execute = options.execute || performTransfer;
  const currency = new Intl.NumberFormat(locale, {style: "currency", currency: "EUR", useGrouping: "always"});
  let state = initialTransfer();
  let context;
  let pendingData;
  let message = copy.start;
  let latestTurn = 0;
  let replyTurn = latestTurn;
  let dictationName = "Boltagon";
  const speaker = createTransferReplyVoice();
  let speech;
  let requestKey;
  let mic;
  let dictation = false;
  let sttWarning = "";
  let voiceCheck;
  let cursorSequence = 0;
  let sending = false;
  let waitingForForm = false;
  const cursorActor = {id: "transfer-assistant", name: copy.title};
  const managed = new Set();
  const marks = new WeakMap();

  root.classList.add("transfer-assistant");
  add(root, "h2", {class: "transfer-assistant__title"}, copy.title);
  const response = add(root, "p", {class: "transfer-assistant__reply", role: "status"}, message);
  const voiceStatus = add(root, "p", {class: "transfer-assistant__note", role: "status", hidden: ""});
  const candidates = add(root, "div", {class: "transfer-assistant__choices"});
  const fields = add(root, "dl", {class: "transfer-assistant__slots"});
  const entries = copy.fields.map(name => {
    const row = add(fields, "div");
    add(row, "dt", {}, name);
    return add(row, "dd", {}, copy.pending);
  });
  const composer = add(root, "form", {class: "transfer-assistant__composer"});
  const input = add(composer, "input", {
    type: "text", "aria-label": copy.input, placeholder: copy.placeholder, autocomplete: "off", maxlength: "1000",
  });
  const send = add(composer, "button", {type: "submit", class: "transfer-assistant__primary"}, copy.send);
  const controls = add(root, "div", {class: "transfer-assistant__controls"});
  const microphone = add(controls, "button", {type: "button", "aria-pressed": "false"}, copy.mic);
  const listen = add(controls, "button", {type: "button"}, copy.listen);
  const confirm = add(controls, "button", {type: "button", class: "transfer-assistant__primary", hidden: ""}, copy.confirm);
  const cancel = add(controls, "button", {type: "button", hidden: ""}, copy.cancel);
  const captureStatus = add(root, "p", {class: "transfer-assistant__note", role: "status", hidden: ""});
  const dictationStatus = add(root, "p", {class: "transfer-assistant__note", role: "status", hidden: ""});
  const transcript = add(root, "p", {class: "transfer-assistant__transcript", hidden: ""});
  const trace = add(root, "details", {class: "transfer-assistant__trace", hidden: ""});
  add(trace, "summary", {}, copy.trace);
  const traceList = add(trace, "ul");
  let traceTurn = 0;
  const units = new Intl.NumberFormat(locale, {style: "unit", unit: "millisecond", maximumFractionDigits: 0});
  const traceRows = new Map();
  const provisional = lang === "es" ? "Transcripción provisional" : "Partial transcript";

  function track(turn, step, provider, elapsed) {
    if (turn !== traceTurn) return;
    let row = traceRows.get(step);
    if (!row) {
      row = add(traceList, "li");
      traceRows.set(step, row);
    }
    row.textContent = [copy.stages[step], provider, Number.isFinite(elapsed) && units.format(elapsed)].filter(Boolean).join(" · ");
    trace.hidden = false;
  }

  function show(element, text = "") {
    element.textContent = text;
    element.hidden = !text;
  }

  function showDictation(route, name) {
    if (name) dictationName = dictationLabel(name);
    const label = ["direct", "app", "common"].includes(route) ? copy.dictation_remote : copy.dictation_fallback;
    show(dictationStatus, label(dictationName));
  }

  function paint() {
    const phase = waitingForForm ? "collecting" : state.phase;
    if (["ready", "executing", "complete", "cancelled"].includes(phase)) {
      window.HoardApp?.clearPoint?.(cursorActor);
    }
    root.dataset.transferPhase = phase;
    response.textContent = message;
    const {slots} = state;
    const source = context?.accounts.find(item => item.id === slots.source);
    const values = [slots.recipient?.name, slots.amountCents && currency.format(slots.amountCents / 100), slots.concept, source?.name];
    entries.forEach((entry, index) => {
      entry.textContent = values[index] || copy.pending;
      entry.dataset.filled = String(Boolean(values[index]));
    });
    confirm.hidden = waitingForForm || state.phase !== "ready";
    cancel.hidden = state.phase === "complete" || !Object.keys(slots).length && !state.candidates.length;
    cancel.disabled = sending;
    input.disabled = sending;
    send.disabled = sending;
    mic?.setDisabled(sending);
    candidates.replaceChildren(...state.candidates.map(item => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = item.name;
      button.addEventListener("click", () => void submit(item.name, {recipientChoice: item.id || item.iban}));
      return button;
    }));
  }

  async function reflect() {
    const sequence = ++cursorSequence;
    const snapshot = state;
    const current = snapshot.slots;
    const hasSlots = Object.keys(current).length > 0;
    const showCursor = !["complete", "cancelled"].includes(snapshot.phase);
    options.onDraft?.(snapshot);
    const scope = root.closest("[data-transfer-scope]") || document;
    const fields = [...scope.querySelectorAll("[data-transfer-slot]")];
    for (const field of fields) {
      if (sequence !== cursorSequence) return;
      const key = field.dataset.transferSlot;
      field.toggleAttribute("data-transfer-next", (key === snapshot.next || key === "iban" && snapshot.next === "recipient") && hasSlots);
      const after = controlValue(field, key, current, locale);
      if (after === undefined && !managed.has(field)) continue;
      if (after !== undefined) managed.add(field);
      if (String(field.value) === String(after ?? "")) continue;
      if (showCursor && field.getClientRects().length) {
        try {
          await window.HoardApp?.pointTo?.(field, cursorActor, {scroll: true, presence: true, expiryMs: 2500});
        } catch (error) {
          console.warn("Transfer assistant could not move the preview cursor", error);
        }
      }
      if (sequence !== cursorSequence) return;
      field.value = after ?? "";
      const mark = Symbol();
      marks.set(field, mark);
      field.setAttribute("data-transfer-changed", "");
      setTimeout(() => {
        if (marks.get(field) === mark) field.removeAttribute("data-transfer-changed");
      }, 900);
      if (after === undefined) managed.delete(field);
      field.dispatchEvent(new Event("input", {bubbles: true}));
      field.dispatchEvent(new Event("change", {bubbles: true}));
    }
  }

  async function refreshData() {
    if (!pendingData) {
      pendingData = Promise.resolve().then(loadContext)
        .then(data => { context = data; return data; })
        .finally(() => { pendingData = null; });
    }
    return pendingData;
  }

  function stopPlayback() {
    speech?.abort();
    speech = undefined;
  }

  function read(timing, turn = traceTurn) {
    if (replyTurn !== latestTurn || document.hidden) {
      finishTrace(timing, performance.now(), "cancelled");
      return;
    }
    stopPlayback();
    speech = new AbortController();
    const {signal} = speech;
    const replyAt = performance.now();
    let audioAt;
    show(voiceStatus);
    void speaker.speak(message, {
      locale, signal, traceId: timing?.traceId,
      onPending: () => {
        show(voiceStatus, copy.written_pending);
        track(turn, 2, copy.text_only, performance.now() - replyAt);
      },
      onFallback: () => {
        show(voiceStatus, copy.written_replies);
        if (audioAt === undefined) track(turn, 2, copy.text_only, performance.now() - replyAt);
      },
      onStart: (engine, lead = 0) => {
        audioAt = performance.now() + lead * 1000;
        const provider = "Boltagon · " + engine;
        show(voiceStatus);
        track(turn, 2, provider, audioAt - replyAt);
        if (timing) {
          const round = Math.round;
          root.dispatchEvent(new CustomEvent("transfer-assistant:latency", {
            bubbles: true,
            detail: {
              inputProvider: timing.inputProvider, outputProvider: provider, stopReason: timing.stopReason,
              speechEndToCaptureStopMs: round(timing.captureStoppedAt - timing.speechEnd),
              captureStopToTranscriptMs: round(Math.max(0, timing.transcriptAt - timing.captureStoppedAt)),
              speechEndToTranscriptMs: round(timing.transcriptAt - timing.speechEnd),
              transcriptToReplyMs: round(replyAt - timing.transcriptAt),
              replyToAudioMs: round(audioAt - replyAt),
              speechEndToAudioMs: round(audioAt - timing.speechEnd),
              uploadMs: round(timing.uploadMs || 0),
              transcriptionMs: round(timing.transcriptionMs || 0),
              understandingMs: round(timing.understandingMs || 0),
              hubWaitMs: 0,
            },
          }));
        }
      },
      onEnd: receipt => {
        if (!receipt.cached) return;
        const {first_audio: first, queue} = receipt.timings_ms || {};
        const cacheMs = Number.isFinite(first) && Number.isFinite(queue) ? Math.max(0, first - queue) : undefined;
        track(turn, 6, "", cacheMs);
        if (timing && Number.isFinite(cacheMs)) {
          timing.stages.push(["voice.cache", replyAt + queue, cacheMs, "ok"]);
        }
      },
      onSettled: outcome => {
        const end = audioAt ?? performance.now();
        timing?.stages.push(["voice.speak", replyAt, end - replyAt, outcome]);
        finishTrace(timing, end, outcome);
      },
    });
  }

  function finishTrace(timing, end, outcome) {
    if (timing?.traceId) {
      publishVoiceTrace(timing.traceId, [
        ["voice.turn", timing.speechEnd, end - timing.speechEnd, outcome], ...timing.stages,
      ]);
    }
  }

  let turnQueue = Promise.resolve();
  let formVersion = 0;

  function submit(text, options = {}) {
    if (!text.trim() || sending) return Promise.resolve(false);
    const turnId = ++latestTurn;
    speaker.activate();
    stopPlayback();
    const reviewed = state.phase === "ready" && !waitingForForm ? state.summary : undefined;
    const version = formVersion;
    if (!options.spoken) {
      mic?.cancel();
      show(transcript);
    }
    const turn = turnQueue.then(() => handleTurn(text, options, {version, reviewed, turnId}));
    turnQueue = turn.catch(() => false);
    return turn;
  }

  async function handleTurn(text, {spoken = false, timing, interpretation, recipientChoice}, {version, reviewed, turnId}) {
    if (version !== formVersion) return false;
    stopPlayback();
    if (!context) {
      try { await refreshData(); }
      catch { response.textContent = copy.data; return false; }
    }
    const understandingAt = performance.now();
    const command = isTransferCommand(text);
    const diagnostic = {};
    if (!spoken && !recipientChoice && !command) {
      interpretation = await understandText(text, state, context, locale, undefined, diagnostic);
      showDictation(interpretation?.dictation_route, interpretation?.dictation_name);
    }
    if (version !== formVersion || sending) return false;
    const currentTrace = ++traceTurn;
    traceList.replaceChildren();
    traceRows.clear();
    trace.hidden = true;
    if (spoken && timing) {
      const {transcriptionProvider, transcriptionMs, fallbackReason, transcriptionStartedAt, uploadMs, primaryMs} = timing;
      const cut = timing.captureStoppedAt - timing.speechEnd;
      track(currentTrace, 4, "", cut);
      track(currentTrace, 5, "", uploadMs);
      timing.stages = [["voice.cut", timing.speechEnd, cut, "ok"]];
      if (Number.isFinite(uploadMs)) timing.stages.push(["voice.upload", transcriptionStartedAt, uploadMs, "ok"]);
      if (Number.isFinite(transcriptionMs)) {
        const reserve = transcriptionProvider?.startsWith("Funes");
        const started = transcriptionStartedAt + (uploadMs || 0);
        if (reserve && Number.isFinite(primaryMs)) {
          timing.stages.push(["voice.transcribe", started, primaryMs, /timeout$/.test(fallbackReason) ? "timeout" : "error"]);
        }
        timing.stages.push([reserve ? "voice.transcribe_reserve" : "voice.transcribe",
          started + (primaryMs || 0), transcriptionMs, fallbackReason ? "fallback" : "ok"]);
      }
      const reasons = STT_FALLBACK[lang];
      const reason = fallbackReason && (Object.hasOwn(reasons, fallbackReason) ? reasons[fallbackReason] : reasons.unavailable);
      track(currentTrace, 0, reason ? transcriptionProvider + " · " + reason : transcriptionProvider, transcriptionMs);
    }
    const previous = state.slots;
    const previousPhase = state.phase;
    const previousNext = state.next;
    const allowConfirm = Boolean(reviewed && reviewed === state.summary && (!spoken || context.allowConfirm));
    const localAt = performance.now();
    const turn = transferTurn(state, text, {...context, lang, allowConfirm, interpretation, recipientChoice});
    if (!command && !recipientChoice) {
      const label = dictationLabel(interpretation?.dictation_name || dictationName);
      const failure = timing?.understandingFailure || diagnostic.reason;
      const reason = DICTATION_FAILURE[lang][failure] || DICTATION_FAILURE[lang].boltagon_failed;
      const duration = timing?.understandingMs ?? performance.now() - understandingAt;
      track(currentTrace, 1, interpretation ? label : copy.local_parser + " ? " + reason, duration);
      if (timing) {
        const started = timing.understandingStartedAt ?? understandingAt;
        timing.stages.push(["voice.understand", started, timing.understandingServiceMs ?? duration,
          interpretation ? "ok" : failure === "boltagon_timeout" ? "timeout" : "error"]);
        if (!interpretation) timing.stages.push(["voice.local_understand", localAt, performance.now() - localAt, "fallback"]);
      }
    }
    state = turn.state;
    if (turn.message) {
      message = turn.message;
      replyTurn = turnId;
    }
    const changed = JSON.stringify(previous) !== JSON.stringify(state.slots);
    if (!turn.action) {
      if (changed || state.phase !== "ready") requestKey = undefined;
      const fill = changed || previousPhase !== state.phase || previousNext !== state.next ? reflect() : null;
      waitingForForm = Boolean(fill && state.phase === "ready");
      paint();
      if (turn.message) read(timing, currentTrace);
      else finishTrace(timing, performance.now(), "ok");
      if (waitingForForm) {
        try { await fill; }
        finally { waitingForForm = false; paint(); }
      }
      return true;
    }

    sending = true;
    message = copy.executing;
    replyTurn = turnId;
    paint();
    const key = requestKey ??= crypto.randomUUID();
    const executionAt = performance.now();
    let executionOutcome = "ok";
    try {
      const receipt = await execute(turn.action, key);
      state = {...initialTransfer(), phase: "complete"};
      requestKey = undefined;
      void reflect();
      message = copy.success;
      root.dispatchEvent(new CustomEvent("transfer-assistant:receipt", {bubbles: true, detail: receipt}));
      void refreshData().catch(() => { context = undefined; });
    } catch (error) {
      executionOutcome = "error";
      if (error.code === "insufficient_balance") {
        state = {...state, phase: "insufficient", next: "amountCents"};
        message = copy.balance;
        requestKey = undefined;
        void refreshData().catch(() => { context = undefined; });
      } else {
        state = {...state, phase: "ready"};
        message = copy.rejected;
      }
    } finally {
      const duration = performance.now() - executionAt;
      track(currentTrace, 3, "Vitruvius", duration);
      timing?.stages.push(["voice.execute", executionAt, duration, executionOutcome]);
      sending = false;
      paint();
    }
    read(timing, currentTrace);
    return true;
  }

  let adaptiveTurn = false;
  let captureVersion;
  let captureState;
  let captureContext;
  let captureTrace;

  function checkVoice() {
    if (!voiceCheck) {
      voiceCheck = voiceAvailability().catch(() => null).then(available => {
        dictation = Boolean(available?.dictation);
        adaptiveTurn = Boolean(available?.adaptive_turn);
        showDictation(available?.dictation_route, available?.dictation_name);
        sttWarning = available?.stt || dictation ? "" : copy.stt_unavailable;
        show(captureStatus, sttWarning);
      }).finally(() => { voiceCheck = null; });
    }
    return voiceCheck;
  }

  composer.addEventListener("submit", async event => {
    event.preventDefault();
    const text = input.value;
    if (await submit(text) && input.value === text) input.value = "";
  });
  confirm.addEventListener("click", () => void submit(lang === "es" ? "confirmo" : "confirm"));
  cancel.addEventListener("click", () => void submit(lang === "es" ? "cancela" : "cancel"));
  listen.addEventListener("click", () => {
    speaker.activate();
    read();
  });
  mic = mountDictationMicrophone(microphone, {
    language: locale,
    finalTimeoutMs: 53000,
    labels: {start: copy.mic, finish: copy.stop},
    request: (blob, options) => transcribeTransferSpeech(blob, {
      ...options, state: captureState, context: captureContext, locale, traceId: captureTrace,
    }),
    adaptive: () => adaptiveTurn,
    endTurn: (turn, {signal}) => assessTransferEndTurn(turn, {
      state: captureState, context: captureContext, locale, signal,
    }),
    beforeStart: async () => {
      speaker.activate();
      stopPlayback();
      show(transcript);
      if (!dictation || sttWarning || voiceCheck) await checkVoice();
      if (!context) await refreshData().catch(() => {});
      captureVersion = formVersion;
      captureTrace = crypto.randomUUID().replaceAll("-", "");
      captureState = state;
      captureContext = context;
      return !sttWarning;
    },
    onStatus: phase => show(captureStatus, copy[phase] || sttWarning),
    onError: error => {
      sttWarning = error === "stt_unavailable" ? copy[error] : sttWarning;
      show(captureStatus, copy[error]);
    },
    onPartial: result => show(transcript, provisional + " · " + result.text),
    onFinal: (result, timing) => {
      if (captureVersion !== formVersion) return;
      if (timing.stopReason === "adaptive") result = finishProvisionalTransfer(result);
      if (result.interpretation && result.interpretation.is_final !== true) return;
      if (!isTransferCommand(result.text)) showDictation(result.interpretation?.dictation_route, result.interpretation?.dictation_name);
      show(transcript, result.text);
      if (result.text) void submit(result.text, {spoken: true, timing: {
        ...timing, inputProvider: result.provider, transcriptionProvider: result.transcriptionProvider,
        fallbackReason: result.fallbackReason,
        transcriptionMs: result.transcriptionMs, uploadMs: result.uploadMs,
        transcriptionStartedAt: result.transcriptionStartedAt, primaryMs: result.primaryMs,
        understandingMs: result.understandingMs, understandingStartedAt: result.understandingStartedAt,
        understandingFailure: result.understandingFailure, understandingServiceMs: result.understandingServiceMs,
        traceId: result.traceId,
      }, interpretation: result.interpretation});
      else show(captureStatus, copy.empty);
    },
  });
  document.addEventListener("input", event => {
    const scope = root.closest("[data-transfer-scope]") || document;
    if (!event.isTrusted || !scope.contains(event.target) || state.phase !== "ready" || !event.target.matches?.("[data-transfer-slot]")) return;
    const key = event.target.dataset.transferSlot;
    const slot = key === "iban" ? "recipient" : key;
    const slots = {...state.slots};
    delete slots[slot];
    state = {...state, slots, phase: "collecting", next: slot};
    cursorSequence++;
    formVersion++;
    managed.delete(event.target);
    requestKey = undefined;
    stopPlayback();
    message = copy.start;
    replyTurn = latestTurn;
    paint();
  });
  window.addEventListener("pagehide", stopPlayback);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopPlayback();
  });
  paint();
  void refreshData().catch(() => {});
  void checkVoice();
  return {submit};
}

for (const root of document.querySelectorAll("[data-transfer-assistant]:not([data-transfer-assistant=manual])")) {
  mountTransferAssistant(root);
}
