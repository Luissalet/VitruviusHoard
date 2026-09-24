import React, { useState } from "react";
import { STATUS_COLORS, SEVERITY_COLORS, contrastRatio, bestTextColor } from "../format.js";

export function Icon({ d, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

export function Empty({ children }) {
  return <div className="panel help text-center">{children}</div>;
}

export function StatusPill({ status, t }) {
  const color = STATUS_COLORS[status] || STATUS_COLORS.idle;
  return (
    <span className="chip">
      <span className="dot" style={{ background: color }} />
      {t(`status_${status}`)}
    </span>
  );
}

export function SeverityChip({ severity, t }) {
  const color = SEVERITY_COLORS[severity] || SEVERITY_COLORS.info;
  const cls = severity === "error" ? "chip chip-danger" : severity === "warn" ? "chip chip-amber" : "chip";
  return (
    <span className={cls}>
      <span className="dot" style={{ background: color }} />
      {t(`severity_${severity}`) || severity}
    </span>
  );
}

export function LicenseBadge({ license, t }) {
  if (!license) return null;
  const unverified = license === "check";
  return (
    <span className={unverified ? "chip chip-amber" : "chip"} title={unverified ? t("license_check") : undefined}>
      {unverified ? t("license_check") : license}
    </span>
  );
}

export function CopyButton({ value, t, small = true }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      // clipboard may be unavailable; fail silently
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button type="button" className={`btn ${small ? "btn-sm" : ""}`} onClick={onCopy} aria-label={t("copy")}>
      {copied ? t("copied") : t("copy")}
    </button>
  );
}

export function ConfirmButton({ label, confirmLabel, onConfirm, t, className = "btn btn-sm btn-danger" }) {
  const [pending, setPending] = useState(false);
  if (pending) {
    return (
      <span className="inline-flex gap-1">
        <button type="button" className={className} onClick={() => { setPending(false); onConfirm(); }}>
          {confirmLabel || t("delete")}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => setPending(false)}>{t("cancel")}</button>
      </span>
    );
  }
  return (
    <button type="button" className={className} onClick={() => setPending(true)}>
      {label || t("delete")}
    </button>
  );
}

export function Tabs({ tabs, active, onChange }) {
  return (
    <div role="tablist" className="flex gap-1 border-b" style={{ borderColor: "var(--line)" }}>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          className="tab"
          aria-selected={tab.key === active}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function ColorSwatch({ hex, label, sub }) {
  return (
    <div className="flex flex-col items-center gap-1 text-center" style={{ width: 64 }}>
      <div className="swatch" style={{ background: hex, width: 56, height: 40 }} title={hex} />
      <div className="mono" style={{ fontSize: 10 }}>{hex}</div>
      {label && <div className="help" style={{ fontSize: 10 }}>{label}</div>}
      {sub && <div className="help" style={{ fontSize: 10 }}>{sub}</div>}
    </div>
  );
}

export function ContrastSwatch({ hex, step, t }) {
  const fg = bestTextColor(hex);
  const ratioWhite = contrastRatio(hex, "#ffffff").toFixed(2);
  const ratioBlack = contrastRatio(hex, "#000000").toFixed(2);
  return (
    <div
      className="rounded-md flex flex-col justify-between p-2"
      style={{ background: hex, color: fg, minHeight: 68, border: "1px solid var(--line)" }}
      title={`${hex} — ${ratioWhite} ${t("contrast_vs")} #fff, ${ratioBlack} ${t("contrast_vs")} #000`}
    >
      <div className="mono" style={{ fontSize: 10 }}>{step}</div>
      <div className="mono" style={{ fontSize: 10 }}>{hex}</div>
    </div>
  );
}

// Score dial: a plain SVG arc, 0-10, no chart library.
export function ScoreDial({ score, size = 96 }) {
  const value = Math.max(0, Math.min(10, score ?? 0));
  const r = size / 2 - 8;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  const fraction = value / 10;
  const color = value >= 8 ? "var(--ok)" : value >= 5 ? "var(--warn)" : "var(--danger)";
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`Score ${value.toFixed(1)} / 10`}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--surface-2)" strokeWidth="8" />
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth="8"
        strokeLinecap="round"
        strokeDasharray={`${circumference * fraction} ${circumference}`}
        transform={`rotate(-90 ${cx} ${cy})`}
      />
      <text x={cx} y={cy + 6} textAnchor="middle" fontSize="22" fontWeight="700" fill="var(--ink)">
        {value.toFixed(1)}
      </text>
    </svg>
  );
}

export function Chip({ children, className = "chip" }) {
  return <span className={className}>{children}</span>;
}
