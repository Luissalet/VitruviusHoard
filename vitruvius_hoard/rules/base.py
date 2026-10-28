"""Shared helpers for rule implementations."""

from __future__ import annotations

import re
from typing import Any, Optional

from .pagesrc import RGBA, Page, _split_top, colors_in, parse_color, px
from .registry import make_finding

__all__ = ["F", "shadow_layers", "gradients_in", "short", "uniq"]


def F(rule_id: str, detail: str, evidence: Any = None, fix: Optional[str] = None, title: Optional[str] = None) -> dict:
    return make_finding(rule_id, detail, evidence, fix, title)


def short(text: str, n: int = 80) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def uniq(items):
    seen, out = set(), []
    for i in items:
        key = repr(i)
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def shadow_layers(value: str) -> list[dict]:
    """Layers of a box-shadow / text-shadow value: {x, y, blur, spread, color, inset}."""
    out = []
    if not value or value.strip().lower() in ("none", "initial", "inherit"):
        return out
    for layer in _split_top(value, ","):
        layer = layer.strip()
        if not layer:
            continue
        inset = bool(re.search(r"\binset\b", layer, re.I))
        cols = colors_in(layer)
        rest = re.sub(r"(#[0-9a-fA-F]{3,8}\b|(?:rgba?|hsla?|oklch)\([^)]*\))", " ", layer)
        rest = re.sub(r"\binset\b", " ", rest, flags=re.I)
        nums = []
        for tok in rest.split():
            v = px(tok)
            if v is not None:
                nums.append(v)
        if len(nums) < 2:
            continue
        nums += [0.0] * (4 - len(nums))
        color = cols[0] if cols else (0.0, 0.0, 0.0, 1.0)
        out.append({"x": nums[0], "y": nums[1], "blur": nums[2], "spread": nums[3], "color": color, "inset": inset})
    return out


def gradients_in(value: str) -> list[tuple[str, str]]:
    """[(kind, body)] for linear/radial/conic (repeating too) gradient functions in a value."""
    out = []
    for m in re.finditer(r"((?:repeating-)?(?:linear|radial|conic)-gradient)\(", value or "", re.I):
        depth, i = 1, m.end()
        while i < len(value) and depth:
            if value[i] == "(":
                depth += 1
            elif value[i] == ")":
                depth -= 1
            i += 1
        out.append((m.group(1).lower(), value[m.end(): i - 1]))
    return out
