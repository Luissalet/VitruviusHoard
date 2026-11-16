"""Rules against the generic dashboard, with a reference dashboard that follows them. The rules are also checked by the design critique
(`webcraft/dashboard-*`), which cites them by id."""
from __future__ import annotations

import html

from . import pages

RULES: list[dict] = [
    {"id": "type-scale", "rule": "webcraft/dashboard-type-scale", "title": "A real type scale", "title_es": "Una escala tipográfica real",
     "do": "Pick five sizes on a ratio (for example 12, 14, 16, 20, 28) and use nothing else. Numbers get tabular figures.",
     "do_es": "Elige cinco tamaños con una razón fija (por ejemplo 12, 14, 16, 20, 28) y no uses otros. Las cifras llevan números tabulares.",
     "check": "Count the distinct font sizes: more than seven, or three sizes within 2 px of each other, means no scale was chosen."},
    {"id": "one-card", "rule": "webcraft/dashboard-card-styles", "title": "One card style", "title_es": "Un solo estilo de tarjeta",
     "do": "Radius, border and shadow are decided once. Variation comes from content and size, not from a second look.",
     "do_es": "El radio, el borde y la sombra se deciden una vez. La variación viene del contenido y el tamaño, no de un segundo aspecto.",
     "check": "Collect the radius, border and shadow of every card-like rule: more than two distinct combinations is a mix of styles."},
    {"id": "actions-up", "rule": "webcraft/dashboard-actions-below", "title": "Actions at the top", "title_es": "Las acciones arriba",
     "do": "The page title and its primary actions share the top row; filters follow; content after. Grouped hierarchy, not a wall of tiles.",
     "do_es": "El título de la página y sus acciones principales comparten la primera fila; luego los filtros; después el contenido. Jerarquía agrupada, no un muro de teselas.",
     "check": "The first button of the page must come before the first card."},
    {"id": "no-greeting", "rule": "webcraft/dashboard-welcome-banner", "title": "No welcome banner", "title_es": "Sin banner de bienvenida",
     "do": "Start with what changed since the last visit; the name of the person is not information.",
     "do_es": "Empieza por lo que ha cambiado desde la última visita; el nombre de la persona no es información.",
     "check": "A heading such as «Welcome back» or «Bienvenido de nuevo» on a dashboard."},
    {"id": "command-palette", "rule": "webcraft/dashboard-command-palette", "title": "A command palette", "title_es": "Una paleta de comandos",
     "do": "⌘K / Ctrl+K opens one dialog to jump anywhere or run any action; it is the same list the menus use.",
     "do_es": "⌘K / Ctrl+K abre un diálogo para saltar a cualquier sitio o lanzar cualquier acción; es la misma lista que usan los menús.",
     "check": "A dashboard with a sidebar of six or more links and no dialog, shortcut or command element."},
    {"id": "calm-cta", "rule": None, "title": "An action that feels like a win", "title_es": "Una acción que se siente como un logro",
     "do": "The primary button gets one considered hover (a lift of 2 px and a deeper fill in 160 ms), never a glow.",
     "do_es": "El botón principal recibe un solo efecto de hover cuidado (elevación de 2 px y relleno más profundo en 160 ms), nunca un resplandor.",
     "check": "Judged from the page: glowing shadows are already caught by slop/dark-glow."},
    {"id": "frosted-surface", "rule": None, "title": "Frosted glass over a real ground", "title_es": "Vidrio esmerilado sobre un fondo real",
     "do": "If a panel is translucent, put a photograph or a texture behind it (see the fluted-glass and landscape recipes); over a flat colour it does nothing.",
     "do_es": "Si un panel es translúcido, pon detrás una fotografía o una textura (recetas de vidrio acanalado y paisaje); sobre un color plano no hace nada.",
     "check": "Judged from the page."},
]


def calm_dashboard() -> dict:
    """A dashboard that follows the rules: five sizes, one card style, actions first, no greeting, a command palette."""
    css = (":root{--s0:12px;--s1:14px;--s2:16px;--s3:20px;--s4:28px;--r:10px}body{font-size:var(--s2);background:#eef1f4}"
           ".app{display:grid;grid-template-columns:232px 1fr;min-height:100svh}.side{background:#f9fafb;border-right:1px solid #d9dee3;padding:20px 12px}"
           ".side h2{font-family:Barlow,system-ui,sans-serif;font-weight:700;font-size:var(--s2);padding:0 12px 16px}.side a{display:flex;align-items:center;min-height:44px;padding:0 12px;border-radius:8px;text-decoration:none;font-size:var(--s1)}"
           ".side a[aria-current=page]{background:#e3ebf3;font-weight:600}.top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;padding:24px 32px 8px}"
           ".top h1{font-size:var(--s4)}.btn{min-height:44px;padding:0 16px;white-space:nowrap;border-radius:8px;border:1px solid #9aa6b1;background:#f9fafb;cursor:pointer;font-size:var(--s1)}"
           ".btn.primary{background:#0b5d8f;color:#f9fafb;border-color:#0b5d8f;transition:transform .16s,background .16s}.btn.primary:hover{background:#094a73;transform:translateY(-2px)}"
           ".filters{display:flex;gap:8px;padding:8px 32px 20px;flex-wrap:wrap}.chip{min-height:36px;padding:0 16px;border-radius:99px;border:1px solid #c3ccd4;background:#f9fafb;font-size:var(--s1)}"
           ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;padding:0 32px 32px}"
           ".card:first-child{grid-column:span 2}.card{background:#f9fafb;border:1px solid #d9dee3;border-radius:var(--r);padding:20px}.card .l{font-size:var(--s0);color:#4a5660}"
           ".card .v{font:400 var(--s4)/1.1 'Instrument Serif',Georgia,serif;font-variant-numeric:tabular-nums;margin-top:8px}.card .d{font-size:var(--s1);color:#2a6b3b;margin-top:8px}"
           "dialog{border:1px solid #c3ccd4;border-radius:var(--r);padding:0;width:min(560px,92vw);margin-top:12vh}dialog input{width:100%;min-height:52px;border:0;border-bottom:1px solid #d9dee3;padding:0 20px;font-size:var(--s2)}"
           "dialog ul{list-style:none;margin:0;padding:8px}dialog li button{width:100%;text-align:left;min-height:44px;border:0;background:none;padding:0 12px;border-radius:8px;font-size:var(--s1);cursor:pointer}dialog li button:hover{background:#e3ebf3}"
           "dialog::backdrop{background:#14181c66}@media(max-width:760px){.app{grid-template-columns:1fr}.side{display:none}.card:first-child{grid-column:auto}}")
    cards = "".join(f'<article class="card"><div class="l">{html.escape(l)}</div><div class="v">{html.escape(v)}</div><div class="d">{html.escape(d)}</div></article>'
                    for l, v, d in [("Pedidos hoy", "1.284", "+86 desde ayer"), ("Tiempo medio de envío", "2,4 días", "−0,3 días"), ("Devoluciones", "1,9 %", "sin cambios"), ("Ingresos del mes", "48.920 €", "+6,1 %")])
    current = ' aria-current="page"'
    links = "".join(f'<a href="#{n}"{current if n == "resumen" else ""}>{t}</a>' for n, t in
                    [("resumen", "Resumen"), ("pedidos", "Pedidos"), ("clientes", "Clientes"), ("inventario", "Inventario"), ("informes", "Informes"), ("ajustes", "Ajustes")])
    body = (f'<div class="app"><nav class="side" aria-label="Principal"><h2>Almacén</h2>{links}</nav><main><header class="head"><div class="top"><h1>Resumen</h1><div>'
            '<button class="btn" type="button" id="abrir" aria-keyshortcuts="Control+K">Buscar (Ctrl K)</button> <button class="btn primary" type="button">Nuevo pedido</button></div></div>'
            '<div class="filters" role="group" aria-label="Periodo"><span class="chip">Hoy</span><span class="chip">7 días</span><span class="chip">30 días</span></div></header>'
            f'<section class="grid" aria-label="Indicadores">{cards}</section></main></div>'
            '<dialog id="paleta" aria-label="Paleta de comandos"><input id="q" type="search" placeholder="Escribe una acción" aria-label="Buscar acción"><ul>'
            '<li><button type="button">Nuevo pedido</button></li><li><button type="button">Ir a Clientes</button></li><li><button type="button">Exportar informe</button></li></ul></dialog>')
    script = ("var d=document.getElementById('paleta');document.getElementById('abrir').addEventListener('click',function(){d.showModal()});"
              "addEventListener('keydown',function(e){if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();d.open?d.close():d.showModal()}})")
    return pages.document("Resumen — panel de referencia", css, body, script)


def slop_dashboard() -> dict:
    """The pattern the rules exist to catch (used by tests and as a before/after for the critique)."""
    css = ("body{background:#1b1030;color:#fff;font-family:Inter,sans-serif}.hero{padding:32px;font-size:34px;background:linear-gradient(135deg,#7c3aed,#4f46e5)}"
           ".stat-a{border-radius:24px;box-shadow:0 0 40px #7c3aed;padding:20px;font-size:13px}.stat-b{border-radius:6px;border:1px solid #fff4;padding:20px;font-size:15px}"
           ".stat-c{border-radius:14px;box-shadow:0 8px 30px #0008;padding:20px;font-size:17px}.t{font-size:11px}.u{font-size:19px}.w{font-size:23px}.x{font-size:31px}.y{font-size:42px}")
    body = ('<aside><nav><a href="#">A</a><a href="#">B</a><a href="#">C</a><a href="#">D</a><a href="#">E</a><a href="#">F</a></nav></aside>'
            '<main><section class="hero"><h1>Welcome back, Sam!</h1></section><div class="stats"><div class="stat-a stat">Revenue</div><div class="stat-b stat">Users</div><div class="stat-c stat">Churn</div></div>'
            '<p class="t">a</p><p class="u">b</p><p class="w">c</p><p class="x">d</p><p class="y">e</p><button>Export</button></main>')
    return pages.document("Dashboard", css, body, lang="en")
