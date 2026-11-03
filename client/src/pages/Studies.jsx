import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";

const num = (v) => (typeof v === "number" ? Math.round(v * 1000) / 1000 : String(v));

function Study({ id, t, notify }) {
  const [study, setStudy] = useState(null);
  const [view, setView] = useState(null);
  const [weights, setWeights] = useState({});
  useEffect(() => {
    api.study(id).then((s) => {
      setStudy(s);
      setView(s.analysis);
      setWeights(Object.fromEntries(s.criteria.map((c) => [c.id, c.weight])));
    }).catch((e) => notify(e.message));
  }, [id, notify]);
  if (!study) return null;
  const labels = Object.fromEntries(study.alternatives.map((a) => [a.id, a.label]));
  const change = async (criterion, value) => {
    const next = { ...weights, [criterion]: Number(value) };
    setWeights(next);
    try { setView(await api.studyAnalyze(id, { weights: next })); } catch (e) { notify(e.message); }
  };
  return (
    <div className="panel flex flex-col gap-3" data-testid="study">
      <p>{study.brief}</p>
      <div className="flex gap-2 flex-wrap">
        {study.frozen && <span className="chip">{t("st_frozen")}</span>}
        {!view?.complete && <span className="chip chip-amber">{t("st_incomplete")}</span>}
      </div>
      <h3 className="text-[13px] font-semibold">{t("st_weights")}</h3>
      <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))" }}>
        {study.criteria.map((c) => (
          <div key={c.id}>
            <label className="label" htmlFor={`w-${c.id}`}>{c.name} · {c.source} · {c.direction}</label>
            <input id={`w-${c.id}`} className="field" type="range" min="0" max="10" step="0.5" value={weights[c.id] ?? 1} onChange={(e) => change(c.id, e.target.value)} />
          </div>
        ))}
      </div>
      {view?.complete && (
        <>
          <h3 className="text-[13px] font-semibold">{t("st_ranking")}</h3>
          {view.effect && <p role="status" className="help">{view.effect}</p>}
          <ol className="pl-4" style={{ listStyle: "decimal" }}>
            {view.ranking.map((r) => (
              <li key={r.id}>{r.label} <span className="mono">{num(r.score)}</span>{" "}
                {view.frontier.includes(r.id) ? <span className="chip chip-ok">{t("st_frontier")}</span> : <span className="chip chip-danger">{t("st_dominated")} {view.dominated[r.id].by.map((d) => labels[d]).join(", ")}</span>}
              </li>
            ))}
          </ol>
          <h3 className="text-[13px] font-semibold">{t("st_tradeoffs")}</h3>
          <ul className="pl-4" style={{ listStyle: "disc" }}>{view.tradeoffs.map((x, i) => <li key={i}>{x.text}</li>)}</ul>
        </>
      )}
      {study.decision && (
        <div><h3 className="text-[13px] font-semibold">{t("st_decision")}: {study.decision.label}</h3><p>{study.decision.reason}</p></div>
      )}
    </div>
  );
}

function Instrument({ item, t, notify }) {
  const [report, setReport] = useState(null);
  const [explain, setExplain] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setReport(await api.instrumentCheck(item.id, {})); } catch (e) { notify(e.message); } finally { setBusy(false); }
  };
  const show = async () => {
    try { setExplain(await api.instrumentExplain(item.id, {})); } catch (e) { notify(e.message); }
  };
  return (
    <div className="panel flex flex-col gap-2" data-testid="instrument">
      <div className="flex gap-2 flex-wrap items-center">
        <strong>{item.name}</strong><span className="chip">{item.kind}</span>
        {item.examples_ok === true && <span className="chip chip-ok">{t("st_examples_ok")}</span>}
        {item.examples_ok === false && <span className="chip chip-danger">{t("st_examples_bad")}</span>}
        <button type="button" className="btn" onClick={show}>{t("st_explain")}</button>
        <button type="button" className="btn btn-primary" onClick={run} disabled={busy}>{busy ? t("st_checking") : t("st_check")}</button>
      </div>
      <p className="help">{item.spec.description}</p>
      {explain && (
        <div className="overflow-auto"><table className="w-full text-[12.5px]"><tbody>
          {explain.shown.map((r) => <tr key={r.name}><th scope="row" className="text-left">{r.label}</th><td className="mono">{r.formula || "—"}</td><td className="mono">{r.text} {r.unit}</td></tr>)}
        </tbody></table></div>
      )}
      {report && <p role="status" className={report.ok ? "chip chip-ok" : "chip chip-danger"}>{report.ok ? t("st_check_ok") : t("st_check_bad")}</p>}
    </div>
  );
}

export default function Studies() {
  const { t, notify } = useApp();
  const [studies, setStudies] = useState([]);
  const [open, setOpen] = useState(null);
  const [instruments, setInstruments] = useState([]);
  useEffect(() => {
    api.studies().then((r) => setStudies(r.studies)).catch((e) => notify(e.message));
    api.instruments().then((r) => setInstruments(r.instruments)).catch((e) => notify(e.message));
  }, [notify]);
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[22px] font-semibold">{t("st_title")}</h1>
        <p className="help mt-1" style={{ maxWidth: 760 }}>{t("st_intro")}</p>
      </div>
      <h2 className="text-[15px] font-semibold">{t("st_alternatives")}</h2>
      {studies.length === 0 && <p className="help">{t("st_none")}</p>}
      {studies.map((s) => (
        <div key={s.id}>
          <button type="button" className="btn" aria-expanded={open === s.id} onClick={() => setOpen(open === s.id ? null : s.id)}>{s.brief}</button>
          {open === s.id && <Study id={s.id} t={t} notify={notify} />}
        </div>
      ))}
      <h2 className="text-[15px] font-semibold">{t("st_instruments")}</h2>
      {instruments.length === 0 && <p className="help">{t("st_none")}</p>}
      {instruments.map((i) => <Instrument key={i.id} item={i} t={t} notify={notify} />)}
    </div>
  );
}
