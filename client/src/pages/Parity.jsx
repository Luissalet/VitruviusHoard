import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { useCopilotRefresh } from "../copilot-hooks.js";
import { Empty } from "../components/ui.jsx";

const pic = (url) => `/design${url}`;
const parseWidths = (text) => text.split(/[\s,;]+/).map((s) => parseInt(s, 10)).filter((n) => Number.isFinite(n));
const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : "");

function Slider({ width, es }) {
  const [pos, setPos] = useState(50);
  const [mode, setMode] = useState("slider");
  const box = useRef(null);
  const urls = width.image_urls;
  if (!urls) return null;
  const move = (event) => {
    const r = box.current.getBoundingClientRect();
    setPos(Math.max(0, Math.min(100, (100 * (event.clientX - r.left)) / r.width)));
  };
  const modes = [["slider", es ? "Deslizador" : "Slider"], ["diff", es ? "Diferencias" : "Differences"], ["reference", es ? "Referencia" : "Reference"], ["candidate", es ? "Candidata" : "Candidate"]];
  return (
    <div className="flex flex-col gap-2" data-testid="parity-compare">
      <div className="flex gap-2 flex-wrap">
        {modes.map(([key, label]) => (
          <button key={key} type="button" className={`btn btn-sm ${mode === key ? "btn-active" : ""}`} data-testid={`parity-mode-${key}`} aria-pressed={mode === key} onClick={() => setMode(key)}>{label}</button>
        ))}
      </div>
      {mode === "slider" ? (
        <div ref={box} data-testid="parity-slider" style={{ position: "relative", overflow: "hidden", lineHeight: 0, border: "1px solid var(--line)", borderRadius: 6, touchAction: "none", background: "#fff", cursor: "ew-resize" }}
          onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); move(e); }}
          onPointerMove={(e) => { if (e.buttons) move(e); }}>
          <img src={pic(urls.reference)} alt={es ? "Referencia" : "Reference"} style={{ display: "block", width: "100%", height: "auto" }} draggable={false} />
          <div style={{ position: "absolute", inset: 0, clipPath: `inset(0 0 0 ${pos}%)` }}>
            <img src={pic(urls.candidate)} alt={es ? "Candidata" : "Candidate"} style={{ display: "block", width: "100%", height: "auto" }} draggable={false} />
          </div>
          <div style={{ position: "absolute", top: 0, bottom: 0, left: `${pos}%`, width: 3, marginLeft: -1, background: "var(--hoard-accent, #6ea8ff)" }} />
        </div>
      ) : (
        <div style={{ lineHeight: 0, border: "1px solid var(--line)", borderRadius: 6, overflow: "hidden", background: "#fff" }}>
          <img src={pic(urls[mode])} alt={mode} style={{ display: "block", width: "100%", height: "auto" }} />
        </div>
      )}
      {mode === "slider" && (
        <input type="range" min="0" max="100" step="0.1" value={pos} data-testid="parity-range" aria-label={es ? "Posición del deslizador" : "Slider position"} onChange={(e) => setPos(Number(e.target.value))} />
      )}
      {mode === "slider" && <div className="help flex justify-between"><span>← {es ? "Referencia" : "Reference"}</span><span>{es ? "Candidata" : "Candidate"} →</span></div>}
      {mode === "diff" && <div className="help"><span style={{ color: "#e53935" }}>■</span> {es ? "distinto" : "different"} · <span style={{ color: "#1e88e5" }}>■</span> {es ? "inestable (enmascarado)" : "unstable (masked)"} · {es ? "el resto, atenuado" : "the rest, dimmed"}</div>}
    </div>
  );
}

export default function Parity() {
  const { notify, lang } = useApp();
  const es = lang !== "en";
  const [reference, setReference] = useState("");
  const [candidate, setCandidate] = useState("");
  const [widths, setWidths] = useState("1440, 390");
  const [maxScreens, setMaxScreens] = useState(12);
  const [tolerance, setTolerance] = useState(10);
  const [passScore, setPassScore] = useState(98);
  const [heightTol, setHeightTol] = useState(4);
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState(null);
  const [tab, setTab] = useState(0);
  const [history, setHistory] = useState([]);

  const loadHistory = useCallback(() => api.parityList().then((r) => setHistory(r.runs || [])).catch(() => setHistory([])), []);
  useEffect(() => { loadHistory(); }, [loadHistory]);
  useCopilotRefresh(loadHistory);

  const submit = async (event) => {
    event.preventDefault();
    if (!reference.trim() || !candidate.trim()) { notify(es ? "Rellena la referencia y la candidata." : "Fill in the reference and the candidate."); return; }
    const list = parseWidths(widths);
    if (!list.length) { notify(es ? "Escribe al menos una anchura (por ejemplo 1440, 390)." : "Enter at least one width (for example 1440, 390)."); return; }
    setBusy(true);
    try {
      const out = await api.parityCreate({ reference: reference.trim(), candidate: candidate.trim(), widths: list, max_screens: Number(maxScreens) || 12,
        tolerance: (Number(tolerance) || 0) / 100, pass_score: Number(passScore) || 98, height_tolerance: Number(heightTol) || 0 });
      setRun(out); setTab(0); loadHistory();
    } catch (e) { notify(e.message); } finally { setBusy(false); }
  };

  const open = async (id) => {
    try { setRun(await api.parity(id)); setTab(0); } catch (e) { notify(e.message); }
  };
  const remove = async (id) => {
    try {
      await api.parityDelete(id);
      if (run && run.id === id) setRun(null);
      loadHistory();
    } catch (e) { notify(e.message); }
  };

  const width = run ? run.widths[Math.min(tab, run.widths.length - 1)] : null;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[22px] font-semibold">{es ? "Paridad visual" : "Visual parity"}</h1>
        <p className="help mt-1" style={{ maxWidth: 780 }}>{es
          ? "Compara una página candidata con una referencia, pantalla a pantalla, en escritorio y móvil. Las dos se cargan con el reloj, el azar, las animaciones, las transiciones y los vídeos congelados; la referencia se carga dos veces y los píxeles que cambian entre cargas no cuentan. Una pantalla pasa con el 98 % de píxeles estables dentro de la tolerancia de color; la altura total debe coincidir con pocos píxeles de margen."
          : "Compares a candidate page with a reference, screen by screen, on desktop and mobile. Both load with the clock, random numbers, animations, transitions and videos frozen; the reference loads twice and pixels that change between loads do not count. A screen passes with 98 % of stable pixels within the colour tolerance; total height must match within a few pixels."}</p>
      </div>

      <form className="panel flex flex-col gap-3" onSubmit={submit} aria-busy={busy}>
        <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
          <div>
            <label className="label" htmlFor="parity-reference">{es ? "Referencia (URL, id de render o HTML)" : "Reference (URL, render id or HTML)"}</label>
            <textarea id="parity-reference" data-testid="parity-reference" className="field" rows={4} value={reference} onChange={(e) => setReference(e.target.value)} placeholder="https://ejemplo.com" />
          </div>
          <div>
            <label className="label" htmlFor="parity-candidate">{es ? "Candidata (URL, id de render o HTML)" : "Candidate (URL, render id or HTML)"}</label>
            <textarea id="parity-candidate" data-testid="parity-candidate" className="field" rows={4} value={candidate} onChange={(e) => setCandidate(e.target.value)} placeholder="https://mi-version.ejemplo.com" />
          </div>
        </div>
        <div className="flex gap-4 flex-wrap items-end">
          <div style={{ width: 150 }}>
            <label className="label" htmlFor="parity-widths">{es ? "Anchuras (px)" : "Widths (px)"}</label>
            <input id="parity-widths" data-testid="parity-widths" className="field" value={widths} onChange={(e) => setWidths(e.target.value)} />
          </div>
          <div style={{ width: 110 }}>
            <label className="label" htmlFor="parity-screens">{es ? "Pantallas máx." : "Max screens"}</label>
            <input id="parity-screens" type="number" min="1" max="40" className="field" value={maxScreens} onChange={(e) => setMaxScreens(e.target.value)} />
          </div>
          <div style={{ width: 130 }}>
            <label className="label" htmlFor="parity-tol">{es ? "Tolerancia color (%)" : "Colour tolerance (%)"}</label>
            <input id="parity-tol" type="number" min="0" max="50" className="field" value={tolerance} onChange={(e) => setTolerance(e.target.value)} />
          </div>
          <div style={{ width: 120 }}>
            <label className="label" htmlFor="parity-pass">{es ? "Pasa con (%)" : "Passes at (%)"}</label>
            <input id="parity-pass" type="number" min="50" max="100" step="0.1" className="field" value={passScore} onChange={(e) => setPassScore(e.target.value)} />
          </div>
          <div style={{ width: 130 }}>
            <label className="label" htmlFor="parity-height">{es ? "Altura ± (px)" : "Height ± (px)"}</label>
            <input id="parity-height" type="number" min="0" max="500" className="field" value={heightTol} onChange={(e) => setHeightTol(e.target.value)} />
          </div>
          <button type="submit" className="btn btn-primary" data-testid="parity-run" disabled={busy}>{busy ? (es ? "Comparando…" : "Comparing…") : (es ? "Comparar" : "Compare")}</button>
        </div>
      </form>

      {run && (
        <div className="flex flex-col gap-3" data-testid="parity-result">
          <div className="panel flex flex-col gap-2" data-testid="parity-verdict" data-passed={run.passed ? "true" : "false"}
            style={{ borderColor: run.passed ? "var(--ok)" : "var(--danger)" }}>
            <div className="flex gap-3 items-center flex-wrap">
              <span className={`chip ${run.passed ? "chip-ok" : "chip-danger"}`}>{run.passed ? (es ? "Pasa" : "Pass") : (es ? "No pasa" : "Fail")}</span>
              <span className="text-[14px] font-semibold">{run.summary.text}</span>
              <a className="btn-link ml-auto" data-testid="parity-report-link" href={pic(run.report_url)} target="_blank" rel="noreferrer">{es ? "Abrir página de prueba" : "Open test page"}</a>
              <button type="button" className="btn btn-sm" data-testid="parity-delete" onClick={() => remove(run.id)}>{es ? "Borrar" : "Delete"}</button>
            </div>
            {run.summary.failures.length > 0 && (
              <ul className="help" style={{ margin: 0, paddingLeft: 18 }}>
                {run.summary.failures.map((f) => <li key={f}>{f}</li>)}
              </ul>
            )}
            <div className="help">{es ? "Referencia" : "Reference"}: {run.reference.label} · {es ? "Candidata" : "Candidate"}: {run.candidate.label}</div>
          </div>

          <div className="flex gap-2 flex-wrap" role="tablist">
            {run.widths.map((w, i) => (
              <button key={w.width} type="button" role="tab" aria-selected={i === tab} data-testid={`parity-tab-${w.width}`} className={`btn ${i === tab ? "btn-active" : ""}`} onClick={() => setTab(i)}>
                {w.width} px · {w.score === null ? "—" : `${w.score} %`} {w.passed ? "✓" : "✗"}
              </button>
            ))}
          </div>

          {width && (
            <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
              <div className="panel">
                <p className="help" style={{ marginTop: 0 }} data-testid="parity-meta">
                  {es ? "Altura" : "Height"}: {es ? "referencia" : "reference"} {width.reference_height} px, {es ? "candidata" : "candidate"} {width.candidate_height} px ({width.height_delta >= 0 ? "+" : ""}{width.height_delta} px, {width.height_pass ? (es ? "dentro" : "within") : (es ? "fuera de" : "outside")} {es ? "la tolerancia" : "tolerance"}). {es ? "Ruido enmascarado" : "Masked noise"}: {width.noise_pct} %.
                </p>
                <Slider key={`${run.id}-${width.width}`} width={width} es={es} />
              </div>
              <div className="panel">
                <table style={{ width: "100%", borderCollapse: "collapse" }} data-testid="parity-screens">
                  <thead><tr className="help"><th align="left">{es ? "Pantalla" : "Screen"}</th><th align="left">{es ? "Coincidencia" : "Match"}</th><th align="left">{es ? "Resultado" : "Result"}</th><th /></tr></thead>
                  <tbody>
                    {width.screens.map((s) => (
                      <tr key={s.index} data-testid="parity-screen" data-passed={s.passed ? "true" : "false"} style={{ borderTop: "1px solid var(--line)" }}>
                        <td className="py-1">{s.index + 1} <span className="help">({s.y} px)</span></td>
                        <td>{s.score === null ? "—" : `${s.score} %`}</td>
                        <td><span className={`chip ${s.passed ? "chip-ok" : "chip-danger"}`}>{s.passed ? (es ? "pasa" : "pass") : (es ? "no pasa" : "fail")}</span></td>
                        <td>{s.diff_url && <a className="btn-link" href={pic(s.diff_url)} target="_blank" rel="noreferrer">{es ? "diferencias" : "diff"}</a>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {width.truncated && <p className="help">{es ? `Solo se han comprobado ${width.screens_checked} de ${width.screens_total} pantallas.` : `Only ${width.screens_checked} of ${width.screens_total} screens were checked.`}</p>}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="panel" data-testid="parity-history">
        <h2 className="text-[15px] font-semibold mb-2">{es ? "Comparaciones guardadas" : "Saved comparisons"}</h2>
        {history.length === 0 ? <Empty>{es ? "Todavía no hay ninguna." : "None yet."}</Empty> : (
          <ul className="list-none p-0 m-0 flex flex-col gap-2">
            {history.map((h) => (
              <li key={h.id} className="flex gap-3 items-center flex-wrap" data-testid="parity-history-item">
                <span className={`chip ${h.passed ? "chip-ok" : "chip-danger"}`}>{h.passed ? (es ? "Pasa" : "Pass") : (es ? "No pasa" : "Fail")}</span>
                <span className="text-[13px]" style={{ minWidth: 200 }}>{h.label || `${h.reference} → ${h.candidate}`}</span>
                <span className="help">{h.widths.map((w) => `${w.width}px ${w.score === null ? "—" : `${w.score} %`}`).join(" · ")} · {when(h.created_ts)}</span>
                <button type="button" className="btn btn-sm ml-auto" onClick={() => open(h.id)}>{es ? "Abrir" : "Open"}</button>
                <button type="button" className="btn btn-sm" onClick={() => remove(h.id)}>{es ? "Borrar" : "Delete"}</button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
