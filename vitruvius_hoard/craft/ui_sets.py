"""UI style sets: ordinary controls with a distinct look (anime, 1930s cartoon, pixel art) that a page can use instead of the default ones.

Three MIT-licensed sets ship in ``ui_sets/`` (one plain script per control, the licence beside them). A fourth, an effects pack whose licence
requires a visible credit, is only described here and downloaded on demand with its credit line written next to the files. Everything is read
from disk, so discovery needs no engine and no data store.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.request
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent / "ui_sets"
CITE = "[vitruvius: craft/{kind}/{id}]"

#: Sets that are not copied into the repository: the licence asks for a visible credit on every use and forbids redistributing the assets as a pack.
ON_DEMAND = [{
    "id": "kanaworks-sakuga-vfx", "name": "KanaWorks Sakuga VFX", "look": "efectos de juego estilo anime",
    "summary": "Anime-style game effects (fire, water, thunder, wind, poison, ice, light, dark, rock) as transparent flipbook sprite sheets with a small JSON of grid, frames, fps and pivot.",
    "summary_es": "Efectos de juego estilo anime (fuego, agua, trueno, viento, veneno, hielo, luz, oscuridad, roca) como hojas de sprites transparentes, con un JSON de rejilla, fotogramas y fps.",
    "tags": ["anime", "efectos", "vfx", "juego", "sprites", "flipbook", "fuego", "agua", "trueno", "unity", "godot", "web"],
    "license": "KanaWorks_AI VFX Asset License 1.0 (assets); MIT (code)", "delivery": "on_demand",
    "source": "https://github.com/kanaworksai-hue/kanaworks-sakuga-vfx", "release": "v1.0.0",
    "credit": "VFX: KanaWorks_AI (@KanaWorks_AI)",
    "conditions_es": ("Gratis para personas y empresas con menos de 1 M USD de ingresos anuales; hay que mostrar el crédito en toda obra que use los efectos "
                      "(créditos del juego, descripción del vídeo, pie de la web). No se pueden redistribuir los efectos como pack de recursos. "
                      "Los efectos no se copian a este repositorio: se descargan bajo demanda."),
    "download": "https://github.com/kanaworksai-hue/kanaworks-sakuga-vfx/releases/download/v1.0.0/{effect}.zip",
    "checksums": "https://github.com/kanaworksai-hue/kanaworks-sakuga-vfx/releases/download/v1.0.0/SHA256SUMS.txt",
    "effect_pattern": r"^(dark|fire|ice|light|poison|rock|thunder|water|wind)_(aura|charge|column|impact|projectile|shield|slash|strike|vortex)_0[1-3]$",
    "max_bytes": 40_000_000,
}]


@lru_cache(maxsize=1)
def catalog() -> dict:
    data = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    return data


def sets() -> list[dict]:
    return catalog()["sets"]


def get(set_id: str) -> dict:
    row = next((s for s in sets() if s["id"] == set_id), None)
    if row is not None:
        return row
    row = next((s for s in ON_DEMAND if s["id"] == set_id), None)
    if row is None:
        raise LookupError("Unknown UI set: " + str(set_id))
    return row


def control(set_id: str, control_id: str) -> tuple[dict, dict]:
    owner = get(set_id)
    if owner.get("delivery") != "bundled":
        raise LookupError(f"{set_id} has no bundled controls; use ui_set_fetch")
    row = next((c for c in owner["controls"] if c["id"] == control_id), None)
    if row is None:
        raise LookupError(f"Unknown control {control_id!r} in {set_id}: " + ", ".join(c["id"] for c in owner["controls"]))
    return owner, row


def _script(set_id: str, row: dict) -> str:
    return (ROOT / set_id / row["file"]).read_text(encoding="utf-8")


def summary_row(owner: dict) -> dict:
    return {"id": owner["id"], "title": owner["name"], "summary": owner["summary_es"] if "summary_es" in owner else owner["summary"],
            "tags": owner["tags"] + [owner["name"], owner["summary"], owner["look"]], "delivery": owner["delivery"],
            "reference_url": f"/craft/ui-sets/{owner['id']}/index.html" if owner["delivery"] == "bundled" else owner["source"]}


def control_rows() -> list[dict]:
    out = []
    for owner in sets():
        for c in owner["controls"]:
            out.append({"id": f"{owner['id']}/{c['id']}", "title": f"{owner['name']}: {c['title_es']}", "summary": c["use_when_es"],
                        "tags": owner["tags"] + [c["tag"], c["id"], c["title_es"], c["description"], owner["look"]],
                        "reference_url": f"/craft/ui-sets/{owner['id']}/{c['id']}/index.html"})
    return out


def listing() -> list[dict]:
    out = []
    for owner in [*sets(), *ON_DEMAND]:
        out.append({"id": owner["id"], "name": owner["name"], "look": owner["look"], "delivery": owner["delivery"], "license": owner["license"],
                    "summary": owner.get("summary_es") or owner["summary"], "controls": [c["id"] for c in owner.get("controls", [])],
                    "credit": owner.get("credit"), "cite": CITE.format(kind="ui-set", id=owner["id"]),
                    "reference_url": f"/craft/ui-sets/{owner['id']}/index.html" if owner["delivery"] == "bundled" else owner["source"]})
    return out


def read_set(set_id: str) -> dict:
    owner = get(set_id)
    base = {k: v for k, v in owner.items() if k != "controls"}
    base.update({"kind": "ui-set", "cite": CITE.format(kind="ui-set", id=set_id)})
    if owner["delivery"] == "bundled":
        base["controls"] = [{"id": c["id"], "tag": c["tag"], "title": c["title_es"], "use_when": c["use_when_es"], "avoid_when": c["avoid_when_es"], "demo": c["demo"],
                             "bytes": c["bytes"], "accessibility_note": c.get("a11y_note_es"), "preview_url": f"/craft/ui-sets/{set_id}/{c['id']}/index.html"} for c in owner["controls"]]
        base["board_url"] = f"/craft/ui-sets/{set_id}/index.html"
        base["how_to_use"] = ("Each control is one plain script that registers a custom element: load it with a script tag (not as a module), then use the element. "
                              "Do not rewrite or split the file. Pick the control by what it does for the person (use_when), then read it with craft_read kind ui-control, "
                              "preview it with craft_page kind ui-control and copy the files into the project with ui_set_install. Keep the licence file beside them.")
        base["accessibility"] = ("The look is the set's; the behaviour must stay the control's. Keep a visible text name (label, or the text inside), reach every control with Tab, "
                                 "keep a visible focus ring, and check with design_critique (interaction rules) after wiring it in.")
    else:
        base["how_to_use"] = "Download one effect with ui_set_fetch (id and effect name); the credit line is written beside the files and must be shown wherever the effect is used."
    return base


def read_control(set_id: str, control_id: str) -> dict:
    owner, row = control(set_id, control_id)
    return {**{k: v for k, v in row.items() if k not in {"use_when_es", "avoid_when_es", "title_es", "a11y_note_es"}}, "kind": "ui-control", "set": set_id, "title": row["title_es"],
            "use_when": row["use_when_es"], "avoid_when": row["avoid_when_es"], "accessibility_note": row.get("a11y_note_es"), "cite": CITE.format(kind="ui-control", id=f"{set_id}/{control_id}"),
            "license": owner["license"], "source": owner["source"], "commit": owner["commit"], "preview_url": f"/craft/ui-sets/{set_id}/{control_id}/index.html",
            "script": f"{set_id}/{row['file']}", "usage": f'<script src="{row["file"]}"></script>\n{row["demo"]}'}


# ── pages ───────────────────────────────────────────────────────────────────

_CSS = ("*{box-sizing:border-box}html{overflow-x:clip}body{margin:0;font:16px/1.5 system-ui,sans-serif;background:#fff;color:#1d1a4a}main{max-width:760px;margin:0 auto;padding:32px 20px 56px}"
        "h1{font-size:28px;line-height:1.15;margin:0 0 6px}p{margin:0 0 12px}.stage{display:flex;flex-wrap:wrap;gap:24px;align-items:center;justify-content:center;min-height:240px;padding:32px 0}"
        "ul{padding:0;list-style:none;display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr));gap:12px}li{border:1px solid #cfcbea;border-radius:8px;padding:12px}"
        "a{color:#4b3fd0}:focus-visible{outline:3px solid #0b6fb3;outline-offset:3px}.meta{color:#5a5690;font-size:14px}code{font-size:14px}")


def _doc(title: str, body: str, script: str = "", description: str = "") -> dict:
    source = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
              f'<title>{html.escape(title)}</title><meta name="description" content="{html.escape(description or title, quote=True)}"><style>{_CSS}</style></head>'
              f"<body><main>{body}</main>{script}</body></html>")
    return {"html": source, "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(), "title": title}


def _driver(row: dict) -> str:
    """A small, label-free script that makes the demo show its main reaction without a click (progress, toast, status)."""
    tag = row["tag"]
    kind = row["kind"]
    if kind == "progress" or tag in {"round-bar", "sigil-spinner"}:
        return (f"<script>{{const el=document.querySelector('{tag}');let v=0;const tick=()=>{{v=v>=1?0:Math.min(1,v+.1);el.set&&el.set(v)}};"
                "setInterval(tick,700)}</script>")
    if kind == "toast":
        return (f"<p><button type=\"button\" id=\"go\">Mostrar aviso</button></p><script>document.getElementById('go').addEventListener('click',()=>"
                f"document.querySelector('{tag}').show('Guardado'))</script>")
    return ""


def control_page(set_id: str, control_id: str, params: dict | None = None) -> dict:
    owner, row = control(set_id, control_id)
    params = params or {}
    inline = params.get("inline", True)
    script = f'<script>{_script(set_id, row)}</script>' if inline else f'<script src="/craft/ui-sets/{set_id}/{row["file"]}"></script>'
    demo = str(params.get("markup") or row["demo"])
    body = (f'<h1>{html.escape(owner["name"])}: {html.escape(row["title_es"])}</h1><p class="meta">{html.escape(row["use_when_es"])}</p>'
            f'<div class="stage">{demo}</div><p class="meta">Evitar: {html.escape(row["avoid_when_es"])}</p>'
            f'<p class="meta"><code>&lt;{html.escape(row["tag"])}&gt;</code> · Licencia {html.escape(owner["license"])} · <a href="{html.escape(owner["source"], quote=True)}">origen</a></p>')
    return _doc(f"{owner['name']}: {row['title_es']}", body, script + _driver(row), row["use_when_es"])


def set_page(set_id: str) -> dict:
    owner = get(set_id)
    if owner["delivery"] != "bundled":
        raise LookupError(f"{set_id} is downloaded on demand; there is no bundled preview")
    items = "".join(f'<li><a href="/craft/ui-sets/{set_id}/{c["id"]}/index.html"><strong>{html.escape(c["title_es"])}</strong></a>'
                    f'<p class="meta">{html.escape(c["use_when_es"])}</p><code>&lt;{html.escape(c["tag"])}&gt;</code></li>' for c in owner["controls"])
    body = (f'<h1>{html.escape(owner["name"])}</h1><p>{html.escape(owner["summary_es"])}</p><p class="meta">{html.escape(owner["palette_es"])} Licencia {html.escape(owner["license"])}, '
            f'{html.escape(owner["copyright"])}.</p><ul>{items}</ul>')
    return _doc(owner["name"], body, description=owner["summary_es"])


def board_page() -> dict:
    cards = "".join(f'<li><a href="/craft/ui-sets/{s["id"]}/index.html"><strong>{html.escape(s["name"])}</strong></a><p class="meta">{html.escape(s["summary_es"])}</p>'
                    f'<p class="meta">{len(s["controls"])} controles · {html.escape(s["license"])}</p></li>' for s in sets())
    extra = "".join(f'<li><a href="{html.escape(s["source"], quote=True)}"><strong>{html.escape(s["name"])}</strong></a><p class="meta">{html.escape(s["summary_es"])}</p>'
                    f'<p class="meta">Descarga bajo demanda · crédito obligatorio: {html.escape(s["credit"])}</p></li>' for s in ON_DEMAND)
    return _doc("Paquetes de estilo para controles", f'<h1>Paquetes de estilo para controles</h1><p>Aspectos distintos para botones, interruptores, deslizadores y demás.</p><ul>{cards}{extra}</ul>')


def asset(set_id: str, filename: str) -> bytes:
    owner = get(set_id)
    names = {c["file"] for c in owner.get("controls", [])} | {"LICENSE"}
    if owner["delivery"] != "bundled" or filename not in names:
        raise LookupError("Unknown file: " + filename)
    return (ROOT / set_id / filename).read_bytes()


# ── install and download ────────────────────────────────────────────────────

def install(set_id: str, out_dir: str, controls: list[str] | None = None) -> dict:
    """Copy the chosen controls (all of them when none is named) and the licence into ``out_dir/<set id>/``; nothing else on disk changes."""
    owner = get(set_id)
    if owner["delivery"] != "bundled":
        raise LookupError(f"{set_id} is downloaded on demand; use ui_set_fetch")
    chosen = list(controls or [c["id"] for c in owner["controls"]])
    rows = [control(set_id, cid)[1] for cid in chosen]
    dest = Path(out_dir).expanduser().resolve() / set_id
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for row in rows:
        (dest / row["file"]).write_bytes((ROOT / set_id / row["file"]).read_bytes())
        written.append(str(dest / row["file"]))
    (dest / "LICENSE").write_bytes((ROOT / set_id / "LICENSE").read_bytes())
    snippets = "\n".join(f'<script src="{set_id}/{r["file"]}"></script>' for r in rows) + "\n" + "\n".join(r["demo"] for r in rows)
    return {"set": set_id, "dir": str(dest), "files": written + [str(dest / "LICENSE")], "snippet": snippets,
            "license": owner["license"], "note": "Keep the LICENSE file beside the scripts. Load each script with a plain script tag, not as a module."}


_EFFECT = re.compile(r"[a-z0-9_]+")


def fetch(set_id: str, effect: str, out_dir: str, *, opener=None) -> dict:
    """Download one effect of an on-demand set into ``out_dir/<set id>/`` and write its credit and licence note beside it."""
    owner = next((s for s in ON_DEMAND if s["id"] == set_id), None)
    if owner is None:
        raise LookupError("Not an on-demand set: " + str(set_id))
    if not _EFFECT.fullmatch(effect or "") or not re.fullmatch(owner["effect_pattern"], effect):
        raise ValueError("effect must look like fire_impact_01 (element_form_number); see craft_read kind ui-set for the list")
    url = owner["download"].format(effect=effect)
    opener = opener or (lambda target: urllib.request.urlopen(urllib.request.Request(target, headers={"User-Agent": "vitruvius-hoard"}), timeout=60))
    with opener(url) as response:
        data = response.read(owner["max_bytes"] + 1)
    if len(data) > owner["max_bytes"]:
        raise ValueError("The download is larger than the limit for one effect")
    dest = Path(out_dir).expanduser().resolve() / set_id
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"{effect}.zip"
    target.write_bytes(data)
    credit = dest / "CREDIT.txt"
    credit.write_text(f"{owner['credit']}\n\nSource: {owner['source']}\nLicense: {owner['license']}\n\n{owner['conditions_es']}\n", encoding="utf-8")
    return {"set": set_id, "effect": effect, "file": str(target), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "credit_file": str(credit),
            "credit": owner["credit"], "checksums": owner["checksums"],
            "note": "Show the credit line wherever the effect is used. Do not redistribute the effects as a pack."}
