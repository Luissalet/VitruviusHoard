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


function mockCapture(t) {
  let voiced = false;
  let time = 0;
  let tick;
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
    setInterval: handler => { tick = handler; return 1; },
    clearInterval: () => { tick = undefined; },
  };
  for (const [name, value] of Object.entries(overrides)) {
    const old = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, {configurable: true, writable: true, value});
    t.after(() => old ? Object.defineProperty(globalThis, name, old) : delete globalThis[name]);
  }
  return async (duration, voice = false) => {
    voiced = voice;
    for (let frame = 0; frame < duration; frame += 50) {
      time += 50;
      tick?.();
      await new Promise(resolve => setImmediate(resolve));
    }
  };
}

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
    assert.deepEqual(requests, endTurn ? [true, false] : [false]);
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

test("the adaptive detector can complete a brief response with two voiced frames", async t => {
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


test("a late short verdict waits instead of cutting immediately from a stale snapshot", async t => {
  const advance = mockCapture(t);
  const {recordDictation} = await import("../vitruvius_hoard/transfer_assistant/microphone.js");
  const pending = Promise.withResolvers();
  const final = [];
  let requests = 0;
  await recordDictation({
    request: async () => ({text: ++requests === 1 ? "Sí" : "Sí, confirmo"}),
    endTurn: async result => {
      if (requests === 1) await pending.promise;
      return {silenceMs: 650, result};
    },
    onFinal: result => final.push(result.text),
  });
  await advance(400, true);
  await advance(900);
  pending.resolve();
  await advance(50);
  assert.deepEqual(final, []);
  await advance(350, true);
  await advance(650);
  assert.deepEqual(final, ["Sí, confirmo"]);
});
