import React, { useEffect, useState } from "react";
import { api } from "../api.js";

// Preset catalogue (authored, hallmark themes, Hoard family palettes): three picks for a brief, live swatches in light and dark,
// and a partial apply (colours / radius / type / spacing / motion) to a design system. Each preset is also served as a
// shadcn registry-item.json.
const PARTS = [["colors", "Colores", "Colours"], ["radius", "Radios", "Radius"], ["type", "Tipografía", "Type"], ["spacing", "Espaciado", "Spacing"], ["motion", "Movimiento", "Motion"]];
const SOURCES = [["", "Todos", "All"], ["vitruvius", "Propios", "Authored"], ["flexoki", "Flexoki (tinta sobre papel)", "Flexoki (ink on paper)"], ["hoard", "Familia Hoard", "Hoard family"], ["hallmark", "Temas hallmark", "hallmark themes"]];

function Swatches({ colors, mode }) {
  return (
    <div className="flex" title={mode} style={{ borderRadius: 6, overflow: "hidden", border: "1px solid var(--line)" }}>
      {colors.map((c, k) => <span key={k} style={{ background: c, width: 22, height: 22, display: "inline-block" }} />)}
    </div>
  );
}

function PresetCard({ p, L, active, onSelect, recommended }) {
  return (
    <button type="button" className="card text-left" onClick={() => onSelect(p.name)} data-testid="preset-card"
      style={active ? { outline: "2px solid var(--accent, #6d8dff)" } : undefined}>
      <div className="flex items-center justify-between gap-1 flex-wrap">
        <span className="font-semibold text-[13px]">{p.title}</span>
        <span className="flex gap-1">{recommended && <span className="chip chip-ok">{L("Recomendado", "Recommended")}</span>}<span className="chip">{p.source}</span></span>
      </div>
      <div className="flex gap-2 mt-2 flex-wrap">
        <Swatches colors={p.swatches.light} mode="light" />
        <Swatches colors={p.swatches.dark} mode="dark" />
      </div>
      <div className="help mt-2">{p.fonts.heading} / {p.fonts.body} · r {p.radius}</div>
      <div className="help mt-1">{p.why || p.character}</div>
      {(p.license || p.aa !== undefined) && (
        <div className="flex gap-1 mt-2 flex-wrap" data-testid="preset-license">
          {p.aa && <span className="chip chip-ok">{L("Texto AA en claro y oscuro", "Text AA in light and dark")}</span>}
          {p.license && <span className="chip" title={p.license.notice}>{p.license.name} · {p.license.holder}</span>}
        </div>
      )}
    </button>
  );
}

export default function PresetPicker({ lang, notify, saved, currentId, onApplied }) {
  const L = (es, en) => (lang === "es" ? es : en);
  const [brief, setBrief] = useState("");
  const [picked, setPicked] = useState(null);
  const [busyPick, setBusyPick] = useState(false);
  const [source, setSource] = useState("");
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState("");
  const [target, setTarget] = useState("");
  const [parts, setParts] = useState(["colors", "radius", "type"]);
  const [busyApply, setBusyApply] = useState(false);
  const [applied, setApplied] = useState(null);

  useEffect(() => { if (currentId) setTarget(currentId); }, [currentId]);
  useEffect(() => {
    const id = setTimeout(() => api.presets({ source, q: query, limit: 60 }).then((r) => setRows(r.presets || [])).catch((e) => notify(e.message)), 200);
    return () => clearTimeout(id);
  }, [source, query]);

  const pick = async () => {
    setBusyPick(true);
    try {
      const res = await api.presetsPick({ brief, n: 3 });
      setPicked(res);
      setSelected(res.recommended || "");
    } catch (e) {
      notify(e.message);
    } finally {
      setBusyPick(false);
    }
  };

  const toggle = (part) => setParts((cur) => (cur.includes(part) ? cur.filter((x) => x !== part) : [...cur, part]));

  const apply = async () => {
    if (!selected) return;
    setBusyApply(true);
    try {
      const body = { preset: selected };
      if (target) { body.tokens_id = target; body.parts = parts; }
      const res = await api.presetApply(body);
      setApplied(res);
      onApplied && onApplied(res.tokens_id);
    } catch (e) {
      notify(e.message);
    } finally {
      setBusyApply(false);
    }
  };

  return (
    <div className="panel" data-testid="preset-picker">
      <h2 className="text-[14px] font-semibold">{L("Presets de diseño", "Design presets")}</h2>
      <div className="flex gap-2 mt-3 items-end flex-wrap">
        <div className="flex-1 min-w-[200px]">
          <label className="label" htmlFor="preset-brief">{L("¿Para qué es el diseño?", "What is the design for?")}</label>
          <input id="preset-brief" className="field" value={brief} onChange={(e) => setBrief(e.target.value)}
            placeholder={L("p. ej. seguimiento de envíos para importadores", "e.g. shipment tracking for small importers")} />
        </div>
        <button type="button" className="btn btn-primary" onClick={pick} disabled={busyPick || brief.trim().length < 3} data-testid="preset-pick">
          {busyPick ? L("Eligiendo…", "Picking…") : L("Proponer tres", "Pick three")}
        </button>
        <button type="button" className="btn" data-testid="preset-flexoki"
          title={L("Paleta Flexoki de Steph Ango (MIT): tinta sobre papel, claro y oscuro", "Steph Ango's Flexoki palette (MIT): ink on paper, light and dark")}
          onClick={() => { setSelected("flexoki"); setSource("flexoki"); setQuery(""); setCatalogOpen(true); }}>
          {L("Elegir Flexoki", "Choose Flexoki")}
        </button>
      </div>
      {picked && (
        <div className="mt-3">
          <div className="help mb-2">{picked.source === "model" ? `${L("Ordenado por", "Ranked by")} ${picked.model || L("el modelo", "the model")}` : L("Ordenado por palabras clave (sin modelo)", "Ranked by keywords (no model)")}</div>
          <div className="grid gap-2 md:grid-cols-3" data-testid="preset-picks">
            {picked.candidates.map((p) => <PresetCard key={p.name} p={p} L={L} active={selected === p.name} onSelect={setSelected} recommended={p.name === picked.recommended} />)}
          </div>
        </div>
      )}
      <details className="mt-3" open={catalogOpen} onToggle={(e) => setCatalogOpen(e.currentTarget.open)}>
        <summary className="text-[13px] cursor-pointer">{L("Catálogo", "Catalogue")}</summary>
        <div className="flex gap-2 mt-2 flex-wrap">
          <select className="field" style={{ maxWidth: 200 }} value={source} onChange={(e) => setSource(e.target.value)} aria-label={L("Origen", "Source")}>
            {SOURCES.map(([v, es, en]) => <option key={v} value={v}>{L(es, en)}</option>)}
          </select>
          <input className="field flex-1" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={L("Buscar preset", "Search presets")} aria-label={L("Buscar preset", "Search presets")} />
        </div>
        <div className="grid gap-2 md:grid-cols-2 mt-2" style={{ maxHeight: 420, overflowY: "auto" }}>
          {rows.map((p) => <PresetCard key={p.name} p={p} L={L} active={selected === p.name} onSelect={setSelected} />)}
        </div>
      </details>
      <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--line)" }}>
        <div className="grid gap-2 md:grid-cols-2">
          <div>
            <label className="label" htmlFor="preset-target">{L("Aplicar a", "Apply to")}</label>
            <select id="preset-target" className="field" value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">{L("Nuevo design system (preset completo)", "New design system (whole preset)")}</option>
              {(saved || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div>
            <div className="label">{L("Partes", "Parts")}</div>
            <div className="flex gap-1 flex-wrap">
              {PARTS.map(([v, es, en]) => (
                <button key={v} type="button" className={`btn btn-sm ${parts.includes(v) ? "btn-active" : ""}`} aria-pressed={parts.includes(v)} disabled={!target}
                  onClick={() => toggle(v)}>{L(es, en)}</button>
              ))}
            </div>
          </div>
        </div>
        <div className="flex gap-2 items-center flex-wrap mt-3">
          <button type="button" className="btn btn-primary" onClick={apply} disabled={!selected || busyApply || (target && !parts.length)} data-testid="preset-apply">
            {busyApply ? L("Aplicando…", "Applying…") : `${L("Aplicar", "Apply")} ${selected || ""}`}
          </button>
          {selected && <a className="btn-link text-[12px]" href={api.registryItemUrl(selected)} target="_blank" rel="noreferrer">registry-item.json</a>}
          {applied && <span className="help" data-testid="preset-applied">{L("Aplicado", "Applied")}: {applied.preset.title} → {applied.name} ({applied.parts.join(", ")})</span>}
        </div>
        {applied?.contrast_pairs && (
          <details className="mt-2" data-testid="preset-contrast">
            <summary className="text-[13px] cursor-pointer">
              {L("Contraste de los pares texto/fondo", "Contrast of the text/background pairs")}: {applied.contrast_pairs.filter((c) => c.level !== "fail").length}/{applied.contrast_pairs.length} AA
            </summary>
            <div className="grid gap-1 mt-2 md:grid-cols-2 text-[12px]">
              {applied.contrast_pairs.map((c, k) => (
                <div key={k} className="flex items-center gap-2">
                  <span style={{ background: c.bg, color: c.fg, border: "1px solid var(--line)", borderRadius: 4, padding: "0 6px" }}>Aa</span>
                  <span>{c.mode === "light" ? L("claro", "light") : L("oscuro", "dark")} · {c.text} / {c.on}</span>
                  <span className={`chip ${c.level === "fail" ? "" : "chip-ok"}`}>{c.ratio}:1 {c.level}</span>
                </div>
              ))}
            </div>
            {applied.preset.license && <p className="help mt-2">{applied.preset.license.notice}</p>}
          </details>
        )}
      </div>
    </div>
  );
}
