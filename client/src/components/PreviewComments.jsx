import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { anchorChanges, copilotComments, groupComments, pinsFor, sameComments, sourceLine, statusLabel, targetName } from "../preview-comments.js";

const POLL_MS = 2500;

/**
 * Pinned comments of the application preview, shown inside the bar of `PreviewSelection` (which owns the frame, the mode
 * buttons and the message listener). The inspector inside the preview paints the pins and reports the element a person
 * picked in Comment mode; this component writes the note, keeps the list (polled, so the agent's steps show up) and
 * says which comments lost their element. `register.current` is the handler `PreviewSelection` calls with each message;
 * `served.current` is the revision the page says it serves (`previewRevision.current`, the one the preview was started on,
 * stands in for a page that does not say), `onContext` receives what the copilot sees of the open comments.
 * A draft keeps the revision its element was picked on: if the page moved on, it is dropped, never saved as the newer one.
 */
export default function PreviewComments({ projectId, running, served, previewRevision, es, notify, send, register, ready, onContext }) {
  const [comments, setComments] = useState([]);
  const [draft, setDraft] = useState(null); // {element, page}
  const [note, setNote] = useState("");
  const [replies, setReplies] = useState({});
  const [focusId, setFocusId] = useState(null);
  const [page, setPage] = useState(null);
  const state = useRef({ comments, page, draft });
  state.current = { comments, page, draft };
  const now = () => served.current || previewRevision.current || null;

  const apply = (list) => setComments((held) => (sameComments(held, list) ? held : list));
  const load = () => projectId && api.appProjectComments(projectId).then((data) => apply(data.comments)).catch(() => {});

  useEffect(() => {
    setComments([]); setDraft(null); setNote(""); setReplies({}); setFocusId(null); setPage(null);
    if (!running || !projectId) return undefined;
    load();
    const timer = setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
    return () => clearInterval(timer);
  }, [running, projectId]);

  // The preview paints pins from this list: again after a new page, a reload of the preview, or any change.
  useEffect(() => {
    if (running && page !== null) send("inspect/pins", { pins: pinsFor(comments, page) });
  }, [comments, page, running, ready]);

  useEffect(() => {
    register.current = (data) => {
      if (typeof data.page === "string") setPage(data.page);
      const held = state.current.draft;
      if (held && data.type !== "dock/comment-target" && now() && now() !== held.revision) dropDraft(true);
      if (data.type === "dock/comment-target" && data.element) { setDraft({ element: data.element, page: data.page || "/", revision: data.revision || previewRevision.current || null, crop: data.crop || null, attrs: data.attrs || {} }); setNote(""); }
      else if (data.type === "dock/comment-anchors" && Array.isArray(data.anchors)) {
        // The report names the revision the page itself serves; the server refuses one the preview no longer serves.
        const reported = data.revision || previewRevision.current;
        const changed = anchorChanges(state.current.comments, data.anchors, reported);
        if (changed.length && projectId && reported) api.appProjectCommentAnchors(projectId, { anchors: changed, revision: reported, session: data.session || undefined }).then(load).catch(() => {});
      } else if (data.type === "dock/comment-focus") setFocusId(data.id);
    };
    return () => { register.current = null; };
  }, [projectId]);

  useEffect(() => {
    if (!focusId) return;
    document.getElementById(`preview-comment-${focusId}`)?.scrollIntoView?.({ block: "nearest" });
  }, [focusId, comments]);

  useEffect(() => { onContext(copilotComments(comments)); }, [comments]);

  const step = (comment, name, body) => api.appProjectCommentStep(projectId, comment.id, name, body)
    .then(() => { setReplies((held) => ({ ...held, [comment.id]: "" })); return load(); }).catch((error) => notify(error.message));
  const cancelDraft = () => { setDraft(null); setNote(""); send("inspect/draft-clear"); };
  const dropDraft = (moved) => { if (moved) notify(es ? "La vista previa cambió de versión: elige el elemento otra vez." : "The preview moved to another revision: pick the element again."); cancelDraft(); };
  const save = () => {
    if (!draft || !note.trim()) return;
    if (!draft.revision || draft.revision !== now()) { dropDraft(true); return; }
    api.appProjectCommentAdd(projectId, { note: note.trim(), revision: draft.revision, page: draft.page, element: draft.element, crop: draft.crop || undefined, attrs: draft.attrs })
      .then(() => { cancelDraft(); return load(); }).catch((error) => { notify(error.message); if (error.status === 409) cancelDraft(); });
  };

  const { anchored, lost, closed } = groupComments(comments);
  if (!running) return null;

  const item = (comment) => <li key={comment.id} id={`preview-comment-${comment.id}`} className={`panel flex flex-col gap-1 ${focusId === comment.id ? "ring-2" : ""}`} style={{ padding: 10 }}>
    <div className="flex gap-2 items-center flex-wrap">
      <strong>#{comment.n}</strong>
      <span className={`chip ${comment.status === "resolved" ? "chip-ok" : comment.status === "dismissed" ? "" : comment.status === "answered" ? "chip-accent" : "chip-amber"}`}>{statusLabel(comment.status, es)}</span>
      <span className="help">{targetName(comment)} · {sourceLine(comment, es)}</span>
      {comment.stale && <span className="chip chip-wrap" title={comment.revision}>{es ? "hecho en una versión anterior" : "made on an earlier revision"}</span>}
    </div>
    <p>{comment.note}</p>
    {comment.has_crop && <img src={`/design/api/app-projects/${projectId}/comments/${comment.id}/crop`} alt={es ? `Recorte de ${targetName(comment)} cuando se comentó` : `Crop of ${targetName(comment)} when it was commented`} style={{ maxWidth: 240, maxHeight: 120, objectFit: "contain", alignSelf: "flex-start", border: "1px solid var(--line)", background: "white" }} />}
    {comment.status === "resolved" && comment.summary && <p className="help"><strong>{es ? "Qué cambió: " : "What changed: "}</strong>{comment.summary}</p>}
    {comment.status === "answered" && comment.reply && <p className="help"><strong>{es ? "El agente dice: " : "The agent says: "}</strong>{comment.reply}</p>}
    {comment.status === "dismissed" && comment.history.at(-1)?.text && <p className="help"><strong>{es ? "Motivo: " : "Reason: "}</strong>{comment.history.at(-1).text}</p>}
    {comment.status === "answered" && <label className="label">{es ? "Tu respuesta" : "Your reply"}
      <textarea className="field" rows={2} value={replies[comment.id] || ""} onChange={(event) => setReplies((held) => ({ ...held, [comment.id]: event.target.value }))} />
    </label>}
    <div className="flex gap-2 flex-wrap">
      {comment.status === "answered" && <button type="button" className="btn" disabled={!(replies[comment.id] || "").trim()} onClick={() => step(comment, "respond", { text: replies[comment.id] })}>{es ? "Responder" : "Reply"}</button>}
      {!lost.includes(comment) && <button type="button" className="btn" onClick={() => { setFocusId(comment.id); send("inspect/pin-focus", { id: comment.id }); }}>{es ? "Ver en la vista previa" : "Show on the preview"}</button>}
      {["pending", "seen", "answered"].includes(comment.status) && <button type="button" className="btn" onClick={() => step(comment, "dismiss", { text: "" })}>{es ? "Descartar" : "Dismiss"}</button>}
      {["resolved", "dismissed"].includes(comment.status) && <button type="button" className="btn" onClick={() => step(comment, "reopen", {})}>{es ? "Reabrir" : "Reopen"}</button>}
      {comment.history.length > 1 && <button type="button" className="btn" onClick={() => step(comment, "undo", {})}>{es ? "Deshacer el último paso" : "Undo the last step"}</button>}
    </div>
  </li>;

  return <div className="flex flex-col gap-3" aria-label={es ? "Comentarios en la vista previa" : "Preview comments"}>
    {draft && <form className="panel flex flex-col gap-2" style={{ padding: 10 }} onSubmit={(event) => { event.preventDefault(); save(); }}>
      <strong>{es ? "Comentario sobre " : "Comment on "}{targetName(draft.element)}</strong>
      <span className="help">{draft.element.vsrc || (es ? "sin posición en el fuente" : "no source position")}</span>
      {draft.crop && <img src={draft.crop} alt={es ? "Recorte del elemento" : "Crop of the element"} style={{ maxWidth: 240, maxHeight: 120, objectFit: "contain", alignSelf: "flex-start", border: "1px solid var(--line)", background: "white" }} />}
      <label className="label">{es ? "Nota para el agente" : "Note for the agent"}
        <textarea className="field" rows={3} autoFocus value={note} onChange={(event) => setNote(event.target.value)} />
      </label>
      <div className="flex gap-2"><button type="submit" className="btn btn-primary" disabled={!note.trim()}>{es ? "Guardar comentario" : "Save comment"}</button><button type="button" className="btn" onClick={cancelDraft}>{es ? "Cancelar" : "Cancel"}</button></div>
    </form>}
    {anchored.length > 0 && <div><h4 className="font-semibold">{es ? "Comentarios abiertos" : "Open comments"} ({anchored.length})</h4><ul className="flex flex-col gap-2 mt-2">{anchored.map(item)}</ul></div>}
    {lost.length > 0 && <div><h4 className="font-semibold">{es ? "Sin ancla" : "Without anchor"} ({lost.length})</h4>
      <p className="help">{es ? "El elemento ya no está en esta versión de la página. El comentario se conserva." : "The element is no longer in this revision of the page. The comment is kept."}</p>
      <ul className="flex flex-col gap-2 mt-2">{lost.map(item)}</ul></div>}
    {closed.length > 0 && <details><summary className="font-semibold">{es ? "Cerrados" : "Closed"} ({closed.length})</summary><ul className="flex flex-col gap-2 mt-2">{closed.map(item)}</ul></details>}
  </div>;
}
