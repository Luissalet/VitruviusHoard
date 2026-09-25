import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { Empty, StatusPill, LicenseBadge, CopyButton, Tabs, ColorSwatch } from "../components/ui.jsx";

const KINDS = ["skill", "guide", "rule", "catalog", "reference", "readme", "other"];
const AREAS = ["typography", "color", "layout", "motion", "a11y", "forms", "performance", "content"];

function SearchPanel({ t }) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [source, setSource] = useState("");
  const [area, setArea] = useState("");
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const run = async (e) => {
    e?.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await api.librarySearch({ query, kind: kind || undefined, source: source || undefined, area: area || undefined, limit: 20 });
      setItems(res.items);
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <form onSubmit={run} className="flex flex-col gap-3">
        <input
          className="field"
          placeholder={t("library_search_placeholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label={t("library_search_placeholder")}
        />
        <div className="grid grid-cols-3 gap-2">
          <select className="field" value={kind} onChange={(e) => setKind(e.target.value)} aria-label={t("library_kind")}>
            <option value="">{t("library_kind")}</option>
            {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <input className="field" placeholder={t("library_source")} value={source} onChange={(e) => setSource(e.target.value)} aria-label={t("library_source")} />
          <select className="field" value={area} onChange={(e) => setArea(e.target.value)} aria-label={t("library_area")}>
            <option value="">{t("library_area")}</option>
            {AREAS.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <button type="submit" className="btn btn-primary self-start" disabled={busy || !query.trim()}>
          {t("search") || "Search"}
        </button>
      </form>

      {err && <div className="help mt-3" style={{ color: "var(--danger)" }}>{err}</div>}

      <div className="mt-4 flex flex-col gap-3">
        {items === null && <div className="help">{t("library_empty")}</div>}
        {items !== null && items.length === 0 && <div className="help">{t("library_no_results")}</div>}
        {items?.map((item, i) => (
          <div key={i} className="card">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="chip chip-accent">{item.kind}</span>
                <span className="help">{item.source}</span>
                <LicenseBadge license={item.license} t={t} />
                {item.match && item.match !== "bm25" && (
                  <span className="chip" title={t("match_hint")}>{t(`match_${item.match}`)}{item.similarity != null ? ` · ${item.similarity}` : ""}</span>
                )}
              </div>
              <CopyButton value={item.cite} t={t} />
            </div>
            {item.heading && <div className="mt-2 text-[12px] font-semibold" style={{ color: "var(--light)" }}>{item.heading}</div>}
            <div className="mt-1 text-[13px]" style={{ color: "var(--ink)" }}>{item.text}</div>
            <div className="mono mt-2" style={{ color: "var(--muted)" }}>{item.cite}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EmbeddingsBar({ t, notify }) {
  const [st, setSt] = useState(null);
  const load = async () => {
    try { setSt(await api.embeddings()); } catch (e) { /* older server: no dense search */ }
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!st || !["queued", "building"].includes(st.build?.state)) return undefined;
    const timer = setTimeout(load, 2000);
    return () => clearTimeout(timer);
  }, [st]);
  if (!st) return null;
  const building = ["queued", "building"].includes(st.build?.state);
  const build = async () => {
    try { await api.embeddingsBuild(); load(); } catch (e) { notify(e.message); }
  };
  return (
    <div className="card mb-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="text-[13px] font-semibold">{t("dense_title")}</div>
        <button type="button" className="btn btn-sm" onClick={build} disabled={building || st.backend === "none"}>
          {building ? `${t("dense_building")} ${st.build.done}/${st.build.total}` : t("dense_build")}
        </button>
      </div>
      <div className="help mt-1">
        {st.active ? t("dense_on") : t("dense_off")} · {st.vectors}/{st.chunks} · {st.model || st.backend}
        {st.error ? ` · ${st.error}` : ""}{st.build?.error ? ` · ${st.build.error}` : ""}
      </div>
    </div>
  );
}

function SourcesPanel({ t, notify }) {
  const [sources, setSources] = useState(null);
  const [form, setForm] = useState({ url: "", id: "", license: "", category: "" });
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const res = await api.sources();
      setSources(res.sources);
    } catch (e) {
      notify(e.message);
    }
  };
  useEffect(() => { load(); }, []);

  const ingest = async (id) => {
    try {
      await api.sourceIngest(id);
      notify(`${id}: queued`);
      load();
    } catch (e) {
      notify(e.message);
    }
  };

  const ingestAll = async () => {
    if (!sources) return;
    for (const s of sources) {
      // eslint-disable-next-line no-await-in-loop
      await api.sourceIngest(s.id).catch((e) => notify(e.message));
    }
    load();
  };

  const addSource = async (e) => {
    e.preventDefault();
    if (!form.url.trim()) return;
    setBusy(true);
    try {
      await api.sourceAdd({
        url: form.url,
        id: form.id || undefined,
        license: form.license,
        category: form.category,
      });
      setForm({ url: "", id: "", license: "", category: "" });
      notify(t("saved"));
      load();
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[14px] font-semibold">{t("sources_title")}</h2>
        <button type="button" className="btn btn-sm" onClick={ingestAll} disabled={!sources?.length}>{t("sources_ingest_all")}</button>
      </div>
      <EmbeddingsBar t={t} notify={notify} />
      <div className="flex flex-col gap-2 mb-4">
        {sources === null && <div className="help">{t("sources_empty")}</div>}
        {sources?.length === 0 && <div className="help">{t("sources_empty")}</div>}
        {sources?.map((s) => (
          <div key={s.id} className="flex items-center justify-between gap-2 border-t pt-2 first:border-t-0 first:pt-0 flex-wrap" style={{ borderColor: "var(--line)" }}>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold text-[13px]">{s.id}</span>
                <StatusPill status={s.status} t={t} />
                <LicenseBadge license={s.license} t={t} />
              </div>
              <div className="help">{s.docs ?? 0} {t("docs")} · {s.chunks ?? 0} {t("chunks")}{s.error ? ` · ${s.error}` : ""}</div>
            </div>
            <button type="button" className="btn btn-sm" onClick={() => ingest(s.id)} disabled={s.status === "cloning" || s.status === "ingesting"}>
              {t("sources_ingest")}
            </button>
          </div>
        ))}
      </div>
      <form onSubmit={addSource} className="flex flex-col gap-2 border-t pt-3" style={{ borderColor: "var(--line)" }}>
        <div className="text-[12px] font-semibold" style={{ color: "var(--muted)" }}>{t("sources_add_title")}</div>
        <input className="field" placeholder={t("sources_add_url")} value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} aria-label={t("sources_add_url")} />
        <div className="grid grid-cols-3 gap-2">
          <input className="field" placeholder={t("sources_add_id")} value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} aria-label={t("sources_add_id")} />
          <input className="field" placeholder={t("sources_add_license")} value={form.license} onChange={(e) => setForm({ ...form, license: e.target.value })} aria-label={t("sources_add_license")} />
          <input className="field" placeholder={t("sources_add_category")} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} aria-label={t("sources_add_category")} />
        </div>
        <button type="submit" className="btn btn-primary self-start" disabled={busy || !form.url.trim()}>{t("add")}</button>
      </form>
    </div>
  );
}

function StylesTab({ t, items }) {
  if (!items?.length) return <Empty>{t("catalog_empty")}</Empty>;
  return (
    <div className="grid-cards">
      {items.map((s) => (
        <div key={s.id} className="card">
          <div className="font-semibold text-[13px]">{s.name}</div>
          <div className="help mt-1">{s.description}</div>
          {!!s.keywords?.length && (
            <div className="flex flex-wrap gap-1 mt-2">
              {s.keywords.map((k) => <span key={k} className="chip">{k}</span>)}
            </div>
          )}
          {!!s.colors?.length && (
            <div className="flex flex-wrap gap-1 mt-2">
              {s.colors.slice(0, 6).map((c, i) => (
                <span key={i} className="swatch" style={{ background: c, width: 20, height: 20, display: "inline-block" }} title={c} />
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function PalettesTab({ t, items }) {
  if (!items?.length) return <Empty>{t("catalog_empty")}</Empty>;
  return (
    <div className="flex flex-col gap-3">
      {items.map((p) => (
        <div key={p.id} className="card">
          <div className="flex items-center justify-between">
            <div className="font-semibold text-[13px]">{p.name}</div>
            <span className="help">{p.product_type}</span>
          </div>
          <div className="flex flex-wrap gap-3 mt-2">
            {p.colors?.map((c, i) => <ColorSwatch key={i} hex={c.hex} label={c.role} />)}
          </div>
        </div>
      ))}
    </div>
  );
}

function FontsTab({ t, items }) {
  if (!items?.length) return <Empty>{t("catalog_empty")}</Empty>;
  return (
    <div className="grid-cards">
      {items.map((f) => (
        <div key={f.id} className="card">
          <div className="text-[18px]" style={{ fontFamily: "Georgia, serif" }}>{f.heading || "—"}</div>
          <div className="text-[13px]">{f.body || "—"}</div>
          {f.mono && <div className="mono mt-1">{f.mono}</div>}
          <div className="help mt-2">{f.mood || f.category}</div>
        </div>
      ))}
    </div>
  );
}

function CatalogPanel({ t }) {
  const [tab, setTab] = useState("styles");
  const [styles, setStyles] = useState(null);
  const [palettes, setPalettes] = useState(null);
  const [fonts, setFonts] = useState(null);

  useEffect(() => {
    api.catalogStyles(200).then((r) => setStyles(r.styles)).catch(() => setStyles([]));
    api.catalogPalettes(200).then((r) => setPalettes(r.palettes)).catch(() => setPalettes([]));
    api.catalogFonts(200).then((r) => setFonts(r.fonts)).catch(() => setFonts([]));
  }, []);

  return (
    <div className="panel">
      <Tabs
        tabs={[
          { key: "styles", label: t("catalog_styles") },
          { key: "palettes", label: t("catalog_palettes") },
          { key: "fonts", label: t("catalog_fonts") },
        ]}
        active={tab}
        onChange={setTab}
      />
      <div className="pt-4">
        {tab === "styles" && <StylesTab t={t} items={styles} />}
        {tab === "palettes" && <PalettesTab t={t} items={palettes} />}
        {tab === "fonts" && <FontsTab t={t} items={fonts} />}
      </div>
    </div>
  );
}

function BriefPanel({ t }) {
  const [subject, setSubject] = useState("");
  const [vibe, setVibe] = useState("");
  const [productType, setProductType] = useState("");
  const [platform, setPlatform] = useState("");
  const [mode, setMode] = useState("marketing");
  const [variance, setVariance] = useState(5);
  const [motion, setMotion] = useState(5);
  const [density, setDensity] = useState(5);
  const [brief, setBrief] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const generate = async (e) => {
    e.preventDefault();
    if (!subject.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await api.libraryBrief({
        subject,
        vibe: vibe || undefined,
        product_type: productType || undefined,
        platform: platform || undefined,
        mode,
        knobs: { variance, motion, density },
      });
      setBrief(res);
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2 className="text-[14px] font-semibold mb-3">{t("brief_title")}</h2>
      <form onSubmit={generate} className="flex flex-col gap-3">
        <div>
          <label className="label" htmlFor="brief-subject">{t("brief_subject")}</label>
          <input id="brief-subject" className="field" placeholder={t("brief_subject_ph")} value={subject} onChange={(e) => setSubject(e.target.value)} />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <input className="field" placeholder={t("brief_vibe")} value={vibe} onChange={(e) => setVibe(e.target.value)} aria-label={t("brief_vibe")} />
          <input className="field" placeholder={t("brief_product_type")} value={productType} onChange={(e) => setProductType(e.target.value)} aria-label={t("brief_product_type")} />
          <input className="field" placeholder={t("brief_platform")} value={platform} onChange={(e) => setPlatform(e.target.value)} aria-label={t("brief_platform")} />
          <select className="field" value={mode} onChange={(e) => setMode(e.target.value)} aria-label={t("brief_mode")}>
            <option value="marketing">{t("brief_mode_marketing")}</option>
            <option value="product">{t("brief_mode_product")}</option>
          </select>
        </div>
        <div className="grid grid-cols-3 gap-3">
          {[
            [t("brief_knob_variance"), variance, setVariance],
            [t("brief_knob_motion"), motion, setMotion],
            [t("brief_knob_density"), density, setDensity],
          ].map(([label, val, setVal]) => (
            <div key={label}>
              <label className="label">{label} ({val})</label>
              <input type="range" min="1" max="10" value={val} onChange={(e) => setVal(Number(e.target.value))} className="w-full" aria-label={label} />
            </div>
          ))}
        </div>
        <button type="submit" className="btn btn-primary self-start" disabled={busy || !subject.trim()}>{t("brief_generate")}</button>
      </form>

      {err && <div className="help mt-3" style={{ color: "var(--danger)" }}>{err}</div>}

      {!brief && <div className="help mt-4">{t("brief_empty")}</div>}

      {brief && (
        <div className="mt-5 flex flex-col gap-4">
          {!!brief.styles?.length && (
            <div>
              <h3 className="text-[13px] font-semibold mb-2">{t("brief_styles")}</h3>
              <div className="grid-cards">
                {brief.styles.map((s) => (
                  <div key={s.id} className="card">
                    <div className="font-semibold text-[13px]">{s.name}</div>
                    <div className="help mt-1">{s.description}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {brief.palette && (
            <div>
              <h3 className="text-[13px] font-semibold mb-2">{t("brief_palette")}</h3>
              <div className="flex flex-wrap gap-3">
                {brief.palette.colors?.map((c, i) => <ColorSwatch key={i} hex={c.hex} label={c.role} />)}
              </div>
            </div>
          )}
          {brief.font_pairing && (
            <div>
              <h3 className="text-[13px] font-semibold mb-2">{t("brief_fonts")}</h3>
              <div className="card">
                <div className="text-[16px]" style={{ fontFamily: "Georgia, serif" }}>{brief.font_pairing.heading}</div>
                <div>{brief.font_pairing.body}</div>
                {brief.font_pairing.mono && <div className="mono mt-1">{brief.font_pairing.mono}</div>}
              </div>
            </div>
          )}
          {!!brief.rules?.length && (
            <div>
              <h3 className="text-[13px] font-semibold mb-2">{t("brief_rules")}</h3>
              <ul className="flex flex-col gap-1 list-disc pl-5 text-[13px]">
                {brief.rules.map((r) => <li key={r.id}>{r.title}: {r.text}</li>)}
              </ul>
            </div>
          )}
          {!!brief.anti_patterns?.length && (
            <div>
              <h3 className="text-[13px] font-semibold mb-2">{t("brief_anti_patterns")}</h3>
              <ul className="flex flex-col gap-1 list-disc pl-5 text-[13px]">
                {brief.anti_patterns.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          )}
          {!!brief.checklist?.length && (
            <div>
              <h3 className="text-[13px] font-semibold mb-2">{t("brief_checklist")}</h3>
              <ul className="flex flex-col gap-1 list-disc pl-5 text-[13px]">
                {brief.checklist.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            </div>
          )}
          {brief.direction && (
            <div>
              <h3 className="text-[13px] font-semibold mb-2">{t("brief_direction")}</h3>
              <p className="text-[13px]">{brief.direction}</p>
            </div>
          )}
          {!!brief.cites?.length && (
            <div className="flex flex-wrap gap-2">
              {brief.cites.map((c, i) => <span key={i} className="mono chip chip-wrap">{c}</span>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Library() {
  const { t, notify } = useApp();
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-[20px] font-semibold">{t("nav_library")}</h1>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-6">
          <SearchPanel t={t} />
          <BriefPanel t={t} />
        </div>
        <div className="flex flex-col gap-6">
          <SourcesPanel t={t} notify={notify} />
          <CatalogPanel t={t} />
        </div>
      </div>
    </div>
  );
}
