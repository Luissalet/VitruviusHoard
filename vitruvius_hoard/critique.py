"""`critique()` = lint + (optional) vision model critique, merged and deduped."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from . import review as review_mod
from . import waivers as waivers_mod
from .lint import run_lint, score_of
from .rules.critique_checks import PATTERN_WEIGHTS

DEFAULT_TIMEOUT_S = 110
TIMEOUT_DESCRIPTION = ("Budget in seconds for optional model work. Default 110 leaves time for the reply under the Hub's "
                       "120-second limit. If the budget expires, deterministic findings still return.")

_REVIEW_WEIGHTS = {
    "font.generic-only": 2.65,
    "webcraft/native-control-chrome": 1.65,
    "webcraft/scaffold-copy": 1.3,
}


def _with_review_weights(findings: list[dict]) -> list[dict]:
    """Use calibrated penalty points while leaving lint and the shipping gate intact."""
    weighted = []
    default_faces = any(f.get("check_id") == "font.generic-only" and not f.get("waived") for f in findings)
    for finding in findings:
        rule = finding.get("check_id")
        weight = _REVIEW_WEIGHTS.get(rule)
        if rule == "webcraft/category-composition":
            patterns = (finding.get("evidence") or {}).get("patterns") or []
            weight = max((PATTERN_WEIGHTS.get(pattern["kind"], 0) for pattern in patterns), default=None)
        elif rule == "unslop/single-default-sans" and default_faces:
            weight = 0
        weighted.append({**finding, "score_weight": weight} if weight is not None else finding)
    return weighted


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


def _visual_score(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return score if 0 <= score <= 10 else None


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


def _guidance(findings: list[dict], focus: Optional[str]) -> tuple[list[dict], list[dict]]:
    """Guides (older patterns found in the page) and craft references (textures, dashboard rules) a critique points at, with their cites."""
    guides: dict[str, dict] = {}
    for f in findings:
        evidence = f.get("evidence")
        if f.get("check_id") == "webcraft/legacy-pattern" and isinstance(evidence, dict) and evidence.get("guide"):
            row = guides.setdefault(evidence["guide"], {"guide": evidence["guide"], "cite": evidence["cite"], "patterns": []})
            row["patterns"].append(evidence["rule"])
    try:
        from . import craft
        references = craft.related(findings, focus)
    except Exception:  # noqa: BLE001 — the references never fail a critique
        references = []
    return list(guides.values()), references


def _keyboard_summary(probe: dict, findings: list[dict]) -> Optional[dict]:
    """What the Tab walk measured and how many interaction findings stand (None when the capture took no measurement)."""
    data = (probe or {}).get("keyboard")
    if not isinstance(data, dict) or data.get("error"):
        return None
    mine = [f for f in findings if str(f.get("check_id") or "").startswith("interaction/") and not f.get("waived")]
    return {"tab_stops": data.get("tab_stops", 0), "focusable": data.get("focusable", 0), "complete": bool(data.get("complete")),
            "pointer_only": len(data.get("pointer_only") or []), "unreached": len(data.get("unreached") or []),
            "without_focus_ring": sum(1 for s in data.get("stops") or [] if s.get("ring") is False), "open_findings": len(mine),
            "rules": sorted({f["check_id"] for f in mine})}


def critique(*, probe: dict, html: str, focus: Optional[str] = None, images: Optional[list[bytes]] = None,
             link: Any = None, use_vision: bool = True, tokens: Optional[dict] = None, waivers: Any = None,
             prior_waivers: Optional[dict[str, str]] = None, clean_review: bool = False,
             deadline: Optional[float] = None, capture_truncation: Optional[list[dict]] = None) -> dict[str, Any]:
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
    vision = {"status": "not_requested"}
    capture_note = ""
    if capture_truncation:
        dimensions = ", ".join(
            f"{file['width']} px wide: top {file['captured_height']} of {file['page_height']} px"
            for file in capture_truncation
        )
        capture_note = f"\nScreenshots cropped ({dimensions}). Treat the uncaptured regions as unobserved."

    if use_vision and not images:
        vision = {"status": "unavailable", "reason": "no_screenshots"}
    elif use_vision and link is None:
        vision = {"status": "unavailable", "reason": "no_model"}
    elif use_vision:
        try:
            messages = [
                {"role": "system", "content": vision_prompt()},
                {"role": "user", "content": f"Focus: {focus or 'overall quality'}. Rate and critique this page.{capture_note}"},
            ]
            result = review_mod.chat_before_deadline(link, messages, images, deadline)
            text = result.text if hasattr(result, "text") else (result.get("text") if isinstance(result, dict) else str(result))
            model = getattr(result, "model", None) or (result.get("model") if isinstance(result, dict) else None)
            parsed = _extract_json(text or "")
            score = _visual_score(parsed.get("score")) if parsed else None
            if score is not None:
                findings.extend(_vision_findings(parsed))
                vision_model = model
                vision_score = score
                vision_summary = parsed.get("summary", "")
                vision = {"status": "complete"}
            else:
                vision = {"status": "unavailable", "reason": "invalid_score" if parsed else "invalid_response"}
        except TimeoutError:
            vision = {"status": "timed_out"}
        except Exception as error:  # noqa: BLE001 — vision is best-effort
            vision_summary = f"(vision critique unavailable: {type(error).__name__}: {error})"
            vision = {"status": "unavailable", "reason": "model_error"}

    findings = _dedupe(findings)
    checked = waivers_mod.validate(waivers, findings, prior_waivers)
    waivers_mod.apply(findings, checked["accepted"])
    gate = waivers_mod.gate(findings)
    findings = _with_review_weights(findings)
    heuristic_score = score_of(findings)
    if vision_score is None:
        score = heuristic_score
        score_source = "heuristic"
    else:
        score = round((vision_score + heuristic_score) / 2, 2)
        score_source = "vision_blend"

    review = None
    if clean_review:
        review = review_mod.run(link, images=images or [], html=html, findings=findings,
                                deadline=deadline, capture_note=capture_note)
        if review.get("verdict") in ("recapture", "rebuild") and gate["state"] == "pass":
            gate = {**gate, "state": "fix", "blocking": [*gate["blocking"], f"review:{review['verdict']}"]}

    missing = []
    if vision["status"] in ("timed_out", "unavailable"):
        missing.append("vision")
    if review is not None and (review.get("error") or not images):
        missing.append("clean_review")
    next_action = {
        "en": "Continue with these deterministic findings. For the next check, call design_critique with use_vision=false and clean_review=false.",
        "es": "Continúa con estos hallazgos deterministas. Para la siguiente comprobación, llama a design_critique con use_vision=false y clean_review=false.",
    }
    open_n = gate["floor"] + gate["reflex_open"]
    web_guidance, references = _guidance(findings, focus)
    summary = vision_summary or (
        f"{len(findings)} finding(s) ({gate['floor']} floor, {gate['reflex_open']} reflex open, {gate['reflex_waived']} waived, {gate['finish']} finish); "
        f"heuristic score {heuristic_score}/10."
        if findings else f"No issues found by the deterministic checks; heuristic score {heuristic_score}/10."
    )
    return {
        "score": score,
        "heuristic_score": heuristic_score,
        "score_source": score_source,
        "vision_model": vision_model,
        "vision": vision,
        "partial": bool(missing),
        "missing": missing,
        **({"next_action": next_action} if missing else {}),
        "findings": findings,
        "summary": summary,
        "gate": gate,
        "ship_ready": gate["state"] == "pass",
        "open": open_n,
        "waivers": checked,
        "review": review,
        "design_system": bool(tokens),
        "rules_run": lint_result.get("rules_run"),
        "web_guidance": web_guidance,
        "references": references,
        "keyboard": _keyboard_summary(probe, findings),
        "ms": round((time.monotonic() - t0) * 1000, 1),
    }
