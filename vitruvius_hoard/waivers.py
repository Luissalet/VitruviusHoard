"""Waivers: how a Reflex-tier finding may be left standing, on the record.

Tiers follow the severity of the rule that fired: **Floor** (``error``) is never waived, **Reflex** (``warning``) is fixed or
waived with a real reason, **Finish** (``advisory``) is answered but never blocks. A waiver names the rule and gives a reason of
at least 24 characters that is not a restatement of the rule and was not already given for another rule of the same page.
"""

from __future__ import annotations

import re
import time
from typing import Any, Iterable, Optional

from .rules.registry import get_rule

MIN_REASON = 24


def reason_key(reason: str) -> str:
    """The form a reason is compared in: case, accents-insensitive-ish, punctuation and spacing folded."""
    return re.sub(r"[^a-z0-9áéíóúñü]+", " ", (reason or "").lower()).strip()


def normalise(waivers: Any) -> list[dict[str, str]]:
    """Accepts [{rule, reason}] or {rule: reason}; anything else is no waivers."""
    if not waivers:
        return []
    if isinstance(waivers, dict):
        return [{"rule": str(k), "reason": str(v)} for k, v in waivers.items()]
    out = []
    for w in waivers:
        if isinstance(w, dict):
            out.append({"rule": str(w.get("rule") or w.get("rule_id") or w.get("check_id") or ""), "reason": str(w.get("reason") or "")})
    return out


def validate(waivers: Any, findings: list[dict], prior: Optional[dict[str, str]] = None) -> dict[str, list]:
    """Check each waiver against the findings of this run. ``prior`` maps rule id -> reason already on record for the page.

    Returns ``{"accepted": [{rule, reason}], "rejected": [{rule, reason, why}]}``.
    """
    prior = dict(prior or {})
    fired: dict[str, dict] = {}
    for f in findings:
        if f.get("check_id") and f["check_id"] not in fired:
            fired[f["check_id"]] = f
    used = {reason_key(r): rid for rid, r in prior.items()}
    accepted, rejected = [], []
    for w in normalise(waivers):
        raw_rule, reason = w["rule"].strip(), re.sub(r"\s+", " ", w["reason"]).strip()
        rule = get_rule(raw_rule)

        def reject(why: str) -> None:
            rejected.append({"rule": raw_rule, "reason": reason, "why": why})
        if rule is None:
            reject("no such rule; list them with design_rules_list")
            continue
        if rule.tier == "floor":
            reject("Floor rules (severity error) are never waived: fix the page")
            continue
        if rule.tier == "finish":
            reject("Finish rules (advisory) do not block anything, so there is nothing to waive")
            continue
        if len(reason) < MIN_REASON:
            reject(f"the reason is {len(reason)} characters; a waiver needs at least {MIN_REASON}")
            continue
        key = reason_key(reason)
        if key in (reason_key(rule.id), reason_key(rule.name), reason_key(rule.description)):
            reject("the reason only restates the rule: say why this page is right to break it")
            continue
        if rule.id not in fired:
            reject("the rule has no open finding on this page, so there is nothing to waive")
            continue
        if key in used and used[key] != rule.id:
            reject(f"the same reason was already given for {used[key]}: each waiver needs its own")
            continue
        used[key] = rule.id
        accepted.append({"rule": rule.id, "reason": reason})
    return {"accepted": accepted, "rejected": rejected}


def apply(findings: list[dict], accepted: Iterable[dict]) -> list[dict]:
    """Mark the findings of waived rules (``waived`` and ``waiver_reason``); nothing is removed."""
    by_rule = {a["rule"]: a["reason"] for a in accepted}
    for f in findings:
        reason = by_rule.get(f.get("check_id") or "")
        if reason and f.get("tier") == "reflex":
            f["waived"] = True
            f["waiver_reason"] = reason
    return findings


def gate(findings: list[dict]) -> dict[str, Any]:
    """The state of the three tiers: ``pass`` only with no Floor finding and no open Reflex finding."""
    floor = [f for f in findings if f.get("tier") == "floor"]
    reflex_open = [f for f in findings if f.get("tier") == "reflex" and not f.get("waived")]
    waived = [f for f in findings if f.get("tier") == "reflex" and f.get("waived")]
    finish = [f for f in findings if f.get("tier") == "finish"]
    blocking = sorted({f["check_id"] for f in [*floor, *reflex_open] if f.get("check_id")})
    return {"state": "pass" if not floor and not reflex_open else "fix", "floor": len(floor), "reflex_open": len(reflex_open),
            "reflex_waived": len(waived), "finish": len(finish), "blocking": blocking}


def stored(db, render_id: str) -> dict[str, str]:
    return {r["rule_id"]: r["reason"] for r in db.query("SELECT rule_id, reason FROM waivers WHERE render_id = ?", (render_id,))}


def store(db, render_id: str, accepted: Iterable[dict]) -> None:
    for a in accepted:
        db.execute(
            "INSERT INTO waivers(render_id, rule_id, reason, reason_key, created_ts) VALUES (?,?,?,?,?) "
            "ON CONFLICT(render_id, rule_id) DO UPDATE SET reason = excluded.reason, reason_key = excluded.reason_key, created_ts = excluded.created_ts",
            (render_id, a["rule"], a["reason"], reason_key(a["reason"]), time.time()))
