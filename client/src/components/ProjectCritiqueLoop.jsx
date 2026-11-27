import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

function Findings({ title, changes, side }) {
  if (!changes?.length) return null;
  return <div>
    <h3 className="font-semibold">{title}</h3>
    <ul className="list-disc pl-5">
      {changes.map((change) => {
        const finding = change[side][0];
        const evidence = Array.isArray(finding?.evidence)
          ? finding.evidence.filter((item) => typeof item === "string").slice(0, 3)
          : [];
        return <li key={change.criterion}>
          {finding?.title || change.criterion}
          {finding?.detail && <span className="help block">{finding.detail}</span>}
          {evidence.length > 0 && <span className="help block">{evidence.join(" · ")}</span>}
        </li>;
      })}
    </ul>
  </div>;
}

export default function ProjectCritiqueLoop({ project, visibleRevision, lang, onRevision }) {
  const es = lang === "es";
  const [state, setState] = useState(null);
  const [undo, setUndo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [previewWarning, setPreviewWarning] = useState(false);
  const operation = useRef(0);
  const pending = useRef(false);
  const id = project.id;

  useEffect(() => {
    let active = true;
    const load = async () => {
      const before = operation.current;
      if (pending.current || document.hidden) return;
      try {
        const result = await api.appProjectCritiqueLoop(id, lang);
        if (active && before === operation.current) setState(result);
      } catch (failure) {
        if (active && before === operation.current) setError(failure.message);
      }
    };
    load();
    const timer = setInterval(load, 2500);
    return () => { active = false; clearInterval(timer); };
  }, [id, lang]);

  const run = async (undoing) => {
    pending.current = true;
    operation.current++;
    setBusy(true);
    setError("");
    try {
      const next = undoing
        ? await api.appProjectCritiqueUndo(id, { ...undo, lang })
        : await api.appProjectCritiqueRound(id, { expected_revision: project.revision, lang });
      setState(next);
      setUndo(next.undo?.arguments ?? null);
      setPreviewWarning(Boolean(next.preview_warning));
      if (next.revision !== project.revision) onRevision();
    } catch (failure) {
      setError(failure.message);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  const fmt = (score) => new Intl.NumberFormat(es ? "es-ES" : "en", { maximumFractionDigits: 2 }).format(score);
  const best = state?.best;
  const last = state?.latest;
  const revisionReady = state?.revision === project.revision && visibleRevision === project.revision;
  const undoAvailable = undo && undo.expected_round_id === last?.id && undo.expected_revision === project.revision
    && undo.expected_updated_ts === project.updated_ts;
  const status = last?.decision === "restored"
    ? (es ? "Volvió a la mejor versión" : "Restored the best revision")
    : last?.decision === "tie" ? (es ? "Misma nota que la mejor versión" : "Matched the best score")
    : (es ? "Nueva mejor versión" : "New best revision");

  return <section className="canvas-inspector-section flex flex-col gap-2" aria-label={es ? "Bucle de crítica" : "Critique loop"}>
    <h2 className="canvas-inspector-heading">{es ? "Bucle de crítica" : "Critique loop"}</h2>
    {best && <p className="help">
      {es ? "Mejor" : "Best"} · {fmt(best.score)}/10 · <code>{best.revision}</code>
    </p>}
    {last && <>
      <p role="status">
        {es ? "Ronda" : "Round"} {last.number} · {fmt(last.score)}/10 · {status}
      </p>
      {last.score_delta !== null && <p className="help">
        {es ? "Cambio de nota" : "Score change"} · {last.score_delta > 0 && "+"}{fmt(last.score_delta)}
      </p>}
      {last.changed_files.length > 0 && <p className="help">
        {es ? "Archivos modificados" : "Changed files"} · {last.changed_files.join(", ")}
      </p>}
      <Findings title={es ? "Criterios que empeoraron" : "Criteria that regressed"} changes={last.regressions} side="after" />
      <Findings title={es ? "Criterios que mejoraron" : "Criteria that improved"} changes={last.improvements} side="before" />
      <a className="help underline" href={`#/critique/${encodeURIComponent(last.render_id)}`}>
        {es ? "Ver captura evaluada" : "Open assessed capture"}
      </a>
    </>}
    {previewWarning && <p className="help">{es ? "Vuelve a abrir la vista previa para ver la revisión activa." : "Reopen the preview to see the active revision."}</p>}
    {error && <p role="alert" className="help">{error}</p>}
    <div className="flex flex-wrap gap-2">
      <button type="button" className="btn" disabled={busy || !revisionReady} onClick={() => run(false)}>
        {busy ? (es ? "Evaluando…" : "Working…") : (es ? "Evaluar revisión" : "Assess revision")}
      </button>
      {undoAvailable && <button type="button" className="btn" disabled={busy || !revisionReady} onClick={() => run(true)}>
        {es ? "Deshacer ronda" : "Undo round"}
      </button>}
    </div>
  </section>;
}
