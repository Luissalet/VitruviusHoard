import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { TierChip } from "./RulesPanel.jsx";

// Slop audit: eight widths, a 0-100 slop score, the mode (heavy / light / none), the ordered fix passes, the findings marked
// on the screenshot, and the five-line direction brief. Sign list: unslop by Damir Sokolovsky (CC BY 4.0).
const PASSES = ["spacing", "color", "icons", "copy", "type", "layout", "details", "visuals", "motion"];
const PASS_ES = { spacing: "Espaciado", color: "Color", icons: "Iconos", copy: "Texto", type: "Tipografía", layout: "Composición",
  details: "Detalles", visuals: "Imágenes", motion: "Movimiento" };
const MODE = {
  heavy: ["Rediseño por pasadas", "Full fix passes", "chip-danger"],
  light: ["Retoque", "Light polish", "chip-amber"],
  none: ["Sin señales de slop", "No slop", "chip-ok"],
};

export default function SlopAudit({ render, html, url, lang, notify, initialId, t }) {
  const L = (es, en) => (lang === "es" ? es : en);
  const [audit, setAudit] = useState(null);
  const [busy, setBusy] = useState(false);
  const [width, setWidth] = useState(null);
  const [selected, setSelected] = useState(null);
  const [brief, setBrief] = useState(null);
  const [busyBrief, setBusyBrief] = useState(false);
  const frame = useRef(null);

  const show = (res) => { setAudit(res); setWidth(res.display_width); setSelected(null); };
  useEffect(() => {
    setBrief(null);
    if (initialId) api.slopAuditGet(initialId).then(show).catch(() => {});
  }, [initialId]);

  const run = async () => {
    setBusy(true);
    setBrief(null);
    try {
      const body = render ? { render_id: render.id } : html?.trim() ? { html } : { url };
      show(await api.slopAudit(body));
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };

  const writeBrief = async () => {
    setBusyBrief(true);
    try {
      setBrief(await api.directionBrief(audit ? { render_id: audit.render_id } : render ? { render_id: render.id } : html?.trim() ? { html } : { url }));
    } catch (e) {
      notify(e.message);
    } finally {
      setBusyBrief(false);
    }
  };

  const shot = audit?.screenshots?.find((s) => s.width === width);
  const marks = useMemo(() => (audit?.findings || []).map((f, i) => ({ f, i })).filter(({ f }) => f.box_width === width && f.boxes?.length), [audit, width]);
  const grouped = useMemo(() => {
    const g = {};
    (audit?.findings || []).forEach((f, i) => { (g[f.pass] = g[f.pass] || []).push({ f, i }); });
    return PASSES.filter((p) => g[p]).map((p) => [p, g[p]]);
  }, [audit]);

  const pick = (i) => {
    const f = audit.findings[i];
    setSelected(i);
    if (f.box_width) setWidth(f.box_width);
    setTimeout(() => {
      const el = frame.current?.querySelector(`[data-mark="${i}"]`);
      if (el && frame.current) frame.current.scrollTop = Math.max(0, el.offsetTop - 80);
    }, 60);
  };

  const can = !!render || !!html?.trim() || !!url?.trim();

  return (
    <div className="panel mt-4" data-testid="slop-audit">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-[14px] font-semibold">{L("Auditoría de slop", "Slop audit")}</h3>
        <div className="flex gap-2 flex-wrap">
          <button type="button" className="btn btn-primary" onClick={run} disabled={busy || !can} data-testid="slop-run">
            {busy ? L("Auditando 8 anchos…", "Auditing 8 widths…") : L("Auditoría de slop", "Slop audit")}
          </button>
          <button type="button" className="btn" onClick={writeBrief} disabled={busyBrief || (!audit && !can)} data-testid="slop-brief">
            {busyBrief ? L("Escribiendo…", "Writing…") : L("Dirección en 5 líneas", "5-line direction")}
          </button>
        </div>
      </div>
      {!audit && <div className="help mt-2">{L("Renderiza la página (o pega HTML / URL) y audítala a 320-1920 px: puntuación de slop, modo y pasadas de arreglo en orden.",
        "Render the page (or paste HTML / a URL) and audit it at 320-1920 px: slop score, mode and the ordered fix passes.")}</div>}
      {brief && (
        <div className="card mt-3" data-testid="slop-brief-out">
          <div className="flex items-center justify-between gap-2"><span className="font-semibold text-[13px]">{L("Dirección", "Direction")}</span>
            <span className="chip">{brief.source === "model" ? (brief.model || L("modelo", "model")) : L("catálogo de temas", "theme catalogue")}</span></div>
          <dl className="mt-2 text-[13px] grid gap-1" style={{ gridTemplateColumns: "max-content 1fr" }}>
            {[["product", L("Producto", "Product")], ["character", L("Carácter", "Character")], ["bright_moment", L("Momento brillante", "Bright moment")],
              ["signature", L("Firma", "Signature")], ["avoid", L("Evitar", "Avoid")]].map(([k, label]) => (
              <React.Fragment key={k}><dt className="font-semibold pr-3">{label}</dt><dd>{brief[k]}</dd></React.Fragment>
            ))}
          </dl>
        </div>
      )}
      {audit && (
        <>
          <div className="flex items-center gap-4 flex-wrap mt-3">
            <div className="text-center" data-testid="slop-score">
              <div style={{ fontSize: 34, fontWeight: 600, lineHeight: 1 }}>{audit.slop_score}</div>
              <div className="help">/ 100 slop</div>
            </div>
            <span className={`chip ${MODE[audit.mode][2]}`}>{L(MODE[audit.mode][0], MODE[audit.mode][1])}</span>
            <span className="help">{audit.signs} {L("señales", "signs")} · {audit.findings.length} {L("hallazgos", "findings")} · {audit.rules_run} {L("reglas", "rules")} · {Math.round(audit.ms / 1000)} s</span>
          </div>
          <p className="text-[13px] mt-2">{audit.plan.summary}</p>
          <div className="grid gap-4 mt-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
            <div>
              <div className="flex gap-1 flex-wrap mb-2">
                {audit.widths.map((w) => (
                  <button key={w} type="button" className={`btn btn-sm ${w === width ? "btn-active" : ""}`} aria-pressed={w === width} onClick={() => setWidth(w)}>{w}</button>
                ))}
              </div>
              {shot && (
                <div ref={frame} className="rounded-md border overflow-y-auto" style={{ borderColor: "var(--line)", maxHeight: 620, background: "#fff" }}>
                  <div style={{ position: "relative" }}>
                    <img src={api.renderFileUrl(audit.render_id, shot.file)} alt={`${width}px`} className="w-full block" />
                    {marks.map(({ f, i }) => f.boxes.map((b, k) => (
                      <button key={`${i}-${k}`} type="button" data-mark={i} title={f.title} onClick={() => pick(i)}
                        style={{ position: "absolute", left: `${(b[0] / width) * 100}%`, top: `${(b[1] / (shot.h || 900)) * 100}%`,
                          width: `${Math.max(0.6, (b[2] / width) * 100)}%`, height: `${Math.max(0.3, (b[3] / (shot.h || 900)) * 100)}%`,
                          border: `2px solid ${selected === i ? "#e5534b" : f.slop ? "rgba(229,83,75,.55)" : "rgba(212,168,67,.6)"}`,
                          background: selected === i ? "rgba(229,83,75,.16)" : "transparent", borderRadius: 3, padding: 0, cursor: "pointer" }} />
                    )))}
                  </div>
                </div>
              )}
              <div className="help mt-1">{marks.length} {L("hallazgos marcados a", "findings marked at")} {width}px</div>
            </div>
            <div className="flex flex-col gap-3" style={{ maxHeight: 680, overflowY: "auto" }}>
              {grouped.map(([pass, rows]) => (
                <div key={pass}>
                  <div className="text-[12px] font-semibold mb-1" style={{ color: "var(--muted)" }}>{L(PASS_ES[pass], pass)} · {rows.length}</div>
                  {rows.map(({ f, i }) => (
                    <button key={i} type="button" className="card text-left w-full mb-2" onClick={() => pick(i)} data-testid="slop-finding"
                      style={selected === i ? { outline: "2px solid #e5534b" } : undefined}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-[13px]">{f.title}</span>
                        <span className="flex gap-1">{f.slop && <span className="chip">slop</span>}<TierChip tier={f.tier} t={t} /></span>
                      </div>
                      <div className="text-[12px] mt-1">{f.detail}</div>
                      {f.fix && <div className="help mt-1"><strong>{L("Arreglo", "Fix")}:</strong> {f.fix}</div>}
                    </button>
                  ))}
                </div>
              ))}
              {!grouped.length && <div className="help">{L("Nada que arreglar.", "Nothing to fix.")}</div>}
            </div>
          </div>
          {audit.plan.passes?.length > 0 && (
            <div className="mt-4">
              <h4 className="text-[13px] font-semibold mb-1">{L("Plan por pasadas (en este orden)", "Fix passes (in this order)")}</h4>
              <ol className="text-[13px] flex flex-col gap-1" style={{ listStyle: "decimal", paddingLeft: 20 }}>
                {audit.plan.passes.map((p) => <li key={p.pass}><strong>{p.title}</strong> · {p.steps.length} {L("cambios", "changes")}</li>)}
              </ol>
            </div>
          )}
          {audit.plan.steps?.length > 0 && (
            <ul className="text-[13px] mt-3" style={{ listStyle: "disc", paddingLeft: 20 }}>
              {audit.plan.steps.map((s, k) => <li key={k}>{s.title}: {s.fix}</li>)}
            </ul>
          )}
          <div className="help mt-3">{audit.credit}</div>
        </>
      )}
    </div>
  );
}
