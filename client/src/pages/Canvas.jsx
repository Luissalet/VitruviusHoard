import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { useCopilotObjects, useCopilotRefresh } from "../copilot-hooks.js";
import { Empty } from "../components/ui.jsx";
import PreviewSelection from "../components/PreviewSelection.jsx";
import { CanvasElements, CanvasHistory } from "../canvas/CanvasInspector.jsx";
import { CanvasConversation, CanvasTimeline } from "../canvas/CanvasActivity.jsx";
import { conversationEntry, recordCanvasActivity } from "../canvas/canvasConversation.js";
import ProjectCritiqueLoop from "../components/ProjectCritiqueLoop.jsx";
import { PreviewFrames, previewAllow, useProjectPreviewCanvas } from "../canvas/projectPreview.jsx";
import { canvasContext, isCanvasMessage, modeFromPage, modeMessages, supportedModes } from "../canvas/canvasPanel.js";

const MODE_TEXT = {
  navigate: ["Navegar", "Navigate", "Usa la aplicación como siempre.", "Use the application as usual."],
  select: ["Seleccionar", "Select", "Haz clic o elige un elemento en el panel. Mayús+clic añade o quita. Arrastra un tirador o pulsa Alt+Intro. Doble clic edita texto. Esc sale.", "Click or choose an element in the panel. Shift+click adds or removes. Drag a handle or press Alt+Enter. Double-click edits text. Esc leaves."],
  comment: ["Comentar", "Comment", "Haz clic en un elemento y escribe la nota en el panel. Esc sale.", "Click an element and write the note in the panel. Esc leaves."],
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
  const [projectsState, setProjectsState] = useState("loading");
  const [project, setProject] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState("");
  const [modes, setModes] = useState(["navigate"]);
  const [mode, setMode] = useState("navigate");
  const [selection, setSelection] = useState([]);
  const [elements, setElements] = useState(null);
  const [projectError, setProjectError] = useState(false);
  const [comments, setComments] = useState([]);
  const [rail, setRail] = useState("activity");
  const [panelOpen, setPanelOpen] = useState(true);
  const [focusMode, setFocusMode] = useState(false);
  const [liveSteps, setLiveSteps] = useState([]);
  const elementsTimer = useRef(null);
  const projectRequest = useRef(0);
  const currentId = useRef(param);
  currentId.current = param;
  const held = useRef(mode);
  held.current = mode;

  const loadProject = async (id) => {
    const request = ++projectRequest.current;
    try {
      const data = await api.appProject(id);
      if (currentId.current !== id || request !== projectRequest.current) return;
      setProjectError(false);
      setProject(data);
      setPreview((current) => current?.state === "running" && data.preview.state === "running" ? current : data.preview);
    } catch (error) {
      if (currentId.current !== id || request !== projectRequest.current) return;
      setProjectError(true);
      notify(error.message);
    }
  };
  const syncRevision = async () => { if (currentId.current) loadProject(currentId.current); };
  const reportActivity = (step) => {
    if (step && step.projectId === currentId.current) setLiveSteps((steps) => recordCanvasActivity(steps, step));
  };
  const { frameRef, attachFrame, frames, visible } = useProjectPreviewCanvas({
    projectId: project?.id === param ? param : null, preview, baseline: project?.revision, lang, onRevision: syncRevision,
    onActivity: reportActivity,
    onError: () => notify(es ? "No se pudo actualizar la vista previa. Se mantiene la página anterior." : "The preview could not update. The previous page is still visible."),
  });
  const running = preview?.state === "running" && Boolean(visible);
  const frameKey = frames[0]?.key;

  const loadProjects = async () => {
    setProjectsState("loading");
    try {
      const { projects } = await api.appProjects();
      setProjects(projects);
      setProjectsState("ready");
    } catch {
      setProjectsState("error");
    }
  };
  useEffect(() => { void loadProjects(); }, []);
  useEffect(() => {
    setProject(null); setPreview(null); setProjectError(false); setComments([]); setLiveSteps([]);
    if (param) loadProject(param);
    else setFocusMode(false);
  }, [param]);
  useCopilotRefresh(() => { if (param) loadProject(param); });
  useCopilotObjects(project ? [{ kind: "app_project", id: project.id }] : [],
    project ? { external_project_id: project.id, title: project.name } : null);

  useEffect(() => {
    const onConversation = (event) => reportActivity(conversationEntry(event.detail, event.detail?.projectId));
    window.addEventListener("hoard:copilot-conversation", onConversation);
    return () => window.removeEventListener("hoard:copilot-conversation", onConversation);
  }, []);

  useEffect(() => {
    const expiries = liveSteps.map((step) => step.expiresAt).filter(Number.isFinite);
    if (!expiries.length) return undefined;
    const timer = setTimeout(() => setLiveSteps((steps) => steps.filter(
      (step) => !step.expiresAt || step.expiresAt > Date.now(),
    )), Math.max(0, Math.min(...expiries) - Date.now()) + 5);
    return () => clearTimeout(timer);
  }, [liveSteps]);

  useEffect(() => {
    const root = document.documentElement;
    root.toggleAttribute("data-canvas-focus", focusMode);
    return () => root.removeAttribute("data-canvas-focus");
  }, [focusMode]);

  // Floating conversation stays on the left when opened outside the inline rail.
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.hoardCopilotPosition = "left";
    return () => { delete root.dataset.hoardCopilotPosition; };
  }, []);

  // A new project, a stopped or reopened preview, or a swapped frame knows nothing yet: only Navigate until the
  // inspector in that frame announces what it supports. The selection itself is kept and restored by PreviewSelection.
  useEffect(() => { setModes(["navigate"]); setMode("navigate"); }, [param, running, visible?.url, frameKey]);
  useEffect(() => { if (!running) setSelection([]); }, [running, param]);
  useEffect(() => { setSelection([]); }, [param]);

  const originOf = (frame) => { try { return new URL(frame.src, window.location.href).origin; } catch { return null; } };
  const send = (message) => {
    const frame = frameRef.current;
    const target = frame && originOf(frame);
    if (frame?.contentWindow && target) frame.contentWindow.postMessage({ hoardDock: 1, ...message }, target);
  };

  const requestElements = () => {
    clearTimeout(elementsTimer.current);
    send({ type: "inspect/elements" });
    elementsTimer.current = setTimeout(() => setElements((current) => ({ ...current, error: true })), 3500);
  };

  // Read-only: the modes the inspector announces and the selection it reports (PreviewSelection answers it).
  useEffect(() => {
    if (!running) { setElements(null); return undefined; }
    setElements((current) => current?.items ? current : null);
    elementsTimer.current = setTimeout(() => setElements((current) => ({ ...current, error: true })), 3500);
    const onMessage = (event) => {
      const frame = frameRef.current;
      if (!isCanvasMessage(event, frame?.contentWindow, frame && originOf(frame))) return;
      const data = event.data;
      if (data.type === "dock/inspector-ready") {
        setModes(supportedModes(data));
        setMode(modeFromPage(data));
        requestElements();
        if (Array.isArray(data.selection) && data.selection.length) setSelection(data.selection); // empty: PreviewSelection restores it
        return;
      }
      if (data.type === "dock/select") {
        const next = modeFromPage(data);
        if (next === "comment" && held.current !== "comment") { setPanelOpen(true); setRail("activity"); }
        setMode(next);
        if (Array.isArray(data.selection)) setSelection(data.selection);
      }
      if (data.type === "dock/comment-target" || data.type === "dock/comment-focus") { setPanelOpen(true); setRail("activity"); }
      if (data.type === "dock/elements" && Array.isArray(data.items)) {
        clearTimeout(elementsTimer.current);
        setElements(data);
      }
    };
    window.addEventListener("message", onMessage);
    return () => {
      clearTimeout(elementsTimer.current);
      window.removeEventListener("message", onMessage);
    };
  }, [running, visible?.url, frameKey, param]);

  // What the Dock host (Faustus) sees of this screen: the same active and expired elements the panel shows.
  useEffect(() => {
    window.HoardApp?.setContext?.(canvasContext({ project, revision: visible?.revision, mode, selection, comments }));
  }, [project?.id, project?.name, visible?.revision, mode, selection, comments]);
  useEffect(() => () => window.HoardApp?.setContext?.({}), []);

  const choose = (next) => {
    const current = held.current;
    if (next === current) next = "navigate";
    modeMessages(next, current).forEach(send);
    setMode(next);
    if (next === "comment") { setPanelOpen(true); setRail("activity"); }
  };
  useEffect(() => {
    // Select has its own Esc in PreviewSelection; the handles mode is left from here.
    const onKey = (event) => { if (event.key === "Escape" && held.current === "handles") choose("navigate"); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const moveModeFocus = (event) => {
    const buttons = Array.from(event.currentTarget.querySelectorAll("button"));
    const index = buttons.indexOf(document.activeElement);
    let next;
    if (event.key === "ArrowRight") next = (index + 1) % buttons.length;
    if (event.key === "ArrowLeft") next = (index - 1 + buttons.length) % buttons.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = buttons.length - 1;
    if (next !== undefined) { event.preventDefault(); buttons[next]?.focus(); }
  };

  const selectElement = (id, additive) => {
    send({ type: "inspect/element-select", id, additive, page: elements.page, revision: elements.revision });
  };
  const updateHistory = (updated) => {
    if (currentId.current !== param) return;
    if (!updated) { void loadProject(param); return; }
    projectRequest.current++;
    setProject((held) => (held?.id === updated.id && held.updated_ts <= updated.updated_ts ? updated : held));
  };

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
        <button className="btn canvas-focus-toggle" type="button" aria-pressed={focusMode} onClick={() => setFocusMode((held) => !held)}>
          {es ? "Modo enfoque" : "Focus mode"}
        </button>
        {running && <span className="help">{es ? "Versión" : "Revision"} {project.revisions.indexOf(visible.revision) + 1}{visible.revision === project.revision ? (es ? " · actual" : " · current") : ""}</span>}
      </>}
    </div>
    {!param && projectsState === "loading" ? <p className="help" role="status">{es ? "Cargando aplicaciones…" : "Loading applications…"}</p>
      : !param && projectsState === "error" ? <Empty><p role="alert">{es ? "No se pudieron cargar las aplicaciones." : "Could not load applications."}</p><button type="button" className="btn" onClick={loadProjects}>{es ? "Reintentar" : "Retry"}</button></Empty>
      : !param ? <Empty>{projects.length ? (es ? "Elige una aplicación para verla en el lienzo." : "Choose an application to see it on the canvas.") : (es ? "Crea una aplicación en Aplicaciones para empezar." : "Create an application in Applications to begin.")}</Empty>
      : !project ? (projectError
        ? <Empty><p role="alert">{es ? "No se pudo cargar la aplicación." : "Could not load the application."}</p><button type="button" className="btn" onClick={() => loadProject(param)}>{es ? "Reintentar" : "Retry"}</button></Empty>
        : <p className="help" role="status">{es ? "Cargando…" : "Loading…"}</p>)
      : <>
        <div className="canvas-mode-bar">
          {running && <>
          <div role="toolbar" aria-label={es ? "Modo del lienzo" : "Canvas mode"} className="canvas-modes" onKeyDown={moveModeFocus}>
            {modes.map((item) => <button key={item} type="button" className="canvas-mode" aria-pressed={mode === item}
              aria-keyshortcuts={item === "select" ? "Alt+Shift+S" : item === "comment" ? "Alt+Shift+C" : undefined}
              onClick={() => choose(item)}>{es ? MODE_TEXT[item][0] : MODE_TEXT[item][1]}</button>)}
          </div>
          <p className="help canvas-mode-hint" role="status">{modes.length === 1
            ? (elements?.error ? (es ? "Esta vista previa solo admite navegar." : "This preview only supports navigating.")
              : (es ? "Conectando con la vista previa…" : "Connecting to the preview…"))
            : MODE_TEXT[mode][es ? 2 : 3]}</p>
          </>}
          <button className="btn btn-sm" type="button" aria-expanded={panelOpen} aria-controls="canvas-rail"
            onClick={() => setPanelOpen((held) => !held)}>
            {panelOpen ? (es ? "Recoger panel" : "Collapse panel") : (es ? "Mostrar panel" : "Expand panel")}
          </button>
        </div>
        <div className="canvas-workspace" data-panel-closed={!panelOpen || undefined}>
          {running
            ? <PreviewFrames frames={frames} frameRef={attachFrame} allow={previewAllow(project)} title={es ? "Vista previa de aplicación" : "Application preview"} height="var(--canvas-height)" />
            : <Empty>{es ? "Abre la vista previa para trabajar sobre la aplicación." : "Open the preview to work on the application."}</Empty>}
          <div className="canvas-rail-slot" inert={!panelOpen}>
            <aside id="canvas-rail" className="canvas-inspector" aria-label={es ? "Panel del lienzo" : "Canvas inspector"}>
              <div className="canvas-rail-tabs" role="tablist" aria-label={es ? "Vistas del panel" : "Panel views"} onKeyDown={(event) => {
                if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
                event.preventDefault();
                const next = event.key === "Home" ? "activity" : event.key === "End" ? "elements"
                  : rail === "activity" ? "elements" : "activity";
                setRail(next); document.getElementById(`canvas-tab-${next}`)?.focus();
              }}>
                {["activity", "elements"].map((tab) => <button key={tab} id={`canvas-tab-${tab}`} type="button" role="tab"
                  aria-selected={rail === tab} aria-controls={`canvas-pane-${tab}`} tabIndex={rail === tab ? 0 : -1}
                  onClick={() => setRail(tab)}>
                  {tab === "activity" ? (es ? "Conversación" : "Conversation") : (es ? "Elementos" : "Elements")}
                </button>)}
              </div>
              <div id="canvas-pane-activity" role="tabpanel" aria-labelledby="canvas-tab-activity" hidden={rail !== "activity"}>
                <CanvasConversation es={es} projectId={project.id} />
                <CanvasTimeline steps={liveSteps.filter((step) => step.projectId === param
                  && (step.kind !== "edit" || step.revision === visible?.revision))} es={es} />
                <ProjectCritiqueLoop key={project.id} project={project} visibleRevision={visible?.revision}
                  lang={lang} onRevision={syncRevision} />
                <CanvasHistory key={project.id} project={project} visibleRevision={visible?.revision} onChange={updateHistory} es={es} />
              </div>
              <div id="canvas-pane-elements" role="tabpanel" aria-labelledby="canvas-tab-elements" hidden={rail !== "elements"}>
                {running
                  ? <CanvasElements elements={elements} onSelect={selectElement} onRetry={requestElements} es={es} />
                  : <div className="canvas-inspector-section">
                      <p className="canvas-empty">{es ? "Abre la vista previa para ver los elementos." : "Open the preview to see its elements."}</p>
                    </div>}
              </div>
              <PreviewSelection key={project.id} project={project} preview={preview} frameRef={frameRef} frameKey={frameKey} es={es} notify={notify} canvas onComments={setComments} />
            </aside>
          </div>
        </div>
      </>}
  </div>;
}
