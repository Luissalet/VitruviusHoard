import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { useCopilotRefresh } from "../copilot-hooks.js";
import { Empty } from "../components/ui.jsx";

const STATUS_CLASS = { fail: "chip chip-danger", warn: "chip chip-amber", note: "chip", pass: "chip chip-ok" };
const STATUS = { es: { fail: "Falla", warn: "Aviso", note: "Nota", pass: "Bien" }, en: { fail: "Fail", warn: "Warning", note: "Note", pass: "Pass" } };
const VERDICT = { es: { lista: "Lista", revisar: "Revisar", rehacer: "Rehacer" }, en: { lista: "Ready", revisar: "Review", rehacer: "Redo" } };

const pic = (url, stamp) => `/design${url}?v=${stamp || 0}`;
const scoreColor = (s) => (s >= 85 ? "var(--ok)" : s >= 60 ? "var(--warn)" : "var(--danger)");

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

const parseGrounds = (text) => text.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);

export default function Marks() {
  const { notify, lang } = useApp();
  const es = lang !== "en";
  const L = es ? "es" : "en";
  const [file, setFile] = useState(null);
  const [path, setPath] = useState("");
  const [grounds, setGrounds] = useState("");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [stamp, setStamp] = useState(0);
  const [history, setHistory] = useState([]);

  const loadHistory = useCallback(() => api.marks().then((r) => setHistory(r.reports || [])).catch(() => setHistory([])), []);
  useEffect(() => { loadHistory(); }, [loadHistory]);
  useCopilotRefresh(loadHistory);

  const run = async (event) => {
    event.preventDefault();
    if (!file && !path.trim()) { notify(es ? "Elige una imagen o escribe una ruta." : "Pick an image or type a path."); return; }
    setBusy(true);
    try {
      const body = { backgrounds: parseGrounds(grounds) };
      if (file) { body.data = await readFile(file); body.name = file.name; } else body.path = path.trim();
      const out = await api.markAudit(body);
      setReport(out); setStamp(Date.now()); loadHistory();
    } catch (e) { notify(e.message); } finally { setBusy(false); }
  };

  const redraw = async () => {
    if (!report) return;
    setBusy(true);
    try {
      const out = await api.markSheet({ id: report.id, backgrounds: parseGrounds(grounds) });
      setReport({ ...report, backgrounds: out.backgrounds }); setStamp(Date.now());
    } catch (e) { notify(e.message); } finally { setBusy(false); }
  };

  const open = async (id) => {
    try { const r = await api.mark(id); setReport(r); setGrounds((r.backgrounds || []).join(", ")); setStamp(Date.now()); } catch (e) { notify(e.message); }
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[22px] font-semibold">{es ? "Logotipos" : "Logos"}</h1>
        <p className="help mt-1" style={{ maxWidth: 760 }}>{es
          ? "Comprueba si una marca aguanta en un color, invertida, sobre fondo claro y oscuro, a 32 y 16 px y como avatar. Puntúa sobre 100 (25 por fallo, 8 por aviso, 1 por nota) y dibuja una hoja de prueba."
          : "Checks whether a mark holds up in one colour, inverted, on light and dark grounds, at 32 and 16 px and as an avatar. Scores out of 100 (25 per fail, 8 per warning, 1 per note) and draws a test sheet."}</p>
      </div>

      <form className="panel flex flex-col gap-3" onSubmit={run} aria-busy={busy}>
        <div className="flex gap-4 flex-wrap items-end">
          <div>
            <label className="label" htmlFor="mark-file">{es ? "Imagen (PNG, JPG, WebP, SVG)" : "Image (PNG, JPG, WebP, SVG)"}</label>
            <input id="mark-file" data-testid="mark-file" type="file" accept="image/*,.svg" className="field"
              onChange={(e) => { setFile(e.target.files?.[0] || null); if (e.target.files?.[0]) setPath(""); }} />
          </div>
          <div className="flex-1" style={{ minWidth: 260 }}>
            <label className="label" htmlFor="mark-path">{es ? "…o ruta en este PC" : "…or a path on this PC"}</label>
            <input id="mark-path" data-testid="mark-path" className="field" value={path} disabled={!!file}
              onChange={(e) => setPath(e.target.value)} placeholder={"C:\\marca\\logo.png"} />
          </div>
        </div>
        <div className="flex gap-4 flex-wrap items-end">
          <div className="flex-1" style={{ minWidth: 260 }}>
            <label className="label" htmlFor="mark-grounds">{es ? "Fondos de marca para la hoja (#rrggbb, hasta 6)" : "Brand grounds for the sheet (#rrggbb, up to 6)"}</label>
            <input id="mark-grounds" data-testid="mark-grounds" className="field" value={grounds} onChange={(e) => setGrounds(e.target.value)} placeholder="#0a2540, #ff5a1f" />
          </div>
          <button type="submit" className="btn btn-primary" data-testid="mark-run" disabled={busy}>{busy ? (es ? "Midiendo…" : "Measuring…") : (es ? "Auditar logotipo" : "Audit logo")}</button>
          {report && <button type="button" className="btn" data-testid="mark-redraw" disabled={busy} onClick={redraw}>{es ? "Redibujar hoja con estos fondos" : "Redraw sheet with these grounds"}</button>}
        </div>
      </form>

      {report ? (
        <div className="flex flex-col gap-3" data-testid="mark-report">
          <div className="panel flex gap-6 items-center flex-wrap">
            <img src={pic(report.mark_url, stamp)} alt="" style={{ width: 72, height: 72, objectFit: "contain", background: "#fff", borderRadius: 8, border: "1px solid var(--line, #ddd)" }} />
            <div style={{ minWidth: 110 }}>
              <div className="text-[44px] font-bold leading-none" data-testid="mark-score" style={{ color: scoreColor(report.score) }}>{report.score}</div>
              <div className="help">/ 100 · {VERDICT[L][report.verdict] || report.verdict}</div>
            </div>
            <div className="flex-1" style={{ minWidth: 240 }}>
              <div className="text-[14px] font-semibold">{report.name}</div>
              <div className="flex gap-2 flex-wrap mt-2">
                {["fail", "warn", "note", "pass"].map((s) => <span key={s} className={STATUS_CLASS[s]}>{STATUS[L][s]}: {report.counts?.[s] || 0}</span>)}
                {(report.metrics?.palette || []).map((p) => (
                  <span key={p.hex} className="chip" title={`${Math.round(p.share * 100)} %`}>
                    <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: p.hex, marginRight: 6, border: "1px solid #0003" }} />{p.hex}
                  </span>
                ))}
              </div>
            </div>
          </div>
          <ul className="grid gap-2 list-none p-0" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
            {report.checks.map((c) => (
              <li key={c.id} className="card" data-testid="mark-check" data-check={c.id} data-status={c.status}>
                <div className="flex items-center gap-2"><span className={STATUS_CLASS[c.status]}>{STATUS[L][c.status]}</span><strong className="text-[13px]">{c.title}</strong></div>
                <p className="help mt-1">{c.detail}</p>
              </li>
            ))}
          </ul>
          <div className="panel" data-testid="mark-sheet">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <h3 className="text-[13px] font-semibold">{es ? "Hoja de prueba" : "Test sheet"}</h3>
              <a className="btn btn-sm" href={pic(report.sheet_url, stamp)} download={`hoja-${report.id}.png`}>{es ? "Descargar PNG" : "Download PNG"}</a>
            </div>
            <img src={pic(report.sheet_url, stamp)} alt={es ? "Hoja de prueba del logotipo" : "Logo test sheet"} className="mt-2" style={{ maxWidth: "100%", borderRadius: 6 }} />
            <ul className="mt-2 pl-4 text-[12.5px]" style={{ listStyle: "disc" }}>{(report.limits || []).map((l) => <li key={l} className="help">{l}</li>)}</ul>
          </div>
        </div>
      ) : !busy && <Empty>{es ? "Sube un logotipo para medirlo." : "Upload a logo to measure it."}</Empty>}

      {!!history.length && (
        <div className="panel" data-testid="mark-history">
          <h3 className="text-[13px] font-semibold">{es ? "Historial" : "History"}</h3>
          <ul className="mt-2 flex flex-col gap-1 list-none p-0">
            {history.map((h) => (
              <li key={h.id} className="flex items-center justify-between gap-2 flex-wrap text-[12.5px]">
                <span className="flex items-center gap-2">
                  <img src={pic(h.mark_url)} alt="" style={{ width: 24, height: 24, objectFit: "contain", background: "#fff", borderRadius: 4 }} />
                  {h.name}
                </span>
                <span className="help">{new Date(h.created_at * 1000).toLocaleString(es ? "es-ES" : "en-GB")} · {h.score}/100 · {VERDICT[L][h.verdict] || h.verdict}</span>
                <button type="button" className="btn btn-sm" onClick={() => open(h.id)}>{es ? "Abrir" : "Open"}</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
