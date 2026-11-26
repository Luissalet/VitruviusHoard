import {initialTransfer, isTransferCommand, PROMPT_PHRASES, transferTurn} from "./dialogue.js";
import {speakTransferReply, transcribeTransferSpeech, understandText, voiceAvailability} from "./voice.js";
import {mountDictationMicrophone} from "./microphone.js";

const COPY = {
  es: {
    title: "Asistente de transferencias", start: "¿A quién quieres hacer una transferencia simulada?",
    input: "Escribe lo que quieres hacer", placeholder: "Escribe un mensaje", send: "Enviar", mic: "Hablar", stop: "Terminar",
    listen: "Escuchar respuesta", confirm: "Confirmar transferencia", cancel: "Cancelar",
    getting_mic: "Solicitando acceso al micrófono…", recording: "Escuchando…", transcribing: "Transcribiendo…",
    mic_unavailable: "No se puede usar el micrófono aquí. Puedes escribir.",
    stt_unavailable: "El servicio de transcripción local no responde. Puedes escribir.",
    written_replies: "Respuestas por escrito.",
    dictation_common: "Dictado mediante el servicio común de Cyrano.",
    dictation_app: "Dictado mediante la app de Cyrano.",
    dictation_fallback: "Cyrano no responde. Se usa el análisis local de la página.",
    empty: "No se ha entendido la frase. Prueba de nuevo o escríbela.",
    data: "No se han podido cargar las cuentas y los contactos. Vuelve a enviar el mensaje.",
    executing: "Confirmando la transferencia…", success: "Transferencia simulada realizada.",
    rejected: "Revisa los datos y vuelve a confirmar la transferencia.",
    balance: "El saldo es insuficiente para este importe.",
    trace: "Cómo se procesó esta respuesta", stages: ["Transcribe", "Entiende", "Habla", "Ejecuta"],
    local_parser: "Análisis local", text_only: "Respuesta escrita", natural_voice: "Caché de voz natural (Cyrano/Prospero mañana)",
    fields: ["Destinatario", "Importe", "Concepto", "Origen"], pending: "Pendiente",
  },
  en: {
    title: "Transfer assistant", start: "Who would you like to make a simulated transfer to?",
    input: "Type what you want to do", placeholder: "Type a message", send: "Send", mic: "Speak", stop: "Finish",
    listen: "Read reply aloud", confirm: "Confirm transfer", cancel: "Cancel",
    getting_mic: "Requesting microphone access…", recording: "Listening…", transcribing: "Transcribing…",
    mic_unavailable: "The microphone is unavailable here. You can type your reply.",
    stt_unavailable: "The local transcription service is unavailable. You can type your reply.",
    written_replies: "Written replies.",
    dictation_common: "Dictation via the shared Cyrano service.",
    dictation_app: "Dictation via the Cyrano app.",
    dictation_fallback: "Cyrano is unavailable. This page is interpreting your input locally.",
    empty: "The speech was unclear. Try again or type your reply.",
    data: "Accounts and contacts could not load. Send the message again.",
    executing: "Confirming the transfer…", success: "Simulated transfer complete.",
    rejected: "Review the details and try confirming the transfer again.",
    balance: "The balance is too low for this amount.",
    trace: "How this reply was processed", stages: ["Transcribes", "Interprets", "Speaks", "Executes"],
    local_parser: "Local parser", text_only: "Written reply", natural_voice: "Natural voice cache",
    fields: ["Recipient", "Amount", "Reference", "From"], pending: "Pending",
  },
};

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
  let phraseId = "saludo";
  let voicePhrases;
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
  const fixedReply = add(root, "p", {class: "transfer-assistant__note", hidden: ""});
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
  const voiceStatus = add(root, "p", {class: "transfer-assistant__note", role: "status", hidden: ""});
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

  function showDictation(route) {
    show(dictationStatus, copy["dictation_" + route] || copy.dictation_fallback);
  }

  function showFixed() {
    const fixed = lang === "es" && voicePhrases?.[phraseId];
    show(fixedReply, fixed && fixed !== message ? fixed : "");
  }

  function paint() {
    const phase = waitingForForm ? "collecting" : state.phase;
    if (["ready", "executing", "complete", "cancelled"].includes(phase)) {
      window.HoardApp?.clearPoint?.(cursorActor);
    }
    root.dataset.transferPhase = phase;
    response.textContent = message;
    showFixed();
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
          await window.HoardApp?.pointTo?.(field, cursorActor, {scroll: true, presence: true});
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

  async function read(id, timing, turn = traceTurn) {
    stopPlayback();
    speech = new AbortController();
    const {signal} = speech;
    const replyAt = performance.now();
    await voiceCheck;
    if (lang !== "es" || !id || signal.aborted || (voicePhrases && !voicePhrases[id])) return;
    void speakTransferReply(id, {
      locale, signal,
      onFallback: () => {
        show(voiceStatus, copy.written_replies);
        track(turn, 2, copy.text_only, performance.now() - replyAt);
      },
      onStart: provider => {
        show(voiceStatus);
        track(turn, 2, provider === "cache-natural" ? copy.natural_voice : "Prospero", performance.now() - replyAt);
        if (timing) {
          const round = Math.round;
          root.dispatchEvent(new CustomEvent("transfer-assistant:latency", {
            bubbles: true,
            detail: {
              inputProvider: timing.inputProvider, outputProvider: provider, stopReason: timing.stopReason,
              speechEndToCaptureStopMs: round(timing.captureStoppedAt - timing.speechEnd),
              captureStopToTranscriptMs: round(timing.transcriptAt - timing.captureStoppedAt),
              speechEndToTranscriptMs: round(timing.transcriptAt - timing.speechEnd),
              transcriptToReplyMs: round(replyAt - timing.transcriptAt),
              replyToAudioMs: round(performance.now() - replyAt),
              speechEndToAudioMs: round(performance.now() - timing.speechEnd),
            },
          }));
        }
      },
    });
  }

  let turnQueue = Promise.resolve();
  let formVersion = 0;

  function submit(text, options = {}) {
    if (!text.trim() || sending) return Promise.resolve(false);
    const reviewed = state.phase === "ready" && !waitingForForm ? state.summary : undefined;
    const version = formVersion;
    if (!options.spoken) {
      mic?.cancel();
      show(transcript);
    }
    const turn = turnQueue.then(() => handleTurn(text, options, version, reviewed));
    turnQueue = turn.catch(() => false);
    return turn;
  }

  async function handleTurn(text, {spoken = false, timing, interpretation, recipientChoice}, version, reviewed) {
    if (version !== formVersion) return false;
    stopPlayback();
    if (!context) {
      try { await refreshData(); }
      catch { response.textContent = copy.data; return false; }
    }
    const understandingAt = performance.now();
    const command = isTransferCommand(text);
    if (!spoken && !recipientChoice && !command) {
      interpretation = await understandText(text, state, context, locale);
      showDictation(interpretation?.dictation_route);
    }
    if (version !== formVersion || sending) return false;
    const currentTrace = ++traceTurn;
    traceList.replaceChildren();
    traceRows.clear();
    trace.hidden = true;
    if (spoken && timing) track(currentTrace, 0, "Funes / Talos", timing.transcriptionMs);
    const previous = state.slots;
    const previousPhase = state.phase;
    const previousNext = state.next;
    const allowConfirm = Boolean(reviewed && reviewed === state.summary && (!spoken || context.allowConfirm));
    const turn = transferTurn(state, text, {...context, lang, allowConfirm, interpretation, recipientChoice});
    if (!command && !recipientChoice) {
      track(currentTrace, 1, interpretation ? "Cyrano" : copy.local_parser,
        timing?.understandingMs ?? performance.now() - understandingAt);
    }
    state = turn.state;
    if (turn.message) {
      ({message, phraseId} = turn);
    }
    const changed = JSON.stringify(previous) !== JSON.stringify(state.slots);
    if (!turn.action) {
      if (changed || state.phase !== "ready") requestKey = undefined;
      const fill = changed || previousPhase !== state.phase || previousNext !== state.next ? reflect() : null;
      waitingForForm = Boolean(fill && state.phase === "ready");
      paint();
      if (turn.message) read(phraseId, timing, currentTrace);
      if (waitingForForm) {
        try { await fill; }
        finally { waitingForForm = false; paint(); }
      }
      return true;
    }

    sending = true;
    message = copy.executing;
    phraseId = "espera";
    paint();
    const key = requestKey ??= crypto.randomUUID();
    const executionAt = performance.now();
    try {
      const receipt = await execute(turn.action, key);
      state = {...initialTransfer(), phase: "complete"};
      requestKey = undefined;
      void reflect();
      message = copy.success;
      phraseId = "hecho";
      root.dispatchEvent(new CustomEvent("transfer-assistant:receipt", {bubbles: true, detail: receipt}));
      void refreshData().catch(() => { context = undefined; });
    } catch (error) {
      if (error.code === "insufficient_balance") {
        state = {...state, phase: "insufficient", next: "amountCents"};
        message = copy.balance;
        phraseId = "saldo-insuficiente";
        requestKey = undefined;
        void refreshData().catch(() => { context = undefined; });
      } else {
        state = {...state, phase: "ready"};
        message = copy.rejected;
        phraseId = "servicio-caido";
      }
    } finally {
      track(currentTrace, 3, "Vitruvius", performance.now() - executionAt);
      sending = false;
      paint();
    }
    read(phraseId, timing, currentTrace);
    return true;
  }

  function checkVoice() {
    if (!voiceCheck) {
      voiceCheck = voiceAvailability().catch(() => null).then(available => {
        dictation = Boolean(available?.dictation);
        voicePhrases = available ? available.voice_phrases || {} : undefined;
        showFixed();
        showDictation(available?.dictation_route);
        sttWarning = available?.stt || dictation ? "" : copy.stt_unavailable;
        show(captureStatus, sttWarning);
        show(voiceStatus, available?.tts ? "" : copy.written_replies);
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
  listen.addEventListener("click", () => read(phraseId));
  mic = mountDictationMicrophone(microphone, {
    language: locale,
    finalTimeoutMs: 53000,
    labels: {start: copy.mic, finish: copy.stop},
    request: (blob, options) => transcribeTransferSpeech(blob, {...options, state, context, locale, dictation}),
    beforeStart: async () => {
      stopPlayback();
      show(transcript);
      if (!dictation || sttWarning || voiceCheck) await checkVoice();
      if (!context) await refreshData().catch(() => {});
      return !sttWarning;
    },
    onStatus: phase => show(captureStatus, copy[phase] || sttWarning),
    onError: error => {
      sttWarning = error === "stt_unavailable" ? copy[error] : sttWarning;
      show(captureStatus, copy[error]);
    },
    onPartial: result => show(transcript, provisional + " · " + result.text),
    onFinal: (result, timing) => {
      if (result.interpretation && result.interpretation.is_final !== true) return;
      showDictation(result.interpretation?.dictation_route);
      show(transcript, result.text);
      if (result.text) void submit(result.text, {spoken: true, timing: {
        ...timing, inputProvider: result.provider, transcriptionMs: result.transcriptionMs,
        understandingMs: result.understandingMs,
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
    phraseId = PROMPT_PHRASES[slot];
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
