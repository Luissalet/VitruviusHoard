import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";

const STATUS_CLASS = { violated: "chip chip-danger", holds: "chip chip-ok", inconclusive: "chip chip-amber" };
const show = (v) => (v === null ? "null" : typeof v === "object" ? JSON.stringify(v) : String(v));

function Trace({ violation, t }) {
  return (
    <table className="w-full mt-2 text-[12.5px]" data-testid="protocol-trace">
      <thead><tr className="text-left"><th>#</th><th>{t("pr_process")}</th><th>{t("pr_step")}</th><th>{t("pr_changes")}</th></tr></thead>
      <tbody>
        {violation.trace.map((s, i) => (
          <tr key={i}>
            <td className="mono">{i + 1}</td>
            <td className="mono">{s.process}</td>
            <td>{s.kind === "crash" ? <span className="chip chip-danger">{t("pr_crash")} · {s.label}</span> : <span className="mono">{s.label}{s.branch !== null && s.branch !== undefined ? ` [${s.branch + 1}]` : ""}</span>}</td>
            <td className="mono">
              {Object.entries(s.changes).map(([k, [a, b]]) => <div key={k}>{k}: {show(a)} → {show(b)}</div>)}
              {Object.entries(s.local_changes).map(([k, [a, b]]) => <div key={k} className="help">{s.process}.{k}: {show(a)} → {show(b)}</div>)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Protocols() {
  const { t, notify } = useApp();
  const [examples, setExamples] = useState([]);
  const [text, setText] = useState("");
  const [seconds, setSeconds] = useState(60);
  const [result, setResult] = useState(null);
  const [replay, setReplay] = useState(null);
  const [busy, setBusy] = useState(false);

  const parse = () => {
    try { return JSON.parse(text); } catch (e) { notify(t("pr_bad_json") + ": " + e.message); return null; }
  };
  const loadExample = async (id) => {
    const r = await api.protocolExample(id);
    setText(JSON.stringify(r.spec, null, 2));
    setResult(null);
    setReplay(null);
  };
  useEffect(() => {
    api.protocolExamples().then((r) => {
      setExamples(r.examples);
      if (r.examples.length) loadExample(r.examples[0].id);
    }).catch((e) => notify(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const check = async (e) => {
    e?.preventDefault();
    const spec = parse();
    if (!spec) return;
    setBusy(true);
    setReplay(null);
    try { setResult(await api.protocolCheck({ spec, time_limit: Number(seconds) || 60 })); } catch (err) { notify(err.message); } finally { setBusy(false); }
  };
  const doReplay = async () => {
    const spec = parse();
    if (!spec || !result?.violation) return;
    try { setReplay(await api.protocolReplay({ spec, schedule: result.violation.schedule })); } catch (err) { notify(err.message); }
  };
  const download = async () => {
    const spec = parse();
    if (!spec) return;
    try {
      const blob = await api.protocolTest({ spec, time_limit: Number(seconds) || 60 });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "test_contraejemplo.py";
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (err) { notify(err.message); }
  };

  const v = result?.violation;
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[22px] font-semibold">{t("pr_title")}</h1>
        <p className="help mt-1" style={{ maxWidth: 760 }}>{t("pr_intro")}</p>
      </div>
      <form className="panel flex flex-col gap-3" onSubmit={check} aria-busy={busy}>
        <div className="flex gap-3 flex-wrap items-end">
          <div>
            <label className="label" htmlFor="pr-example">{t("pr_example")}</label>
            <select id="pr-example" className="field" onChange={(e) => loadExample(e.target.value)} data-testid="protocol-example">
              {examples.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="pr-seconds">{t("pr_seconds")}</label>
            <input id="pr-seconds" className="field" style={{ width: 90 }} type="number" min="1" max="3600" value={seconds} onChange={(e) => setSeconds(e.target.value)} />
          </div>
          <button type="submit" className="btn btn-primary" data-testid="protocol-run" disabled={busy}>{busy ? t("pr_running") : t("pr_run")}</button>
        </div>
        <label className="label" htmlFor="pr-spec">{t("pr_spec")}</label>
        <textarea id="pr-spec" className="field mono" style={{ minHeight: 320, fontSize: 12 }} spellCheck={false} value={text} onChange={(e) => setText(e.target.value)} data-testid="protocol-spec" />
        <p className="help">{t("pr_spec_help")}</p>
      </form>

      {result && (
        <div className="panel flex flex-col gap-2" data-testid="protocol-result">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={STATUS_CLASS[result.status] || "chip"} data-testid="protocol-status">{t(`pr_status_${result.status}`)}</span>
            <span className="chip">{result.states} {t("pr_states")}</span>
            <span className="chip">{result.transitions} {t("pr_transitions")}</span>
            <span className="chip">{result.seconds} s</span>
            {result.truncated && <span className="chip chip-amber">{result.truncated}</span>}
          </div>
          {v && (
            <>
              <h3 className="text-[13px] font-semibold mt-2">{t(`pr_kind_${v.kind}`)}: {v.property} · {v.length} {t("pr_steps")}</h3>
              <Trace violation={v} t={t} />
              <details><summary className="cursor-pointer help">{t("pr_final_state")}</summary><pre className="mono text-[11px] overflow-auto">{JSON.stringify(v.final_state, null, 2)}</pre></details>
              <div className="flex gap-2 flex-wrap">
                <button type="button" className="btn" onClick={doReplay} data-testid="protocol-replay">{t("pr_replay")}</button>
                <button type="button" className="btn" onClick={download} data-testid="protocol-test">{t("pr_download_test")}</button>
              </div>
            </>
          )}
          {replay && (
            <ol className="text-[12.5px] mono" data-testid="protocol-replay-result">
              {replay.steps.map((s, i) => <li key={i}>{s.process} · {s.label}{s.kind === "crash" ? " (caída)" : ""}{s.broken.length ? ` ✗ ${s.broken.join(", ")}` : " ✓"}</li>)}
            </ol>
          )}
          <h3 className="text-[13px] font-semibold mt-2">{t("pr_assumptions")}</h3>
          <ul className="help pl-4" style={{ listStyle: "disc" }}>{result.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        </div>
      )}
    </div>
  );
}
