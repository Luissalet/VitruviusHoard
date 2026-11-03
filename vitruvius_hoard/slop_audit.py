"""Slop audit: render a page at eight widths, run every generic-interface rule, score the slop and decide what to do.

* **Score** 0-100 (0 = no sign of a generated look): each distinct slop sign adds its weight once, whatever the widths.
* **Mode**: ``heavy`` (score 40+ or six signs or more) -> the full ordered fix passes; ``light`` -> a short polish list;
  ``none`` -> say so and leave the page alone.
* **Passes**, in the order they are worked: spacing, color, icons, copy, type, layout, details, visuals, motion.
* **Direction brief**: five lines (product / character / bright moment / signature / avoid) written by the family model from
  the page's own text, with a deterministic fallback from the theme catalogue when no model answers.

The mode decision, the pass order and the five-line brief follow the method of *unslop* by Damir Sokolovsky
(https://github.com/heydamir/unslop, CC BY 4.0); the multi-width render follows hallmark's sloplint (MIT). Code is original.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
AUDIT_WIDTHS = [320, 375, 414, 768, 1024, 1280, 1440, 1920]
PASSES = ("spacing", "color", "icons", "copy", "type", "layout", "details", "visuals", "motion")
PASS_TITLES = {
    "spacing": "Spacing: one 4px scale, tight inside groups, wide between them",
    "color": "Colour: one neutral surface, the accent only where it means something",
    "icons": "Icons: one line set or none, no emoji",
    "copy": "Copy: say what the product does, plainly",
    "type": "Type: a few sizes, weights 400-500, sentence case",
    "layout": "Layout: one primary action, varied widths, no stock stack",
    "details": "Details: badges, radii, punctuation, figures",
    "visuals": "Visuals: the product itself, or one concrete picture",
    "motion": "Motion: one ease-out curve, nothing that loops or floats",
}
PACKS = ["core", "slop", "unslop", "craft", "quality"]
SLOP_PACKS = {"slop", "unslop"}
SLOP_CORE = {"color.generic-ai-palette-1", "color.generic-ai-palette-2", "color.generic-ai-palette-3", "color.purple-blue-gradient",
             "content.emoji-icons", "font.generic-only", "layout.hero-three-cards", "content.placeholder-copy", "content.lorem-ipsum"}
WEIGHT = {"error": 14, "warning": 9, "advisory": 4}
HEAVY_SCORE, HEAVY_SIGNS, LIGHT_SCORE = 40, 6, 8

_PASS_OF = {
    "spacing": {"unslop/off-grid-spacing", "unslop/uneven-sibling-padding", "slop/monotonous-spacing", "craft/section-gaps",
                "quality/cramped-padding", "quality/heading-rhythm", "ds/spacing", "quality/body-text-viewport-edge",
                "quality/edge-flush-cards", "craft/dead-band"},
    "icons": {"unslop/emoji-in-ui", "content.emoji-icons", "slop/two-icon-libraries", "slop/icon-tile-stack"},
    "details": {"unslop/stacked-badges", "unslop/pill-everything", "craft/tabular-figures", "craft/straight-quotes", "craft/three-dots",
                "slop/template-punctuation", "quality/straggler", "quality/unbalanced-heading", "craft/no-text-balance",
                "slop/border-accent-on-rounded", "slop/side-tab", "slop/nested-cards", "slop/gpt-thin-border-wide-shadow"},
    "visuals": {"slop/shape-assembled-illustration", "slop/empty-picture", "slop/photo-wall", "slop/fake-browser-bar",
                "slop/wireframe-page", "slop/counting-device", "slop/repeating-stripes-gradient", "slop/codex-grid-background"},
    "copy": {"unslop/label-trailing-period", "content.lorem-ipsum", "content.placeholder-copy", "slop/fake-send"},
    "layout": {"layout.hero-three-cards"},
}
_SCOPE_PASS = {"color": "color", "system": "color", "type": "type", "layout": "layout", "imagery": "visuals", "motion": "motion",
               "copy": "copy", "content": "copy", "a11y": "details", "perf": "details"}


def pass_of(finding: dict) -> str:
    rid = finding.get("check_id") or ""
    for name, ids in _PASS_OF.items():
        if rid in ids:
            return name
    return _SCOPE_PASS.get(finding.get("scope") or "", "details")


def is_slop(finding: dict) -> bool:
    return finding.get("pack") in SLOP_PACKS or finding.get("check_id") in SLOP_CORE


def _evidence_strings(evidence: Any) -> list[str]:
    if isinstance(evidence, str):
        return [evidence]
    if isinstance(evidence, dict):
        return _evidence_strings(evidence.get("items") or [])
    if isinstance(evidence, (list, tuple)):
        return [str(x) for x in evidence if isinstance(x, (str, int, float))]
    return []


def locate(dom, evidence: Any, limit: int = 6) -> list[list[int]]:
    """Boxes for a finding that names elements by label ("div.card ...", "h1: ..."): the matching elements of one snapshot."""
    if dom is None:
        return []
    out: list[list[int]] = []
    for s in _evidence_strings(evidence)[:limit]:
        head = re.split(r"[\s:,(“]", s.strip(), maxsplit=1)[0]
        if not re.match(r"^[a-z][a-z0-9]*([#.][\w-]+)*$", head):
            continue
        quoted = re.search(r"“([^”]{3,})", s)
        for e in dom.els:
            if e.label() == head and (not quoted or quoted.group(1)[:12] in (e.text or e.snippet(60))):
                b = [int(e.x), int(e.y), int(e.w), int(e.h)]
                if b not in out and e.w > 0 and e.h > 0:
                    out.append(b)
                    break
    return out


def score(findings: list[dict]) -> dict[str, Any]:
    signs: dict[str, dict] = {}
    for f in findings:
        if is_slop(f) and not f.get("waived"):
            signs.setdefault(f["check_id"], f)
    total = sum(WEIGHT.get(f.get("level") or "warning", 9) for f in signs.values())
    value = min(100, total)
    if value >= HEAVY_SCORE or len(signs) >= HEAVY_SIGNS:
        mode = "heavy"
    elif value >= LIGHT_SCORE:
        mode = "light"
    else:
        mode = "none"
    return {"slop_score": value, "signs": len(signs), "mode": mode, "sign_ids": sorted(signs)}


def _step(f: dict) -> dict[str, Any]:
    ev = f.get("evidence")
    return {"rule": f.get("check_id"), "title": f.get("title"), "detail": f.get("detail"), "fix": f.get("fix"), "tier": f.get("tier"),
            "slop": is_slop(f), "items": _evidence_strings(ev)[:6], "widths": (ev or {}).get("widths") if isinstance(ev, dict) else None}


_ORDER = {"floor": 0, "reflex": 1, "finish": 2}


def plan(findings: list[dict], mode: str) -> dict[str, Any]:
    """The fix plan the mode asks for."""
    if mode == "none":
        finish = [f for f in findings if f.get("tier") == "finish"][:3]
        return {"mode": "none", "summary": "No generated-look signs worth a pass: leave the page as it is.",
                "refinements": [_step(f) for f in finish], "passes": []}
    if mode == "light":
        ranked = sorted(findings, key=lambda f: (not is_slop(f), _ORDER.get(f.get("tier"), 3)))
        steps = [_step(f) for f in ranked[:6]]
        return {"mode": "light", "summary": f"A light polish: {len(steps)} changes, no redesign.", "steps": steps, "passes": []}
    passes = []
    for name in PASSES:
        mine = [f for f in findings if pass_of(f) == name]
        if mine:
            mine.sort(key=lambda f: (not is_slop(f), _ORDER.get(f.get("tier"), 3)))
            passes.append({"pass": name, "title": PASS_TITLES[name], "steps": [_step(f) for f in mine]})
    return {"mode": "heavy", "summary": f"A full unslop: {len(passes)} passes in order; render again after each one.", "passes": passes}


def _store(svc) -> Path:
    d = Path(svc.config.data_dir) / "slop-audits"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run(svc, *, render_id: Optional[str] = None, html: Optional[str] = None, url: Optional[str] = None,
        widths: Optional[list[int]] = None, title: str = "", rerender: Optional[bool] = None) -> dict[str, Any]:
    """Audit a stored render (re-rendered at the eight widths when it has fewer than five and its source is at hand) or a
    page given as HTML / URL. The result is kept under data/slop-audits/<render_id>.json."""
    from . import lint as lint_mod
    from .rules.domtree import doms
    t0 = time.monotonic()
    widths = sorted({int(w) for w in (widths or AUDIT_WIDTHS) if 240 <= int(w) <= 2560}) or AUDIT_WIDTHS
    render = None
    if render_id:
        render = svc.get_render(render_id)
        if render is None:
            raise LookupError(f"Unknown render '{render_id}'.")
        _, source = svc._render_lint_inputs(render)
        again = rerender if rerender is not None else len(render.get("widths") or []) < 5
        if again and (source or render.get("url")):
            render = svc.render(html=source or None, url=None if source else render["url"], widths=widths, full_page=True, lint=False,
                                title=render.get("title") or "slop audit")
            render = svc.get_render(render["id"])
    elif html or url:
        # The family's own apps (loopback: 127.0.0.1, localhost, ::1) are captured with the operator profile, as app previews are.
        local = bool(url) and urlparse(url).hostname in LOOPBACK and getattr(svc, "app_browser", None) is not None
        row = svc.render(html=html, url=url, widths=widths, full_page=True, lint=False, title=title or (url or "slop audit")[:120],
                         **({"_browser": svc.app_browser} if local else {}))
        render = svc.get_render(row["id"])
    else:
        raise ValueError("slop audit needs render_id, html or url")
    if (render.get("metrics") or {}).get("error"):
        raise ValueError(f"The page could not be rendered: {render['metrics']['error']}")
    probe, source = svc._render_lint_inputs(render)
    result = lint_mod.run_lint(probe, source, packs=PACKS)
    snaps = {d.width: d for d in doms(probe)}
    shot_widths = [f["width"] for f in render.get("files") or []]
    display = 1440 if 1440 in shot_widths else max([w for w in shot_widths if w <= 1440] or shot_widths or [0])
    findings = []
    for f in result["findings"]:
        f = dict(f)
        f["pass"], f["slop"] = pass_of(f), is_slop(f)
        ev = f.get("evidence")
        if isinstance(ev, dict) and ev.get("boxes"):
            f["boxes"], f["box_width"] = ev["boxes"], ev.get("box_width") or display
        else:
            f["boxes"], f["box_width"] = locate(snaps.get(display), ev), display
        findings.append(f)
    s = score(findings)
    out = {"render_id": render["id"], "title": render.get("title") or "", "url": render.get("url") or "", "widths": shot_widths,
           "display_width": display, "screenshots": [{"width": f["width"], "h": f.get("h"), "file": Path(f["path"]).name}
                                                     for f in render.get("files") or []],
           "findings": findings, **s, "plan": plan(findings, s["mode"]), "rules_run": result.get("rules_run"),
           "by_pass": {p: sum(1 for f in findings if f["pass"] == p) for p in PASSES}, "created_ts": time.time(),
           "ms": round((time.monotonic() - t0) * 1000), "credit": "Sign list and method: unslop by Damir Sokolovsky (CC BY 4.0)."}
    (_store(svc) / f"{render['id']}.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    try:
        svc._emit_event("vitruvius.slop_audit.done", {"render_id": render["id"], "slop_score": s["slop_score"], "mode": s["mode"]})
    except Exception:  # noqa: BLE001
        pass
    return out


def get(svc, render_id: str) -> Optional[dict[str, Any]]:
    path = _store(svc) / f"{render_id}.json"
    if not re.fullmatch(r"[0-9a-f]{6,40}", render_id or "") or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def latest(svc, limit: int = 20) -> list[dict[str, Any]]:
    rows = []
    for p in sorted(_store(svc).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            a = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows.append({k: a.get(k) for k in ("render_id", "title", "url", "slop_score", "mode", "signs", "created_ts")})
    return rows


# ---------------------------------------------------------------------------- the five-line direction

BRIEF_KEYS = ("product", "character", "bright_moment", "signature", "avoid")
_LABELS = {"product": "Product", "character": "Character", "bright_moment": "Bright moment", "signature": "Signature", "avoid": "Avoid"}
TEXT_CAP = 6000

_BRIEF_SYSTEM = """You write a design direction for an existing web page, from its own text. Reply with exactly five lines and nothing else:
Product: what it is and who it is for, in the product's own nouns (one sentence).
Character: the personality the interface should have, drawn from the product's world, not from web trends (one sentence).
Bright moment: the one or two places that earn the accent colour or the motion, and why (one sentence).
Signature: one concrete detail only this product would have (a material, a typographic habit, a unit, an object).
Avoid: the generic moves this page must not make (comma-separated, specific).
No marketing words, no exclamation marks, no emoji."""


def page_text(html: str) -> str:
    body = re.sub(r"(?is)<(script|style|noscript|template|svg)\b.*?</\1>", " ", html or "")
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", html_lib.unescape(body)).strip()


def parse_brief(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        m = re.match(r"^\W*(product|character|bright\s*moment|signature|avoid)\W*[:\-]\s*(.+)$", line.strip(), re.I)
        if m:
            key = re.sub(r"\s+", "_", m.group(1).lower())
            out.setdefault(key, m.group(2).strip().strip("*").strip())
    return out


def fallback_brief(text: str, avoid: list[str], theme: Optional[dict]) -> dict[str, str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if 12 <= len(s.strip()) <= 200]
    product = sentences[0] if sentences else (text[:140] or "A page whose text says too little to name the product.")
    if theme:
        character = f"{theme['name']}: {theme['posture']} {theme['genre']} — {theme['material'][:160]}."
        signature = f"Display set in {theme['display']['face']}, on {theme['paper']['band']} paper."
    else:
        character = "Plain and specific: the product's own objects and numbers carry the page."
        signature = "One recurring object from the product's world, drawn the same way everywhere."
    return {"product": product, "character": character,
            "bright_moment": "The primary action and the one figure that proves the product works; nothing else gets the accent.",
            "signature": signature, "avoid": ", ".join(avoid[:6]) or "purple gradients, glows, emoji icons, centred stacks, three equal cards"}


def direction_brief(svc, *, render_id: Optional[str] = None, html: Optional[str] = None, url: Optional[str] = None,
                    text: Optional[str] = None, use_model: bool = True) -> dict[str, Any]:
    from . import themes as themes_mod
    t0 = time.monotonic()
    source = text or ""
    audit = None
    if not source and render_id:
        render = svc.get_render(render_id)
        if render is None:
            raise LookupError(f"Unknown render '{render_id}'.")
        probe, src = svc._render_lint_inputs(render)
        source = page_text(src or probe.get("html_text") or "")
        audit = get(svc, render_id)
    if not source and html:
        source = page_text(html)
    if not source and url:
        svc.check_url(url)
        source = page_text(svc._fetch_page(url))
    source = (source or "").strip()[:TEXT_CAP]
    if len(source) < 20:
        raise ValueError("The page has too little text to write a direction from (pass text, html, url or a render_id).")
    avoid = [f["title"] for f in (audit or {}).get("findings", []) if f.get("slop")][:6]
    try:
        theme = themes_mod.get(themes_mod.deal(prompt=source[:600], n=1, salt="direction", today="brief")["deal"][0]["slug"])
    except Exception:  # noqa: BLE001
        theme = None
    brief, model, error = {}, None, None
    if use_model and getattr(svc, "link_sync", None) is not None:
        user = f"PAGE TEXT\n{source}" + (f"\n\nSIGNS ALREADY FOUND ON THIS PAGE\n- " + "\n- ".join(avoid) if avoid else "")
        try:
            res = svc.link_sync.chat([{"role": "system", "content": _BRIEF_SYSTEM}, {"role": "user", "content": user}], effort="low")
            reply = getattr(res, "text", None) or (res.get("text") if isinstance(res, dict) else str(res))
            model = getattr(res, "model", None) or (res.get("model") if isinstance(res, dict) else None)
            brief = parse_brief(reply or "")
        except Exception as exc:  # noqa: BLE001 — the brief falls back to the catalogue
            error = f"{type(exc).__name__}: {exc}"[:200]
    got = sum(1 for k in BRIEF_KEYS if brief.get(k))
    complete = got == len(BRIEF_KEYS)
    if not complete:
        fb = fallback_brief(source, avoid, theme)
        brief = {k: brief.get(k) or fb[k] for k in BRIEF_KEYS}
    lines = "\n".join(f"{_LABELS[k]}: {brief[k]}" for k in BRIEF_KEYS)
    return {**{k: brief[k] for k in BRIEF_KEYS}, "text": lines, "source": "model" if complete else ("partial" if got else "fallback"),
            "model": model, "error": error, "theme": themes_mod.public(theme) if theme else None, "render_id": render_id,
            "ms": round((time.monotonic() - t0) * 1000)}
