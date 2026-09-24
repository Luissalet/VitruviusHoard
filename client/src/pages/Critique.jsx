import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { Empty, SeverityChip, ScoreDial } from "../components/ui.jsx";
import { clock, fileRelPath } from "../format.js";

// The probe reports fonts as { loaded: [...], h1, h2, p, button } and colours as
// { color, background } pairs; flatten both for display.
function fontList(fonts) {
  if (!fonts) return [];
  const out = new Set(fonts.loaded || []);
  for (const key of ["h1", "h2", "p", "button"]) {
    const fam = (fonts[key] || "").split(",")[0].replace(/["']/g, "").trim();
    if (fam) out.add(fam);
  }
  return Array.from(out);
}

function colorList(colors) {
  if (!colors) return [];
  const out = [];
  for (const c of colors) {
    for (const v of [typeof c === "string" ? c : c.background, typeof c === "string" ? null : c.color]) {
      if (!v || /rgba\(.*,\s*0\)/.test(v) || v === "transparent") continue;
      if (!out.includes(v)) out.push(v);
    }
  }
  return out;
}

const WIDTHS = [390, 1024, 1440];

function findingsByArea(findings) {
  const groups = {};
  for (const f of findings || []) {
    const key = f.area || "other";
    (groups[key] = groups[key] || []).push(f);
  }
  return groups;
}

function RenderView({ render, t }) {
  if (!render) return null;
  if (render.metrics?.error) {
    return (
      <div className="mt-4 rounded-md border p-3 text-[13px]" style={{ background: "var(--danger-bg)", borderColor: "#e5534b66" }}>
        {t("critique_no_browser")}
      </div>
    );
  }
  const groups = findingsByArea(render.lint?.findings);
  return (
    <div className="mt-4 flex flex-col gap-4">
      <div className="flex gap-3 overflow-x-auto pb-2">
        {render.files?.map((f) => (
          <figure key={f.width} className="shrink-0" style={{ width: Math.min(f.width, 320) }}>
            <div className="rounded-md border overflow-y-auto" style={{ borderColor: "var(--line)", maxHeight: 440, background: "#fff" }}>
              <img
                src={api.renderFileUrl(render.id, fileRelPath(f.path, render.id))}
                alt={`${f.width}px`}
                className="w-full block"
                loading="lazy"
              />
            </div>
            <figcaption className="help text-center mt-1">{f.width}px</figcaption>
          </figure>
        ))}
      </div>

      <div className="panel">
        <h3 className="text-[13px] font-semibold mb-2">{t("critique_metrics")}</h3>
        <div className="grid gap-3 md:grid-cols-3 text-[12px]">
          <div>
            <div className="label">{t("critique_fonts")}</div>
            <div className="flex flex-wrap gap-1">
              {fontList(render.metrics?.fonts).map((f) => <span key={f} className="chip">{f}</span>)}
              {!fontList(render.metrics?.fonts).length && <span className="help">—</span>}
            </div>
          </div>
          <div>
            <div className="label">{t("critique_colors")}</div>
            <div className="flex flex-wrap gap-1">
              {colorList(render.metrics?.colors).slice(0, 14).map((c, i) => (
                <span key={i} className="swatch" style={{ background: c, width: 18, height: 18, display: "inline-block", borderRadius: 4, border: "1px solid var(--line)" }} title={c} />
              ))}
              {!colorList(render.metrics?.colors).length && <span className="help">—</span>}
            </div>
          </div>
          <div>
            <div className="label">{t("critique_libs")}</div>
            <div className="flex flex-wrap gap-1">
              {(render.metrics?.libs || []).map((l) => <span key={l} className="chip">{l}</span>)}
              {!render.metrics?.libs?.length && <span className="help">—</span>}
            </div>
          </div>
        </div>
      </div>

      <div className="panel">
        <h3 className="text-[13px] font-semibold mb-2">{t("critique_findings")}</h3>
        {!Object.keys(groups).length && <div className="help">{t("critique_findings_empty")}</div>}
        <div className="flex flex-col gap-3">
          {Object.entries(groups).map(([area, findings]) => (
            <div key={area}>
              <div className="text-[12px] font-semibold mb-1" style={{ color: "var(--muted)" }}>{area}</div>
              <div className="flex flex-col gap-2">
                {findings.map((f, i) => (
                  <div key={i} className="card">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-[13px]">{f.title}</span>
                      <SeverityChip severity={f.severity} t={t} />
                    </div>
                    <div className="text-[13px] mt-1">{f.detail}</div>
                    {f.fix && <div className="help mt-1"><strong>{t("critique_fix")}:</strong> {f.fix}</div>}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function CritiqueView({ critique, t }) {
  if (!critique) return null;
  const groups = findingsByArea(critique.findings);
  return (
    <div className="panel mt-4">
      <div className="flex items-center gap-4 flex-wrap">
        <ScoreDial score={critique.score} />
        <div className="flex-1 min-w-[200px]">
          <h3 className="text-[13px] font-semibold mb-1">{t("critique_summary")}</h3>
          <p className="text-[13px]">{critique.summary}</p>
          {critique.vision_model && <div className="help mt-1">{critique.vision_model}</div>}
        </div>
      </div>
      <div className="flex flex-col gap-2 mt-4">
        {Object.entries(groups).map(([area, findings]) => (
          <div key={area}>
            <div className="text-[12px] font-semibold mb-1" style={{ color: "var(--muted)" }}>{area}</div>
            {findings.map((f, i) => (
              <div key={i} className="card mb-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-[13px]">{f.title}</span>
                  <SeverityChip severity={f.severity} t={t} />
                </div>
                <div className="text-[13px] mt-1">{f.detail}</div>
                {f.fix && <div className="help mt-1"><strong>{t("critique_fix")}:</strong> {f.fix}</div>}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Critique() {
  const { t, notify, lang } = useApp();
  const [html, setHtml] = useState("");
  const [url, setUrl] = useState("");
  const [widths, setWidths] = useState(WIDTHS);
  const [dark, setDark] = useState(false);
  const [render, setRender] = useState(null);
  const [critique, setCritique] = useState(null);
  const [busyRender, setBusyRender] = useState(false);
  const [busyCritique, setBusyCritique] = useState(false);
  const [history, setHistory] = useState(null);

  const loadHistory = async () => {
    try {
      const res = await api.renders(30);
      setHistory(res.renders);
    } catch (e) {
      notify(e.message);
    }
  };
  useEffect(() => { loadHistory(); }, []);

  const toggleWidth = (w) => {
    setWidths((prev) => (prev.includes(w) ? prev.filter((x) => x !== w) : [...prev, w].sort((a, b) => a - b)));
  };

  const doRender = async () => {
    if (!html.trim() && !url.trim()) return;
    setBusyRender(true);
    setCritique(null);
    try {
      const body = { widths: widths.length ? widths : WIDTHS, dark, full_page: true, lint: true };
      if (html.trim()) body.html = html;
      else body.url = url;
      const row = await api.renderCreate(body);
      setRender(row);
      loadHistory();
    } catch (e) {
      notify(e.message);
    } finally {
      setBusyRender(false);
    }
  };

  const doCritique = async () => {
    if (!render) return;
    setBusyCritique(true);
    try {
      const res = await api.renderCritique(render.id, { use_vision: true });
      setCritique(res);
    } catch (e) {
      notify(e.message);
    } finally {
      setBusyCritique(false);
    }
  };

  const openHistory = async (id) => {
    try {
      const row = await api.render(id);
      setRender(row);
      setCritique(null);
    } catch (e) {
      notify(e.message);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-[20px] font-semibold">{t("nav_critique")}</h1>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div>
          <div className="panel">
            <div>
              <label className="label" htmlFor="critique-html">{t("critique_html")}</label>
              <textarea id="critique-html" className="field" rows={8} placeholder={t("critique_html_ph")} value={html} onChange={(e) => setHtml(e.target.value)} />
            </div>
            <div className="mt-3">
              <label className="label" htmlFor="critique-url">{t("critique_url")}</label>
              <input id="critique-url" className="field" placeholder={t("critique_url_ph")} value={url} onChange={(e) => setUrl(e.target.value)} />
            </div>
            <div className="flex items-center gap-4 flex-wrap mt-3">
              <div>
                <div className="label">{t("critique_widths")}</div>
                <div className="flex gap-1">
                  {WIDTHS.map((w) => (
                    <button
                      key={w}
                      type="button"
                      className={`btn btn-sm ${widths.includes(w) ? "btn-active" : ""}`}
                      aria-pressed={widths.includes(w)}
                      onClick={() => toggleWidth(w)}
                    >
                      {w}
                    </button>
                  ))}
                </div>
              </div>
              <label className="flex items-center gap-2 text-[13px]">
                <input type="checkbox" checked={dark} onChange={(e) => setDark(e.target.checked)} />
                {t("critique_dark")}
              </label>
            </div>
            <div className="flex gap-2 mt-4">
              <button type="button" className="btn btn-primary" onClick={doRender} disabled={busyRender || (!html.trim() && !url.trim())}>
                {busyRender ? t("critique_rendering") : t("critique_render")}
              </button>
              <button type="button" className="btn" onClick={doCritique} disabled={!render || busyCritique}>
                {busyCritique ? t("critique_critiquing") : t("critique_with_vision")}
              </button>
            </div>
          </div>

          {!render && <div className="mt-4"><Empty>{t("critique_empty")}</Empty></div>}
          <RenderView render={render} t={t} />
          <CritiqueView critique={critique} t={t} />
        </div>

        <div className="panel">
          <h2 className="text-[14px] font-semibold mb-3">{t("critique_history")}</h2>
          {!history?.length && <div className="help">{t("critique_history_empty")}</div>}
          <div className="flex flex-col gap-2">
            {history?.map((r) => (
              <button
                key={r.id}
                type="button"
                className="card text-left"
                onClick={() => openHistory(r.id)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-[13px] truncate">{r.title || r.url || r.id}</span>
                  <span className="help">{clock(r.created_ts, lang)}</span>
                </div>
                <div className="help mt-1">{(r.widths || []).join(", ")}px {r.lint?.score !== undefined ? `· ${r.lint.score}` : ""}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
