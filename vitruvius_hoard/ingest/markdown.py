"""Markdown chunker: split by headings, at most ~1200 characters per chunk, with heading breadcrumbs.

The splitting itself is the shared `hoard_link.docs.chunking.chunk_markdown` (front matter, the heading stack
`Guide § Install § Windows`, headings inside code fences left alone, an oversized paragraph cut at a sentence or word break);
this module only reshapes its answer into the rows the ingest stores.
"""

from __future__ import annotations

from typing import Any

from ..hoard_link.docs import chunking

MAX_CHUNK_CHARS = 1200


def chunk_markdown(text: str, *, default_title: str = "") -> dict[str, Any]:
    """Returns {"title": str, "chunks": [{"heading": breadcrumb, "ordinal": int, "text": str, "tokens": int}]}.

    The title is the front matter `title:`, else the first `# Heading`, else `default_title`."""
    source = text or ""
    chunks = chunking.chunk_markdown(source, size=MAX_CHUNK_CHARS, default_title=default_title)
    return {
        "title": chunking.markdown_title(source, default_title) or default_title,
        "chunks": [{"heading": c.section, "ordinal": c.ordinal, "text": c.text, "tokens": max(1, len(c.text) // 4)} for c in chunks],
    }
