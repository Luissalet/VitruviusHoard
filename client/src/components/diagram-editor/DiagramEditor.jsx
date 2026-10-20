import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api.js";
import { useApp } from "../../App.jsx";
import { useCopilotForm, useCopilotObjects, useCopilotRefresh } from "../../copilot-hooks.js";
import { clone, connector, equal, geometry, mergeDraft, templates, uid } from "./model.js";
import { editorialNames, editorialTemplate, selectedPage } from './editorial.js';
import { PageControls, TextControls } from './EditorialControls.jsx';
import { StyleControls } from './StyleControls.jsx';
import { IsometricControls, selectedState } from './IsometricControls.jsx';
import "./diagram-editor.css";

const labels = {
  es: { title: "Editor visual", blank: "En blanco", template: "Plantilla", use: "Usar plantilla", save: "Guardar", saving: "Guardando…", saved: "Guardado", dirty: "Cambios sin guardar", nodes: "Formas", select: "Seleccionar", connect: "Conectar", pan: "Mover vista", name: "Nombre del diagrama", text: "Texto", details: "Explicación y fuentes", width: "Ancho", height: "Alto", pin: "Fijar posición", fill: "Relleno", shape: "Forma", remove: "Eliminar selección", duplicate: "Duplicar", arrange: "Distribuir automáticamente", group: "Agrupar", ungroup: "Desagrupar", left: "Alinear a la izquierda", top: "Alinear arriba", undo: "Deshacer", redo: "Rehacer", history: "Versiones", compare: "Comparar con la actual", export: "Exportar", source: "Fuente editable", reader: "Vista interactiva", import: "Importar", documents: "Documentos", empty: "Crea un diagrama en blanco o parte de una plantilla. También puedes pedirlo al panel de Faustus.", selected: "seleccionadas", hint: "Arrastra para mover. Mayús añade a la selección. Flechas desplazan; Supr elimina. Intro activa; Mayús+Intro añade; Esc cancela.", connectHint: "Selecciona la forma de origen y después la de destino.", noSelection: "Selecciona una forma o conexión para editarla.", selectDocument: "Abrir documento…", flow: "Proceso con revisión", architecture: "Arquitectura", tree: "Organigrama", concepts: "Mapa conceptual", comparison: "Comparación", help: "Edición manual y Faustus sobre el mismo documento.", revision: "Revisión", next: "Origen", target: "Destino", mode: "Color", light: "Claro", dark: "Oscuro", views: "Ocultar o mostrar inspector", reloaded: "Se han conservado tus cambios al recibir la nueva revisión.", position: "Posición", result: "Cambios entre revisiones", emptyCanvas: "Añade una forma para empezar", style: "Línea", solid: "Continua", dashed: "Discontinua", box: "Rectángulo", round: "Redondeado", diamond: "Decisión", pill: "Inicio o fin", cylinder: "Datos", port: "Anclaje", auto: "Automático", right: "Derecha", bottom: "Abajo" },
  en: { title: "Visual editor", blank: "Blank", template: "Template", use: "Use template", save: "Save", saving: "Saving…", saved: "Saved", dirty: "Unsaved changes", nodes: "Shapes", select: "Select", connect: "Connect", pan: "Pan", name: "Diagram name", text: "Text", details: "Explanation and sources", width: "Width", height: "Height", pin: "Pin position", fill: "Fill", shape: "Shape", remove: "Delete selection", duplicate: "Duplicate", arrange: "Arrange automatically", group: "Group", ungroup: "Ungroup", left: "Align left", top: "Align top", undo: "Undo", redo: "Redo", history: "Versions", compare: "Compare with current", export: "Export", source: "Editable source", reader: "Interactive view", import: "Import", documents: "Documents", empty: "Create a blank diagram or start with a template. You can also ask the Faustus panel.", selected: "selected", hint: "Drag to move. Shift adds to the selection. Arrows move; Delete removes. Enter activates; Shift+Enter adds; Escape cancels.", connectHint: "Select the source shape, then the destination.", noSelection: "Select a shape or connector to edit it.", selectDocument: "Open document…", flow: "Review process", architecture: "Architecture", tree: "Organisation chart", concepts: "Concept map", comparison: "Comparison", help: "Manual editing and Faustus share the same document.", revision: "Revision", next: "Source", target: "Target", mode: "Colour", light: "Light", dark: "Dark", views: "Toggle inspector", reloaded: "Your changes were preserved while receiving the new revision.", position: "Position", result: "Changes between revisions", emptyCanvas: "Add a shape to get started", style: "Line", solid: "Solid", dashed: "Dashed", box: "Rectangle", round: "Rounded", diamond: "Decision", pill: "Start or end", cylinder: "Data", port: "Connection point", auto: "Automatic", right: "Right", bottom: "Bottom" },
};

export default function DiagramEditor() {
  const { lang, notify } = useApp();
  const l = labels[lang] || labels.es;
  const [row, setRow] = useState(null), [draft, setDraft] = useState(null), [items, setItems] = useState([]);
  const [selection, setSelection] = useState([]), [edgeId, setEdgeId] = useState(null), [tool, setTool] = useState("select");
  const [pending, setPending] = useState(false), [error, setError] = useState(""), [mode, setMode] = useState("light");
  const [zoom, setZoom] = useState(1), [pan, setPan] = useState({ x: 0, y: 0 }), [inspector, setInspector] = useState(true);
  const [canvasSize, setCanvasSize] = useState({ width: 800, height: 480 });
  const [paletteOpen, setPaletteOpen] = useState(() => window.innerWidth > 650);
  const [pageId, setPageId] = useState('');
  const [stateId, setStateId] = useState(''), [partId, setPartId] = useState('');
  const [template, setTemplate] = useState("flow"), [history, setHistory] = useState([]), [comparison, setComparison] = useState(null);
  const [undoStack, setUndoStack] = useState([]), [redoStack, setRedoStack] = useState([]);
  const svgRef = useRef(null), drag = useRef(null), draftRef = useRef(draft), rowRef = useRef(row), selectionRef = useRef(selection);
  const localUndo = useRef([]), localRedo = useRef([]);
  useEffect(() => { const query = matchMedia("(max-width:650px)"), changed = event => setPaletteOpen(!event.matches); query.addEventListener("change", changed); return () => query.removeEventListener("change", changed); }, []);
  draftRef.current = draft; rowRef.current = row; selectionRef.current = selection;
  useEffect(() => {
    if (!row || !svgRef.current) return;
    const observer = new ResizeObserver(([entry]) => setCanvasSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(svgRef.current); return () => observer.disconnect();
  }, [row?.id, inspector]);
  const reloadList = useCallback(() => api.diagramDocuments().then(data => setItems(data.documents || [])).catch(e => setError(e.message)), []);
  useEffect(() => { reloadList(); }, [reloadList]);
  useEffect(() => { if (row?.id && draft) sessionStorage.setItem(`diagram-draft:${row.id}`, JSON.stringify({ revision: row.revision, content: draft })); }, [draft, row]);
  useCopilotObjects(row ? [{ kind: "diagram-document", id: row.id }] : []);
  useCopilotForm("diagram-document-draft", { objectId: row?.id, initial: { content: row?.content, revision: row?.revision, selected_nodes: [], selected_edge: null }, current: { content: draft, revision: row?.revision, selected_nodes: selection, selected_edge: edgeId, selected_page: selectedPage(draft, pageId)?.id || null, selected_state: selectedState(draft, stateId) || null, selected_piece: draft?.diagram.type === 'isometric' ? (draft.diagram.pieces.find(p => p.id === partId) || draft.diagram.pieces[0])?.id : null } });
  const refresh = useCallback(async () => {
    reloadList();
    const old = rowRef.current;
    if (!old) return;
    try {
      const fresh = await api.diagramDocument(old.id);
      if (rowRef.current?.id !== old.id) return;
      const merged = mergeDraft(old.content, draftRef.current, fresh.content);
      // Rebase every local snapshot before adopting a new remote revision.
      // Undo and redo must preserve fields the person never edited.
      const rebasedUndo = localUndo.current.map(snapshot => mergeDraft(old.content, snapshot, fresh.content));
      const rebasedRedo = localRedo.current.map(snapshot => mergeDraft(old.content, snapshot, fresh.content));
      localUndo.current = rebasedUndo; localRedo.current = rebasedRedo;
      setRow(fresh); setDraft(merged);
    } catch (e) { setError(e.message); }
  }, [reloadList]);
  useCopilotRefresh(refresh);
  const adopt = (next) => { localUndo.current = []; localRedo.current = []; setRow(next); setDraft(clone(next.content)); setSelection([]); setEdgeId(null); setComparison(null); setHistory([]); setUndoStack([]); setRedoStack([]); setPan({ x: 0, y: 0 }); setZoom(1); setError(""); };
  const open = async id => {
    if (!id) return;
    try {
      const next = await api.diagramDocument(id), retained = JSON.parse(sessionStorage.getItem(`diagram-draft:${id}`) || "null");
      if (retained && retained.revision <= next.revision) {
        const base = retained.revision === next.revision ? next : await api.diagramDocument(id, retained.revision);
        let merged;
        try { merged = mergeDraft(base.content, retained.content, next.content); }
        catch (e) {
          // Keep both the local source and the revision it was based on. Saving
          // remains conflict-aware and session storage stays recoverable.
          adopt(base); setDraft(clone(retained.content)); setError(e.message); return;
        }
        adopt(next); setDraft(merged);
      } else if (retained) { throw new Error("El borrador pertenece a una revisión posterior; se ha conservado en esta sesión."); }
      else adopt(next);
    } catch (e) { setError(e.message); }
  };
  useEffect(() => {
    const follow = () => { const id = new URLSearchParams(location.hash.split("?")[1]).get("document"); if (id && /^[0-9a-f]{12}$/.test(id)) open(id); };
    follow(); window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  const create = async kind => { setPending(true); try { const content = kind?.startsWith('editorial') ? editorialTemplate(kind) : { diagram: kind ? clone(templates[kind]) : { type: "flowchart", title: "", nodes: [] } }; const next = await api.diagramDocumentSave({ content }); adopt(next); setPageId(''); reloadList(); } catch (e) { setError(e.message); } finally { setPending(false); } };
  const change = (fn, record = true) => { if (record) { localUndo.current.push(clone(draftRef.current)); localRedo.current = []; } setDraft(current => { const next = clone(current); fn(next); return next; }); };
  const save = async () => {
    const previous = rowRef.current, submitted = clone(draftRef.current);
    if (!previous) return;
    setPending(true); setError("");
    try {
      const next = await api.diagramDocumentSave({ id: previous.id, base_revision: previous.revision, content: submitted });
      if (rowRef.current?.id !== previous.id) return;
      const merged = mergeDraft(submitted, draftRef.current, next.content);
      localUndo.current = []; localRedo.current = []; setRow(next); setDraft(merged); setUndoStack(s => [...s, next.revision]); setRedoStack([]); reloadList();
      return next;
    } catch (e) { setError(e.message); } finally { setPending(false); }
  };
  const undo = async redo => {
    const local = redo ? localRedo : localUndo, reverse = redo ? localUndo : localRedo;
    if (local.current.length) { reverse.current.push(clone(draftRef.current)); setDraft(local.current.pop()); return; }
    const stack = redo ? redoStack : undoStack, revision = stack.at(-1);
    if (!revision || !equal(draft, row.content)) return;
    setPending(true);
    try { const next = await api.diagramDocumentUndo(row.id, revision); setRow(next); setDraft(clone(next.content));
      if (redo) { setRedoStack(s => s.slice(0, -1)); setUndoStack(s => [...s, next.revision]); }
      else { setUndoStack(s => s.slice(0, -1)); setRedoStack(s => [...s, next.revision]); }
    } catch (e) { setError(e.message); } finally { setPending(false); }
  };
  const scene = row?.rendering?.scene, boxes = draft ? geometry(draft, scene) : {};
  const editorial = draft?.view.kind === 'infographic';
  const isometric = draft?.diagram.type === 'isometric';
  const stateUrl = (url, content = draft) => selectedState(content, stateId) ? `${url}&state_id=${encodeURIComponent(selectedState(content, stateId))}` : url;
  const page = selectedPage(draft, pageId);
  const visibleNodes = (draft?.diagram.nodes || []).filter(n => !page || boxes[n.id].page_id === page.id);
  const visibleIds = new Set(visibleNodes.map(n => n.id));
  const visibleEdges = (draft?.diagram.edges || []).filter(e => visibleIds.has(e.from) && visibleIds.has(e.to));
  const selectPage = id => { setPageId(id); setSelection([]); setEdgeId(null); setPan({x:0,y:0}); };
  const chosen = draft?.diagram.nodes.find(n => selection.includes(n.id)), edge = draft?.diagram.edges.find(e => e.id === edgeId);
  const colours = draft?.profile?.[mode] || { paper: "#ffffff", ink: "#1d2433", border: "#8a94a6", surface: "#f3f5f9", accent: "#2f5bd3", muted: "#5b6474" };
  const width = canvasSize.width, height = canvasSize.height;
  const fit = () => { setZoom(Math.min(width / (page?.width || Math.max(400, ...Object.values(boxes).map(b => b.x + b.width + 40))), height / (page?.height || Math.max(300, ...Object.values(boxes).map(b => b.y + b.height + 40))))); setPan({ x: 0, y: 0 }); };
  const dirty = row && !equal(draft, row.content), editableGraph = !draft || ["flowchart", "architecture", "state", "er", "swimlane"].includes(draft.diagram.type);
  const point = e => { const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(svgRef.current.getScreenCTM().inverse()); return { x: p.x, y: p.y }; };
  const moveSelection = (dx, dy) => change(next => { for (const id of selectionRef.current) { const b = boxes[id]; if (b && !b.pinned) next.view.nodes[id] = { ...b, x: Math.max(0, b.x + dx), y: Math.max(0, b.y + dy) }; } });
  const remove = () => change(next => { const gone = new Set(selection); next.diagram.nodes = next.diagram.nodes.filter(n => !gone.has(n.id)); next.diagram.edges = next.diagram.edges.filter(e => e.id !== edgeId && !gone.has(e.from) && !gone.has(e.to)); setSelection([]); setEdgeId(null); });
  const add = shape => { const id = uid("node"); change(next => { next.diagram.nodes.push({ id, label: l[shape], shape }); next.view.nodes[id] = { ...(page ? {page_id:page.id,font_size:22,font_weight:500,align:'center'} : {}), x: Math.max(40, pan.x + 80 + (next.diagram.nodes.length % 4) * 35), y: Math.max(60, pan.y + 100 + (next.diagram.nodes.length % 4) * 35), width: 176, height: shape === "diamond" ? 96 : 64 }; }); setSelection([id]); setEdgeId(null); };
  const duplicate = () => change(next => { const mapped = Object.fromEntries(selection.map(id => [id, uid("node")])); const nodes = next.diagram.nodes.filter(n => mapped[n.id]).map(n => ({ ...clone(n), id: mapped[n.id] })); next.diagram.nodes.push(...nodes); for (const id of selection) next.view.nodes[mapped[id]] = { ...boxes[id], x: boxes[id].x + 30, y: boxes[id].y + 30 }; next.diagram.edges.push(...next.diagram.edges.filter(e => mapped[e.from] && mapped[e.to]).map(e => ({ ...clone(e), id: uid("edge"), from: mapped[e.from], to: mapped[e.to] }))); setSelection(nodes.map(n => n.id)); });
  const align = axis => change(next => { const minimum = Math.min(...selection.map(id => boxes[id][axis])); for (const id of selection) next.view.nodes[id] = { ...boxes[id], [axis]: minimum }; });
  const group = () => change(next => { const id = uid("group"); next.diagram.groups.push({ id, label: lang === "en" ? "Group" : "Grupo" }); next.diagram.type = "architecture"; for (const node of next.diagram.nodes) if (selection.includes(node.id)) node.group = id; });
  const arrange = async () => {
    const previous = rowRef.current, source = clone(draftRef.current), next = clone(source);
    next.view.nodes = Object.fromEntries(Object.entries(next.view.nodes).filter(([, value]) => value.pinned)); next.view.edges = {};
    setPending(true);
    try { const preview = await api.diagramDocumentPreview(next); const positions = geometry(next, preview.rendering.scene);
      for (const [id, box] of Object.entries(positions)) next.view.nodes[id] = box;
      if (rowRef.current?.id === previous.id) { const before = draftRef.current, merged = mergeDraft(source, before, next); localUndo.current.push(clone(before)); localRedo.current = []; setDraft(merged); }
    } catch (e) { setError(e.message); } finally { setPending(false); }
  };
  const activateNode = (id, additive = false) => {
    setEdgeId(null);
    if (tool === "connect") { if (!selection.length) setSelection([id]); else { const from = selection[0]; change(next => next.diagram.edges.push({ id: uid("edge"), from, to: id, label: "", style: "solid" })); setSelection([]); } return; }
    const selected = additive ? selection.includes(id) ? selection.filter(key => key !== id) : [...selection, id] : selection.includes(id) ? selection : [id];
    setSelection(selected); return selected;
  };
  const pointerDown = (e, id) => {
    e.preventDefault(); e.stopPropagation(); svgRef.current.focus({ preventScroll: true });
    const selected = activateNode(id, e.shiftKey); if (!selected || e.shiftKey || tool === "pan") return;
    localUndo.current.push(clone(draftRef.current)); localRedo.current = [];
    drag.current = { start: point(e), extent: { width, height }, boxes: Object.fromEntries(selected.map(key => [key, boxes[key]])) }; svgRef.current.setPointerCapture(e.pointerId);
  };
  const pointerMove = e => {
    const state = drag.current; if (!state) return;
    if (state.pan) { const scale = svgRef.current.getBoundingClientRect().width / (width / zoom); setPan({ x: state.pan.x - (e.clientX - state.client.x) / scale, y: state.pan.y - (e.clientY - state.client.y) / scale }); return; }
    if (state.resize) { const p = point(e), b = state.box; change(next => { next.view.nodes[state.resize] = { ...b, width: Math.max(24, Math.round(b.width + p.x - state.start.x)), height: Math.max(24, Math.round(b.height + p.y - state.start.y)) }; }, false); return; }
    const p = point(e); change(next => { for (const [id, b] of Object.entries(state.boxes)) if (!b.pinned) next.view.nodes[id] = { ...b, x: Math.max(0, Math.round(b.x + p.x - state.start.x)), y: Math.max(0, Math.round(b.y + p.y - state.start.y)) }; }, false);
  };
  const updateNode = (key, value) => change(next => { const node = next.diagram.nodes.find(n => n.id === chosen.id); node[key] = value; });
  const updateBox = (key, value) => change(next => { next.view.nodes[chosen.id] = { ...boxes[chosen.id], [key]: value }; });
  const updateEdge = (key, value) => change(next => { next.diagram.edges.find(e => e.id === edgeId)[key] = value; });
  const importFile = async file => { if (!file) return; setPending(true); try { const next = await api.diagramDocumentImport(await file.text()); adopt(next); reloadList(); } catch (e) { setError(e.message); } finally { setPending(false); } };
  const output = async (event, kind) => {
    if (!dirty) return;
    event.preventDefault();
    const viewer = kind === "viewer" ? window.open("about:blank", "_blank") : null;
    const saved = await save();
    if (!saved) { viewer?.close(); return; }
    const url = kind === "viewer" ? api.diagramDocumentViewer(saved.id, saved.revision) : kind === "source" ? api.diagramDocumentSource(saved.id, saved.revision) : api.diagramDocumentExport(saved.id, kind, saved.revision, mode, kind === "vfigure" ? selectedPage(saved.content, page?.id)?.id || '' : '');
    if (viewer) viewer.location.href = stateUrl(url, saved.content);
    else { const link = document.createElement("a"); link.href = kind === 'source' ? url : stateUrl(url, saved.content); link.download = ""; document.body.append(link); link.click(); link.remove(); }
  };
  return <section className="diagram-editor" aria-label={l.title}>
    <div className="de-heading"><div><h2>{l.title}</h2><p>{l.help}</p></div><div className="de-actions"><button className="btn" disabled={pending} onClick={() => create(null)}>{l.blank}</button><label className="btn de-import">{l.import}<input aria-label={l.import} type="file" accept=".json,.vfigure,.xml,.drawio,.txt,.mmd,.excalidraw" onChange={e => { importFile(e.target.files?.[0]); e.target.value = ""; }}/></label></div></div>
    <div className="de-actions de-documentbar"><select className="field" aria-label={l.documents} value={row?.id || ""} onChange={e => open(e.target.value)}><option value="">{l.selectDocument}</option>{items.map(item => <option key={item.id} value={item.id}>{item.title || item.id}</option>)}</select><select className="field" aria-label={l.template} value={template} onChange={e => setTemplate(e.target.value)}>{[...Object.keys(templates),...Object.keys(editorialNames.es)].map(key => <option key={key} value={key}>{l[key] || (key === 'mechanism' ? (lang === 'en' ? 'Isometric mechanism' : 'Mecanismo isométrico') : '') || editorialNames[lang]?.[key] || editorialNames.es[key]}</option>)}</select><button className="btn" disabled={pending} onClick={() => create(template)}>{l.use}</button></div>
    {error && <p className="de-error" role="alert">{error}</p>}
    {!row ? <div className="de-empty"><p>{l.empty}</p><button className="btn btn-primary" onClick={() => create("flow")}>{l.flow}</button></div> : <>
      <div className="de-actions de-toolbar"><input className="field de-title" aria-label={l.name} value={draft.diagram.title} onChange={e => change(next => { next.diagram.title = e.target.value; })}/><button className="btn btn-primary" disabled={pending || !dirty} onClick={save}>{pending ? l.saving : l.save}</button><span className="de-status" role="status">{dirty ? l.dirty : `${l.saved} · ${l.revision} ${row.revision}`}</span><button className="btn" disabled={pending || !(localUndo.current.length || (!dirty && undoStack.length))} onClick={() => undo(false)}>{l.undo}</button><button className="btn" disabled={pending || !(localRedo.current.length || (!dirty && redoStack.length))} onClick={() => undo(true)}>{l.redo}</button><button className="btn de-tools-toggle" aria-expanded={paletteOpen} onClick={() => setPaletteOpen(v => !v)}>{l.nodes}</button><button className="btn" aria-expanded={inspector} onClick={() => setInspector(v => !v)}>{l.views}</button></div>
      {page && <PageControls draft={draft} page={page} change={change} select={selectPage} lang={lang}/>}
      <div className={`de-workspace ${isometric ? "de-isometric" : ""} ${inspector ? "" : "de-no-inspector"} ${paletteOpen ? "" : "de-no-palette"}`}>
        {!isometric && <div className={`de-palette ${paletteOpen ? "" : "de-collapsed"}`}><h3>{l.nodes}</h3>{["box", "round", "diamond", "pill", "cylinder"].map(shape => <button className="btn" key={shape} disabled={!editableGraph} onClick={() => add(shape)}>{l[shape]}</button>)}<hr/>{["select", "connect", "pan"].map(value => <button className={`btn ${tool === value ? "btn-active" : ""}`} key={value} aria-pressed={tool === value} onClick={() => { setTool(value); if (value === "connect") setSelection([]); }}>{l[value]}</button>)}<button className="btn" disabled={!editableGraph || pending || editorial} onClick={arrange}>{l.arrange}</button></div>}
        <div className="de-canvas-area">{!isometric && <div className="de-actions de-canvasbar"><button className="btn" aria-label="Zoom −" onClick={() => setZoom(v => Math.max(.2, v / 1.2))}>−</button><button className="btn" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}>{Math.round(zoom * 100)}%</button><button className="btn" aria-label="Zoom +" onClick={() => setZoom(v => Math.min(5, v * 1.2))}>+</button><button className="btn" onClick={fit}>{lang === "en" ? "Fit" : "Ajustar"}</button><select className="field" aria-label={l.mode} value={mode} onChange={e => setMode(e.target.value)}><option value="light">{l.light}</option><option value="dark">{l.dark}</option></select><span>{selection.length ? `${selection.length} ${l.selected}` : ""}</span></div>}
        {isometric ? <IsometricControls key={row.id} draft={draft} change={change} stateId={stateId} setStateId={setStateId} partId={partId} setPartId={setPartId} mode={mode} setMode={setMode} lang={lang} inspector={inspector} error={setError}/> : editableGraph ? <svg ref={svgRef} className="de-canvas" style={{ background: colours.paper }} viewBox={`${pan.x} ${pan.y} ${width / zoom} ${height / zoom}`} tabIndex="0" role="application" aria-label={l.title} onPointerMove={pointerMove} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onPointerDown={e => { if (tool === "pan" || e.button === 1) { drag.current = { pan, client: { x: e.clientX, y: e.clientY } }; e.currentTarget.setPointerCapture(e.pointerId); } else { setSelection([]); setEdgeId(null); } }} onKeyDown={e => { if (e.key === "Escape") { setTool("select"); setSelection([]); setEdgeId(null); } const step = e.shiftKey ? 10 : 1; if (e.key.startsWith("Arrow")) { e.preventDefault(); moveSelection(e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0, e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0); } if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); remove(); } }}>
          <defs><marker id="de-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill={colours.accent}/></marker></defs>
          {page && <rect x="0" y="0" width={page.width} height={page.height} fill={colours.paper} stroke={colours.border}/>}
          {(draft.diagram.groups || []).map(group => { const members = visibleNodes.filter(n => n.group === group.id).map(n => boxes[n.id]); if (!members.length) return null; const x = Math.min(...members.map(b => b.x)) - 18, y = Math.min(...members.map(b => b.y)) - 38, w = Math.max(...members.map(b => b.x + b.width)) - x + 18, h = Math.max(...members.map(b => b.y + b.height)) - y + 18; return <g key={group.id}><rect x={x} y={y} width={w} height={h} rx="8" fill="none" stroke={colours.border} strokeDasharray="6 4"/><text x={x + 10} y={y + 17} fill={colours.ink} fontSize="13">{group.label}</text></g>; })}
          {visibleEdges.map(edge => { const points = connector(edge, boxes, draft.view.edges[edge.id], draft.diagram.edges), path = "M" + points.map(p => p.join(",")).join(" L"), middle = points[Math.floor(points.length / 2)]; return <g key={edge.id} role="button" tabIndex="0" aria-label={`${edge.label || "Conexión"}: ${edge.from} → ${edge.to}`} onPointerDown={e => { e.stopPropagation(); setEdgeId(edge.id); setSelection([]); }} onKeyDown={e => { if (e.key === "Enter") { setEdgeId(edge.id); setSelection([]); } }}><path d={path} fill="none" stroke="transparent" strokeWidth="18"/><path d={path} fill="none" stroke={edgeId === edge.id ? "#c46b18" : colours.accent} strokeWidth={edgeId === edge.id ? 3 : 1.6} strokeDasharray={edge.style === "dashed" ? "6 4" : undefined} markerEnd="url(#de-arrow)"/>{middle && edge.label && <text x={middle[0] + 5} y={middle[1] - 8} fill={colours.muted} fontSize="12" paintOrder="stroke" stroke={colours.paper} strokeWidth="4">{edge.label}</text>}</g>; })}
          {visibleNodes.map(node => { const b = boxes[node.id], size = b.font_size || 13, selected = selection.includes(node.id), fill = b.fill || colours.surface, stroke = selected ? colours.accent : b.stroke || colours.border; const lines = node.label.split("\n").flatMap(line => line.match(new RegExp(`.{1,${Math.max(4, Math.floor((b.width - 25) / (size * .577)))}}(?:\\s|$)|.{1,${Math.max(4, Math.floor((b.width - 25) / (size * .577)))}}`, "gu")) || [line]); return <g key={node.id} data-editor-node={node.id} tabIndex="0" role="button" aria-label={node.label || node.id} aria-pressed={selected} onPointerDown={e => pointerDown(e, node.id)} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); activateNode(node.id, e.shiftKey); } }} onDoubleClick={() => document.getElementById("de-node-label")?.focus()}>
            {node.shape === "diamond" ? <polygon points={`${b.x + b.width / 2},${b.y} ${b.x + b.width},${b.y + b.height / 2} ${b.x + b.width / 2},${b.y + b.height} ${b.x},${b.y + b.height / 2}`} fill={b.border===false ? "transparent" : fill} stroke={b.border===false && !selected ? "none" : stroke} strokeWidth={selected ? 2.6 : 1.4}/> : <rect x={b.x} y={b.y} width={b.width} height={b.height} rx={node.shape === "pill" ? b.height / 2 : node.shape === "round" ? 12 : 5} fill={b.border===false ? "transparent" : fill} stroke={b.border===false && !selected ? "none" : stroke} strokeWidth={selected ? 2.6 : 1.4}/>}
            {node.shape === "cylinder" && b.border!==false && <ellipse cx={b.x + b.width / 2} cy={b.y + 8} rx={b.width / 2} ry="7" fill="none" stroke={stroke}/>}{b.asset_id && draft.view.assets?.[b.asset_id] && <image x={b.x} y={b.y} width={b.width} height={b.height} href={draft.view.assets[b.asset_id].data} preserveAspectRatio="xMidYMid meet" pointerEvents="none"/>}<text x={b.align==="left"?b.x+12:b.align==="right"?b.x+b.width-12:b.x+b.width/2} y={b.y+b.height/2-(lines.length-1)*size*1.3/2} textAnchor={b.align==="left"?"start":b.align==="right"?"end":"middle"} dominantBaseline="central" fill={b.ink || colours.ink} fontSize={size} fontWeight={b.font_weight||500} pointerEvents="none">{b.show_label!==false && lines.map((line,i)=><tspan key={i} x={b.align==="left"?b.x+12:b.align==="right"?b.x+b.width-12:b.x+b.width/2} dy={i?size*1.3:0}>{line}</tspan>)}</text>{b.pinned && <path d={`M${b.x + b.width - 15},${b.y + 7}v10m-4-7h8`} stroke={colours.ink}/>}{selected && <rect x={b.x + b.width - 5} y={b.y + b.height - 5} width="10" height="10" fill={colours.accent} style={{ cursor: "nwse-resize" }} aria-label={lang === "en" ? "Resize shape" : "Redimensionar forma"} onPointerDown={e => { e.preventDefault(); e.stopPropagation(); localUndo.current.push(clone(draftRef.current)); localRedo.current = []; drag.current = { resize: node.id, box: b, start: point(e) }; svgRef.current.setPointerCapture(e.pointerId); }}/>}</g>; })}
          {!visibleNodes.length && <text x="55" y="75" fill={colours.muted} fontSize="18">{l.emptyCanvas}</text>}
        </svg> : <img className="de-special-preview" src={api.diagramDocumentExport(row.id, "svg", row.revision, mode)} alt={draft.diagram.title || draft.diagram.type}/>}
        {!isometric && <p className="de-canvas-help">{tool === "connect" ? l.connectHint : l.hint}</p>}</div>
        {inspector && !isometric && <aside className="de-inspector" aria-label={lang === "en" ? "Selection properties" : "Propiedades de la selección"}>{chosen ? <><label>{l.text}<textarea id="de-node-label" className="field" rows="3" value={chosen.label} onChange={e => updateNode("label", e.target.value)}/></label><label>{l.shape}<select className="field" value={chosen.shape || "box"} onChange={e => updateNode("shape", e.target.value)}>{["box", "round", "diamond", "pill", "cylinder"].map(k => <option key={k} value={k}>{l[k]}</option>)}</select></label><div className="de-geometry">{["x", "y", "width", "height"].map(key => <label key={key}>{l[key] || key.toUpperCase()}<input className="field" type="number" min={key === "width" || key === "height" ? 24 : 0} aria-label={l[key] || key.toUpperCase()} value={Math.round(boxes[chosen.id][key])} onChange={e => updateBox(key, Math.max(key === "width" || key === "height" ? 24 : 0, Number(e.target.value)))}/></label>)}</div><label className="de-check"><input type="checkbox" checked={!!boxes[chosen.id].pinned} onChange={e => updateBox("pinned", e.target.checked)}/>{l.pin}</label><label>{l.fill}<input type="color" aria-label={l.fill} value={boxes[chosen.id].fill || colours.surface} onChange={e => updateBox("fill", e.target.value)}/></label>{editorial && <TextControls box={boxes[chosen.id]} update={updateBox} draft={draft} change={change} chosen={chosen} lang={lang} error={setError}/>}<label>{l.details}<textarea className="field" rows="4" value={chosen.details || ""} onChange={e => updateNode("details", e.target.value)}/></label></> : edge ? <><label>{l.text}<input className="field" value={edge.label} onChange={e => updateEdge("label", e.target.value)}/></label>{["from", "to"].map(key => <label key={key}>{key === "from" ? l.next : l.target}<select className="field" value={edge[key]} onChange={e => updateEdge(key, e.target.value)}>{draft.diagram.nodes.map(n => <option key={n.id} value={n.id}>{n.label}</option>)}</select></label>)}<label>{l.style}<select className="field" value={edge.style} onChange={e => updateEdge("style", e.target.value)}><option value="solid">{l.solid}</option><option value="dashed">{l.dashed}</option></select></label>{["source_port", "target_port"].map(key => <label key={key}>{l.port} · {key === "source_port" ? l.next : l.target}<select className="field" value={draft.view.edges[edge.id]?.[key] || "auto"} onChange={e => change(next => { next.view.edges[edge.id] = { ...next.view.edges[edge.id], [key]: e.target.value }; })}>{["auto", "top", "right", "bottom", "left"].map(k => <option key={k} value={k}>{l[k]}</option>)}</select></label>)}</> : <p className="help">{l.noSelection}</p>}
          {chosen && <StyleControls key={row.id} box={boxes[chosen.id]} colours={colours} selection={selection} change={change} lang={lang} error={setError}/>}
          <div className="de-selection-actions"><button className="btn" disabled={!selection.length} onClick={duplicate}>{l.duplicate}</button><button className="btn" disabled={selection.length < 2} onClick={() => align("x")}>{l.left}</button><button className="btn" disabled={selection.length < 2} onClick={() => align("y")}>{l.top}</button><button className="btn" disabled={selection.length < 2} onClick={group}>{l.group}</button><button className="btn" disabled={!selection.length} onClick={() => change(next => { for (const n of next.diagram.nodes) if (selection.includes(n.id)) n.group = ""; })}>{l.ungroup}</button><button className="btn" disabled={!selection.length && !edgeId} onClick={remove}>{l.remove}</button></div></aside>}
      </div>
      {editorial && !dirty && row.rendering.gates.some(g=>!g.ok) && <p role="status" className="help">{lang==="en"?"Some blocks exceed page or text bounds. Resize or move them before publishing.":"Hay bloques fuera de página o con texto que no cabe. Amplíalos o muévelos antes de publicar."}</p>}
      <div className="de-actions de-exports"><span>{dirty ? (lang === "en" ? "Save and export" : "Guardar y exportar") : l.export}:</span><a className="btn" href={stateUrl(api.diagramDocumentExport(row.id, "vfigure", row.revision, mode, page?.id || ""))} onClick={e => output(e, "vfigure")} download>{lang === "en" ? "Figure with source" : "Figura con fuente"}</a>{["svg", "png", "pdf", "drawio", "mmd", "html"].map(format => <a key={format} className="btn" href={stateUrl(api.diagramDocumentExport(row.id, format, row.revision, mode))} onClick={e => output(e, format)} download>{format.toUpperCase()}</a>)}<a className="btn" href={api.diagramDocumentSource(row.id, row.revision)} onClick={e => output(e, "source")} download>{l.source}</a><a className="btn" href={stateUrl(api.diagramDocumentViewer(row.id, row.revision))} onClick={e => output(e, "viewer")} target="_blank" rel="noreferrer">{l.reader}</a><button className="btn" onClick={async () => { try { setHistory((await api.diagramDocumentHistory(row.id)).revisions); } catch (e) { setError(e.message); } }}>{l.history}</button></div>
      {history.length > 0 && <div className="de-history">{history.map(item => <div key={item.revision}><span>{l.revision} {item.revision} · {item.reason}</span><button className="btn" onClick={async () => { try { setComparison(await api.diagramDocumentCompare(row.id, item.revision)); } catch (e) { setError(e.message); } }}>{l.compare}</button></div>)}</div>}
      {comparison && <div className="de-comparison" role="status"><strong>{l.result}: {comparison.before_revision} → {comparison.after_revision}</strong>{Object.entries(comparison.changes).map(([kind, changes]) => <p key={kind}>{kind}: +{changes.added.length} / −{changes.removed.length} / {changes.changed.length} · {[...changes.added, ...changes.removed, ...changes.changed.map(v => v.id)].join(", ")}</p>)}</div>}
    </>}
  </section>;
}
