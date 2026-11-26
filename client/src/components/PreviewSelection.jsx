import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useCopilotForm } from "../copilot-hooks.js";
import { affectsText, chipText, copilotSelection, isInspectorMessage, selectorsOf, sourceText } from "../preview-selection.js";

/**
 * "Select" mode for the application preview. The inspector script inside the preview reports the elements the person
 * picked; this bar shows them as chips, lets the person remove one, and stores the list so an agent can read it
 * (`app_project_selection`) and the copilot sees it in the turn context. The frame is found through `frameRef`.
 */
export default function PreviewSelection({ project, preview, frameRef, es, notify }) {
  const [mode, setMode] = useState(false);
  const [items, setItems] = useState([]);
  const [connected, setConnected] = useState(false);
  const state = useRef({ mode, items });
  state.current = { mode, items };
  const origin = useRef(null);
  const page = useRef(null); // the page path the selection was made on: a selection belongs to one page
  const projectId = project?.id;
  const running = preview?.state === "running" && Boolean(preview?.url);

  const send = (type, fields = {}) => {
    const frame = frameRef.current;
    if (frame?.contentWindow && origin.current) frame.contentWindow.postMessage({ hoardDock: 1, type, ...fields }, origin.current);
  };
  const revision = useRef(preview?.revision);
  revision.current = preview?.revision;
  const store = (list) => {
    if (!projectId) return;
    api.appProjectSelectionSet(projectId, { selection: list, revision: revision.current }).catch((error) => notify(error.message));
  };

  // A new project or a stopped preview starts clean. A reload of the same preview (a new address) keeps the selection.
  useEffect(() => {
    setMode(false); setItems([]); setConnected(false);
    return () => { if (projectId) api.appProjectSelectionSet(projectId, { selection: [] }).catch(() => {}); };
  }, [running, projectId]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!running || !frame) { origin.current = null; return undefined; }
    try { origin.current = new URL(frame.src, window.location.href).origin; } catch { origin.current = null; return undefined; }
    const hello = () => send("inspect/hello");
    const onMessage = (event) => {
      if (!isInspectorMessage(event, frame.contentWindow, origin.current)) return;
      setConnected(true);
      const { selection, mode: pageMode } = event.data;
      if (event.data.type === "dock/inspector-ready") {
        // A reloaded page forgets: give it back the selection and the mode this page still holds.
        const held = state.current;
        const samePage = page.current === null || page.current === event.data.page;
        page.current = event.data.page ?? null;
        if (!samePage && held.items.length) { setItems([]); store([]); }
        else if (!selection.length && held.items.length) send("inspect/restore", { selectors: selectorsOf(held.items) });
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
  }, [running, preview?.url, projectId]);

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
  useCopilotForm("app-preview-selection", { objectId: projectId, initial: { selection: [] }, current: { selection: copilotSelection(items) } });

  if (!running) return null;
  return <div className="panel flex flex-col gap-3" aria-label={es ? "Selección en la vista previa" : "Preview selection"}>
    <div className="flex gap-2 items-center flex-wrap">
      <button type="button" className={`btn ${mode ? "btn-active" : ""}`} aria-pressed={mode} aria-keyshortcuts="Alt+Shift+S" onClick={toggle} disabled={!connected} title="Alt+Shift+S">{mode ? (es ? "Salir de seleccionar" : "Stop selecting") : (es ? "Seleccionar" : "Select")}</button>
      {items.length > 0 && <button type="button" className="btn" onClick={() => { send("inspect/clear"); setItems([]); store([]); }}>{es ? "Quitar todo" : "Clear all"}</button>}
      <span className="help" role="status">{!connected ? (es ? "Esta vista previa no admite selección todavía." : "This preview does not support selection yet.") : mode ? (es ? "Pasa el ratón y haz clic. Mayús+clic añade o quita. Esc sale." : "Hover and click. Shift+click adds or removes. Esc leaves.") : items.length ? (es ? `${items.length} seleccionados: el agente los ve en su turno.` : `${items.length} selected: the agent sees them in its turn.`) : (es ? "Selecciona elementos para pedir un cambio sobre ellos." : "Select elements to ask for a change on them.")}</span>
    </div>
    {items.length > 0 && <ul className="flex flex-wrap gap-2" aria-label={es ? "Elementos seleccionados" : "Selected elements"}>{items.map((item, index) => <li key={item.selector + index} className="chip chip-wrap chip-accent" style={{ alignItems: "flex-start" }}>
      <span><strong>{chipText(item, index)}</strong>{sourceText(item, es) && <><br /><span>{sourceText(item, es)}</span></>}{affectsText(item, es) && <><br /><span>{affectsText(item, es)}</span></>}</span>
      <button type="button" className="px-2 text-[16px] leading-none" aria-label={`${es ? "Quitar" : "Remove"} ${chipText(item, index)}`} onClick={() => { send("inspect/remove", { index }); const next = items.filter((_, at) => at !== index); setItems(next); store(next); }}>×</button>
    </li>)}</ul>}
  </div>;
}
