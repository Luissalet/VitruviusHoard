"""The design-rule registry and the rule packs.

``load_packs()`` registers the built-in packs (slop, quality, craft, visual, ds) once; the ``core`` pack is registered by
``lint.py`` next to the check functions it wraps. See ``registry`` for the data model.
"""

from __future__ import annotations

from . import registry
from .registry import (ENGINES, SEVERITIES, SCOPES, Rule, all_rules, enrich, get_rule, list_rules, make_finding, register_pack,
                       register_rule, summary, unregister_pack)

_LOADED = False


def implementations() -> dict:
    """Every packaged check, by rule id."""
    from . import dom_rules, static_a, static_b, unslop  # noqa: F401 — static_b registers into static_a's table
    return {**static_a.CHECKS, **dom_rules.CHECKS}


def load_packs() -> None:
    global _LOADED
    if _LOADED:
        return
    from .catalog import PACKS, specs_for
    impl = implementations()
    for pack in PACKS:
        specs = specs_for(pack)
        register_pack(pack, specs, check_for=lambda name, pack=pack: impl.get(f"{pack}/{name}"))
    _LOADED = True


__all__ = ["registry", "Rule", "ENGINES", "SEVERITIES", "SCOPES", "all_rules", "enrich", "get_rule", "list_rules", "load_packs",
           "implementations", "make_finding", "register_pack", "register_rule", "summary", "unregister_pack"]
