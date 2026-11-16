"""Ten texture recipes for designs that are not flat: each is working CSS driven by custom properties (its controls).

Original implementations. A recipe is a class ``tx-<id>`` plus the custom properties listed under ``controls``; set the
properties on the element (or let the sliders of the reference page do it). Noise and lines come from inline SVG filters in
data URIs, so nothing loads from the network and nothing needs a script. ``landscape`` also ships a seeded SVG builder.
"""
from __future__ import annotations

import random

_NS = "xmlns='http://www.w3.org/2000/svg'"


def _uri(svg: str) -> str:
    return 'url("data:image/svg+xml,' + svg.replace("#", "%23") + '")'


GRAIN = _uri(f"<svg {_NS} width='220' height='220'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/>"
             "<feColorMatrix values='0 0 0 0 .5  0 0 0 0 .5  0 0 0 0 .5  0 0 0 1.6 -.3'/></filter><rect width='100%' height='100%' filter='url(#n)'/></svg>")
SPECKS = _uri(f"<svg {_NS} width='260' height='260'><filter id='s'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' seed='4' stitchTiles='stitch'/>"
              "<feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  9 0 0 0 -6.1'/></filter><rect width='100%' height='100%' filter='url(#s)'/></svg>")
MOTTLE = _uri(f"<svg {_NS} width='400' height='400'><filter id='m'><feTurbulence type='fractalNoise' baseFrequency='.018' numOctaves='3' seed='9' stitchTiles='stitch'/>"
              "<feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  1.6 0 0 0 -.2'/></filter><rect width='100%' height='100%' filter='url(#m)'/></svg>")
WAVE = _uri(f"<svg {_NS} width='120' height='24' viewBox='0 0 120 24'><path d='M0 12 Q15 1 30 12 T60 12 T90 12 T120 12' fill='none' stroke='#0b0d10' stroke-width='1.6'/></svg>")
CONTOUR = _uri(f"<svg {_NS} width='640' height='640'><filter id='c' x='0' y='0' width='100%' height='100%'><feTurbulence type='fractalNoise' baseFrequency='.0065' numOctaves='2' seed='11' stitchTiles='stitch'/>"
               "<feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  1 0 0 0 0'/><feComponentTransfer><feFuncA type='table' tableValues='0 0 0 0 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 1 0 0 0'/></feComponentTransfer></filter>"
               "<rect width='100%' height='100%' filter='url(#c)'/></svg>")
BLADES = _uri(f"<svg {_NS} width='300' height='300'><filter id='b'><feTurbulence type='fractalNoise' baseFrequency='.03 .7' numOctaves='2' seed='3' stitchTiles='stitch'/>"
              "<feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 .8  7 0 0 0 -4.1'/></filter><rect width='100%' height='100%' filter='url(#b)'/></svg>")


def _c(key, label, low, high, step, default, unit=""):
    return {"key": key, "label": label, "min": low, "max": high, "step": step, "default": default, "unit": unit}


TEXTURES: list[dict] = [
    {"id": "thermal", "title": "Thermal gradient", "title_es": "Degradado térmico",
     "summary": "Blurred heat-map blooms (magenta, orange, yellow, cold blue) with film grain on top.",
     "summary_es": "Manchas de calor difuminadas (magenta, naranja, amarillo, azul frío) con grano de película encima.",
     "tags": ["gradient", "heat", "bloom", "hero", "degradado", "calor", "mapa", "fondo"], "controls": [
         _c("--tx-hue", "Tono", 0, 360, 1, 18), _c("--tx-spread", "Difuminado (px)", 20, 140, 1, 70), _c("--tx-grain", "Grano", 0, 0.6, 0.01, 0.2)],
     "css": ".tx-thermal{--tx-hue:18;--tx-spread:70;--tx-grain:.2;position:relative;isolation:isolate;overflow:hidden;background:#2a0f1c}\n"
            ".tx-thermal::before{content:\"\";position:absolute;inset:-25%;z-index:-2;background:"
            "radial-gradient(38% 48% at 18% 82%,hsl(calc(var(--tx-hue) - 22) 95% 52%),transparent 72%),"
            "radial-gradient(44% 54% at 78% 24%,hsl(var(--tx-hue) 100% 58%),transparent 72%),"
            "radial-gradient(52% 58% at 54% 62%,hsl(calc(var(--tx-hue) + 34) 100% 62%),transparent 74%),"
            "radial-gradient(55% 65% at 6% 6%,hsl(calc(var(--tx-hue) + 215) 90% 48%),transparent 72%);"
            "filter:blur(calc(var(--tx-spread) * 1px)) saturate(1.35)}\n"
            ".tx-thermal::after{content:\"\";position:absolute;inset:0;z-index:-1;pointer-events:none;background:" + GRAIN + ";opacity:var(--tx-grain);mix-blend-mode:overlay}",
     "use_when": "A hero or a closing section that needs warmth and depth without a photograph.",
     "avoid_when": "Behind long body text: the colour moves too much under it. Keep copy on a solid panel.",
     "why": "Adjacent hues blended wide read as light, not as a pasted gradient; the grain breaks the banding that smooth gradients show on large screens.",
     "accessibility": "Decorative. Check headline contrast at the brightest bloom; keep text on the darkest quadrant.", "guides": ["visually-texture-content", "color"]},
    {"id": "blueprint", "title": "Blueprint grid", "title_es": "Cuadrícula de plano",
     "summary": "Two-level drafting grid (minor cells, major every five) over an ink-blue ground with a soft vignette.",
     "summary_es": "Cuadrícula de dibujo a dos niveles (celda menor y mayor cada cinco) sobre azul tinta con viñeta suave.",
     "tags": ["grid", "technical", "architecture", "plan", "cuadricula", "plano", "tecnico", "arquitectura"], "controls": [
         _c("--tx-hue", "Tono", 190, 260, 1, 214), _c("--tx-cell", "Celda (px)", 8, 40, 1, 16), _c("--tx-line", "Línea", 0.05, 0.6, 0.01, 0.26)],
     "css": ".tx-blueprint{--tx-hue:214;--tx-cell:16;--tx-line:.26;background-color:hsl(var(--tx-hue) 68% 30%);background-image:"
            "linear-gradient(hsl(0 0% 100% / var(--tx-line)) 1px,transparent 1px),linear-gradient(90deg,hsl(0 0% 100% / var(--tx-line)) 1px,transparent 1px),"
            "linear-gradient(hsl(0 0% 100% / calc(var(--tx-line) * .38)) 1px,transparent 1px),linear-gradient(90deg,hsl(0 0% 100% / calc(var(--tx-line) * .38)) 1px,transparent 1px),"
            "radial-gradient(120% 95% at 50% 38%,transparent 38%,hsl(var(--tx-hue) 80% 10% / .6) 100%);"
            "background-size:calc(var(--tx-cell) * 5px) calc(var(--tx-cell) * 5px),calc(var(--tx-cell) * 5px) calc(var(--tx-cell) * 5px),calc(var(--tx-cell) * 1px) calc(var(--tx-cell) * 1px),calc(var(--tx-cell) * 1px) calc(var(--tx-cell) * 1px),100% 100%;"
            "background-position:-1px -1px,-1px -1px,-1px -1px,-1px -1px,0 0}",
     "use_when": "Architecture, engineering, tools and anything that is measured or drawn.",
     "avoid_when": "Consumer or emotional subjects: the grid reads as a technical document.",
     "why": "The hierarchy of two grid weights gives scale without a single object; the vignette keeps the eye in the middle.",
     "accessibility": "Keep the grid under 0.3 opacity so text over it stays readable.", "guides": ["visually-texture-content"]},
    {"id": "waves", "title": "Line waves", "title_es": "Ondas",
     "summary": "A tiled sine line in one ink, faded toward the bottom, for rhythm without imagery.",
     "summary_es": "Una línea sinusoidal en baldosa y de una sola tinta, desvanecida hacia abajo, para dar ritmo sin imagen.",
     "tags": ["wave", "line", "pattern", "rhythm", "ondas", "linea", "patron", "ritmo"], "controls": [
         _c("--tx-hue", "Tono", 0, 360, 1, 200), _c("--tx-wave", "Ancho de onda (px)", 40, 320, 1, 120), _c("--tx-gap", "Separación (px)", 8, 60, 1, 22)],
     "css": ".tx-waves{--tx-hue:200;--tx-wave:120;--tx-gap:22;position:relative;isolation:isolate;overflow:hidden;background:hsl(var(--tx-hue) 55% 93%)}\n"
            ".tx-waves::before{content:\"\";position:absolute;inset:0;z-index:-1;background:hsl(var(--tx-hue) 70% 36%);"
            "-webkit-mask:" + WAVE + " 0 0/calc(var(--tx-wave) * 1px) calc(var(--tx-gap) * 1px) repeat,linear-gradient(#0b0d10,transparent 92%);-webkit-mask-composite:source-in;"
            "mask:" + WAVE + " 0 0/calc(var(--tx-wave) * 1px) calc(var(--tx-gap) * 1px) repeat,linear-gradient(#0b0d10,transparent 92%);mask-composite:intersect}",
     "use_when": "Water, sound, audio and finance headers; any place a quiet repeating line gives rhythm.",
     "avoid_when": "Under dense tables or code, where the line competes with rows.",
     "why": "One repeated stroke gives texture with a single colour; the fade lets the content take the lower half.",
     "accessibility": "Decorative; the page does not rely on it to convey anything.", "guides": ["visually-texture-content"]},
    {"id": "graphite", "title": "Speckled graphite", "title_es": "Grafito moteado",
     "summary": "Dark matte stone: slow mottling plus sparse pale specks, like honed granite.",
     "summary_es": "Piedra mate oscura: moteado lento y puntos claros dispersos, como granito pulido.",
     "tags": ["stone", "dark", "granite", "matte", "grafito", "piedra", "oscuro", "granito"], "controls": [
         _c("--tx-tone", "Luminosidad (%)", 8, 40, 1, 17), _c("--tx-mottle", "Moteado", 0, 0.9, 0.01, 0.42), _c("--tx-speck", "Puntos", 0, 1, 0.01, 0.5)],
     "css": ".tx-graphite{--tx-tone:17;--tx-mottle:.42;--tx-speck:.5;position:relative;isolation:isolate;overflow:hidden;background:hsl(220 6% calc(var(--tx-tone) * 1%))}\n"
            ".tx-graphite::before{content:\"\";position:absolute;inset:0;z-index:-2;background:" + MOTTLE + ";background-size:400px;opacity:var(--tx-mottle);mix-blend-mode:screen}\n"
            ".tx-graphite::after{content:\"\";position:absolute;inset:0;z-index:-1;background:" + SPECKS + ";background-size:260px;opacity:var(--tx-speck)}",
     "use_when": "Premium hardware, tools, audio, anything that should feel like a dense material.",
     "avoid_when": "Light, friendly or children's content.",
     "why": "Two noise scales (slow mottle, sharp speck) are what makes stone read as stone; one scale reads as dirty screen.",
     "accessibility": "Pale specks stay under 0.5 opacity so they never cross text contrast.", "guides": ["visually-texture-content"]},
    {"id": "fluted", "title": "Fluted glass", "title_es": "Vidrio acanalado",
     "summary": "Vertical ribs that blur and brighten what sits behind a panel, like reeded glass.",
     "summary_es": "Nervios verticales que difuminan y aclaran lo que hay detrás de un panel, como vidrio acanalado.",
     "tags": ["glass", "blur", "ribs", "panel", "overlay", "vidrio", "acanalado", "cristal", "desenfoque"], "controls": [
         _c("--tx-rib", "Nervio (px)", 8, 60, 1, 22), _c("--tx-blur", "Desenfoque (px)", 0, 24, 1, 9), _c("--tx-shine", "Brillo", 0, 0.6, 0.01, 0.3)],
     "css": ".tx-fluted{--tx-rib:22;--tx-blur:9;--tx-shine:.3;position:relative;border-radius:18px;overflow:hidden;"
            "background:repeating-linear-gradient(90deg,hsl(0 0% 100% / var(--tx-shine)) 0,hsl(0 0% 100% / 0) calc(var(--tx-rib) * .34px),hsl(215 40% 10% / .2) calc(var(--tx-rib) * 1px));"
            "-webkit-backdrop-filter:blur(calc(var(--tx-blur) * 1px)) saturate(1.4);backdrop-filter:blur(calc(var(--tx-blur) * 1px)) saturate(1.4);"
            "box-shadow:inset 0 0 0 1px hsl(0 0% 100% / .35),0 24px 40px -18px hsl(220 50% 8% / .55)}",
     "use_when": "A panel, a card or a navigation bar over a colourful or photographic ground.",
     "avoid_when": "Over a plain colour: nothing is behind it to distort, so it looks like stripes.",
     "why": "A repeating gradient models the highlight and the groove of each rib; the blur makes the content behind it feel refracted. It approximates refraction, it does not displace pixels.",
     "accessibility": "Text on it needs the contrast of the darkest rib; keep it on a stable ground.", "guides": ["visually-texture-content", "visual-effects"]},
    {"id": "contour", "title": "Contour lines", "title_es": "Curvas de nivel",
     "summary": "Hairline elevation contours from fractal noise, in the ink colour you choose.",
     "summary_es": "Curvas de nivel finas a partir de ruido fractal, con la tinta que elijas.",
     "tags": ["topographic", "map", "lines", "terrain", "nivel", "mapa", "topografico", "terreno"], "controls": [
         _c("--tx-hue", "Tono", 0, 360, 1, 150), _c("--tx-scale", "Escala (px)", 320, 1400, 10, 640), _c("--tx-ink", "Tinta", 0.1, 1, 0.01, 0.5)],
     "css": ".tx-contour{--tx-hue:150;--tx-scale:640;--tx-ink:.5;position:relative;isolation:isolate;overflow:hidden;background:hsl(var(--tx-hue) 30% 94%)}\n"
            ".tx-contour::before{content:\"\";position:absolute;inset:0;z-index:-1;background:hsl(var(--tx-hue) 55% 24%);opacity:var(--tx-ink);"
            "-webkit-mask:" + CONTOUR + " 0 0/calc(var(--tx-scale) * 1px) repeat;mask:" + CONTOUR + " 0 0/calc(var(--tx-scale) * 1px) repeat}",
     "use_when": "Maps, outdoors, geology, land and travel; quiet backgrounds for editorial pages.",
     "avoid_when": "Interfaces that already carry lines (tables, charts).",
     "why": "A table function on noise turns slopes into thin evenly spaced bands: the structure of a real elevation map with no data.",
     "accessibility": "Keep ink below 0.6 under text.", "guides": ["visually-texture-content"]},
    {"id": "grain", "title": "Film grain", "title_es": "Grano",
     "summary": "A neutral noise overlay that removes the plastic look of flat colour and gradients.",
     "summary_es": "Una capa de ruido neutra que quita el aspecto de plástico del color plano y los degradados.",
     "tags": ["noise", "film", "overlay", "paper", "grano", "ruido", "papel", "pelicula"], "controls": [
         _c("--tx-grain", "Cantidad", 0, 0.6, 0.01, 0.16), _c("--tx-size", "Tamaño (px)", 80, 420, 1, 220)],
     "css": ".tx-grain{--tx-grain:.16;--tx-size:220;position:relative;isolation:isolate}\n"
            ".tx-grain::after{content:\"\";position:absolute;inset:0;z-index:1;pointer-events:none;background:" + GRAIN + ";background-size:calc(var(--tx-size) * 1px);opacity:var(--tx-grain);mix-blend-mode:overlay}",
     "use_when": "Over any large flat surface or gradient, to give it a printed or photographic feel.",
     "avoid_when": "Over small UI controls, where it makes edges look dirty.",
     "why": "Real surfaces are never perfectly even; a small amount of noise is the cheapest way to say so.",
     "accessibility": "Pointer events pass through; overlay blending does not change text colour tokens.", "guides": ["visually-texture-content"]},
    {"id": "landscape", "title": "Monochrome landscape", "title_es": "Paisaje monocolor",
     "summary": "Receding ridgelines in tints of one hue with haze between them; seeded, so it can be reproduced.",
     "summary_es": "Cordilleras que se alejan en tonos de un solo color con bruma entre ellas; con semilla, reproducible.",
     "tags": ["landscape", "mountains", "ridge", "layers", "depth", "paisaje", "montanas", "capas", "profundidad"], "controls": [
         _c("--tx-hue", "Tono", 0, 360, 1, 205), _c("--tx-haze", "Bruma", 0, 0.8, 0.01, 0.42)],
     "css": ".tx-landscape{--tx-hue:205;--tx-haze:.42;position:relative;isolation:isolate;overflow:hidden;background:linear-gradient(hsl(var(--tx-hue) 55% 84%),hsl(var(--tx-hue) 45% 95%) 70%)}\n"
            ".tx-landscape>svg{position:absolute;inset:auto 0 0 0;width:100%;height:78%;z-index:-1}\n"
            ".tx-landscape>svg path{fill:hsl(var(--tx-hue) calc(36% + var(--layer) * 3%) calc(78% - var(--layer) * 11%))}\n"
            ".tx-landscape>svg .haze{fill:hsl(var(--tx-hue) 40% 96% / var(--tx-haze))}",
     "use_when": "Calm hero backgrounds for travel, wellness, cartography and anything that should breathe.",
     "avoid_when": "Interfaces that need a neutral ground.",
     "why": "Depth comes from value steps between layers and haze, not from detail: each ridge is a flat shape, a little lighter and bluer than the one in front.",
     "accessibility": "Decorative SVG with aria-hidden; text sits on the sky, which stays above 7:1 with dark ink.", "guides": ["visually-texture-content"],
     "markup": "<div class=\"tx-landscape\">{svg}</div>"},
    {"id": "grass", "title": "Mown grass", "title_es": "Césped",
     "summary": "Broad mowing stripes, fine blade noise and light falling from above.",
     "summary_es": "Franjas de siega anchas, ruido fino de hojas y luz que cae desde arriba.",
     "tags": ["grass", "lawn", "stripes", "nature", "cesped", "hierba", "naturaleza", "campo"], "controls": [
         _c("--tx-hue", "Tono", 70, 150, 1, 108), _c("--tx-stripe", "Franja (px)", 20, 160, 1, 56), _c("--tx-blades", "Hojas", 0, 0.7, 0.01, 0.34)],
     "css": ".tx-grass{--tx-hue:108;--tx-stripe:56;--tx-blades:.34;position:relative;isolation:isolate;overflow:hidden;background-color:hsl(var(--tx-hue) 50% 27%);"
            "background-image:radial-gradient(130% 90% at 50% 0%,hsl(var(--tx-hue) 70% 70% / .38),transparent 62%),"
            "repeating-linear-gradient(90deg,hsl(var(--tx-hue) 55% 36% / .5) 0 calc(var(--tx-stripe) * 1px),transparent 0 calc(var(--tx-stripe) * 2px))}\n"
            ".tx-grass::after{content:\"\";position:absolute;inset:0;z-index:-1;background:" + BLADES + ";background-size:300px;opacity:var(--tx-blades);mix-blend-mode:soft-light}",
     "use_when": "Sport, garden, outdoor and sustainability pages.",
     "avoid_when": "Anything that is not about nature: green is a strong signal.",
     "why": "Alternating stripe widths mimic mowing, the anisotropic noise reads as blades, and the top light gives the field a horizon.",
     "accessibility": "Decorative; keep body text on a panel.", "guides": ["visually-texture-content"]},
    {"id": "softshadow", "title": "Soft shadow", "title_es": "Sombra suave",
     "summary": "Six layered shadows that double in offset and blur, so an object sits on the page instead of floating.",
     "summary_es": "Seis sombras apiladas cuyo desplazamiento y desenfoque se duplican, para que un objeto se apoye en la página y no flote.",
     "tags": ["shadow", "elevation", "depth", "card", "sombra", "elevacion", "profundidad", "tarjeta"], "controls": [
         _c("--tx-elev", "Elevación", 1, 24, 1, 8), _c("--tx-shadow-hue", "Tono de la sombra", 0, 360, 1, 222), _c("--tx-shadow-alpha", "Opacidad", 0.04, 0.3, 0.01, 0.1)],
     "css": ".tx-softshadow{--tx-elev:8;--tx-shadow-hue:222;--tx-shadow-alpha:.1;"
            "box-shadow:0 calc(var(--tx-elev) * .125px) calc(var(--tx-elev) * .25px) hsl(var(--tx-shadow-hue) 40% 18% / var(--tx-shadow-alpha)),"
            "0 calc(var(--tx-elev) * .25px) calc(var(--tx-elev) * .5px) hsl(var(--tx-shadow-hue) 40% 18% / var(--tx-shadow-alpha)),"
            "0 calc(var(--tx-elev) * .5px) calc(var(--tx-elev) * 1px) hsl(var(--tx-shadow-hue) 40% 18% / var(--tx-shadow-alpha)),"
            "0 calc(var(--tx-elev) * 1px) calc(var(--tx-elev) * 2px) hsl(var(--tx-shadow-hue) 40% 18% / var(--tx-shadow-alpha)),"
            "0 calc(var(--tx-elev) * 2px) calc(var(--tx-elev) * 4px) hsl(var(--tx-shadow-hue) 40% 18% / var(--tx-shadow-alpha)),"
            "0 calc(var(--tx-elev) * 4px) calc(var(--tx-elev) * 8px) hsl(var(--tx-shadow-hue) 40% 18% / var(--tx-shadow-alpha))}",
     "use_when": "Cards, popovers and images that must lift off a surface without a hard outline.",
     "avoid_when": "Dark interfaces, where shadow cannot show: raise by lightness steps instead.",
     "why": "Real shadows are a gradient of penumbras; layers that double apply the same law and look physical, where one box-shadow looks like a halo.",
     "accessibility": "No effect on contrast; do not use it as the only cue for focus.", "guides": ["visually-texture-content"]},
]


def landscape_svg(seed: int = 7, layers: int = 5, width: int = 1600, height: int = 620) -> str:
    """Seeded ridgelines by midpoint displacement: the same seed always draws the same land."""
    rnd = random.Random(seed)
    parts = []
    for layer in range(layers):
        base = height * (0.16 + 0.15 * layer)
        rough = 0.5 - layer * 0.04
        pts = [base + rnd.uniform(-40, 40), base + rnd.uniform(-40, 40)]
        amp = 120 - layer * 14
        for _ in range(7):
            nxt = []
            for a, b in zip(pts, pts[1:]):
                nxt.extend([a, (a + b) / 2 + rnd.uniform(-amp, amp)])
            nxt.append(pts[-1])
            pts = nxt
            amp *= rough
        step = width / (len(pts) - 1)
        d = "M0 %d " % height + " ".join("L%.1f %.1f" % (i * step, y) for i, y in enumerate(pts)) + " L%d %d Z" % (width, height)
        parts.append(f'<path style="--layer:{layer}" d="{d}"/>')
        parts.append(f'<rect class="haze" y="{base + 40:.0f}" width="{width}" height="{height}" opacity=".5"/>' if layer < layers - 1 else "")
    return f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" aria-hidden="true">{"".join(parts)}</svg>'


def example_html(texture: dict, seed: int = 7) -> str:
    cls = f"tx-{texture['id']}"
    if texture["id"] == "landscape":
        return f'<div class="{cls}" style="min-height:360px">{landscape_svg(seed)}</div>'
    if texture["id"] == "fluted":
        return f'<div style="background:linear-gradient(120deg,#f4a259,#e4572e 50%,#17bebb);padding:40px"><div class="{cls}" style="min-height:220px"></div></div>'
    if texture["id"] == "softshadow":
        return f'<div style="background:#eef0f4;padding:48px"><div class="{cls}" style="background:#fff;border-radius:14px;min-height:140px"></div></div>'
    if texture["id"] == "grain":
        return f'<div class="{cls}" style="min-height:320px;background:linear-gradient(135deg,#3b6ea5,#e8a87c)"></div>'
    return f'<div class="{cls}" style="min-height:320px"></div>'


def by_id(texture_id: str) -> dict:
    row = next((t for t in TEXTURES if t["id"] == texture_id), None)
    if row is None:
        raise LookupError("Unknown texture recipe: " + texture_id)
    return row
