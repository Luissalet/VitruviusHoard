"""Worked examples of the isometric type: a small chest of drawers (the card example) and a cache explained as one."""

from __future__ import annotations

CHEST = {
    "type": "isometric", "title": "Chest of drawers", "figure": 1, "hint": "Pull one drawer", "readout": "2 drawers",
    "pieces": [
        {"id": "base", "kind": "slab", "plan": {"x": 0, "y": 0, "w": 140, "d": 110}, "z": 0, "h": 6, "tone": "lo", "details": ["screws"]},
        {"id": "side-l", "kind": "slab", "plan": {"x": 15, "y": 12, "w": 5, "d": 60}, "z": 6, "h": 40},
        {"id": "side-r", "kind": "slab", "plan": {"x": 120, "y": 12, "w": 5, "d": 60}, "z": 6, "h": 40},
        {"id": "top", "kind": "slab", "plan": {"x": 15, "y": 12, "w": 110, "d": 60}, "z": 46, "h": 5, "details": ["seam"]},
        {"id": "drawer-a", "kind": "slab", "plan": {"x": 20, "y": 36, "w": 100, "d": 56}, "z": 6, "h": 18, "tone": "hi",
         "lit": True, "label": "A", "face": "left"},
        {"id": "pull-a", "kind": "slab", "plan": {"x": 80, "y": 92, "w": 28, "d": 3}, "z": 12, "h": 4},
        {"id": "drawer-b", "kind": "slab", "plan": {"x": 20, "y": 14, "w": 100, "d": 56}, "z": 26, "h": 18, "tone": "hi",
         "label": "B", "face": "left"},
        {"id": "pull-b", "kind": "slab", "plan": {"x": 80, "y": 70, "w": 28, "d": 3}, "z": 32, "h": 4},
    ],
}


def _cache() -> dict:
    pieces = [
        {"id": "base", "kind": "slab", "plan": {"x": 0, "y": 0, "w": 210, "d": 150}, "z": 0, "h": 6, "tone": "lo",
         "details": ["screws", "ticks"]},
        {"id": "side-l", "kind": "slab", "plan": {"x": 20, "y": 14, "w": 5, "d": 90}, "z": 6, "h": 76},
        {"id": "side-r", "kind": "slab", "plan": {"x": 185, "y": 14, "w": 5, "d": 90}, "z": 6, "h": 76},
        {"id": "top", "kind": "slab", "plan": {"x": 20, "y": 14, "w": 170, "d": 90}, "z": 82, "h": 5, "details": ["seam"]},
    ]
    for n in range(4):
        z = 6 + 20 * n
        pulled = n == 2
        y = 16 + (26 if pulled else 0)
        pieces.append({"id": f"set-{n}", "kind": "slab", "plan": {"x": 25, "y": y, "w": 160, "d": 86, "corner": 2}, "z": z, "h": 14,
                       "tone": "hi", "lit": pulled, "label": f"SET {n}" + (" HIT" if pulled else ""), "face": "left"})
        pieces.append({"id": f"pull-{n}", "kind": "slab", "plan": {"x": 140, "y": y + 86, "w": 30, "d": 3}, "z": z + 5, "h": 4})
    pieces.append({"id": "index", "kind": "cylinder", "plan": {"cx": 150, "cy": 59, "r": 18}, "z": 87, "h": 6,
                   "details": ["knurl", "ticks"], "label": "IDX"})
    return {"type": "isometric", "title": "Set-associative cache", "figure": 3, "hint": "The index picks the drawer",
            "readout": "HIT  SET 2  WAY 1", "pieces": pieces}


CACHE = _cache()
