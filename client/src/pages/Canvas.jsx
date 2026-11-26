import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { useCopilotObjects, useCopilotRefresh } from "../copilot-hooks.js";
import { Empty } from "../components/ui.jsx";
import { PreviewFrames, useProjectPreviewCanvas } from "../canvas/projectPreview.jsx";
import { canvasContext, elementLabel, isCanvasMessage, modeFromPage, modeMessages, supportedModes } from "../canvas/canvasPanel.js";

const MODE_TEXT = {
  navigate: ["Navegar", "Navigate", "Usa la aplicación como siempre.", "Use the application as usual."],
  select: ["Seleccionar", "Select", "Pasa el ratón y haz clic. Mayús+clic añade o quita. Esc sale.", "Hover and click. Shift+click adds or removes. Esc leaves."],
  comment: ["Comentar", "Comment", "Haz clic en un elemento y escribe la nota. Esc sale.", "Click an element and write the note. Esc leaves."],
  handles: ["Tiradores", "Handles", "Arrastra los tiradores para cambiar tamaño, margen o relleno.", "Drag the handles to change size, margin or padding."],
};
const POLL_MS = 2500;

/**
 * Canvas: one application preview across the screen, the mode toolbar and a side panel with the person's selection and
 * comments. It shares the preview, its live refresh and the agent bridge with Applications (`useProjectPreviewCanvas`),
 * and tells the Dock host what is selected through `HoardApp.setContext`, so Faustus sees it in the turn.
 */
export default function Canvas({ param }) {
  const { lang, notify } = useApp();
  const es = lang === "es";
  const [projects, setProjects] = useState([]);
  const [project, setProject] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState("");
  const [modes, setModes] = useState(["navigate"]);
  const [mode, setMode] = useState("navigate");
  const [selection, setSelection] = useState([]);
  const [comments, setComments] = useState([]);
  const [draft, setDraft] = useState(null);
  const [note, setNote] = useState("");
  const currentId = useRef(param);
  currentId.current = param;
  const held = useRef({ mode, selection });
  held.current = { mode, selection };

  const loadProject = async (id) => {
    try {
      const data = await api.appProject(id);
      if (currentId.current !== id) return;
      setProject(data);
      setPreview((current) => current?.state === "running" && data.preview.state === "running" ? current : data.preview);
    } catch (error) { notify(error.message); }
  };
  const syncRevision = async () => { if (currentId.current) loadProject(currentId.current); };
  const { frameRef, attachFrame, frames, visible } = useProjectPreviewCanvas({
    projectId: project?.id === param ? param : null, preview, baseline: project?.revision, lang, onRevision: syncRevision,
    onError: () => notify(es ? "No se pudo actualizar la vista previa. Se mantiene la página anterior." : "The preview could not update. The previous page is still visible."),
  });
  const running = visible?.state === "running";

  useEffect(() => { api.appProjects().then((data) => setProjects(data.projects)).catch((error) => notify(error.message)); }, []);
  useEffect(() => {
    setProject(null); setPreview(null); setSelection([]); setComments([]); setDraft(null); setModes(["navigate"]); setMode("navigate");
    if (param) loadProject(param);
  }, [param]);
  useCopilotRefresh(() => { if (param) loadProject(param); });
  useCopilotObjects(project ? [{ kind: "app_project", id: project.id }] : []);

  const originOf = (frame) => { try { return new URL(frame.src, window.location.href).origin; } catch { return null; } };
  const send = (message) => {
    const frame = frameRef.current;
    const target = frame && originOf(frame);
    if (frame?.contentWindow && target) frame.contentWindow.postMessage({ hoardDock: 1, ...message }, target);
  };

  // The inspector inside the preview says which modes it supports and what the person picks.
  useEffect(() => {
    if (!running) return undefined;
    const onMessage = (event) => {
      const frame = frameRef.current;
      if (!isCanvasMessage(event, frame?.contentWindow, frame && originOf(frame))) return;
      const data = event.data;
      if (data.type === "dock/inspector-ready") {
        setModes(supportedModes(data));
        // A reloaded page forgets its mode: give back the one this screen holds.
        if (held.current.mode !== "navigate" && modeFromPage(data) !== held.current.mode) modeMessages(held.current.mode, "navigate").forEach(send);
        if (Array.isArray(data.selection) && data.selection.length) setSelection(data.selection);
        else if (held.current.selection.length) send({ type: "inspect/restore", selectors: held.current.selection.map((item) => item.selector).filter(Boolean) });
        return;
      }
      if (data.type === "dock/select") { setMode(modeFromPage(data)); if (Array.isArray(data.selection)) setSelection(data.selection); }
      if (data.type === "dock/comment-target" && data.element) { setDraft({ element: data.element, page: data.page || "/" }); setNote(""); }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [running, visible?.url]);

  // Comments are stored by the server when this build has them; the list is polled so the agent's steps show up.
  const canComment = typeof api.appProjectComments === "function";
  const loadComments = () => canComment && project && api.appProjectComments(project.id).then((data) => setComments(data.comments || [])).catch(() => {});
  useEffect(() => {
    if (!running || !project || !canComment) return undefined;
    loadComments();
    const timer = setInterval(() => { if (!document.hidden) loadComments(); }, POLL_MS);
    return () => clearInterval(timer);
  }, [running, project?.id]);

  // What the Dock host (Faustus) and the copilot see of this screen.
  useEffect(() => {
    const context = canvasContext({ project, revision: visible?.revision, mode, selection, comments });
    window.HoardApp?.setContext?.(context);
  }, [project?.id, project?.name, visible?.revision, mode, selection, comments]);
  useEffect(() => () => window.HoardApp?.setContext?.({}), []);

  const choose = (next) => {
    if (next === mode) next = "navigate";
    modeMessages(next, mode).forEach(send);
    setMode(next);
  };
  useEffect(() => {
    const onKey = (event) => { if (event.key === "Escape" && held.current.mode !== "navigate") choose("navigate"); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const run = async (operation) => {
    const id = project.id; setBusy(operation);
    try { const result = await api.appProjectPreview(id, { operation, revision: project.revision }); if (currentId.current === id) setPreview(result); }
    catch (error) { notify(error.message); }
    finally { setBusy(""); }
  };
  const clearSelection = () => { send({ type: "inspect/clear" }); setSelection([]); };
  const saveComment = () => {
    if (!draft || !note.trim() || typeof api.appProjectCommentAdd !== "function") return;
    api.appProjectCommentAdd(project.id, { note: note.trim(), revision: visible?.revision, page: draft.page, element: draft.element })
      .then(() => { setDraft(null); setNote(""); send({ type: "inspect/draft-clear" }); return loadComments(); }).catch((error) => notify(error.message));
  };
  const open = comments.filter((comment) => ["pending", "seen", "answered"].includes(comment.status));

  return <div className="flex flex-col gap-3">
    <div className="flex items-center gap-3 flex-wrap">
      <h1 className="text-[20px] font-semibold">{es ? "Lienzo" : "Canvas"}</h1>
      <label className="label flex-row items-center gap-2">{es ? "Aplicación" : "Application"}
        <select aria-label={es ? "Aplicación" : "Application"} className="field" value={param || ""} onChange={(event) => { window.location.hash = event.target.value ? `#/canvas/${event.target.value}` : "#/canvas"; }}>
          <option value="">{es ? "Elige una aplicación" : "Choose an application"}</option>
          {projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      {project && <>
        {running
          ? <button className="btn" disabled={!!busy} onClick={() => run("stop")}>{es ? "Detener vista previa" : "Stop preview"}</button>
          : <button className="btn btn-primary" disabled={!!busy} onClick={() => run("start")}>{busy === "start" ? (es ? "Abriendo…" : "Opening…") : (es ? "Abrir vista previa" : "Open preview")}</button>}
        <a className="btn" href={`#/projects/${project.id}`}>{es ? "Editar archivos" : "Edit files"}</a>
        {running && <span className="help">{es ? "Versión" : "Revision"} {project.revisions.indexOf(visible.revision) + 1}{visible.revision === project.revision ? (es ? " · actual" : " · current") : ""}</span>}
      </>}
    </div>
    {!param ? <Empty>{projects.length ? (es ? "Elige una aplicación para verla en el lienzo." : "Choose an application to see it on the canvas.") : (es ? "Crea una aplicación en Aplicaciones para empezar." : "Create an application in Applications to begin.")}</Empty>
      : !project ? <p className="help" role="status">{es ? "Cargando…" : "Loading…"}</p>
      : !running ? <Empty>{es ? "Abre la vista previa para trabajar sobre la aplicación." : "Open the preview to work on the application."}</Empty>
      : <>
        <div role="toolbar" aria-label={es ? "Modo del lienzo" : "Canvas mode"} className="flex gap-2 items-center flex-wrap">
          {modes.map((item) => <button key={item} type="button" className={`btn ${mode === item ? "btn-active" : ""}`} aria-pressed={mode === item} onClick={() => choose(item)}>{es ? MODE_TEXT[item][0] : MODE_TEXT[item][1]}</button>)}
          <span className="help" role="status">{modes.length === 1 ? (es ? "Esta vista previa solo admite navegar." : "This preview only supports navigating.") : es ? MODE_TEXT[mode][2] : MODE_TEXT[mode][3]}</span>
        </div>
        <div className="grid xl:grid-cols-[minmax(0,1fr)_300px] gap-3 items-start">
          <PreviewFrames frames={frames} frameRef={attachFrame} title={es ? "Vista previa de aplicación" : "Application preview"} height="max(480px, calc(100dvh - 190px))" />
          <aside className="panel flex flex-col gap-4" aria-label={es ? "Selección y comentarios" : "Selection and comments"}>
            <section>
              <div className="flex items-center gap-2"><h2 className="font-semibold">{es ? "Selección" : "Selection"} ({selection.length})</h2>
                {selection.length > 0 && <button type="button" className="btn btn-sm ml-auto" onClick={clearSelection}>{es ? "Quitar todo" : "Clear all"}</button>}</div>
              {selection.length ? <ul className="flex flex-col gap-2 mt-2">{selection.map((item, index) => <li key={(item.selector || "") + index} className="chip chip-wrap chip-accent">
                <span><strong>{index + 1}. {elementLabel(item)}</strong>{item.vsrc && <><br /><span>{item.vsrc}</span></>}{item.vgen && <><br /><span>{es ? `generado por {{${item.vgen}}}` : `generated by {{${item.vgen}}}`}</span></>}{item.same_vsrc_count > 1 && <><br /><span>{es ? `afecta a ${item.same_vsrc_count} elementos` : `affects ${item.same_vsrc_count} elements`}</span></>}</span>
              </li>)}</ul> : <p className="help mt-2">{es ? "Lo que selecciones lo ve el agente en su turno." : "The agent sees what you select in its turn."}</p>}
            </section>
            {(canComment || modes.includes("comment")) && <section>
              <h2 className="font-semibold">{es ? "Comentarios abiertos" : "Open comments"} ({open.length})</h2>
              {draft && <form className="flex flex-col gap-2 mt-2" onSubmit={(event) => { event.preventDefault(); saveComment(); }}>
                <strong>{es ? "Comentario sobre " : "Comment on "}{elementLabel(draft.element)}</strong>
                <label className="label">{es ? "Nota para el agente" : "Note for the agent"}<textarea className="field" rows={3} autoFocus value={note} onChange={(event) => setNote(event.target.value)} /></label>
                <div className="flex gap-2"><button type="submit" className="btn btn-primary" disabled={!note.trim()}>{es ? "Guardar comentario" : "Save comment"}</button><button type="button" className="btn" onClick={() => { setDraft(null); send({ type: "inspect/draft-clear" }); }}>{es ? "Cancelar" : "Cancel"}</button></div>
              </form>}
              {open.length ? <ul className="flex flex-col gap-2 mt-2">{open.map((comment) => <li key={comment.id}>
                <button type="button" className="text-left w-full" onClick={() => send({ type: "inspect/pin-focus", id: comment.id })}><strong>#{comment.n}</strong> {comment.note}</button>
              </li>)}</ul> : !draft && <p className="help mt-2">{es ? "Sin comentarios abiertos." : "No open comments."}</p>}
            </section>}
          </aside>
        </div>
      </>}
  </div>;
}
