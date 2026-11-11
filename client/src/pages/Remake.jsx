import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { useCopilotRefresh } from "../copilot-hooks.js";
import { Empty } from "../components/ui.jsx";
import { Slider } from "./Parity.jsx";
import Benchmark from "./Benchmark.jsx";

const at = (url) => (url && url.startsWith("/api/") ? `/design${url}` : url);
const parseWidths = (text) => text.split(/[\s,;]+/).map((s) => parseInt(s, 10)).filter((n) => Number.isFinite(n));
const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : "");
const STATUS = {
  queued: ["En cola", "Queued", "chip"], running: ["Trabajando", "Working", "chip chip-warn"], done: ["Terminado", "Finished", "chip chip-ok"],
  failed: ["Error", "Error", "chip chip-danger"], stopped: ["Parado", "Stopped", "chip"], interrupted: ["Interrumpido", "Interrupted", "chip"],
};
const KIND = { copy: ["copia", "copy"], model: ["modelo", "model"], fetch: ["descarga", "fetch"] };

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function Preview({ project, es }) {
  const [width, setWidth] = useState(project.widths[0]);
  const box = useRef(null);
  const [scale, setScale] = useState(0.5);
  useEffect(() => {
    const measure = () => { if (box.current) setScale(Math.min(1, box.current.clientWidth / width)); };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [width]);
  const height = 760;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-2 flex-wrap items-center">
        {project.widths.map((w) => (
          <button key={w} type="button" className={`btn btn-sm ${w === width ? "btn-active" : ""}`} aria-pressed={w === width} onClick={() => setWidth(w)}>{w} px</button>
        ))}
        <a className="btn-link ml-auto" href={at(project.site_url)} target="_blank" rel="noreferrer">{es ? "Abrir en otra pestaña" : "Open in a new tab"}</a>
      </div>
      <div ref={box} style={{ height: height * scale, overflow: "hidden", border: "1px solid var(--line)", borderRadius: 6, background: "#fff" }}>
        <iframe title={es ? "Resultado" : "Result"} data-testid="remake-preview" key={`${project.id}-${project.best_round}-${width}`} src={at(project.site_url)}
          sandbox="allow-scripts" style={{ width, height, border: 0, transform: `scale(${scale})`, transformOrigin: "0 0" }} />
      </div>
    </div>
  );
}

function Code({ project, es }) {
  const [code, setCode] = useState(null);
  const [path, setPath] = useState("index.html");
  useEffect(() => {
    let alive = true;
    api.remakeCode(project.id, path).then((c) => alive && setCode(c)).catch((e) => alive && setCode({ text: e.message }));
    return () => { alive = false; };
  }, [project.id, project.best_round, path]);
  const texts = (project.files || []).filter((f) => /\.(html|css|svg|json)$/i.test(f.path)).slice(0, 60);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-2 items-center flex-wrap">
        <select className="field" style={{ maxWidth: 420 }} value={path} onChange={(e) => setPath(e.target.value)} aria-label={es ? "Fichero" : "File"}>
          {texts.map((f) => <option key={f.path} value={f.path}>{f.path}</option>)}
        </select>
        {code && <span className="help">{code.chars} {es ? "caracteres" : "characters"}{code.truncated ? (es ? " (recortado)" : " (cut)") : ""}</span>}
        <button type="button" className="btn btn-sm ml-auto" onClick={() => code && navigator.clipboard?.writeText(code.text)}>{es ? "Copiar" : "Copy"}</button>
      </div>
      <pre data-testid="remake-code" style={{ maxHeight: 520, overflow: "auto", margin: 0, padding: 12, fontSize: 12, lineHeight: 1.45, background: "var(--panel-2, rgba(127,127,127,.08))", border: "1px solid var(--line)", borderRadius: 6, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {code ? code.text : "…"}
      </pre>
    </div>
  );
}

function Pieces({ project, es }) {
  const s = project.slots || {};
  const sum = s.resumen;
  if (!sum) return <p className="help">{es ? "Sin inventario (la referencia era una captura)." : "No inventory (the reference was a screenshot)."}</p>;
  const groups = s.enlaces || {};
  const names = { redes: es ? "redes sociales" : "social", reservas: es ? "reservas" : "booking", correo: es ? "correo" : "email", telefono: es ? "teléfono" : "phone",
    paginas_no_rehechas: es ? "páginas no rehechas" : "pages not remade", otros: es ? "otros" : "other" };
  return (
    <div className="flex flex-col gap-3" data-testid="remake-pieces">
      <p className="help" style={{ margin: 0 }}>{es
        ? "Lo que sigue perteneciendo al original y hay que cambiar o licenciar antes de publicar."
        : "What still belongs to the original and must be replaced or licensed before publishing."}</p>
      <div className="flex gap-2 flex-wrap">
        <span className="chip">{sum.textos} {es ? "bloques de texto" : "text blocks"}</span>
        <span className="chip">{sum.imagenes} {es ? "imágenes" : "images"}</span>
        <span className={`chip ${sum.fuentes_a_revisar ? "chip-warn" : ""}`}>{sum.fuentes} {es ? "fuentes" : "fonts"}{sum.fuentes_a_revisar ? ` (${sum.fuentes_a_revisar} ${es ? "a revisar" : "to check"})` : ""}</span>
        <span className="chip">{sum.colores} {es ? "colores" : "colours"}</span>
        <span className="chip">{sum.enlaces_externos} {es ? "enlaces externos" : "external links"}</span>
        <span className="chip">{sum.formularios} {es ? "formularios" : "forms"}</span>
      </div>
      {s.fuentes?.length > 0 && (
        <ul className="help" style={{ margin: 0, paddingLeft: 18 }}>
          {s.fuentes.map((f) => <li key={f.family}><b>{f.family}</b>: {f.note}</li>)}
        </ul>
      )}
      {s.colores?.length > 0 && (
        <div className="flex gap-1 flex-wrap">{s.colores.map((c) => <span key={c.c} title={c.c} style={{ width: 22, height: 22, borderRadius: 4, background: c.c, border: "1px solid var(--line)" }} />)}</div>
      )}
      <div className="help">{Object.entries(groups).filter(([, v]) => v.length).map(([k, v]) => `${v.length} ${names[k] || k}`).join(" · ") || (es ? "Sin enlaces." : "No links.")}</div>
      {project.assets?.count > 0 && (
        <details>
          <summary className="help" style={{ cursor: "pointer" }}>{es ? `Recursos descargados (${project.assets.count}) y su licencia` : `Downloaded files (${project.assets.count}) and their licence`}</summary>
          <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 6 }}>
            <tbody>
              {project.assets.files.slice(0, 120).map((f) => (
                <tr key={f.local} style={{ borderTop: "1px solid var(--line)" }}>
                  <td className="text-[12px] py-1" style={{ wordBreak: "break-all" }}>{f.local}</td>
                  <td className="help">{f.kind}</td>
                  <td className="help">{f.licence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

export default function Remake({ param }) {
  const { notify, lang } = useApp();
  const es = lang !== "en";
  const [source, setSource] = useState("url");
  const [url, setUrl] = useState("");
  const [image, setImage] = useState(null);
  const [imageWidth, setImageWidth] = useState(1440);
  const [mode, setMode] = useState("copy");
  const [rounds, setRounds] = useState(4);
  const [widths, setWidths] = useState("1440, 390");
  const [passScore, setPassScore] = useState(98);
  const [keepScripts, setKeepScripts] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [project, setProject] = useState(null);
  const [history, setHistory] = useState([]);
  const [roundN, setRoundN] = useState(null);
  const [run, setRun] = useState(null);
  const [tab, setTab] = useState(0);
  const [view, setView] = useState("preview");
  const [more, setMore] = useState(2);
  const [moreNote, setMoreNote] = useState("");

  const loadHistory = useCallback(() => api.remakeList().then((r) => setHistory(r.remakes || [])).catch(() => setHistory([])), []);
  useEffect(() => { loadHistory(); }, [loadHistory]);
  useCopilotRefresh(loadHistory);

  const open = useCallback(async (id) => {
    try { setProject(await api.remake(id)); } catch (e) { notify(e.message); }
  }, [notify]);
  useEffect(() => { if (param) open(param); }, [param, open]);

  // While the job works, follow it.
  useEffect(() => {
    if (!project || !(project.running || project.status === "queued" || project.status === "running")) return undefined;
    const timer = setInterval(async () => {
      try {
        const next = await api.remake(project.id);
        setProject(next);
        if (!next.running && next.status !== "queued" && next.status !== "running") loadHistory();
      } catch { /* the next tick tries again */ }
    }, 2500);
    return () => clearInterval(timer);
  }, [project, loadHistory]);

  const shown = project ? (roundN ?? (project.best_round !== null && project.best_round !== undefined ? project.rounds[project.best_round]?.n : null)) : null;
  const shownRound = project && shown !== null ? project.rounds.find((r) => r.n === shown) : null;
  useEffect(() => {
    if (!shownRound?.parity_id) { setRun(null); return; }
    let alive = true;
    api.parity(shownRound.parity_id).then((r) => alive && setRun(r)).catch(() => alive && setRun(null));
    return () => { alive = false; };
  }, [shownRound?.parity_id]);

  const submit = async (event) => {
    event.preventDefault();
    const list = parseWidths(widths);
    const body = { mode, widths: list.length ? list : [1440, 390], max_rounds: Number(rounds) || undefined, pass_score: Number(passScore) || 98,
      keep_scripts: keepScripts, note: note.trim() };
    if (source === "url") {
      if (!url.trim()) { notify(es ? "Escribe la URL de la página." : "Enter the page URL."); return; }
      body.url = url.trim();
    } else {
      if (!image) { notify(es ? "Elige la captura de la página." : "Choose the page screenshot."); return; }
      body.image = image;
      body.image_width = Number(imageWidth) || 1440;
      body.mode = "rebuild";
    }
    setBusy(true);
    try {
      const out = await api.remakeStart(body);
      setProject(out); setRoundN(null); setTab(0); setView("preview"); loadHistory();
    } catch (e) { notify(e.message); } finally { setBusy(false); }
  };

  const act = async (fn) => {
    try { const out = await fn(); if (out && out.id && out.rounds) setProject(out); loadHistory(); } catch (e) { notify(e.message); }
  };
  const remove = async (id) => {
    try { await api.remakeDelete(id); if (project && project.id === id) setProject(null); loadHistory(); } catch (e) { notify(e.message); }
  };

  const working = project && (project.running || project.status === "queued" || project.status === "running");
  const width = run ? run.widths[Math.min(tab, run.widths.length - 1)] : null;
  const st = project ? (STATUS[project.status] || STATUS.queued) : null;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[22px] font-semibold">{es ? "Rehacer una web" : "Remake a web page"}</h1>
        <p className="help mt-1" style={{ maxWidth: 820 }}>{es
          ? "Rehace una página a partir de su URL o de una captura hasta alcanzar la paridad visual en escritorio y móvil. Se captura la referencia congelada (estructura, textos, paleta, fuentes, imágenes y CSS); la primera versión es la propia página copiada (sin rastreadores ni scripts) o una reconstrucción en HTML y CSS nuevos escrita por el modelo global de la familia; después se mide pantalla a pantalla y se corrige en bucle la primera pantalla que falla de cada anchura. Una ronda que empeora se deshace. No se rehacen páginas con comprobación anti-robots ni con formularios de inicio de sesión o de pago."
          : "Remakes a page from its URL or a screenshot until it reaches visual parity on desktop and mobile. The reference is captured frozen (structure, texts, palette, fonts, images and CSS); the first version is the page itself copied (without trackers or scripts) or a rebuild in new HTML and CSS written by the family's global model; then it is measured screen by screen and the first failing screen of each width is fixed in a loop. A round that scores lower is undone. Pages behind a bot check or with sign-in or payment forms are not remade."}</p>
      </div>

      <form className="panel flex flex-col gap-3" onSubmit={submit} aria-busy={busy} data-testid="remake-form">
        <div className="flex gap-2 flex-wrap" role="radiogroup" aria-label={es ? "Referencia" : "Reference"}>
          <button type="button" className={`btn btn-sm ${source === "url" ? "btn-active" : ""}`} aria-pressed={source === "url"} onClick={() => setSource("url")}>{es ? "Desde una URL" : "From a URL"}</button>
          <button type="button" className={`btn btn-sm ${source === "image" ? "btn-active" : ""}`} aria-pressed={source === "image"} onClick={() => setSource("image")} data-testid="remake-source-image">{es ? "Desde una captura" : "From a screenshot"}</button>
        </div>
        {source === "url" ? (
          <div>
            <label className="label" htmlFor="remake-url">{es ? "URL de la página" : "Page URL"}</label>
            <input id="remake-url" data-testid="remake-url" className="field" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://ejemplo.com" />
          </div>
        ) : (
          <div className="flex gap-4 flex-wrap items-end">
            <div>
              <label className="label" htmlFor="remake-image">{es ? "Captura de página completa (PNG o JPEG)" : "Full-page screenshot (PNG or JPEG)"}</label>
              <input id="remake-image" type="file" accept="image/png,image/jpeg,image/webp" className="field"
                onChange={async (e) => { const f = e.target.files?.[0]; setImage(f ? await readFile(f) : null); }} />
            </div>
            <div style={{ width: 160 }}>
              <label className="label" htmlFor="remake-image-width">{es ? "Anchura de la captura (px)" : "Screenshot width (px)"}</label>
              <input id="remake-image-width" type="number" min="200" max="3000" className="field" value={imageWidth} onChange={(e) => setImageWidth(e.target.value)} />
            </div>
          </div>
        )}
        <div className="flex gap-4 flex-wrap items-end">
          <div style={{ minWidth: 300 }}>
            <label className="label" htmlFor="remake-mode">{es ? "Cómo" : "How"}</label>
            <select id="remake-mode" data-testid="remake-mode" className="field" value={source === "image" ? "rebuild" : mode} disabled={source === "image"}
              onChange={(e) => { setMode(e.target.value); setRounds(e.target.value === "copy" ? 4 : 6); }}>
              <option value="copy">{es ? "Copiar la página (su HTML, CSS y recursos)" : "Copy the page (its HTML, CSS and files)"}</option>
              <option value="rebuild">{es ? "Reconstruir con el modelo (HTML y CSS nuevos)" : "Rebuild with the model (new HTML and CSS)"}</option>
            </select>
          </div>
          <div style={{ width: 110 }}>
            <label className="label" htmlFor="remake-rounds">{es ? "Rondas máx." : "Max rounds"}</label>
            <input id="remake-rounds" type="number" min="1" max="20" className="field" value={rounds} onChange={(e) => setRounds(e.target.value)} />
          </div>
          <div style={{ width: 140 }}>
            <label className="label" htmlFor="remake-widths">{es ? "Anchuras (px)" : "Widths (px)"}</label>
            <input id="remake-widths" className="field" value={widths} disabled={source === "image"} onChange={(e) => setWidths(e.target.value)} />
          </div>
          <div style={{ width: 110 }}>
            <label className="label" htmlFor="remake-pass">{es ? "Pasa con (%)" : "Passes at (%)"}</label>
            <input id="remake-pass" type="number" min="50" max="100" step="0.1" className="field" value={passScore} onChange={(e) => setPassScore(e.target.value)} />
          </div>
          {source === "url" && mode === "copy" && (
            <label className="flex gap-2 items-center text-[13px]" style={{ paddingBottom: 8 }}>
              <input type="checkbox" checked={keepScripts} onChange={(e) => setKeepScripts(e.target.checked)} />
              {es ? "Conservar los scripts del original" : "Keep the original's scripts"}
            </label>
          )}
        </div>
        <div>
          <label className="label" htmlFor="remake-note">{es ? "Indicaciones para el modelo (opcional)" : "Instructions for the model (optional)"}</label>
          <textarea id="remake-note" className="field" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <div><button type="submit" className="btn btn-primary" data-testid="remake-run" disabled={busy}>{busy ? (es ? "Empezando…" : "Starting…") : (es ? "Rehacer" : "Remake")}</button></div>
      </form>

      <Benchmark es={es} notify={notify} openRemake={open} />

      {project && (
        <div className="flex flex-col gap-3" data-testid="remake-project" data-status={project.status} data-passed={project.passed ? "true" : "false"}>
          <div className="panel flex flex-col gap-2" style={{ borderColor: project.passed ? "var(--ok)" : project.status === "failed" ? "var(--danger)" : undefined }}>
            <div className="flex gap-3 items-center flex-wrap">
              <span className={st[2]} data-testid="remake-status">{es ? st[0] : st[1]}</span>
              {project.best_score !== null && project.best_score !== undefined && (
                <span className={`chip ${project.passed ? "chip-ok" : ""}`}>{es ? "Mejor" : "Best"}: {project.best_score} %</span>
              )}
              <span className="text-[14px] font-semibold" style={{ wordBreak: "break-all" }}>{project.source.url || (es ? "Captura de la página" : "Page screenshot")}</span>
              <span className="help">{project.mode === "copy" ? (es ? "copia de la página" : "page copy") : (es ? "reconstrucción con el modelo" : "model rebuild")}{project.model ? ` · ${project.model}` : ""}</span>
            </div>
            <div className="help" data-testid="remake-phase">{project.phase}</div>
            <div className="flex gap-2 flex-wrap items-end">
              {working ? (
                <button type="button" className="btn btn-sm" data-testid="remake-stop" onClick={() => act(() => api.remakeStop(project.id))}>{es ? "Parar" : "Stop"}</button>
              ) : (
                <>
                  <div style={{ width: 90 }}>
                    <label className="label" htmlFor="remake-more">{es ? "Rondas" : "Rounds"}</label>
                    <input id="remake-more" type="number" min="1" max="20" className="field" value={more} onChange={(e) => setMore(e.target.value)} />
                  </div>
                  <div style={{ minWidth: 260, flex: 1 }}>
                    <label className="label" htmlFor="remake-more-note">{es ? "Nuevas indicaciones (opcional)" : "New instructions (optional)"}</label>
                    <input id="remake-more-note" className="field" value={moreNote} onChange={(e) => setMoreNote(e.target.value)} />
                  </div>
                  <button type="button" className="btn btn-sm" data-testid="remake-continue"
                    onClick={() => act(() => api.remakeContinue(project.id, { rounds: Number(more) || 2, note: moreNote.trim() }))}>{es ? "Seguir corrigiendo" : "Keep fixing"}</button>
                </>
              )}
              {project.best_round !== null && project.best_round !== undefined && <a className="btn btn-sm" data-testid="remake-download" href={at(project.download_url)}>{es ? "Descargar ZIP" : "Download ZIP"}</a>}
              <a className="btn btn-sm" href={at(project.report_url)} target="_blank" rel="noreferrer">{es ? "Informe" : "Report"}</a>
              <button type="button" className="btn btn-sm" onClick={() => remove(project.id)}>{es ? "Borrar" : "Delete"}</button>
            </div>
          </div>

          <div className="panel" data-testid="remake-rounds">
            <h2 className="text-[15px] font-semibold mb-2">{es ? "Rondas" : "Rounds"}</h2>
            {project.rounds.length === 0 ? <Empty>{working ? (es ? "Preparando la primera ronda…" : "Preparing the first round…") : (es ? "Sin rondas." : "No rounds.")}</Empty> : (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead><tr className="help"><th align="left">#</th><th align="left">{es ? "Qué se hizo" : "What was done"}</th><th align="left">{es ? "Paridad" : "Parity"}</th><th align="left">{es ? "Resultado" : "Result"}</th><th /></tr></thead>
                <tbody>
                  {project.rounds.map((r) => (
                    <tr key={r.n} data-testid="remake-round" data-kept={r.kept ? "true" : "false"} style={{ borderTop: "1px solid var(--line)", background: r.n === shown ? "rgba(127,127,127,.10)" : undefined }}>
                      <td className="py-1">{r.n}</td>
                      <td className="text-[13px]"><span className="chip" style={{ marginRight: 6 }}>{es ? KIND[r.kind]?.[0] : KIND[r.kind]?.[1]}</span>{r.note}{r.error ? <div className="help" style={{ color: "var(--danger)" }}>{r.error}</div> : null}</td>
                      <td className="help">{(r.widths || []).map((w) => `${w.width} px ${w.score} %${w.passed ? " ✓" : ""}`).join(" · ") || "—"}</td>
                      <td>
                        {r.passed && <span className="chip chip-ok">{es ? "pasa" : "pass"}</span>}{" "}
                        {r.parity_id && !r.kept && <span className="chip">{es ? "deshecha" : "undone"}</span>}
                        {r.kept && project.rounds[project.best_round]?.n === r.n && <span className="chip chip-ok">{es ? "mejor" : "best"}</span>}
                      </td>
                      <td>{r.parity_id && <button type="button" className="btn btn-sm" onClick={() => { setRoundN(r.n); setTab(0); }}>{es ? "Comparar" : "Compare"}</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {run && width && (
            <div className="panel flex flex-col gap-2" data-testid="remake-compare">
              <div className="flex gap-2 flex-wrap items-center">
                <h2 className="text-[15px] font-semibold" style={{ margin: 0 }}>{es ? `Comparación de la ronda ${shown}` : `Round ${shown} comparison`}</h2>
                {run.widths.map((w, i) => (
                  <button key={w.width} type="button" className={`btn btn-sm ${i === tab ? "btn-active" : ""}`} onClick={() => setTab(i)}>
                    {w.width} px · {w.score === null ? "—" : `${w.score} %`} {w.passed ? "✓" : "✗"}
                  </button>
                ))}
                <a className="btn-link ml-auto" href={at(run.report_url)} target="_blank" rel="noreferrer">{es ? "Página de prueba" : "Test page"}</a>
              </div>
              <p className="help" style={{ margin: 0 }}>
                {es ? "Altura" : "Height"}: {es ? "referencia" : "reference"} {width.reference_height} px, {es ? "candidata" : "candidate"} {width.candidate_height} px. {es ? "Pantallas que fallan" : "Failing screens"}: {width.failing_screens.length ? width.failing_screens.join(", ") : (es ? "ninguna" : "none")}.
              </p>
              <Slider key={`${run.id}-${width.width}`} width={width} es={es} />
            </div>
          )}

          {project.best_round !== null && project.best_round !== undefined && (
            <div className="panel flex flex-col gap-2">
              <div className="flex gap-2 flex-wrap">
                {[["preview", es ? "Resultado" : "Result"], ["code", es ? "Código" : "Code"], ["pieces", es ? "Piezas del original" : "Original's pieces"]].map(([k, l]) => (
                  <button key={k} type="button" className={`btn btn-sm ${view === k ? "btn-active" : ""}`} data-testid={`remake-view-${k}`} aria-pressed={view === k} onClick={() => setView(k)}>{l}</button>
                ))}
              </div>
              {view === "preview" && <Preview project={project} es={es} />}
              {view === "code" && <Code project={project} es={es} />}
              {view === "pieces" && <Pieces project={project} es={es} />}
            </div>
          )}
        </div>
      )}

      <div className="panel" data-testid="remake-history">
        <h2 className="text-[15px] font-semibold mb-2">{es ? "Proyectos" : "Projects"}</h2>
        {history.length === 0 ? <Empty>{es ? "Todavía no hay ninguno." : "None yet."}</Empty> : (
          <ul className="list-none p-0 m-0 flex flex-col gap-2">
            {history.map((h) => {
              const s = STATUS[h.status] || STATUS.queued;
              return (
                <li key={h.id} className="flex gap-3 items-center flex-wrap" data-testid="remake-history-item">
                  <span className={s[2]}>{es ? s[0] : s[1]}</span>
                  {h.passed && <span className="chip chip-ok">{es ? "pasa" : "pass"}</span>}
                  <span className="text-[13px]" style={{ minWidth: 200, wordBreak: "break-all" }}>{h.label || h.source}</span>
                  <span className="help">{h.mode === "copy" ? (es ? "copia" : "copy") : (es ? "modelo" : "model")} · {h.rounds} {es ? "rondas" : "rounds"}{h.best_score !== null && h.best_score !== undefined ? ` · ${h.best_score} %` : ""} · {when(h.created_ts)}</span>
                  <button type="button" className="btn btn-sm ml-auto" onClick={() => { setRoundN(null); setTab(0); open(h.id); }}>{es ? "Abrir" : "Open"}</button>
                  <button type="button" className="btn btn-sm" onClick={() => remove(h.id)}>{es ? "Borrar" : "Delete"}</button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
