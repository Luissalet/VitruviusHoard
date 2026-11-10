import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { fileRelPath } from "../format.js";

// Design galleries as references: what each one gives, when to use it, its areas and licence note, and a captured sample page
// (screenshot + fragments) that the brief and the critique cite as [vitruvius: gallery/<id>].
const AREAS = [
  ["", "Todas las áreas", "All areas"], ["layout", "Maquetación", "Layout"], ["motion", "Movimiento", "Motion"], ["color", "Color", "Colour"],
  ["typography", "Tipografía", "Typography"], ["components", "Componentes", "Components"], ["effects", "Efectos", "Effects"],
  ["imagery", "Imagen", "Imagery"], ["iconography", "Iconografía", "Iconography"], ["content", "Contenido", "Content"],
];

function GalleryCard({ g, L, es, busy, onCapture, onOpen }) {
  const sample = g.samples?.[0];
  const shot = sample?.files?.desktop;
  return (
    <div className="card p-0 overflow-hidden flex flex-col" data-testid="design-gallery" data-gallery={g.id}>
      <button type="button" className="text-left" onClick={() => sample && onOpen(sample.id)} disabled={!sample}
        style={{ aspectRatio: "16/9", background: "var(--surface-2)", display: "block" }} aria-label={sample ? (sample.title || g.name) : g.name}>
        {shot
          ? <img loading="lazy" src={api.referenceFileUrl(sample.id, fileRelPath(shot, sample.id))} alt="" className="w-full h-full object-cover object-top" />
          : <span className="help flex items-center justify-center h-full">{L("Sin muestra capturada", "No sample captured")}</span>}
      </button>
      <div className="p-3 flex flex-col gap-2 flex-1">
        <div className="flex items-center justify-between gap-2">
          <a href={g.url} target="_blank" rel="noreferrer" className="font-semibold text-[13px] truncate">{g.name}</a>
          <span className="chip">{g.kind}</span>
        </div>
        <p className="text-[13px]">{es ? g.provides_es : g.provides}</p>
        {(g.when || g.when_es) && <p className="help"><strong>{L("Cuándo", "When")}:</strong> {es ? g.when_es : g.when}</p>}
        <div className="flex flex-wrap gap-1">{g.areas.map((a) => <span key={a} className="chip chip-accent">{a}</span>)}</div>
        {sample && (
          <div className="help" data-testid="gallery-fragments">
            {sample.fragments.headings.length > 0 && <p className="truncate" title={sample.fragments.headings.map((h) => h.text).join(" · ")}>
              {L("Titulares", "Headings")}: {sample.fragments.headings.slice(0, 3).map((h) => h.text).join(" · ")}</p>}
            {sample.fragments.ctas.length > 0 && <p className="truncate">CTA: {sample.fragments.ctas.slice(0, 4).join(" · ")}</p>}
            {sample.fragments.footer_links.length > 0 && <p className="truncate">{L("Pie", "Footer")}: {sample.fragments.footer_links.slice(0, 6).join(" · ")}</p>}
            <p className="truncate" title={sample.cite}>{sample.cite}</p>
          </div>
        )}
        <p className="help truncate" title={g.license}>{g.license}</p>
        <div className="flex gap-2 mt-auto">
          <button type="button" className="btn btn-sm" disabled={busy} onClick={() => onCapture(g.id)} data-testid="gallery-capture">
            {busy ? L("Capturando…", "Capturing…") : sample ? L("Volver a capturar", "Capture again") : L("Capturar muestra", "Capture sample")}
          </button>
          {sample && <button type="button" className="btn btn-sm" onClick={() => onOpen(sample.id)}>{L("Ver muestra", "Open sample")}</button>}
        </div>
      </div>
    </div>
  );
}

export default function DesignGalleries({ lang, notify, onOpen, onChanged }) {
  const es = lang === "es";
  const L = (a, b) => (es ? a : b);
  const [query, setQuery] = useState("");
  const [area, setArea] = useState("");
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState({});
  const [all, setAll] = useState(false);

  const load = (q = query, a = area) => api.galleries({ q: q || undefined, area: a || undefined, limit: 30 })
    .then((r) => setRows(r.galleries)).catch((e) => notify(e.message));
  useEffect(() => { load(); }, [area]);

  const capture = async (id) => {
    setBusy((b) => ({ ...b, [id]: true }));
    try {
      const res = await api.galleriesIngest({ ids: [id] });
      const r = res.results[0];
      if (!r.ok) notify(`${id}: ${r.error}`);
      await load();
      onChanged && onChanged();
    } catch (e) { notify(e.message); }
    finally { setBusy((b) => ({ ...b, [id]: false })); }
  };

  const captureAll = async () => {
    setAll(true);
    for (const g of (rows || []).filter((x) => x.curated && x.sample_url)) await capture(g.id);
    setAll(false);
  };

  return (
    <section className="panel flex flex-col gap-3" data-testid="design-galleries">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="text-[15px] font-semibold">{L("Galerías de diseño", "Design galleries")}</h2>
        <button type="button" className="btn btn-sm" disabled={all || !rows} onClick={captureAll} data-testid="gallery-capture-all">
          {all ? L("Capturando muestras…", "Capturing samples…") : L("Capturar todas las muestras", "Capture every sample")}
        </button>
      </div>
      <p className="help">{L("Fuentes de referencia por parte de la página: scroll, shaders, pies de página, CTA, estilos de producto, heros, iconos 3D y cristal. Cada muestra guarda la captura y sus fragmentos para citarlos en el brief y la crítica.",
        "Reference sources by part of the page: scroll, shaders, footers, CTAs, product styles, heroes, 3D icons and glass. Each sample keeps its capture and fragments so the brief and the critique can cite them.")}</p>
      <form className="flex gap-2 flex-wrap" onSubmit={(e) => { e.preventDefault(); load(); }}>
        <input className="field" style={{ maxWidth: 280 }} value={query} onChange={(e) => setQuery(e.target.value)} data-testid="gallery-query"
          placeholder={L("p. ej. footers, ejemplos de CTA", "e.g. footers, CTA examples")} aria-label={L("Buscar galería", "Search galleries")} />
        <select className="field" style={{ maxWidth: 200 }} value={area} onChange={(e) => setArea(e.target.value)} aria-label={L("Área", "Area")}>
          {AREAS.map(([v, a, b]) => <option key={v} value={v}>{L(a, b)}</option>)}
        </select>
        <button type="submit" className="btn" data-testid="gallery-search">{L("Buscar", "Search")}</button>
      </form>
      {rows && rows.length === 0 && <p className="help">{L("Ninguna galería encaja con esa búsqueda.", "No gallery fits that search.")}</p>}
      {!!rows?.length && (
        <div className="grid-cards">
          {rows.map((g) => <GalleryCard key={g.id} g={g} L={L} es={es} busy={!!busy[g.id]} onCapture={capture} onOpen={onOpen} />)}
        </div>
      )}
    </section>
  );
}
