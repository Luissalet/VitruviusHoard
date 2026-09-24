"""Markdown chunker: split by headings, ≤ ~1200 chars per chunk with heading breadcrumbs."""

from __future__ import annotations

import re
from typing import Any

MAX_CHUNK_CHARS = 1200
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw = m.group(1)
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip().lower()] = v.strip().strip('"').strip("'")
    return meta, text[m.end():]


def _split_paragraphs(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text] if text.strip() else []
    paras = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    current = ""
    for p in paras:
        candidate = (current + "\n\n" + p) if current else p
        if len(candidate) > limit and current:
            chunks.append(current)
            current = p
        else:
            current = candidate
        while len(current) > limit:
            chunks.append(current[:limit])
            current = current[limit:]
    if current.strip():
        chunks.append(current)
    return chunks


def chunk_markdown(text: str, *, default_title: str = "") -> dict[str, Any]:
    """Returns {"title": str, "chunks": [{"heading": breadcrumb, "ordinal": int, "text": str, "tokens": int}]}."""
    meta, body = _parse_frontmatter(text or "")
    title = meta.get("title") or default_title

    lines = body.splitlines()
    sections: list[tuple[list[str], str]] = []  # (breadcrumb_stack, content)
    stack: list[str] = []
    current_lines: list[str] = []
    first_h1_seen = False

    def flush():
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((list(stack), content))

    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            flush()
            current_lines = []
            level = len(m.group(1))
            text_h = m.group(2).strip()
            if level == 1 and not title:
                title = text_h
            if level == 1:
                first_h1_seen = True
            stack = stack[: level - 1]
            while len(stack) < level - 1:
                stack.append("")
            if len(stack) >= level:
                stack = stack[: level - 1]
            stack.append(text_h)
        else:
            current_lines.append(line)
    flush()

    if not sections and body.strip():
        sections = [([], body.strip())]

    chunks = []
    ordinal = 0
    for breadcrumb, content in sections:
        pieces = _split_paragraphs(content, MAX_CHUNK_CHARS)
        for piece in pieces:
            heading = " § ".join(b for b in breadcrumb if b) or (title or "")
            chunks.append({
                "heading": heading,
                "ordinal": ordinal,
                "text": piece.strip(),
                "tokens": max(1, len(piece) // 4),
            })
            ordinal += 1

    return {"title": title or default_title, "chunks": chunks}
