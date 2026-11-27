import { useEffect } from "react";

function previewOrigin(frame) {
  return frame ? new URL(frame.src, window.location.href).origin : null;
}

export function usePreviewEdits(projectId, running, frameRef, lang) {
  useEffect(() => {
    if (!projectId || !running) return undefined;
    let disposed = false;
    const send = (frame, origin, type, payload = {}) => {
      frame?.contentWindow?.postMessage({ hoardDock: 1, type, ...payload }, origin);
    };
    const configure = (frame) => send(frame, previewOrigin(frame), "inspect/edits-config", { lang });
    const receive = async (event) => {
      const frame = frameRef.current;
      const origin = previewOrigin(frame);
      const { data } = event;
      if (!frame || event.source !== frame.contentWindow || event.origin !== origin || data?.hoardDock !== 1) return;
      if (data.type === "dock/inspector-ready") {
        configure(frame);
        return;
      }
      const scale = data.type === "dock/edit-scale";
      const kind = data.type === "dock/commit" ? "style" : data.type === "dock/text" ? "text" : null;
      const args = data.args;
      if (typeof data.request !== "string") return;
      if (scale) {
        if (typeof args?.revision !== "string" || typeof args.path !== "string" ||
            !Number.isFinite(args.root_font_px)) return;
      } else if (!kind || args?.change?.kind !== kind) return;
      const reply = (payload) => {
        if (!disposed && frame === frameRef.current && previewOrigin(frame) === origin) {
          send(frame, origin, "inspect/canvas-edit-result", { request: data.request, ...payload });
        }
      };
      try {
        const endpoint = "/design/api/app-projects/" + encodeURIComponent(projectId) + "/canvas-edit";
        const response = scale
          ? await fetch(endpoint + "/scale?" + new URLSearchParams({
              revision: args.revision, path: args.path, root_font_px: args.root_font_px,
            }))
          : await fetch(endpoint, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ ...args, lang }),
            });
        const result = await response.json();
        if (response.ok) reply({ result });
        else reply({ error: result.error || (lang === "es" ? "No se ha podido editar." : "The edit could not be saved.") });
      } catch {
        reply({ error: lang === "es" ? "No se ha podido conectar con el editor." : "Could not reach the editor." });
      }
    };
    window.addEventListener("message", receive);
    if (frameRef.current) configure(frameRef.current);
    return () => {
      disposed = true;
      window.removeEventListener("message", receive);
    };
  }, [projectId, running, frameRef, lang]);
}
