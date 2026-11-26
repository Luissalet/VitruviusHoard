import assert from "node:assert/strict";
import {test} from "node:test";
import {createTransferReplyVoice} from "../vitruvius_hoard/transfer_assistant/reply_audio.js";

const VERSION = "cyrano.voice/v0";
const ENGINE = "qwen3-tts";
const JOB = "a".repeat(32);
const SAMPLE_RATE = 8000;
const FRAMES = 800;
const start = {
  type: "start", job_id: JOB, version: VERSION, encoding: "pcm_s16le", channels: 1,
  sample_rate: SAMPLE_RATE, buffer_frames: FRAMES,
};
const block = offset => ({
  type: "audio", offset_frames: offset, frames: FRAMES,
  data_base64: Buffer.alloc(FRAMES * 2).toString("base64"),
});
const end = (blocks, cached = false) => ({
  type: "end", job_id: JOB, version: VERSION, engine_id: ENGINE, state: "succeeded", cached,
  duration_s: blocks * FRAMES / SAMPLE_RATE,
});

function pipe() {
  let controller;
  const body = new ReadableStream({start: value => { controller = value; }});
  const push = (...values) => controller.enqueue(new TextEncoder().encode(values.map(value => JSON.stringify(value) + "\n").join("")));
  const response = new Response(body, {
    headers: {"X-Transfer-Voice-Engine": ENGINE, "X-Transfer-Voice-Job": JOB},
  });
  return {response, push, close: () => controller.close()};
}

function installAudio(testContext, {finish = true, unlock} = {}) {
  const started = [];
  const stopped = [];
  globalThis.AudioContext = class {
    currentTime = 0;
    state = unlock ? "suspended" : "running";
    destination = {};
    async resume() {
      await unlock;
      this.state = "running";
    }
    createBuffer(_channels, frames, rate) {
      const samples = new Float32Array(frames);
      return {duration: frames / rate, getChannelData: () => samples};
    }
    createBufferSource() {
      return {
        connect() {},
        disconnect() {},
        start(when) {
          started.push({when, duration: this.buffer.duration});
          if (finish) setTimeout(() => this.onended?.(), 0);
        },
        stop() { stopped.push(true); },
      };
    }
  };
  testContext.after(() => { delete globalThis.AudioContext; });
  return {started, stopped};
}

test("keeps a slow full reply in writing until PCM is ready, streams it, and pins the next turn", async t => {
  const {started} = installAudio(t);
  const first = pipe();
  const second = pipe();
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.match(url, /\/transfer-voice\/reply$/u);
    return [first.response, second.response][requests.push(JSON.parse(options.body)) - 1];
  });
  const player = createTransferReplyVoice();
  player.activate();
  const callbacks = [];
  const written = Promise.withResolvers();
  const playing = Promise.withResolvers();
  const text = "¿Confirmas la transferencia de 40 euros a María con el concepto «cena»?";
  const before = performance.now();
  first.push(start);
  const speaking = player.speak(text, {
    locale: "es-ES", signal: new AbortController().signal,
    onPending: () => { callbacks.push("written"); written.resolve(); },
    onStart: name => { callbacks.push(name); playing.resolve(); },
    onFallback: () => { callbacks.push("unavailable"); written.resolve(); playing.resolve(); },
    onEnd: () => callbacks.push("end"),
  });
  await written.promise;
  assert.deepEqual(callbacks, ["written"]);
  assert.ok(performance.now() - before >= 1450);
  first.push(block(0));
  await playing.promise;
  assert.deepEqual(callbacks, ["written", ENGINE]);
  assert.equal(started.length, 1);
  first.push(block(FRAMES), end(2));
  first.close();
  await speaking;
  assert.deepEqual(callbacks, ["written", ENGINE, "end"]);
  assert.equal(started[1].when, started[0].when + started[0].duration);
  assert.deepEqual(requests[0], {version: VERSION, text, language: "es"});

  let receipt;
  second.push(start, block(0), end(1, true));
  second.close();
  const fixed = "What reference would you like to use?";
  await player.speak(fixed, {locale: "en-IE", signal: new AbortController().signal, onEnd: value => { receipt = value; }});
  assert.equal(receipt.cached, true);
  assert.deepEqual(requests[1], {version: VERSION, text: fixed, language: "en", engine: ENGINE});
});

test("aborting a playing turn stops its nodes and cancels its job once", async t => {
  const {stopped} = installAudio(t, {finish: false});
  const voice = pipe();
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push([options.method, url.split("/").at(-1)]);
    return options.method === "POST" ? voice.response : Response.json({ok: true});
  });
  const player = createTransferReplyVoice();
  player.activate();
  const aborter = new AbortController();
  const started = Promise.withResolvers();
  const callbacks = [];
  voice.push(start, block(0));
  const speaking = player.speak("Hola", {
    locale: "es-ES", signal: aborter.signal,
    onStart: started.resolve, onFallback: () => callbacks.push("unavailable"),
    onEnd: () => callbacks.push("end"),
  });
  await started.promise;
  aborter.abort();
  await speaking;
  assert.deepEqual(requests, [["POST", "reply"], ["DELETE", JOB]]);
  assert.deepEqual(stopped, [true]);
  assert.deepEqual(callbacks, []);
});

test("an unavailable service leaves the written reply and does not request another voice", async t => {
  installAudio(t);
  const requests = [];
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    requests.push(options.method);
    return Response.json({code: "voice_disabled"}, {status: 503});
  });
  const player = createTransferReplyVoice();
  player.activate();
  let written = false;
  await player.speak("Hola", {
    locale: "es-ES", signal: new AbortController().signal,
    onFallback: () => { written = true; }, onStart: () => assert.fail("Unexpected audio"),
  });
  assert.ok(written);
  assert.deepEqual(requests, ["POST"]);
});

test("a reply waits for the browser to activate its audio context", async t => {
  const unlock = Promise.withResolvers();
  const {started} = installAudio(t, {unlock: unlock.promise});
  const voice = pipe();
  voice.push(start, block(0), end(1));
  voice.close();
  t.mock.method(globalThis, "fetch", async () => voice.response);
  const player = createTransferReplyVoice();
  player.activate();
  const speaking = player.speak("Hola", {
    locale: "es-ES", signal: new AbortController().signal, onFallback: () => assert.fail("Unexpected fallback"),
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(started.length, 0);
  unlock.resolve();
  await speaking;
  assert.equal(started.length, 1);
});
