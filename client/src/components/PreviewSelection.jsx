import React, { useEffect, useRef, useState } from "react";
import { useCopilotForm } from "../copilot-hooks.js";
import { affectsText, chipText, copilotSelection, elementName, identitiesOf, isInspectorMessage, sourceText } from "../preview-selection.js";
import { isCommentMessage } from "../preview-comments.js";
import PreviewComments from "./PreviewComments.jsx";

/**
 * "Select" and "Comment" modes for the application preview. Comment pins a note on an element (see `PreviewComments`,
 * which shares this bar, the frame and the message listener); the copilot turn context carries the selection and the
 * comments waiting for the agent in the same card.
 * The inspector reports the elements the person picks. This bar keeps the chips in this workbench and includes them in
 * the copilot turn context. The read-only agent tool queries the live preview through the canvas relay.
 */
export default function PreviewSelection({ project, preview, frameRef, frameKey, es, notify, canvas = false, selectionActive = true, onComments }) {
  const [mode, setMode] = useState(false);
  const [commentMode, setCommentMode] = useState(false);
  const [ready, setReady] = useState(0); // counts the greetings of the page, so pins are sent again after a reload
  const [waiting, setWaiting] = useState([]); // comments waiting for the agent, as the copilot sees them
  const commentHandler = useRef(null);
  const [items, setItems] = useState([]);
  const [connected, setConnected] = useState(false);
  const state = useRef({ mode, commentMode, items });
  state.current = { mode, commentMode, items };
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
  const previewRevision = useRef(null);
  previewRevision.current = preview?.revision || null;
  // A new workbench, project or preview opening starts clean.
  useEffect(() => {
    page.current = null;
    served.current = null;
    setMode(false); setCommentMode(false); setItems([]); setConnected(false);
  }, [running, projectId]);

  // `frameKey` names the visible frame: when a live refresh swaps in a new iframe (even at the same address), the page
  // inside it knows nothing of this selection, and the greeting its script sent while it was hidden was ignored.
  const lastFrame = useRef(frameKey);
  useEffect(() => {
    const frame = frameRef.current;
    if (!running || !frame) return undefined;
    const hello = () => send("inspect/hello");
    // A swapped-in frame has already loaded: greet it now. The first frame is greeted by its own load event instead.
    if (!canvas && lastFrame.current !== undefined && frameKey !== undefined && lastFrame.current !== frameKey) hello();
    lastFrame.current = frameKey;
    const onMessage = (event) => {
      const current = frameRef.current;
      if (isCommentMessage(event, current?.contentWindow, current && originOf(current))) {
        setConnected(true);
        if (event.data.revision) served.current = event.data.revision;
        commentHandler.current?.(event.data);
        return;
      }
      if (!isInspectorMessage(event, current?.contentWindow, current && originOf(current))) return;
      setConnected(true);
      const { selection, mode: pageMode } = event.data;
      served.current = event.data.revision ?? null;
      setCommentMode(Boolean(event.data.comment_mode));
      commentHandler.current?.(event.data);
      if (event.data.type === "dock/inspector-ready") {
        // A reloaded page forgets: give it back the selection and the mode this page still holds.
        const held = state.current;
        const samePage = page.current === null || page.current === event.data.page;
        page.current = event.data.page ?? null;
        if (!samePage && held.items.length) setItems([]);
        else if (!selection.length && held.items.length) send("inspect/restore", { items: identitiesOf(held.items) });
        if (!canvas) {
          if (held.mode && !pageMode) send("inspect/mode", { on: true });
          else if (held.commentMode && !event.data.comment_mode) send("inspect/mode", { on: true, kind: "comment" });
        }
        setReady((count) => count + 1);
        if (selection.length && samePage) setItems(selection);
        return;
      }
      page.current = event.data.page ?? page.current;
      setMode(Boolean(pageMode)); setItems(selection);
    };
    window.addEventListener("message", onMessage);
    if (!canvas) frame.addEventListener("load", hello); // Canvas owns its greeting and mode changes.
    return () => { window.removeEventListener("message", onMessage); frame.removeEventListener("load", hello); };
  }, [running, preview?.url, projectId, frameKey, canvas]);

  const toggle = () => { const next = !state.current.mode; setMode(next); if (next) setCommentMode(false); send("inspect/mode", { on: next }); };
  const toggleComment = () => { const next = !state.current.commentMode; setCommentMode(next); if (next) setMode(false); send("inspect/mode", { on: next, kind: "comment" }); };
  useEffect(() => {
    if (!running || canvas) return undefined;
    const onKey = (event) => {
      if (event.altKey && event.shiftKey && event.code === "KeyS") { event.preventDefault(); toggle(); }
      else if (event.altKey && event.shiftKey && event.code === "KeyC") { event.preventDefault(); toggleComment(); }
      else if (!event.defaultPrevented && event.key === "Escape" && state.current.mode) toggle(); // Esc leaves the mode from this page too, not only from inside the frame
      else if (!event.defaultPrevented && event.key === "Escape" && state.current.commentMode) toggleComment();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [running, projectId, canvas]);
  const activeItems = selectionActive ? items : [];
  useCopilotForm("app-preview-selection", { objectId: projectId, initial: { selection: [], comments: [] }, current: { revision: activeItems.length ? served.current || undefined : undefined, selection: copilotSelection(activeItems), comments: waiting } });

  if (!running) return null;
  return <div className={canvas ? "min-w-0" : "panel flex flex-col gap-3"} aria-label={es ? "Selección en la vista previa" : "Preview selection"}>
    {(!canvas || activeItems.length > 0) && <div className={canvas ? "canvas-inspector-section" : "contents"}>
    {canvas && <h2 className="canvas-inspector-heading">{es ? "Selección" : "Selection"}</h2>}
    <div className="flex gap-2 items-center flex-wrap">
      {!canvas && <><button type="button" className={`btn ${mode ? "btn-active" : ""}`} aria-pressed={mode} aria-keyshortcuts="Alt+Shift+S" onClick={toggle} disabled={!connected} title="Alt+Shift+S">{mode ? (es ? "Salir de seleccionar" : "Stop selecting") : (es ? "Seleccionar" : "Select")}</button>
      <button type="button" className={`btn ${commentMode ? "btn-active" : ""}`} aria-pressed={commentMode} aria-keyshortcuts="Alt+Shift+C" onClick={toggleComment} disabled={!connected} title="Alt+Shift+C">{commentMode ? (es ? "Salir de comentar" : "Stop commenting") : (es ? "Comentar" : "Comment")}</button></>}
      {items.length > 0 && <button type="button" className="btn" onClick={() => { send("inspect/clear"); setItems([]); if (canvas) document.getElementById("canvas-elements-title")?.focus(); }}>{es ? "Quitar todo" : "Clear all"}</button>}
      {!canvas && <span className="help" role="status">{!connected ? (es ? "Esta vista previa no admite selección todavía." : "This preview does not support selection yet.") : commentMode ? (es ? "Haz clic en un elemento y escribe la nota. Esc sale." : "Click an element and write the note. Esc leaves.") : mode ? (es ? "Haz clic para seleccionar. Mayús+clic añade o quita. Arrastra un tirador o enfócalo con Alt+Intro. Doble clic edita texto. Esc sale." : "Click to select. Shift+click adds or removes. Drag a handle or focus it with Alt+Enter. Double-click to edit text. Esc leaves.") : items.length ? (es ? `${items.filter((item) => !item.expired).length} seleccionados: el agente los ve en su turno.` : `${items.filter((item) => !item.expired).length} selected: the agent sees them in its turn.`) : (es ? "Selecciona elementos para pedir un cambio sobre ellos." : "Select elements to ask for a change on them.")}</span>}
    </div>
    {items.length > 0 && <ul className="flex flex-wrap gap-2" aria-label={es ? "Elementos seleccionados" : "Selected elements"}>
      {items.map((item, index) => {
        const label = chipText(item, es);
        const source = sourceText(item, es);
        const affects = affectsText(item, es);
        const element = elementName(item);
        return <li key={item.selector + index} className={`preview-selection-card chip chip-wrap ${item.expired ? "chip-amber" : "chip-accent"}`}>
          <div className="preview-selection-content">
            <strong style={item.expired ? { textDecoration: "line-through" } : undefined}>{label}</strong>
            {item.expired && <span>{es ? "Caducada. La versión actual ya no tiene este elemento." : "Expired. The current revision no longer contains this element."}</span>}
            {affects && <span>{affects}</span>}
            <details className="preview-selection-details">
              <summary>{es ? "Detalles técnicos" : "Technical details"}</summary>
              <dl>
                {item.selector && <><dt>Selector</dt><dd><code>{item.selector}</code></dd></>}
                {element !== item.selector && <><dt>{es ? "Elemento" : "Element"}</dt><dd><code>{element}</code></dd></>}
                {source && <><dt>{es ? "Origen" : "Source"}</dt><dd><code>{source}</code></dd></>}
                {item.vgen && item.vsrc && <><dt>{es ? "Ruta" : "Path"}</dt><dd><code>{item.vsrc}</code></dd></>}
              </dl>
            </details>
          </div>
          <button type="button" className="px-2 text-[16px] leading-none" aria-label={`${es ? "Quitar" : "Remove"} ${label}`} onClick={() => {
            send(item.expired ? "inspect/dismiss" : "inspect/remove", { index: items.slice(0, index).filter((other) => Boolean(other.expired) === Boolean(item.expired)).length });
            setItems(items.filter((_, at) => at !== index));
          }}>×</button>
        </li>;
      })}
    </ul>}
    </div>}
    <PreviewComments projectId={projectId} running={running} served={served} previewRevision={previewRevision} es={es} notify={notify} send={send} register={commentHandler} ready={ready} onContext={setWaiting} onComments={onComments} canvas={canvas} />
  </div>;
}
