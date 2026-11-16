"""Cold web-guide controls on the software host and the MCP catalogue (available with every module OFF)."""
from __future__ import annotations

import asyncio

NAMES = {"web_guide_search", "web_guide_read", "web_legacy_scan"}


def catalog(control):
    string = {"type": "string"}
    return [
        control("web_guide_search", "Find modern web platform guides (dialog, popover, anchor positioning, view transitions, container queries, scroll-driven animation, forms, accessibility, performance, security...). "
                "Buscar guías de la plataforma web moderna. 2-5 word query in English or Spanish; empty lists everything. Returns ids to read with web_guide_read. Available with modules OFF.",
                {"query": string, "category": string, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, read=True),
        control("web_guide_read", "Read one or more web guides in full (comma-separated ids from web_guide_search). Leer guías web con código y alternativas de compatibilidad.",
                {"ids": string}, ("ids",), True),
        control("web_legacy_scan", "Scan a front-end folder, a file or inline sources for older patterns that a native web feature now replaces (float layouts, div modals, click-outside scripts, jQuery animation, "
                "scroll listeners, moment.js, ...). Each finding names the guide with the native alternative and when the old pattern is still right. Buscar patrones antiguos en un frontend. Read-only.",
                {"path": string, "sources": {"type": "array", "items": {"type": "object", "properties": {"name": string, "text": string}, "required": ["text"]}},
                 "include_vendor": {"type": "boolean"}, "max_files": {"type": "integer", "minimum": 1, "maximum": 5000}}, read=True),
    ]


async def execute(runtime, name, arguments):
    from . import legacy, listing, read, search
    if name == "web_guide_search":
        if not arguments.get("query") and not arguments.get("category"):
            return listing()
        return search(arguments.get("query", ""), arguments.get("category"), arguments.get("limit", 8))
    if name == "web_guide_read":
        return read(arguments["ids"])
    if arguments.get("sources"):
        return legacy.scan_sources(arguments["sources"])
    if not arguments.get("path"):
        raise ValueError("Give a path or inline sources")
    return await asyncio.to_thread(legacy.scan_path, arguments["path"], max_files=arguments.get("max_files", 600), include_vendor=bool(arguments.get("include_vendor")))
