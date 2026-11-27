/** Local microphone capture for the shared dictation service. */
const MIME = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
const ADAPTIVE_PROBE_MS = 150;
const ADAPTIVE_LONG_MS = 1650;

export async function recordDictation({
  request, onPartial = () => {}, onStatus = () => {}, onFinal = () => {}, onError = () => {},
  silenceMs = 1500, maxDurationMs = 20000, finalTimeoutMs = 15000, partials = true, endTurn,
}) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {echoCancellation: true, noiseSuppression: true},
  });
  let audio;
  let capture;
  try {
    const mimeType = MIME.find(type => MediaRecorder.isTypeSupported(type));
    capture = mimeType ? new MediaRecorder(stream, {mimeType}) : new MediaRecorder(stream);
    audio = new AudioContext();
  } catch (error) {
    stream.getTracks().forEach(track => track.stop());
    throw error;
  }
  const analyser = audio.createAnalyser();
  analyser.fftSize = 512;
  audio.createMediaStreamSource(stream).connect(analyser);
  void audio.resume().catch(() => {});
  const samples = new Float32Array(analyser.fftSize);
  const chunks = [];
  const final = new AbortController();
  let partial;
  let probing;
  let proposal;
  let accepted;
  let probeRequested = false;
  let pendingSnapshot;
  let speechEpoch = 0;
  let speaking = false;
  let timer;
  let stopped = false;
  let speechEnd;
  let captureStoppedAt;
  let stopReason;
  let audibleFrames = 0;
  const minimumVoicedFrames = endTurn ? 2 : 4;
  const started = performance.now();

  function stop({cancel = false, reason = "manual"} = {}) {
    if (cancel) final.abort();
    if (stopped) return;
    stopped = true;
    partial?.abort();
    probing?.abort();
    captureStoppedAt = performance.now();
    speechEnd ??= captureStoppedAt;
    stopReason = reason;
    clearInterval(timer);
    if (capture.state !== "inactive") capture.stop();
    stream.getTracks().forEach(track => track.stop());
    void audio.close().catch(() => {});
    if (!cancel) onStatus("transcribing");
  }

  async function probe(blob, controller, observedSpeechEnd) {
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(1600)]);
    try {
      const result = await request(blob, {partial: true, adaptive: true, signal});
      signal.throwIfAborted();
      if (!result?.text) return;
      onPartial(result);
      const candidate = await endTurn(result, {signal});
      if (signal.aborted || !candidate || observedSpeechEnd !== speechEnd) return;
      proposal = candidate;
      // Recheck the microphone before cutting. Speech may have resumed between interval ticks.
      if (candidate.silenceMs <= 700 && performance.now() - observedSpeechEnd >= candidate.silenceMs) sampleVoice();
    } catch {
      // The ordinary final request still handles missing, slow and unsupported probes.
    } finally {
      if (probing === controller) probing = undefined;
    }
  }

  capture.addEventListener("dataavailable", event => {
    if (event.data.size) chunks.push(event.data);
    if (endTurn) {
      const epoch = pendingSnapshot;
      pendingSnapshot = undefined;
      if (stopped || epoch === undefined || epoch !== speechEpoch) return;
      if (!speaking && chunks.length) {
        probing = new AbortController();
        void probe(new Blob(chunks, {type: capture.mimeType}), probing, speechEnd);
      }
      return;
    }
    if (!partials || stopped || partial || !speechEnd || chunks.length < 2) return;
    const controller = new AbortController();
    partial = controller;
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(4000)]);
    Promise.resolve().then(() => request(new Blob(chunks, {type: capture.mimeType}), {partial: true, signal}))
      .then(result => {
        if (!stopped && (result?.text_clean || result?.text || result?.raw_transcript)) onPartial(result);
      })
      .catch(() => {})
      .finally(() => { partial = null; });
  });
  capture.addEventListener("stop", async () => {
    if (final.signal.aborted) return;
    const blob = new Blob(chunks, {type: capture.mimeType});
    try {
      const signal = AbortSignal.any([final.signal, AbortSignal.timeout(finalTimeoutMs)]);
      const result = accepted || (blob.size ? await request(blob, {partial: false, signal}) : {text: ""});
      if (!final.signal.aborted) onFinal(result, {
        speechEnd, captureStoppedAt, stopReason, transcriptAt: result.transcribedAt ?? performance.now(),
      });
    } catch {
      if (!final.signal.aborted) onError("stt_unavailable");
    }
  });
  capture.addEventListener("error", () => {
    if (stopped) return;
    stop({cancel: true});
    onError("mic_unavailable");
  });
  stream.getTracks().forEach(track => track.addEventListener("ended", () => {
    if (!stopped) {
      stop({cancel: true});
      onError("mic_unavailable");
    }
  }, {once: true}));

  try {
    if (endTurn) capture.start();
    else capture.start(1250);
  } catch (error) {
    stop({cancel: true});
    throw error;
  }
  function sampleVoice() {
    if (stopped) return;
    const now = performance.now();
    analyser.getFloatTimeDomainData(samples);
    const energy = Math.sqrt(samples.reduce((sum, sample) => sum + sample * sample, 0) / samples.length);
    const wasSpeaking = speaking;
    speaking = energy >= .018;
    if (speaking) {
      audibleFrames += 1;
      if (audibleFrames >= minimumVoicedFrames) speechEnd = now;
      if (endTurn && !wasSpeaking) {
        speechEpoch++;
        probing?.abort();
        probing = undefined;
        probeRequested = false;
        proposal = undefined;
      }
    } else if (!speechEnd) audibleFrames = 0;
    const pause = speechEnd ? now - speechEnd : 0;
    if (endTurn && !speaking && pause >= ADAPTIVE_PROBE_MS && !probeRequested && pendingSnapshot === undefined) {
      probeRequested = true;
      try {
        pendingSnapshot = speechEpoch;
        capture.requestData();
      } catch {
        pendingSnapshot = undefined;
      }
    }
    const cutoff = proposal?.silenceMs ?? (endTurn ? ADAPTIVE_LONG_MS : silenceMs);
    if (!speaking && pause >= cutoff) {
      accepted = proposal?.result;
      stop({reason: accepted ? "adaptive" : "silence"});
    } else if (now - started >= maxDurationMs) stop({reason: "limit"});
  }
  timer = setInterval(sampleVoice, 50);
  return {stop};
}

const LABELS = {
  es: {start: "Hablar", finish: "Terminar"},
  en: {start: "Speak", finish: "Finish"},
};

/** Bind capture to an existing button. Consumers can provide a DictationClient or their own transport. */
export function mountDictationMicrophone(button, {
  client, request, language = "es-ES", options = () => ({}), labels,
  onStatus = () => {}, beforeStart = () => true, onPartial, onFinal, onError = () => {},
  silenceMs, finalTimeoutMs, partials, endTurn, adaptive = () => true,
} = {}) {
  if (!request && !client?.understandAudio) throw new TypeError("A dictation client or request is required");
  const transcribe = request || ((blob, {partial, signal}) =>
    client.understandAudio(blob, {...options(), language, is_final: !partial, signal}));
  const copy = labels || LABELS[language.startsWith("en") ? "en" : "es"];
  let sequence = 0;
  let capture;
  let phase = "";
  let disabled = button.disabled;

  function updateButton() {
    button.textContent = phase === "recording" ? copy.finish : copy.start;
    button.setAttribute("aria-pressed", String(phase === "recording"));
    button.disabled = disabled || phase === "getting_mic" || phase === "transcribing";
  }

  function setPhase(next) {
    phase = next;
    updateButton();
    onStatus(next);
  }

  function cancel() {
    sequence++;
    capture?.stop({cancel: true});
    capture = undefined;
    if (phase) setPhase("");
  }

  async function click() {
    if (phase === "recording") {
      capture?.stop();
      return;
    }
    if (phase || disabled) return;
    const current = ++sequence;
    setPhase("getting_mic");
    function ifCurrent(handler) {
      return (...args) => { if (current === sequence) handler?.(...args); };
    }
    const reportError = ifCurrent(code => {
      capture = undefined;
      setPhase("");
      onError(code);
    });
    try {
      if (!await beforeStart() || current !== sequence) {
        if (current === sequence) setPhase("");
        return;
      }
      const next = await recordDictation({
        request: transcribe, silenceMs, finalTimeoutMs, partials, onPartial: ifCurrent(onPartial),
        endTurn: adaptive() ? endTurn : undefined,
        onError: reportError, onStatus: ifCurrent(setPhase),
        onFinal: ifCurrent((result, timing) => {
          capture = undefined;
          setPhase("");
          onFinal?.(result, timing);
        }),
      });
      if (current !== sequence) next.stop({cancel: true});
      else {
        capture = next;
        setPhase("recording");
      }
    } catch {
      reportError("mic_unavailable");
    }
  }

  function whenHidden() {
    if (document.hidden) cancel();
  }

  button.addEventListener("click", click);
  window.addEventListener("pagehide", cancel);
  document.addEventListener("visibilitychange", whenHidden);
  setPhase("");
  return {
    cancel,
    setDisabled(value) {
      disabled = value;
      updateButton();
    },
    destroy() {
      cancel();
      button.removeEventListener("click", click);
      window.removeEventListener("pagehide", cancel);
      document.removeEventListener("visibilitychange", whenHidden);
    },
  };
}
