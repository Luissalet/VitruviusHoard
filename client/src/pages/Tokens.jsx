import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { Empty, ContrastSwatch, ConfirmButton } from "../components/ui.jsx";
import { clock } from "../format.js";

const STYLE_OPTIONS = ["sharp", "soft", "pill", "flat", "hard-offset"];
const RAMP_STEPS = ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"];

function download(filename, content, type = "text/plain") {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function RampRow({ label, ramp, t }) {
  if (!ramp) return null;
  return (
    <div>
      <div className="label">{label}</div>
      <div className="grid grid-cols-11 gap-1">
        {RAMP_STEPS.map((step) => ramp[step] ? <ContrastSwatch key={step} hex={ramp[step]} step={step} t={t} /> : <div key={step} />)}
      </div>
    </div>
  );
}

function TokensResult({ ds, t, notify, onDeleted }) {
  const [dark, setDark] = useState(false);
  const [lintResult, setLintResult] = useState(null);
  const [busyLint, setBusyLint] = useState(false);
  const tokens = ds.tokens;

  const doPreviewLint = async () => {
    setBusyLint(true);
    try {
      const preview = await api.tokensPreview(ds.id, { dark });
      const lint = await api.lint({ render_id: preview.id });
      setLintResult(lint);
    } catch (e) {
      notify(e.message);
    } finally {
      setBusyLint(false);
    }
  };

  const exportFormat = async (format) => {
    try {
      if (format === "css" || format === "tailwind") {
        const text = await (await fetch(api.tokensExportUrl(ds.id, format))).text();
        download(`${ds.name}.${format === "tailwind" ? "css" : "css"}`, text, "text/css");
      } else {
        const res = await api.tokensExport(ds.id, format);
        download(`${ds.name}.${format}.json`, JSON.stringify(res.content, null, 2), "application/json");
      }
    } catch (e) {
      notify(e.message);
    }
  };

  if (!tokens) return null;

  return (
    <div className="panel mt-4 flex flex-col gap-5">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-[15px] font-semibold">{ds.name}</h2>
        <div className="flex gap-2 flex-wrap">
          <button type="button" className="btn btn-sm" onClick={() => exportFormat("css")}>CSS</button>
          <button type="button" className="btn btn-sm" onClick={() => exportFormat("tailwind")}>Tailwind</button>
          <button type="button" className="btn btn-sm" onClick={() => exportFormat("w3c")}>W3C JSON</button>
          <button type="button" className="btn btn-sm" onClick={() => exportFormat("json")}>JSON</button>
          {onDeleted && <ConfirmButton t={t} onConfirm={() => onDeleted(ds.id)} />}
        </div>
      </div>

      <div>
        <h3 className="text-[13px] font-semibold mb-2">{t("tokens_ramps")}</h3>
        <div className="flex flex-col gap-3">
          <RampRow label="primary" ramp={tokens.color?.primary} t={t} />
          <RampRow label="neutral" ramp={tokens.color?.neutral} t={t} />
        </div>
      </div>

      {tokens.color?.semantic && (
        <div>
          <h3 className="text-[13px] font-semibold mb-2">{t("tokens_semantic")}</h3>
          <div className="flex flex-col gap-3">
            {Object.entries(tokens.color.semantic).map(([name, ramp]) => (
              <RampRow key={name} label={name} ramp={ramp} t={t} />
            ))}
          </div>
        </div>
      )}

      {tokens.typography?.scale && (
        <div>
          <h3 className="text-[13px] font-semibold mb-2">{t("tokens_type_scale")}</h3>
          <div className="flex flex-col gap-1">
            {Object.entries(tokens.typography.scale).map(([step, value]) => (
              <div key={step} className="flex items-baseline gap-3">
                <span className="mono" style={{ width: 40, color: "var(--muted)" }}>{step}</span>
                <span style={{ fontSize: value, fontFamily: tokens.typography.heading }}>Aa {step}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {tokens.spacing && (
        <div>
          <h3 className="text-[13px] font-semibold mb-2">{t("tokens_spacing")}</h3>
          <div className="flex flex-col gap-1">
            {Object.entries(tokens.spacing).map(([step, value]) => (
              <div key={step} className="flex items-center gap-3">
                <span className="mono" style={{ width: 40, color: "var(--muted)" }}>{step}</span>
                <div style={{ width: value, height: 10, background: "var(--accent)", borderRadius: 3 }} />
                <span className="help">{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {tokens.motion && (
        <div>
          <h3 className="text-[13px] font-semibold mb-2">{t("tokens_motion")}</h3>
          <div className="grid md:grid-cols-2 gap-4 text-[12px]">
            <table className="w-full">
              <tbody>
                {Object.entries(tokens.motion.duration || {}).map(([k, v]) => (
                  <tr key={k} className="border-t" style={{ borderColor: "var(--line)" }}>
                    <td className="py-1 pr-2 mono">{k}</td>
                    <td className="py-1 num">{v} ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <table className="w-full">
              <tbody>
                {Object.entries(tokens.motion.easing || {}).map(([k, v]) => (
                  <tr key={k} className="border-t" style={{ borderColor: "var(--line)" }}>
                    <td className="py-1 pr-2 mono">{k}</td>
                    <td className="py-1 mono">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
          <h3 className="text-[13px] font-semibold">{t("tokens_playground")}</h3>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-2 text-[12px]">
              <input type="checkbox" checked={dark} onChange={(e) => setDark(e.target.checked)} />
              {t("tokens_mode_dark")}
            </label>
            <button type="button" className="btn btn-sm" onClick={doPreviewLint} disabled={busyLint}>{t("tokens_preview_lint")}</button>
          </div>
        </div>
        <iframe
          title="playground"
          src={api.tokensPlaygroundUrl(ds.id, dark)}
          className="w-full rounded-md border"
          style={{ borderColor: "var(--line)", height: 480, background: "#fff" }}
        />
        {lintResult && (
          <div className="help mt-2">
            {t("critique_score")}: {lintResult.score} · {lintResult.counts?.error || 0} error, {lintResult.counts?.warn || 0} warn, {lintResult.counts?.info || 0} info
          </div>
        )}
      </div>
    </div>
  );
}

export default function Tokens() {
  const { t, notify, lang } = useApp();
  const [name, setName] = useState("");
  const [baseColor, setBaseColor] = useState("#1b2f9e");
  const [hue, setHue] = useState(233);
  const [style, setStyle] = useState("");
  const [vibe, setVibe] = useState("");
  const [mode, setMode] = useState("both");
  const [motionIntensity, setMotionIntensity] = useState(5);
  const [headingFont, setHeadingFont] = useState("");
  const [bodyFont, setBodyFont] = useState("");
  const [monoFont, setMonoFont] = useState("");
  const [radius, setRadius] = useState("");
  const [density, setDensity] = useState("comfortable");
  const [busy, setBusy] = useState(false);
  const [current, setCurrent] = useState(null);
  const [saved, setSaved] = useState(null);

  const loadSaved = async () => {
    try {
      const res = await api.tokensList(30);
      setSaved(res.design_systems);
    } catch (e) {
      notify(e.message);
    }
  };
  useEffect(() => { loadSaved(); }, []);

  const generate = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      const body = {
        name,
        base_color: baseColor || undefined,
        hue: baseColor ? undefined : hue,
        style: style || undefined,
        vibe: vibe || undefined,
        mode,
        knobs: { motion_intensity: motionIntensity },
        fonts: (headingFont || bodyFont || monoFont) ? { heading: headingFont, body: bodyFont, mono: monoFont } : undefined,
        radius: radius || undefined,
        density,
      };
      const res = await api.tokensCreate(body);
      setCurrent(res);
      loadSaved();
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };

  const openSaved = async (id) => {
    try {
      const row = await api.tokensGet(id);
      setCurrent(row);
    } catch (e) {
      notify(e.message);
    }
  };

  const deleteSaved = async (id) => {
    try {
      await api.tokensDelete(id);
      if (current?.id === id) setCurrent(null);
      loadSaved();
    } catch (e) {
      notify(e.message);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-[20px] font-semibold">{t("nav_tokens")}</h1>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <div className="flex flex-col gap-6">
          <div className="panel">
            <h2 className="text-[14px] font-semibold mb-3">{t("tokens_form_title")}</h2>
            <form onSubmit={generate} className="flex flex-col gap-3">
              <div>
                <label className="label" htmlFor="tokens-name">{t("tokens_name")}</label>
                <input id="tokens-name" className="field" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="grid grid-cols-2 gap-2 items-end">
                <div>
                  <label className="label" htmlFor="tokens-color">{t("tokens_base_color")}</label>
                  <input id="tokens-color" type="color" className="field" style={{ height: 36, padding: 2 }} value={baseColor} onChange={(e) => setBaseColor(e.target.value)} />
                </div>
                <div>
                  <label className="label" htmlFor="tokens-hue">{t("tokens_hue")} ({hue})</label>
                  <input id="tokens-hue" type="range" min="0" max="360" value={hue} onChange={(e) => { setHue(Number(e.target.value)); setBaseColor(""); }} className="w-full" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <select className="field" value={style} onChange={(e) => setStyle(e.target.value)} aria-label={t("tokens_style")}>
                  <option value="">{t("tokens_style")}</option>
                  {STYLE_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
                <input className="field" placeholder={t("tokens_vibe")} value={vibe} onChange={(e) => setVibe(e.target.value)} aria-label={t("tokens_vibe")} />
              </div>
              <div>
                <label className="label">{t("tokens_mode")}</label>
                <div className="flex gap-1">
                  {["light", "dark", "both"].map((m) => (
                    <button key={m} type="button" className={`btn btn-sm ${mode === m ? "btn-active" : ""}`} aria-pressed={mode === m} onClick={() => setMode(m)}>
                      {t(`tokens_mode_${m}`)}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="label">{t("tokens_knob_motion")} ({motionIntensity})</label>
                <input type="range" min="1" max="10" value={motionIntensity} onChange={(e) => setMotionIntensity(Number(e.target.value))} className="w-full" />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <input className="field" placeholder={t("tokens_font_heading")} value={headingFont} onChange={(e) => setHeadingFont(e.target.value)} aria-label={t("tokens_font_heading")} />
                <input className="field" placeholder={t("tokens_font_body")} value={bodyFont} onChange={(e) => setBodyFont(e.target.value)} aria-label={t("tokens_font_body")} />
                <input className="field" placeholder={t("tokens_font_mono")} value={monoFont} onChange={(e) => setMonoFont(e.target.value)} aria-label={t("tokens_font_mono")} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <input className="field" placeholder={t("tokens_radius")} value={radius} onChange={(e) => setRadius(e.target.value)} aria-label={t("tokens_radius")} />
                <select className="field" value={density} onChange={(e) => setDensity(e.target.value)} aria-label={t("tokens_density")}>
                  <option value="compact">compact</option>
                  <option value="comfortable">comfortable</option>
                  <option value="spacious">spacious</option>
                </select>
              </div>
              <button type="submit" className="btn btn-primary self-start" disabled={busy || !name.trim()}>
                {busy ? t("tokens_generating") : t("tokens_generate")}
              </button>
            </form>
          </div>

          <div className="panel">
            <h2 className="text-[14px] font-semibold mb-3">{t("tokens_saved_title")}</h2>
            {!saved?.length && <div className="help">{t("tokens_saved_empty")}</div>}
            <div className="flex flex-col gap-2">
              {saved?.map((s) => (
                <div key={s.id} className="flex items-center justify-between gap-2 border-t pt-2 first:border-t-0 first:pt-0" style={{ borderColor: "var(--line)" }}>
                  <div>
                    <div className="font-semibold text-[13px]">{s.name}</div>
                    <div className="help">{clock(s.created_ts, lang)}</div>
                  </div>
                  <div className="flex gap-2">
                    <button type="button" className="btn btn-sm" onClick={() => openSaved(s.id)}>{t("tokens_open")}</button>
                    <ConfirmButton t={t} onConfirm={() => deleteSaved(s.id)} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div>
          {!current && <Empty>{t("tokens_empty")}</Empty>}
          {current && <TokensResult ds={current} t={t} notify={notify} onDeleted={deleteSaved} />}
        </div>
      </div>
    </div>
  );
}
