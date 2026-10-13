import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { useCopilotForm, useCopilotObjects, useCopilotRefresh } from "../copilot-hooks.js";
import { Empty } from "../components/ui.jsx";

export default function Projects({ param }) {
  const { lang, notify } = useApp();
  const es = lang === "es";
  const [templates, setTemplates] = useState([]);
  const [projects, setProjects] = useState([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [template, setTemplate] = useState("work-board");
  const [project, setProject] = useState(null);
  const [file, setFile] = useState("pages/index.html");
  const [drafts, setDrafts] = useState({});
  const [newFile, setNewFile] = useState("");
  const [preview, setPreview] = useState(null);
  const [bundle, setBundle] = useState(null);
  const [includeData, setIncludeData] = useState(false);
  const [busy, setBusy] = useState("");
  const [render, setRender] = useState(null);
  const loadSequence = useRef(0);
  const listSequence = useRef(0);
  const currentId = useRef(param);
  currentId.current = param;
  const createDraft = useRef({ name, description });
  createDraft.current = { name, description };
  const activeView = useRef({ revision: null, file });
  activeView.current = { revision: project?.selected_revision, file };
  const draftPrefix = project ? `${project.id}:${project.selected_revision}:` : "";
  const draftKey = draftPrefix + file;
  const source = project ? drafts[draftKey] ?? project.files[file] ?? "" : "";
  const draftPaths = Object.keys(drafts).filter((key) => key.startsWith(draftPrefix)).map((key) => key.slice(draftPrefix.length));
  useCopilotForm("app-create-draft", { initial: { name: "", description: "", template: "work-board" }, current: { name, description, template } });
  useCopilotForm("app-source-draft", { objectId: project?.id, initial: { file, source: project?.files[file] ?? "" }, current: { file, source, revision: project?.selected_revision } });
  useCopilotObjects(project ? [{ kind: "app_project", id: project.id }] : []);
  const loadList = async () => { const sequence = ++listSequence.current; try { const data = await api.appProjects(); if (sequence === listSequence.current) setProjects(data.projects); } catch (error) { if (sequence === listSequence.current) notify(error.message); } };
  const loadProject = async (id, revision) => {
    const sequence = ++loadSequence.current;
    try {
      const data = await api.appProject(id, revision);
      if (sequence !== loadSequence.current || currentId.current !== id) return;
      setProject(data); setPreview(data.preview);
    } catch (error) { if (sequence === loadSequence.current) notify(error.message); }
  };
  useEffect(() => { loadList(); api.appTemplates().then((data) => setTemplates(data.templates)).catch((error) => notify(error.message)); }, []);
  useEffect(() => {
    loadSequence.current++;
    setProject(null); setPreview(null); setBundle(null); setRender(null); setFile("pages/index.html");
    if (param) loadProject(param);
    return () => { loadSequence.current++; };
  }, [param]);
  useCopilotRefresh(() => { loadList(); if (param) loadProject(param); });
  const create = async (event) => {
    event.preventDefault(); setBusy("create");
    const submitted = { name, description, template };
    const submittedRoute = window.location.hash;
    try {
      const data = await api.appProjectCreate(submitted);
      if (createDraft.current.name === submitted.name) setName("");
      if (createDraft.current.description === submitted.description) setDescription("");
      await loadList(); if (window.location.hash === submittedRoute) window.location.hash = `#/projects/${data.id}`;
    } catch (error) { notify(error.message); }
    finally { setBusy(""); }
  };
  const save = async () => {
    const captured = { id: project.id, file, source, revision: project.selected_revision, key: draftKey };
    loadSequence.current++; setBusy("save");
    try {
      const data = await api.appProjectUpdate(captured.id, { files: { [captured.file]: captured.source }, expected_revision: captured.revision });
      if (currentId.current !== captured.id) return;
      loadSequence.current++;
      if (activeView.current.revision === captured.revision) setProject(data);
      else loadProject(captured.id, activeView.current.revision);
      setDrafts((current) => {
        const next = { ...current };
        const prefix = `${captured.id}:${captured.revision}:`;
        for (const [key, value] of Object.entries(current)) {
          if (!key.startsWith(prefix)) continue;
          const path = key.slice(prefix.length);
          if (key === captured.key && value === captured.source) delete next[key];
          else {
            const newKey = `${captured.id}:${data.selected_revision}:${path}`;
            if (next[newKey] === undefined) next[newKey] = value;
          }
        }
        return next;
      });
      notify(es ? "Versión guardada" : "Revision saved"); loadList();
    } catch (error) { notify(error.message); }
    finally { setBusy(""); }
  };
  const run = async (operation) => {
    const id = project.id; loadSequence.current++; setBusy(operation);
    try {
      const result = await api.appProjectPreview(id, { operation, revision: project.selected_revision });
      if (currentId.current === id) { loadSequence.current++; setPreview(result); }
    } catch (error) { notify(error.message); }
    finally { setBusy(""); }
  };
  const exportProject = async () => {
    const id = project.id; setBusy("export");
    try { const result = await api.appProjectExport(id, { revision: project.selected_revision, include_data: includeData }); if (currentId.current === id) setBundle(result); }
    catch (error) { notify(error.message); }
    finally { setBusy(""); }
  };
  const capture = async () => {
    const id = project.id; setBusy("render");
    try { const result = await api.appProjectRender(id, { revision: project.selected_revision, widths: [390, 1440] }); if (currentId.current === id) setRender(result); }
    catch (error) { notify(error.message); }
    finally { setBusy(""); }
  };
  return <div className="flex flex-col gap-6">
    <h1 className="text-[20px] font-semibold">{es ? "Aplicaciones" : "Applications"}</h1>
    <details className="panel" open={!projects.length && !project}><summary className="cursor-pointer font-semibold">{es ? "Crear aplicación" : "Create application"}</summary>
    <form className="flex flex-col gap-3 mt-3" onSubmit={create}>
      <div className="grid md:grid-cols-2 gap-3">
        <label className="label">{es ? "Nombre" : "Name"}<input className="field mt-1" value={name} onChange={(event) => setName(event.target.value)} required /></label>
        <label className="label">{es ? "Punto de partida" : "Starting point"}<select aria-label={es ? "Punto de partida" : "Starting point"} className="field mt-1" value={template} onChange={(event) => setTemplate(event.target.value)}>{templates.map((item) => <option key={item.id} value={item.id}>{es ? item.name_es : item.name}</option>)}</select></label>
      </div>
      <label className="label">{es ? "Descripción" : "Description"}<input className="field mt-1" value={description} onChange={(event) => setDescription(event.target.value)} /></label>
      <p className="help">{es ? "Incluye páginas, datos persistentes y servidor propio. El código se puede editar y exportar para usarlo por separado." : "Includes pages, persistent data and its own server. Edit and export the code to run it independently."}</p>
      <button className="btn btn-primary self-start" disabled={!!busy || !name.trim()}>{busy === "create" ? (es ? "Creando…" : "Creating…") : (es ? "Crear" : "Create")}</button>
    </form></details>
    <div className="grid lg:grid-cols-[240px_minmax(0,1fr)] gap-5">
      <aside className="panel">
        <h2 className="font-semibold mb-3">{es ? "Proyectos" : "Projects"}</h2>
        {!projects.length && <p className="help">{es ? "Crea una aplicación para empezar." : "Create an application to begin."}</p>}
        <div className="flex flex-col gap-2">{projects.map((item) => <a key={item.id} className={`btn text-left break-words ${item.id === param ? "btn-active" : ""}`} href={`#/projects/${item.id}`} aria-current={item.id === param ? "page" : undefined}>{item.name}</a>)}</div>
      </aside>
      {!project ? <Empty>{es ? "Selecciona un proyecto para editarlo y probarlo." : "Select a project to edit and test it."}</Empty> : <div className="min-w-0 flex flex-col gap-4">
        <div className="panel">
          <h2 className="text-[16px] font-semibold break-words">{project.name}</h2>
          <div className="flex gap-2 items-center flex-wrap mt-3">
            <label className="label">{es ? "Versión" : "Revision"}<select aria-label={es ? "Versión" : "Revision"} className="field" value={project.selected_revision} onChange={(event) => loadProject(project.id, event.target.value)}>{project.revisions.map((revision, index) => <option key={revision} value={revision}>{index + 1}{revision === project.revision ? (es ? " · actual" : " · current") : ""}</option>)}</select></label>
            <button className="btn" disabled={!!busy} onClick={() => run("start")}>{busy === "start" ? (es ? "Abriendo…" : "Opening…") : (es ? "Abrir vista previa" : "Open preview")}</button>
            {preview?.state === "running" && <button className="btn" disabled={!!busy} onClick={() => run("stop")}>{es ? "Detener vista previa" : "Stop preview"}</button>}
            <button className="btn" disabled={!!busy} onClick={capture}>{busy === "render" ? (es ? "Capturando…" : "Capturing…") : (es ? "Capturar para revisión" : "Capture for review")}</button>
          </div>
          {preview?.state === "running" && <p className="help mt-3">{preview.revision === project.selected_revision ? (es ? "Vista previa de esta versión" : "Preview of this revision") : (es ? "La vista previa muestra otra versión" : "Preview shows another revision")} · <a className="underline" href={preview.url} target="_blank" rel="noreferrer">{es ? "Abrir en otra pestaña" : "Open in another tab"}</a></p>}
        </div>
        {preview?.state === "running" && <iframe title={es ? "Vista previa de aplicación" : "Application preview"} src={preview.url} className="w-full border rounded-md" style={{ height: 560, borderColor: "var(--line)", background: "white" }} />}
        <div className="panel">
          <h3 className="font-semibold">{es ? "Archivos de la aplicación" : "Application files"}</h3>
          <label className="label mt-3">{es ? "Archivo" : "File"}<select aria-label={es ? "Archivo" : "File"} className="field" value={file} onChange={(event) => setFile(event.target.value)}>{Array.from(new Set([...Object.keys(project.files), ...draftPaths])).sort().map((path) => <option key={path} value={path}>{path}{drafts[draftPrefix + path] !== undefined ? " *" : ""}</option>)}</select></label>
          <label className="label mt-3">{es ? "Fuente editable" : "Editable source"}<textarea aria-label={es ? "Fuente editable" : "Editable source"} className="field mt-1" rows={12} value={source} onChange={(event) => setDrafts((current) => ({ ...current, [draftKey]: event.target.value }))} /></label>
          <div className="flex gap-2 items-center flex-wrap mt-3"><button className="btn btn-primary" disabled={!!busy || drafts[draftKey] === undefined} onClick={save}>{busy === "save" ? (es ? "Guardando…" : "Saving…") : (es ? "Guardar archivo" : "Save file")}</button><span className="help">{es ? "Guardar conserva las versiones anteriores y los datos." : "Saving retains earlier revisions and data."}</span></div>
          <details className="mt-3"><summary className="cursor-pointer help">{es ? "Añadir archivo" : "Add file"}</summary><div className="flex gap-2 flex-wrap mt-2"><input className="field flex-1 min-w-0" aria-label={es ? "Ruta del archivo nuevo" : "New file path"} placeholder="pages/about.html" value={newFile} onChange={(event) => setNewFile(event.target.value)} /><button className="btn" type="button" disabled={!newFile.trim()} onClick={() => { if (!Object.hasOwn(project.files, newFile)) setDrafts((current) => ({ ...current, [draftPrefix + newFile]: current[draftPrefix + newFile] ?? "" })); setFile(newFile); setNewFile(""); }}>{es ? "Añadir" : "Add"}</button></div></details>
        </div>
        <div className="panel flex gap-3 flex-wrap items-center"><label className="flex gap-2 items-center"><input type="checkbox" checked={includeData} onChange={(event) => setIncludeData(event.target.checked)} />{es ? "Incluir copia de los datos" : "Include a data copy"}</label><button className="btn" disabled={!!busy} onClick={exportProject}>{busy === "export" ? (es ? "Exportando…" : "Exporting…") : (es ? "Exportar aplicación" : "Export application")}</button>{bundle && <a className="btn btn-primary" href={bundle.download_url} download>{`${es ? "Descargar ZIP · versión" : "Download ZIP · revision"} ${project.revisions.indexOf(bundle.revision) + 1}`}</a>}</div>
        {render && <div className="panel"><p className="help">{es ? "Captura guardada en el historial de Crítica." : "Capture saved in Critique history."}</p><a href="#/critique" className="btn mt-2">{es ? "Revisar captura" : "Review capture"}</a></div>}
      </div>}
    </div>
  </div>;
}
