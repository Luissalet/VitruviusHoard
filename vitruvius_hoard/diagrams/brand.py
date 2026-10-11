"""Brand profiles for diagrams: read the colour roles of a website (rendered in the real browser) or of a folder of CSS/JSON
tokens, and keep them under a name so every later diagram can use them.

A site gives computed colours of its biggest elements and text/background pairs; the paper is the dominant background, the
ink the most common text colour on it, the accent the most chromatic colour that still reads on the paper. A folder gives
custom properties and token files: names with background/bg/paper, foreground/text/ink, primary/accent/brand, muted,
border. Missing roles fall back to the defaults, and the dark mode is derived from the light one when the brand has none.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from ..tokens import contrast_ratio, hex_to_oklch, oklch_to_hex, parse_hex, to_hex
from .render import DEFAULT, FONT_STACK, profile_from_colors

_RGB = re.compile(r"rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:[ ,/]+([\d.]+))?\s*\)")
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def css_to_hex(value: str) -> Optional[str]:
    value = (value or "").strip()
    m = _RGB.match(value)
    if m:
        alpha = float(m.group(4)) if m.group(4) is not None else 1.0
        if alpha < 0.5:
            return None
        return to_hex(*(float(m.group(i)) / 255 for i in (1, 2, 3)))
    m = _HEX.search(value)
    if m:
        return to_hex(*parse_hex(m.group(0)))
    return None


def _chroma(hex_value: str) -> float:
    return hex_to_oklch(hex_value)[1]


def _readable_on(color: str, paper: str, need: float) -> str:
    """Move a colour's lightness until it reaches ``need`` contrast on ``paper`` (hue and chroma kept)."""
    if contrast_ratio(color, paper) >= need:
        return color
    L, C, H = hex_to_oklch(color)
    dark_paper = contrast_ratio(paper, "#000000") < contrast_ratio(paper, "#ffffff")
    for _ in range(40):
        L = L + 0.02 if dark_paper else L - 0.02
        L = min(max(L, 0.0), 1.0)
        candidate = oklch_to_hex(L, C, H)
        if contrast_ratio(candidate, paper) >= need:
            return candidate
    return "#ffffff" if dark_paper else "#000000"


def roles_from_colors(paper: str, inks: list[str], others: list[str]) -> dict[str, Any]:
    ink = next((c for c in inks if contrast_ratio(c, paper) >= 4.5), None) or ("#111111" if contrast_ratio("#111111", paper) >= 4.5 else "#f5f5f5")
    # brand colours in the order the page uses them (text colours by amount of text, then backgrounds by area); the
    # accent is the first chromatic one that already reads on the paper, so it keeps the brand's own shade
    used = list(dict.fromkeys(c for c in inks + others if c not in (paper, ink)))
    accent = next((c for c in used if _chroma(c) > 0.06 and contrast_ratio(c, paper) >= 3.0), None)
    pool = sorted(used, key=_chroma, reverse=True)
    if not accent:
        accent = next((c for c in pool if _chroma(c) > 0.06), None)
        accent = _readable_on(accent, paper, 3.0) if accent else _readable_on(DEFAULT["light"]["accent"], paper, 3.0)
    pool = [c for c in used if contrast_ratio(c, paper) >= 3.0] + [c for c in pool if contrast_ratio(c, paper) < 3.0]
    muted = next((c for c in inks if c != ink and 4.5 <= contrast_ratio(c, paper) < contrast_ratio(ink, paper) and _chroma(c) < 0.05), None)
    if not muted:
        L, C, H = hex_to_oklch(ink)
        pL = hex_to_oklch(paper)[0]
        muted = _readable_on(oklch_to_hex(L + (pL - L) * 0.35, C, H), paper, 4.5)
    pL, pC, pH = hex_to_oklch(paper)
    surface = oklch_to_hex(pL - 0.035 if pL > 0.5 else pL + 0.05, pC, pH)
    border = _readable_on(oklch_to_hex(pL - 0.3 if pL > 0.5 else pL + 0.3, min(pC, 0.02), pH), paper, 3.0)
    series = [accent]
    for c in pool:
        if c != accent and _chroma(c) > 0.06 and contrast_ratio(c, paper) >= 3.0 and all(abs(hex_to_oklch(c)[2] - hex_to_oklch(s)[2]) > 25 for s in series):
            series.append(c)
        if len(series) == 4:
            break
    mode = "light" if pL > 0.5 else "dark"
    series += [s for s in DEFAULT[mode]["series"] if s not in series]
    return {"paper": paper, "ink": ink, "muted": muted, "accent": accent, "surface": surface, "border": border, "series": series[:6]}


def derive_other_mode(roles: dict[str, Any], mode: str) -> dict[str, Any]:
    """The opposite mode from one set of roles: default paper/ink/surface of that mode, brand accent and series made readable."""
    other = "dark" if mode == "light" else "light"
    base = dict(DEFAULT[other])
    paper = base["paper"]
    base["accent"] = _readable_on(roles["accent"], paper, 3.0)
    base["series"] = [_readable_on(s, paper, 3.0) for s in roles.get("series", [])][:6] or base["series"]
    return base


def from_probe(probe: dict[str, Any], name: str = "") -> dict[str, Any]:
    """Roles from the browser probe of a rendered page (``colors`` by area, ``contrast_pairs``, ``fonts``)."""
    backgrounds: dict[str, int] = {}
    for item in probe.get("colors") or []:
        bg = css_to_hex(item.get("background", ""))
        if bg:
            backgrounds[bg] = backgrounds.get(bg, 0) + int(item.get("count", 1))
    pairs = probe.get("contrast_pairs") or []
    # the paper is where the reading happens: the background under the most text, not the biggest coloured band
    under_text: dict[str, int] = {}
    for pr in pairs:
        bg = css_to_hex(pr.get("background", ""))
        if bg:
            under_text[bg] = under_text.get(bg, 0) + max(1, len(pr.get("text") or ""))
    votes = under_text or backgrounds
    paper = max(votes, key=votes.get) if votes else "#ffffff"
    texts: dict[str, int] = {}
    for pr in pairs:
        if css_to_hex(pr.get("background", "")) == paper:
            c = css_to_hex(pr.get("color", ""))
            if c:
                texts[c] = texts.get(c, 0) + len(pr.get("text") or "")
    inks = sorted(texts, key=texts.get, reverse=True)
    others = [c for c in backgrounds if c != paper]
    others += [c for c in (css_to_hex(pr.get("color", "")) for pr in pairs) if c and c not in others]
    roles = roles_from_colors(paper, inks, others)
    mode = "light" if hex_to_oklch(paper)[0] > 0.5 else "dark"
    font = ((probe.get("fonts") or {}).get("p") or (probe.get("fonts") or {}).get("h1") or "").strip() or FONT_STACK
    out = {"name": name or "brand", "font": font, mode: roles, "source": "site",
           "evidence": {"backgrounds_under_text": sorted(under_text.items(), key=lambda kv: -kv[1])[:4], "inks": inks[:4], "others": others[:6]}}
    out["dark" if mode == "light" else "light"] = derive_other_mode(roles, mode)
    return out


_VAR = re.compile(r"(--[\w-]+|\"[\w.-]+\"|[\w-]+)\s*:\s*\"?([^;\"\n,}]+)")
_ROLE_WORDS = [
    ("paper", ("background", "bg", "paper", "canvas", "base-100", "surface-0")),
    ("ink", ("foreground", "fg", "text", "ink", "content", "base-content", "on-bg", "body")),
    ("accent", ("primary", "accent", "brand", "main")),
    ("muted", ("muted", "secondary-text", "subtle", "gray", "grey")),
    ("border", ("border", "outline", "divider", "line")),
]


def from_folder(folder: str | Path, name: str = "") -> dict[str, Any]:
    root = Path(folder)
    if not root.is_dir():
        raise LookupError(f"Folder '{folder}' does not exist.")
    found: dict[str, list[str]] = {}
    dark_found: dict[str, list[str]] = {}
    files = [p for p in root.rglob("*") if p.suffix.lower() in (".css", ".scss", ".json", ".js", ".ts") and p.stat().st_size < 400_000
             and "node_modules" not in p.parts][:200]
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for block_dark, chunk in _blocks(text):
            for key, value in _VAR.findall(chunk):
                hex_value = css_to_hex(value)
                if not hex_value:
                    continue
                k = key.strip('"').lower()
                for role, words in _ROLE_WORDS:
                    if any(w in k for w in words):
                        (dark_found if block_dark else found).setdefault(role, []).append(hex_value)
                        break
    if not found:
        raise ValueError("no colour tokens found (looked for background, text, primary/accent, muted and border names)")
    light = found
    paper = (light.get("paper") or ["#ffffff"])[0]
    roles = roles_from_colors(paper, light.get("ink", []) + light.get("muted", []), light.get("accent", []) + light.get("border", []))
    if light.get("accent"):
        roles["accent"] = _readable_on(light["accent"][0], paper, 3.0)
        roles["series"][0] = roles["accent"]
    mode = "light" if hex_to_oklch(paper)[0] > 0.5 else "dark"
    out = {"name": name or root.name, "font": FONT_STACK, mode: roles, "source": "folder"}
    if dark_found.get("paper"):
        dpaper = dark_found["paper"][0]
        out["dark" if mode == "light" else "light"] = roles_from_colors(dpaper, dark_found.get("ink", []), dark_found.get("accent", []))
    else:
        out["dark" if mode == "light" else "light"] = derive_other_mode(roles, mode)
    return out


def _blocks(text: str):
    """(is_dark, text) pieces: CSS blocks under a dark selector or media query count as dark tokens."""
    dark = re.compile(r"(\.dark|\[data-theme=['\"]?dark|prefers-color-scheme:\s*dark|\"dark\"\s*:)", re.I)
    pos = 0
    for m in dark.finditer(text):
        yield False, text[pos:m.start()]
        depth, i = 0, text.find("{", m.end())
        if i < 0:
            pos = m.end()
            continue
        j = i
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield True, text[i:j + 1]
        pos = j + 1
    yield False, text[pos:]


class ProfileStore:
    """Named profiles as JSON files under ``<data>/diagrams/profiles``."""

    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir) / "diagrams" / "profiles"

    @staticmethod
    def _slug(name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40]
        if not slug:
            raise ValueError("a profile needs a name with letters or digits")
        return slug

    def save(self, name: str, profile: dict[str, Any]) -> dict[str, Any]:
        self.dir.mkdir(parents=True, exist_ok=True)
        slug = self._slug(name)
        full = profile_from_colors({**profile, "name": name}, base={"light": profile.get("light") or DEFAULT["light"],
                                                                     "dark": profile.get("dark") or DEFAULT["dark"],
                                                                     "font": profile.get("font")})
        full["source"] = profile.get("source", "")
        (self.dir / f"{slug}.json").write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"profile": slug, **full}

    def get(self, name: str) -> Optional[dict[str, Any]]:
        path = self.dir / f"{self._slug(name)}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def list(self) -> list[dict[str, Any]]:
        if not self.dir.exists():
            return []
        out = []
        for p in sorted(self.dir.glob("*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append({"profile": p.stem, "name": data.get("name", p.stem), "source": data.get("source", ""),
                        "accent": (data.get("light") or {}).get("accent"), "paper": (data.get("light") or {}).get("paper")})
        return out

    def delete(self, name: str) -> bool:
        path = self.dir / f"{self._slug(name)}.json"
        if path.exists():
            path.unlink()
            return True
        return False
