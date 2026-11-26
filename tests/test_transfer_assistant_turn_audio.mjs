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
