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
      const kind = data.type === "dock/commit" ? "style" : data.type === "dock/text" ? "text" : null;
      if (!kind || data.args?.change?.kind !== kind || typeof data.request !== "string") return;
      const reply = (payload) => {
        if (!disposed && frame === frameRef.current && previewOrigin(frame) === origin) {
          send(frame, origin, "inspect/canvas-edit-result", { request: data.request, ...payload });
        }
      };
      try {
        const response = await fetch("/design/api/app-projects/" + encodeURIComponent(projectId) + "/canvas-edit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...data.args, lang }),
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
