"""Reference library for designs that are not generic: textures, heroes, 3D scenes, dashboard rules, the 3D-model-to-site recipe and an
index of the ThreeUI Community catalogue (MIT). Everything is read from disk, so discovery needs no engine and no data store."""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent
KINDS = ("texture", "hero", "scene", "dashboard-rule", "model-site", "threeui", "ui-set", "ui-control")
CITE = "[vitruvius: craft/{kind}/{id}]"

_ES = {"textura": "texture", "texturas": "texture", "degradado": "gradient", "ondas": "waves", "grano": "grain", "cesped": "grass", "hierba": "grass",
       "sombra": "shadow", "vidrio": "glass", "paisaje": "landscape", "curvas": "contour", "plano": "blueprint", "cuadricula": "grid",
       "portada": "hero", "cabecera": "hero", "panel": "dashboard", "cuadro": "dashboard", "mando": "dashboard", "tarjeta": "card", "tarjetas": "card",
       "boton": "button", "botones": "buttons", "fondo": "background", "fondos": "background", "tres": "3d", "esfera": "sphere", "cristal": "crystal",
       "modelo": "model", "maqueta": "model", "corte": "section", "inmobiliaria": "real estate", "arquitectura": "architecture", "escena": "scene",
       "movimiento": "motion", "iconos": "icons", "icono": "icons", "texto": "text", "tipografia": "type", "paleta": "palette", "comandos": "command"}
_STOP = {"de", "del", "la", "el", "los", "las", "un", "una", "para", "con", "y", "o", "en", "a", "al", "the", "and", "or", "for", "of", "to", "in"}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def _terms(query: str) -> list[str]:
    out: list[str] = []
    for word in re.findall(r"[a-z0-9]+", _fold(query)):
        if word in _STOP:
            continue
        out.append(word)
        out.extend(_ES.get(word, "").split())
        if len(word) > 3 and word.endswith("s"):
            out.append(word[:-1])
    return out


@lru_cache(maxsize=1)
def threeui() -> list[dict]:
    return json.loads((ROOT / "threeui_catalog.json").read_text(encoding="utf-8"))


def _rows() -> list[dict]:
    from . import dashboard, heroes, model_site, scenes, textures, ui_sets
    rows = []
    for t in textures.TEXTURES:
        rows.append({"kind": "texture", "id": t["id"], "title": t["title_es"], "summary": t["summary_es"], "tags": t["tags"] + [t["title"], t["summary"]],
                     "reference_url": f"/craft/textures/#{t['id']}"})
    for h in heroes.HEROES:
        rows.append({"kind": "hero", "id": h["id"], "title": h["title_es"], "summary": h["summary_es"], "tags": h["tags"] + [h["title"], h["summary"]],
                     "reference_url": f"/craft/heroes/{h['id']}/index.html"})
    for s in scenes.SCENES:
        rows.append({"kind": "scene", "id": s["id"], "title": s["title_es"], "summary": s["summary_es"], "tags": s["tags"] + [s["title"], s["summary"]],
                     "reference_url": f"/craft/scenes/{s['id']}/index.html"})
    for r in dashboard.RULES:
        rows.append({"kind": "dashboard-rule", "id": r["id"], "title": r["title_es"], "summary": r["do_es"], "tags": ["dashboard", "panel", "rule", r["title"], r["do"]],
                     "reference_url": "/craft/dashboard/index.html"})
    rows.append({"kind": "model-site", "id": "model-site", "title": model_site.RECIPE["title_es"], "summary": model_site.RECIPE["summary_es"],
                 "tags": model_site.RECIPE["tags"] + [model_site.RECIPE["title"], model_site.RECIPE["summary"]], "reference_url": ""})
    for c in threeui():
        if c.get("variant_of"):
            continue
        rows.append({"kind": "threeui", "id": c["id"], "title": c["label"], "summary": c["description"][:200], "tags": c["tags"] + [c["category"], c["runtime"]],
                     "reference_url": ""})
    for owner in [*ui_sets.sets(), *ui_sets.ON_DEMAND]:
        base = ui_sets.summary_row(owner)
        rows.append({"kind": "ui-set", "id": base["id"], "title": base["title"], "summary": base["summary"], "tags": base["tags"], "reference_url": base["reference_url"]})
    for base in ui_sets.control_rows():
        rows.append({"kind": "ui-control", "id": base["id"], "title": base["title"], "summary": base["summary"], "tags": base["tags"], "reference_url": base["reference_url"]})
    for row in rows:
        row["cite"] = CITE.format(kind=row["kind"], id=row["id"])
    return rows


def search(query: str = "", kind: str | None = None, limit: int = 10) -> dict:
    if kind and kind not in KINDS:
        raise ValueError("kind must be one of: " + ", ".join(KINDS))
    terms = set(_terms(query))
    rows = [r for r in _rows() if not kind or r["kind"] == kind]
    words = {r["id"]: set(re.findall(r"[a-z0-9]+", _fold(" ".join([r["id"], r["title"], r["summary"], *r["tags"]])))) for r in rows}
    weight = {t: 1 + 4 / max(1, sum(t in w for w in words.values())) for t in terms}  # a rare word says more than a common one
    scored = []
    for row in rows:
        if not terms:
            scored.append((0, row))
            continue
        id_words = set(re.findall(r"[a-z0-9]+", _fold(row["id"])))
        title_words = set(re.findall(r"[a-z0-9]+", _fold(row["title"])))
        hay = set(re.findall(r"[a-z0-9]+", _fold(" ".join([row["summary"], *row["tags"]]))))
        score = sum(weight[t] * (6 * (t in id_words) + 4 * (t in title_words) + 2 * (t in hay)) for t in terms)
        if score:
            scored.append((score + (0 if row["kind"] in {"threeui", "ui-control"} else 3), row))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["kind"], pair[1]["id"]))
    limit = max(1, min(int(limit or 10), 60))
    items = [{"kind": r["kind"], "id": r["id"], "title": r["title"], "summary": r["summary"], "cite": r["cite"], "reference_url": r["reference_url"], "score": round(s, 2)}
             for s, r in scored[:limit]]
    counts: dict[str, int] = {}
    for _, r in scored:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return {"query": query, "items": items, "matched": len(scored), "by_kind": counts}


def read(kind: str, item_id: str) -> dict:
    from . import dashboard, heroes, model_site, scenes, textures, ui_sets
    if kind == "ui-set":
        return ui_sets.read_set(item_id)
    if kind == "ui-control":
        set_id, _, control_id = item_id.partition("/")
        return ui_sets.read_control(set_id, control_id)
    if kind == "texture":
        t = textures.by_id(item_id)
        return {**{k: v for k, v in t.items() if k != "markup"}, "kind": kind, "cite": CITE.format(kind=kind, id=item_id), "example_html": textures.example_html(t),
                "page_url": f"/craft/textures/#{item_id}", "page_tool": "craft_page"}
    if kind == "hero":
        h = heroes.by_id(item_id)
        return {**h, "kind": kind, "cite": CITE.format(kind=kind, id=item_id), "reference_url": f"/craft/heroes/{item_id}/index.html"}
    if kind == "scene":
        s = scenes.by_id(item_id)
        return {**s, "kind": kind, "cite": CITE.format(kind=kind, id=item_id), "reference_url": f"/craft/scenes/{item_id}/index.html",
                "source_url": "/craft/scenes.js", "requires": "/showcase/assets/three.module.js"}
    if kind == "dashboard-rule":
        r = next((x for x in dashboard.RULES if x["id"] == item_id), None)
        if r is None:
            raise LookupError("Unknown dashboard rule: " + item_id)
        return {**r, "kind": kind, "cite": CITE.format(kind=kind, id=item_id), "reference_url": "/craft/dashboard/index.html"}
    if kind == "model-site":
        return {**model_site.RECIPE, "kind": kind, "cite": CITE.format(kind=kind, id="model-site"), "default_views": model_site.DEFAULT_VIEWS, "tool": "craft_model_site"}
    if kind == "threeui":
        c = next((x for x in threeui() if x["id"] == item_id), None)
        if c is None:
            raise LookupError("Unknown ThreeUI component: " + item_id)
        variants = [x for x in threeui() if x.get("variant_of") == item_id]
        return {**c, "kind": kind, "cite": CITE.format(kind=kind, id=item_id), "variant_records": [{"id": v["id"], "label": v["label"]} for v in variants],
                "origin": {"project": "ThreeUI Community", "repository": "https://github.com/MengTo/threeui", "license": "MIT",
                           "note": "Catalogue metadata only. The native scenes of this library (kind scene) are the implemented references; build a catalogue entry "
                                   "into the target page from its description, controls and runtime."}}
    raise ValueError("kind must be one of: " + ", ".join(KINDS))


def page(kind: str, item_id: str, params: dict | None = None) -> dict:
    """A complete HTML document for a texture, a hero, a scene or the calm dashboard: ready to open, export or send to design_critique."""
    from . import dashboard, heroes, pages, scenes, ui_sets
    params = params or {}
    if kind == "ui-set":
        return ui_sets.set_page(item_id)
    if kind == "ui-control":
        set_id, _, control_id = item_id.partition("/")
        return ui_sets.control_page(set_id, control_id, params)
    if kind == "texture":
        return pages.texture_page(item_id, params, str(params.get("title") or ""), str(params.get("subtitle") or ""))
    if kind == "hero":
        return heroes.page(item_id, params)
    if kind == "scene":
        return scenes.page(item_id, str(params.get("title") or ""))
    if kind == "dashboard-rule":
        return dashboard.calm_dashboard()
    raise ValueError("A page can be generated for texture, hero, scene, dashboard-rule, ui-set or ui-control")


def related(findings: list[dict], focus: str | None = None, limit: int = 4) -> list[dict]:
    """References to point at from a critique: dashboard rules for the dashboard findings, textures for a flat surface, plus a focus search."""
    out: dict[tuple, dict] = {}

    def add(kind: str, item_id: str, why: str) -> None:
        row = next((r for r in _rows() if r["kind"] == kind and r["id"] == item_id), None)
        if row:
            out.setdefault((kind, item_id), {"kind": kind, "id": item_id, "title": row["title"], "cite": row["cite"], "why": why})

    from . import dashboard
    by_rule = {r["rule"]: r["id"] for r in dashboard.RULES if r["rule"]}
    for f in findings:
        cid = f.get("check_id") or ""
        if cid in by_rule:
            add("dashboard-rule", by_rule[cid], f.get("title") or cid)
        elif cid == "webcraft/flat-hero-surface":
            for tid in ("grain", "thermal", "softshadow"):
                add("texture", tid, "The top of the page is one flat colour: give it material.")
    if focus:
        for hit in search(focus, limit=limit)["items"]:
            if hit["kind"] != "threeui":
                add(hit["kind"], hit["id"], "Matches the critique focus.")
    return list(out.values())[: max(limit, 4) * 2]
