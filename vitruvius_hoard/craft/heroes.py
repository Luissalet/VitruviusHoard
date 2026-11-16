"""Hero layouts that are not the default centred headline over a gradient: three working pages and the decisions behind each."""
from __future__ import annotations

import html

from . import pages
from . import textures as tx

HEROES: list[dict] = [
    {"id": "typographic-wall", "title": "Typographic wall", "title_es": "Muro tipográfico",
     "summary": "The name set so large it crops at the edges; letters lean away from the pointer.",
     "summary_es": "El nombre compuesto tan grande que se recorta en los bordes; las letras se apartan del puntero.",
     "tags": ["type", "display", "letters", "pointer", "tipografia", "letras", "puntero", "marca"],
     "decisions": {"structure": "One word at 24vw on a tinted ground, a single sentence and one action. Nothing else competes.",
                   "interaction": "Each letter moves away from the pointer by up to 22 px with a short ease; keyboard users get the static composition.",
                   "why": "Scale is the effect: a word the size of the viewport is memorable without an image. The motion proves the page is alive and costs one listener.",
                   "avoid": "Long names (above ten letters) and pages that need a visible navigation bar above the fold."},
     "params": ["title", "subtitle", "hue"]},
    {"id": "texture-field", "title": "Texture field", "title_es": "Campo de textura",
     "summary": "A full-bleed material (thermal, graphite, grass...) with the headline set low and a switch to try the others.",
     "summary_es": "Un material a pantalla completa (térmico, grafito, césped...) con el titular abajo y un selector para probar los demás.",
     "tags": ["texture", "material", "background", "switch", "textura", "material", "fondo", "selector"],
     "decisions": {"structure": "Header fills the viewport with one texture recipe; the headline sits at the bottom edge and the controls of the recipe sit in a small strip.",
                   "interaction": "Buttons change the recipe in place; the recipe's own sliders change its look.",
                   "why": "The material carries the mood so the page needs no stock photograph; letting the person change it shows the range at no extra cost.",
                   "avoid": "Pages with long copy over the texture."},
     "params": ["title", "subtitle", "texture"]},
    {"id": "index-list", "title": "Index list", "title_es": "Índice interactivo",
     "summary": "The hero is the table of contents: a list of works whose hovered item drives a large numeral and the page colour.",
     "summary_es": "La portada es el índice: una lista de obras cuyo elemento activo gobierna un numeral grande y el color de la página.",
     "tags": ["list", "index", "portfolio", "navigation", "lista", "indice", "portafolio", "navegacion"],
     "decisions": {"structure": "A short intro, then five rows of title, year and kind. The active row names the large numeral at the right.",
                   "interaction": "Hover and keyboard focus both set the active row; the colour changes by hue only, in 240 ms.",
                   "why": "It tells a visitor what exists before they scroll and turns navigation into the first impression.",
                   "avoid": "More than eight entries: the list stops being a composition."},
     "params": ["title", "items"]},
]


def _wall(title: str, subtitle: str, hue: int) -> dict:
    letters = "".join(f'<span aria-hidden="true">{html.escape(ch)}</span>' for ch in title)
    css = (f".wall{{min-height:100svh;display:grid;align-content:space-between;overflow:hidden;padding:clamp(20px,4vw,56px);background:hsl({hue} 38% 14%);color:hsl({hue} 60% 94%)}}"
           f".wall h1{{font-size:min(24vw,40vh);line-height:.82;white-space:nowrap;margin:0 -2vw;letter-spacing:-.03em;color:hsl({hue} 80% 70%)}}"
           ".wall h1 span{display:inline-block;transition:transform .24s cubic-bezier(.2,.7,.2,1)}"
           ".wall p{max-width:40ch;font-size:clamp(18px,1.8vw,24px)}.wall a{display:inline-flex;align-items:center;min-height:48px;padding:0 26px;background:hsl(var(--h) 80% 70%);color:hsl(var(--h) 40% 12%);text-decoration:none;font-weight:600;width:max-content}"
           ".wall a:hover{background:#f9fafb}")
    body = (f'<header class="wall" style="--h:{hue}"><div><p>{html.escape(subtitle)}</p><a href="#mas">Entrar</a></div>'
            f'<h1 aria-label="{html.escape(title)}">{letters}</h1></header><main id="mas" style="padding:64px clamp(20px,4vw,56px)"><h2 style="font-size:48px">Después</h2><p style="max-width:60ch">El resto de la página empieza aquí.</p></main>')
    script = ("var ls=[].slice.call(document.querySelectorAll('.wall h1 span'));var reduce=matchMedia('(prefers-reduced-motion: reduce)');"
              "addEventListener('pointermove',function(e){if(reduce.matches)return;ls.forEach(function(s){var r=s.getBoundingClientRect();var dx=e.clientX-(r.left+r.width/2),dy=e.clientY-(r.top+r.height/2);"
              "var d=Math.hypot(dx,dy)||1,f=Math.max(0,1-d/360)*22;s.style.transform='translate('+(-dx/d*f)+'px,'+(-dy/d*f)+'px)'})})")
    return pages.document(title, css, body, script)


def _field(title: str, subtitle: str, texture: str) -> dict:
    names = [(t["id"], t["title_es"]) for t in tx.TEXTURES if t["id"] not in {"fluted", "softshadow", "grain", "landscape", "waves", "contour"}]
    base = pages.texture_page(texture, title=title, subtitle=subtitle)["html"]
    buttons = "".join(f'<button type="button" data-tx="{i}" aria-pressed="{str(i == texture).lower()}">{html.escape(n)}</button>' for i, n in names)
    strip = (f'<div class="strip" role="group" aria-label="Material">{buttons}</div>'
             "<style>.strip{position:fixed;right:20px;top:20px;display:flex;gap:6px;flex-wrap:wrap;max-width:60vw;justify-content:flex-end;z-index:5}"
             ".strip button{min-height:44px;padding:0 16px;border:1.5px solid #f9fafb;background:#0b0d1070;color:#f9fafb;cursor:pointer}.strip button[aria-pressed=true]{background:#f9fafb;color:#14181c}</style>"
             "<script>document.querySelectorAll('.strip button').forEach(function(b){b.addEventListener('click',function(){var h=document.querySelector('header.stage');"
             "h.className=h.className.replace(/tx-\\w+/,'tx-'+b.dataset.tx);h.removeAttribute('style');document.querySelectorAll('.strip button').forEach(function(o){o.setAttribute('aria-pressed',o===b)})})})</script>")
    return {**pages_wrap(base, strip), "title": title}


def pages_wrap(document_html: str, extra: str) -> dict:
    import hashlib
    source = document_html.replace("</body>", extra + "</body>")
    return {"html": source, "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()}


def _index(title: str, items: list[tuple[str, str, str]]) -> dict:
    rows = "".join(f'<li><a href="#o{i}" data-i="{i}" data-h="{(i * 67 + 200) % 360}"><span class="n">0{i + 1}</span><span class="t">{html.escape(t)}</span><span class="k">{html.escape(k)}</span><span class="y">{html.escape(y)}</span></a></li>'
                   for i, (t, k, y) in enumerate(items))
    css = (".idx{overflow-x:clip;min-height:100svh;display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:4vw;padding:clamp(20px,4vw,56px);background:hsl(var(--h,200) 30% 94%);color:hsl(var(--h,200) 40% 12%);transition:background .24s}"
           ".idx h1{font-size:clamp(44px,6vw,96px);margin-bottom:6vh}.idx ol{list-style:none;margin:0;padding:0;border-top:1.5px solid currentColor}"
           ".idx li a{display:grid;grid-template-columns:32px minmax(0,1fr) auto auto;gap:12px;align-items:baseline;padding:18px 4px;border-bottom:1.5px solid currentColor;text-decoration:none;min-height:56px}"
           ".idx li a:hover,.idx li a:focus-visible{background:hsl(var(--h,200) 60% 84%)}.idx .t{font:400 28px/1.1 'Instrument Serif',Georgia,serif}.idx .n,.idx .y{font-variant-numeric:tabular-nums;font-size:14px}"
           ".big{font:400 clamp(160px,32vw,520px)/.8 'Instrument Serif',Georgia,serif;align-self:end;justify-self:end;color:hsl(var(--h,200) 55% 40%)}"
           "@media(max-width:800px){.idx{grid-template-columns:1fr}.big{font-size:40vw}}")
    body = f'<main class="idx" style="--h:200"><div><h1>{html.escape(title)}</h1><ol>{rows}</ol></div><div class="big" aria-hidden="true">01</div></main>'
    script = ("var root=document.querySelector('.idx'),big=document.querySelector('.big');document.querySelectorAll('.idx li a').forEach(function(a){function on(){root.style.setProperty('--h',a.dataset.h);"
              "big.textContent='0'+(Number(a.dataset.i)+1)}a.addEventListener('pointerenter',on);a.addEventListener('focus',on)})")
    return pages.document(title, css, body, script)


def page(hero_id: str, params: dict | None = None) -> dict:
    params = params or {}
    if hero_id == "typographic-wall":
        return _wall(str(params.get("title") or "Faro"), str(params.get("subtitle") or "Un estudio de diseño que construye lo que dibuja."), int(params.get("hue", 205)))
    if hero_id == "texture-field":
        return _field(str(params.get("title") or "Materia"), str(params.get("subtitle") or "Un fondo que se siente, no una foto de archivo."), str(params.get("texture") or "thermal"))
    if hero_id == "index-list":
        items = params.get("items") or [("Casa en la sierra", "Vivienda", "2026"), ("Mercado cubierto", "Equipamiento", "2025"), ("Puente peatonal", "Infraestructura", "2025"),
                                        ("Biblioteca", "Cultural", "2024"), ("Pabellón de agua", "Efímero", "2023")]
        return _index(str(params.get("title") or "Obra reciente"), [tuple(i) for i in items][:8])
    raise LookupError("Unknown hero recipe: " + hero_id)


def by_id(hero_id: str) -> dict:
    row = next((h for h in HEROES if h["id"] == hero_id), None)
    if row is None:
        raise LookupError("Unknown hero recipe: " + hero_id)
    return row
