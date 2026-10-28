"""The design-rule registry: every deterministic check is a row of data.

A rule has a stable ``id``, the ``engine`` that can evaluate it (``static`` reads the HTML/CSS text, ``browser`` reads
what a real browser measured, ``visual`` is judged from screenshots by the vision model), a ``scope`` (type, layout,
color, motion, a11y, content, copy, perf, imagery, system), a ``severity`` (``error`` | ``warning`` | ``advisory``) and a
name, a description and a reference. The severity fixes the tier a rule binds with: ``error`` is Floor (never waived),
``warning`` is Reflex (may be waived on the record with a real reason) and ``advisory`` is Finish (answered, never
blocking).

Rules ship in *packs*. The built-in ``core`` pack keeps the original ids (``area.name``); every other pack prefixes its
rules (``slop/nested-cards``). A pack can never shadow an existing id. ``list_rules`` is what ``--list-rules`` and the
``design_rules_list`` tool print.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

ENGINES = ("static", "browser", "visual")
SEVERITIES = ("error", "warning", "advisory")
SCOPES = ("type", "layout", "color", "motion", "a11y", "content", "copy", "perf", "imagery", "system")
TIER_OF = {"error": "floor", "warning": "reflex", "advisory": "finish"}
# The finding vocabulary the UI and the score already speak (info | warn | error).
LEGACY_SEVERITY = {"error": "error", "warning": "warn", "advisory": "info"}
AREA_OF_SCOPE = {"type": "typography", "layout": "layout", "color": "color", "motion": "motion", "a11y": "a11y",
                 "content": "content", "copy": "content", "perf": "perf", "imagery": "layout", "system": "color"}

CheckFn = Callable[[dict, str], list]

_PACK_RE = re.compile(r"^[a-z][a-z0-9-]{1,23}$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")


@dataclass(frozen=True)
class Rule:
    id: str
    engine: str
    scope: str
    severity: str
    name: str
    description: str
    reference: str = ""
    pack: str = "core"
    source: str = "vitruvius"          # where the idea comes from (vitruvius | impeccable | hallmark)
    source_id: str = ""                 # the id it has upstream, when it has one
    fix: str = ""
    judged: bool = False                # decided by a model looking at the page, not by a measurement
    aliases: tuple[str, ...] = ()
    check: Optional[CheckFn] = field(default=None, compare=False, repr=False)

    @property
    def tier(self) -> str:
        return TIER_OF[self.severity]

    def row(self) -> dict[str, Any]:
        return {"id": self.id, "engine": self.engine, "scope": self.scope, "severity": self.severity, "tier": self.tier,
                "name": self.name, "description": self.description, "reference": self.reference, "pack": self.pack,
                "source": self.source, "source_id": self.source_id, "fix": self.fix, "judged": self.judged,
                "aliases": list(self.aliases), "runnable": self.check is not None}


_RULES: dict[str, Rule] = {}
_ALIASES: dict[str, str] = {}


def _validate(rule: Rule) -> None:
    if rule.engine not in ENGINES:
        raise ValueError(f"rule {rule.id}: unknown engine {rule.engine!r}")
    if rule.severity not in SEVERITIES:
        raise ValueError(f"rule {rule.id}: unknown severity {rule.severity!r}")
    if rule.scope not in SCOPES:
        raise ValueError(f"rule {rule.id}: unknown scope {rule.scope!r}")
    if not rule.name or not rule.description:
        raise ValueError(f"rule {rule.id}: a rule needs a name and a description")


def register_rule(rule: Rule) -> Rule:
    _validate(rule)
    if rule.id in _RULES or rule.id in _ALIASES:
        raise ValueError(f"rule id {rule.id!r} is already registered (a pack can never shadow an existing id)")
    for alias in rule.aliases:
        if alias in _RULES or alias in _ALIASES:
            raise ValueError(f"alias {alias!r} of {rule.id} is already taken")
    _RULES[rule.id] = rule
    for alias in rule.aliases:
        _ALIASES[alias] = rule.id
    return rule


def register_pack(prefix: str, rules: list[dict[str, Any]], *, source: str = "vitruvius", check_for: Optional[Callable[[str], Optional[CheckFn]]] = None) -> list[Rule]:
    """Register ``rules`` (dicts without ``id``/``pack``, with ``name_id``) under ``prefix``. The pack prefix keeps ids
    stable and keeps packs apart: ``slop`` + ``nested-cards`` -> ``slop/nested-cards``."""
    if not _PACK_RE.match(prefix) or prefix == "core":
        raise ValueError(f"invalid pack prefix {prefix!r}")
    out = []
    for spec in rules:
        spec = dict(spec)
        name_id = spec.pop("name_id")
        if not _NAME_RE.match(name_id):
            raise ValueError(f"invalid rule name {name_id!r}")
        check = spec.pop("check", None) or (check_for(name_id) if check_for else None)
        out.append(register_rule(Rule(id=f"{prefix}/{name_id}", pack=prefix, source=spec.pop("source", source), check=check, **spec)))
    return out


def unregister_pack(prefix: str) -> int:
    """Remove a pack (tests and plug-ins that unload). The built-in packs are re-registered by ``load_builtin``."""
    gone = [rid for rid, r in _RULES.items() if r.pack == prefix]
    for rid in gone:
        for alias in _RULES[rid].aliases:
            _ALIASES.pop(alias, None)
        del _RULES[rid]
    return len(gone)


def get_rule(rule_id: str) -> Optional[Rule]:
    rule_id = (rule_id or "").strip()
    return _RULES.get(rule_id) or _RULES.get(_ALIASES.get(rule_id, ""))


def all_rules() -> list[Rule]:
    return list(_RULES.values())


def list_rules(*, engine: Optional[str] = None, scope: Optional[str] = None, severity: Optional[str] = None,
               tier: Optional[str] = None, pack: Optional[str] = None, source: Optional[str] = None,
               query: Optional[str] = None, runnable: Optional[bool] = None) -> list[dict[str, Any]]:
    needle = (query or "").lower().strip()
    rows = []
    for rule in _RULES.values():
        if engine and rule.engine != engine:
            continue
        if scope and rule.scope != scope:
            continue
        if severity and rule.severity != severity:
            continue
        if tier and rule.tier != tier:
            continue
        if pack and rule.pack != pack:
            continue
        if source and rule.source != source:
            continue
        if runnable is not None and (rule.check is not None) != runnable:
            continue
        if needle and needle not in " ".join([rule.id, rule.name, rule.description, rule.source_id, *rule.aliases]).lower():
            continue
        rows.append(rule.row())
    return rows


def summary() -> dict[str, Any]:
    """Counts by pack, engine, severity and source (what the screen and ``--list-rules`` show first)."""
    out: dict[str, Any] = {"total": len(_RULES), "by_pack": {}, "by_engine": {}, "by_severity": {}, "by_source": {}, "by_scope": {}}
    for rule in _RULES.values():
        for key, value in (("by_pack", rule.pack), ("by_engine", rule.engine), ("by_severity", rule.severity),
                           ("by_source", rule.source), ("by_scope", rule.scope)):
            out[key][value] = out[key].get(value, 0) + 1
    return out


def make_finding(rule_id: str, detail: str, evidence: Any = None, fix: Optional[str] = None, title: Optional[str] = None) -> dict[str, Any]:
    """A finding in the shape every consumer already reads, with the rule's metadata attached."""
    rule = get_rule(rule_id)
    if rule is None:
        raise KeyError(rule_id)
    return enrich({"check_id": rule.id, "area": AREA_OF_SCOPE.get(rule.scope, "content"), "severity": LEGACY_SEVERITY[rule.severity],
                   "title": title or rule.name, "detail": detail, "evidence": evidence, "fix": fix or rule.fix}, rule)


def enrich(finding: dict[str, Any], rule: Optional[Rule] = None) -> dict[str, Any]:
    """Attach engine / scope / level / tier / pack to a finding whose ``check_id`` is a registered rule."""
    rule = rule or get_rule(finding.get("check_id") or "")
    if rule is None:
        return finding
    finding.setdefault("engine", rule.engine)
    finding.setdefault("scope", rule.scope)
    finding["level"] = rule.severity
    finding["tier"] = rule.tier
    finding["pack"] = rule.pack
    finding["severity"] = LEGACY_SEVERITY[rule.severity]
    return finding
