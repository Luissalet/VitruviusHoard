"""FTS5 search over the criterion library, and deterministic brief composition."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

from .db import Database

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")

DEFAULT_ANTI_PATTERNS = [
    "Do not default to the generic hero + three feature cards layout.",
    "Do not use Inter/Roboto/Arial as the only font family; pick a distinctive pairing.",
    "Avoid the stock purple-to-blue gradient button.",
    "Avoid near-black text on white paired with an acid-green accent, or cream+terracotta+serif, as the default palette.",
    "Do not leave Lorem ipsum or 'Your Company' placeholder copy in the final page.",
    "Do not disable focus outlines without a :focus-visible replacement.",
]

DEFAULT_CHECKLIST = [
    "Run render_preview at 390/1024/1440 and check for horizontal overflow.",
    "Run design_lint and fix every error-severity finding.",
    "Check text/background contrast is at least 4.5:1 for body text.",
    "Confirm a real content language (no Lorem ipsum, no 'Your Company').",
    "Confirm prefers-reduced-motion is respected.",
    "Confirm the page does not use the default hero+3-cards shape unless asked.",
]


def _quote_token(tok: str) -> str:
    return '"' + tok.replace('"', '""') + '"'


def _fts_query(query: str, mode: str) -> str:
    tokens = _TOKEN_RE.findall(query or "")
    if not tokens:
        return ""
    joiner = " AND " if mode == "and" else " OR "
    return joiner.join(_quote_token(t) for t in tokens)


def _cite(source_id: str, path: str, heading: str) -> str:
    tail = f" § {heading}" if heading else ""
    return f"[vitruvius: {source_id}/{path}{tail}]"


def _chunk_rows(db: Database, ids: list[int], kind: Optional[str], source: Optional[str]) -> dict[int, Any]:
    if not ids:
        return {}
    sql = (
        "SELECT c.id AS chunk_id, c.heading, c.text, d.path, d.kind AS doc_kind, d.source_id, s.license "
        "FROM chunks c JOIN documents d ON d.id = c.document_id JOIN sources s ON s.id = d.source_id "
        f"WHERE c.id IN ({','.join('?' * len(ids))})"
    )
    params: list[Any] = list(ids)
    if kind:
        sql += " AND d.kind = ?"
        params.append(kind)
    if source:
        sql += " AND d.source_id = ?"
        params.append(source)
    return {int(r["chunk_id"]): r for r in db.query(sql, params)}


def search(db: Database, query: str, *, kind: Optional[str] = None, source: Optional[str] = None,
           area: Optional[str] = None, limit: int = 8, dense: Any = None, mode: str = "auto") -> list[dict[str, Any]]:
    """bm25 over FTS5, fused by reciprocal rank with multilingual dense vectors when they exist.

    mode: auto (hybrid when vectors exist, else bm25), hybrid, bm25, dense.
    """
    items: list[dict[str, Any]] = []
    fts_and = _fts_query(query, "and")
    rows: list[Any] = []
    use_dense = dense is not None and mode in ("auto", "hybrid", "dense") and dense.usable()
    if fts_and and mode != "dense":
        sql = (
            "SELECT c.id AS chunk_id, c.heading, c.text, d.path, d.kind AS doc_kind, d.source_id, "
            "s.license, bm25(chunks_fts) AS rank "
            "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
            "JOIN documents d ON d.id = c.document_id JOIN sources s ON s.id = d.source_id "
            "WHERE chunks_fts MATCH ?"
        )
        params: list[Any] = [fts_and]
        if kind:
            sql += " AND d.kind = ?"
            params.append(kind)
        if source:
            sql += " AND d.source_id = ?"
            params.append(source)
        sql += " ORDER BY rank LIMIT ?"
        params.append(max(limit * 3, 30 if use_dense else limit * 3))  # over-fetch: duplicates are folded below
        rows = db.query(sql, params)
        if not rows:
            fts_or = _fts_query(query, "or")
            if fts_or and fts_or != fts_and:
                params[0] = fts_or
                rows = db.query(sql, params)

    by_id = {int(r["chunk_id"]): r for r in rows}
    bm25_ids = [int(r["chunk_id"]) for r in rows]
    dense_ids: list[int] = []
    dense_scores: dict[int, float] = {}
    if use_dense:
        try:
            hits = dense.query(query, k=max(50, limit * 6))
        except Exception:  # noqa: BLE001 - a broken model never breaks keyword search
            hits = []
        missing = [cid for cid, _ in hits if cid not in by_id]
        by_id.update(_chunk_rows(db, missing, kind, source))
        dense_ids = [cid for cid, _ in hits if cid in by_id]
        dense_scores = {cid: sc for cid, sc in hits}

    if dense_ids:
        from .dense import rrf

        order = rrf([bm25_ids, dense_ids] if bm25_ids else [dense_ids])
        bm25_set, dense_set = set(bm25_ids), set(dense_ids)
        for cid, fused in order:
            r = by_id[cid]
            match = "both" if cid in bm25_set and cid in dense_set else ("bm25" if cid in bm25_set else "dense")
            items.append({
                "cite": _cite(r["source_id"], r["path"], r["heading"]),
                "source": r["source_id"], "license": r["license"], "score": round(fused * 1000, 3),
                "text": r["text"], "kind": r["doc_kind"], "heading": r["heading"], "match": match,
                "similarity": round(dense_scores[cid], 3) if cid in dense_scores else None,
            })
    else:
        for r in rows:
            items.append({
                "cite": _cite(r["source_id"], r["path"], r["heading"]),
                "source": r["source_id"],
                "license": r["license"],
                "score": round(-float(r["rank"]), 4),
                "text": r["text"],
                "kind": r["doc_kind"],
                "heading": r["heading"],
                "match": "bm25",
            })

    if area:
        rule_rows = db.query(
            "SELECT source_id, title, text, severity, check_id FROM rules WHERE area = ? LIMIT ?",
            (area, max(0, limit - len(items))),
        )
        for r in rule_rows:
            items.append({
                "cite": f"[vitruvius: {r['source_id']} rule]", "source": r["source_id"], "license": "",
                "score": 0.0, "text": r["text"], "kind": "rule", "heading": r["title"],
                "severity": r["severity"], "check_id": r["check_id"],
            })

    # The same passage vendored twice in a repo (plugin/ and skill/ copies) counts once.
    seen: set[str] = set()
    unique = []
    for item in items:
        key = re.sub(r"\s+", " ", (item.get("text") or "")[:400]).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:limit]


def list_rules(db: Database, *, area: Optional[str] = None, severity: Optional[str] = None,
               source: Optional[str] = None, limit: int = 30) -> list[dict[str, Any]]:
    sql = "SELECT id, source_id, area, severity, title, text, check_id FROM rules WHERE 1=1"
    params: list[Any] = []
    if area:
        sql += " AND area = ?"
        params.append(area)
    if severity:
        sql += " AND severity = ?"
        params.append(severity)
    if source:
        sql += " AND source_id = ?"
        params.append(source)
    sql += " ORDER BY id LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.query(sql, params)]


def _hue_from_text(text: str) -> float:
    digest = hashlib.sha1((text or "").encode("utf-8")).hexdigest()
    return int(digest[:4], 16) % 360


_STOP = {"the", "a", "an", "for", "of", "and", "or", "with", "app", "page", "site", "web", "una", "un", "para", "de", "la",
         "el", "los", "las", "y", "con", "que", "in", "on", "to", "is", "it", "as", "at", "by", "from", "this", "that"}

# Spanish/English synonyms so «sobria», «lujo» or «cálido» find catalog rows written in English.
_SYNONYMS = {
    "calm": ["calm", "serene", "quiet", "minimal", "clean", "soft"], "calma": ["calm", "serene", "quiet"],
    "editorial": ["editorial", "magazine", "serif", "typographic"], "lujo": ["luxury", "premium", "elegant"],
    "luxury": ["luxury", "premium", "elegant"], "sobrio": ["minimal", "clean", "restrained"], "sobria": ["minimal", "clean", "restrained"],
    "oscuro": ["dark", "oled", "night"], "dark": ["dark", "oled", "night"], "juguetón": ["playful", "fun", "colorful"],
    "playful": ["playful", "fun", "colorful", "bold"], "brutalista": ["brutalist", "brutalism", "raw"],
    "brutalist": ["brutalist", "brutalism", "raw"], "cálido": ["warm", "organic", "earth"], "warm": ["warm", "organic", "earth"],
    "tech": ["tech", "futuristic", "cyber", "industrial"], "finanzas": ["finance", "fintech", "banking"],
    "fintech": ["finance", "fintech", "banking"], "finance": ["finance", "fintech", "banking"],
    "tienda": ["ecommerce", "e-commerce", "shop", "retail"], "ecommerce": ["ecommerce", "e-commerce", "shop", "retail"],
    "salud": ["health", "medical", "wellness"], "health": ["health", "medical", "wellness"],
    "portfolio": ["portfolio", "creative", "personal"], "landing": ["landing", "marketing", "hero"],
    "saas": ["saas", "dashboard", "product", "b2b"], "juego": ["gaming", "game"], "gaming": ["gaming", "game"],
    "cripto": ["crypto", "web3"], "crypto": ["crypto", "web3"], "educación": ["education", "learning"],
    "education": ["education", "learning"], "glass": ["glass", "glassmorphism", "frosted"],
    "retro": ["retro", "vintage", "nostalgic"], "neón": ["neon", "cyberpunk"], "neon": ["neon", "cyberpunk"],
}


def _tokens(*parts: Optional[str]) -> list[str]:
    """Lower-case word tokens (≥3 chars) of the given strings, expanded with synonyms."""
    out: list[str] = []
    for part in parts:
        for tok in re.findall(r"[a-záéíóúñü0-9][a-záéíóúñü0-9\-]+", (part or "").lower()):
            if tok in _STOP or len(tok) < 3:
                continue
            out.append(tok)
            out.extend(_SYNONYMS.get(tok, []))
    seen: set[str] = set()
    return [t for t in out if not (t in seen or seen.add(t))]


def _score(tokens: list[str], *fields: Any, weights: Optional[list[float]] = None) -> float:
    """How many query tokens appear in each field (name-ish fields weigh more)."""
    score = 0.0
    for i, field in enumerate(fields):
        text = (json.dumps(field) if not isinstance(field, str) else field).lower()
        w = weights[i] if weights and i < len(weights) else 1.0
        for tok in tokens:
            if tok in text:
                score += w
    return score


def _rank(rows: list[dict], tokens: list[str], fields: list[str], weights: Optional[list[float]] = None,
          limit: int = 3) -> list[dict]:
    scored = [(_score(tokens, *[r.get(f, "") for f in fields], weights=weights), i, r) for i, r in enumerate(rows)]
    scored.sort(key=lambda t: (-t[0], t[1]))
    hits = [r for s, _, r in scored if s > 0]
    return (hits or [r for _, _, r in scored])[:limit]


def _find_styles(db: Database, subject: str, vibe: Optional[str], limit: int = 3,
                 product_type: Optional[str] = None) -> list[dict]:
    rows = [dict(r) for r in db.query("SELECT * FROM styles ORDER BY id")]
    tokens = _tokens(vibe, subject, product_type)
    return _rank(rows, tokens, ["name", "keywords", "description", "best_for", "raw"], [3, 2, 1, 2, 0.5], limit)


def _find_palette(db: Database, product_type: Optional[str], subject: str, vibe: Optional[str] = None) -> dict:
    rows = [dict(r) for r in db.query("SELECT * FROM palettes ORDER BY id")]
    tokens = _tokens(product_type, subject, vibe)
    if rows:
        ranked = _rank(rows, tokens, ["product_type", "name", "notes"], [3, 3, 1], 1)
        if ranked and _score(tokens, ranked[0].get("product_type", ""), ranked[0].get("name", ""), ranked[0].get("notes", "")) > 0:
            return ranked[0]
    from . import tokens as T
    hue = _hue_from_text(subject)
    ramp = T.make_ramp(hue, 0.16)
    return {"id": None, "name": "generated", "product_type": product_type or "", "notes": "generated (no catalog palette available)",
            "colors": [{"role": "primary", "hex": ramp["500"]}, {"role": "primary-dark", "hex": ramp["700"]},
                      {"role": "primary-light", "hex": ramp["200"]}]}


def _find_font_pairing(db: Database, vibe: Optional[str], subject: Optional[str] = None,
                       product_type: Optional[str] = None) -> dict:
    rows = [dict(r) for r in db.query("SELECT * FROM font_pairings ORDER BY id")]
    tokens = _tokens(vibe, product_type, subject)
    if rows:
        return _rank(rows, tokens, ["mood", "notes", "category", "heading", "body"], [3, 2, 1, 1, 1], 1)[0]
    return {"id": None, "heading": "Fraunces", "body": "Inter", "mono": "IBM Plex Mono", "category": "serif+sans",
            "mood": vibe or "", "google_fonts_url": "", "notes": "generated (no catalog font pairing available)"}


def _loads(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return value if value is not None else default


def _clean_style(row: dict) -> dict:
    raw = _loads(row.get("raw"), {}) or {}
    return {"id": row.get("id"), "source_id": row.get("source_id"), "name": row.get("name"), "slug": row.get("slug"),
            "description": row.get("description", ""), "keywords": _loads(row.get("keywords"), []),
            "colors": _loads(row.get("colors"), []), "typography": _loads(row.get("typography"), {}),
            "effects": _loads(row.get("effects"), []), "best_for": _loads(row.get("best_for"), []),
            "avoid": _loads(row.get("avoid"), []), "css_hints": row.get("css_hints", ""),
            "accessibility": raw.get("Accessibility", ""), "performance": raw.get("Performance", ""),
            "era": raw.get("Era/Origin", ""), "complexity": raw.get("Complexity", "")}


def _clean_palette(row: dict) -> dict:
    row = dict(row)
    row["colors"] = _loads(row.get("colors"), [])
    return row


def brief(db: Database, *, subject: str, vibe: Optional[str] = None, product_type: Optional[str] = None,
         platform: Optional[str] = None, mode: str = "marketing", knobs: Optional[dict] = None,
         use_model: bool = False, link: Any = None) -> dict[str, Any]:
    knobs = knobs or {}
    cites: list[str] = []

    styles = [_clean_style(s) for s in _find_styles(db, subject, vibe, product_type=product_type)]
    for s in styles:
        cites.append(f"[vitruvius: {s['source_id']} style/{s['slug']}]")

    palette = _clean_palette(_find_palette(db, product_type, subject, vibe))
    if palette.get("id") is not None:
        cites.append(f"[vitruvius: {palette['source_id']} palette/{palette['name']}]")

    font_pairing = _find_font_pairing(db, vibe, subject, product_type)
    if font_pairing.get("id") is not None:
        cites.append(f"[vitruvius: {font_pairing['source_id']} fonts/{font_pairing['heading']}+{font_pairing['body']}]")

    areas = ["typography", "color", "layout", "motion", "a11y"] if mode == "marketing" else \
        ["typography", "color", "layout", "motion", "a11y", "forms"]
    rules: list[dict] = []
    subject_tokens = _tokens(subject, vibe, product_type, platform)
    for area in areas:
        pool = [dict(r) for r in db.query(
            "SELECT id, source_id, area, severity, title, text, check_id FROM rules WHERE area = ? ORDER BY "
            "CASE WHEN source_id IN ('hyperframes', 'bang-motion', 'nullmotion', 'claude-design-skillstack') THEN 1 ELSE 0 END, "
            "CASE severity WHEN 'error' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, length(text) DESC", (area,))]
        # Relevant to the brief first, then the strongest general rules of the area.
        relevant = _rank(pool, subject_tokens, ["title", "text"], [2, 1], 2) if subject_tokens else []
        picked = [r for r in relevant if _score(subject_tokens, r["title"], r["text"]) > 0]
        for r in pool:
            if len(picked) >= 2:
                break
            if r not in picked:
                picked.append(r)
        rules.extend(picked)
    rules = rules[:12]
    for r in rules:
        cites.append(f"[vitruvius: {r['source_id']} rule/{r['id']}]")

    motion_chunks = search(db, "motion easing duration reduced motion", limit=4)
    for c in motion_chunks:
        cites.append(c["cite"])

    anti_patterns = list(DEFAULT_ANTI_PATTERNS)
    generic_rules = db.query(
        "SELECT source_id, id, text FROM rules WHERE lower(title) LIKE '%generic%' OR lower(title) LIKE '%avoid%' LIMIT 6"
    )
    for r in generic_rules:
        anti_patterns.append(r["text"])
        cites.append(f"[vitruvius: {r['source_id']} rule/{r['id']}]")

    result: dict[str, Any] = {
        "subject": subject, "vibe": vibe, "product_type": product_type, "platform": platform, "mode": mode,
        "styles": styles, "palette": palette, "font_pairing": font_pairing, "rules": rules,
        "motion_guidance": motion_chunks, "anti_patterns": anti_patterns[:10], "checklist": list(DEFAULT_CHECKLIST),
        "cites": sorted(set(cites)),
    }

    if use_model and link is not None:
        try:
            prompt = (f"Write a 150-word art direction paragraph for a {mode} {product_type or 'page'} about "
                     f"'{subject}', vibe '{vibe or 'unspecified'}', platform '{platform or 'web'}'. "
                     f"Reference the chosen style names ({', '.join(s['name'] for s in styles) or 'n/a'}), "
                     f"the palette and the font pairing. Plain prose, no headings.")
            chat_result = link.chat([{"role": "user", "content": prompt}])
            result["direction"] = getattr(chat_result, "text", None) or (
                chat_result.get("text") if isinstance(chat_result, dict) else str(chat_result))
        except Exception as error:  # noqa: BLE001
            result["direction"] = None
            result["direction_error"] = str(error)

    return result
