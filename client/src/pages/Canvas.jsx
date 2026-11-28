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
import { canvasContext, isCanvasMessage, modeFromPage, modeMessages, previewPick, supportedModes } from "../canvas/canvasPanel.js";

const MODE_TEXT = {
  navigate: ["Navegar", "Navigate", "Usa la aplicación como siempre.", "Use the application as usual."],
  select: ["Seleccionar", "Select", "Haz clic o elige un elemento en el panel. Mayús+clic añade o quita. Arrastra un tirador o pulsa Alt+Intro. Doble clic edita texto. Esc sale.", "Click or choose an element in the panel. Shift+click adds or removes. Drag a handle or press Alt+Enter. Double-click edits text. Esc leaves."],
  comment: ["Comentar", "Comment", "Haz clic en un elemento y escribe la nota en el panel. Esc sale.", "Click an element and write the note in the panel. Esc leaves."],
  handles: ["Tiradores", "Handles", "Arrastra los tiradores para cambiar tamaño, margen o relleno. Esc sale.", "Drag the handles to change size, margin or padding. Esc leaves."],
};
const CONNECTING_MODES = ["navigate", "select", "comment"];
const HELLO_INTERVAL = 500;
const CONNECT_WINDOW = 12000;
const MODE_RETRY = 900;
const MODE_TIMEOUT = 3500;

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
  const [modes, setModes] = useState(null);
  const capabilities = useRef(null);
  const [mode, setMode] = useState("navigate");
  const [requestedMode, setRequestedMode] = useState(null);
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
  const setConfirmedMode = (next) => { held.current = next; setMode(next); };
  const modeChange = useRef(null);
  const modeRequest = useRef(0);
  const lastPreview = useRef(null);

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
  const hasFrame = running && frameKey !== undefined;
  const previewSession = running ? (preview.session || preview.url) : null;

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

  // One preview opening keeps the requested mode across frame replacements. A new opening starts in Navigate.
  useEffect(() => {
    const sameOpening = lastPreview.current?.project === param && lastPreview.current?.session === previewSession;
    const restore = sameOpening ? (modeChange.current?.mode || held.current) : "navigate";
    lastPreview.current = hasFrame ? { project: param, session: previewSession } : null;
    capabilities.current = null;
    setModes(null);
    setConfirmedMode("navigate");
    clearModeChange();
    if (hasFrame && restore !== "navigate") queueMode(restore);
    return () => clearTimeout(modeChange.current?.timer);
  }, [param, hasFrame, previewSession, visible?.url, frameKey]);
  useEffect(() => { if (!running) setSelection([]); }, [running, param]);
  useEffect(() => { setSelection([]); }, [param]);

  const originOf = (frame) => { try { return new URL(frame.src, window.location.href).origin; } catch { return null; } };
  const send = (message) => {
    const frame = frameRef.current;
    const target = frame && originOf(frame);
    if (frame?.contentWindow && target) frame.contentWindow.postMessage({ hoardDock: 1, ...message }, target);
  };

  function clearModeChange() {
    clearTimeout(modeChange.current?.timer);
    modeChange.current = null;
    setRequestedMode(null);
  }

  function navigate() {
    for (const leaving of new Set([modeChange.current?.mode, held.current])) {
      modeMessages("navigate", leaving).forEach(send);
    }
    clearModeChange();
    setConfirmedMode("navigate");
  }

  function requestMode(pending) {
    const now = Date.now();
    if (now < (pending.retryAfter ?? 0)) return;
    pending.retryAfter = now + MODE_RETRY;
    if (pending.timer === undefined) {
      pending.timer = setTimeout(() => {
        if (modeChange.current !== pending || pending.ready) return;
        navigate();
        notify(es ? "No se pudo activar el modo en la vista previa." : "Could not activate the mode in the preview.");
      }, MODE_TIMEOUT);
    }
    send(pending.message);
  }

  function queueMode(next) {
    clearModeChange();
    const message = { ...modeMessages(next, held.current)[0], mode_request: ++modeRequest.current };
    const pending = { mode: next, message, ready: false, pointer: null, pick: null };
    modeChange.current = pending;
    setRequestedMode(next);
    if (capabilities.current) requestMode(pending);
  }

  const finishModeChange = () => {
    const pending = modeChange.current;
    if (!pending?.ready || pending.pointer) return;
    if (pending.pick) send(pending.pick);
    clearModeChange();
  };

  const shieldDown = (event) => {
    const pending = modeChange.current;
    if (!pending || pending.pick || pending.pointer || event.button !== 0 || !event.isPrimary) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    pending.pointer = { id: event.pointerId, x: event.clientX, y: event.clientY };
  };

  const shieldEnd = (event) => {
    const pending = modeChange.current;
    const pointer = pending?.pointer;
    if (!pointer || pointer.id !== event.pointerId) return;
    if (event.type === "pointerup" && frameRef.current &&
        Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) <= 8) {
      pending.pick = previewPick(frameRef.current, event);
    }
    pending.pointer = null;
    finishModeChange();
  };

  const requestElements = () => {
    clearTimeout(elementsTimer.current);
    send({ type: "inspect/elements" });
    elementsTimer.current = setTimeout(() => setElements((current) => ({ ...current, error: true })), 3500);
  };

  // Ask for a fresh greeting on mount and load. A lost command can be resent on the next greeting with the same id.
  useEffect(() => {
    const frame = frameRef.current;
    if (!hasFrame || !frame) { setElements(null); return undefined; }
    setElements((current) => current?.items ? current : null);
    elementsTimer.current = setTimeout(() => setElements((current) => ({ ...current, error: true })), 3500);
    let connectUntil;
    const hello = () => send({ type: "inspect/hello" });
    const onLoad = () => { connectUntil = Date.now() + CONNECT_WINDOW; hello(); };
    const onMessage = (event) => {
      const frame = frameRef.current;
      if (!isCanvasMessage(event, frame?.contentWindow, frame && originOf(frame))) return;
      const data = event.data;
      if (data.type === "dock/inspector-ready") {
        const offered = supportedModes(data);
        capabilities.current = offered;
        setModes(offered);
        const pending = modeChange.current;
        if (pending && !offered.includes(pending.mode)) {
          navigate();
          notify(es ? "Esta vista previa no admite el modo solicitado." : "This preview does not support the requested mode.");
        } else if (pending && !pending.ready) requestMode(pending);
        else if (!pending) {
          const reported = modeFromPage(data);
          const previous = held.current;
          setConfirmedMode(reported);
          if (previous !== "navigate" && previous !== reported && offered.includes(previous)) queueMode(previous);
        }
        requestElements();
        if (Array.isArray(data.selection) && data.selection.length) setSelection(data.selection); // empty: PreviewSelection restores it
        return;
      }
      if (data.type === "dock/select") {
        const next = modeFromPage(data);
        const pending = modeChange.current;
        if (pending && data.mode_request === pending.message.mode_request && next === pending.mode) {
          pending.ready = true;
          clearTimeout(pending.timer);
          setConfirmedMode(next);
          finishModeChange();
        } else if (!pending && data.mode_request === undefined) {
          if (next === "comment" && held.current !== "comment") { setPanelOpen(true); setRail("activity"); }
          setConfirmedMode(next);
        }
        if (Array.isArray(data.selection)) setSelection(data.selection);
      }
      if (data.type === "dock/comment-target" || data.type === "dock/comment-focus") { setPanelOpen(true); setRail("activity"); }
      if (data.type === "dock/elements" && Array.isArray(data.items)) {
        clearTimeout(elementsTimer.current);
        setElements(data);
      }
    };
    window.addEventListener("message", onMessage);
    frame.addEventListener("load", onLoad);
    onLoad();
    const probe = setInterval(() => {
      const pending = modeChange.current;
      if (pending ? !pending.ready : !capabilities.current && Date.now() < connectUntil) hello();
    }, HELLO_INTERVAL);
    return () => {
      clearTimeout(elementsTimer.current);
      clearInterval(probe);
      window.removeEventListener("message", onMessage);
      frame.removeEventListener("load", onLoad);
    };
  }, [hasFrame, visible?.url, frameKey, param, es]);

  // What the Dock host (Faustus) sees of this screen: the same active and expired elements the panel shows.
  useEffect(() => {
    window.HoardApp?.setContext?.(canvasContext({ project, revision: visible?.revision, mode, selection, comments }));
  }, [project?.id, project?.name, visible?.revision, mode, selection, comments]);
  useEffect(() => () => window.HoardApp?.setContext?.({}), []);

  const choose = (next) => {
    if (next === "navigate" || next === (modeChange.current?.mode || held.current)) { navigate(); return; }
    if (next === "handles") {
      clearModeChange();
      modeMessages(next, held.current).forEach(send);
      setConfirmedMode(next);
      return;
    }
    queueMode(next);
    if (next === "comment") { setPanelOpen(true); setRail("activity"); }
  };
  useEffect(() => {
    // Route the host's mode shortcuts through the same handoff as the toolbar.
    const onKey = (event) => {
      if (event.altKey && event.shiftKey && (event.code === "KeyS" || event.code === "KeyC")) {
        const next = event.code === "KeyS" ? "select" : "comment";
        if (hasFrame && (!capabilities.current || capabilities.current.includes(next))) {
          event.preventDefault();
          event.stopImmediatePropagation();
          choose(next);
        }
      } else if (!event.defaultPrevented && event.key === "Escape" && (held.current !== "navigate" || modeChange.current)) {
        navigate();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
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

  const locale = es ? 0 : 1;
  const requestedLabel = requestedMode && MODE_TEXT[requestedMode][locale];
  const modeHint = !modes
    ? requestedMode
      ? (es ? `Conectando con la vista previa… Se activará «${requestedLabel}» al conectar.` : `Connecting to the preview… “${requestedLabel}” will activate when connected.`)
      : (es ? "Conectando con la vista previa…" : "Connecting to the preview…")
    : requestedMode
      ? (es ? `Activando «${requestedLabel}»…` : `Activating “${requestedLabel}”…`)
      : modes.length === 1
        ? (es ? "Esta vista previa solo admite navegar." : "This preview only supports navigating.")
        : MODE_TEXT[mode][es ? 2 : 3];

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
          {hasFrame && <>
          <div role="toolbar" aria-label={es ? "Modo del lienzo" : "Canvas mode"} aria-describedby="canvas-mode-status" className="canvas-modes" onKeyDown={moveModeFocus}>
            {(modes || CONNECTING_MODES).map((item) => <button key={item} type="button" className="canvas-mode" aria-pressed={mode === item}
              aria-describedby="canvas-mode-status"
              aria-keyshortcuts={item === "select" ? "Alt+Shift+S" : item === "comment" ? "Alt+Shift+C" : undefined}
              onClick={() => choose(item)}>{MODE_TEXT[item][locale]}</button>)}
          </div>
          <p className="help canvas-mode-hint" id="canvas-mode-status" role="status">{modeHint}</p>
          </>}
          <button className="btn btn-sm" type="button" aria-expanded={panelOpen} aria-controls="canvas-rail"
            onClick={() => setPanelOpen((held) => !held)}>
            {panelOpen ? (es ? "Recoger panel" : "Collapse panel") : (es ? "Mostrar panel" : "Expand panel")}
          </button>
        </div>
        <div className="canvas-workspace" data-panel-closed={!panelOpen || undefined}>
          {running
            ? <div className="relative min-w-0">
                <PreviewFrames frames={frames} frameRef={attachFrame} allow={previewAllow(project)} title={es ? "Vista previa de aplicación" : "Application preview"} height="var(--canvas-height)" />
                {requestedMode && <div className="canvas-mode-shield" aria-hidden="true" onPointerDown={shieldDown}
                  onPointerUp={shieldEnd} onPointerCancel={shieldEnd} onLostPointerCapture={shieldEnd} />}
              </div>
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
