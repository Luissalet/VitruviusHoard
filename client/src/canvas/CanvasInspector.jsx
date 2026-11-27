import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
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
                  title={item.text || item.tag}
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
  const [undoing, setUndoing] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);
  const focusAfterUndo = useRef(false);
  const heading = useRef(null);
  const history = project.history || [];
  const recorded = new Set(history.map((entry) => entry.revision));
  const entries = [
    ...project.revisions.filter((revision) => !recorded.has(revision)).map((revision) => ({ revision })),
    ...history,
  ].reverse();
  const recentCount = 2;
  const visibleEntries = showAll ? entries : entries.slice(0, recentCount);
  const last = history.at(-1);
  const currentIndex = entries.findIndex((entry) => entry.revision === project.revision);
  const legacy = !last || last.action === "legacy";
  const savedIndex = project.revisions.indexOf(project.revision);
  const undoTarget = legacy && savedIndex > 0 ? project.revisions[savedIndex - 1] : last?.undo_revision;
  const authorLabel = ({ author }) => {
    if (author?.kind === "person") return es ? "Persona" : "Person";
    if (author?.kind === "agent") return author.name || (author.id !== "agent" && author.id) || (es ? "Agente" : "Agent");
    return es ? "Autor sin registrar" : "Author unrecorded";
  };
  const revisionLabel = (revision) => (es ? "Versión " : "Revision ") + (project.revisions.indexOf(revision) + 1);
  const labels = es ? { create: "Creación", edit: "Edición", undo: "Deshacer", "undo-change": "Paso deshecho", legacy: "Guardada" }
    : { create: "Created", edit: "Edited", undo: "Undo", "undo-change": "Step undone", legacy: "Saved" };
  const date = new Intl.DateTimeFormat(es ? "es-ES" : "en-GB", { dateStyle: "short", timeStyle: "short" });

  useEffect(() => {
    if (!focusAfterUndo.current || undoing) return;
    focusAfterUndo.current = false;
    if (document.activeElement === document.body) heading.current?.focus({ preventScroll: true });
  }, [undoing, undoTarget]);

  const undo = async (step) => {
    setUndoing(true); setError(false); setMessage("");
    focusAfterUndo.current = heading.current?.parentElement?.contains(document.activeElement);
    try {
      const expected = { expected_revision: project.revision, expected_updated_ts: project.updated_ts };
      const updated = step
        ? await api.appProjectUndoChange(project.id, { ...expected, change_id: step.id })
        : await api.appProjectUndo(project.id, { ...expected, revision: undoTarget });
      onChange(updated);
      if (updated.already_undone) setMessage(es ? "El paso ya estaba deshecho." : "The step was already undone.");
      else if (!step && legacy) setMessage(es ? "Versión restaurada." : "Revision restored.");
      else setMessage(es ? "Cambio deshecho." : "Change undone.");
    } catch (error) {
      setError(true);
      const overlap = error.message.startsWith("Later changes overlap:");
      setMessage(overlap
        ? (es ? "Hay ediciones posteriores en los mismos archivos. El paso se conserva." : "Later edits touch the same files. The step was kept.")
        : (es ? "No se pudo deshacer. Comprueba la versión actual e inténtalo de nuevo." : "Could not undo. Check the current revision and try again."));
      onChange();
    } finally {
      setUndoing(false);
    }
  };

  return <section className="canvas-inspector-section" aria-labelledby="canvas-history-title">
    <h2 className="canvas-inspector-heading" id="canvas-history-title" ref={heading} tabIndex={-1}>
      {es ? "Historial" : "History"}
      {entries.length > 0 && <span className="canvas-count">{entries.length}</span>}
    </h2>
    {entries.length ? <ol className="canvas-history-list" id="canvas-history-entries">
      {visibleEntries.map((entry, index) => <li key={entry.id || `${entry.revision}-${entry.ts || "legacy"}`}>
        <div className="canvas-history-line">
          <strong>{revisionLabel(entry.revision)}</strong>
          {index === currentIndex && <span className="chip chip-accent">{entry.revision === visibleRevision ? (es ? "Actual" : "Current") : (es ? "Guardada" : "Saved")}</span>}
        </div>
        <div className="canvas-history-meta">
          <span>{labels[entry.action || "legacy"]} · {authorLabel(entry)}</span>
          {entry.ts && <time dateTime={new Date(entry.ts * 1000).toISOString()}>{date.format(entry.ts * 1000)}</time>}
        </div>
        {(entry.target || entry.files?.length > 0) && <p className="canvas-step-target" title={entry.files?.join(", ")}>
          <code>{entry.target || entry.files[0]}</code>
          {!entry.target && entry.files.length > 1 && <span> +{entry.files.length - 1}</span>}
        </p>}
        <CanvasMaterials examples={entry.examples} tokensId={entry.tokens_id} />
        {entry.action === "edit" && entry.id && <button type="button" className="btn-link canvas-step-undo"
          aria-disabled={undoing} aria-label={`${es ? "Deshacer paso" : "Undo step"} · ${revisionLabel(entry.revision)}`}
          onClick={() => { if (!undoing) void undo(entry); }}>{es ? "Deshacer paso" : "Undo step"}</button>}
      </li>)}
    </ol> : <p className="canvas-empty">{es ? "Aún no hay revisiones." : "No revisions yet."}</p>}
    {entries.length > recentCount && <button type="button" className="btn-link canvas-history-more"
      aria-expanded={showAll} aria-controls="canvas-history-entries" onClick={() => setShowAll((value) => !value)}>
      {showAll ? (es ? "Mostrar solo los recientes" : "Show recent only")
        : (es ? "Ver el historial completo" : "Show full history")}
    </button>}
    {undoTarget && <button type="button" className="btn canvas-undo" aria-disabled={undoing}
      title={revisionLabel(undoTarget)} onClick={() => { if (!undoing) void undo(); }}>
      {undoing ? (es ? "Restaurando…" : "Restoring…")
        : legacy ? (es ? "Restaurar versión anterior" : "Restore previous revision")
        : (es ? "Deshacer último cambio" : "Undo last change")}
    </button>}
    {message && <p className="canvas-empty" role={error ? "alert" : "status"}>{message}</p>}
  </section>;
}
