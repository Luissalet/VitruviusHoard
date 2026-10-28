"""`critique()` = lint + (optional) vision model critique, merged and deduped."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from . import review as review_mod
from . import waivers as waivers_mod
from .lint import run_lint, score_of

RUBRIC_AREAS = ["hierarchy", "typography", "color", "spacing", "motion", "distinctiveness", "a11y", "content"]

_VISION_PROMPT = """You are a senior visual designer critiquing a rendered web page from screenshots.
Rubric: hierarchy, typography, colour, spacing/rhythm, motion, distinctiveness vs generic AI output,
accessibility, copy. Reply with ONLY a JSON object:
{"score": 0-10, "findings": [{"area": "...", "severity": "info|warn|error", "title": "...", "detail": "...", "fix": "..."}],
 "summary": "...", "direction": "..."}
Say what to change, not just what is wrong."""


def vision_prompt() -> str:
    """The rubric plus the judged rules (the registry's `visual` pack): the model may cite one by id in `rule`."""
    from .lint import ensure_rules
    from .rules.registry import list_rules
    ensure_rules()
    judged = list_rules(engine="visual")
    if not judged:
        return _VISION_PROMPT
    lines = "\n".join(f"- {r['id']}: {r['description']}" for r in judged)
    return (_VISION_PROMPT + "\n\nJudged rules. Only when one clearly applies, cite its id in a finding's `rule` field "
            "(and say what you saw in `detail`); never cite one you cannot point to on the screenshots:\n" + lines)


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


def _vision_findings(parsed: dict) -> list[dict]:
    from .rules.registry import enrich, get_rule, make_finding
    out = []
    for f in parsed.get("findings", []) or []:
        if not isinstance(f, dict):
            continue
        rule = get_rule(str(f.get("rule") or ""))
        if rule is not None and rule.engine == "visual":
            item = make_finding(rule.id, str(f.get("detail") or rule.description), None, f.get("fix") or None, f.get("title") or None)
            out.append(item)
            continue
        out.append({"check_id": None, "area": f.get("area", "content"), "severity": f.get("severity", "info"), "title": f.get("title", ""),
                    "detail": f.get("detail", ""), "evidence": None, "fix": f.get("fix", ""), "engine": "visual", "tier": "finish", "level": "advisory",
                    "judged": True})
    return out


def critique(*, probe: dict, html: str, focus: Optional[str] = None, images: Optional[list[bytes]] = None,
             link: Any = None, use_vision: bool = True, tokens: Optional[dict] = None, waivers: Any = None,
             prior_waivers: Optional[dict[str, str]] = None, clean_review: bool = False) -> dict[str, Any]:
    """Lint (all registered rules; ``tokens`` switches on the design-system rules) merged with an optional vision pass.

    ``waivers`` are validated (``waivers.validate``) and applied to Reflex findings. The result carries the tier gate and, with
    ``clean_review``, the verdict of a fresh-context model call (``review.run``). ``link`` is a Link-like object with a sync ``.chat``.
    """
    t0 = time.monotonic()
    lint_result = run_lint(probe, html, tokens=tokens)
    findings = list(lint_result["findings"])
    vision_model = None
    vision_summary = ""
    vision_score = None

    if use_vision and link is not None and images:
        try:
            messages = [
                {"role": "system", "content": vision_prompt()},
                {"role": "user", "content": f"Focus: {focus or 'overall quality'}. Rate and critique this page."},
            ]
            result = link.chat(messages, images=images, effort="high")
            text = result.text if hasattr(result, "text") else (result.get("text") if isinstance(result, dict) else str(result))
            model = getattr(result, "model", None) or (result.get("model") if isinstance(result, dict) else None)
            parsed = _extract_json(text or "")
            if parsed:
                vision_model = model
                vision_score = parsed.get("score")
                vision_summary = parsed.get("summary", "")
                findings.extend(_vision_findings(parsed))
        except Exception as error:  # noqa: BLE001 — vision is best-effort
            vision_summary = f"(vision critique unavailable: {type(error).__name__}: {error})"

    findings = _dedupe(findings)
    checked = waivers_mod.validate(waivers, findings, prior_waivers)
    waivers_mod.apply(findings, checked["accepted"])
    gate = waivers_mod.gate(findings)
    heuristic_score = score_of(findings)
    if vision_score is not None:
        try:
            score = round((float(vision_score) + heuristic_score) / 2, 2)
        except (TypeError, ValueError):
            score = heuristic_score
    else:
        score = heuristic_score

    review = None
    if clean_review:
        review = review_mod.run(link if use_vision or clean_review else None, images=images or [], html=html, findings=findings)
        if review.get("verdict") in ("recapture", "rebuild") and gate["state"] == "pass":
            gate = {**gate, "state": "fix", "blocking": [*gate["blocking"], f"review:{review['verdict']}"]}

    open_n = gate["floor"] + gate["reflex_open"]
    summary = vision_summary or (
        f"{len(findings)} finding(s) ({gate['floor']} floor, {gate['reflex_open']} reflex open, {gate['reflex_waived']} waived, {gate['finish']} finish); "
        f"heuristic score {heuristic_score}/10."
        if findings else f"No issues found by the deterministic checks; heuristic score {heuristic_score}/10."
    )
    return {
        "score": score,
        "heuristic_score": heuristic_score,
        "vision_model": vision_model,
        "findings": findings,
        "summary": summary,
        "gate": gate,
        "ship_ready": gate["state"] == "pass",
        "open": open_n,
        "waivers": checked,
        "review": review,
        "design_system": bool(tokens),
        "rules_run": lint_result.get("rules_run"),
        "ms": round((time.monotonic() - t0) * 1000, 1),
    }
