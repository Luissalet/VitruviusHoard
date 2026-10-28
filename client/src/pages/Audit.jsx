import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { useCopilotForm, useCopilotRefresh } from "../copilot-hooks.js";
import { Empty } from "../components/ui.jsx";

const SEVERITY_CLASS = { critical: "chip chip-danger", high: "chip chip-danger", medium: "chip chip-amber", low: "chip", info: "chip" };
const RATING_CLASS = { good: "chip chip-ok", "needs-improvement": "chip chip-amber", poor: "chip chip-danger" };
const VITALS = [["lcp_ms", "LCP", "ms"], ["inp_ms", "INP", "ms"], ["cls", "CLS", ""], ["fcp_ms", "FCP", "ms"], ["ttfb_ms", "TTFB", "ms"], ["tbt_ms", "TBT", "ms"]];

function scoreColor(score) {
  return score >= 85 ? "var(--ok)" : score >= 60 ? "var(--warn)" : "var(--danger)";
}

function Bar({ score }) {
  return (
    <div style={{ height: 6, borderRadius: 3, background: "var(--surface-2)", overflow: "hidden" }} aria-hidden="true">
      <div style={{ width: `${score ?? 0}%`, height: "100%", background: scoreColor(score ?? 0) }} />
    </div>
  );
}

function Finding({ f, t }) {
  return (
    <li className="card" data-testid="audit-finding" data-finding={f.id}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className={SEVERITY_CLASS[f.severity] || "chip"}>{t(`au_sev_${f.severity}`)}</span>
        {f.judgement && <span className="chip chip-accent" title={t("au_judgement_help")}>{t("au_judgement")}</span>}
        <strong className="text-[13px]">{f.title}</strong>
      </div>
      <p className="help mt-1">{f.description}</p>
      <p className="text-[12.5px] mt-1"><strong>{t("au_fix")}:</strong> {f.recommendation}</p>
      {f.url && <div className="mono mt-1">{f.url}</div>}
    </li>
  );
}

function Category({ c, t }) {
  return (
    <details className="panel" data-testid={`audit-category-${c.id}`} open={c.measured && c.findings.some((f) => !f.judgement && ["critical", "high"].includes(f.severity))}>
      <summary className="flex items-center justify-between gap-3 cursor-pointer flex-wrap">
        <span className="text-[13px] font-semibold">{c.name} <span className="help">· {t("au_weight")} {c.weight}</span></span>
        <span className={c.measured ? "chip" : "chip chip-amber"} data-testid={`audit-score-${c.id}`}>
          {c.measured ? `${c.score}/100` : t("au_unmeasured")}
        </span>
      </summary>
      <div className="mt-2"><Bar score={c.score} /></div>
      {c.findings.length ? (
        <ul className="flex flex-col gap-2 mt-3 list-none p-0">{c.findings.map((f) => <Finding key={f.id} f={f} t={t} />)}</ul>
      ) : (
        <p className="help mt-2">{t("au_no_findings")}</p>
      )}
    </details>
  );
}

function Plan({ plan, t }) {
  return (
    <div className="panel" data-testid="audit-plan">
      <h3 className="text-[13px] font-semibold">{t("au_plan")}</h3>
      <ol className="flex flex-col gap-3 mt-2 list-none p-0">
        {plan.phases.map((p) => (
          <li key={p.phase}>
            <div className="text-[13px]"><strong>{p.phase}. {p.name}</strong> <span className="help">· {p.timeframe} · {p.items.length}</span></div>
            {!!p.items.length && (
              <ul className="mt-1 pl-4 text-[12.5px]" style={{ listStyle: "disc" }}>
                {p.items.slice(0, 8).map((i) => <li key={i.id}>{i.title}{i.url ? <span className="mono"> · {new URL(i.url).pathname}</span> : null}</li>)}
                {p.items.length > 8 && <li className="help">{t("au_more", { n: p.items.length - 8 })}</li>}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

function Vitals({ vitals, t }) {
  if (!vitals) return null;
  if (!vitals.measured) return <div className="panel" data-testid="audit-vitals"><h3 className="text-[13px] font-semibold">Core Web Vitals</h3><p className="help mt-1">{t("au_vitals_none")}: {vitals.reason}</p></div>;
  const m = vitals.metrics || {};
  return (
    <div className="panel" data-testid="audit-vitals">
      <h3 className="text-[13px] font-semibold">Core Web Vitals</h3>
      <p className="help mt-1">{vitals.conditions?.label} · {t("au_lab")}</p>
      <div className="flex gap-2 flex-wrap mt-2">
        {VITALS.map(([key, name, unit]) => m[key] != null && (
          <span key={key} className={RATING_CLASS[vitals.ratings?.[key]] || "chip"} title={t(`au_rating_${(vitals.ratings?.[key] || "good").replace("-", "_")}`)}>
            {name} {key === "cls" ? Number(m[key]).toFixed(3) : Math.round(m[key])}{unit && ` ${unit}`}
          </span>
        ))}
        {m.transfer_bytes != null && <span className="chip">{(m.transfer_bytes / 1024).toFixed(0)} KB · {m.requests} {t("au_requests")}</span>}
      </div>
    </div>
  );
}

function Crawlers({ rows, t }) {
  if (!rows?.length) return null;
  return (
    <div className="panel" data-testid="audit-crawlers">
      <h3 className="text-[13px] font-semibold">{t("au_crawlers")}</h3>
      <p className="help mt-1">{t("au_crawlers_help")}</p>
      <table className="w-full mt-2 text-[12.5px]">
        <thead><tr className="text-left"><th>{t("au_crawler")}</th><th>{t("au_operator")}</th><th>{t("au_purpose")}</th><th>{t("au_state")}</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.crawler}>
              <td className="mono">{r.crawler}</td><td>{r.operator}</td><td>{t(`au_purpose_${r.purpose}`)}</td>
              <td><span className={r.allowed ? "chip chip-ok" : "chip chip-danger"}>{r.allowed ? t("au_allowed") : t("au_blocked")}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Audit() {
  const { t, notify, lang } = useApp();
  const [url, setUrl] = useState("");
  const [pages, setPages] = useState(10);
  const [links, setLinks] = useState(true);
  const [vitals, setVitals] = useState(true);
  const [fresh, setFresh] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [history, setHistory] = useState([]);
  useCopilotForm("audit-draft", { initial: { url: "", pages: 10, links: true, vitals: true }, current: { url, pages, links, vitals } });

  const loadHistory = useCallback(() => api.siteAuditReports().then((r) => setHistory(r.reports || [])).catch(() => setHistory([])), []);
  useEffect(() => { loadHistory(); }, [loadHistory]);
  useCopilotRefresh(loadHistory);

  const run = async (event) => {
    event.preventDefault();
    if (!url.trim()) { notify(t("au_url_needed")); return; }
    setBusy(true);
    setReport(null);
    try {
      const out = await api.siteAudit({ url: url.trim(), max_pages: Number(pages) || 10, check_links: links, vitals, fresh });
      if (out.ok === false) notify(`${out.error}${out.hint ? ` · ${out.hint}` : ""}`);
      else { setReport(out); loadHistory(); }
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };

  const open = async (id) => {
    try { setReport(await api.siteAuditReport(id)); } catch (e) { notify(e.message); }
  };

  const counts = report?.summary?.counts || {};
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[22px] font-semibold">{t("au_title")}</h1>
        <p className="help mt-1" style={{ maxWidth: 760 }}>{t("au_intro")}</p>
      </div>

      <form className="panel flex flex-col gap-3" onSubmit={run} aria-busy={busy}>
        <div>
          <label className="label" htmlFor="audit-url">{t("au_url")}</label>
          <input id="audit-url" data-testid="audit-url" className="field" value={url} onChange={(e) => setUrl(e.target.value)} placeholder={t("au_url_ph")} inputMode="url" autoComplete="url" />
        </div>
        <div className="flex gap-4 flex-wrap items-end">
          <div>
            <label className="label" htmlFor="audit-pages">{t("au_pages")}</label>
            <input id="audit-pages" className="field" style={{ width: 90 }} type="number" min="1" max="40" value={pages} onChange={(e) => setPages(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={links} onChange={(e) => setLinks(e.target.checked)} /> {t("au_links")}</label>
          <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={vitals} onChange={(e) => setVitals(e.target.checked)} /> {t("au_vitals")}</label>
          <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={fresh} onChange={(e) => setFresh(e.target.checked)} /> {t("au_fresh")}</label>
          <button type="submit" className="btn btn-primary" data-testid="audit-run" disabled={busy}>{busy ? t("au_running") : t("au_run")}</button>
        </div>
        {busy && <p className="help" role="status">{t("au_running_help")}</p>}
      </form>

      {report ? (
        <div className="flex flex-col gap-3" data-testid="audit-report">
          <div className="panel flex gap-6 items-center flex-wrap">
            <div style={{ minWidth: 120 }}>
              <div className="text-[44px] font-bold leading-none" data-testid="audit-score" style={{ color: scoreColor(report.score ?? 0) }}>{report.score ?? "—"}</div>
              <div className="help">{t("au_score_of")}</div>
            </div>
            <div className="flex-1" style={{ minWidth: 240 }}>
              <div className="mono">{report.final_url || report.url}</div>
              <div className="help mt-1">
                {new Date(report.audited_at).toLocaleString(lang === "en" ? "en-GB" : "es-ES")} · {t("au_pages_read")}: {report.summary.pages_audited} · {report.summary.requests} {t("au_requests")}
                {report.from_cache ? ` · ${t("au_cached")}` : ""}
              </div>
              <div className="flex gap-2 flex-wrap mt-2">
                {["critical", "high", "medium", "low", "info"].map((s) => <span key={s} className={SEVERITY_CLASS[s]}>{t(`au_sev_${s}`)}: {counts[s] || 0}</span>)}
                <span className="chip chip-accent">{t("au_judgement")}: {report.summary.judgement_total}</span>
              </div>
              {report.previous && (
                <p className="help mt-2" data-testid="audit-previous">{t("au_previous", { score: report.previous.score ?? "—", fixed: report.previous.fixed.length, added: report.previous.new.length })}</p>
              )}
            </div>
          </div>
          {!!report.summary.categories_unmeasured.length && <p className="help" role="note">{t("au_unmeasured_note")}</p>}
          <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
            {report.categories.map((c) => <Category key={c.id} c={c} t={t} />)}
          </div>
          <Plan plan={report.action_plan} t={t} />
          <Vitals vitals={report.vitals} t={t} />
          <Crawlers rows={report.ai_crawlers} t={t} />
          <div className="panel">
            <h3 className="text-[13px] font-semibold">{t("au_limits")}</h3>
            <ul className="mt-1 pl-4 text-[12.5px]" style={{ listStyle: "disc" }}>{report.limits.map((l) => <li key={l}>{l}</li>)}</ul>
            <div className="mt-3 flex gap-2 flex-wrap">
              <button type="button" className="btn btn-sm" onClick={() => {
                const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = `auditoria-${(report.final_url || report.url).replace(/^https?:\/\//, "").replace(/[^a-z0-9]+/gi, "-")}.json`;
                a.click();
                URL.revokeObjectURL(a.href);
              }}>{t("au_download")}</button>
            </div>
          </div>
        </div>
      ) : !busy && <Empty>{t("au_empty")}</Empty>}

      {!!history.length && (
        <div className="panel" data-testid="audit-history">
          <h3 className="text-[13px] font-semibold">{t("au_history")}</h3>
          <ul className="mt-2 flex flex-col gap-1 list-none p-0">
            {history.map((h) => (
              <li key={h.id} className="flex items-center justify-between gap-2 flex-wrap text-[12.5px]">
                <span className="mono">{h.url}</span>
                <span className="help">{new Date(h.audited_at).toLocaleString(lang === "en" ? "en-GB" : "es-ES")} · {h.score ?? "—"}/100</span>
                <button type="button" className="btn btn-sm" onClick={() => open(h.id)}>{t("au_open")}</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
