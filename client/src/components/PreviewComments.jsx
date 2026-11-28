import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { anchorChanges, copilotComments, groupComments, isOpen, pinsFor, sameComments, statusLabel } from "../preview-comments.js";
import { chipText, sourceText } from "../preview-selection.js";
import PreviewTargetDetails from "./PreviewTargetDetails.jsx";

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
export default function PreviewComments({ projectId, running, served, previewRevision, es, notify, send, register, ready, onContext, onComments, canvas = false }) {
  const [comments, setComments] = useState([]);
  const [anchorReport, setAnchorReport] = useState(null);
  const [draft, setDraft] = useState(null); // {element, page}
  const [note, setNote] = useState("");
  const [replies, setReplies] = useState({});
  const [focusId, setFocusId] = useState(null);
  const [page, setPage] = useState(null);
  const [loadState, setLoadState] = useState("loading");
  const [working, setWorking] = useState(null);
  const pendingAnchor = useRef(null);
  const resolveFocus = useRef(null);
  const [saving, setSaving] = useState(false);
  const heading = useRef(null);
  const draftForm = useRef(null);
  const requests = useRef(0);
  const currentProject = useRef(projectId);
  currentProject.current = projectId;
  const state = useRef({ comments, page, draft });
  state.current = { comments, page, draft };
  const now = () => served.current || previewRevision.current || null;

  const apply = (list) => setComments((held) => (sameComments(held, list) ? held : list));
  const load = async () => {
    const request = ++requests.current;
    try {
      const data = await api.appProjectComments(projectId);
      if (currentProject.current !== projectId || request !== requests.current) return;
      apply(data.comments);
      setLoadState("ready");
    } catch {
      if (currentProject.current === projectId && request === requests.current) setLoadState("error");
    }
  };

  useEffect(() => {
    setComments([]); setAnchorReport(null); setDraft(null); setNote(""); setReplies({}); setFocusId(null); setPage(null);
    setLoadState("loading"); setWorking(null); setSaving(false); pendingAnchor.current = null;
    if (!running || !projectId) return undefined;
    load();
    const timer = setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
    return () => { clearInterval(timer); requests.current++; };
  }, [running, projectId]);

  // The preview paints pins from this list: again after a new page, a reload of the preview, or any change.
  useEffect(() => {
    if (running && page !== null) {
      send("inspect/pins", { pins: pinsFor(comments, page) });
      if (pendingAnchor.current?.page === page) {
        send("inspect/pin-focus", { id: pendingAnchor.current.id });
        pendingAnchor.current = null;
      }
    }
  }, [comments, page, running, ready]);

  useEffect(() => {
    register.current = (data) => {
      if (typeof data.page === "string") setPage(data.page);
      const held = state.current.draft;
      if (held && data.type !== "dock/comment-target" && now() && now() !== held.revision) dropDraft(true);
      if (data.type === "dock/comment-target" && data.element) {
        setFocusId(null);
        setDraft({ element: data.element, page: data.page || "/", revision: data.revision || previewRevision.current || null, crop: data.crop || null, attrs: data.attrs || {} });
        setNote("");
      }
      else if (data.type === "dock/comment-anchors" && Array.isArray(data.anchors)) {
        // The report names the revision the page itself serves; the server refuses one the preview no longer serves.
        const reported = data.revision || previewRevision.current;
        const texts = data.anchors.filter((anchor) => anchor?.state === "ok" && typeof anchor.text === "string");
        setAnchorReport({ page: data.page, revision: reported, texts: new Map(texts.map((anchor) => [anchor.id, anchor.text])) });
        const changed = anchorChanges(state.current.comments, data.anchors, reported);
        if (changed.length && projectId && reported) {
          const anchors = changed.map(({ id, state, vsrc, box }) => ({ id, state, vsrc, box }));
          api.appProjectCommentAnchors(projectId, { anchors, revision: reported, session: data.session || undefined }).then(load).catch(() => {});
        }
      } else if (data.type === "dock/comment-focus") {
        setFocusId(data.id);
        requestAnimationFrame(() => document.getElementById(`preview-comment-${data.id}`)?.focus());
      } else if (data.type === "dock/comment-jump" && !data.found) {
        notify(es ? "No se encontró el ancla en esta página." : "The anchor could not be located on this page.");
      }
    };
    return () => { register.current = null; };
  }, [projectId]);

  useLayoutEffect(() => {
    if (!draft) return;
    const form = draftForm.current;
    form?.elements.namedItem("note")?.focus({ preventScroll: true });
    form?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [draft]);

  useEffect(() => {
    if (!focusId) return;
    document.getElementById(`preview-comment-${focusId}`)?.scrollIntoView?.({ block: "nearest" });
  }, [focusId, comments]);

  useEffect(() => { onContext(copilotComments(comments)); onComments?.(comments); }, [comments]);

  const focusAnchor = (comment) => {
    setFocusId(comment.id);
    if (canvas && comment.page !== page) {
      pendingAnchor.current = comment;
      send("inspect/pin-navigate", { page: comment.page });
    } else send("inspect/pin-focus", { id: comment.id });
  };
  const step = async (comment, name, body) => {
    if (working) return;
    setWorking(comment.id);
    try {
      if (canvas && ["resolve", "dismiss"].includes(name) && document.activeElement?.closest("li")?.id === `preview-comment-${comment.id}`) {
        resolveFocus.current = comment.id;
      }
      const updated = await api.appProjectCommentStep(projectId, comment.id, name, body);
      if (currentProject.current !== projectId) return;
      requests.current++;
      setComments((held) => held.map((item) => item.id === comment.id ? updated : item));
      setReplies((held) => ({ ...held, [comment.id]: "" }));
      await load();
    } catch (error) {
      resolveFocus.current = null;
      if (currentProject.current === projectId) notify(error.message);
    } finally {
      if (currentProject.current === projectId) setWorking(null);
    }
  };
  useEffect(() => {
    if (resolveFocus.current && comments.some((item) => item.id === resolveFocus.current && !isOpen(item))) {
      resolveFocus.current = null;
      heading.current?.focus({ preventScroll: true });
    }
  }, [comments]);
  const cancelDraft = () => { setDraft(null); setNote(""); send("inspect/draft-clear"); };
  const dropDraft = (moved) => { if (moved) notify(es ? "La vista previa cambió de versión: elige el elemento otra vez." : "The preview moved to another revision: pick the element again."); cancelDraft(); };
  const save = async () => {
    if (saving || !draft || !note.trim()) return;
    if (!draft.revision || draft.revision !== now()) { dropDraft(true); return; }
    setSaving(true);
    try {
      await api.appProjectCommentAdd(projectId, { note: note.trim(), revision: draft.revision, page: draft.page, element: draft.element, crop: draft.crop || undefined, attrs: draft.attrs });
      if (currentProject.current !== projectId) return;
      cancelDraft();
      if (canvas) heading.current?.focus({ preventScroll: true });
      await load();
    } catch (error) {
      if (currentProject.current !== projectId) return;
      notify(error.message);
      if (error.status === 409) cancelDraft();
    } finally {
      if (currentProject.current === projectId) setSaving(false);
    }
  };

  const { anchored, lost, closed } = groupComments(comments);
  if (!running) return null;

  const visibleTexts = anchorReport && anchorReport.page === page && anchorReport.revision === now() ? anchorReport.texts : null;
  const item = (comment) => {
    const lastDecision = comment.history.findLast((entry) => entry.status !== "seen");
    const liveText = comment.page === page ? visibleTexts?.get(comment.id) : undefined;
    const quote = liveText ?? comment.element_text;
    const showOriginal = liveText !== undefined && liveText !== comment.element_text && (comment.element_text || comment.has_crop);
    const originalName = chipText({ ...comment, text: comment.element_text }, es);
    const originalCrop = comment.has_crop && <img className="preview-comment-crop" src={`/design/api/app-projects/${projectId}/comments/${comment.id}/crop`} alt={es ? `Recorte de ${originalName} cuando se comentó` : `Crop of ${originalName} when it was commented`} />;
    return <li key={comment.id} id={`preview-comment-${comment.id}`} tabIndex={-1} className={`panel flex flex-col gap-1 ${focusId === comment.id ? "ring-2" : ""}`} style={{ padding: 10 }}>
      <div className="flex gap-2 items-center flex-wrap">
        <strong>#{comment.n}</strong>
        <span className={`chip ${comment.status === "resolved" ? "chip-ok" : comment.status === "dismissed" ? "" : comment.status === "answered" ? "chip-accent" : "chip-amber"}`}>{statusLabel(comment.status, es)}</span>
        <span className="help">{chipText({ ...comment, text: quote }, es)}</span>
        {comment.stale && <span className="chip chip-wrap" title={comment.revision}>{es ? "hecho en una versión anterior" : "made on an earlier revision"}</span>}
      </div>
      <PreviewTargetDetails es={es} selector={comment.selector} source={sourceText(comment, es)} />
      <p>{comment.note}</p>
      {quote && <blockquote className="preview-comment-quote">{quote}</blockquote>}
      {showOriginal ? <details className="help">
        <summary>{es ? "Texto al comentar" : "Text when commented"}</summary>
        {comment.element_text && <blockquote>{comment.element_text}</blockquote>}
        {originalCrop}
      </details> : originalCrop}
      {comment.status === "resolved" && comment.summary && <p className="help"><strong>{es ? "Qué cambió: " : "What changed: "}</strong>{comment.summary}</p>}
      {lastDecision?.source_undo && <p className="help"><strong>{es ? "Cambio deshecho. Qué había cambiado: " : "Change undone. What had changed: "}</strong>{lastDecision.text}</p>}
      {comment.status === "answered" && comment.reply && <p className="help"><strong>{es ? "El agente dice: " : "The agent says: "}</strong>{comment.reply}</p>}
      {comment.status === "dismissed" && comment.history.at(-1)?.text && <p className="help"><strong>{es ? "Motivo: " : "Reason: "}</strong>{comment.history.at(-1).text}</p>}
      {comment.status === "answered" && <label className="label">{es ? "Tu respuesta" : "Your reply"}
        <textarea className="field preview-comment-text" rows={2} value={replies[comment.id] || ""} onChange={(event) => setReplies((held) => ({ ...held, [comment.id]: event.target.value }))} />
      </label>}
      <div className="flex gap-2 flex-wrap">
        {comment.status === "answered" && <button type="button" className="btn" disabled={!(replies[comment.id] || "").trim()} onClick={() => step(comment, "respond", { text: replies[comment.id] })}>{es ? "Responder" : "Reply"}</button>}
        {!lost.includes(comment) && <button type="button" className="btn" onClick={() => focusAnchor(comment)}>{canvas ? (es ? "Ir al ancla" : "Go to anchor") : (es ? "Ver en la vista previa" : "Show on the preview")}</button>}
        {canvas && isOpen(comment) && <button type="button" className="btn" aria-disabled={Boolean(working)} onClick={() => step(comment, "resolve", {})}>{working === comment.id ? (es ? "Guardando…" : "Saving…") : (es ? "Resolver" : "Resolve")}</button>}
        {["pending", "seen", "answered"].includes(comment.status) && <button type="button" className="btn" onClick={() => step(comment, "dismiss", { text: "" })}>{es ? "Descartar" : "Dismiss"}</button>}
        {["resolved", "dismissed"].includes(comment.status) && <button type="button" className="btn" onClick={() => step(comment, "reopen", {})}>{es ? "Reabrir" : "Reopen"}</button>}
        {comment.history.length > 1 && <button type="button" className="btn" onClick={() => step(comment, "undo", {})}>{es ? "Deshacer el último paso" : "Undo the last step"}</button>}
      </div>
    </li>;
  };

  const openCount = comments.filter(isOpen).length;
  return <div className={canvas ? "canvas-inspector-section flex flex-col gap-2" : "flex flex-col gap-3"} aria-label={es ? "Comentarios en la vista previa" : "Preview comments"}>
    {canvas && <h2 className="canvas-inspector-heading" tabIndex={-1} ref={heading}>{es ? "Comentarios" : "Comments"}{openCount > 0 && <span className="canvas-count">{openCount}</span>}</h2>}
    {canvas && loadState === "loading" && <p className="canvas-empty" role="status">{es ? "Cargando comentarios…" : "Loading comments…"}</p>}
    {canvas && loadState === "error" && <p className="canvas-empty" role="status">{es ? "No se pudieron actualizar los comentarios." : "Could not refresh comments."} <button type="button" className="btn-link" onClick={load}>{es ? "Reintentar" : "Retry"}</button></p>}
    {canvas && loadState === "ready" && !openCount && !draft && <p className="canvas-empty">{es ? "No hay comentarios abiertos." : "No open comments."}</p>}
    {draft && <form ref={draftForm} className="preview-comment-draft panel flex flex-col gap-2" style={{ padding: 10 }} onSubmit={(event) => { event.preventDefault(); save(); }}>
      <strong>{es ? "Comentario sobre " : "Comment on "}{chipText(draft.element, es)}</strong>
      <PreviewTargetDetails es={es} selector={draft.element.selector} source={sourceText(draft.element, es)} />
      {draft.element.text && <blockquote className="preview-comment-quote">{draft.element.text}</blockquote>}
      {draft.crop && <img className="preview-comment-crop" src={draft.crop} alt={es ? "Recorte del elemento" : "Crop of the element"} />}
      <label className="label">{es ? "Nota para el agente" : "Note for the agent"}
        <textarea name="note" className="field preview-comment-text" rows={3} value={note} onChange={(event) => setNote(event.target.value)} />
      </label>
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={canvas ? "btn btn-primary btn-sm" : "btn btn-primary"} disabled={saving || !note.trim()}>{saving ? (es ? "Guardando…" : "Saving…") : (es ? "Guardar comentario" : "Save comment")}</button>
        <button type="button" className={canvas ? "btn btn-sm" : "btn"} onClick={cancelDraft}>{es ? "Cancelar" : "Cancel"}</button>
      </div>
    </form>}
    {anchored.length > 0 && <div>{!canvas && <h4 className="font-semibold">{es ? "Comentarios abiertos" : "Open comments"} ({anchored.length})</h4>}<ul className={canvas ? "canvas-comment-list" : "flex flex-col gap-2 mt-2"}>{anchored.map(item)}</ul></div>}
    {lost.length > 0 && <div><h4 className="font-semibold">{es ? "Sin ancla" : "Without anchor"} ({lost.length})</h4>
      <p className="help">{es ? "El elemento ya no está en esta versión de la página. El comentario se conserva." : "The element is no longer in this revision of the page. The comment is kept."}</p>
      <ul className="flex flex-col gap-2 mt-2">{lost.map(item)}</ul></div>}
    {closed.length > 0 && <details><summary className="font-semibold">{es ? "Cerrados" : "Closed"} ({closed.length})</summary><ul className="flex flex-col gap-2 mt-2">{closed.map(item)}</ul></details>}
  </div>;
}
