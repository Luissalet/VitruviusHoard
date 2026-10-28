"""Theme dealing with memory.

A theme is a short, concrete art direction: the paper (light / mid / dark), the display face class and the accent colour band
(together its *axes triple*), a posture and a material. Left alone, a model converges on the same two or three looks; this
module deals a hand of themes against a memory of the recent builds so that two pages in a row do not come out alike.

* The deal is **reproducible**: its ``seed`` (``<prompt>·<salt>·<date>·r<reroll>``) gives the same hand back, and ``reroll``
  moves on to the next one.
* **Blocked**: the last three themes built and every theme that shares the paper / display / accent triple with one of them.
* ``check`` answers whether a plan (axes, display face, accent hue) lands on a catalogue theme or a recent build.

The theme headers in ``themes.json`` are data taken from the hallmark theme library (MIT); the dealing logic is original. See NOTICE.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

GENRES = ("editorial", "modern-minimal", "atmospheric", "playful")
PAPER_BANDS = ("light", "mid", "dark")
DISPLAY_CLASSES = ("roman-serif", "high-contrast-serif", "slab-serif", "grotesk-sans", "grotesk-heavy", "geometric-sans", "rounded-sans",
                   "display-condensed", "display-heavy", "mono", "pixel", "handwritten", "blackletter")
_ACCENT_BAND = re.compile(r"^(warm|cool|neutral|chromatic-[a-z-]+)$")
MEMORY_DEPTH = 3

_SERIF = {"roman-serif", "high-contrast-serif", "slab-serif", "blackletter"}
_BODY_FOR = {"roman-serif": "Hanken Grotesk", "high-contrast-serif": "Manrope", "slab-serif": "Chivo", "grotesk-sans": "Newsreader",
             "grotesk-heavy": "Archivo", "geometric-sans": "Karla", "rounded-sans": "Figtree", "display-condensed": "Archivo",
             "display-heavy": "Golos Text", "mono": "IBM Plex Sans", "pixel": "Chivo", "handwritten": "Karla", "blackletter": "Hanken Grotesk"}
_STYLE_FOR = {"editorial": "sharp", "modern-minimal": "soft", "atmospheric": "soft", "playful": "pill"}
_DENSITY_FOR = {"editorial": "spacious", "atmospheric": "spacious", "modern-minimal": "comfortable", "playful": "comfortable"}

_ASK = {"build", "make", "create", "design", "need", "want", "please", "page", "site", "website", "landing", "called", "for", "and", "the", "with",
        "that", "this", "our", "your", "una", "para", "con", "que", "los", "las", "del", "sus", "web"}


@lru_cache(maxsize=1)
def load() -> tuple[dict, ...]:
    raw = json.loads((Path(__file__).with_name("themes.json")).read_text(encoding="utf-8"))
    names = raw["fields"]
    out = []
    for row in raw["themes"]:
        r = dict(zip(names, row))
        out.append({"slug": r["slug"], "name": r["name"], "genre": r["genre"], "posture": r["posture"],
                    "paper": {"band": r["paper_band"], "L": r["paper_L"], "hue": r["paper_hue"]},
                    "display": {"class": r["display_class"], "face": r["display_face"]},
                    "accent": {"band": r["accent_band"], "hue": r["accent_hue"]},
                    "keywords": [k.lower() for k in r["keywords"]], "material": r["material"]})
    return tuple(out)


def get(slug: str) -> Optional[dict]:
    return next((t for t in load() if t["slug"] == (slug or "").strip().lower()), None)


def triple(t: dict) -> str:
    return f"{t['paper']['band']}/{t['display']['class']}/{t['accent']['band']}"


def _words(text: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9áéíóúñü\s-]", " ", (text or "").lower()).split() if len(w) > 2]


def _stem(w: str) -> str:
    x = re.sub(r"(?:ing|ed)$", "", w)
    if len(x) < 3:
        x = w
    return x if x.endswith("ss") else re.sub(r"s$", "", x)


def _prompt_words(text: str) -> list[str]:
    return [w for w in _words(text) if w not in _ASK]


def seeded_rand(key: str) -> Callable[[], float]:
    """A deterministic stream of floats in [0, 1) from a string (sha256 chained)."""
    state = {"h": hashlib.sha256(key.encode("utf-8")).digest(), "i": 0}

    def rand() -> float:
        if state["i"] >= len(state["h"]) - 4:
            state["h"] = hashlib.sha256(state["h"]).digest()
            state["i"] = 0
        v = int.from_bytes(state["h"][state["i"]: state["i"] + 4], "big")
        state["i"] += 4
        return v / 0xFFFFFFFF
    return rand


def hue_gap(a: float, b: float) -> float:
    d = abs((a - b) % 360)
    return min(d, 360 - d)


def parse_seed(seed: str) -> tuple[str, int]:
    """``<base>·r<reroll>`` -> (base, reroll): the seed a deal printed gives that same deal back."""
    m = re.match(r"^(.*)·r(\d+)$", seed or "")
    return (m.group(1), int(m.group(2))) if m else (seed or "", 0)


def blocked_by(memory: Iterable[dict], themes: Optional[Iterable[dict]] = None) -> dict[str, str]:
    """slug -> why it cannot be dealt: one of the last three themes, or sharing the triple of one of them."""
    themes = list(themes or load())
    recent = list(memory)[:MEMORY_DEPTH]
    names = {str(r.get("slug") or "").lower() for r in recent} | {str(r.get("name") or "").lower() for r in recent}
    axes = {r.get("axes") for r in recent if r.get("axes")}
    out: dict[str, str] = {}
    for t in themes:
        if t["slug"] in names or t["name"].lower() in names:
            out[t["slug"]] = "one of the last three themes built"
        elif triple(t) in axes:
            out[t["slug"]] = f"shares the {triple(t)} triple with a recent build"
    return out


def _pick(pool: list[dict], n: int, exclude: set[str]) -> list[dict]:
    avail = [s for s in pool if s["t"]["slug"] not in exclude]
    picked: list[dict] = []
    if not avail:
        return picked
    picked.append(avail[0])

    def rest() -> list[dict]:
        return [s for s in avail if s not in picked]
    if n >= 2 and rest():
        best = rest()[0]
        other = next((s for s in rest() if s["t"]["paper"]["band"] != picked[0]["t"]["paper"]["band"] and s["fit"] >= best["fit"] - 2
                      and triple(s["t"]) != triple(picked[0]["t"])), None)
        picked.append(other or next((s for s in rest() if triple(s["t"]) != triple(picked[0]["t"])), None) or best)
    while len(picked) < n and rest():
        cand = next((s for s in rest() if all(triple(p["t"]) != triple(s["t"]) for p in picked)), None) or rest()[0]
        picked.append(cand)
    return picked


def deal(*, prompt: str = "", genre: Optional[str] = None, n: int = 3, reroll: int = 0, seed: Optional[str] = None, salt: str = "",
         today: Optional[str] = None, memory: Iterable[dict] = ()) -> dict[str, Any]:
    """A hand of ``n`` themes for a prompt, clear of the recent builds. Same arguments (or the printed ``seed``) -> same hand."""
    if genre and genre not in GENRES:
        raise ValueError(f"unknown genre {genre!r} (valid: {', '.join(GENRES)})")
    memory = list(memory)
    themes = list(load())
    if seed:
        base, seed_reroll = parse_seed(seed)
        reroll = reroll or seed_reroll
    else:
        words = _prompt_words(prompt)
        slug = "-".join(words[:4]) or "prompt"
        digest = hashlib.sha1((prompt or "").strip().lower().encode("utf-8")).hexdigest()[:4]
        base = f"{slug}-{digest}·{salt or 'nosalt'}·{today or time.strftime('%Y-%m-%d')}"
    seed_key = f"{base}·r{reroll}"
    rand = seeded_rand(base)
    block = blocked_by(memory, themes)
    occupied = {r.get("axes") for r in memory[:MEMORY_DEPTH] if r.get("axes")}
    bw = {_stem(w) for w in _prompt_words(prompt)}
    df: dict[str, int] = {}
    for t in themes:
        for k in set(t["keywords"]):
            df[k] = df.get(k, 0) + 1
    scored = []
    for t in themes:
        fit, hits = 0, []
        for k in t["keywords"]:
            kw = [_stem(w) for w in k.split()]
            if kw and all(w in bw for w in kw):
                d = df.get(k, 1)
                fit += 3 if d <= 2 else 2 if d <= 4 else 1
                hits.append(k)
        if genre:
            fit += 2 if t["genre"] == genre else -1
        scored.append({"t": t, "fit": fit, "hits": hits, "blocked": t["slug"] in block, "r": rand()})
    pool = sorted((s for s in scored if not s["blocked"]), key=lambda s: (-s["fit"], s["r"]))
    previously: set[str] = set()
    for _ in range(max(0, reroll)):
        for p in _pick(pool, n, previously):
            previously.add(p["t"]["slug"])
    picked = _pick(pool, n, previously)
    if not picked:
        raise LookupError(f"nothing left to deal at reroll {reroll}; use a lower reroll")
    out = []
    for s in picked:
        t = s["t"]
        out.append({**{k: t[k] for k in ("slug", "name", "genre", "posture", "material")}, "axes": triple(t), "paper": t["paper"], "display": t["display"],
                    "accent": t["accent"], "fit": s["fit"], "hits": s["hits"][:6],
                    "why": ("fits: " + ", ".join(s["hits"][:4])) if s["hits"] else ("genre fit" if genre and t["genre"] == genre else "adjacent genre")})
    return {"seed": seed_key, "genre": genre or "", "reroll": reroll, "deal": out,
            "blocked": [{"slug": k, "reason": v} for k, v in sorted(block.items())],
            "avoid": [{"theme": r.get("name") or r.get("slug"), "axes": r.get("axes") or ""} for r in memory[:MEMORY_DEPTH]],
            "memory_depth": MEMORY_DEPTH, "occupied_axes": sorted(a for a in occupied if a)}


def check(*, axes: Optional[str] = None, face: Optional[str] = None, hue: Optional[float] = None, memory: Iterable[dict] = ()) -> dict[str, Any]:
    """Does a plan land on a catalogue theme or a recent build? ``axes`` is ``paper/display/accent``."""
    if not axes and not face and hue is None:
        raise ValueError("check needs axes, face or hue")
    pb = dc = ab = ""
    if axes:
        parts = [p.strip() for p in axes.split("/")]
        if len(parts) != 3:
            raise ValueError("axes is paper/display/accent, for example light/roman-serif/warm")
        pb, dc, ab = parts
        if pb not in PAPER_BANDS:
            raise ValueError(f"unknown paper band {pb!r} (valid: {', '.join(PAPER_BANDS)})")
        if dc not in DISPLAY_CLASSES:
            raise ValueError(f"unknown display class {dc!r} (valid: {', '.join(DISPLAY_CLASSES)})")
        if not _ACCENT_BAND.match(ab):
            raise ValueError("unknown accent band (valid: warm, cool, neutral, chromatic-<hue name>)")
    themes = list(load())
    near, collisions, named = [], [], set()
    if axes:
        for t in themes:
            if (t["paper"]["band"], t["display"]["class"], t["accent"]["band"]) == (pb, dc, ab):
                near.append({"theme": t["name"], "slug": t["slug"], "axes": triple(t), "note": "sits on the same triple"})
                named.add(t["slug"])
    if face:
        want = [w for w in re.split(r"[\s-]+", face.lower().strip()) if w]
        for t in themes:
            have = [w for w in re.split(r"[\s-]+", t["display"]["face"].lower()) if w]
            k = min(len(want), len(have))
            if k and want[:k] == have[:k]:
                collisions.append({"theme": t["name"], "slug": t["slug"], "face": t["display"]["face"], "note": "already sets its display in this face"})
    if hue is not None:
        for t in themes:
            if t["slug"] in named:
                continue
            if axes:
                close = t["paper"]["band"] == pb and t["display"]["class"] == dc and hue_gap(t["accent"]["hue"], hue) <= 20
            else:
                close = hue_gap(t["accent"]["hue"], hue) <= 10
            if close:
                near.append({"theme": t["name"], "slug": t["slug"], "axes": triple(t), "note": f"accent at hue {t['accent']['hue']}"})
    recent = [{"theme": r.get("name") or r.get("slug"), "axes": r.get("axes"), "note": "used this triple in a recent build"}
              for r in list(memory)[:MEMORY_DEPTH] if axes and r.get("axes") == axes]
    return {"clear": not (near or collisions or recent), "near": near, "collisions": collisions, "recent": recent}


def as_brief(theme: dict) -> dict[str, Any]:
    """What a theme contributes to a ``tokens_generate`` brief: hue, fonts, radius/shadow style and density."""
    face = re.split(r"\s+and\s+", theme["display"]["face"])[0].strip()
    cls = theme["display"]["class"]
    fallback = "ui-serif, Georgia, serif" if cls in _SERIF else "ui-monospace, monospace" if cls in ("mono", "pixel") else "ui-sans-serif, system-ui, sans-serif"
    accent = theme["accent"]["hue"] if theme["accent"]["band"] != "neutral" else theme["paper"]["hue"]
    return {"hue": float(accent) % 360, "style": _STYLE_FOR.get(theme["genre"], "soft"), "density": _DENSITY_FOR.get(theme["genre"], "comfortable"),
            "fonts": {"heading": f"{face}, {fallback}", "body": f"{_BODY_FOR.get(cls, 'Karla')}, ui-sans-serif, system-ui, sans-serif"}}


def public(theme: dict) -> dict[str, Any]:
    return {**{k: theme[k] for k in ("slug", "name", "genre", "posture", "material", "keywords")}, "axes": triple(theme),
            "paper": theme["paper"], "display": theme["display"], "accent": theme["accent"]}
