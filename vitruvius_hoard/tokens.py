"""Pure-Python OKLCH colour maths and a full design-token generator.

No third-party dependency: sRGB <-> linear sRGB <-> OKLab <-> OKLCH,
gamut clamping by chroma reduction, WCAG contrast, ramps, type scale,
spacing, radius, shadows, motion tokens and four export formats plus a
self-contained playground HTML specimen.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

# ---------------------------------------------------------------------------
# sRGB <-> linear <-> OKLab <-> OKLCH  (Björn Ottosson's matrices)
# ---------------------------------------------------------------------------


def srgb_to_linear(c: float) -> float:
    c = min(1.0, max(0.0, c))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    c = min(1.0, max(0.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def linear_srgb_to_oklab(r: float, g: float, b: float) -> tuple[float, float, float]:
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = _cbrt(l), _cbrt(m), _cbrt(s)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b2 = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, a, b2


def oklab_to_linear_srgb(L: float, a: float, b: float) -> tuple[float, float, float]:
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    b2 = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return r, g, b2


def _cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1 / 3), x)


def rgb01_to_oklab(r: float, g: float, b: float) -> tuple[float, float, float]:
    return linear_srgb_to_oklab(srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b))


def oklab_to_rgb01(L: float, a: float, b: float) -> tuple[float, float, float]:
    r, g, b2 = oklab_to_linear_srgb(L, a, b)
    return linear_to_srgb(r), linear_to_srgb(g), linear_to_srgb(b2)


def oklab_to_oklch(L: float, a: float, b: float) -> tuple[float, float, float]:
    c = math.hypot(a, b)
    h = math.degrees(math.atan2(b, a))
    if h < 0:
        h += 360
    return L, c, h


def oklch_to_oklab(L: float, c: float, h: float) -> tuple[float, float, float]:
    rad = math.radians(h)
    return L, c * math.cos(rad), c * math.sin(rad)


def _in_gamut(r: float, g: float, b: float, eps: float = 1e-4) -> bool:
    return -eps <= r <= 1 + eps and -eps <= g <= 1 + eps and -eps <= b <= 1 + eps


def oklch_to_rgb01(L: float, c: float, h: float, *, clamp: bool = True) -> tuple[float, float, float]:
    """OKLCH -> sRGB [0,1], reducing chroma by binary search until in gamut."""
    L = min(1.0, max(0.0, L))
    lo, hi = 0.0, max(c, 1e-6)
    _, a, b = oklch_to_oklab(L, hi, h)
    r, g, b2 = oklab_to_rgb01(L, a, b)
    if _in_gamut(r, g, b2) or not clamp:
        return (min(1.0, max(0.0, r)), min(1.0, max(0.0, g)), min(1.0, max(0.0, b2)))
    for _ in range(24):
        mid = (lo + hi) / 2
        _, a, b = oklch_to_oklab(L, mid, h)
        r, g, b2 = oklab_to_rgb01(L, a, b)
        if _in_gamut(r, g, b2):
            lo = mid
        else:
            hi = mid
    _, a, b = oklch_to_oklab(L, lo, h)
    r, g, b2 = oklab_to_rgb01(L, a, b)
    return (min(1.0, max(0.0, r)), min(1.0, max(0.0, g)), min(1.0, max(0.0, b2)))


def rgb01_to_oklch(r: float, g: float, b: float) -> tuple[float, float, float]:
    return oklab_to_oklch(*rgb01_to_oklab(r, g, b))


# ---------------------------------------------------------------------------
# Hex helpers
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def parse_hex(value: str) -> tuple[float, float, float]:
    m = _HEX_RE.match((value or "").strip())
    if not m:
        raise ValueError(f"not a hex colour: {value!r}")
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return r, g, b


def to_hex(r: float, g: float, b: float) -> str:
    def byte(c: float) -> int:
        return max(0, min(255, round(c * 255)))

    return "#{:02x}{:02x}{:02x}".format(byte(r), byte(g), byte(b))


def oklch_to_hex(L: float, c: float, h: float) -> str:
    return to_hex(*oklch_to_rgb01(L, c, h))


def hex_to_oklch(value: str) -> tuple[float, float, float]:
    return rgb01_to_oklch(*parse_hex(value))


# ---------------------------------------------------------------------------
# WCAG contrast
# ---------------------------------------------------------------------------


def relative_luminance(hex_or_rgb) -> float:
    if isinstance(hex_or_rgb, str):
        r, g, b = parse_hex(hex_or_rgb)
    else:
        r, g, b = hex_or_rgb
    R, G, B = srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b)
    return 0.2126 * R + 0.7152 * G + 0.0722 * B


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la, lb = relative_luminance(hex_a), relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def best_on_color(bg_hex: str, candidates: tuple[str, str] = ("#ffffff", "#0a0a0f")) -> str:
    return max(candidates, key=lambda c: contrast_ratio(bg_hex, c))


def wcag_level(ratio: float, large: bool = False) -> str:
    if ratio >= (3.0 if large else 4.5):
        if ratio >= (4.5 if large else 7.0):
            return "AAA"
        return "AA"
    return "fail"


# ---------------------------------------------------------------------------
# Ramps
# ---------------------------------------------------------------------------

RAMP_STEPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]
_STEP_L = {
    50: 0.98, 100: 0.95, 200: 0.90, 300: 0.82, 400: 0.72, 500: 0.62,
    600: 0.52, 700: 0.42, 800: 0.32, 900: 0.24, 950: 0.16,
}
# Chroma multiplier per step (peaks around 400-600, tapers at the extremes).
_STEP_C_MULT = {
    50: 0.12, 100: 0.22, 200: 0.45, 300: 0.68, 400: 0.88, 500: 1.0,
    600: 0.96, 700: 0.86, 800: 0.72, 900: 0.55, 950: 0.38,
}


def make_ramp(hue: float, base_chroma: float, *, min_chroma: float = 0.0) -> dict[str, str]:
    """A 50..950 ramp at a fixed hue; chroma scaled per step, gamut-clamped."""
    out: dict[str, str] = {}
    for step in RAMP_STEPS:
        L = _STEP_L[step]
        c = max(min_chroma, base_chroma * _STEP_C_MULT[step])
        out[str(step)] = oklch_to_hex(L, c, hue)
    return out


def neutral_ramp(hue: float, chroma: float = 0.012) -> dict[str, str]:
    return make_ramp(hue, chroma, min_chroma=0.002)


# ---------------------------------------------------------------------------
# Brief / knobs
# ---------------------------------------------------------------------------

STYLE_RADIUS = {
    "sharp": {"sm": "2px", "md": "4px", "lg": "6px", "xl": "10px", "pill": "999px"},
    "soft": {"sm": "6px", "md": "10px", "lg": "16px", "xl": "24px", "pill": "999px"},
    "pill": {"sm": "10px", "md": "16px", "lg": "24px", "xl": "999px", "pill": "999px"},
}

STYLE_SHADOW = {
    "flat": {
        "sm": "none", "md": "none", "lg": "none",
    },
    "soft": {
        "sm": "0 1px 2px rgb(0 0 0 / 0.06)",
        "md": "0 4px 12px rgb(0 0 0 / 0.10)",
        "lg": "0 12px 32px rgb(0 0 0 / 0.16)",
    },
    "hard-offset": {
        "sm": "2px 2px 0 rgb(0 0 0 / 0.9)",
        "md": "4px 4px 0 rgb(0 0 0 / 0.9)",
        "lg": "8px 8px 0 rgb(0 0 0 / 0.9)",
    },
}

SPACING_SCALE = [0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24]  # multiples of 4px base

MOTION_EASINGS = {
    "standard": "cubic-bezier(0.2, 0, 0, 1)",
    "emphasized": "cubic-bezier(0.3, 0, 0.1, 1)",
    "decelerate": "cubic-bezier(0, 0, 0, 1)",
    "accelerate": "cubic-bezier(0.3, 0, 1, 1)",
    "spring": "cubic-bezier(0.5, 1.5, 0.5, 1)",
}

_SEMANTIC_HUES = {"success": 145.0, "warn": 85.0, "danger": 25.0, "info": 235.0}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def type_scale(ratio: float = 1.25, min_vw: int = 360, max_vw: int = 1440, steps: int | None = None) -> dict[str, str]:
    """Fluid type scale via CSS clamp(), base 1rem = 16px, min/max grow by ratio each step."""
    names = ["xs", "sm", "base", "lg", "xl", "2xl", "3xl", "4xl", "5xl"]
    base_index = names.index("base")
    out: dict[str, str] = {}
    for i, name in enumerate(names):
        power = i - base_index
        min_px = 16 * (ratio ** power) * 0.92 if power > 0 else 16 * (ratio ** power) * 0.98
        max_px = 16 * (ratio ** power)
        min_px = max(10.0, min_px)
        max_rem = max_px / 16
        min_rem = min_px / 16
        slope = (max_rem - min_rem) / ((max_vw - min_vw) / 16)
        intercept = min_rem - slope * (min_vw / 16)
        out[name] = f"clamp({min_rem:.4f}rem, {intercept:.4f}rem + {slope * 100:.4f}vw, {max_rem:.4f}rem)"
    return out


def generate(brief: dict[str, Any]) -> dict[str, Any]:
    """Build the full token set from a brief dict.

    Keys (all optional): name, base_color (hex) or hue (0-360), style
    (sharp|soft|pill for radius; flat|soft|hard-offset for shadow),
    density (compact|comfortable|spacious), motion_intensity (1-10),
    fonts {heading, body, mono}.
    """
    name = brief.get("name") or "untitled"
    if brief.get("base_color"):
        base_L, base_c, base_h = hex_to_oklch(brief["base_color"])
        base_c = max(base_c, 0.10)
    else:
        base_h = float(brief.get("hue", 250.0)) % 360
        base_c = 0.16
        base_L = 0.62

    style = brief.get("style") or "soft"
    radius_key = style if style in STYLE_RADIUS else "soft"
    shadow_key = style if style in STYLE_SHADOW else "soft"

    density = brief.get("density") or "comfortable"
    density_mult = {"compact": 0.8, "comfortable": 1.0, "spacious": 1.25}.get(density, 1.0)
    ratio = {"compact": 1.2, "comfortable": 1.25, "spacious": 1.333}.get(density, 1.25)

    motion_intensity = _clamp(float(brief.get("motion_intensity", 5)), 1, 10)
    motion_scale = 0.6 + (motion_intensity / 10.0) * 0.8  # 0.68..1.4
    travel_scale = 0.5 + (motion_intensity / 10.0) * 1.5  # 0.65..2.0

    primary = make_ramp(base_h, base_c)
    neutral = neutral_ramp(base_h)
    semantic = {k: make_ramp(h, 0.15) for k, h in _SEMANTIC_HUES.items()}

    surfaces = {
        "light": {"bg": neutral["50"], "surface": "#ffffff", "surface-2": neutral["100"], "border": neutral["200"]},
        "dark": {"bg": oklch_to_hex(0.16, 0.02, base_h), "surface": oklch_to_hex(0.20, 0.02, base_h),
                 "surface-2": oklch_to_hex(0.25, 0.02, base_h), "border": oklch_to_hex(0.32, 0.02, base_h)},
    }
    on_colors = {
        "light": {"on-bg": best_on_color(surfaces["light"]["bg"]), "on-surface": best_on_color(surfaces["light"]["surface"]),
                  "on-primary": best_on_color(primary["500"])},
        "dark": {"on-bg": best_on_color(surfaces["dark"]["bg"]), "on-surface": best_on_color(surfaces["dark"]["surface"]),
                 "on-primary": best_on_color(primary["500"])},
    }

    spacing = {str(v).replace(".", "_"): f"{v * 4 * density_mult:.2f}px" for v in SPACING_SCALE}

    fonts = brief.get("fonts") or {}
    typography = {
        "heading": fonts.get("heading") or "Fraunces, ui-serif, Georgia, serif",
        "body": fonts.get("body") or "Inter, ui-sans-serif, system-ui, sans-serif",
        "mono": fonts.get("mono") or "IBM Plex Mono, ui-monospace, monospace",
        "scale": type_scale(ratio=ratio),
    }

    motion = {
        "duration": {
            "fast": round(120 * motion_scale),
            "base": round(200 * motion_scale),
            "slow": round(320 * motion_scale),
            "enter": round(240 * motion_scale),
            "exit": round(160 * motion_scale),
        },
        "easing": dict(MOTION_EASINGS),
        "travel_px": round(16 * travel_scale),
        "intensity": motion_intensity,
    }

    tokens: dict[str, Any] = {
        "name": name,
        "hue": base_h,
        "color": {"primary": primary, "neutral": neutral, "semantic": semantic, "surfaces": surfaces, "on": on_colors},
        "typography": typography,
        "spacing": spacing,
        "radius": STYLE_RADIUS[radius_key],
        "shadow": STYLE_SHADOW[shadow_key],
        "motion": motion,
        "z_index": {"base": 0, "dropdown": 1000, "sticky": 1100, "overlay": 1200, "modal": 1300, "toast": 1400},
        "breakpoints": {"sm": "480px", "md": "768px", "lg": "1024px", "xl": "1280px", "2xl": "1536px"},
        "style": style,
        "density": density,
    }
    return tokens


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


def _flatten(prefix: list[str], value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(prefix + [str(k)], v, out)
    else:
        out["-".join(prefix)] = value


def to_flat(tokens: dict[str, Any]) -> dict[str, Any]:
    """Style-Dictionary-ish flat {token-path: value} JSON."""
    out: dict[str, Any] = {}
    for section in ("color", "typography", "spacing", "radius", "shadow", "motion", "z_index", "breakpoints"):
        if section in tokens:
            _flatten([section], tokens[section], out)
    return out


def _w3c_walk(value: Any, kind_hint: str = "") -> Any:
    if isinstance(value, dict):
        return {k: _w3c_walk(v, k) for k, v in value.items()}
    ttype = "color" if isinstance(value, str) and value.startswith("#") else (
        "dimension" if isinstance(value, str) and re.match(r"^-?[\d.]+(px|rem|em|%)", value) else
        "number" if isinstance(value, (int, float)) else "string")
    return {"$value": value, "$type": ttype}


def to_w3c(tokens: dict[str, Any]) -> dict[str, Any]:
    """W3C design tokens community group format ($value/$type), nested by group."""
    out: dict[str, Any] = {}
    for section in ("color", "typography", "spacing", "radius", "shadow", "motion", "z_index", "breakpoints"):
        if section in tokens:
            out[section] = _w3c_walk(tokens[section])
    out["name"] = {"$value": tokens.get("name", ""), "$type": "string"}
    return out


def _css_vars_for_theme(tokens: dict[str, Any], theme: str) -> list[str]:
    lines = []
    surf = tokens["color"]["surfaces"][theme]
    on = tokens["color"]["on"][theme]
    for k, v in surf.items():
        lines.append(f"  --color-{k}: {v};")
    for k, v in on.items():
        lines.append(f"  --color-{k}: {v};")
    return lines


def to_css(tokens: dict[str, Any]) -> str:
    lines = [":root {"]
    for ramp_name in ("primary", "neutral"):
        for step, hex_ in tokens["color"][ramp_name].items():
            lines.append(f"  --color-{ramp_name}-{step}: {hex_};")
    for sem_name, ramp in tokens["color"]["semantic"].items():
        for step, hex_ in ramp.items():
            lines.append(f"  --color-{sem_name}-{step}: {hex_};")
    lines.extend(_css_vars_for_theme(tokens, "light"))
    for name, value in tokens["spacing"].items():
        lines.append(f"  --space-{name}: {value};")
    for name, value in tokens["radius"].items():
        lines.append(f"  --radius-{name}: {value};")
    for name, value in tokens["shadow"].items():
        lines.append(f"  --shadow-{name}: {value};")
    lines.append(f"  --font-heading: {tokens['typography']['heading']};")
    lines.append(f"  --font-body: {tokens['typography']['body']};")
    lines.append(f"  --font-mono: {tokens['typography']['mono']};")
    for name, value in tokens["typography"]["scale"].items():
        lines.append(f"  --text-{name}: {value};")
    for name, value in tokens["motion"]["duration"].items():
        lines.append(f"  --duration-{name}: {value}ms;")
    for name, value in tokens["motion"]["easing"].items():
        lines.append(f"  --ease-{name}: {value};")
    lines.append(f"  --motion-travel: {tokens['motion']['travel_px']}px;")
    for name, value in tokens["breakpoints"].items():
        lines.append(f"  --breakpoint-{name}: {value};")
    lines.append("}")
    lines.append("")
    lines.append('[data-theme="dark"] {')
    lines.extend(_css_vars_for_theme(tokens, "dark"))
    lines.append("}")
    lines.append("")
    lines.append("@media (prefers-color-scheme: dark) {")
    lines.append('  :root:not([data-theme="light"]) {')
    lines.extend("  " + l for l in _css_vars_for_theme(tokens, "dark"))
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_tailwind(tokens: dict[str, Any]) -> str:
    """Tailwind v4 `@theme` block referencing the same CSS variables."""
    lines = ["@theme {"]
    for ramp_name in ("primary", "neutral"):
        for step, hex_ in tokens["color"][ramp_name].items():
            lines.append(f"  --color-{ramp_name}-{step}: {hex_};")
    for sem_name, ramp in tokens["color"]["semantic"].items():
        for step, hex_ in ramp.items():
            lines.append(f"  --color-{sem_name}-{step}: {hex_};")
    for name, value in tokens["spacing"].items():
        lines.append(f"  --spacing-{name}: {value};")
    for name, value in tokens["radius"].items():
        lines.append(f"  --radius-{name}: {value};")
    for name, value in tokens["typography"]["scale"].items():
        lines.append(f"  --text-{name}: {value};")
    lines.append(f"  --font-heading: {tokens['typography']['heading']};")
    lines.append(f"  --font-body: {tokens['typography']['body']};")
    lines.append(f"  --font-mono: {tokens['typography']['mono']};")
    for name, value in tokens["motion"]["duration"].items():
        lines.append(f"  --duration-{name}: {value}ms;")
    lines.append("}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Playground HTML
# ---------------------------------------------------------------------------


def playground_html(tokens: dict[str, Any], dark: bool = False) -> str:
    css = to_css(tokens)
    theme_attr = ' data-theme="dark"' if dark else ""
    primary = tokens["color"]["primary"]
    neutral = tokens["color"]["neutral"]

    def swatch_row(ramp: dict[str, str], label: str) -> str:
        cells = []
        for step, hex_ in ramp.items():
            on = best_on_color(hex_)
            ratio = round(contrast_ratio(hex_, on), 2)
            cells.append(
                f'<div class="swatch" style="background:{hex_};color:{on}">'
                f'<span>{step}</span><span>{hex_}</span><span>{ratio}:1</span></div>'
            )
        return f'<div class="ramp"><h3>{label}</h3><div class="swatch-row">{"".join(cells)}</div></div>'

    type_rows = "".join(
        f'<div style="font-size:{v};font-family:var(--font-heading);line-height:1.15;margin:0 0 .35em"><span class="meta" style="display:inline-block;width:3.5em">{k}</span> The quick brown fox jumps over the lazy dog</div>'
        for k, v in tokens["typography"]["scale"].items()
    )
    typo = tokens.get("typography", {})
    fonts_line = f"Heading: {typo.get('heading', '')} · Body: {typo.get('body', '')} · Mono: {typo.get('mono', '')}"
    dur = tokens["motion"].get("duration", {})
    durations_line = f"{dur.get('fast', '')} / {dur.get('base', '')} / {dur.get('slow', '')} ms"

    html = f"""<!doctype html>
<html lang="en"{theme_attr}>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{tokens.get('name', 'design system')} — playground</title>
<style>
{css}
* {{ box-sizing: border-box; }}
html {{ color-scheme: light dark; }}
body {{
  margin: 0; background: var(--color-bg); color: var(--color-on-bg);
  font-family: var(--font-body); font-size: var(--text-base); line-height: 1.55;
  transition: background var(--duration-base) var(--ease-standard);
}}
.wrap {{ max-width: 1120px; margin: 0 auto; padding: var(--space-8) var(--space-6); }}
h1, h2, h3 {{ font-family: var(--font-heading); line-height: 1.1; margin: 0 0 var(--space-3); letter-spacing: -0.01em; }}
h1 {{ font-size: var(--text-5xl); }}
h2 {{ font-size: var(--text-2xl); margin-top: var(--space-12); }}
h3 {{ font-size: var(--text-xl); }}
p {{ max-width: 62ch; margin: 0 0 var(--space-4); }}
.eyebrow {{ font-family: var(--font-mono); font-size: var(--text-xs); letter-spacing: 0.12em; text-transform: uppercase; color: var(--color-primary-600); margin-bottom: var(--space-3); }}
.hero {{ display: grid; grid-template-columns: 1.2fr 0.8fr; gap: var(--space-10); align-items: center; padding: var(--space-12) 0 var(--space-8); border-bottom: 1px solid var(--color-border); }}
.hero .lede {{ font-size: var(--text-lg); color: var(--color-neutral-600); }}
.hero-art {{ aspect-ratio: 4 / 3; border-radius: var(--radius-xl); background: linear-gradient(135deg, var(--color-primary-200), var(--color-primary-600)); box-shadow: var(--shadow-lg); position: relative; overflow: hidden; }}
.hero-art::after {{ content: ""; position: absolute; inset: auto -20% -30% auto; width: 70%; height: 70%; border-radius: 50%; background: var(--color-primary-900); opacity: 0.35; }}
.meta {{ font-family: var(--font-mono); font-size: var(--text-sm); color: var(--color-neutral-600); }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: var(--space-6); }}
.row {{ display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: center; }}
.ramp .swatch-row {{ display: flex; flex-wrap: wrap; gap: 4px; }}
.swatch {{ width: 92px; height: 72px; border-radius: var(--radius-sm); padding: 6px; display: flex; flex-direction: column; justify-content: space-between; font-family: var(--font-mono); font-size: 11px; }}
.semantic {{ display: flex; gap: var(--space-3); flex-wrap: wrap; }}
.semantic span {{ padding: var(--space-2) var(--space-4); border-radius: var(--radius-pill); font-size: var(--text-sm); font-weight: 600; }}
button, .btn {{ font: inherit; font-family: var(--font-body); font-weight: 600; min-height: 44px; padding: 0 var(--space-5); border-radius: var(--radius-md); border: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-on-surface); cursor: pointer; display: inline-flex; align-items: center; gap: var(--space-2); transition: transform var(--duration-fast) var(--ease-standard), box-shadow var(--duration-fast) var(--ease-standard), background var(--duration-fast) var(--ease-standard); }}
button.primary {{ background: var(--color-primary-700); color: #fff; border-color: transparent; }}
button.ghost {{ background: transparent; border-color: transparent; color: var(--color-primary-700); }}
[data-theme="dark"] button.primary {{ background: var(--color-primary-300); color: var(--color-primary-950); }}
[data-theme="dark"] button.ghost, [data-theme="dark"] .eyebrow {{ color: var(--color-primary-300); }}
[data-theme="dark"] .hint, [data-theme="dark"] .meta, [data-theme="dark"] .hero .lede, [data-theme="dark"] th, [data-theme="dark"] footer {{ color: var(--color-neutral-300); }}
[data-theme="dark"] .error {{ color: var(--color-danger-300, #f2a19b); }}
[data-theme="dark"] .card .tag, [data-theme="dark"] nav a[aria-current] {{ background: var(--color-primary-900); color: var(--color-primary-100); }}
[data-theme="dark"] .toast {{ background: var(--color-neutral-100); color: var(--color-neutral-900); }}
[data-theme="dark"] .semantic span {{ filter: none; }}
button:hover {{ transform: translateY(-1px); box-shadow: var(--shadow-sm); }}
button:active {{ transform: translateY(0); }}
button:disabled {{ opacity: 0.5; cursor: not-allowed; transform: none; box-shadow: none; }}
button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible {{ outline: 2px solid var(--color-primary-500); outline-offset: 2px; }}
label {{ display: grid; gap: var(--space-1); font-size: var(--text-sm); font-weight: 600; }}
input, select {{ font: inherit; min-height: 44px; padding: 0 var(--space-3); border-radius: var(--radius-sm); border: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-on-surface); }}
input::placeholder {{ color: var(--color-neutral-500); }}
.hint {{ font-size: var(--text-sm); color: var(--color-neutral-600); font-weight: 400; }}
.error {{ color: var(--color-danger-700, #b3261e); }}
.card {{ background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: var(--space-6); box-shadow: var(--shadow-md); display: grid; gap: var(--space-3); align-content: start; }}
.card .tag {{ justify-self: start; font-family: var(--font-mono); font-size: var(--text-xs); padding: 2px var(--space-2); border-radius: var(--radius-sm); background: var(--color-primary-100); color: var(--color-primary-800); }}
table {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }}
th, td {{ border-bottom: 1px solid var(--color-border); padding: var(--space-3) var(--space-3); text-align: left; }}
th {{ font-size: var(--text-sm); color: var(--color-neutral-600); font-weight: 600; }}
td.num {{ text-align: right; font-family: var(--font-mono); }}
.toast {{ display: inline-flex; align-items: center; gap: var(--space-3); background: var(--color-neutral-900); color: var(--color-neutral-50); padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); box-shadow: var(--shadow-md); }}
.modal-backdrop {{ background: rgb(0 0 0 / 0.45); padding: var(--space-8); border-radius: var(--radius-lg); display: grid; place-items: center; }}
.modal {{ background: var(--color-surface); color: var(--color-on-surface); border-radius: var(--radius-lg); padding: var(--space-6); max-width: 380px; box-shadow: var(--shadow-lg); display: grid; gap: var(--space-4); }}
nav {{ display: flex; gap: var(--space-2); padding: var(--space-2); background: var(--color-surface); border-radius: var(--radius-md); border: 1px solid var(--color-border); }}
nav a {{ color: var(--color-on-surface); text-decoration: none; min-height: 44px; display: inline-flex; align-items: center; padding: 0 var(--space-4); border-radius: var(--radius-sm); }}
nav a[aria-current] {{ background: var(--color-primary-100); color: var(--color-primary-800); }}
nav a:hover {{ background: var(--color-surface-2); }}
.spacing {{ display: grid; gap: var(--space-2); }}
.spacing div {{ height: 10px; background: var(--color-primary-400); border-radius: 2px; }}
.radii {{ display: flex; gap: var(--space-4); flex-wrap: wrap; }}
.radii div {{ width: 72px; height: 72px; background: var(--color-surface); border: 1px solid var(--color-border); display: grid; place-items: center; font-family: var(--font-mono); font-size: var(--text-xs); }}
.shadows {{ display: flex; gap: var(--space-6); flex-wrap: wrap; }}
.shadows div {{ width: 120px; height: 72px; background: var(--color-surface); border-radius: var(--radius-md); display: grid; place-items: center; font-family: var(--font-mono); font-size: var(--text-xs); }}
.reveal {{ opacity: 0; transform: translateY(var(--motion-travel)); animation: reveal var(--duration-slow) var(--ease-decelerate) forwards; }}
.reveal:nth-child(2) {{ animation-delay: 80ms; }}
.reveal:nth-child(3) {{ animation-delay: 160ms; }}
@keyframes reveal {{ to {{ opacity: 1; transform: translateY(0); }} }}
.drawer {{ background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: var(--space-4); width: 240px; transition: transform var(--duration-base) var(--ease-emphasized); }}
.drawer:hover {{ transform: translateX(var(--space-2)); }}
footer {{ margin-top: var(--space-16); padding-top: var(--space-6); border-top: 1px solid var(--color-border); color: var(--color-neutral-600); font-size: var(--text-sm); }}
@media (max-width: 760px) {{ .hero {{ grid-template-columns: 1fr; }} h1 {{ font-size: var(--text-4xl); }} .wrap {{ padding: var(--space-6) var(--space-4); }} }}
@media (prefers-reduced-motion: reduce) {{
  * {{ animation-duration: 0.001ms !important; animation-iteration-count: 1 !important; transition-duration: 0.001ms !important; }}
  .reveal {{ opacity: 1; transform: none; }}
}}
</style>
</head>
<body>
<div class="wrap">
<header class="hero">
  <div>
    <div class="eyebrow">Design system · {tokens.get('style')} · {tokens.get('density')}</div>
    <h1>{tokens.get('name', 'design system')}</h1>
    <p class="lede">Every surface on this page is drawn only from the tokens: the primary ramp, a tinted neutral scale, one type scale, a spacing grid and a motion register of {tokens['motion']['intensity']}/10.</p>
    <div class="row"><button class="primary">Primary action</button><button>Secondary</button><button class="ghost">Learn more →</button></div>
  </div>
  <div class="hero-art" role="img" aria-label="Gradient built from the primary ramp"></div>
</header>

<section id="colors" class="ramp">
<h2>Colour</h2>
<p class="meta">Contrast against white/black is printed on every step; 500 is the brand, 600 the interactive colour on light surfaces, 300 on dark ones.</p>
{swatch_row(primary, 'Primary')}
{swatch_row(neutral, 'Neutral')}
<h3>Semantic</h3>
<div class="semantic">
  <span style="background: var(--color-success-100, #e3f6e8); color: var(--color-success-800, #14532d)">Success</span>
  <span style="background: var(--color-warn-100, #fff4d6); color: var(--color-warn-800, #713f12)">Warning</span>
  <span style="background: var(--color-danger-100, #ffe1de); color: var(--color-danger-800, #7f1d1d)">Danger</span>
  <span style="background: var(--color-info-100, #dfeeff); color: var(--color-info-800, #1e3a8a)">Info</span>
</div>
</section>

<section id="type">
<h2>Type scale</h2>
<p class="meta">{fonts_line}</p>
{type_rows}
</section>

<section id="space">
<h2>Spacing, radius, elevation</h2>
<div class="grid">
  <div><h3>Spacing</h3><div class="spacing"><div style="width: var(--space-2)"></div><div style="width: var(--space-4)"></div><div style="width: var(--space-6)"></div><div style="width: var(--space-8)"></div><div style="width: var(--space-12)"></div><div style="width: var(--space-16)"></div></div></div>
  <div><h3>Radius</h3><div class="radii"><div style="border-radius: var(--radius-sm)">sm</div><div style="border-radius: var(--radius-md)">md</div><div style="border-radius: var(--radius-lg)">lg</div><div style="border-radius: var(--radius-pill)">pill</div></div></div>
  <div><h3>Elevation</h3><div class="shadows"><div style="box-shadow: var(--shadow-sm)">sm</div><div style="box-shadow: var(--shadow-md)">md</div><div style="box-shadow: var(--shadow-lg)">lg</div></div></div>
</div>
</section>

<section id="components">
<h2>Components</h2>
<div class="grid">
  <div class="card"><span class="tag">Card</span><h3>Quarterly summary</h3><p>Body copy sits on the surface colour with the neutral ramp for hierarchy. Cards carry one elevation step.</p><div class="row"><button class="primary">Open</button><button class="ghost">Dismiss</button></div></div>
  <div class="card"><span class="tag">Form</span><label>Name <input type="text" placeholder="Ada Lovelace" /></label><label>Plan <select><option>Starter</option><option>Studio</option></select></label><label>Email <input type="email" value="not-an-email" aria-invalid="true" /><span class="hint error">Enter a valid address.</span></label><button class="primary">Save changes</button></div>
  <div class="card"><span class="tag">Table</span><table><thead><tr><th>Metric</th><th class="num">Value</th></tr></thead><tbody><tr><td>Score</td><td class="num">8.4</td></tr><tr><td>Findings</td><td class="num">3</td></tr><tr><td>Renders</td><td class="num">12</td></tr></tbody></table></div>
</div>
<h3 style="margin-top: var(--space-8)">Navigation, toast, modal</h3>
<div class="row" style="align-items: flex-start; gap: var(--space-6)">
  <nav aria-label="Example"><a href="#" aria-current="page">Home</a><a href="#">Library</a><a href="#">Settings</a></nav>
  <div class="toast"><span aria-hidden="true">●</span> Saved.</div>
</div>
<div class="modal-backdrop" style="margin-top: var(--space-6)"><div class="modal" role="dialog" aria-labelledby="mt"><h3 id="mt">Delete this render?</h3><p>The screenshots are removed from disk. This cannot be undone.</p><div class="row"><button class="primary">Delete</button><button>Cancel</button></div></div></div>
</section>

<section id="motion">
<h2>Motion</h2>
<p class="meta">Durations {durations_line} · staggered reveal · hover lift · drawer slide (hover). Everything collapses under prefers-reduced-motion.</p>
<div class="grid">
  <div class="card reveal">Item one</div>
  <div class="card reveal">Item two</div>
  <div class="card reveal">Item three</div>
</div>
<div class="drawer" style="margin-top: var(--space-6)">Drawer content</div>
</section>

<footer>Generated by the design-system generator · tokens exported as CSS variables, Tailwind theme and W3C JSON.</footer>
</div>
</body>
</html>
"""
    return html


__all__ = [
    "srgb_to_linear", "linear_to_srgb", "linear_srgb_to_oklab", "oklab_to_linear_srgb",
    "rgb01_to_oklab", "oklab_to_rgb01", "oklab_to_oklch", "oklch_to_oklab",
    "oklch_to_rgb01", "rgb01_to_oklch", "parse_hex", "to_hex", "oklch_to_hex", "hex_to_oklch",
    "relative_luminance", "contrast_ratio", "best_on_color", "wcag_level",
    "make_ramp", "neutral_ramp", "type_scale", "generate",
    "to_flat", "to_w3c", "to_css", "to_tailwind", "playground_html",
]
