import assert from "node:assert/strict";
import {test} from "node:test";

class Element extends EventTarget {
  constructor() {
    super();
    this.children = [];
    this.dataset = {};
    this.classList = {add() {}};
    this.value = "";
  }

  setAttribute() {}
  removeAttribute() {}
  toggleAttribute() {}
  append(item) { this.children.push(item); }
  replaceChildren(...items) { this.children = items; }
  closest() { return null; }
  getClientRects() { return [true]; }
}

test("a pending microphone request can be cancelled and a late grant stops its tracks", async t => {
  const {mountDictationMicrophone} = await import("../vitruvius_hoard/transfer_assistant/microphone.js");
  const pending = Promise.withResolvers();
  const requestStarted = Promise.withResolvers();
  const navigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  let requests = 0;
  let stopped = 0;
  let captureInitializations = 0;
  const recorder = Object.getOwnPropertyDescriptor(globalThis, "MediaRecorder");
  Object.defineProperty(globalThis, "MediaRecorder", {configurable: true, value: class {
    static isTypeSupported() { captureInitializations++; return false; }
  }});
  Object.defineProperty(globalThis, "navigator", {configurable: true, value: {mediaDevices: {
    getUserMedia() {
      requests++;
      if (requests === 2) return Promise.reject(new DOMException("blocked", "NotAllowedError"));
      requestStarted.resolve();
      return pending.promise;
    },
  }}});
  globalThis.document = new EventTarget();
  globalThis.window = new EventTarget();
  t.after(() => {
    delete globalThis.document;
    delete globalThis.window;
    if (navigatorDescriptor) Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
    else delete globalThis.navigator;
    if (recorder) Object.defineProperty(globalThis, "MediaRecorder", recorder);
    else delete globalThis.MediaRecorder;
  });
  const button = new Element();
  const phases = [], errors = [];
  mountDictationMicrophone(button, {request() { assert.fail("No audio should be sent"); },
    onStatus: phase => phases.push(phase), onError: error => errors.push(error)});

  button.dispatchEvent(new Event("click"));
  await requestStarted.promise;
  assert.equal(button.textContent, "Cancelar solicitud");
  assert.equal(button.disabled, false);
  button.dispatchEvent(new Event("click"));
  assert.equal(button.textContent, "Hablar");
  pending.resolve({getTracks: () => [{stop() { stopped++; }}]});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(stopped, 1);
  assert.equal(captureInitializations, 0);
  assert.deepEqual(phases, ["", "getting_mic", ""]);
  assert.deepEqual(errors, []);

  button.dispatchEvent(new Event("click"));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(errors, ["mic_permission_denied"]);
  assert.equal(button.textContent, "Hablar");
  assert.equal(button.disabled, false);
});

test("the microphone permission message survives a delayed voice availability check", {timeout: 5000}, async t => {
  const availability = Promise.withResolvers();
  const permission = Promise.withResolvers();
  const requesting = Promise.withResolvers();
  let mic;
  const navigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  const recorderDescriptor = Object.getOwnPropertyDescriptor(globalThis, "MediaRecorder");
  Object.defineProperty(globalThis, "navigator", {configurable: true, value: {mediaDevices: {
    getUserMedia() {
      requesting.resolve();
      return permission.promise;
    },
  }}});
  Object.defineProperty(globalThis, "MediaRecorder", {configurable: true, value: class {}});
  globalThis.document = Object.assign(new EventTarget(), {
    documentElement: {lang: "es"},
    createElement: () => new Element(),
    querySelectorAll: () => [],
  });
  globalThis.window = new EventTarget();
  t.after(() => {
    if (mic?.textContent === "Cancelar solicitud") mic.dispatchEvent(new Event("click"));
    availability.resolve(Response.json({dictation: true, stt: true}));
    permission.resolve({getTracks: () => []});
    delete globalThis.document;
    delete globalThis.window;
    if (navigatorDescriptor) Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
    else delete globalThis.navigator;
    if (recorderDescriptor) Object.defineProperty(globalThis, "MediaRecorder", recorderDescriptor);
    else delete globalThis.MediaRecorder;
  });
  t.mock.method(globalThis, "fetch", url => {
    assert.ok(url.endsWith("/capabilities"), url);
    return availability.promise;
  });
  const {mountTransferAssistant} = await import("../vitruvius_hoard/transfer_assistant/assistant.js");
  const root = new Element();
  mountTransferAssistant(root, {loadContext: async () => ({accounts: [], contacts: []})});
  mic = root.children.flatMap(item => item.children).find(item => item.textContent === "Hablar");
  mic.dispatchEvent(new Event("click"));
  const waiting = root.children.find(item => item.textContent?.startsWith("Comprobando la conexión"));
  assert.ok(waiting);
  availability.resolve(Response.json({dictation: true, stt: true, dictation_route: "direct"}));
  await requesting.promise;
  assert.match(waiting.textContent, /^Esperando permiso del micrófono/u);
  assert.equal(mic.textContent, "Cancelar solicitud");
  mic.dispatchEvent(new Event("click"));
  assert.equal(mic.textContent, "Hablar");
  assert.equal(waiting.textContent, "");
});

test("a reply computed while a newer turn is queued cannot start audio or be replayed", {timeout: 5000}, async t => {
  const field = new Element();
  field.dataset.transferSlot = "amountCents";
  const reflection = Promise.withResolvers();
  const reflecting = Promise.withResolvers();
  const understanding = Promise.withResolvers();
  const understandingStarted = Promise.withResolvers();
  const played = Promise.withResolvers();
  const submitted = [];
  const scheduled = [];
  globalThis.HTMLSelectElement = class extends Element {};
  globalThis.document = Object.assign(new EventTarget(), {
    documentElement: {lang: "es"},
    createElement: () => new Element(),
    querySelectorAll: selector => selector === "[data-transfer-slot]" ? [field] : [],
  });
  globalThis.window = Object.assign(new EventTarget(), {
    HoardApp: {clearPoint() {}, pointTo() { reflecting.resolve(); return reflection.promise; }},
  });
  globalThis.AudioContext = class {
    state = "running";
    currentTime = 0;
    destination = {};
    createBuffer(_channels, frames, rate) {
      return {duration: frames / rate, getChannelData: () => new Float32Array(frames)};
    }
    createBufferSource() {
      return {connect() {}, disconnect() {}, stop() {}, start() {
        scheduled.push(submitted.at(-1));
        played.resolve();
        queueMicrotask(() => this.onended?.());
      }};
    }
  };
  t.after(() => {
    understanding.resolve();
    reflection.resolve();
    for (const name of ["window", "document", "HTMLSelectElement", "AudioContext"]) delete globalThis[name];
  });
  t.mock.method(globalThis, "fetch", async (url, request) => {
    if (url.endsWith("/capabilities")) return Response.json({dictation: false, stt: false});
    if (url.endsWith("/understand")) {
      understandingStarted.resolve();
      await understanding.promise;
      return Response.json({code: "offline"}, {status: 503});
    }
    if (request?.method === "DELETE") return Response.json({ok: true});
    assert.ok(url.endsWith("/reply"), url);
    submitted.push(JSON.parse(request.body).text);
    const version = "cyrano.voice/v0";
    const job = "a".repeat(32);
    const engine = "qwen3-tts";
    const events = [
      {type: "start", version, job_id: job, sample_rate: 8000, buffer_frames: 800, encoding: "pcm_s16le", channels: 1},
      {type: "audio", offset_frames: 0, frames: 800, data_base64: Buffer.alloc(1600).toString("base64")},
      {type: "end", version, job_id: job, engine_id: engine, state: "succeeded", duration_s: 0.1},
    ];
    return new Response(events.map(event => JSON.stringify(event) + "\n").join(""), {
      headers: {"X-Transfer-Voice-Job": job, "X-Transfer-Voice-Engine": engine},
    });
  });

  const {mountTransferAssistant} = await import("../vitruvius_hoard/transfer_assistant/assistant.js");
  const root = new Element();
  const assistant = mountTransferAssistant(root, {loadContext: async () => ({
    accounts: [{id: "daily", name: "Cuenta diaria", aliases: ["diaria"], balanceCents: 150000}],
    contacts: [{id: "marta", name: "Marta Vidal", aliases: ["Marta"]}],
  })});
  const first = assistant.submit("Haz una transferencia a Marta de 40 euros con concepto cena desde la cuenta diaria");
  await understandingStarted.promise;
  const next = assistant.submit("cancela");
  understanding.resolve();
  await reflecting.promise;
  assert.match(root.children[1].textContent, /^¿Confirmas la transferencia/u);
  const listen = root.children.flatMap(element => element.children).find(element => element.textContent === "Escuchar respuesta");
  listen.dispatchEvent(new Event("click"));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(submitted, []);
  assert.deepEqual(scheduled, []);
  reflection.resolve();
  assert.equal(await first, true);
  assert.equal(await next, true);
  await played.promise;
  assert.deepEqual(submitted, ["Transferencia cancelada."]);
  assert.deepEqual(scheduled, ["Transferencia cancelada."]);
});


test("playback and replay shorten the IBAN while the written reply and form keep it", async t => {
  const iban = "ES8200000000000000000000";
  const field = new Element();
  field.dataset.transferSlot = "iban";
  const spoken = [];
  const conversation = [];
  globalThis.HTMLSelectElement = class extends Element {};
  globalThis.document = Object.assign(new EventTarget(), {
    documentElement: {lang: "es"},
    createElement: () => new Element(),
    querySelectorAll: selector => selector === "[data-transfer-slot]" ? [field] : [],
  });
  globalThis.window = Object.assign(new EventTarget(), {
    HoardApp: {reportConversation: entry => conversation.push(entry)},
  });
  globalThis.AudioContext = class { state = "running"; };
  t.after(() => {
    for (const name of ["window", "document", "HTMLSelectElement", "AudioContext"]) delete globalThis[name];
  });
  t.mock.method(globalThis, "fetch", async (url, request) => {
    if (url.endsWith("/capabilities")) return Response.json({dictation: false, stt: false});
    if (url.endsWith("/reply")) spoken.push(JSON.parse(request.body).text);
    return Response.json({code: "offline"}, {status: 503});
  });

  const {mountTransferAssistant} = await import("../vitruvius_hoard/transfer_assistant/assistant.js");
  const root = new Element();
  const assistant = mountTransferAssistant(root, {loadContext: async () => ({
    accounts: [{id: "daily", name: "Cuenta diaria", aliases: ["diaria"], balanceCents: 10000}],
    contacts: [{id: "marta", name: "Marta Vidal", iban}],
  })});
  assert.equal(await assistant.submit(`A ${iban} por 40 euros, concepto cena desde diaria`), true);
  const written = root.children[1].textContent;
  assert.ok(written.includes(iban));
  assert.equal(field.value, iban);
  assert.equal(root.children[4].children[0].children[1].textContent, iban);
  assert.equal(conversation.find(entry => entry.role === "assistant").text, written);
  const listen = root.children.flatMap(element => element.children).find(element => element.textContent === "Escuchar respuesta");
  listen.dispatchEvent(new Event("click"));
  assert.deepEqual(spoken, Array(2).fill(written.replace(iban, "la cuenta terminada en 0000")));
  assert.equal(root.children[1].textContent, written);

  assert.equal(await assistant.submit("A Marta"), true);
  assert.equal(field.value, "");
  assert.match(spoken.at(-1), /a Marta Vidal desde/u);
  assert.equal(spoken.at(-1), root.children[1].textContent);
});


function mockCapture(t) {
  let voiced = false;
  let time = 0;
  let tick;
  let sampleMs;
  class Recorder extends EventTarget {
    static isTypeSupported() { return true; }
    mimeType = "audio/webm";
    state = "inactive";
    start() { this.state = "recording"; }
    requestData() {
      queueMicrotask(() => this.dispatchEvent(Object.assign(new Event("dataavailable"), {data: new Blob(["audio"])})));
    }
    stop() {
      this.state = "inactive";
      this.requestData();
      queueMicrotask(() => this.dispatchEvent(new Event("stop")));
    }
  }
  const track = Object.assign(new EventTarget(), {stop() {}});
  const overrides = {
    navigator: {mediaDevices: {getUserMedia: async () => ({getTracks: () => [track]})}},
    performance: {now: () => time},
    MediaRecorder: Recorder,
    AudioContext: class {
      createAnalyser() { return {getFloatTimeDomainData(samples) { samples.fill(voiced ? .2 : 0); }}; }
      createMediaStreamSource() { return {connect() {}}; }
      async resume() {}
      async close() {}
    },
    setInterval: (handler, interval) => { tick = handler; sampleMs = interval; return 1; },
    clearInterval: () => { tick = undefined; },
  };
  for (const [name, value] of Object.entries(overrides)) {
    const old = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, {configurable: true, writable: true, value});
    t.after(() => old ? Object.defineProperty(globalThis, name, old) : delete globalThis[name]);
  }
  return async (duration, voice = false, sample = true) => {
    voiced = voice;
    if (!sample) return;
    for (let frame = 0; frame < duration; frame += sampleMs) {
      time += sampleMs;
      tick?.();
      await new Promise(resolve => setImmediate(resolve));
    }
  };
}

for (const mode of ["accepted", "incomplete", "failed", "resumed", "speaking", "pending"]) {
  test("manual microphone finish uses the correct transcript: " + mode, async t => {
    const advance = mockCapture(t);
    const {recordDictation} = await import("../vitruvius_hoard/transfer_assistant/microphone.js");
    const requests = [];
    const final = [];
    const deferred = Promise.withResolvers();
    const capture = await recordDictation({
      request: async (_blob, {partial}) => {
        requests.push(partial);
        return {text: partial ? "Veinte euros" : "Veinte euros con concepto cena"};
      },
      endTurn: async result => {
        if (mode === "failed") throw new Error("Unavailable");
        if (mode === "pending") await deferred.promise;
        return {silenceMs: mode === "incomplete" ? 1650 : 650, result};
      },
      onFinal: (result, timing) => final.push({result, timing}),
    });
    await advance(400, true);
    await advance(200);
    if (mode === "resumed") {
      await advance(125, true);
      await advance(25);
    }
    if (mode === "speaking") await advance(1, true, false);
    capture.stop();
    deferred.resolve();
    await new Promise(resolve => setImmediate(resolve));
    const reused = mode === "accepted";
    assert.deepEqual(requests, reused ? [true] : [true, false]);
    assert.equal(final.length, 1);
    assert.equal(final[0].result.text, reused ? "Veinte euros" : "Veinte euros con concepto cena");
    assert.equal(final[0].timing.reusedProvisional, reused);
    assert.equal(final[0].timing.stopReason, "manual");
  });
}

test("busy and unavailable microphone buttons expose a reason", async t => {
  const {mountDictationMicrophone} = await import("../vitruvius_hoard/transfer_assistant/microphone.js");
  const navigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  globalThis.document = new EventTarget();
  globalThis.window = new EventTarget();
  t.after(() => {
    delete globalThis.document;
    delete globalThis.window;
    if (navigatorDescriptor) Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
    else delete globalThis.navigator;
  });
  function mount(mediaDevices) {
    Object.defineProperty(globalThis, "navigator", {configurable: true, value: {mediaDevices}});
    const button = new Element();
    const phases = [];
    const microphone = mountDictationMicrophone(button, {request() {}, onStatus: phase => phases.push(phase)});
    return {button, phases, microphone};
  }
  const ready = mount({getUserMedia() {}});
  ready.microphone.setDisabled(true);
  assert.equal(ready.button.disabled, true);
  assert.equal(ready.phases.at(-1), "busy");
  ready.microphone.setDisabled(false);
  assert.equal(ready.button.disabled, false);
  assert.equal(ready.phases.at(-1), "");

  const unavailable = mount(undefined);
  assert.equal(unavailable.button.disabled, true);
  assert.equal(unavailable.phases.at(-1), "unavailable");
});

test("a renewed pause invalidates an in-flight provisional parse", async t => {
  const advance = mockCapture(t);
  const {recordDictation} = await import("../vitruvius_hoard/transfer_assistant/microphone.js");
  const old = Promise.withResolvers();
  const final = [];
  let firstSignal;
  let probes = 0;
  await recordDictation({
    request: async (_blob, {partial}) => {
      assert.equal(partial, true);
      return {text: ++probes === 1 ? "Sí" : "Sí, confirmo"};
    },
    endTurn: async (result, {signal}) => {
      if (probes === 1) {
        firstSignal = signal;
        await old.promise; // The double can complete after cancellation.
      }
      return {silenceMs: 650, result};
    },
    onFinal: (result, timing) => final.push({result, timing}),
  });
  await advance(400, true);
  await advance(500);
  assert.ok(firstSignal && !firstSignal.aborted);
  await advance(250, true);
  assert.equal(firstSignal.aborted, true);
  old.resolve();
  await advance(600);
  assert.deepEqual(final, []);
  await advance(50);
  assert.equal(final.length, 1);
  assert.equal(final[0].result.text, "Sí, confirmo");
  assert.equal(final[0].timing.stopReason, "adaptive");
  assert.equal(final[0].timing.captureStoppedAt - final[0].timing.speechEnd, 650);
});

test("an incomplete partial survives a pause longer than the short threshold", async t => {
  const advance = mockCapture(t);
  const {recordDictation} = await import("../vitruvius_hoard/transfer_assistant/microphone.js");
  const final = [];
  let probes = 0;
  await recordDictation({
    request: async (_blob, {partial}) => {
      assert.equal(partial, true);
      return {text: ++probes === 1 ? "Treinta y" : "Treinta y cinco euros"};
    },
    endTurn: async result => result.text === "Treinta y" ? null : {silenceMs: 650, result},
    onFinal: result => final.push(result),
  });
  await advance(400, true);
  await advance(1050);
  assert.deepEqual(final, []);
  await advance(400, true);
  await advance(650);
  assert.deepEqual(final, [{text: "Treinta y cinco euros"}]);
});

test("failed adaptive probes use a full final and legacy callers keep 1500 ms", async t => {
  const advance = mockCapture(t);
  const {recordDictation} = await import("../vitruvius_hoard/transfer_assistant/microphone.js");
  for (const endTurn of [undefined, async () => { throw new Error("missing"); }]) {
    const final = [];
    const requests = [];
    await recordDictation({
      request: async (_blob, {partial}) => {
        requests.push(partial);
        return {text: partial ? "continuación" : "final íntegro"};
      },
      endTurn,
      onFinal: (result, timing) => final.push({result, timing}),
    });
    const cutoff = endTurn ? 1650 : 1500;
    await advance(400, true);
    await advance(cutoff - 50);
    assert.deepEqual(final, []);
    await advance(50);
    assert.equal(final[0].result.text, "final íntegro");
    assert.equal(final[0].timing.captureStoppedAt - final[0].timing.speechEnd, cutoff);
    assert.deepEqual(requests, endTurn ? [true, true, false] : [false]);
  }
});

test("local commands skip understand and a speculative interpretation commits only in finalization", async t => {
  const {
    assessTransferEndTurn, finishProvisionalTransfer, transcribeTransferSpeech,
  } = await import("../vitruvius_hoard/transfer_assistant/voice.js");
  const routes = [];
  const decision = {
    decision: "short", silence_ms: 650, interpretation: {version: "cyrano.dictation/v0", is_final: false,
      raw_transcript: "Veinte euros", fields: {amount_cents: {value: 2000}},
      changed: ["amount_cents"], missing: [], ambiguous: []},
  };
  t.mock.method(globalThis, "fetch", async (url, request) => {
    const route = url.split("/").at(-1).split("?")[0];
    routes.push(route);
    if (route === "transcribe") return Response.json({text: "Sí, confirmo", provider: "Boltagon"});
    assert.equal(route, "end-turn");
    const body = JSON.parse(request.body);
    assert.equal(body.dialogue, "slots");
    assert.equal(body.context.field, "amount_cents");
    return Response.json(decision);
  });
  const signal = new AbortController().signal;
  const options = {signal, locale: "es-ES", state: {phase: "collecting", next: "amountCents", slots: {}}};
  assert.equal((await transcribeTransferSpeech(new Blob(["test"]), options)).text, "Sí, confirmo");
  assert.deepEqual(routes, ["transcribe"]);
  const proposal = await assessTransferEndTurn({text: "Veinte euros"}, options);
  assert.equal(proposal.result.provisionalInterpretation.is_final, false);
  assert.equal(finishProvisionalTransfer(proposal.result).interpretation.is_final, true);
  assert.equal(proposal.result.provisionalInterpretation.is_final, false);
  assert.deepEqual(routes, ["transcribe", "end-turn"]);
});


test("an affirmative review waits for a later correction and uses the final recording", async t => {
  const advance = mockCapture(t);
  const {recordDictation} = await import("../vitruvius_hoard/transfer_assistant/microphone.js");
  const {assessTransferEndTurn} = await import("../vitruvius_hoard/transfer_assistant/voice.js");
  const {initialTransfer, transferTurn} = await import("../vitruvius_hoard/transfer_assistant/dialogue.js");
  const context = {accounts: [{id: "daily", name: "Cuenta diaria", aliases: ["diaria"], balanceCents: 10000}],
    contacts: [{id: "marta", name: "Marta Vidal", aliases: ["Marta"]}]};
  const draft = "Haz una transferencia a Marta de 40 euros con concepto cena desde la cuenta diaria";
  const {state} = transferTurn(initialTransfer(), draft, context);
  assert.equal(state.phase, "ready");
  const correction = "Sí. No, mejor cincuenta";
  const final = [];
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.ok(url.endsWith("/end-turn"), url);
    assert.equal(JSON.parse(options.body).text, correction, "The prefix must not consult the cutoff service");
    return Response.json({decision: "long", silence_ms: 1650, reason: "incomplete"});
  });
  const capture = () => recordDictation({
    request: async (_blob, {partial}) => {
      requests.push(partial);
      return {text: requests.length === 1 ? "Sí" : correction};
    },
    endTurn: (turn, {signal}) => assessTransferEndTurn(turn, {state, context, locale: "es-ES", signal}),
    onFinal: (result, timing) => final.push({result, timing, outcome: transferTurn(state, result.text, context)}),
  });
  await capture();
  await advance(300, true);
  await advance(800);
  assert.deepEqual(final, []);
  await advance(450, true);
  await advance(1650);
  assert.deepEqual(requests, [true, true, false]);
  assert.equal(final[0].timing.stopReason, "silence");
  assert.equal(final[0].result.text, correction);
  assert.equal(final[0].outcome.action, undefined);

  // A real confirmation remains available, but only after a final request.
  const confirmation = [];
  await recordDictation({
    request: async (_blob, {partial}) => {
      confirmation.push(partial);
      return {text: "Sí, confirmo"};
    },
    endTurn: (turn, {signal}) => assessTransferEndTurn(turn, {state, context, locale: "es-ES", signal}),
    onFinal: (result, timing) => final.push({result, timing, outcome: transferTurn(state, result.text, context)}),
  });
  await advance(300, true);
  await advance(1450);
  assert.equal(final.length, 1);
  await advance(50);
  assert.deepEqual(confirmation, [true, false]);
  assert.equal(final[1].timing.stopReason, "silence");
  assert.equal(final[1].outcome.action.amountCents, 4000);
});

test("the adaptive detector can complete a brief response with 100 ms of voiced samples", async t => {
  const advance = mockCapture(t);
  const {recordDictation} = await import("../vitruvius_hoard/transfer_assistant/microphone.js");
  const final = [];
  await recordDictation({
    request: async (_blob, {partial}) => {
      assert.equal(partial, true);
      return {text: "Sí"};
    },
    endTurn: async result => ({silenceMs: 650, result}),
    onFinal: result => final.push(result),
  });
  await advance(100, true);
  await advance(650);
  assert.deepEqual(final, [{text: "Sí"}]);
});


for (const [latency, silenceMs, cutoff] of [[450, 650, 650], [550, 650, 675], [700, 650, 825], [550, 1650, 1650]]) {
  test(`a ${silenceMs} ms verdict with ${latency} ms transcription cuts at ${cutoff} ms`, async t => {
    const advance = mockCapture(t);
    const {recordDictation} = await import("../vitruvius_hoard/transfer_assistant/microphone.js");
    const transcript = Promise.withResolvers();
    const short = silenceMs === 650;
    const final = [];
    const requests = [];
    let probeAt;
    await recordDictation({
      request: async (_blob, {partial}) => {
        requests.push(partial);
        if (!partial) return {text: "Treinta y cinco euros"};
        probeAt = performance.now();
        await transcript.promise;
        return {text: short ? "Veinte euros" : "Treinta y"};
      },
      endTurn: async result => ({silenceMs, result}),
      onFinal: (result, timing) => final.push({result, timing}),
    });
    await advance(400, true);
    const speechEnd = performance.now();
    await advance(125);
    assert.equal(probeAt - speechEnd, 125);
    await advance(latency);
    assert.deepEqual(final, []);
    transcript.resolve();
    await new Promise(resolve => setImmediate(resolve));

    const remaining = cutoff - (probeAt - speechEnd + latency);
    if (remaining > 0) {
      await advance(remaining - 25);
      assert.deepEqual(final, []);
      await advance(25);
    }
    assert.equal(final.length, 1);
    assert.equal(final[0].result.text, short ? "Veinte euros" : "Treinta y cinco euros");
    assert.equal(final[0].timing.captureStoppedAt - final[0].timing.speechEnd, cutoff);
    assert.equal(final[0].timing.stopReason, short ? "adaptive" : "silence");
    assert.deepEqual(requests, short ? [true] : [true, false]);
  });
}

test("a rejected snapshot retries during the final pause without waiting on an obsolete request", async t => {
  const advance = mockCapture(t);
  const {recordDictation} = await import("../vitruvius_hoard/transfer_assistant/microphone.js");
  const first = Promise.withResolvers();
  const final = [];
  const requests = [];
  let busyUntil = 0;
  let obsoleteSignal;
  await recordDictation({
    request: async (_blob, {partial, signal}) => {
      const now = performance.now();
      const busy = now < busyUntil;
      requests.push({partial, now, status: busy ? 429 : 200});
      if (busy) throw new Error("partial_busy");
      busyUntil = now + 700;
      if (requests.length === 1) {
        obsoleteSignal = signal;
        return await first.promise;
      }
      return {text: "Treinta y cinco euros"};
    },
    endTurn: async result => ({silenceMs: 650, result}),
    onFinal: (result, timing) => final.push({result, timing}),
  });
  await advance(400, true);
  await advance(150);
  await advance(150, true);
  assert.equal(obsoleteSignal.aborted, true);
  await advance(75); // The second interior pause is too brief for another snapshot.
  await advance(200, true);
  const speechEnd = performance.now();
  await advance(150);
  assert.deepEqual(requests.map(({status}) => status), [200, 429]);
  await advance(225);
  assert.equal(requests.length, 2);
  await advance(25);
  assert.deepEqual(requests.map(({status}) => status), [200, 429, 200]);
  first.resolve({text: "Treinta y"});
  await advance(250);
  assert.deepEqual(requests, [
    {partial: true, now: 525, status: 200},
    {partial: true, now: speechEnd + 150, status: 429},
    {partial: true, now: speechEnd + 400, status: 200},
  ]);
  assert.equal(final.length, 1);
  assert.equal(final[0].result.text, "Treinta y cinco euros");
  assert.equal(final[0].timing.stopReason, "adaptive");
});

test("a late short verdict samples the microphone again before accepting its snapshot", async t => {
  const advance = mockCapture(t);
  const {recordDictation} = await import("../vitruvius_hoard/transfer_assistant/microphone.js");
  const pending = Promise.withResolvers();
  const final = [];
  let firstSignal;
  let requests = 0;
  await recordDictation({
    request: async () => ({text: ++requests === 1 ? "Sí" : "Sí, confirmo"}),
    endTurn: async (result, {signal}) => {
      if (requests === 1) {
        firstSignal = signal;
        await pending.promise;
      }
      return {silenceMs: 650, result};
    },
    onFinal: result => final.push(result.text),
  });
  await advance(400, true);
  await advance(900);
  await advance(0, true); // Speech resumes before the next scheduled sample.
  pending.resolve();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(firstSignal.aborted, true);
  assert.deepEqual(final, []);
  await advance(350, true);
  await advance(650);
  assert.deepEqual(final, ["Sí, confirmo"]);
});
