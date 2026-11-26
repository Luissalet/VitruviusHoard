import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useCopilotForm } from "../copilot-hooks.js";
import { affectsText, chipText, copilotSelection, identitiesOf, isInspectorMessage, sourceText } from "../preview-selection.js";

/**
 * "Select" mode for the application preview. The inspector script inside the preview reports the elements the person
 * picked; this bar shows them as chips, lets the person remove one, and stores the list so an agent can read it
 * (`app_project_selection`) and the copilot sees it in the turn context. The frame is found through `frameRef`.
 */
export default function PreviewSelection({ project, preview, frameRef, frameKey, es, notify }) {
  const [mode, setMode] = useState(false);
  const [items, setItems] = useState([]);
  const [connected, setConnected] = useState(false);
  const state = useRef({ mode, items });
  state.current = { mode, items };
  const page = useRef(null); // the page path the selection was made on: a selection belongs to one page
  const projectId = project?.id;
  const running = preview?.state === "running" && Boolean(preview?.url);

  // The frame is read on every use: a live refresh may swap the iframe element or its address under this component.
  const originOf = (frame) => { try { return new URL(frame.src, window.location.href).origin; } catch { return null; } };
  const send = (type, fields = {}) => {
    const frame = frameRef.current;
    const target = frame && originOf(frame);
    if (frame?.contentWindow && target) frame.contentWindow.postMessage({ hoardDock: 1, type, ...fields }, target);
  };
  // The revision the page itself says it was served (meta vitruvius-preview-revision), never the one this page believes.
  const served = useRef(null);
  const store = (list) => {
    if (!projectId) return;
    api.appProjectSelectionSet(projectId, { selection: list, revision: served.current || undefined })
      .catch((error) => { if (error.status !== 409) notify(error.message); }); // 409: the page settled on another revision and will report again
  };

  // A new project or a stopped preview starts clean. A reload of the same preview (a new address) keeps the selection.
  useEffect(() => {
    setMode(false); setItems([]); setConnected(false);
    return () => { if (projectId) api.appProjectSelectionSet(projectId, { selection: [] }).catch(() => {}); };
  }, [running, projectId]);

  // `frameKey` names the visible frame: when a live refresh swaps in a new iframe (even at the same address), the page
  // inside it knows nothing of this selection, and the greeting its script sent while it was hidden was ignored.
  const lastFrame = useRef(frameKey);
  useEffect(() => {
    const frame = frameRef.current;
    if (!running || !frame) return undefined;
    const hello = () => send("inspect/hello");
    if (lastFrame.current !== frameKey) { lastFrame.current = frameKey; hello(); } // the new frame has already loaded: greet it now
    const onMessage = (event) => {
      const current = frameRef.current;
      if (!isInspectorMessage(event, current?.contentWindow, current && originOf(current))) return;
      setConnected(true);
      const { selection, mode: pageMode } = event.data;
      served.current = event.data.revision ?? null;
      if (event.data.type === "dock/inspector-ready") {
        // A reloaded page forgets: give it back the selection and the mode this page still holds.
        const held = state.current;
        const samePage = page.current === null || page.current === event.data.page;
        page.current = event.data.page ?? null;
        if (!samePage && held.items.length) { setItems([]); store([]); }
        else if (!selection.length && held.items.length) send("inspect/restore", { items: identitiesOf(held.items) });
        if (held.mode && !pageMode) send("inspect/mode", { on: true });
        if (selection.length && samePage) { setItems(selection); store(selection); }
        return;
      }
      page.current = event.data.page ?? page.current;
      setMode(Boolean(pageMode)); setItems(selection); store(selection);
    };
    window.addEventListener("message", onMessage);
    frame.addEventListener("load", hello); // before it loads, the frame is still the empty document of this page: nothing to greet
    return () => { window.removeEventListener("message", onMessage); frame.removeEventListener("load", hello); };
  }, [running, preview?.url, projectId, frameKey]);

  const toggle = () => { const next = !state.current.mode; setMode(next); send("inspect/mode", { on: next }); };
  useEffect(() => {
    if (!running) return undefined;
    const onKey = (event) => {
      if (event.altKey && event.shiftKey && event.code === "KeyS") { event.preventDefault(); toggle(); }
      else if (event.key === "Escape" && state.current.mode) toggle(); // Esc leaves the mode from this page too, not only from inside the frame
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [running]);
  useCopilotForm("app-preview-selection", { objectId: projectId, initial: { selection: [] }, current: { revision: items.length ? served.current || undefined : undefined, selection: copilotSelection(items) } });

  if (!running) return null;
  return <div className="panel flex flex-col gap-3" aria-label={es ? "Selección en la vista previa" : "Preview selection"}>
    <div className="flex gap-2 items-center flex-wrap">
      <button type="button" className={`btn ${mode ? "btn-active" : ""}`} aria-pressed={mode} aria-keyshortcuts="Alt+Shift+S" onClick={toggle} disabled={!connected} title="Alt+Shift+S">{mode ? (es ? "Salir de seleccionar" : "Stop selecting") : (es ? "Seleccionar" : "Select")}</button>
      {items.length > 0 && <button type="button" className="btn" onClick={() => { send("inspect/clear"); setItems([]); store([]); }}>{es ? "Quitar todo" : "Clear all"}</button>}
      <span className="help" role="status">{!connected ? (es ? "Esta vista previa no admite selección todavía." : "This preview does not support selection yet.") : mode ? (es ? "Haz clic para seleccionar. Mayús+clic añade o quita. Arrastra un tirador o enfócalo con Alt+Intro. Doble clic edita texto. Esc sale." : "Click to select. Shift+click adds or removes. Drag a handle or focus it with Alt+Enter. Double-click to edit text. Esc leaves.") : items.length ? (es ? `${items.filter((item) => !item.expired).length} seleccionados: el agente los ve en su turno.` : `${items.filter((item) => !item.expired).length} selected: the agent sees them in its turn.`) : (es ? "Selecciona elementos para pedir un cambio sobre ellos." : "Select elements to ask for a change on them.")}</span>
    </div>
    {items.length > 0 && <ul className="flex flex-wrap gap-2" aria-label={es ? "Elementos seleccionados" : "Selected elements"}>{items.map((item, index) => <li key={item.selector + index} className={`chip chip-wrap ${item.expired ? "chip-amber" : "chip-accent"}`} style={{ alignItems: "flex-start" }}>
      <span><strong style={item.expired ? { textDecoration: "line-through" } : undefined}>{chipText(item, index)}</strong>{item.expired && <><br /><span>{es ? "caducada: la versión actual ya no tiene este elemento" : "expired: the current revision no longer has this element"}</span></>}{sourceText(item, es) && <><br /><span>{sourceText(item, es)}</span></>}{affectsText(item, es) && <><br /><span>{affectsText(item, es)}</span></>}</span>
      <button type="button" className="px-2 text-[16px] leading-none" aria-label={`${es ? "Quitar" : "Remove"} ${chipText(item, index)}`} onClick={() => { send(item.expired ? "inspect/dismiss" : "inspect/remove", { index: items.slice(0, index).filter((other) => Boolean(other.expired) === Boolean(item.expired)).length }); const next = items.filter((_, at) => at !== index); setItems(next); store(next); }}>×</button>
    </li>)}</ul>}
  </div>;
}
