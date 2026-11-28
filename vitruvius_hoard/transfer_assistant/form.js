import {mountDictationMicrophone} from "./microphone.js";
import {createTransferReplyVoice} from "./reply_audio.js";

const API = "/__vitruvius_preview__/transfer-voice/";
const formElements = Object.getOwnPropertyDescriptor(HTMLFormElement.prototype, "elements").get;
const COPY = {
  es: {
    title: "Asistente de voz", input: "Escribir una instrucción", send: "Enviar", replay: "Escuchar respuesta",
    listening: "Escuchando…", transcribing: "Transcribiendo…", understanding: "Interpretando…",
    speechPending: "Puedes leer la respuesta mientras se prepara el audio.", speaking: "Leyendo la respuesta…",
    written: "Respuesta por escrito", trace: "Procesamiento por turno", fallback: "Reserva",
    stages: {transcribe: "Transcribe", understand: "Entiende", execute: "Ejecuta", speak: "Habla"},
    firstAudio: "Desde el fin de voz hasta el primer audio", silence: "No he oído una instrucción. Puedes repetirla o escribirla.",
    micDown: "No se ha podido abrir el micrófono. Puedes escribir la instrucción.",
    sttDown: "La transcripción no responde. Puedes escribir la instrucción.",
    dictationDown: "El servicio que interpreta la instrucción no responde. Puedes rellenar el formulario a mano.",
    extractionUnavailable: "El modelo no está disponible.", extractionTimeout: "El modelo ha agotado el tiempo de respuesta.",
    rules: "reglas", model: "modelo",
    choices: "Opciones",
    ask: name => "¿Qué pongo en «" + name + "»?", ambiguous: name => "¿Puedes concretar «" + name + "»?",
    changed: "He actualizado el formulario.", yes: "Sí", no: "No", review: "Revisa los datos.",
    confirm: "Si están bien, di «sí, confirmo» para enviarlo.",
    noChanges: "No he encontrado un cambio para el formulario. Di el nombre del campo y el valor.",
    submitted: "He solicitado el envío del formulario.", invalid: "Revisa los campos marcados antes de enviar.",
    accepted: /^(?:sí[,.]?\s*)?confirmo[.!]?$/iu,
    repair: /^(?:no[,\s]+)?mejor\b/iu,
  },
  en: {
    title: "Voice assistant", input: "Type an instruction", send: "Send", replay: "Read reply aloud",
    listening: "Listening…", transcribing: "Transcribing…", understanding: "Interpreting…",
    speechPending: "You can read the reply while the audio is prepared.", speaking: "Reading the reply…",
    written: "Written reply", trace: "Turn processing", fallback: "Fallback",
    stages: {transcribe: "Transcribes", understand: "Understands", execute: "Applies", speak: "Speaks"},
    firstAudio: "End of speech to first audio", silence: "I did not hear an instruction. Try again or type it.",
    micDown: "The microphone could not be opened. You can type the instruction.",
    sttDown: "Transcription is unavailable. You can type the instruction.",
    dictationDown: "The dictation service is unavailable. You can fill in the form by hand.",
    extractionUnavailable: "The model is unavailable.", extractionTimeout: "The model ran out of time.",
    rules: "rules", model: "model",
    choices: "Options",
    ask: name => "What should I enter for “" + name + "”?", ambiguous: name => "Can you clarify “" + name + "”?",
    changed: "I’ve updated the form.", yes: "Yes", no: "No", review: "Check the details.",
    confirm: "If they’re correct, say “I confirm” to submit.",
    noChanges: "I couldn’t find a change to make. Say the field name and its value.",
    submitted: "I’ve requested submission of the form.", invalid: "Check the highlighted fields before submitting.",
    accepted: /^(?:yes[,.]?\s*)?(?:i )?confirm[.!]?$/iu,
    repair: /^(?:no[,\s]+)?(?:actually|make that)\b/iu,
  },
};

const round = value => Math.max(0, Math.round(value));

async function request(route, body, type, signal) {
  const response = await fetch(API + route, {method: "POST", headers: {"Content-Type": type},
    body, signal, redirect: "error"});
  if (!response.ok) throw new Error(route);
  return response.json();
}

function controlsFor(form, name) {
  return [...formElements.call(form)].filter(control => control.name === name && !control.matches(":disabled,[readonly]")
    && control.matches("input:not([type=hidden],[type=file],[type=button],[type=submit],[type=reset],[type=image]),select,textarea"));
}

function readField(controls, spec) {
  const field = controls[0];
  if (!field) return undefined;
  if (field.type === "checkbox" && spec.type === "boolean") return field.checked;
  const value = field.type === "radio" ? controls.find(control => control.checked)?.value : field.value;
  if (!value) return undefined;
  if (spec.type === "integer" || spec.type === "number") {
    const number = Number(value);
    return Number.isFinite(number) ? number : undefined;
  }
  return value;
}

function setField(controls, spec, value) {
  const field = controls[0];
  if (!field || Object.is(readField(controls, spec), value)) return false;
  let changed = field;
  if (field.type === "radio") {
    changed = controls.find(control => control.value === String(value));
    if (!changed) return false;
    changed.checked = true;
  } else if (field.type === "checkbox") {
    if (typeof value !== "boolean") return false;
    field.checked = value;
  } else {
    const previous = field.value;
    field.value = String(value);
    if (field.value !== String(value)) {
      field.value = previous;
      return false;
    }
  }
  changed.dispatchEvent(new Event("input", {bubbles: true}));
  changed.dispatchEvent(new Event("change", {bubbles: true}));
  return true;
}

function mountFormAssistant(form, {schema, allowSubmit}) {
  const locale = document.documentElement.lang.toLowerCase().startsWith("en") ? "en-IE" : "es-ES";
  const copy = COPY[locale.slice(0, 2)];
  const root = document.createElement("section");
  root.className = "voice-form-assistant";
  root.setAttribute("aria-label", copy.title);
  root.innerHTML =
    '<h2 class="voice-form-assistant__title">' + copy.title + '</h2>' +
    '<div class="voice-form-assistant__controls"><button type="button" data-mic></button>' +
    '<button type="button" data-replay hidden>' + copy.replay + '</button></div>' +
    '<form class="voice-form-assistant__composer"><input aria-label="' + copy.input +
    '" placeholder="' + copy.input + '" maxlength="1000" required><button>' + copy.send + '</button></form>' +
    '<p class="voice-form-assistant__reply" data-reply aria-live="polite" hidden></p>' +
    '<p class="voice-form-assistant__status" data-status role="status" hidden></p>' +
    '<details class="voice-form-assistant__trace" open hidden><summary>' + copy.trace +
    '</summary><ol></ol></details>';
  Element.prototype.after.call(form, root);
  const composer = root.querySelector("form");
  const input = composer.querySelector("input");
  const send = composer.querySelector("button");
  const replay = root.querySelector("[data-replay]");
  const reply = root.querySelector("[data-reply]");
  const status = root.querySelector("[data-status]");
  const history = root.querySelector("details");
  const voice = createTransferReplyVoice({engine: "qwen3-tts"});
  const entries = Object.entries(schema.properties);
  const required = schema.required || [];
  const aliases = entries.flatMap(([, spec]) => [spec.title, ...(Array.isArray(spec.aliases) ? spec.aliases : [])])
    .filter(value => typeof value === "string" && value.trim() && value.length <= 128).slice(0, 128);
  const label = name => schema.properties[name]?.title || name;
  const draft = () => Object.fromEntries(entries.map(([name, spec]) => [name, readField(controlsFor(form, name), spec)]));
  const validated = new Map();
  const dateFormat = new Intl.DateTimeFormat(locale, {dateStyle: "long", timeZone: "UTC"});
  const labelMatch = new Intl.Collator(locale, {usage: "search", sensitivity: "base"});
  let pending;
  let speech;
  let lastChanged;
  let asked;
  let ready;
  let latest;
  let sttStarted;

  function show(element, text) {
    element.textContent = text;
    element.hidden = !text;
  }

  function setStatus(text) {
    show(status, text);
  }

  function startTurn(text, timing) {
    const turn = {speechEnd: timing?.speechEnd};
    turn.item = document.createElement("li");
    turn.item.innerHTML = "<strong></strong><ul></ul><p hidden></p>";
    turn.item.querySelector("strong").textContent = text;
    history.querySelector("ol").prepend(turn.item);
    history.hidden = false;
    latest = turn;
    replay.hidden = true;
    show(reply, "");
    return turn;
  }

  function trace(turn, stage, service, ms, fallback = false, rowKey = stage) {
    const step = {service, ms: round(ms), fallback};
    const list = turn.item.querySelector("ul");
    let row = list.querySelector('[data-stage="' + rowKey + '"]');
    if (!row) {
      row = document.createElement("li");
      row.dataset.stage = rowKey;
      list.append(row);
    }
    row.textContent = [copy.stages[stage], service, round(ms) + " ms", fallback && copy.fallback]
      .filter(Boolean).join(" · ");
    root.dispatchEvent(new CustomEvent("voice-assistant:trace", {bubbles: true,
      detail: {stage, ...step}}));
  }

  async function say(turn, text, isReplay = false) {
    speech?.abort();
    const controller = new AbortController();
    speech = controller;
    const started = performance.now();
    let reported = false;
    function finish(service, fallback) {
      reported = true;
      if (!isReplay) trace(turn, "speak", service, performance.now() - started, fallback);
    }
    function fallback() {
      setStatus(copy.written);
      finish("Vitruvius", true);
    }
    const timer = setTimeout(() => {
      controller.abort();
      fallback();
    }, 30_000);
    try {
      await voice.speak(text, {locale, signal: controller.signal,
        onPending: () => setStatus(copy.speechPending),
        onStart: (engine, audioAt) => {
          setStatus(copy.speaking);
          if (!isReplay && turn.speechEnd !== undefined) {
            turn.firstAudioMs = round(audioAt - turn.speechEnd);
            show(turn.item.querySelector("p"), copy.firstAudio + " · " + turn.firstAudioMs + " ms");
            root.dispatchEvent(new CustomEvent("voice-assistant:latency", {bubbles: true,
              detail: {firstAudioMs: turn.firstAudioMs, engine}}));
          }
        },
        onEnd: result => {
          setStatus("");
          finish("Boltagon · " + result.engine_id, false);
        },
        onFallback: fallback,
      });
    } finally {
      clearTimeout(timer);
      if (speech === controller) {
        speech = undefined;
      }
      if (controller.signal.aborted && !reported) finish("Vitruvius", true);
    }
  }

  function respond(turn, text) {
    turn.replay = text;
    show(reply, text);
    replay.hidden = false;
    void say(turn, text);
  }

  function summarize(current) {
    return entries
      .filter(([name]) => validated.has(name) && Object.is(current[name], validated.get(name)))
      .map(([name, spec]) => {
        const value = current[name];
        const field = controlsFor(form, name)[0];
        let display = String(value);
        if (typeof value === "boolean") display = value ? copy.yes : copy.no;
        if (field?.tagName === "SELECT") display = field.selectedOptions[0]?.label || display;
        if (spec.format === "date" && /^\d{4}-\d{2}-\d{2}$/.test(display)) {
          const date = new Date(display + "T00:00:00Z");
          if (!Number.isNaN(date.valueOf())) display = dateFormat.format(date);
        }
        const title = label(name).trim();
        display = display.trim().replace(/[.?!]+$/u, "");
        const beginsWithTitle = labelMatch.compare(display.slice(0, title.length), title) === 0
          && /^(?:$|[\s:\-–—])/u.test(display.slice(title.length));
        return (beginsWithTitle ? display : title + " " + display) + ".";
      }).join(" ");
  }

  function choiceLabel(name, value) {
    const control = controlsFor(form, name)[0];
    if (control?.tagName === "SELECT") {
      return [...control.options].find(option => option.value === String(value))?.label || String(value);
    }
    return String(value);
  }

  async function interpret(text, transcription, timing) {
    speech?.abort();
    speech = undefined;
    const turn = startTurn(text || (transcription ? copy.silence : ""), timing);
    if (transcription) trace(turn, "transcribe", transcription.provider || "Boltagon",
      transcription.elapsed, /reserva|fallback/i.test(transcription.provider || ""));
    if (!text) {
      respond(turn, copy.silence);
      return;
    }
    send.disabled = true;
    microphone.setDisabled(true);
    pending = new AbortController();
    const active = pending;
    try {
      const started = performance.now();
      const values = draft();
      if (allowSubmit && ready === JSON.stringify(values) && copy.accepted.test(text.trim())) {
        trace(turn, "understand", "Vitruvius", performance.now() - started);
        const began = performance.now();
        const valid = HTMLFormElement.prototype.reportValidity.call(form);
        if (valid) {
          ready = undefined;
          // No synthetic click or custom transport: the project's normal submit handlers own the action.
          HTMLFormElement.prototype.requestSubmit.call(form);
        }
        trace(turn, "execute", "Vitruvius", performance.now() - began);
        respond(turn, valid ? copy.submitted : copy.invalid);
        return;
      }
      setStatus(copy.understanding);
      let understood;
      const correction = copy.repair.test(text);
      const field = (correction && lastChanged) || asked;
      try {
        const option_labels = Object.fromEntries(entries.filter(([, spec]) => Array.isArray(spec.enum)).map(([name, spec]) => [
          name, Object.fromEntries(spec.enum.map(value => [String(value), choiceLabel(name, value)])),
        ]));
        const signal = AbortSignal.any([active.signal, AbortSignal.timeout(12_000)]);
        understood = await request("form-understand", JSON.stringify({version: "cyrano.dictation/v0",
          language: locale, schema, text, vocabulary: aliases, correction,
          context: {draft: values, option_labels, ...(field ? {field} : {})}}),
        "application/json", signal);
        if (understood.version !== "cyrano.dictation/v0" || understood.is_final !== true) {
          throw new Error("dictation_version");
        }
      } catch {
        if (!active.signal.aborted) {
          ready = undefined;
          trace(turn, "understand", "Vitruvius", performance.now() - started, true);
          respond(turn, copy.dictationDown);
        }
        return;
      }
      if (active.signal.aborted) return;
      const steps = understood.understanding_steps || [];
      for (const step of steps) {
        trace(turn, "understand", copy[step.method], step.ms,
          step.outcome === "unavailable" || step.outcome === "timeout", "understand-" + step.method);
      }
      const began = performance.now();
      const cited = [];
      let lastApplied;
      for (const [name, spec] of entries) {
        const result = understood.fields?.[name];
        if (result?.validation !== "valid" || typeof result.quote !== "string" || !result.quote.trim()) continue;
        const controls = controlsFor(form, name);
        if (setField(controls, spec, result.value)) lastApplied = name;
        if (controls.length && result.value !== undefined && Object.is(readField(controls, spec), result.value)) {
          validated.set(name, result.value);
          cited.push(name);
        }
      }
      lastChanged = lastApplied || cited.at(-1) || lastChanged;
      trace(turn, "execute", "Vitruvius", performance.now() - began);
      const current = draft();
      const ambiguous = understood.ambiguous?.find(({field}) => Object.hasOwn(schema.properties, field));
      asked = ambiguous?.field || required.find(name => current[name] === undefined)
        || (correction && !cited.length && Array.isArray(schema.properties[field]?.enum) ? field : undefined);
      ready = !asked && cited.length ? JSON.stringify(current) : undefined;
      const choices = asked && (ambiguous?.candidates?.length ? ambiguous.candidates : schema.properties[asked]?.enum);
      const question = asked && [ambiguous ? copy.ambiguous(label(asked)) : copy.ask(label(asked)),
        choices?.length && copy.choices + ": " + choices.slice(0, 8).map(value => choiceLabel(asked, value)).join(", ") + ".",
      ].filter(Boolean).join(" ");
      const outcome = steps.find(step => step.method === "model")?.outcome;
      const modelNotice = outcome === "timeout" ? copy.extractionTimeout
        : outcome === "unavailable" ? copy.extractionUnavailable : "";
      const message = [cited.length && (summarize(current) || copy.changed), modelNotice, question ||
        (cited.length ? copy.review + (allowSubmit ? " " + copy.confirm : "") : copy.noChanges)];
      respond(turn, message.filter(Boolean).join(" "));
    } finally {
      pending = undefined;
      send.disabled = false;
      microphone.setDisabled(false);
    }
  }

  const microphone = mountDictationMicrophone(root.querySelector("[data-mic]"), {
    language: locale, partials: false, finalTimeoutMs: 32_000,
    beforeStart() {
      voice.activate();
      speech?.abort();
      speech = undefined;
      sttStarted = undefined;
      send.disabled = true;
      return true;
    },
    onStatus(phase) {
      if (phase === "recording") setStatus(copy.listening);
      if (phase === "transcribing") setStatus(copy.transcribing);
      if (!phase) {
        send.disabled = false;
        setStatus("");
      }
    },
    async request(blob, {signal}) {
      sttStarted = performance.now();
      const query = new URLSearchParams({language: locale.slice(0, 2), initial_prompt: aliases.join(", ")});
      const result = await request("transcribe?" + query, blob, blob.type, signal);
      return {...result, elapsed: performance.now() - sttStarted};
    },
    onFinal(result, timing) {
      void interpret(String(result.text || "").trim(), {...result, elapsed: result.elapsed || 0}, timing);
    },
    onError(code) {
      const text = code === "stt_unavailable" ? copy.sttDown : copy.micDown;
      const turn = startTurn(text);
      trace(turn, "transcribe", "Vitruvius", sttStarted ? performance.now() - sttStarted : 0, true);
      show(reply, text);
    },
  });
  composer.addEventListener("submit", event => {
    event.preventDefault();
    const text = input.value.trim();
    if (send.disabled || !text) return;
    voice.activate();
    input.value = "";
    void interpret(text);
  });
  replay.addEventListener("click", () => {
    if (!latest?.replay || send.disabled) return;
    voice.activate();
    void say(latest, latest.replay, true);
  });
  function destroy() {
    window.removeEventListener("pagehide", destroy);
    microphone.destroy();
    pending?.abort();
    speech?.abort();
    voice.close();
    root.remove();
  }
  window.addEventListener("pagehide", destroy, {once: true});
  return {form, destroy};
}

const mounts = new Map();
const markers = document.querySelectorAll("span[data-voice-assistant]");

function syncMounts() {
  for (const [marker, mount] of mounts) {
    if (marker.isConnected && mount.form.isConnected) continue;
    mount.destroy();
    mounts.delete(marker);
  }
  for (const marker of markers) {
    if (!marker.isConnected || mounts.has(marker)) continue;
    let config;
    let matches;
    try {
      config = JSON.parse(marker.dataset.voiceAssistant);
      matches = document.querySelectorAll(config.formSelector);
    } catch {
      continue;
    }
    if (matches.length === 1 && matches[0] instanceof HTMLFormElement
        && ![...mounts.values()].some(mount => mount.form === matches[0])) {
      mounts.set(marker, mountFormAssistant(matches[0], config));
    }
  }
}

const observer = new MutationObserver(syncMounts);
observer.observe(document.body, {childList: true, subtree: true});
window.addEventListener("pagehide", () => observer.disconnect(), {once: true});
syncMounts();
