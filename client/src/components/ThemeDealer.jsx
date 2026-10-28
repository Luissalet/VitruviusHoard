import React, { useEffect, useState } from "react";
import { api } from "../api.js";

const GENRES = ["", "editorial", "modern-minimal", "atmospheric", "playful"];

function Swatch({ label, value, color }) {
  return (
    <span className="chip" title={label}>
      {color && <span className="dot" style={{ background: color, border: "1px solid var(--line)" }} />}
      {label}: {value}
    </span>
  );
}

// Deals a hand of themes that avoids the last three builds; the same seed reproduces the hand.
export default function ThemeDealer({ t, notify }) {
  const [prompt, setPrompt] = useState("");
  const [genre, setGenre] = useState("");
  const [seed, setSeed] = useState("");
  const [hand, setHand] = useState(null);
  const [memory, setMemory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [genres, setGenres] = useState(GENRES);

  const loadMemory = () => api.themesMemory(12).then((r) => setMemory(r.memory || [])).catch((e) => notify(e.message));
  useEffect(() => {
    loadMemory();
    api.themes().then((r) => {
      const found = Array.from(new Set((r.themes || []).map((x) => x.genre))).sort();
      if (found.length) setGenres(["", ...found]);
    }).catch(() => {});
  }, []);

  const deal = async (reroll) => {
    setBusy(true);
    try {
      const body = { prompt, n: 3 };
      if (genre) body.genre = genre;
      if (reroll && hand) { body.seed = hand.seed.replace(/·r\d+$/, ""); body.reroll = (hand.reroll || 0) + 1; }
      else if (seed.trim()) body.seed = seed.trim();
      const res = await api.themesDeal(body);
      setHand(res);
      setSeed(res.seed);
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2 className="text-[14px] font-semibold">{t("dq_themes_title")}</h2>
      <div className="grid gap-3 md:grid-cols-[2fr_1fr_1fr] mt-3">
        <div>
          <label className="label" htmlFor="theme-prompt">{t("dq_themes_prompt")}</label>
          <input id="theme-prompt" className="field" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="theme-genre">{t("dq_themes_genre")}</label>
          <select id="theme-genre" className="field" value={genre} onChange={(e) => setGenre(e.target.value)}>
            {genres.map((g) => <option key={g} value={g}>{g || t("dq_rules_all")}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="theme-seed">{t("dq_themes_seed")}</label>
          <input id="theme-seed" className="field mono" value={seed} onChange={(e) => setSeed(e.target.value)} />
        </div>
      </div>
      <div className="flex gap-2 flex-wrap mt-3">
        <button type="button" className="btn btn-primary" onClick={() => deal(false)} disabled={busy}>{t("dq_themes_deal")}</button>
        <button type="button" className="btn" onClick={() => deal(true)} disabled={busy || !hand}>{t("dq_themes_reroll")}</button>
      </div>
      {hand && (
        <div className="grid gap-3 md:grid-cols-3 mt-4" data-testid="theme-hand">
          {hand.deal.map((d) => (
            <div key={d.slug} className="card">
              <div className="font-semibold text-[13px]">{d.name}</div>
              <div className="help">{d.genre} · {d.posture}</div>
              <div className="flex flex-wrap gap-1 mt-2">
                <Swatch label="paper" value={d.paper.band} color={`oklch(${d.paper.L}% 0.02 ${d.paper.hue})`} />
                <Swatch label="display" value={d.display.face} />
                <Swatch label="accent" value={d.accent.band} color={`oklch(62% 0.17 ${d.accent.hue})`} />
              </div>
              <div className="help mt-2">{d.material}</div>
              <div className="help mt-1">{d.why}</div>
            </div>
          ))}
        </div>
      )}
      {hand?.blocked?.length > 0 && (
        <div className="help mt-3">{t("dq_themes_blocked")}: {hand.blocked.map((b) => b.slug).join(", ")}</div>
      )}
      <h3 className="text-[13px] font-semibold mt-4 mb-1">{t("dq_themes_memory")}</h3>
      {!memory.length && <div className="help">{t("dq_themes_empty")}</div>}
      <div className="flex flex-col gap-1">
        {memory.map((m) => (
          <div key={m.id} className="help"><strong>{m.name}</strong> · <span className="mono">{m.axes}</span>{m.prompt ? ` · ${m.prompt}` : ""}</div>
        ))}
      </div>
    </div>
  );
}
