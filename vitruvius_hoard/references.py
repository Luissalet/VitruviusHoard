"""The reference gallery: capture, palette extraction, FTS search, similarity."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .db import Database

_META_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE)
_META_OG_RE = re.compile(r'<meta[^>]+property=["\']og:(\w+)["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE)


_GENERIC_FAMILIES = {"sans-serif", "serif", "monospace", "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace",
                     "-apple-system", "blinkmacsystemfont", "cursive", "fantasy"}


def _font_names(fonts: dict[str, Any]) -> list[str]:
    """Distinct family names actually used: the first family of each computed stack plus the loaded faces
    (in that order), without quotes or the generic fallbacks."""
    out: list[str] = []

    def add(name: str) -> None:
        name = (name or "").strip().strip("'\"").strip()
        if name and name.lower() not in _GENERIC_FAMILIES and name not in out:
            out.append(name)

    for key in ("h1", "h2", "p", "body", "button"):
        add((fonts.get(key) or "").split(",")[0])
    for name in fonts.get("loaded") or []:
        add(name)
    return out[:12]


def _meta_from_html(html: str) -> dict[str, Any]:
    title_m = _META_TITLE_RE.search(html or "")
    desc_m = _META_DESC_RE.search(html or "")
    og = {m.group(1): m.group(2) for m in _META_OG_RE.finditer(html or "")}
    return {"title": (title_m.group(1).strip() if title_m else ""), "description": (desc_m.group(1) if desc_m else ""), "og": og}


def extract_palette(image_path: str, n: int = 6) -> list[str]:
    """Pillow quantize(n) on the image, dropping near-white/near-black unless they dominate."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return []
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((300, 300))
        quantized = img.quantize(colors=max(2, n + 4))
        palette = quantized.getpalette() or []
        counts = quantized.getcolors() or []
        counts.sort(key=lambda c: -c[0])
        total = sum(c for c, _ in counts) or 1
        out = []
        for count, idx in counts:
            r, g, b = palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2]
            is_near_white = r > 240 and g > 240 and b > 240
            is_near_black = r < 15 and g < 15 and b < 15
            share = count / total
            if (is_near_white or is_near_black) and share < 0.3:
                continue
            hex_ = "#{:02x}{:02x}{:02x}".format(r, g, b)
            # Merge colours that read as the same swatch (Δ < 28 in RGB).
            if any(abs(r - int(o[1:3], 16)) + abs(g - int(o[3:5], 16)) + abs(b - int(o[5:7], 16)) < 28 for o in out):
                continue
            out.append(hex_)
            if len(out) >= n:
                break
        return out
    except Exception:  # noqa: BLE001
        return []


def add(db: Database, browser: Any, config: Any, *, url: Optional[str] = None, html: Optional[str] = None,
       tags: Optional[list[str]] = None, note: str = "", video: bool = True, analyze: bool = True,
       link: Any = None, source_id: Optional[str] = None) -> dict[str, Any]:
    if not url and not html:
        raise ValueError("reference_add needs a url or html")
    ref_id = uuid.uuid4().hex[:12]
    out_dir = Path(config.references_dir) / ref_id
    out_dir.mkdir(parents=True, exist_ok=True)

    desktop = browser.capture(html=html, url=url, widths=[1440], full_page=True, record=video, out_dir=out_dir / "desktop")
    mobile = browser.capture(html=html, url=url, widths=[390], full_page=True, record=False, out_dir=out_dir / "mobile")

    files: dict[str, Any] = {}
    if desktop.get("files"):
        files["desktop"] = desktop["files"][0]["path"]
    if mobile.get("files"):
        files["mobile"] = mobile["files"][0]["path"]
    if desktop.get("video"):
        files["video"] = desktop["video"]
    if desktop.get("poster"):
        files["poster"] = desktop["poster"]

    probe = desktop.get("probe") or {}
    fonts = _font_names(probe.get("fonts") or {})
    libs = probe.get("external_libs") or []
    motion = {
        "animations": probe.get("animations_count") or 0,
        "transitions": probe.get("long_transition_count") or 0,
        "scroll_driven": probe.get("scroll_driven_count") or 0,
        "reduced_motion_respected": bool(probe.get("reduced_motion_css_present")),
    }
    meta = _meta_from_html(html or "")
    page_meta = probe.get("page_meta") or {}
    if not meta.get("title"):
        meta["title"] = page_meta.get("title") or page_meta.get("og_title") or ""
    if not meta.get("description"):
        meta["description"] = page_meta.get("description") or ""
    palette = extract_palette(files.get("desktop"), n=8) if files.get("desktop") else []

    analysis: dict[str, Any] = {}
    vibe = ""
    tag_list = list(tags or [])
    if analyze and link is not None and files.get("desktop"):
        try:
            image_bytes = Path(files["desktop"]).read_bytes()
            chat_result = link.chat(
                [{"role": "user", "content": "Describe this web page's visual vibe in one short phrase, and suggest 3 tags."}],
                images=[image_bytes],
            )
            text = getattr(chat_result, "text", None) or (chat_result.get("text") if isinstance(chat_result, dict) else "")
            analysis = {"raw": text}
            vibe = (text or "").strip().split("\n")[0][:120]
        except Exception as error:  # noqa: BLE001
            analysis = {"error": str(error)}

    row = {
        "id": ref_id, "created_ts": time.time(), "url": url or "", "title": meta.get("title") or (url or "local html"),
        "description": meta.get("description") or "", "tags": tag_list, "note": note, "vibe": vibe,
        "files": files, "palette": palette, "fonts": fonts, "libs": libs, "motion": motion,
        "analysis": analysis, "source_id": source_id,
    }
    db.execute(
        "INSERT INTO references_t(id, created_ts, url, title, description, tags, note, vibe, files, palette, fonts, libs, motion, analysis, source_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (row["id"], row["created_ts"], row["url"], row["title"], row["description"], json.dumps(tag_list),
         row["note"], row["vibe"], json.dumps(files), json.dumps(palette), json.dumps(fonts), json.dumps(libs),
         json.dumps(motion), json.dumps(analysis), source_id),
    )
    return row


def _row_to_dict(r) -> dict[str, Any]:
    return {
        "id": r["id"], "created_ts": r["created_ts"], "url": r["url"], "title": r["title"],
        "description": r["description"], "tags": json.loads(r["tags"] or "[]"), "note": r["note"], "vibe": r["vibe"],
        "files": json.loads(r["files"] or "{}"), "palette": json.loads(r["palette"] or "[]"),
        "fonts": json.loads(r["fonts"] or "[]"), "libs": json.loads(r["libs"] or "[]"),
        "motion": json.loads(r["motion"] or "{}"), "analysis": json.loads(r["analysis"] or "{}"),
        "source_id": r["source_id"],
    }


def get(db: Database, ref_id: str) -> Optional[dict[str, Any]]:
    row = db.one("SELECT * FROM references_t WHERE id = ?", (ref_id,))
    return _row_to_dict(row) if row else None


def delete(db: Database, ref_id: str) -> bool:
    cur = db.execute("DELETE FROM references_t WHERE id = ?", (ref_id,))
    return cur.rowcount > 0


def search(db: Database, *, query: Optional[str] = None, tags: Optional[list[str]] = None,
          vibe: Optional[str] = None, lib: Optional[str] = None, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[Any]
    if query:
        tokens = re.findall(r"[A-Za-z0-9_]+", query)
        fts = " OR ".join(f'"{t}"' for t in tokens) if tokens else ""
        if fts:
            rows = db.query(
                "SELECT r.* FROM references_fts f JOIN references_t r ON r.rowid = f.rowid WHERE references_fts MATCH ? ORDER BY r.created_ts DESC LIMIT ?",
                (fts, limit * 3),
            )
        else:
            rows = db.query("SELECT * FROM references_t ORDER BY created_ts DESC LIMIT ?", (limit * 3,))
    else:
        rows = db.query("SELECT * FROM references_t ORDER BY created_ts DESC LIMIT ?", (limit * 3,))

    items = [_row_to_dict(r) for r in rows]
    if tags:
        wanted = set(t.lower() for t in tags)
        items = [it for it in items if wanted & set(t.lower() for t in it["tags"])]
    if vibe:
        items = [it for it in items if vibe.lower() in (it["vibe"] or "").lower()]
    if lib:
        items = [it for it in items if lib.lower() in [l.lower() for l in it["libs"]]]
    return items[:limit]


def similar(db: Database, ref_id: str, limit: int = 6) -> list[dict[str, Any]]:
    base = get(db, ref_id)
    if not base:
        return []
    candidates = [r for r in [_row_to_dict(row) for row in db.query("SELECT * FROM references_t WHERE id != ?", (ref_id,))]]

    def score(item: dict) -> float:
        s = 0.0
        s += len(set(item["tags"]) & set(base["tags"])) * 2
        s += len(set(item["fonts"]) & set(base["fonts"]))
        s += len(set(f["hex"] if isinstance(f, dict) else f for f in item["palette"]) &
                set(f["hex"] if isinstance(f, dict) else f for f in base["palette"]))
        return s

    candidates.sort(key=score, reverse=True)
    return candidates[:limit]


def import_demos(db: Database, browser: Any, config: Any, source_id: str, *, link: Any = None) -> dict[str, Any]:
    """Import local HTML demo files from an ingested source as reference-gallery entries."""
    root = Path(config.sources_dir) / source_id
    if not root.is_dir():
        return {"ok": False, "error": "source not ingested", "count": 0}
    count = 0
    for html_path in sorted(root.rglob("*.html"))[:40]:
        try:
            html = html_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tags = [source_id, html_path.parent.name]
        add(db, browser, config, html=html, tags=tags, note=f"imported from {html_path.name}",
            video=False, analyze=False, link=link, source_id=source_id)
        count += 1
    return {"ok": True, "count": count}
