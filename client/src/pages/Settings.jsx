import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { useCopilotForm, useCopilotRefresh } from "../copilot-hooks.js";
import { mergeSettingsForm, settingsForm, settingsPatch } from "../settings-draft.js";

function StatusRow({ label, ok, detail }) {
  return (
    <div className="flex items-center justify-between border-t pt-2 first:border-t-0 first:pt-0" style={{ borderColor: "var(--line)" }}>
      <span className="text-[13px]">{label}</span>
      <span className={ok ? "chip chip-ok" : "chip chip-danger"}>
        <span className="dot" style={{ background: ok ? "var(--ok)" : "var(--danger)" }} />
        {ok ? "ok" : "missing"}
      </span>
      {detail && <span className="help ml-2">{detail}</span>}
    </div>
  );
}

function ModelRow({ label, resolution }) {
  const resolved = resolution?.state === "resolved";
  return (
    <div className="flex items-start justify-between gap-3 border-t pt-2 first:border-t-0 first:pt-0" style={{ borderColor: "var(--line)" }}>
      <span className="text-[13px] shrink-0">{label}</span>
      <span
        className={resolved ? "chip chip-ok" : "chip chip-amber"}
        style={{ whiteSpace: "normal", textAlign: "right", minWidth: 0, flex: "1 1 auto", maxWidth: "100%" }}
      >
        {resolved ? (resolution.model || resolution.provider || "ok") : (resolution?.reason || resolution?.state || "—")}
      </span>
    </div>
  );
}

// The Figma personal access token for "Import from Figma": saved in the app's data folder, never shown back in full.
function FigmaTokenPanel({ lang, notify, settings, onSaved }) {
  const L = (es, en) => (lang === "es" ? es : en);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async (token) => {
    setBusy(true);
    try {
      onSaved(await api.settingsUpdate({ figma_token: token }));
      setValue("");
      notify(token ? L("Token de Figma guardado.", "Figma token saved.") : L("Token de Figma quitado.", "Figma token removed."));
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="panel" data-testid="figma-token-panel">
      <h2 className="text-[14px] font-semibold mb-2">{L("Token de Figma", "Figma token")}</h2>
      <p className="help mb-2">{L("Para «Importar de Figma» (Design systems). En Figma: Settings > Security > Personal access tokens, con permiso de lectura de contenido. Se guarda solo en la carpeta de datos de la app.",
        "For Import from Figma (Design systems). In Figma: Settings > Security > Personal access tokens, with file content read access. It is kept only in the app's data folder.")}</p>
      <div className="flex gap-2 flex-wrap items-center">
        <input type="password" className="field flex-1" style={{ minWidth: 220 }} value={value} onChange={(e) => setValue(e.target.value)} placeholder="figd_…" aria-label={L("Token de Figma", "Figma token")} autoComplete="off" />
        <button type="button" className="btn btn-primary" disabled={busy || !value.trim()} onClick={() => save(value.trim())}>{L("Guardar token", "Save token")}</button>
        {settings?.figma_token_set && <button type="button" className="btn" disabled={busy} onClick={() => save("")}>{L("Quitar", "Remove")}</button>}
      </div>
      <div className="help mt-2" data-testid="figma-token-state">{settings?.figma_token_set ? `${L("Guardado", "Saved")} ${settings.figma_token_hint || ""}` : L("Sin token.", "No token saved.")}</div>
    </div>
  );
}

export default function Settings() {
  const { t, notify, lang } = useApp();
  const [status, setStatus] = useState(null);
  const [settings, setSettings] = useState(null);
  const [backendText, setBackendText] = useState("{}");
  const [backendError, setBackendError] = useState(null);
  const [widthsText, setWidthsText] = useState("");
  const [videoEnabled, setVideoEnabled] = useState(true);
  const [visionEnabled, setVisionEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const baseline = useRef({ backendText: "{}", widthsText: "", videoEnabled: true, visionEnabled: true });
  const draft = useRef({ backendText, widthsText, videoEnabled, visionEnabled });
  draft.current = { backendText, widthsText, videoEnabled, visionEnabled };
  const readGeneration = useRef(0);
  const applySettings = (cfg, previous = baseline.current) => {
    const next = mergeSettingsForm(previous, draft.current, cfg);
    baseline.current = settingsForm(cfg);
    draft.current = next;
    setSettings(cfg);
    setBackendText(next.backendText);
    setWidthsText(next.widthsText);
    setVideoEnabled(next.videoEnabled);
    setVisionEnabled(next.visionEnabled);
  };

  const load = async () => {
    const generation = ++readGeneration.current;
    try {
      const [s, cfg] = await Promise.all([api.status(), api.settings()]);
      if (generation !== readGeneration.current) return;
      setStatus(s);
      applySettings(cfg);
    } catch (e) {
      notify(e.message);
    }
  };
  useEffect(() => { load(); return () => { ++readGeneration.current; }; }, []);
  useCopilotRefresh(load);
  useCopilotForm("settings-form", {
    initial: { widths: baseline.current.widthsText, video_enabled: baseline.current.videoEnabled, vision_enabled: baseline.current.visionEnabled },
    current: { widths: widthsText, video_enabled: videoEnabled, vision_enabled: visionEnabled },
  });

  const saveAll = async (e) => {
    e.preventDefault();
    const submitted = { ...draft.current };
    let patch;
    try {
      patch = settingsPatch(baseline.current, submitted);
      setBackendError(null);
    } catch {
      setBackendError(t("settings_backend_invalid"));
      return;
    }
    ++readGeneration.current;
    setBusy(true);
    try {
      const res = await api.settingsUpdate(patch);
      ++readGeneration.current;
      applySettings(res, submitted);
      notify(t("saved"));
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-[20px] font-semibold">{t("nav_settings")}</h1>

      <div className="panel">
        <h2 className="text-[14px] font-semibold mb-3">{t("settings_status")}</h2>
        <div className="flex flex-col gap-1">
          <StatusRow label={t("settings_browser")} ok={!!status?.browser?.ok} detail={status?.browser?.error} />
          <StatusRow label={t("settings_ffmpeg")} ok={!!status?.ffmpeg} />
          <StatusRow label={t("settings_assay")} ok={!!status?.assay} />
          <StatusRow label={t("settings_git")} ok={!!status?.git} />
        </div>
      </div>

      <div className="panel">
        <h2 className="text-[14px] font-semibold mb-3">{t("settings_models")}</h2>
        <div className="flex flex-col gap-1">
          <ModelRow label={t("settings_model_llm")} resolution={status?.models?.llm} />
          <ModelRow label={t("settings_model_vision")} resolution={status?.models?.vision} />
          <ModelRow label={t("settings_model_embed")} resolution={status?.models?.embeddings} />
        </div>
      </div>

      <form onSubmit={saveAll} className="panel flex flex-col gap-4">
        <div>
          <label className="label" htmlFor="settings-backend">{t("settings_backend")}</label>
          <p className="help mb-2">{t("settings_backend_hint")}</p>
          <textarea id="settings-backend" className="field" rows={8} value={backendText} onChange={(e) => setBackendText(e.target.value)} />
          {backendError && <div className="help mt-1" style={{ color: "var(--danger)" }}>{backendError}</div>}
        </div>

        <div>
          <h3 className="text-[13px] font-semibold mb-2">{t("settings_capture_defaults")}</h3>
          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <label className="label" htmlFor="settings-widths">{t("settings_widths")}</label>
              <input id="settings-widths" className="field" value={widthsText} onChange={(e) => setWidthsText(e.target.value)} />
            </div>
            <div className="flex flex-col gap-2 justify-end">
              <label className="flex items-center gap-2 text-[13px]">
                <input type="checkbox" checked={videoEnabled} onChange={(e) => setVideoEnabled(e.target.checked)} />
                {t("settings_video_enabled")}
              </label>
              <label className="flex items-center gap-2 text-[13px]">
                <input type="checkbox" checked={visionEnabled} onChange={(e) => setVisionEnabled(e.target.checked)} />
                {t("settings_vision_enabled")}
              </label>
            </div>
          </div>
        </div>

        <button type="submit" className="btn btn-primary self-start" disabled={busy}>{t("save")}</button>
      </form>

      <FigmaTokenPanel lang={lang} notify={notify} settings={settings} onSaved={(cfg) => setSettings(cfg)} />

      <div className="panel">
        <h2 className="text-[14px] font-semibold mb-2">{t("settings_mcp_token")}</h2>
        <p className="help mb-1">{t("settings_mcp_token_hint")}</p>
        <div className="mono">data/mcp-token</div>
      </div>

      <div className="panel">
        <h2 className="text-[14px] font-semibold mb-2">{t("settings_links")}</h2>
        <div className="flex flex-col gap-1 text-[13px]">
          <a href="/README.md" target="_blank" rel="noreferrer">README.md</a>
          <a href="/README.es.md" target="_blank" rel="noreferrer">README.es.md</a>
        </div>
      </div>
    </div>
  );
}
