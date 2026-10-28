import React from "react";
import { TierChip } from "./RulesPanel.jsx";

// Floor / Reflex / Finish counts, what blocks the release, the waiver form and the clean-context verdict.
export default function GatePanel({ critique, t, waivers, setWaivers, onApply, busy }) {
  const gate = critique?.gate;
  if (!gate) return null;
  const open = (critique.findings || []).filter((f) => f.tier === "reflex" && !f.waived);
  const seen = new Set();
  const rules = open.filter((f) => f.check_id && !seen.has(f.check_id) && seen.add(f.check_id));
  const waived = (critique.findings || []).filter((f) => f.waived);
  const review = critique.review;
  return (
    <div className="panel mt-4" data-testid="gate-panel">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-[13px] font-semibold">{t("dq_gate")}</h3>
        <span className={`chip ${gate.state === "pass" ? "chip-ok" : "chip-danger"}`} data-testid="gate-state">
          {gate.state === "pass" ? t("dq_gate_pass") : t("dq_gate_fix")}
        </span>
      </div>
      <div className="flex gap-2 flex-wrap mt-2">
        <span className="chip chip-danger">{t("dq_tier_floor")}: {gate.floor}</span>
        <span className="chip chip-amber">{t("dq_tier_reflex")}: {gate.reflex_open}</span>
        <span className="chip">{t("dq_waived")}: {gate.reflex_waived}</span>
        <span className="chip">{t("dq_tier_finish")}: {gate.finish}</span>
      </div>
      {!!gate.blocking?.length && (
        <div className="help mt-2"><strong>{t("dq_blocking")}:</strong> <span className="mono">{gate.blocking.join(", ")}</span></div>
      )}

      {!!rules.length && (
        <div className="flex flex-col gap-2 mt-3">
          {rules.map((f) => (
            <div key={f.check_id} className="card">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className="text-[13px]"><span className="mono">{f.check_id}</span> · {f.title}</span>
                <TierChip tier="reflex" t={t} />
              </div>
              <label className="label mt-2" htmlFor={`waive-${f.check_id}`}>{t("dq_waive_reason")}</label>
              <textarea id={`waive-${f.check_id}`} className="field" rows={2} value={waivers[f.check_id] || ""}
                onChange={(e) => setWaivers({ ...waivers, [f.check_id]: e.target.value })} />
              <div className="help">{(waivers[f.check_id] || "").trim().length}/24</div>
            </div>
          ))}
          <div>
            <button type="button" className="btn" onClick={onApply} disabled={busy || !Object.values(waivers).some((v) => v && v.trim())}>
              {t("dq_waive_apply")}
            </button>
          </div>
        </div>
      )}

      {!!critique.waivers?.rejected?.length && (
        <div className="flex flex-col gap-1 mt-3">
          {critique.waivers.rejected.map((r, i) => (
            <div key={i} className="help"><strong>{t("dq_waive_rejected")}:</strong> <span className="mono">{r.rule}</span> · {r.why}</div>
          ))}
        </div>
      )}
      {!!waived.length && (
        <div className="flex flex-col gap-1 mt-3">
          {Array.from(new Map(waived.map((f) => [f.check_id, f])).values()).map((f) => (
            <div key={f.check_id} className="help"><span className="mono">{f.check_id}</span> · {t("dq_waived")}: {f.waiver_reason}</div>
          ))}
        </div>
      )}

      {review && (
        <div className="card mt-3" data-testid="review-verdict">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <span className="font-semibold text-[13px]">{t("dq_review_title")}</span>
            <span className={`chip ${review.verdict === "ship" ? "chip-ok" : review.verdict ? "chip-amber" : ""}`}>
              {review.verdict || t("dq_review_unavailable")}
            </span>
          </div>
          {review.error && <div className="help mt-1">{review.error}</div>}
          {!!review.findings?.length && (
            <ul className="mt-2 text-[13px] list-disc pl-5">{review.findings.map((f, i) => <li key={i}>{f}</li>)}</ul>
          )}
          {review.model && <div className="help mt-1">{review.model}</div>}
        </div>
      )}
    </div>
  );
}
