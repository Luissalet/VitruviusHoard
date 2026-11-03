import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

const TIER_CLASS = { floor: "chip chip-danger", reflex: "chip chip-amber", finish: "chip" };
const PAGE = 60;

export function TierChip({ tier, t }) {
  if (!tier) return null;
  return <span className={TIER_CLASS[tier] || "chip"}>{t(`dq_tier_${tier}`)}</span>;
}

// Browsable registry of every lint rule: filter by pack, engine, tier or text.
export default function RulesPanel({ t, notify, lang }) {
  const [data, setData] = useState(null);
  const [pack, setPack] = useState("");
  const [engine, setEngine] = useState("");
  const [tier, setTier] = useState("");
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(PAGE);
  const [open, setOpen] = useState("");

  useEffect(() => {
    let live = true;
    api.rules({ pack: pack || undefined, engine: engine || undefined, tier: tier || undefined, q: q.trim() || undefined, lang: lang || undefined })
      .then((res) => { if (live) { setData(res); setShown(PAGE); } })
      .catch((e) => notify(e.message));
    return () => { live = false; };
  }, [pack, engine, tier, q, lang]);

  const summary = data?.summary;
  const packs = useMemo(() => Object.keys(summary?.by_pack || {}).sort(), [summary]);
  const engines = useMemo(() => Object.keys(summary?.by_engine || {}).sort(), [summary]);

  return (
    <div className="panel">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="text-[14px] font-semibold">{t("dq_rules_title")}</h2>
        <span className="help" data-testid="rules-count">{data ? `${data.count} ${t("dq_rules_count")}` : "…"}</span>
      </div>
      <div className="grid gap-3 md:grid-cols-4 mt-3">
        <div>
          <label className="label" htmlFor="rules-q">{t("dq_rules_search")}</label>
          <input id="rules-q" className="field" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="rules-pack">{t("dq_rules_pack")}</label>
          <select id="rules-pack" className="field" value={pack} onChange={(e) => setPack(e.target.value)}>
            <option value="">{t("dq_rules_all")}</option>
            {packs.map((p) => <option key={p} value={p}>{p} ({summary.by_pack[p]})</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="rules-engine">{t("dq_rules_engine")}</label>
          <select id="rules-engine" className="field" value={engine} onChange={(e) => setEngine(e.target.value)}>
            <option value="">{t("dq_rules_all")}</option>
            {engines.map((p) => <option key={p} value={p}>{p} ({summary.by_engine[p]})</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="rules-tier">{t("dq_rules_tier")}</label>
          <select id="rules-tier" className="field" value={tier} onChange={(e) => setTier(e.target.value)}>
            <option value="">{t("dq_rules_all")}</option>
            {["floor", "reflex", "finish"].map((p) => <option key={p} value={p}>{t(`dq_tier_${p}`)}</option>)}
          </select>
        </div>
      </div>
      <div className="help mt-2">{t("dq_floor_help")} {t("dq_reflex_help")} {t("dq_finish_help")}</div>
      <div className="flex flex-col gap-1 mt-3">
        {(data?.rules || []).slice(0, shown).map((r) => (
          <div key={r.id} className="card">
            <button type="button" className="w-full text-left flex items-center justify-between gap-2 flex-wrap" aria-expanded={open === r.id}
              onClick={() => setOpen(open === r.id ? "" : r.id)}>
              <span><span className="mono text-[12px]">{r.id}</span> <span className="text-[13px]">{r.name}</span></span>
              <span className="flex gap-1 flex-wrap">
                <TierChip tier={r.tier} t={t} />
                <span className="chip">{r.engine}</span>
                <span className="chip">{r.scope}</span>
              </span>
            </button>
            {open === r.id && (
              <div className="mt-2 text-[13px]">
                <p>{r.description}</p>
                {r.fix && <p className="help mt-1">{r.fix}</p>}
                {r.reference && <p className="help mt-1">{t("dq_rules_reference")}: {r.reference}</p>}
                <p className="help mt-1">{t("dq_rules_source")}: {r.source}{r.source_id ? ` · ${r.source_id}` : ""}{r.judged ? ` · ${t("dq_rules_judged")}` : ""}</p>
              </div>
            )}
          </div>
        ))}
      </div>
      {data && data.rules.length > shown && (
        <button type="button" className="btn mt-3" onClick={() => setShown(shown + PAGE)}>{t("dq_rules_more")}</button>
      )}
    </div>
  );
}
