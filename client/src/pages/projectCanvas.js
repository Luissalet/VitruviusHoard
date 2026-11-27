import { useEffect, useRef } from "react";

// Vitruvius hosts a second Dock frame while its own Dock bridge remains a page.
export function useProjectCanvas(frameRef, projectId, previewUrl, revision, locale, onActivity) {
  const report = useRef(onActivity);
  report.current = onActivity;
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !projectId || !previewUrl) return undefined;
    const origin = new URL(previewUrl, window.location.href).origin;
    const route = `/design/api/app-projects/${encodeURIComponent(projectId)}/canvas`;
    const pending = new Map();
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
          const edit = call.type === "canvas/presence";
          const tool = String(call.tool || "").replace(/^app_/, "");
          const action = call.type === "dock/call" && ["click", "fill", "select", "navigate", "scroll", "highlight"].includes(tool);
          const activity = edit || action ? {
            id: call.id, projectId, actor: call.actor, kind: edit ? "edit" : tool, revision: call.revision || revision,
            target: {
              ref: typeof call.args?.ref === "string" ? call.args.ref : undefined,
              ...call.change, ...(call.target || call.presence),
            },
            state: "active",
            expiresAt: edit ? call.expires_at : Date.now() + 47000,
          } : null;
          if (call.id) pending.set(call.id, activity);
          if (activity) report.current?.(activity);
          send(call);
        });
        events.onerror = () => { session = undefined; pending.clear(); };
      }
      if (message.type === "dock/result" && session && pending.has(message.id)) {
        const activity = pending.get(message.id);
        pending.delete(message.id);
        if (activity && activity.kind !== "edit") {
          report.current?.({ ...activity, state: message.ok ? "done" : "failed", expiresAt: null });
        }
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
