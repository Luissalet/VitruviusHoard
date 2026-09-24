"""`critique()` = lint + (optional) vision model critique, merged and deduped."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from .lint import run_lint

RUBRIC_AREAS = ["hierarchy", "typography", "color", "spacing", "motion", "distinctiveness", "a11y", "content"]

_VISION_PROMPT = """You are a senior visual designer critiquing a rendered web page from screenshots.
Rubric: hierarchy, typography, colour, spacing/rhythm, motion, distinctiveness vs generic AI output,
accessibility, copy. Reply with ONLY a JSON object:
{"score": 0-10, "findings": [{"area": "...", "severity": "info|warn|error", "title": "...", "detail": "...", "fix": "..."}],
 "summary": "...", "direction": "..."}
Say what to change, not just what is wrong."""


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except ValueError:
        depth = 0
        for i, ch in enumerate(candidate):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(candidate[: i + 1])
                    except ValueError:
                        return None
        return None


def _dedupe(findings: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for f in findings:
        key = (f.get("area"), (f.get("title") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def critique(*, probe: dict, html: str, focus: Optional[str] = None, images: Optional[list[bytes]] = None,
             link: Any = None, use_vision: bool = True) -> dict[str, Any]:
    """``link`` is a hoard_link.Link-like object with a sync ``.chat`` or None."""
    t0 = time.monotonic()
    lint_result = run_lint(probe, html)
    heuristic_score = lint_result["score"]
    findings = list(lint_result["findings"])
    vision_model = None
    vision_summary = ""
    vision_score = None

    if use_vision and link is not None and images:
        try:
            messages = [
                {"role": "system", "content": _VISION_PROMPT},
                {"role": "user", "content": f"Focus: {focus or 'overall quality'}. Rate and critique this page."},
            ]
            result = link.chat(messages, images=images)
            text = result.text if hasattr(result, "text") else (result.get("text") if isinstance(result, dict) else str(result))
            model = getattr(result, "model", None) or (result.get("model") if isinstance(result, dict) else None)
            parsed = _extract_json(text or "")
            if parsed:
                vision_model = model
                vision_score = parsed.get("score")
                vision_summary = parsed.get("summary", "")
                for f in parsed.get("findings", []) or []:
                    findings.append({
                        "check_id": None, "area": f.get("area", "content"), "severity": f.get("severity", "info"),
                        "title": f.get("title", ""), "detail": f.get("detail", ""), "evidence": None,
                        "fix": f.get("fix", ""),
                    })
        except Exception as error:  # noqa: BLE001 — vision is best-effort
            vision_summary = f"(vision critique unavailable: {error})"

    findings = _dedupe(findings)
    if vision_score is not None:
        try:
            score = round((float(vision_score) + heuristic_score) / 2, 2)
        except (TypeError, ValueError):
            score = heuristic_score
    else:
        score = heuristic_score

    summary = vision_summary or (
        f"{len(findings)} finding(s); heuristic score {heuristic_score}/10."
        if findings else f"No issues found by the deterministic checks; heuristic score {heuristic_score}/10."
    )

    return {
        "score": score,
        "heuristic_score": heuristic_score,
        "vision_model": vision_model,
        "findings": findings,
        "summary": summary,
        "ms": round((time.monotonic() - t0) * 1000, 1),
    }
