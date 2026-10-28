"""The clean-context final review.

A fresh call to the global model that has seen none of the conversation that built the page: only the screenshots, the page's
HTML and the list of findings. The first word of its answer is the verdict (``recapture`` | ``rebuild`` | ``fix`` | ``ship``) and
it lists at most eight findings.
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

VERDICTS = ("recapture", "rebuild", "fix", "ship")
MAX_FINDINGS = 8
HTML_CAP = 28_000

_SYSTEM = """You are reviewing a web page you have never seen. You are given only screenshots of it at several widths, its HTML and a list of
automatic findings. You know nothing about who made it or why, and you must not assume anything beyond what is in front of you.

Reply in this form and nothing else:
Line 1: exactly one word: recapture, rebuild, fix or ship.
  recapture = the screenshots do not show the page (blank, an error, a loader, cut off): take them again.
  rebuild   = the concept or structure fails; patching will not save it.
  fix       = it stands, and specific changes would make it good.
  ship      = nothing blocks it.
Then at most 8 lines, one finding each, in the form: `- <area>: <what is wrong, or what must not change> -> <the change>`.
Judge hierarchy, whether the first screen says what the page is for, type and colour choices that look like a template, copy that
says nothing, and anything the findings list missed. Do not repeat a finding for the sake of it."""


def _digest(findings: list[dict], limit: int = 40) -> str:
    rows = []
    for f in findings[:limit]:
        tag = f.get("tier") or f.get("severity") or "?"
        waived = " (waived: " + str(f.get("waiver_reason", ""))[:80] + ")" if f.get("waived") else ""
        rows.append(f"- [{tag}] {f.get('check_id') or f.get('area')}: {f.get('title')} - {str(f.get('detail') or '')[:160]}{waived}")
    return "\n".join(rows) or "(none)"


def parse(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    first = re.match(r"\W*([A-Za-z]+)", text)
    verdict = first.group(1).lower() if first and first.group(1).lower() in VERDICTS else None
    parsed = True
    if verdict is None:
        parsed = False
        head = text[:120].lower()
        verdict = next((v for v in VERDICTS if v in head), "fix")
    findings = []
    for line in text.splitlines()[1:]:
        m = re.match(r"^\s*(?:[-*•]|\d+[.)])\s*(.+)$", line)
        if m:
            findings.append(m.group(1).strip())
    return {"verdict": verdict, "findings": findings[:MAX_FINDINGS], "verdict_parsed": parsed}


def run(link: Any, *, images: list[bytes], html: str, findings: list[dict]) -> dict[str, Any]:
    """One fresh call: no history, no system prompt from the build. ``link`` has a sync ``chat``."""
    t0 = time.monotonic()
    if link is None:
        return {"verdict": None, "findings": [], "error": "the global model is not reachable", "model": None, "ms": 0}
    if not images:
        return {"verdict": "recapture", "findings": ["There are no screenshots to review: render the page first."], "model": None, "ms": 0}
    body = (html or "")[:HTML_CAP]
    truncated = len(html or "") > HTML_CAP
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"AUTOMATIC FINDINGS\n{_digest(findings)}\n\nHTML{' (truncated)' if truncated else ''}\n```html\n{body}\n```"},
    ]
    try:
        result = link.chat(messages, images=images, effort="high")
    except Exception as error:  # noqa: BLE001 — the review is best-effort
        return {"verdict": None, "findings": [], "error": f"review unavailable: {type(error).__name__}: {error}", "model": None, "ms": round((time.monotonic() - t0) * 1000, 1)}
    text = result.text if hasattr(result, "text") else (result.get("text") if isinstance(result, dict) else str(result))
    model = getattr(result, "model", None) or (result.get("model") if isinstance(result, dict) else None)
    return {**parse(text or ""), "model": model, "images": len(images), "ms": round((time.monotonic() - t0) * 1000, 1)}
