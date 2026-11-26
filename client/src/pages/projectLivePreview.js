import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

export function refreshKind(change, visible, next) {
  if (change.reset || change.previous_revision !== visible || change.revision !== next ||
      !change.files.length || change.global_styles?.length) return "full";
  if (change.files.every((file) => /\.css$/i.test(file))) return "css";
  if (change.files.every((file) => /^pages\/.+\.html$/i.test(file))) return "html";
  return "full";
}

export function previewNavigationUrl(previewUrl, route) {
  const base = new URL(previewUrl, window.location.href);
  if (route?.startsWith("/") && !route.startsWith("//")) {
    const target = new URL(route, base);
    if (target.origin === base.origin) return target.href;
  }
  return base.href;
}

function post(frame, url, type, payload) {
  frame?.contentWindow?.postMessage({ hoardDock: 1, type, ...payload }, new URL(url).origin);
}

let requestSequence = 0;
function frameRequest(frame, url, type, payload, signal, timeout = 700) {
  const source = frame?.contentWindow;
  if (!source || signal.aborted) return Promise.resolve(null);
  const origin = new URL(url).origin;
  const request = ++requestSequence;
  return new Promise((resolve) => {
    const finish = (value) => {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      window.removeEventListener("message", receive);
      resolve(value);
    };
    const abort = () => finish(null);
    const receive = ({ source: sender, origin: from, data }) => {
      if (sender === source && from === origin && data?.hoardDock === 1 &&
          data.type === type + "/result" && data.request === request) finish(data.result);
    };
    const timer = setTimeout(abort, timeout);
    signal.addEventListener("abort", abort, { once: true });
    window.addEventListener("message", receive);
    post(frame, url, type, { ...payload, request });
  });
}

function loadFrame(present, active, next, signal) {
  return new Promise((resolve) => {
    const finish = (frame) => {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      resolve(frame);
    };
    const abort = () => finish(null);
    const timer = setTimeout(abort, 12000);
    signal.addEventListener("abort", abort, { once: true });
    present([active, { ...next, pending: true, onLoad: (event) => finish(event.currentTarget) }]);
  });
}

export function useProjectLivePreview(id, initialPreview, baseline, activeFrame, onRevision, onError) {
  const [frames, setFrames] = useState([]);
  const callback = useRef({ onRevision, onError });
  callback.current = { onRevision, onError };
  const initialBaseline = useRef(baseline);
  initialBaseline.current = baseline;

  useEffect(() => {
    if (!id || initialPreview?.state !== "running") {
      setFrames([]);
      return;
    }
    const controller = new AbortController();
    const { signal } = controller;
    let visible = { ...initialPreview, key: 0, src: previewNavigationUrl(initialPreview.url) };
    let frameKey = 0;
    let processing = false;
    let pending = null;
    setFrames([visible]);

    const endpoint = new URL("/design/api/app-projects/" + encodeURIComponent(id) + "/events", window.location.origin);
    endpoint.searchParams.set("revision", initialBaseline.current || initialPreview.revision);
    const stream = new EventSource(endpoint);

    const refresh = async (change) => {
      if (change.revision === visible.revision) return;
      const frame = activeFrame.current;
      const state = await frameRequest(frame, visible.src, "canvas/state", {}, signal);
      if (signal.aborted) return;
      // The server may already have a newer saved revision when several edits arrive together.
      const next = await api.appProjectPreview(id, { operation: "start" });
      if (signal.aborted || next.revision === visible.revision) return;
      const mode = refreshKind(change, visible.revision, next.revision);
      const detail = next.revision === change.revision ? change : { files: [] };
      const origin = new URL(visible.src).origin;
      const src = previewNavigationUrl(next.url, state?.route);
      const patch = mode !== "full" && state && new URL(src).origin === origin
        ? await frameRequest(frame, src, "canvas/refresh", { mode, change }, signal, 5000)
        : null;
      if (signal.aborted) return;
      if (patch?.applied) {
        visible = { ...visible, ...next };
        setFrames([visible]);
        post(frame, src, "canvas/changed", { ...detail, ...patch.targets });
      } else {
        // Keep the previous document visible until the replacement has loaded and restored its scroll.
        const prepare = async (url, scroll) => {
          const candidate = { ...next, key: ++frameKey, src: url };
          const frame = await loadFrame(setFrames, visible, candidate, signal);
          if (!frame || signal.aborted) return null;
          if (state) {
            const restored = await frameRequest(frame, url, "canvas/restore", { scroll }, signal);
            if (!restored || (restored.revision && restored.revision !== next.revision)) return null;
          }
          return { candidate, frame };
        };
        let ready = await prepare(src, state?.scroll);
        const entry = previewNavigationUrl(next.url);
        if (!ready && state && src !== entry && !signal.aborted) ready = await prepare(entry);
        if (signal.aborted) return;
        if (!ready) throw new Error("Preview did not finish loading");
        visible = ready.candidate;
        setFrames([visible]);
        post(ready.frame, visible.src, "canvas/changed", detail);
      }
      callback.current.onRevision?.(visible.revision);
    };

    const receive = async (event) => {
      try {
        pending = JSON.parse(event.data);
      } catch {
        return;
      }
      if (processing) return;
      processing = true;
      while (pending && !signal.aborted) {
        const change = pending;
        pending = null;
        try {
          await refresh(change);
        } catch (error) {
          if (!signal.aborted) {
            setFrames([visible]);
            callback.current.onError?.(error);
          }
        }
      }
      processing = false;
    };
    stream.addEventListener("revision", receive);
    return () => {
      controller.abort();
      stream.close();
    };
  }, [id, initialPreview, activeFrame]);

  return frames;
}
