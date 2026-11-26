import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useCopilotForm } from "../copilot-hooks.js";
import { anchorChanges, copilotComments, groupComments, pinsFor, sameComments, sourceLine, statusLabel, targetName } from "../preview-comments.js";

const POLL_MS = 2500;

/**
 * Pinned comments of the application preview, shown inside the bar of `PreviewSelection` (which owns the frame, the mode
 * buttons and the message listener). The inspector inside the preview paints the pins and reports the element a person
 * picked in Comment mode; this component writes the note, keeps the list (polled, so the agent's steps show up) and
 * says which comments lost their element. `register.current` is the handler `PreviewSelection` calls with each message.
 */
export default function PreviewComments({ projectId, running, revision, es, notify, send, register, ready }) {
  const [comments, setComments] = useState([]);
  const [draft, setDraft] = useState(null); // {element, page}
  const [note, setNote] = useState("");
  const [replies, setReplies] = useState({});
  const [focusId, setFocusId] = useState(null);
  const [page, setPage] = useState(null);
  const state = useRef({ comments, page });
  state.current = { comments, page };

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
      if (data.type === "dock/comment-target" && data.element) { setDraft({ element: data.element, page: data.page || "/" }); setNote(""); }
      else if (data.type === "dock/comment-anchors" && Array.isArray(data.anchors)) {
        const changed = anchorChanges(state.current.comments, data.anchors);
        if (changed.length && projectId) api.appProjectCommentAnchors(projectId, { anchors: changed, revision: revision.current }).then(load).catch(() => {});
      } else if (data.type === "dock/comment-focus") setFocusId(data.id);
    };
    return () => { register.current = null; };
  }, [projectId]);

  useEffect(() => {
    if (!focusId) return;
    document.getElementById(`preview-comment-${focusId}`)?.scrollIntoView?.({ block: "nearest" });
  }, [focusId, comments]);

  const open = comments.filter((comment) => ["pending", "seen", "answered"].includes(comment.status));
  useCopilotForm("app-preview-comments", { objectId: projectId, initial: { comments: [] }, current: { comments: copilotComments(open) } });

  const step = (comment, name, body) => api.appProjectCommentStep(projectId, comment.id, name, body)
    .then(() => { setReplies((held) => ({ ...held, [comment.id]: "" })); return load(); }).catch((error) => notify(error.message));
  const cancelDraft = () => { setDraft(null); setNote(""); send("inspect/draft-clear"); };
  const save = () => {
    if (!draft || !note.trim()) return;
    api.appProjectCommentAdd(projectId, { note: note.trim(), revision: revision.current, page: draft.page, element: draft.element })
      .then(() => { cancelDraft(); return load(); }).catch((error) => notify(error.message));
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
