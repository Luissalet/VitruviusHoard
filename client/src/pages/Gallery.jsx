import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { Empty, ConfirmButton } from "../components/ui.jsx";
import { fileRelPath } from "../format.js";

function ReferenceCard({ ref, t, onOpen }) {
  const [hover, setHover] = useState(false);
  const poster = ref.files?.poster || ref.files?.desktop;
  const video = ref.files?.video;
  return (
    <button
      type="button"
      className="card text-left p-0 overflow-hidden"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={() => onOpen(ref.id)}
    >
      <div className="relative" style={{ aspectRatio: "16/10", background: "var(--surface-2)" }}>
        {hover && video ? (
          <video
            src={api.referenceFileUrl(ref.id, fileRelPath(video, ref.id))}
            poster={poster ? api.referenceFileUrl(ref.id, fileRelPath(poster, ref.id)) : undefined}
            muted
            loop
            autoPlay
            playsInline
            className="w-full h-full object-cover"
          />
        ) : poster ? (
          <img src={api.referenceFileUrl(ref.id, fileRelPath(poster, ref.id))} alt={ref.title || ref.url} className="w-full h-full object-cover" />
        ) : null}
      </div>
      <div className="p-3">
        <div className="font-semibold text-[13px] truncate">{ref.title || ref.url}</div>
        <div className="flex flex-wrap gap-1 mt-2">
          {(ref.tags || []).map((tag) => <span key={tag} className="chip">{tag}</span>)}
        </div>
        <div className="flex flex-wrap gap-1 mt-2">
          {(ref.fonts || []).slice(0, 3).map((f) => <span key={f} className="chip chip-accent">{f}</span>)}
          {(ref.libs || []).slice(0, 3).map((l) => <span key={l} className="chip">{l}</span>)}
        </div>
      </div>
    </button>
  );
}

function Drawer({ id, t, onClose, onDeleted }) {
  const [ref, setRef] = useState(null);
  useEffect(() => {
    api.reference(id).then(setRef).catch(() => setRef(null));
  }, [id]);
  if (!ref) return null;
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="drawer" role="dialog" aria-label={ref.title || ref.url}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-[15px] font-semibold truncate">{ref.title || ref.url}</h2>
          <button type="button" className="btn btn-sm" onClick={onClose} aria-label={t("close")}>{t("close")}</button>
        </div>
        <a href={ref.url} target="_blank" rel="noreferrer" className="help block mb-4 truncate">{ref.url}</a>

        <div className="grid grid-cols-2 gap-3 mb-4">
          {ref.files?.desktop && (
            <figure>
              <img src={api.referenceFileUrl(ref.id, fileRelPath(ref.files.desktop, ref.id))} alt="" className="w-full rounded-md border" style={{ borderColor: "var(--line)" }} />
              <figcaption className="help text-center mt-1">{t("gallery_detail_desktop")}</figcaption>
            </figure>
          )}
          {ref.files?.mobile && (
            <figure>
              <img src={api.referenceFileUrl(ref.id, fileRelPath(ref.files.mobile, ref.id))} alt="" className="w-full rounded-md border" style={{ borderColor: "var(--line)" }} />
              <figcaption className="help text-center mt-1">{t("gallery_detail_mobile")}</figcaption>
            </figure>
          )}
        </div>

        {!!ref.palette?.length && (
          <div className="mb-4">
            <h3 className="text-[13px] font-semibold mb-2">{t("gallery_detail_palette")}</h3>
            <div className="flex flex-wrap gap-2">
              {ref.palette.map((hex, i) => (
                <span key={i} className="swatch" style={{ background: hex, width: 32, height: 24, display: "inline-block" }} title={hex} />
              ))}
            </div>
          </div>
        )}

        {!!ref.fonts?.length && (
          <div className="mb-4">
            <h3 className="text-[13px] font-semibold mb-2">{t("gallery_detail_fonts")}</h3>
            <div className="flex flex-wrap gap-1">{ref.fonts.map((f) => <span key={f} className="chip">{f}</span>)}</div>
          </div>
        )}

        {!!ref.libs?.length && (
          <div className="mb-4">
            <h3 className="text-[13px] font-semibold mb-2">{t("gallery_detail_libs")}</h3>
            <div className="flex flex-wrap gap-1">{ref.libs.map((l) => <span key={l} className="chip">{l}</span>)}</div>
          </div>
        )}

        {ref.motion && (
          <div className="mb-4">
            <h3 className="text-[13px] font-semibold mb-2">{t("gallery_detail_motion")}</h3>
            <div className="help">
              {ref.motion.animations ?? 0} {t("gallery_motion_animations")} · {ref.motion.transitions ?? 0} {t("gallery_motion_transitions")}
              {ref.motion.scroll_driven ? ` · ${t("gallery_motion_scroll")}` : ""}
              {ref.motion.reduced_motion_respected ? ` · ${t("gallery_motion_reduced")}` : ""}
            </div>
          </div>
        )}

        {(ref.vibe || ref.analysis) && (
          <div className="mb-4">
            <h3 className="text-[13px] font-semibold mb-2">{t("gallery_detail_analysis")}</h3>
            <p className="text-[13px]">{ref.vibe}</p>
            {ref.analysis?.raw && <p className="text-[13px] mt-1">{ref.analysis.raw}</p>}
          </div>
        )}

        {ref.note && <p className="help mb-4">{ref.note}</p>}

        <ConfirmButton t={t} onConfirm={() => onDeleted(ref.id)} />
      </div>
    </>
  );
}

export default function Gallery() {
  const { t, notify } = useApp();
  const [items, setItems] = useState(null);
  const [query, setQuery] = useState("");
  const [tag, setTag] = useState("");
  const [vibe, setVibe] = useState("");
  const [lib, setLib] = useState("");
  const [addUrl, setAddUrl] = useState("");
  const [addTags, setAddTags] = useState("");
  const [addNote, setAddNote] = useState("");
  const [video, setVideo] = useState(true);
  const [analyze, setAnalyze] = useState(true);
  const [busy, setBusy] = useState(false);
  const [openId, setOpenId] = useState(null);

  const load = async () => {
    try {
      const res = await api.references({ query: query || undefined, tags: tag || undefined, vibe: vibe || undefined, lib: lib || undefined, limit: 60 });
      setItems(res.references);
    } catch (e) {
      notify(e.message);
    }
  };
  useEffect(() => { load(); }, []);

  const runFilter = (e) => {
    e.preventDefault();
    load();
  };

  const addReference = async (e) => {
    e.preventDefault();
    if (!addUrl.trim()) return;
    setBusy(true);
    try {
      await api.referenceAdd({
        url: addUrl,
        tags: addTags ? addTags.split(",").map((s) => s.trim()).filter(Boolean) : undefined,
        note: addNote,
        video,
        analyze,
      });
      setAddUrl("");
      setAddTags("");
      setAddNote("");
      notify(t("saved"));
      load();
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };

  const deleteReference = async (id) => {
    try {
      await api.referenceDelete(id);
      setOpenId(null);
      load();
    } catch (e) {
      notify(e.message);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-[20px] font-semibold">{t("nav_gallery")}</h1>

      <form onSubmit={addReference} className="panel flex flex-col gap-2">
        <div className="grid md:grid-cols-3 gap-2">
          <input className="field" placeholder={t("gallery_add_url")} value={addUrl} onChange={(e) => setAddUrl(e.target.value)} aria-label={t("gallery_add_url")} />
          <input className="field" placeholder={t("gallery_add_tags")} value={addTags} onChange={(e) => setAddTags(e.target.value)} aria-label={t("gallery_add_tags")} />
          <input className="field" placeholder={t("gallery_add_note")} value={addNote} onChange={(e) => setAddNote(e.target.value)} aria-label={t("gallery_add_note")} />
        </div>
        <div className="flex items-center gap-4 flex-wrap">
          <label className="flex items-center gap-2 text-[13px]">
            <input type="checkbox" checked={video} onChange={(e) => setVideo(e.target.checked)} />
            {t("gallery_add_video")}
          </label>
          <label className="flex items-center gap-2 text-[13px]">
            <input type="checkbox" checked={analyze} onChange={(e) => setAnalyze(e.target.checked)} />
            {t("gallery_add_analyze")}
          </label>
          <button type="submit" className="btn btn-primary" disabled={busy || !addUrl.trim()}>
            {busy ? t("gallery_capturing") : t("gallery_add")}
          </button>
        </div>
      </form>

      <form onSubmit={runFilter} className="panel flex flex-wrap gap-2">
        <input className="field" style={{ maxWidth: 220 }} placeholder={t("gallery_filter_query")} value={query} onChange={(e) => setQuery(e.target.value)} aria-label={t("gallery_filter_query")} />
        <input className="field" style={{ maxWidth: 160 }} placeholder={t("gallery_filter_tag")} value={tag} onChange={(e) => setTag(e.target.value)} aria-label={t("gallery_filter_tag")} />
        <input className="field" style={{ maxWidth: 160 }} placeholder={t("gallery_filter_vibe")} value={vibe} onChange={(e) => setVibe(e.target.value)} aria-label={t("gallery_filter_vibe")} />
        <input className="field" style={{ maxWidth: 160 }} placeholder={t("gallery_filter_lib")} value={lib} onChange={(e) => setLib(e.target.value)} aria-label={t("gallery_filter_lib")} />
        <button type="submit" className="btn">{t("search") || "Search"}</button>
      </form>

      {items === null && <Empty>{t("gallery_empty")}</Empty>}
      {items?.length === 0 && <Empty>{t("gallery_no_results")}</Empty>}
      {!!items?.length && (
        <div className="grid-cards">
          {items.map((ref) => <ReferenceCard key={ref.id} ref={ref} t={t} onOpen={setOpenId} />)}
        </div>
      )}

      {openId && <Drawer id={openId} t={t} onClose={() => setOpenId(null)} onDeleted={deleteReference} />}
    </div>
  );
}
