import React, { useEffect, useState } from "react";
import { api } from "../api.js";

// "Import from Figma": a frame link (needs the token saved in Settings) or the JSON of GET /v1/files/:key/nodes pasted in.
// The result is a design project: compact spec, HTML/CSS render, extracted design system, critique and the pixel difference
// with Figma's own PNG.
// The pixel difference is measured over the canvas of both images: rows only one of them has count as different, and a
// render scaled to the frame width or of another height is labelled as such, never as a full-frame match.
export function compareText(c, L) {
  if (!c || c.diff_pct === undefined || c.diff_pct === null) return "";
  let s = `${L("diferencia con Figma", "difference with Figma")} ${c.diff_pct}%`;
  if (!c.scope) return s;
  if (c.scope === "full") return `${s} (${L("mismo tamaño", "same size")} ${c.width}×${c.height})`;
  const parts = [`Figma ${c.reference_size[0]}×${c.reference_size[1]}`, `render ${c.render_size[0]}×${c.render_size[1]}`];
  if (c.render_scale !== 1) parts.push(L(`render escalado ×${c.render_scale}`, `render scaled ×${c.render_scale}`));
  if (c.scope === "partial") {
    parts.push(L(`cobertura ${Math.round(c.coverage * 100)}%`, `coverage ${Math.round(c.coverage * 100)}%`));
    if (c.missing_rows) parts.push(L(`${c.missing_rows} filas de Figma sin render`, `${c.missing_rows} Figma rows not rendered`));
    if (c.extra_rows) parts.push(L(`${c.extra_rows} filas de más en el render`, `${c.extra_rows} extra render rows`));
    parts.push(L(`${c.overlap_diff_pct}% en la zona común`, `${c.overlap_diff_pct}% in the shared area`));
  }
  const label = c.scope === "partial" ? L("comparación parcial", "partial comparison") : L("normalizada", "normalized");
  return `${s} · ${label}: ${parts.join(", ")}`;
}

export default function FigmaImport({ lang, notify, onOpenTokens }) {
  const L = (es, en) => (lang === "es" ? es : en);
  const [open, setOpen] = useState(false);
  const [link, setLink] = useState("");
  const [json, setJson] = useState("");
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (open) api.figmaImports(8).then(setState).catch(() => setState(null));
  }, [open, result]);

  const run = async () => {
    setBusy(true);
    setResult(null);
    try {
      const body = {};
      if (json.trim()) body.nodes_json = JSON.parse(json);
      if (link.trim()) body.link = link.trim();
      setResult(await api.figmaImport(body));
    } catch (e) {
      notify(e instanceof SyntaxError ? L("El JSON no es válido.", "That JSON does not parse.") : e.message);
    } finally {
      setBusy(false);
    }
  };

  const canRun = (link.trim() && state?.token_set) || json.trim();

  return (
    <>
      <button type="button" className="btn" onClick={() => setOpen(true)} data-testid="figma-open">{L("Importar de Figma", "Import from Figma")}</button>
      {open && (
        <div role="dialog" aria-modal="true" aria-label={L("Importar de Figma", "Import from Figma")} data-testid="figma-dialog"
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.45)", zIndex: 50, display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "6vh 16px", overflowY: "auto" }}
          onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
          <div className="panel" style={{ width: "min(760px, 100%)", background: "var(--panel, var(--bg))" }}>
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-[15px] font-semibold">{L("Importar un frame de Figma", "Import a Figma frame")}</h2>
              <button type="button" className="btn btn-sm" onClick={() => setOpen(false)}>{L("Cerrar", "Close")}</button>
            </div>
            <div className="mt-3">
              <label className="label" htmlFor="figma-link">{L("Enlace al frame", "Frame link")}</label>
              <input id="figma-link" className="field" value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://www.figma.com/design/<key>/...?node-id=12-34" />
              {state && !state.token_set && (
                <div className="help mt-1" data-testid="figma-token-help">
                  {L("No hay token de Figma. ", "No Figma token yet. ")}{state.help} <a className="btn-link" href="#/settings">{L("Ir a Ajustes", "Open Settings")}</a>
                </div>
              )}
              {state?.token_set && <div className="help mt-1">{L("Token guardado en Ajustes.", "Token saved in Settings.")}</div>}
            </div>
            <details className="mt-3" open={!state?.token_set}>
              <summary className="text-[13px] cursor-pointer">{L("…o pega el JSON de la API (GET /v1/files/:key/nodes)", "…or paste the API JSON (GET /v1/files/:key/nodes)")}</summary>
              <textarea className="field mono mt-2" rows={6} value={json} onChange={(e) => setJson(e.target.value)} aria-label="nodes JSON" data-testid="figma-json" />
            </details>
            <div className="flex gap-2 mt-3">
              <button type="button" className="btn btn-primary" onClick={run} disabled={busy || !canRun} data-testid="figma-import">
                {busy ? L("Importando…", "Importing…") : L("Importar", "Import")}
              </button>
            </div>
            {result && (
              <div className="card mt-3" data-testid="figma-result">
                <div className="font-semibold text-[13px]">{result.name} · {result.width}×{result.height}px</div>
                <div className="help mt-1">{result.counts.nodes} {L("nodos", "nodes")} · {result.counts.styles} {L("estilos con nombre", "named styles")} ({result.counts.style_uses} {L("usos", "uses")})
                  {result.critique?.score !== undefined && ` · ${L("crítica", "critique")} ${result.critique.score}/10 (${result.critique.gate})`}</div>
                {compareText(result.compare, L) && (
                  <div className="help mt-1" style={result.compare.scope === "partial" ? { color: "var(--warn)" } : undefined} data-testid="figma-compare">
                    {compareText(result.compare, L)}
                  </div>
                )}
                <div className="flex gap-2 mt-2 flex-wrap">
                  <a className="btn btn-sm" href={api.figmaFileUrl(result.import_id, "page.html")} target="_blank" rel="noreferrer">HTML</a>
                  <a className="btn btn-sm" href={api.figmaFileUrl(result.import_id, "spec.json")} target="_blank" rel="noreferrer">spec.json</a>
                  {result.compare?.diff_image && <a className="btn btn-sm" href={api.figmaFileUrl(result.import_id, "diff.png")} target="_blank" rel="noreferrer" data-testid="figma-diff">{L("Diferencia (PNG)", "Difference (PNG)")}</a>}
                  <a className="btn btn-sm" href={`#/critique/${result.render_id}`}>{L("Ver render", "Open render")}</a>
                  {result.tokens_id && <button type="button" className="btn btn-sm" onClick={() => { setOpen(false); onOpenTokens && onOpenTokens(result.tokens_id); }}>{L("Abrir design system", "Open design system")}</button>}
                </div>
                <div className="grid gap-2 mt-3" style={{ gridTemplateColumns: result.figma_image ? "1fr 1fr" : "1fr" }}>
                  {result.figma_image && <figure><img src={api.figmaFileUrl(result.import_id, "figma.png")} alt="Figma" className="w-full block rounded border" /><figcaption className="help">Figma</figcaption></figure>}
                  <figure>
                    {(() => {
                      const scale = Math.min(1, (result.figma_image ? 330 : 680) / Math.max(1, result.width));
                      return (
                        <div style={{ width: result.width * scale, height: result.height * scale, overflow: "hidden", border: "1px solid var(--line)", borderRadius: 6, background: "#fff" }}>
                          <iframe title="import" src={api.figmaFileUrl(result.import_id, "page.html")}
                            style={{ width: result.width, height: result.height, border: 0, transform: `scale(${scale})`, transformOrigin: "0 0" }} />
                        </div>
                      );
                    })()}
                    <figcaption className="help">HTML/CSS</figcaption>
                  </figure>
                </div>
              </div>
            )}
            {!!state?.imports?.length && (
              <div className="mt-3">
                <div className="label">{L("Importaciones recientes", "Recent imports")}</div>
                {state.imports.map((i) => <div key={i.import_id} className="help">{i.name} · {i.import_id} {compareText(i.compare, L) ? `· ${compareText(i.compare, L)}` : ""}</div>)}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
