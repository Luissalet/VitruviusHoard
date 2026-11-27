// Web Audio playback for the same-origin relay of Boltagon's resident PCM stream.
const VERSION = "cyrano.voice/v0";
const API = "/__vitruvius_preview__/transfer-voice/reply";
const WRITTEN_AFTER_MS = 1500;
const LEAD_SECONDS = 0.025;

async function* events(body, signal) {
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  const cancel = () => reader.cancel().catch(() => {});
  signal.addEventListener("abort", cancel, {once: true});
  let partial = "";
  try {
    while (true) {
      signal.throwIfAborted();
      const {done, value} = await reader.read();
      if (done) break;
      const lines = (partial + value).split("\n");
      partial = lines.pop();
      for (const line of lines) {
        if (line) yield JSON.parse(line);
      }
    }
    if (partial) throw new Error("invalid_voice_stream");
  } finally {
    signal.removeEventListener("abort", cancel);
    await cancel();
  }
}

export async function playReplyStream(body, context, {signal, job, engine, onStart}) {
  const playing = new Set();
  const pending = [];
  let format;
  let received = 0;
  let nextAt;
  let playbackEnded;
  let end;

  function schedule(buffer) {
    const now = context.currentTime;
    const first = nextAt === undefined;
    if (first || nextAt < now) nextAt = now + LEAD_SECONDS;
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    source.onended = () => {
      playing.delete(source);
      source.disconnect();
      if (!playing.size) playbackEnded?.();
    };
    source.start(nextAt);
    playing.add(source);
    nextAt += buffer.duration;
    if (first) onStart(Math.max(0, nextAt - buffer.duration - context.currentTime));
  }

  function stop() {
    for (const source of playing) {
      source.onended = null;
      source.stop();
      source.disconnect();
    }
    playing.clear();
    playbackEnded?.();
  }

  signal.addEventListener("abort", stop, {once: true});
  try {
    for await (const event of events(body, signal)) {
      signal.throwIfAborted();
      if (event.type === "end") {
        end = event;
        break;
      }
      if (event.type === "start" && !format && event.version === VERSION && event.job_id === job
          && event.encoding === "pcm_s16le" && event.channels === 1
          && Number.isInteger(event.sample_rate) && event.sample_rate > 0
          && Number.isInteger(event.buffer_frames) && event.buffer_frames > 0) {
        format = event;
        continue;
      }
      if (event.type !== "audio" || !format || event.offset_frames !== received
          || !Number.isInteger(event.frames) || event.frames < 1) throw new Error("invalid_voice_stream");
      const raw = atob(event.data_base64);
      if (raw.length !== event.frames * 2) throw new Error("invalid_voice_stream");
      const buffer = context.createBuffer(1, event.frames, format.sample_rate);
      const samples = buffer.getChannelData(0);
      for (let index = 0; index < samples.length; index++) {
        const sample = raw.charCodeAt(index * 2) | (raw.charCodeAt(index * 2 + 1) << 8);
        samples[index] = (sample >= 32768 ? sample - 65536 : sample) / 32768;
      }
      received += event.frames;
      if (nextAt !== undefined) {
        schedule(buffer);
      } else {
        pending.push(buffer);
        if (received >= format.buffer_frames) {
          for (const part of pending) schedule(part);
          pending.length = 0;
        }
      }
    }
    if (end?.version !== VERSION || end.job_id !== job || end.engine_id !== engine || end.state !== "succeeded"
        || !format || pending.length || received !== Math.round(end.duration_s * format.sample_rate)) {
      throw new Error("invalid_voice_stream");
    }
    if (playing.size) await new Promise(resolve => { playbackEnded = resolve; });
    signal.throwIfAborted();
    return end;
  } catch (error) {
    stop();
    throw error;
  } finally {
    signal.removeEventListener("abort", stop);
  }
}

export function createTransferReplyVoice() {
  let context;
  let activation;
  let engine;

  function activate() {
    if (!globalThis.AudioContext || globalThis.navigator?.userActivation?.hasBeenActive === false) return;
    try {
      context ??= new AudioContext();
      if (context.state !== "running" && !activation) {
        activation = context.resume().catch(() => {}).finally(() => { activation = undefined; });
      }
    } catch {
      // A blocked output device leaves the written reply available.
    }
  }

  async function waitForAudio(signal) {
    if (context.state === "running") return;
    let abort;
    try {
      await Promise.race([activation, new Promise((_, reject) => {
        abort = () => reject(signal.reason);
        signal.addEventListener("abort", abort, {once: true});
      })]);
      signal.throwIfAborted();
      if (context.state !== "running") throw new Error("audio_context_inactive");
    } finally {
      if (abort) signal.removeEventListener("abort", abort);
    }
  }

  async function speak(text, {locale, signal, onPending, onFallback, onStart, onEnd, onSettled, traceId}) {
    if (signal.aborted) return;
    const requestId = crypto.randomUUID().replaceAll("-", "");
    let response;
    let submitted = false;
    let completed = false;
    function cancel() {
      if (!submitted) return;
      submitted = false;
      void fetch(API + "/request/" + requestId, {method: "DELETE", keepalive: true, redirect: "error"}).catch(() => {});
    }
    signal.addEventListener("abort", cancel, {once: true});
    const timer = setTimeout(() => { if (!signal.aborted) onPending?.(); }, WRITTEN_AFTER_MS);
    try {
      if (!context) throw new Error("audio_context_inactive");
      submitted = true;
      response = await fetch(API, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({version: VERSION, text, language: locale.slice(0, 2), engine, request_id: requestId, trace_id: traceId}),
        signal,
        redirect: "error",
      });
      if (!response.ok) {
        submitted = false;
        throw new Error("tts_unavailable");
      }
      if (!response.body) throw new Error("invalid_voice_stream");
      const job = response.headers.get("X-Transfer-Voice-Job");
      if (!/^[a-f0-9]{32}$/u.test(job)) {
        throw new Error("invalid_voice_stream");
      }
      const selected = response.headers.get("X-Transfer-Voice-Engine");
      if (!selected || engine && selected !== engine) throw new Error("voice_engine_changed");
      signal.throwIfAborted();
      engine = selected;
      await waitForAudio(signal);
      const end = await playReplyStream(response.body, context, {signal, job, engine, onStart: lead => {
        clearTimeout(timer);
        onStart?.(engine, lead);
      }});
      signal.throwIfAborted();
      completed = true;
      onEnd?.(end);
    } catch {
      if (!signal.aborted) onFallback?.();
    } finally {
      clearTimeout(timer);
      signal.removeEventListener("abort", cancel);
      if (!completed) {
        cancel();
        if (response?.body && !response.body.locked) void response.body.cancel().catch(() => {});
      }
      onSettled?.(signal.aborted ? "cancelled" : completed ? "ok" : "error");
    }
  }

  return {activate, speak};
}
