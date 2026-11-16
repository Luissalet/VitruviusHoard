"""Three native 3D scenes with live controls, built on the bundled three.js module: the kind of 3D hero that ships as a controllable component."""
from __future__ import annotations

import hashlib
import html
import json

from . import pages


def _c(key, label, low, high, step, default):
    return {"key": key, "label": label, "min": low, "max": high, "step": step, "default": default}


SCENES: list[dict] = [
    {"id": "orbital", "title": "Orbital sphere", "title_es": "Esfera orbital",
     "summary": "Points laid on a sphere by the golden angle, with two thin rings; drag to turn it.",
     "summary_es": "Puntos repartidos sobre una esfera con el ángulo áureo y dos anillos finos; arrastra para girarla.",
     "tags": ["3d", "sphere", "points", "hero", "esfera", "puntos", "orbita", "three"],
     "decisions": {"structure": "A centred object with the headline pushed to the left edge, leaving negative space around the sphere.",
                   "interaction": "Drag turns it, arrow keys turn it from the keyboard, and the sliders rebuild it. Reduced motion stops the idle spin.",
                   "why": "The golden angle gives an even spread with no clumps; points and hairline rings read as precise without any texture file."},
     "controls": [_c("count", "Puntos", 200, 4000, 100, 1600), _c("radius", "Radio", 1, 3, 0.1, 2), _c("hue", "Tono", 0, 360, 1, 205), _c("speed", "Velocidad", 0, 3, 0.1, 1)]},
    {"id": "waves", "title": "Wave field", "title_es": "Campo de olas",
     "summary": "A grid of points displaced by two crossing sine waves, seen at a low angle.",
     "summary_es": "Una rejilla de puntos desplazada por dos ondas senoidales que se cruzan, vista desde un ángulo bajo.",
     "tags": ["3d", "grid", "waves", "motion", "background", "rejilla", "olas", "movimiento", "fondo"],
     "decisions": {"structure": "A full-width field under the headline; the camera looks across it like a horizon.",
                   "interaction": "Amplitude, frequency and speed are sliders; drag turns the field. The still view freezes at t=0.",
                   "why": "Two waves at different frequencies avoid the obvious repeat of one; points keep the cost low and the look light."},
     "controls": [_c("count", "Densidad", 30, 120, 5, 70), _c("amplitude", "Amplitud", 0, 1.6, 0.05, 0.6), _c("frequency", "Frecuencia", 0.2, 2, 0.05, 0.8), _c("hue", "Tono", 0, 360, 1, 175), _c("speed", "Velocidad", 0, 3, 0.1, 1)]},
    {"id": "crystal", "title": "Faceted crystal", "title_es": "Cristal facetado",
     "summary": "A flat-shaded polyhedron with a visible edge net, lit from one side.",
     "summary_es": "Un poliedro con sombreado plano y red de aristas visible, iluminado desde un lado.",
     "tags": ["3d", "polyhedron", "icon", "facets", "poliedro", "icono", "facetas", "cristal"],
     "decisions": {"structure": "One object, one light, nothing else on the canvas, so it works as a logo or an icon at hero size.",
                   "interaction": "Detail rebuilds the geometry (0 gives twenty faces); drag and arrow keys turn it.",
                   "why": "Flat shading keeps every facet legible; a single directional light gives the form without any texture."},
     "controls": [_c("detail", "Facetas", 0, 3, 1, 1), _c("radius", "Radio", 1, 3, 0.1, 2), _c("hue", "Tono", 0, 360, 1, 330), _c("speed", "Velocidad", 0, 3, 0.1, 1)]},
]


def by_id(scene_id: str) -> dict:
    row = next((s for s in SCENES if s["id"] == scene_id), None)
    if row is None:
        raise LookupError("Unknown 3D scene: " + scene_id)
    return row


def page(scene_id: str, title: str = "") -> dict:
    s = by_id(scene_id)
    name = html.escape(title or s["title_es"])
    spec = json.dumps({"controls": s["controls"]}).replace("<", "\\u003c")
    css = ("body{background:#0d1117;color:#eef2f6}.hero{position:relative;min-height:100svh;display:grid;grid-template-columns:minmax(260px,5fr) 7fr;align-items:center}"
           ".copy{padding:clamp(24px,5vw,80px);position:relative;z-index:2}.copy h1{font-size:clamp(48px,7vw,112px)}.copy p{max-width:36ch;color:#b9c4cf;margin:18px 0 28px}"
           ".stage{position:relative;height:100svh}canvas{width:100%;height:100%;display:block;cursor:grab;touch-action:pan-y}"
           "#controls{position:absolute;left:clamp(24px,5vw,80px);bottom:24px;z-index:3;display:grid;gap:4px;width:min(360px,80vw);background:#0d1117cc;padding:14px;border:1px solid #2a3440;border-radius:10px}"
           ".ctl{display:grid;grid-template-columns:96px 1fr 44px;gap:10px;align-items:center;font-size:14px}.ctl output{text-align:right;font-variant-numeric:tabular-nums}"
           "@media(max-width:820px){.hero{grid-template-columns:1fr}.stage{position:absolute;inset:0;opacity:.55}#controls{position:relative;left:0;margin:24px}}")
    body = (f'<main class="hero" data-scene="{scene_id}"><div class="copy"><h1>{name}</h1><p>{html.escape(s["summary_es"])}</p></div>'
            f'<div class="stage"><canvas id="scene" tabindex="0" aria-label="Escena 3D: {name}. Arrastra o usa las flechas para girarla."></canvas></div>'
            '<aside id="controls" aria-label="Controles de la escena"></aside></main>'
            f'<script type="application/json" id="spec">{spec}</script><script type="module" src="/craft/scenes.js"></script>')
    doc = pages.document(f"{s['title_es']} — escena 3D", css, body)
    doc["html"] = doc["html"].replace("<body>", f'<body data-scene="{scene_id}">', 1)
    doc["sha256"] = hashlib.sha256(doc["html"].encode("utf-8")).hexdigest()
    return doc
