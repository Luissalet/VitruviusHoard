import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { useCopilotForm, useCopilotObjects, useCopilotRefresh } from "../copilot-hooks.js";
import { Empty, ConfirmButton } from "../components/ui.jsx";
import { clock } from "../format.js";
import DiagramEditor from "../components/diagram-editor/DiagramEditor.jsx";

const SAMPLE = `flowchart TD
  A([Start]) --> B[Review order]
  B --> C{Paid?}
  C -->|yes| D[Ship]
  C -->|no| E[Send reminder]
  E --> B`;

function sourceBody(text) {
  const trimmed = text.trim();
  if (trimmed.startsWith("{") && !trimmed.includes('"elements"')) {
    return { diagram: JSON.parse(trimmed) };
  }
  return { source: trimmed };
}

function Gates({ gates, t }) {
  return (
    <ul className="flex flex-col gap-1 text-[12px]">
      {gates.map((g) => (
        <li key={g.id} className="flex flex-wrap items-baseline gap-2">
          <span className={g.ok ? "chip chip-ok" : "chip chip-danger"}>{g.ok ? t("dg_gate_ok") : t("dg_gate_fail")}</span>
          <code>{g.id}</code>
          <span className="help">{g.detail}</span>
          {g.items && g.items.length > 0 && <span className="help">· {g.items.join(" · ")}</span>}
        </li>
      ))}
    </ul>
  );
}

function BrandForm({ t, notify, onSaved }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [accent, setAccent] = useState("#2f5bd3");
  const [busy, setBusy] = useState(false);
  const save = async (mode) => {
    if (!name.trim()) return notify(t("dg_brand_name_needed"));
    setBusy(true);
    try {
      const body = mode === "url" ? { name, url } : { name, colors: { accent } };
      const saved = await api.diagramBrandOnboard(body);
      notify(`${t("dg_brand_saved")}: ${saved.name}`);
      onSaved(saved.profile);
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="panel flex flex-col gap-3">
      <h2 className="text-[14px] font-semibold">{t("dg_brand_title")}</h2>
      <div>
        <label className="label" htmlFor="dg-brand-name">{t("dg_brand_name")}</label>
        <input id="dg-brand-name" className="field" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1">
          <label className="label" htmlFor="dg-brand-url">{t("dg_brand_url")}</label>
          <input id="dg-brand-url" className="field" placeholder="https://" value={url} onChange={(e) => setUrl(e.target.value)} />
        </div>
        <button type="button" className="btn btn-sm" disabled={busy || !url} onClick={() => save("url")}>{t("dg_brand_from_url")}</button>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="label" htmlFor="dg-brand-accent">{t("dg_brand_accent")}</label>
          <input id="dg-brand-accent" type="color" value={accent} onChange={(e) => setAccent(e.target.value)} />
        </div>
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => save("colors")}>{t("dg_brand_from_color")}</button>
      </div>
      <p className="help">{t("dg_brand_help")}</p>
    </div>
  );
}

export default function Diagrams() {
  const { t, notify } = useApp();
  const [text, setText] = useState(SAMPLE);
  const [intent, setIntent] = useState("");
  const [card, setCard] = useState(null);
  const [catalogue, setCatalogue] = useState({ types: {}, patterns: {} });
  const [kind, setKind] = useState("");
  const [profile, setProfile] = useState("");
  const [brands, setBrands] = useState([]);
  const [systems, setSystems] = useState([]);
  const [result, setResult] = useState(null);
  const [mode, setMode] = useState("light");
  const [busy, setBusy] = useState(false);
  const [recent, setRecent] = useState([]);

  const load = useCallback(async () => {
    try {
      const [b, s, r, c] = await Promise.all([api.diagramBrands(), api.tokensList(50), api.diagrams(20), api.diagramTypes({})]);
      setCatalogue({ types: c.types || {}, patterns: c.patterns || {} });
      setBrands(b.profiles || []);
      setSystems(s.design_systems || []);
      setRecent(r.diagrams || []);
    } catch (e) {
      notify(e.message);
    }
  }, [notify]);
  useEffect(() => { load(); }, [load]);
  useCopilotRefresh(load);
  useCopilotObjects(result?.id ? [{ kind: "diagram", id: result.id }] : []);
  useCopilotForm("diagram-draft", { initial: { source: SAMPLE, intent: "", profile: "" }, current: { source: text, intent, profile } });

  const suggest = async () => {
    try {
      setCard(await api.diagramTypes({ intent }));
    } catch (e) {
      notify(e.message);
    }
  };

  const chooseKind = async (value) => {
    setKind(value);
    if (!value) return;
    try {
      const got = await api.diagramTypes({ type: value });
      const pattern = catalogue.patterns[got.pattern];
      setCard({ type: value, question: pattern ? pattern.question : "", card: got });
    } catch (e) {
      notify(e.message);
    }
  };

  const draw = async () => {
    setBusy(true);
    try {
      const body = { ...sourceBody(text), profile, include_svg: false };
      const out = await api.diagramRender(body);
      setResult(out);
      load();
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };

  const open = async (id) => {
    try {
      const got = await api.diagram(id);
      setResult({ ...got, files: Object.fromEntries((got.modes || []).map((m) => [m, api.diagramSvgUrl(id, m)])) });
    } catch (e) {
      notify(e.message);
    }
  };

  const files = result && result.files;
  return (
    <div className="flex flex-col gap-5">
      <header>
        <h1 className="text-[20px] font-semibold">{t("nav_diagrams")}</h1>
        <p className="help mt-1">{t("dg_intro")}</p>
      </header>
      <DiagramEditor />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-4 min-w-0">
          <div className="panel flex flex-col gap-3">
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-0 flex-1">
                <label className="label" htmlFor="dg-intent">{t("dg_intent")}</label>
                <input id="dg-intent" className="field" value={intent} onChange={(e) => setIntent(e.target.value)}
                       placeholder={t("dg_intent_ph")} onKeyDown={(e) => e.key === "Enter" && suggest()} />
              </div>
              <button type="button" className="btn btn-sm" onClick={suggest}>{t("dg_suggest")}</button>
              <div>
                <label className="label" htmlFor="dg-type">{t("dg_type")}</label>
                <select id="dg-type" className="field" value={kind} onChange={(e) => chooseKind(e.target.value)}>
                  <option value="">{t("dg_type_any")}</option>
                  {Object.keys(catalogue.types).map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
              </div>
            </div>
            {card && card.card && (
              <div className="text-[12px] flex flex-col gap-1">
                <div><strong>{card.type}</strong> · {card.question}</div>
                <div className="help">{card.card.use}</div>
                <div className="help"><code>{card.card.fields}</code></div>
                <button type="button" className="btn-link self-start" onClick={() => setText(JSON.stringify(card.card.example, null, 2))}>
                  {t("dg_use_example")}
                </button>
              </div>
            )}
            <div>
              <label className="label" htmlFor="dg-source">{t("dg_source")}</label>
              <textarea id="dg-source" className="field font-mono text-[12px]" rows={12} value={text} onChange={(e) => setText(e.target.value)} />
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <div>
                <label className="label" htmlFor="dg-profile">{t("dg_profile")}</label>
                <select id="dg-profile" className="field" value={profile} onChange={(e) => setProfile(e.target.value)}>
                  <option value="">{t("dg_profile_default")}</option>
                  {brands.map((b) => <option key={b.profile} value={b.profile}>{b.name}</option>)}
                  {systems.map((s) => <option key={s.id} value={s.id}>{t("nav_tokens")}: {s.name}</option>)}
                </select>
              </div>
              <button type="button" className="btn btn-primary" disabled={busy || !text.trim()} onClick={draw}>
                {busy ? t("dg_drawing") : t("dg_draw")}
              </button>
            </div>
          </div>
          {result && (
            <div className="panel flex flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-[14px] font-semibold">{result.title || result.type} <span className={result.ok ? "chip chip-ok" : "chip chip-amber"}>{result.ok ? t("dg_all_gates") : `${(result.failed || []).length} ${t("dg_failed_gates")}`}</span></h2>
                <div className="flex gap-1">
                  {files && Object.keys(files).map((m) => (
                    <button key={m} type="button" className={mode === m ? "btn btn-sm btn-active" : "btn btn-sm"} onClick={() => setMode(m)}>{t(`dg_mode_${m}`)}</button>
                  ))}
                  {files && files[mode] && <a className="btn btn-sm" href={files[mode]} download={`${result.id || "diagram"}-${mode}.svg`}>{t("dg_download")}</a>}
                </div>
              </div>
              {files && files[mode] && (
                <div className="overflow-auto rounded-md border" style={{ borderColor: "var(--line)" }}>
                  <img src={files[mode]} alt={result.title || result.type} className="max-w-none" />
                </div>
              )}
              <Gates gates={result.gates || []} t={t} />
            </div>
          )}
        </div>
        <div className="flex flex-col gap-4">
          <BrandForm t={t} notify={notify} onSaved={(p) => { setProfile(p); load(); }} />
          <div className="panel flex flex-col gap-2">
            <h2 className="text-[14px] font-semibold">{t("dg_recent")}</h2>
            {recent.length === 0 && <Empty>{t("dg_none")}</Empty>}
            {recent.map((r) => (
              <div key={r.id} className="flex items-center justify-between gap-2 text-[12px]">
                <button type="button" className="btn-link truncate text-left" onClick={() => open(r.id)}>{r.title || r.type}</button>
                <span className="help shrink-0">{r.title ? `${r.type} · ` : ""}{clock(r.created_ts)}</span>
                <ConfirmButton t={t}
                               onConfirm={async () => { await api.diagramDelete(r.id); if (result && result.id === r.id) setResult(null); load(); }} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
