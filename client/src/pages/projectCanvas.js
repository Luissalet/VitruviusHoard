import { useEffect } from "react";

// Vitruvius hosts a second Dock frame while its own Dock bridge remains a page.
export function useProjectCanvas(frameRef, projectId, previewUrl, revision, locale) {
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !projectId || !previewUrl) return undefined;
    const origin = new URL(previewUrl, window.location.href).origin;
    const route = `/design/api/app-projects/${encodeURIComponent(projectId)}/canvas`;
    const pending = new Set();
    let events;
    let session;

    function send(message) {
      frame.contentWindow?.postMessage({ hoardDock: 1, ...message }, origin);
    }

    function close() {
      events?.close();
      events = undefined;
      session = undefined;
      pending.clear();
    }

    function greet() {
      close();
      try {
        if (frame.contentWindow?.location.href === "about:blank") return;
      } catch {
        // The frame has loaded its own preview origin.
      }
      send({ type: "dock/hello", host: "faustus", session: projectId, locale });
    }

    function onMessage(event) {
      const message = event.data;
      if (event.source !== frame.contentWindow || event.origin !== origin || message?.hoardDock !== 1) return;
      if (message.type === "dock/ready" && !events) {
        const query = revision ? "?revision=" + encodeURIComponent(revision) : "";
        events = new EventSource(route + "/events" + query);
        events.addEventListener("ready", (event) => {
          pending.clear();
          session = JSON.parse(event.data);
        });
        events.addEventListener("call", (event) => {
          if (!session) return;
          const call = JSON.parse(event.data);
          if (call.id) pending.add(call.id);
          send(call);
        });
        events.onerror = () => { session = undefined; pending.clear(); };
      }
      if (message.type === "dock/result" && session && pending.delete(message.id)) {
        void fetch(route + "/result", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session, id: message.id, ok: message.ok,
            result: message.result, error: message.error }),
        }).catch(() => {});
      }
    }

    window.addEventListener("message", onMessage);
    window.addEventListener("pagehide", close);
    window.addEventListener("pageshow", greet);
    frame.addEventListener("load", greet);
    greet();
    return () => {
      frame.removeEventListener("load", greet);
      window.removeEventListener("pageshow", greet);
      window.removeEventListener("pagehide", close);
      window.removeEventListener("message", onMessage);
      close();
    };
  }, [frameRef, projectId, previewUrl, revision, locale]);
}
