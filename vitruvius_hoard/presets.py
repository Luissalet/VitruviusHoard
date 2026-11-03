"""Design presets: complete token sets (colours light and dark, radius, fonts, spacing, motion, character) to pick and apply.

Three sources, one shape:

* ``vitruvius`` - the presets authored in ``presets.json``;
* ``hallmark``  - one preset per theme of the hallmark theme library (``themes.json``, MIT; see NOTICE), its paper, accent and
  display face turned into full colour roles here;
* ``hoard``     - the Hoard family palettes, read from the shared ``hoard-theme.css`` (dark as published, light derived).

Colour roles follow the shadcn/ui theme variables (background, foreground, card, primary, muted, accent, border, ring...),
and ``registry_item`` serves a preset as a shadcn ``registry-item.json`` (the registry schema is MIT). ``pick`` deals three
candidates for a brief (the family model ranks them when it answers, keywords otherwise) and ``apply`` writes the colour,
radius or type part of a preset into a Vitruvius design system.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from . import themes as themes_mod
from .tokens import best_on_color, contrast_ratio, hex_to_oklch, oklch_to_hex

HERE = Path(__file__).resolve().parent
PARTS = ("colors", "radius", "type", "spacing", "motion")
EASE = "cubic-bezier(0.2, 0, 0, 1)"
_SERIF_HINT = re.compile(r"serif|garamond|caslon|vollkorn|literata|newsreader|lora|gloock|cormorant|young serif|prata|bodoni|cinzel", re.I)


def _fallback(face: str, kind: str) -> str:
    if kind == "mono":
        return f"'{face}', ui-monospace, SFMono-Regular, Menlo, monospace"
    if _SERIF_HINT.search(face) and "sans" not in face.lower():
        return f"'{face}', ui-serif, Georgia, serif"
    return f"'{face}', ui-sans-serif, system-ui, sans-serif"


def _ok(L: float, C: float, H: float) -> dict[str, Any]:
    return {"hex": oklch_to_hex(L, C, H), "oklch": f"oklch({L:.3f} {C:.3f} {H % 360:.1f})"}


def roles(paper_hue: float, paper_L: float, dark_L: float, accent_hue: float, accent_chroma: float, *, neutral_chroma: float = 0.012) -> dict[str, dict]:
    """shadcn-style colour roles for light and dark, computed in OKLCH."""
    nc, ph, ah, ac = neutral_chroma, paper_hue, accent_hue, accent_chroma
    out: dict[str, dict] = {}
    for mode in ("light", "dark"):
        if mode == "light":
            bg = max(0.9, min(0.995, paper_L))
            spec = {"background": (bg, nc, ph), "foreground": (0.22, nc * 1.6, ph), "card": (min(1.0, bg + 0.018), nc * 0.7, ph),
                    "popover": (min(1.0, bg + 0.018), nc * 0.7, ph), "muted": (bg - 0.045, nc, ph), "muted-foreground": (0.47, nc * 1.4, ph),
                    "secondary": (bg - 0.06, nc * 1.5, ph), "accent": (bg - 0.05, max(0.02, ac * 0.25), ah),
                    "border": (bg - 0.11, nc, ph), "input": (bg - 0.13, nc, ph), "primary": (0.52, ac, ah), "destructive": (0.55, 0.19, 27)}
        else:
            bg = max(0.11, min(0.32, dark_L))
            spec = {"background": (bg, nc * 1.2, ph), "foreground": (0.95, nc * 0.8, ph), "card": (bg + 0.035, nc * 1.2, ph),
                    "popover": (bg + 0.035, nc * 1.2, ph), "muted": (bg + 0.07, nc, ph), "muted-foreground": (0.74, nc, ph),
                    "secondary": (bg + 0.09, nc * 1.3, ph), "accent": (bg + 0.08, max(0.02, ac * 0.3), ah),
                    "border": (bg + 0.13, nc, ph), "input": (bg + 0.15, nc, ph), "primary": (0.74, ac, ah), "destructive": (0.64, 0.19, 25)}
        m = {k: _ok(*v) for k, v in spec.items()}
        for k in ("card", "popover", "secondary", "accent"):
            m[f"{k}-foreground"] = m["foreground"]
        m["primary-foreground"] = _ok(*hex_to_oklch(best_on_color(m["primary"]["hex"])))
        m["destructive-foreground"] = _ok(*hex_to_oklch(best_on_color(m["destructive"]["hex"])))
        m["ring"] = m["primary"]
        out[mode] = m
    return out


_RADIUS_STEPS = (0.5, 1.0, 1.6, 2.4)


def radius_scale(base: float) -> dict[str, str]:
    base = max(0.0, float(base))
    sm, md, lg, xl = (round(base * k) for k in _RADIUS_STEPS)
    return {"base": f"{base:g}px", "sm": f"{sm}px", "md": f"{md}px", "lg": f"{lg}px", "xl": f"{xl}px", "pill": "999px"}


_DENSITY = {"compact": 0.85, "comfortable": 1.0, "spacious": 1.2}


def build(*, name: str, title: str, source: str, genre: str, character: str, keywords: list[str], paper_hue: float, paper_L: float,
          dark_L: float, accent_hue: float, accent_chroma: float, radius: float, heading: str, body: str, mono: str,
          density: str = "comfortable", duration: int = 180, dark_first: bool = False, colors: Optional[dict] = None,
          extra: Optional[dict] = None) -> dict[str, Any]:
    cols = colors or roles(paper_hue, paper_L, dark_L, accent_hue, accent_chroma)
    mult = _DENSITY.get(density, 1.0)
    preset = {
        "name": name, "title": title, "source": source, "genre": genre, "character": character, "keywords": [k.lower() for k in keywords],
        "dark_first": bool(dark_first),
        "tokens": {
            "colors": {mode: {k: v["hex"] for k, v in m.items()} for mode, m in cols.items()},
            "radius": radius_scale(radius),
            "fonts": {"heading": _fallback(heading, "sans"), "body": _fallback(body, "sans"), "mono": _fallback(mono, "mono"),
                      "families": {"heading": heading, "body": body, "mono": mono}},
            "spacing": {"base": "4px", "density": density, "scale": [f"{round(4 * k * mult)}px" for k in (1, 2, 3, 4, 6, 8, 12, 16)]},
            "motion": {"duration_ms": {"fast": round(duration * 0.6), "base": duration, "slow": round(duration * 1.6)}, "easing": EASE},
        },
        "oklch": {mode: {k: v["oklch"] for k, v in m.items()} for mode, m in cols.items()},
        "hue": {"paper": paper_hue % 360, "accent": accent_hue % 360},
    }
    light, dark = preset["tokens"]["colors"]["light"], preset["tokens"]["colors"]["dark"]
    preset["contrast"] = {"light_text": round(contrast_ratio(light["foreground"], light["background"]), 2),
                          "dark_text": round(contrast_ratio(dark["foreground"], dark["background"]), 2),
                          "light_primary": round(contrast_ratio(light["primary-foreground"], light["primary"]), 2),
                          "dark_primary": round(contrast_ratio(dark["primary-foreground"], dark["primary"]), 2)}
    if extra:
        preset.update(extra)
    return preset


def _authored() -> list[dict]:
    raw = json.loads((HERE / "presets.json").read_text(encoding="utf-8"))
    out = []
    for row in raw["presets"]:
        r = dict(zip(raw["fields"], row))
        out.append(build(source="vitruvius", **r))
    return out


def _hallmark() -> list[dict]:
    out = []
    for t in themes_mod.load():
        cls, face = t["display"]["class"], re.split(r"\s+and\s+", t["display"]["face"])[0].strip()
        pL = t["paper"]["L"] / 100.0
        accent = t["accent"]["hue"] if t["accent"]["band"] != "neutral" else t["paper"]["hue"]
        chroma = 0.04 if t["accent"]["band"] == "neutral" else 0.15
        radius = {"editorial": 0, "modern-minimal": 6, "atmospheric": 8, "playful": 12}.get(t["genre"], 6)
        out.append(build(name=f"hallmark-{t['slug']}", title=t["name"], source="hallmark", genre=t["genre"], character=t["material"],
                         keywords=t["keywords"], paper_hue=t["paper"]["hue"], paper_L=pL if pL > 0.85 else 0.97,
                         dark_L=pL if pL < 0.35 else 0.17, accent_hue=accent, accent_chroma=chroma, radius=radius, heading=face,
                         body=themes_mod._BODY_FOR.get(cls, "Karla"), mono="IBM Plex Mono",
                         density={"editorial": "spacious", "atmospheric": "spacious"}.get(t["genre"], "comfortable"),
                         dark_first=t["paper"]["band"] == "dark", extra={"theme": t["slug"], "axes": themes_mod.triple(t)}))
    return out


HOARD_CSS = HERE / "hoard_link" / "ui" / "hoard-theme.css"
_HOARD_MAP = {"background": "deep", "card": "surface", "popover": "elevated", "muted": "elevated", "secondary": "hover",
              "accent": "hover", "border": "border", "input": "border-hover", "foreground": "text", "muted-foreground": "text-muted",
              "primary": "accent", "primary-foreground": "accent-ink"}


def hoard_palettes(css_path: Path = HOARD_CSS) -> dict[str, dict[str, str]]:
    """{app id: {--hoard-* name without prefix: value}} for every ``html[data-hoard-app="..."]`` block of the shared theme."""
    try:
        css = css_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, dict[str, str]] = {}
    for m in re.finditer(r'html\[data-hoard-app="([\w-]+)"\]\s*\{([^}]*)\}', css):
        out[m.group(1)] = {k: v.strip() for k, v in re.findall(r"--hoard-([\w-]+)\s*:\s*([^;]+);", m.group(2))}
    return out


def _hoard() -> list[dict]:
    out = []
    for app, p in hoard_palettes().items():
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", p.get("accent", "")) or not p.get("deep"):
            continue
        dL, _, dh = hex_to_oklch(p["deep"])
        _, aC, aH = hex_to_oklch(p["accent"])
        cols = roles(dh, 0.975, dL, aH, max(0.08, min(0.18, aC)))
        dark = {}
        for role, var in _HOARD_MAP.items():
            v = p.get(var)
            dark[role] = {"hex": v.lower(), "oklch": _ok(*hex_to_oklch(v))["oklch"]} if v and v.startswith("#") else cols["dark"][role]
        for k in ("card", "popover", "secondary", "accent"):
            dark[f"{k}-foreground"] = dark["foreground"]
        dark["destructive"], dark["destructive-foreground"] = _ok(*hex_to_oklch("#c4463a")), _ok(*hex_to_oklch("#ffffff"))
        dark["ring"] = dark["primary"]
        cols["dark"] = dark
        out.append(build(name=f"hoard-{app}", title=f"Hoard {app.title()}", source="hoard", genre="atmospheric",
                         character=f"The {app} palette of the Hoard family: charcoal surfaces, Cinzel display, one accent ({p['accent']}).",
                         keywords=["hoard", app, "family", "dark", "charcoal"], paper_hue=dh, paper_L=0.975, dark_L=dL, accent_hue=aH,
                         accent_chroma=aC, radius=8, heading="Cinzel", body="Source Sans 3", mono="JetBrains Mono", density="comfortable",
                         duration=180, dark_first=True, colors=cols, extra={"app": app}))
    return out


@lru_cache(maxsize=1)
def catalogue() -> tuple[dict, ...]:
    seen, out = set(), []
    for p in [*_authored(), *_hoard(), *_hallmark()]:
        if p["name"] not in seen:
            seen.add(p["name"])
            out.append(p)
    return tuple(out)


def get(name: str) -> Optional[dict]:
    key = (name or "").strip().lower().removesuffix(".json")
    return next((p for p in catalogue() if p["name"] == key), None)


def summary(p: dict) -> dict[str, Any]:
    light, dark = p["tokens"]["colors"]["light"], p["tokens"]["colors"]["dark"]
    return {"name": p["name"], "title": p["title"], "source": p["source"], "genre": p["genre"], "character": p["character"],
            "dark_first": p["dark_first"], "keywords": p["keywords"][:8], "fonts": p["tokens"]["fonts"]["families"],
            "radius": p["tokens"]["radius"]["base"],
            "swatches": {"light": [light[k] for k in ("background", "card", "muted", "primary", "foreground")],
                         "dark": [dark[k] for k in ("background", "card", "muted", "primary", "foreground")]},
            "contrast": p["contrast"]}


def listing(*, source: Optional[str] = None, query: Optional[str] = None, limit: int = 200) -> list[dict]:
    q = (query or "").lower().strip()
    rows = []
    for p in catalogue():
        if source and p["source"] != source:
            continue
        if q and q not in " ".join([p["name"], p["title"], p["character"], *p["keywords"]]).lower():
            continue
        rows.append(summary(p))
    return rows[:limit]


# ---------------------------------------------------------------------------- shadcn registry shape

REGISTRY_ITEM_SCHEMA = "https://ui.shadcn.com/schema/registry-item.json"
REGISTRY_SCHEMA = "https://ui.shadcn.com/schema/registry.json"


def registry_item(p: dict) -> dict[str, Any]:
    fonts = p["tokens"]["fonts"]
    base_px = float(p["tokens"]["radius"]["base"].removesuffix("px") or 0)
    return {"$schema": REGISTRY_ITEM_SCHEMA, "name": p["name"], "type": "registry:theme", "title": p["title"], "description": p["character"],
            "cssVars": {"theme": {"font-sans": fonts["body"], "font-heading": fonts["heading"], "font-mono": fonts["mono"], "radius": f"{base_px / 16:g}rem"},
                        "light": dict(p["oklch"]["light"]), "dark": dict(p["oklch"]["dark"])},
            "meta": {"source": p["source"], "genre": p["genre"], "keywords": p["keywords"], "spacing": p["tokens"]["spacing"],
                     "motion": p["tokens"]["motion"], "hex": p["tokens"]["colors"], "dark_first": p["dark_first"]}}


def registry_index(homepage: str = "") -> dict[str, Any]:
    return {"$schema": REGISTRY_SCHEMA, "name": "vitruvius", "homepage": homepage,
            "items": [{"name": p["name"], "type": "registry:theme", "title": p["title"], "description": p["character"]} for p in catalogue()]}


# ---------------------------------------------------------------------------- picking three for a brief

def keyword_rank(brief: str) -> list[tuple[float, dict, list[str]]]:
    words = {themes_mod._stem(w) for w in themes_mod._prompt_words(brief)}
    ranked = []
    for p in catalogue():
        hits, score = [], 0.0
        for k in p["keywords"]:
            kw = [themes_mod._stem(w) for w in k.split()]
            if kw and all(w in words for w in kw):
                hits.append(k)
                score += 2.0 + (len(kw) - 1)
        score += 0.3 * len(words & {themes_mod._stem(w) for w in themes_mod._words(p["character"])})
        if p["source"] == "vitruvius":
            score += 0.2
        tie = int(hashlib.sha1((brief + p["name"]).encode("utf-8")).hexdigest()[:6], 16) / 0xFFFFFF
        ranked.append((score + tie * 0.01, p, hits))
    ranked.sort(key=lambda r: -r[0])
    return ranked


_PICK_SYSTEM = ("You choose design presets for a brief. You get the brief and a numbered list of candidate presets (name, character, "
                "keywords). Reply with exactly three lines, best first, each `name | why it fits this brief in one short sentence`. "
                "Use only names from the list. No other text.")


def pick(svc, brief: str, *, n: int = 3, use_model: bool = True, pool: int = 12) -> dict[str, Any]:
    brief = (brief or "").strip()
    if len(brief) < 3:
        raise ValueError("Describe what the design is for (a few words at least).")
    ranked = keyword_rank(brief)
    shortlist = ranked[:pool]
    by_name = {p["name"]: (s, p, h) for s, p, h in shortlist}
    chosen: list[tuple[str, str]] = []
    model, error = None, None
    link = getattr(svc, "link_sync", None) if svc is not None else None
    if use_model and link is not None:
        listing_text = "\n".join(f"{i + 1}. {p['name']}: {p['character']} [{', '.join(p['keywords'][:6])}]" for i, (_, p, _) in enumerate(shortlist))
        try:
            res = link.chat([{"role": "system", "content": _PICK_SYSTEM}, {"role": "user", "content": f"BRIEF\n{brief}\n\nCANDIDATES\n{listing_text}"}], effort="low")
            reply = getattr(res, "text", None) or (res.get("text") if isinstance(res, dict) else str(res))
            model = getattr(res, "model", None) or (res.get("model") if isinstance(res, dict) else None)
            for line in (reply or "").splitlines():
                m = re.match(r"^\W*(?:\d+[.)]\s*)?`?([a-z0-9-]+)`?\s*[|:\-]+\s*(.+)$", line.strip())
                if m and m.group(1) in by_name and m.group(1) not in {c for c, _ in chosen}:
                    chosen.append((m.group(1), m.group(2).strip()))
        except Exception as exc:  # noqa: BLE001 — keywords decide when the model does not answer
            error = f"{type(exc).__name__}: {exc}"[:200]
    from_model = len(chosen)
    for s, p, hits in shortlist:
        if len(chosen) >= n:
            break
        if p["name"] not in {c for c, _ in chosen}:
            chosen.append((p["name"], ("fits: " + ", ".join(hits[:4])) if hits else "closest character match"))
    out = []
    for name, why in chosen[:n]:
        s, p, hits = by_name[name]
        out.append({**summary(p), "why": why, "score": round(s, 2), "hits": hits[:6]})
    return {"brief": brief, "recommended": out[0]["name"] if out else None, "candidates": out,
            "source": "model" if from_model else "keywords", "model": model, "error": error}


# ---------------------------------------------------------------------------- applying a preset to a design system

def apply_parts(tokens: dict[str, Any], p: dict, parts: list[str]) -> dict[str, Any]:
    """Write the chosen parts of preset ``p`` into a Vitruvius token set (``tokens.generate`` shape). Pure."""
    from .tokens import SPACING_SCALE, make_ramp, neutral_ramp
    t = json.loads(json.dumps(tokens))
    pt = p["tokens"]
    if "colors" in parts:
        light, dark = pt["colors"]["light"], pt["colors"]["dark"]
        _, pc, ph = hex_to_oklch(light["primary"])
        t["hue"] = ph
        t.setdefault("color", {})
        t["color"]["primary"] = make_ramp(ph, max(0.05, pc))
        t["color"]["neutral"] = neutral_ramp(p["hue"]["paper"])
        t["color"]["surfaces"] = {mode: {"bg": c["background"], "surface": c["card"], "surface-2": c["muted"], "border": c["border"]}
                                  for mode, c in (("light", light), ("dark", dark))}
        t["color"]["on"] = {mode: {"on-bg": c["foreground"], "on-surface": c["card-foreground"], "on-primary": c["primary-foreground"]}
                            for mode, c in (("light", light), ("dark", dark))}
        t["color"]["roles"] = {"light": dict(light), "dark": dict(dark)}
    if "radius" in parts:
        t["radius"] = {k: v for k, v in pt["radius"].items() if k != "base"}
    if "type" in parts:
        t.setdefault("typography", {})
        for k in ("heading", "body", "mono"):
            t["typography"][k] = pt["fonts"][k]
    if "spacing" in parts:
        mult = _DENSITY.get(pt["spacing"]["density"], 1.0)
        t["spacing"] = {str(v).replace(".", "_"): f"{v * 4 * mult:.2f}px" for v in SPACING_SCALE}
        t["density"] = pt["spacing"]["density"]
    if "motion" in parts:
        d = pt["motion"]["duration_ms"]
        t.setdefault("motion", {"easing": {}, "travel_px": 16, "intensity": 5})
        t["motion"]["duration"] = {"fast": d["fast"], "base": d["base"], "slow": d["slow"], "enter": round(d["base"] * 1.2), "exit": round(d["base"] * 0.8)}
        t["motion"].setdefault("easing", {})["standard"] = pt["motion"]["easing"]
    t["preset"] = {"name": p["name"], "title": p["title"], "source": p["source"], "parts": list(parts), "ts": time.time()}
    return t


def apply(svc, name: str, *, tokens_id: Optional[str] = None, parts: Optional[list[str]] = None, title: Optional[str] = None) -> dict[str, Any]:
    from . import tokens as tokens_mod
    p = get(name)
    if p is None:
        raise LookupError(f"Unknown preset '{name}'; list them with design_preset_list.")
    parts = [x for x in (parts or ["colors", "radius", "type"]) if x]
    bad = [x for x in parts if x not in PARTS]
    if bad:
        raise ValueError(f"unknown part(s) {', '.join(bad)} (valid: {', '.join(PARTS)})")
    created = False
    if tokens_id:
        row = svc.tokens_get(tokens_id)
        if row is None:
            raise LookupError(f"Unknown design system '{tokens_id}'.")
    else:
        fam = p["tokens"]["fonts"]
        row = svc.tokens_generate({"name": title or p["title"], "hue": p["hue"]["accent"], "fonts": {k: fam[k] for k in ("heading", "body", "mono")},
                                   "density": p["tokens"]["spacing"]["density"]})
        tokens_id, created = row["id"], True
        parts = list(PARTS)
    tokens = apply_parts(row["tokens"], p, parts)
    svc.db.execute("UPDATE design_systems SET tokens = ?, css = ?, tailwind = ? WHERE id = ?",
                   (json.dumps(tokens), tokens_mod.to_css(tokens), tokens_mod.to_tailwind(tokens), tokens_id))
    try:
        svc._emit_event("vitruvius.tokens.preset_applied", {"id": tokens_id, "preset": p["name"], "parts": parts})
    except Exception:  # noqa: BLE001
        pass
    out = svc.tokens_get(tokens_id)
    return {"tokens_id": tokens_id, "created": created, "preset": summary(p), "parts": parts, "roles": out["roles"], "name": out["name"]}
