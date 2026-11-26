import {initialTransfer, transferTurn} from "./dialogue.js";
import {speakTransferReply, transcribeTransferSpeech, understandText, voiceAvailability} from "./voice.js";
import {mountDictationMicrophone} from "./microphone.js";

const COPY = {
  es: {
    title: "Asistente de transferencias", start: "¿A quién quieres hacer una transferencia simulada?",
    input: "Escribe lo que quieres hacer", send: "Enviar", mic: "Hablar", stop: "Terminar",
    listen: "Escuchar respuesta", confirm: "Confirmar transferencia", cancel: "Cancelar",
    getting_mic: "Solicitando acceso al micrófono…", recording: "Escuchando…", transcribing: "Transcribiendo…",
    mic_unavailable: "No se puede usar el micrófono aquí. Puedes escribir.",
    stt_unavailable: "El servicio de transcripción local no responde. Puedes escribir.",
    tts_unavailable: "El servicio de voz local no responde. Puedes leer la respuesta.",
    tts_fallback: "El servicio de voz local no responde. Se usa una voz de este equipo.",
    empty: "No se ha entendido la frase. Prueba de nuevo o escríbela.",
    data: "No se han podido cargar las cuentas y los contactos. Vuelve a enviar el mensaje.",
    executing: "Confirmando la transferencia…", success: "Transferencia simulada realizada.",
    rejected: "No se ha podido confirmar la transferencia. Puedes corregir los datos o confirmar de nuevo.",
    balance: "Saldo insuficiente. Indica otro importe u otra cuenta.",
    fields: ["Destinatario", "Importe", "Concepto", "Origen"], pending: "Pendiente",
  },
  en: {
    title: "Transfer assistant", start: "Who would you like to make a simulated transfer to?",
    input: "Type what you want to do", send: "Send", mic: "Speak", stop: "Finish",
    listen: "Read reply aloud", confirm: "Confirm transfer", cancel: "Cancel",
    getting_mic: "Requesting microphone access…", recording: "Listening…", transcribing: "Transcribing…",
    mic_unavailable: "The microphone is unavailable here. You can type your reply.",
    stt_unavailable: "The local transcription service is unavailable. You can type your reply.",
    tts_unavailable: "The local speech service is unavailable. You can read the reply.",
    tts_fallback: "The local speech service is unavailable. Using a voice from this device.",
    empty: "The speech was unclear. Try again or type your reply.",
    data: "Accounts and contacts could not load. Send the message again.",
    executing: "Confirming the transfer…", success: "Simulated transfer complete.",
    rejected: "The transfer could not be confirmed. You can correct the details or confirm again.",
    balance: "Insufficient funds. Enter another amount or choose another account.",
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
  let speech;
  let requestKey;
  let mic;
  let dictation = false;
  let sttWarning = "";
  let voiceCheck;
  let cursorSequence = 0;
  let sending = false;
  const managed = new Set();
  const marks = new WeakMap();

  root.classList.add("transfer-assistant");
  add(root, "h2", {class: "transfer-assistant__title"}, copy.title);
  const response = add(root, "p", {class: "transfer-assistant__reply", role: "status"}, message);
  const candidates = add(root, "div", {class: "transfer-assistant__choices"});
  const fields = add(root, "dl", {class: "transfer-assistant__slots"});
  const entries = copy.fields.map(name => {
    const row = add(fields, "div");
    add(row, "dt", {}, name);
    return add(row, "dd", {}, copy.pending);
  });
  const composer = add(root, "form", {class: "transfer-assistant__composer"});
  const input = add(composer, "input", {
    type: "text", "aria-label": copy.input, placeholder: copy.input, autocomplete: "off", maxlength: "1000",
  });
  const send = add(composer, "button", {type: "submit", class: "transfer-assistant__primary"}, copy.send);
  const controls = add(root, "div", {class: "transfer-assistant__controls"});
  const microphone = add(controls, "button", {type: "button", "aria-pressed": "false"}, copy.mic);
  const listen = add(controls, "button", {type: "button"}, copy.listen);
  const confirm = add(controls, "button", {type: "button", class: "transfer-assistant__primary", hidden: ""}, copy.confirm);
  const cancel = add(controls, "button", {type: "button", hidden: ""}, copy.cancel);
  const captureStatus = add(root, "p", {class: "transfer-assistant__note", role: "status", hidden: ""});
  const voiceStatus = add(root, "p", {class: "transfer-assistant__note", role: "status", hidden: ""});
  const transcript = add(root, "p", {class: "transfer-assistant__transcript", hidden: ""});
  const provisional = lang === "es" ? "Transcripción provisional" : "Partial transcript";

  function show(element, text = "") {
    element.textContent = text;
    element.hidden = !text;
  }

  function paint() {
    root.dataset.transferPhase = state.phase;
    response.textContent = message;
    const {slots} = state;
    const source = context?.accounts.find(item => item.id === slots.source);
    const values = [slots.recipient?.name, slots.amountCents && currency.format(slots.amountCents / 100), slots.concept, source?.name];
    entries.forEach((entry, index) => {
      entry.textContent = values[index] || copy.pending;
      entry.dataset.filled = String(Boolean(values[index]));
    });
    confirm.hidden = state.phase !== "ready";
    cancel.hidden = state.phase === "complete" || !Object.keys(slots).length && !state.candidates.length;
    cancel.disabled = sending;
    input.disabled = sending;
    send.disabled = sending;
    mic?.setDisabled(sending);
    candidates.replaceChildren(...state.candidates.map(item => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = item.name;
      button.addEventListener("click", () => void submit(item.name));
      return button;
    }));
  }

  async function reflect() {
    const sequence = ++cursorSequence;
    const snapshot = state;
    const current = snapshot.slots;
    const hasSlots = Object.keys(current).length > 0;
    options.onDraft?.(snapshot);
    const scope = root.closest("[data-transfer-scope]") || document;
    const fields = [...scope.querySelectorAll("[data-transfer-slot]")];
    for (const field of fields) {
      if (sequence !== cursorSequence) return;
      const key = field.dataset.transferSlot;
      field.toggleAttribute("data-transfer-next", key === snapshot.next && hasSlots);
      const after = controlValue(field, key, current, locale);
      if (after === undefined && !managed.has(field)) continue;
      if (after !== undefined) managed.add(field);
      if (String(field.value) === String(after ?? "")) continue;
      try {
        await window.HoardApp?.pointTo?.(field, {id: "transfer-assistant", name: copy.title}, {scroll: false});
      } catch {
        // A preview cursor can disappear when the workbench switches revision.
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

  function read(text, timing) {
    stopPlayback();
    speech = new AbortController();
    const replyAt = performance.now();
    void speakTransferReply(text, {
      locale, signal: speech.signal,
      onFallback: hasVoice => show(voiceStatus, hasVoice ? copy.tts_fallback : copy.tts_unavailable),
      onStart: provider => {
        if (provider === "shared") show(voiceStatus);
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
    }).catch(() => show(voiceStatus, copy.tts_unavailable));
  }

  let turnQueue = Promise.resolve();
  let formVersion = 0;

  function submit(text, options = {}) {
    if (!text.trim() || sending) return Promise.resolve(false);
    const reviewed = state.phase === "ready" ? state.summary : undefined;
    const version = formVersion;
    if (!options.spoken) {
      mic?.cancel();
      show(transcript);
    }
    const turn = turnQueue.then(() => handleTurn(text, options, version, reviewed));
    turnQueue = turn.catch(() => false);
    return turn;
  }

  async function handleTurn(text, {spoken = false, timing, interpretation}, version, reviewed) {
    if (version !== formVersion) return false;
    stopPlayback();
    if (!context) {
      try { await refreshData(); }
      catch { response.textContent = copy.data; return false; }
    }
    if (!spoken && dictation) interpretation = await understandText(text, state, context, locale);
    if (version !== formVersion || sending) return false;
    const previous = state.slots;
    const previousPhase = state.phase;
    const previousNext = state.next;
    const allowConfirm = Boolean(reviewed && reviewed === state.summary && (!spoken || context.allowConfirm));
    const turn = transferTurn(state, text, {...context, lang, allowConfirm, interpretation});
    state = turn.state;
    if (turn.message) message = turn.message;
    const changed = JSON.stringify(previous) !== JSON.stringify(state.slots);
    if (changed || previousPhase !== state.phase || previousNext !== state.next) void reflect();
    if (!turn.action) {
      if (changed || state.phase !== "ready") requestKey = undefined;
      paint();
      if (spoken && turn.message) read(turn.message, timing);
      return true;
    }

    sending = true;
    message = copy.executing;
    paint();
    const key = requestKey ??= crypto.randomUUID();
    try {
      const receipt = await execute(turn.action, key);
      state = {...initialTransfer(), phase: "complete"};
      requestKey = undefined;
      void reflect();
      message = copy.success;
      root.dispatchEvent(new CustomEvent("transfer-assistant:receipt", {bubbles: true, detail: receipt}));
      void refreshData().catch(() => { context = undefined; });
    } catch (error) {
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
      sending = false;
      paint();
    }
    if (spoken) read(message, timing);
    return true;
  }

  function checkVoice() {
    if (!voiceCheck) {
      voiceCheck = voiceAvailability().catch(() => ({})).then(available => {
        dictation = Boolean(available.dictation);
        sttWarning = available.stt || dictation ? "" : copy.stt_unavailable;
        show(captureStatus, sttWarning);
        show(voiceStatus, available.tts ? "" : copy.tts_unavailable);
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
  listen.addEventListener("click", () => read(message));
  mic = mountDictationMicrophone(microphone, {
    language: locale,
    labels: {start: copy.mic, finish: copy.stop},
    request: (blob, options) => transcribeTransferSpeech(blob, {...options, state, context, locale, dictation}),
    beforeStart: async () => {
      stopPlayback();
      show(transcript);
      if (sttWarning || voiceCheck) await checkVoice();
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
      if (dictation && result.provider === "shared") {
        show(captureStatus, lang === "es" ? "El dictado avanzado no responde. Se usa la transcripción local." : "Advanced dictation is unavailable. Using local transcription.");
      }
      show(transcript, result.text);
      if (result.text) void submit(result.text, {spoken: true, timing: {...timing, inputProvider: result.provider}, interpretation: result.interpretation});
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
