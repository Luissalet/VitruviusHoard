import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { useCopilotObjects, useCopilotRefresh } from "../copilot-hooks.js";
import { Empty } from "../components/ui.jsx";
import PreviewSelection from "../components/PreviewSelection.jsx";
import { PreviewFrames, useProjectPreviewCanvas } from "../canvas/projectPreview.jsx";
import { canvasContext, isCanvasMessage, modeFromPage, modeMessages, supportedModes } from "../canvas/canvasPanel.js";

const MODE_TEXT = {
  navigate: ["Navegar", "Navigate", "Usa la aplicación como siempre.", "Use the application as usual."],
  select: ["Seleccionar", "Select", "Pasa el ratón y haz clic. Mayús+clic añade o quita. Esc sale.", "Hover and click. Shift+click adds or removes. Esc leaves."],
  handles: ["Tiradores", "Handles", "Arrastra los tiradores para cambiar tamaño, margen o relleno. Esc sale.", "Drag the handles to change size, margin or padding. Esc leaves."],
};

/**
 * Canvas: one application preview across the screen, the mode toolbar and a side panel with the person's selection.
 * The preview, its live refresh and the agent bridge come from `useProjectPreviewCanvas`, and the selection from
 * `PreviewSelection`, both shared with Applications. This screen only adds the toolbar (modes the inspector announces)
 * and tells the Dock host what is selected through `HoardApp.setContext`, so Faustus sees it in the turn. While it is
 * open, the copilot opens on the left so the preview keeps the right.
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
  const currentId = useRef(param);
  currentId.current = param;
  const held = useRef(mode);
  held.current = mode;

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
  const running = preview?.state === "running" && Boolean(visible);
  const frameKey = frames[0]?.key;

  useEffect(() => { api.appProjects().then((data) => setProjects(data.projects)).catch((error) => notify(error.message)); }, []);
  useEffect(() => {
    setProject(null); setPreview(null);
    if (param) loadProject(param);
  }, [param]);
  useCopilotRefresh(() => { if (param) loadProject(param); });
  useCopilotObjects(project ? [{ kind: "app_project", id: project.id }] : []);

  // The copilot panel takes the left while this screen is open; the preview keeps the right.
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.hoardCopilotPosition = "left";
    return () => { delete root.dataset.hoardCopilotPosition; };
  }, []);

  // A new project, a stopped or reopened preview, or a swapped frame knows nothing yet: only Navigate until the
  // inspector in that frame announces what it supports. The selection itself is kept and restored by PreviewSelection.
  useEffect(() => { setModes(["navigate"]); setMode("navigate"); }, [param, running, visible?.url, frameKey]);
  useEffect(() => { if (!running) setSelection([]); }, [running, param]);

  const originOf = (frame) => { try { return new URL(frame.src, window.location.href).origin; } catch { return null; } };
  const send = (message) => {
    const frame = frameRef.current;
    const target = frame && originOf(frame);
    if (frame?.contentWindow && target) frame.contentWindow.postMessage({ hoardDock: 1, ...message }, target);
  };

  // Read-only: the modes the inspector announces and the selection it reports (PreviewSelection answers it).
  useEffect(() => {
    if (!running) return undefined;
    const onMessage = (event) => {
      const frame = frameRef.current;
      if (!isCanvasMessage(event, frame?.contentWindow, frame && originOf(frame))) return;
      const data = event.data;
      if (data.type === "dock/inspector-ready") {
        setModes(supportedModes(data).filter((item) => item !== "comment"));
        setMode(modeFromPage(data));
        if (Array.isArray(data.selection) && data.selection.length) setSelection(data.selection); // empty: PreviewSelection restores it
        return;
      }
      if (data.type === "dock/select") { setMode(modeFromPage(data)); if (Array.isArray(data.selection)) setSelection(data.selection); }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [running, visible?.url, frameKey]);

  // What the Dock host (Faustus) sees of this screen.
  useEffect(() => {
    window.HoardApp?.setContext?.(canvasContext({ project, revision: visible?.revision, mode, selection }));
  }, [project?.id, project?.name, visible?.revision, mode, selection]);
  useEffect(() => () => window.HoardApp?.setContext?.({}), []);

  const choose = (next) => {
    const current = held.current;
    if (next === current) next = "navigate";
    modeMessages(next, current).forEach(send);
    setMode(next);
  };
  useEffect(() => {
    // Select has its own Esc in PreviewSelection; the handles mode is left from here.
    const onKey = (event) => { if (event.key === "Escape" && held.current === "handles") choose("navigate"); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const run = async (operation) => {
    const id = project.id; setBusy(operation);
    try { const result = await api.appProjectPreview(id, { operation, revision: project.revision }); if (currentId.current === id) setPreview(result); }
    catch (error) { notify(error.message); }
    finally { setBusy(""); }
  };

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
          <section className="min-w-0 flex flex-col gap-3" aria-label={es ? "Selección" : "Selection"}>
            <PreviewSelection project={project} preview={preview} frameRef={frameRef} frameKey={frameKey} es={es} notify={notify} />
          </section>
        </div>
      </>}
  </div>;
}
