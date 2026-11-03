import React, { useEffect, useState } from "react";
import PatternPicker from "../components/PatternPicker.jsx";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { useCopilotForm, useCopilotObjects, useCopilotRefresh } from "../copilot-hooks.js";
import { Empty, SeverityChip, ScoreDial } from "../components/ui.jsx";
import GatePanel from "../components/GatePanel.jsx";
import RulesPanel, { TierChip } from "../components/RulesPanel.jsx";
import ThemeDealer from "../components/ThemeDealer.jsx";
import SlopAudit from "../components/SlopAudit.jsx";
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
                      <span className="flex gap-1"><TierChip tier={f.tier} t={t} /><SeverityChip severity={f.severity} t={t} /></span>
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
                  <span className="flex gap-1"><TierChip tier={f.tier} t={t} />{f.waived && <span className="chip">{t("dq_waived")}</span>}<SeverityChip severity={f.severity} t={t} /></span>
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

function AssayView({ assay, t }) {
  if (!assay) return null;
  if (assay.error) {
    return (
      <div className="panel mt-4">
        <h3 className="text-[13px] font-semibold mb-1">{t("assay_title")}</h3>
        <div className="help">{assay.error}{assay.hint ? ` — ${assay.hint}` : ""}</div>
      </div>
    );
  }
  return (
    <div className="panel mt-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-[13px] font-semibold">{t("assay_title")}</h3>
        <span className={`chip ${assay.works ? "chip-ok" : "chip-danger"}`}>
          {assay.unchecked ? t("assay_unchecked") : assay.works ? t("assay_works") : t("assay_broken")} · {assay.passed}/{assay.planned}
        </span>
      </div>
      <div className="help mt-1">{t("assay_surface")}: {(assay.surface || []).map((s) => `${s.kind} “${s.label || s.selector}”`).join(", ") || "—"}</div>
      {!!assay.failing?.length && (
        <div className="flex flex-col gap-2 mt-3">
          {assay.failing.map((c) => (
            <div key={c.id} className="card">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-[13px]">{c.what}</span>
                <span className="chip chip-danger">{c.id}</span>
              </div>
              {c.detail && <div className="text-[12px] mt-1" style={{ color: "var(--muted)" }}>{c.detail}</div>}
              {!!c.acts?.length && <div className="mono mt-1" style={{ color: "var(--muted)" }}>{JSON.stringify(c.acts)}</div>}
            </div>
          ))}
        </div>
      )}
      {assay.kept && (
        <div className="help mt-2" data-testid="kept-result">
          {assay.kept.ok ? t("dq_kept_ok") : `${t("dq_kept_missing")}: ${Object.entries(assay.kept.missing_count || {}).filter(([, n]) => n).map(([k, n]) => `${n} ${k}`).join(", ")}`}
        </div>
      )}
      <div className="help mt-2">{Math.round((assay.ms || 0) / 1000)} s</div>
    </div>
  );
}

export default function Critique({ param }) {
  const { t, notify, lang } = useApp();
  const [draft, setDraft] = useState({ html: "", previous: [] });
  const html = draft.html;
  const setHtml = (value) => setDraft((current) => ({ ...current, html: value }));
  const applyPattern = (source) => setDraft((current) => ({ html: source, previous: [...current.previous, current.html] }));
  const restoreDraft = () => setDraft((current) => current.previous.length
    ? { html: current.previous.at(-1), previous: current.previous.slice(0, -1) } : current);
  const [url, setUrl] = useState("");
  const [widths, setWidths] = useState(WIDTHS);
  const [dark, setDark] = useState(false);
  useCopilotForm("critique-draft", { initial: { html: "", url: "", widths: WIDTHS, dark: false }, current: { html, url, widths, dark } });
  const [render, setRender] = useState(null);
  const [critique, setCritique] = useState(null);
  const [busyRender, setBusyRender] = useState(false);
  const [busyCritique, setBusyCritique] = useState(false);
  const [assay, setAssay] = useState(null);
  const [busyAssay, setBusyAssay] = useState(false);
  const [checkControl, setCheckControl] = useState("");
  const [checkText, setCheckText] = useState("");
  const [history, setHistory] = useState(null);
  const [tokensList, setTokensList] = useState([]);
  const [tokensId, setTokensId] = useState("");
  const [cleanReview, setCleanReview] = useState(false);
  const [waivers, setWaivers] = useState({});
  const [keptList, setKeptList] = useState([]);
  const [keptId, setKeptId] = useState("");
  const [keptLabel, setKeptLabel] = useState("");
  const [keptSaved, setKeptSaved] = useState(null);
  const loadKept = () => api.keptList(30).then((r) => setKeptList(r.kept || [])).catch(() => {});
  useEffect(() => {
    api.tokensList(30).then((r) => setTokensList(r.design_systems || [])).catch(() => {});
    loadKept();
  }, []);

  const loadHistory = async () => {
    try {
      const res = await api.renders(30);
      setHistory(res.renders);
    } catch (e) {
      notify(e.message);
    }
  };
  useEffect(() => { loadHistory(); }, []);
  useCopilotRefresh(loadHistory);
  useCopilotObjects(render ? [{ kind: "render", id: render.id }] : []);

  const toggleWidth = (w) => {
    setWidths((prev) => (prev.includes(w) ? prev.filter((x) => x !== w) : [...prev, w].sort((a, b) => a - b)));
  };

  const doRender = async () => {
    if (!html.trim() && !url.trim()) return;
    setBusyRender(true);
    setCritique(null);
    setAssay(null);
    try {
      const body = { widths: widths.length ? widths : WIDTHS, dark, full_page: true, lint: true };
      if (tokensId) body.tokens_id = tokensId;
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

  const doAssay = async () => {
    if (!html.trim() && !url.trim()) return;
    if (!!checkControl.trim() !== !!checkText.trim()) {
      notify(t("assay_expect_pair"));
      return;
    }
    setBusyAssay(true);
    setAssay(null);
    try {
      const body = html.trim() ? { html } : { url };
      if (keptId) body.kept = keptId;
      if (checkControl.trim()) body.criteria = [{
        id: "requested-click-result", what: checkText.trim(),
        acts: [{ click: checkControl.trim() }], expect: { want: checkText.trim() },
        control: checkControl.trim(),
      }];
      setAssay(await api.assay(body));
    } catch (e) {
      notify(e.message);
    } finally {
      setBusyAssay(false);
    }
  };

  const saveKept = async () => {
    if (!html.trim() && !url.trim()) return;
    setBusyAssay(true);
    try {
      const body = html.trim() ? { html } : { url };
      const res = await api.assay({ ...body, before: true, snapshot_only: true, label: keptLabel.trim() });
      setKeptSaved(res.kept);
      setKeptId(res.kept?.id || "");
      loadKept();
    } catch (e) {
      notify(e.message);
    } finally {
      setBusyAssay(false);
    }
  };

  const doCritique = async (withWaivers = false) => {
    if (!render) return;
    setBusyCritique(true);
    try {
      const body = { use_vision: true, clean_review: cleanReview };
      if (tokensId) body.tokens_id = tokensId;
      if (withWaivers) {
        body.waivers = Object.entries(waivers).filter(([, reason]) => reason && reason.trim()).map(([rule, reason]) => ({ rule, reason: reason.trim() }));
      } else {
        setWaivers({});
      }
      const res = await api.renderCritique(render.id, body);
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
          <PatternPicker onApply={applyPattern} />
          {draft.previous.length > 0 && <div className="flex gap-3 items-center flex-wrap mb-4" role="status">
            <span className="help">{lang === "es" ? `Fuente aplicada. ${draft.previous.length} ${draft.previous.length === 1 ? "borrador guardado" : "borradores guardados"} durante esta edición.` : `Source applied. ${draft.previous.length} ${draft.previous.length === 1 ? "draft retained" : "drafts retained"} during this edit.`}</span>
            <button type="button" className="btn" onClick={restoreDraft}>{lang === "es" ? "Restaurar borrador" : "Restore draft"}</button>
          </div>}
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
            <div className="grid gap-3 md:grid-cols-2 mt-3">
              <div>
                <label className="label" htmlFor="critique-tokens">{t("dq_tokens_system")}</label>
                <select id="critique-tokens" className="field" value={tokensId} onChange={(e) => setTokensId(e.target.value)}>
                  <option value="">{t("dq_tokens_none")}</option>
                  {tokensList.map((x) => <option key={x.id} value={x.id}>{x.name || x.brief?.name || x.id}</option>)}
                </select>
              </div>
              <div>
                <label className="flex items-center gap-2 text-[13px] mt-6">
                  <input type="checkbox" checked={cleanReview} onChange={(e) => setCleanReview(e.target.checked)} />
                  {t("dq_clean_review")}
                </label>
                <div className="help">{t("dq_clean_review_help")}</div>
              </div>
            </div>
            <details className="mt-3">
              <summary className="text-[13px] cursor-pointer">{t("dq_kept_title")}</summary>
              <div className="grid gap-3 md:grid-cols-2 mt-2">
                <div>
                  <label className="label" htmlFor="kept-label">{t("dq_kept_label")}</label>
                  <input id="kept-label" className="field" value={keptLabel} onChange={(e) => setKeptLabel(e.target.value)} />
                  <button type="button" className="btn mt-2" onClick={saveKept} disabled={busyAssay || (!html.trim() && !url.trim())}>{t("dq_kept_save")}</button>
                  {keptSaved && <div className="help mt-1" data-testid="kept-saved">{t("dq_kept_saved")}: {keptSaved.id} · {Object.entries(keptSaved.counts || {}).map(([k, n]) => `${n} ${k}`).join(", ")}</div>}
                </div>
                <div>
                  <label className="label" htmlFor="kept-use">{t("dq_kept_use")}</label>
                  <select id="kept-use" className="field" value={keptId} onChange={(e) => setKeptId(e.target.value)}>
                    <option value="">{t("dq_kept_none")}</option>
                    {keptList.map((k) => <option key={k.id} value={k.id}>{k.label || k.id} · {Object.entries(k.counts || {}).map(([a, n]) => `${n} ${a}`).join(", ")}</option>)}
                  </select>
                </div>
              </div>
            </details>
            <details className="mt-3">
              <summary className="text-[13px] cursor-pointer">{t("assay_expect")}</summary>
              <div className="grid gap-3 md:grid-cols-2 mt-2">
                <div><label className="label" htmlFor="check-control">{t("assay_control")}</label>
                  <input id="check-control" className="field" placeholder="#save" value={checkControl} onChange={(e) => setCheckControl(e.target.value)} /></div>
                <div><label className="label" htmlFor="check-text">{t("assay_expected_text")}</label>
                  <input id="check-text" className="field" value={checkText} onChange={(e) => setCheckText(e.target.value)} /></div>
              </div>
            </details>
            <div className="flex gap-2 flex-wrap mt-4">
              <button type="button" className="btn btn-primary" onClick={doRender} disabled={busyRender || (!html.trim() && !url.trim())}>
                {busyRender ? t("critique_rendering") : t("critique_render")}
              </button>
              <button type="button" className="btn" onClick={() => doCritique(false)} disabled={!render || busyCritique}>
                {busyCritique ? t("critique_critiquing") : t("critique_with_vision")}
              </button>
              <button type="button" className="btn" onClick={doAssay} disabled={busyAssay || (!html.trim() && !url.trim())} title={t("assay_hint")}>
                {busyAssay ? t("assay_running") : t("assay_button")}
              </button>
            </div>
          </div>

          {!render && <div className="mt-4"><Empty>{t("critique_empty")}</Empty></div>}
          <RenderView render={render} t={t} />
          <SlopAudit render={render} html={html} url={url} lang={lang} notify={notify} t={t} initialId={/^[0-9a-f]{12}$/.test(param || "") ? param : null} />
          <GatePanel critique={critique} t={t} waivers={waivers} setWaivers={setWaivers} onApply={() => doCritique(true)} busy={busyCritique} />
          <CritiqueView critique={critique} t={t} />
          <AssayView assay={assay} t={t} />
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
      <ThemeDealer t={t} notify={notify} />
      <RulesPanel t={t} notify={notify} lang={lang} />
    </div>
  );
}
