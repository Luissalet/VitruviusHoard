/** Local microphone capture for the shared dictation service. */
const MIME = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
const FIRST_PROBE_MS = 110;
const ADAPTIVE_PROBE_MS = 150;
const ADAPTIVE_RETRY_MS = 250;
const ADAPTIVE_LONG_MS = 1650;

export async function recordDictation({
  request, onPartial = () => {}, onStatus = () => {}, onFinal = () => {}, onError = () => {},
  silenceMs = 1500, maxDurationMs = 20000, finalTimeoutMs = 15000, partials = true, endTurn, permissionSignal,
}) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {echoCancellation: true, noiseSuppression: true},
  });
  if (permissionSignal?.aborted) {
    stream.getTracks().forEach(track => track.stop());
    permissionSignal.throwIfAborted();
  }
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
  let hasProbed = false;
  let probeAttempts = 0;
  let retryProbeAt;
  let pendingSnapshot;
  let speechEpoch = 0;
  let speaking = false;
  let timer;
  let stopped = false;
  let speechEnd;
  let captureStoppedAt;
  let stopReason;
  let audibleFrames = 0;
  const sampleMs = endTurn ? 25 : 50;
  const started = performance.now();

  function stop({cancel = false, reason = "manual"} = {}) {
    if (cancel) final.abort();
    if (stopped) return;
    if (!cancel && (reason === "manual" || reason === "silence") && !speaking
        && proposal?.silenceMs >= 500 && proposal.silenceMs <= 700 && proposal.result?.text?.trim()
        && (reason === "silence" || !voicePresent())) {
      accepted = proposal.result;
    }
    stopped = true;
    partial?.abort();
    probing?.abort();
    captureStoppedAt = performance.now();
    speechEnd ??= captureStoppedAt;
    stopReason = accepted && reason === "silence" ? "adaptive" : reason;
    clearInterval(timer);
    if (capture.state !== "inactive") capture.stop();
    stream.getTracks().forEach(track => track.stop());
    void audio.close().catch(() => {});
    if (!cancel) onStatus("transcribing");
  }

  function rearmProbe(epoch) {
    if (!stopped && epoch === speechEpoch && probeAttempts === 1) {
      retryProbeAt = performance.now() + ADAPTIVE_RETRY_MS;
    }
  }

  async function probe(blob, controller, epoch, observedSpeechEnd) {
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(1600)]);
    try {
      const result = await request(blob, {partial: true, adaptive: true, signal});
      signal.throwIfAborted();
      if (epoch !== speechEpoch || !result?.text) return;
      onPartial(result);
      const candidate = await endTurn(result, {signal});
      if (signal.aborted || !candidate || epoch !== speechEpoch || observedSpeechEnd !== speechEnd) return;
      proposal = candidate;
      // Recheck the microphone before cutting. Speech may have resumed between interval ticks.
      if (candidate.silenceMs <= 700 && performance.now() - observedSpeechEnd >= candidate.silenceMs) sampleVoice();
    } catch {
      rearmProbe(epoch);
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
        void probe(new Blob(chunks, {type: capture.mimeType}), probing, epoch, speechEnd);
      } else if (!speaking) {
        rearmProbe(epoch);
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
        speechEnd, captureStoppedAt, stopReason, reusedProvisional: Boolean(accepted),
        transcriptAt: result.transcribedAt ?? performance.now(),
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
  function voicePresent() {
    analyser.getFloatTimeDomainData(samples);
    const energy = Math.sqrt(samples.reduce((sum, sample) => sum + sample * sample, 0) / samples.length);
    return energy >= .018;
  }

  function sampleVoice() {
    if (stopped) return;
    const now = performance.now();
    const wasSpeaking = speaking;
    speaking = voicePresent();
    if (speaking) {
      audibleFrames += 1;
      if (audibleFrames >= 4) speechEnd = now;
      if (endTurn && !wasSpeaking) {
        speechEpoch++;
        probing?.abort();
        probing = undefined;
        probeAttempts = 0;
        retryProbeAt = undefined;
        proposal = undefined;
      }
    } else if (!speechEnd) audibleFrames = 0;
    const pause = speechEnd ? now - speechEnd : 0;
    const probePause = hasProbed ? ADAPTIVE_PROBE_MS : FIRST_PROBE_MS;
    const canProbe = probeAttempts === 0 || (probeAttempts === 1 && now >= retryProbeAt);
    if (endTurn && !speaking && pause >= probePause && canProbe && pendingSnapshot === undefined) {
      hasProbed = true;
      probeAttempts++;
      try {
        pendingSnapshot = speechEpoch;
        capture.requestData();
      } catch {
        pendingSnapshot = undefined;
        rearmProbe(speechEpoch);
      }
    }
    const cutoff = proposal?.silenceMs ?? (endTurn ? ADAPTIVE_LONG_MS : silenceMs);
    if (!speaking && pause >= cutoff) stop({reason: "silence"});
    else if (now - started >= maxDurationMs) stop({reason: "limit"});
  }
  timer = setInterval(sampleVoice, sampleMs);
  return {stop};
}

export const MICROPHONE_TEXT = {
  es: {
    start: "Hablar", finish: "Terminar", cancel: "Cancelar solicitud",
    connecting: "Comprobando la conexión con el servicio de voz…",
    busy: "Espera a que termine la instrucción anterior para volver a hablar.",
    unavailable: "El micrófono no está disponible en esta vista. Puedes escribir.",
    waiting: "Esperando permiso del micrófono… Elige Permitir en el aviso del navegador.",
    denied: "El navegador ha denegado el acceso al micrófono. Abre los permisos del sitio junto a la dirección, permite el micrófono y vuelve a pulsar Hablar. También puedes escribir.",
  },
  en: {
    start: "Speak", finish: "Finish", cancel: "Cancel request",
    connecting: "Checking the connection to the voice service…",
    busy: "Wait for the previous instruction to finish before speaking again.",
    unavailable: "The microphone is unavailable in this view. You can type.",
    waiting: "Waiting for microphone permission… Choose Allow in the browser prompt.",
    denied: "The browser denied microphone access. Open the site permissions next to the address, allow the microphone and select Speak again. You can also type.",
  },
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
  const copy = {...MICROPHONE_TEXT[language.startsWith("en") ? "en" : "es"], ...labels};
  let sequence = 0;
  let capture;
  let permission;
  let phase = "";
  let disabled = Boolean(button.disabled);
  const unavailable = typeof navigator.mediaDevices?.getUserMedia !== "function";
  const cancellable = () => phase === "connecting" || phase === "getting_mic";
  const status = () => phase || (unavailable ? "unavailable" : disabled ? "busy" : "");

  function updateButton() {
    button.textContent = cancellable() ? copy.cancel : phase === "recording" ? copy.finish : copy.start;
    button.setAttribute("aria-pressed", String(phase === "recording"));
    button.disabled = !cancellable() && (disabled || unavailable || phase === "transcribing");
  }

  function setPhase(next) {
    phase = next;
    updateButton();
    onStatus(status());
  }

  function cancel() {
    sequence++;
    permission?.abort();
    permission = undefined;
    capture?.stop({cancel: true});
    capture = undefined;
    if (phase) setPhase("");
  }

  async function click() {
    if (cancellable()) {
      cancel();
      return;
    }
    if (phase === "recording") {
      capture?.stop();
      return;
    }
    if (status()) return;
    const current = ++sequence;
    const attempt = new AbortController();
    permission = attempt;
    function ifCurrent(handler) {
      return (...args) => { if (current === sequence) handler?.(...args); };
    }
    const reportError = ifCurrent(code => {
      capture = undefined;
      setPhase("");
      onError(code);
    });
    try {
      const ready = beforeStart();
      if (ready?.then) setPhase("connecting");
      if (!await ready || current !== sequence) {
        if (current === sequence) setPhase("");
        return;
      }
      setPhase("getting_mic");
      const next = await recordDictation({
        request: transcribe, silenceMs, finalTimeoutMs, partials, onPartial: ifCurrent(onPartial),
        endTurn: adaptive() ? endTurn : undefined, permissionSignal: attempt.signal,
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
    } catch (error) {
      reportError(error?.name === "NotAllowedError" ? "mic_permission_denied" : "mic_unavailable");
    } finally {
      if (permission === attempt) permission = undefined;
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
    get phase() { return status(); },
    cancel,
    setDisabled(value) {
      const previous = status();
      disabled = value;
      updateButton();
      if (status() !== previous) onStatus(status());
    },
    destroy() {
      cancel();
      button.removeEventListener("click", click);
      window.removeEventListener("pagehide", cancel);
      document.removeEventListener("visibilitychange", whenHidden);
    },
  };
}
