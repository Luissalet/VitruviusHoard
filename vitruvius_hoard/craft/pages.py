"""Standalone reference pages: the texture board, the hero layouts and the calm dashboard. Each is one HTML document."""
from __future__ import annotations

import hashlib
import html
import json

from . import textures as tx

FONTS = ("@font-face{font-family:'Instrument Serif';src:url('/showcase/assets/InstrumentSerif.ttf') format('truetype');font-display:swap}"
         "@font-face{font-family:'Barlow';src:url('/showcase/assets/Barlow.ttf') format('truetype');font-weight:100 900;font-display:swap}")
BASE = ("*{box-sizing:border-box}html{color-scheme:light}body{margin:0;font:400 16px/1.55 Barlow,system-ui,sans-serif;color:#14181c;background:#eceff1}"
        "h1,h2,h3{font-family:'Instrument Serif',Georgia,serif;font-weight:400;line-height:1.02;margin:0;text-wrap:balance}"
        "a{color:inherit}button,input,select{font:inherit}"
        ":focus-visible{outline:3px solid #0b6fb3;outline-offset:3px}"
        "@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}")


def document(title: str, css: str, body: str, script: str = "", lang: str = "es", description: str = "") -> dict:
    source = (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
              f'<title>{html.escape(title)}</title><meta name="description" content="{html.escape(description or title, quote=True)}"><style>{FONTS}{BASE}{css}</style></head><body>{body}'
              + (f"<script>{script}</script>" if script else "") + "</body></html>")
    return {"html": source, "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(), "title": title}


def all_texture_css() -> str:
    return "\n".join(t["css"] for t in tx.TEXTURES)


def _controls(texture: dict) -> str:
    rows = []
    for c in texture["controls"]:
        rows.append(f'<label class="ctl"><span>{html.escape(c["label"])}</span>'
                    f'<input type="range" data-var="{c["key"]}" min="{c["min"]}" max="{c["max"]}" step="{c["step"]}" value="{c["default"]}">'
                    f'<output>{c["default"]}</output></label>')
    return "".join(rows)


def textures_page() -> dict:
    cards = []
    for t in tx.TEXTURES:
        cards.append(f'<section class="card" id="{t["id"]}" aria-labelledby="h-{t["id"]}"><div class="sample">{tx.example_html(t)}</div>'
                     f'<div class="meta"><h2 id="h-{t["id"]}">{html.escape(t["title_es"])}</h2><p>{html.escape(t["summary_es"])}</p>'
                     f'<div class="ctls">{_controls(t)}</div></div></section>')
    css = (all_texture_css() +
           "main{max-width:1280px;margin:0 auto;padding:clamp(20px,4vw,56px)}header{margin-bottom:36px}header h1{font-size:clamp(40px,6vw,76px)}"
           "header p{max-width:62ch;color:#3c464e}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,520px),1fr));gap:28px}"
           ".card{background:#f9fafb;border-radius:14px;overflow:hidden;box-shadow:0 1px 2px #14181c14,0 8px 24px -12px #14181c33}"
           ".sample{overflow:hidden}.meta{padding:20px 24px 24px}.meta h2{font-size:30px}.meta p{margin:6px 0 14px;color:#3c464e}"
           ".ctl{display:grid;grid-template-columns:150px 1fr 56px;gap:12px;align-items:center;font-size:14px;margin:4px 0}.ctl output{text-align:right;font-variant-numeric:tabular-nums}"
           "nav a{margin-right:16px}")
    body = ('<main><header><h1>Texturas para diseños no planos</h1><p>Diez recetas de CSS puro, cada una con sus controles. Mueve un control para ver cómo cambia la muestra; '
            'el código de cada receta se lee con la herramienta craft_read.</p></header><div class="grid">' + "".join(cards) + '</div></main>')
    script = ("document.querySelectorAll('.ctl input').forEach(function(input){var card=input.closest('.card');var target=card.querySelector('[class*=tx-]');"
              "var out=input.parentElement.querySelector('output');function apply(){target.style.setProperty(input.dataset.var,input.value);out.textContent=input.value}"
              "input.addEventListener('input',apply);apply()})")
    return document("Texturas — Vitruvius", css, body, script)


def texture_page(texture_id: str, params: dict | None = None, title: str = "", subtitle: str = "") -> dict:
    """A full-bleed page that uses one texture as its ground and carries a real headline: the quickest way to try a recipe in a critique."""
    t = tx.by_id(texture_id)
    params = params or {}
    style = ";".join(f"{c['key']}:{params.get(c['key'].lstrip('-'), params.get(c['key'], c['default']))}" for c in t["controls"])
    inner = tx.landscape_svg(int(params.get("seed", 7))) if texture_id == "landscape" else ""
    dark = texture_id in {"thermal", "blueprint", "graphite", "grass"}
    ink = "#f6f7f8" if dark else "#14181c"
    name = html.escape(title or t["title_es"])
    css = (all_texture_css() + f".stage{{min-height:100svh;display:grid;align-content:end;padding:clamp(24px,6vw,96px);color:{ink}}}"
           ".stage h1{font-size:clamp(56px,11vw,176px);max-width:12ch;text-wrap:balance}.stage p{max-width:44ch;font-size:clamp(17px,1.6vw,21px);margin:20px 0 28px}"
           f".stage a{{display:inline-flex;align-items:center;min-height:48px;padding:0 24px;border:1.5px solid currentColor;text-decoration:none;font-weight:600;width:max-content}}"
           ".stage a:hover{background:currentColor}.stage a:hover span{color:#14181c;mix-blend-mode:difference}")
    body = (f'<header class="stage tx-{texture_id}" style="{style}">{inner}<h1>{name}</h1><p>{html.escape(subtitle or t["summary_es"])}</p>'
            f'<a href="#detalle"><span>Ver la receta</span></a></header><main id="detalle" style="padding:56px clamp(24px,6vw,96px);max-width:1100px">'
            f'<h2 style="font-size:44px">Cuándo usarla</h2><p style="max-width:62ch">{html.escape(t["use_when"])}</p></main>')
    return document(f"{t['title_es']} — receta", css, body, description=t["summary_es"])
