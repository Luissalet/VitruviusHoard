import React, { useEffect, useRef, useState } from "react";
import { canvasHistoryEntries, canvasRevisionLabel, partitionLegacyHistory } from "./canvasPanel.js";
import { api } from "../api.js";
import { chipText } from "../preview-selection.js";
import PreviewTargetDetails from "../components/PreviewTargetDetails.jsx";
import { CanvasMaterials } from "./CanvasActivity.jsx";

export function CanvasElements({ elements, onSelect, onRetry, es }) {
  const items = elements?.items || [];
  const [focused, setFocused] = useState(null);
  const tabStop = items.some((item) => item.id === focused) ? focused : items[0]?.id;
  const moveLayerFocus = (event) => {
    const buttons = Array.from(event.currentTarget.querySelectorAll("button"));
    const current = buttons.indexOf(document.activeElement);
    let next;
    if (event.key === "ArrowDown") next = Math.min(current + 1, buttons.length - 1);
    if (event.key === "ArrowUp") next = Math.max(current - 1, 0);
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = buttons.length - 1;
    if (next !== undefined) { event.preventDefault(); buttons[next]?.focus(); }
  };
  return <section className="canvas-inspector-section" aria-labelledby="canvas-elements-title">
    <h2 className="canvas-inspector-heading" id="canvas-elements-title" tabIndex={-1}>
      {es ? "Elementos" : "Elements"}
      {!!elements?.total && <span className="canvas-count">{elements.total}</span>}
    </h2>
    {elements?.error
      ? <p className="canvas-empty" role="status">{es ? "No se pudieron leer los elementos." : "Could not read page elements."} <button type="button" className="btn-link" onClick={onRetry}>{es ? "Reintentar" : "Retry"}</button></p>
      : !elements
        ? <p className="canvas-empty" role="status">{es ? "Leyendo la página…" : "Reading the page…"}</p>
        : !items.length
          ? <p className="canvas-empty">{es ? "Esta página no tiene elementos seleccionables." : "This page has no selectable elements."}</p>
          : <>
            <ul className="canvas-layer-list" onKeyDown={moveLayerFocus}>
              {items.map((item) => <li key={item.id}>
                <button type="button" aria-pressed={item.selected} tabIndex={item.id === tabStop ? 0 : -1}
                  onFocus={() => setFocused(item.id)}
                  style={{ paddingInlineStart: 9 + Math.min(item.depth, 5) * 10 }}
                  title={item.text ? `${item.tag} · ${item.text}` : item.tag}
                  onClick={(event) => onSelect(item.id, event.shiftKey)}>
                  <code aria-hidden={Boolean(item.text)}>{item.tag}</code>
                  {item.text && <span>{item.text}</span>}
                </button>
              </li>)}
            </ul>
            {items.length < elements.total && <p className="canvas-empty">{es ? `Primeros ${items.length} elementos.` : `First ${items.length} elements.`}</p>}
          </>}
  </section>;
}

export function CanvasHistory({ project, visibleRevision, onChange, es }) {
  const [pending, setPending] = useState(null);
  const savingHistory = Boolean(pending);
  const [showAll, setShowAll] = useState(false);
  const [undoResult, setUndoResult] = useState(null);
  const focusAfterUndo = useRef(false);
  const heading = useRef(null);
  const history = project.history || [];
  const entries = canvasHistoryEntries(project);
  const redoTarget = entries[0]?.redoRevision;
  const recentCount = 2;
  const { recordedEntries, previous } = partitionLegacyHistory(entries, project.revision);
  const visibleEntries = showAll ? recordedEntries : recordedEntries.slice(0, recentCount);
  const previousLabel = es
    ? `${previous.length} ${previous.length === 1 ? "versión anterior sin autor" : "versiones anteriores sin autor"}`
    : `${previous.length} earlier ${previous.length === 1 ? "revision" : "revisions"} without an author`;
  const last = history.at(-1);
  const currentIndex = recordedEntries.findIndex((entry) => entry.revision === project.revision);
  const previewIndex = recordedEntries.findIndex((entry) => entry.revision === visibleRevision);
  const legacy = !last || last.action === "legacy";
  const savedIndex = project.revisions.indexOf(project.revision);
  const undoTarget = legacy && savedIndex > 0 ? project.revisions[savedIndex - 1] : last?.undo_revision;
  const authorLabel = ({ author }) => {
    if (author?.kind === "person") return es ? "Persona" : "Person";
    if (author?.kind === "system") return es ? "Sistema" : "System";
    if (author?.kind === "agent") return author.name || (author.id !== "agent" && author.id) || (es ? "Agente" : "Agent");
    return es ? "Autor sin registrar" : "Author unrecorded";
  };
  const revisionLabel = (revision) => canvasRevisionLabel(project.revisions, revision, es);
  const stepLabel = (step) => (es ? "Paso " : "Step ") + step;
  const labels = es ? { create: "Creación", edit: "Edición", undo: "Deshacer", redo: "Rehacer", "undo-change": "Paso deshecho", "critique-restore": "Mejor versión restaurada", "critique-undo": "Ronda deshecha", legacy: "Guardada" }
    : { create: "Created", edit: "Edited", undo: "Undo", redo: "Redo", "undo-change": "Step undone", "critique-restore": "Best revision restored", "critique-undo": "Round undone", legacy: "Saved" };
  const date = new Intl.DateTimeFormat(es ? "es-ES" : "en-GB", { dateStyle: "short", timeStyle: "short" });
  const undoMessages = es ? {
    alreadyUndone: "El paso ya estaba deshecho.",
    restored: "Versión restaurada.",
    undone: "Cambio deshecho.",
    redone: "Cambio rehecho.",
    redoFailed: "No se pudo rehacer. Comprueba la versión actual e inténtalo de nuevo.",
    conflict: "Hay ediciones posteriores en los mismos archivos. El paso se conserva.",
    failed: "No se pudo deshacer. Comprueba la versión actual e inténtalo de nuevo.",
  } : {
    alreadyUndone: "The step was already undone.",
    restored: "Revision restored.",
    undone: "Change undone.",
    redone: "Change redone.",
    redoFailed: "Could not redo. Check the current revision and try again.",
    conflict: "Later edits touch the same files. The step was kept.",
    failed: "Could not undo. Check the current revision and try again.",
  };

  useEffect(() => {
    if (!focusAfterUndo.current || savingHistory) return;
    focusAfterUndo.current = false;
    if (document.activeElement === document.body) heading.current?.focus({ preventScroll: true });
  }, [savingHistory, undoTarget, redoTarget]);

  const changeHistory = async (operation, step) => {
    setPending(operation); setUndoResult(null);
    focusAfterUndo.current = heading.current?.parentElement?.contains(document.activeElement);
    try {
      const expected = { expected_revision: project.revision, expected_updated_ts: project.updated_ts };
      const target = operation === "redo" ? redoTarget : undoTarget;
      const updated = step
        ? await api.appProjectUndoChange(project.id, { ...expected, change_id: step.id })
        : await api.appProjectUndo(project.id, { ...expected, revision: target });
      onChange(updated);
      if (operation === "redo") setUndoResult("redone");
      else if (updated.already_undone) setUndoResult("alreadyUndone");
      else if (!step && legacy) setUndoResult("restored");
      else setUndoResult("undone");
    } catch (error) {
      const failure = operation === "redo" ? "redoFailed"
        : error.message.startsWith("Later changes overlap:") ? "conflict" : "failed";
      setUndoResult(failure);
      onChange();
    } finally {
      setPending(null);
    }
  };

  return <section className="canvas-inspector-section" aria-labelledby="canvas-history-title">
    <h2 className="canvas-inspector-heading" id="canvas-history-title" ref={heading} tabIndex={-1}>
      {es ? "Historial" : "History"}
      {entries.length > 0 && <span className="canvas-count">{entries.length}</span>}
    </h2>
    {entries.length ? <ol className="canvas-history-list" id="canvas-history-entries">
      {visibleEntries.map((entry, index) => {
        const status = index === previewIndex ? (es ? "En pantalla" : "In preview")
          : index === currentIndex ? (es ? "Guardada" : "Saved") : null;
        const targetName = entry.target_presentation ? chipText(entry.target_presentation, es)
          : entry.target ? (es ? "Elemento editado" : "Edited element") : null;
        const count = entry.files?.length || 0;
        const filesLabel = count === 1 ? (es ? "1 fichero" : "1 file") : (es ? `${count} ficheros` : `${count} files`);
        return <li key={entry.id || `${entry.revision}-${entry.ts || "legacy"}`}>
          <div className="canvas-history-line">
            <strong>{stepLabel(entry.step)}</strong>
            {entry.undone && <span className="chip">{es ? "Deshecho" : "Undone"}</span>}
            <span className={status ? "chip chip-accent" : "help"}>
              {revisionLabel(entry.revision)}{status && ` · ${status}`}
            </span>
          </div>
          <div className="canvas-history-meta">
            <span>{labels[entry.action || "legacy"]} · {authorLabel(entry)}</span>
            {entry.ts && <time dateTime={new Date(entry.ts * 1000).toISOString()}>{date.format(entry.ts * 1000)}</time>}
          </div>
          {(targetName || count > 0) && <>
            <p className="canvas-step-target">{targetName}{count > 0 && <span>{targetName && " · "}{filesLabel}</span>}</p>
            <PreviewTargetDetails es={es} locator={entry.target} files={entry.files} />
          </>}
          <CanvasMaterials materials={entry.materials} es={es} />
          {entry.action === "edit" && entry.id && !entry.undone && <button type="button" className="btn-link canvas-step-undo"
            aria-disabled={savingHistory} aria-label={`${es ? "Deshacer" : "Undo"} · ${stepLabel(entry.step)}`}
            onClick={() => { if (!savingHistory) void changeHistory("undo", entry); }}>{es ? "Deshacer paso" : "Undo step"}</button>}
        </li>;
      })}
      {previous.length > 0 && <li>
        <details className="canvas-history-legacy">
          <summary>{previousLabel}</summary>
          <ol className="canvas-history-list">
            {previous.map((entry) => <li className="canvas-history-line" key={entry.id || entry.revision}>
              <span>{revisionLabel(entry.revision)}</span>
              {entry.ts && <time dateTime={new Date(entry.ts * 1000).toISOString()}>{date.format(entry.ts * 1000)}</time>}
            </li>)}
          </ol>
        </details>
      </li>}
    </ol> : <p className="canvas-empty">{es ? "Aún no hay revisiones." : "No revisions yet."}</p>}
    {recordedEntries.length > recentCount && <button type="button" className="btn-link canvas-history-more"
      aria-expanded={showAll} aria-controls="canvas-history-entries" onClick={() => setShowAll((value) => !value)}>
      {showAll ? (es ? "Mostrar solo los recientes" : "Show recent only")
        : (es ? "Ver el historial completo" : "Show full history")}
    </button>}
    {undoTarget && undoTarget !== redoTarget && <button type="button" className="btn canvas-undo" aria-disabled={savingHistory}
      title={revisionLabel(undoTarget)} onClick={() => { if (!savingHistory) void changeHistory("undo"); }}>
      {pending === "undo" ? (es ? "Restaurando…" : "Restoring…")
        : legacy ? (es ? "Restaurar versión anterior" : "Restore previous revision")
        : (es ? "Deshacer último cambio" : "Undo last change")}
    </button>}
    {redoTarget && <button type="button" className="btn canvas-undo" aria-disabled={savingHistory}
      onClick={() => { if (!savingHistory) void changeHistory("redo"); }}>
      {pending === "redo" ? (es ? "Rehaciendo…" : "Redoing…") : (es ? "Rehacer" : "Redo")}
    </button>}
    {undoResult && <p className="canvas-empty" role={["conflict", "failed", "redoFailed"].includes(undoResult) ? "alert" : "status"}>
      {undoMessages[undoResult]}
    </p>}
  </section>;
}
