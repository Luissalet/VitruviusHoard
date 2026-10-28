"""The rendered-DOM snapshot the browser hands back (``probe["dom"][width]``) as a small tree the render rules read.

Original code. The snapshot itself is produced by ``browser.DOM_JS``: visible elements with their box in page coordinates
and the computed styles the rules need (defaults left out).
"""

from __future__ import annotations

import re
from typing import Any, Iterator, Optional

from .pagesrc import RGBA, parse_color


class El:
    __slots__ = ("d", "dom", "i", "tag", "cls", "text", "tl", "x", "y", "w", "h", "s", "parent", "children", "_bg", "_ink")

    def __init__(self, d: dict, dom: "Dom"):
        self.d, self.dom, self.i = d, dom, d.get("i", 0)
        self.tag = d.get("tag", "")
        self.cls = d.get("c", "")
        self.text = d.get("t", "")
        self.tl = d.get("tl", 0)
        r = d.get("r") or [0, 0, 0, 0]
        self.x, self.y, self.w, self.h = r
        self.s = d.get("s") or {}
        self.parent: Optional[El] = None
        self.children: list[El] = []
        self._bg = self._ink = False

    # -- geometry
    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    # -- style
    def st(self, key: str, default: Any = None) -> Any:
        return self.s.get(key, default)

    @property
    def fs(self) -> float:
        return float(self.s.get("fs") or 16)

    @property
    def fw(self) -> int:
        w = str(self.s.get("fw") or "400")
        return {"normal": 400, "bold": 700}.get(w, int(w) if w.isdigit() else 400)

    @property
    def ff(self) -> str:
        return (self.s.get("ff") or "").lower()

    @property
    def lh(self) -> Optional[float]:
        return self.s.get("lh")

    @property
    def ls_em(self) -> float:
        return (self.s.get("ls") or 0) / self.fs if self.fs else 0.0

    @property
    def ink(self) -> Optional[RGBA]:
        if self._ink is False:
            self._ink = parse_color(self.s.get("color"))
        return self._ink

    @property
    def bg(self) -> Optional[RGBA]:
        if self._bg is False:
            c = parse_color(self.s.get("bg")) if self.s.get("bg") else None
            self._bg = c if c and c[3] > 0.02 else None
        return self._bg

    @property
    def gradient(self) -> bool:
        return "gradient" in (self.s.get("bgi") or "")

    @property
    def radius(self) -> float:
        return max(self.s.get("rad") or [0])

    @property
    def borders(self) -> list[float]:
        return list(self.s.get("bw") or [0, 0, 0, 0])

    @property
    def pad(self) -> list[float]:
        return list(self.s.get("pad") or [0, 0, 0, 0])

    @property
    def has_box(self) -> bool:
        """Something visibly contains: a fill, a border or a shadow."""
        return bool(self.bg or self.gradient or any(b > 0 for b in self.borders) or self.s.get("sh"))

    def eff_bg(self) -> RGBA:
        """The colour painted behind this element's text: the nearest ancestor (or itself) with a mostly opaque fill."""
        n: Optional[El] = self
        while n is not None:
            c = n.bg
            if c and c[3] >= 0.6:
                return c
            n = n.parent
        return (255.0, 255.0, 255.0, 1.0)

    def ancestors(self) -> Iterator["El"]:
        n = self.parent
        while n is not None:
            yield n
            n = n.parent

    def descendants(self) -> Iterator["El"]:
        for c in self.children:
            yield c
            yield from c.descendants()

    def deep_text_len(self) -> int:
        return self.tl + sum(c.deep_text_len() for c in self.children)

    def label(self) -> str:
        s = self.tag
        if self.d.get("id"):
            s += "#" + self.d["id"]
        c = [x for x in self.cls.split() if x][:2]
        if c:
            s += "." + ".".join(c)
        return s

    def snippet(self, n: int = 40) -> str:
        t = self.text or " ".join(c.text for c in self.children if c.text)
        t = re.sub(r"\s+", " ", t).strip()
        return f"{self.label()} “{t[: n]}”" if t else self.label()

    def in_tag(self, *tags: str) -> bool:
        return any(a.tag in tags for a in self.ancestors())

    @property
    def is_card(self) -> bool:
        """A contained block: a fill that differs from what is behind it, a border or a shadow, with some size."""
        if self.w < 140 or self.h < 60 or self.w > self.dom.width * 0.98 or self.tag in ("body", "html", "main", "header", "footer", "nav", "section", "form", "td", "tr", "table"):
            return False
        if self.s.get("sh") or any(b > 0 for b in self.borders):
            return True
        c = self.bg
        if c and c[3] > 0.5 and self.parent is not None:
            pb = self.parent.eff_bg()
            return sum(abs(c[k] - pb[k]) for k in range(3)) > 18
        return False


class Dom:
    def __init__(self, snap: dict):
        self.width = int(snap.get("width") or 0)
        self.vh = int(snap.get("height") or 900)
        self.page_height = int(snap.get("page_height") or 0)
        self.page_width = int(snap.get("page_width") or self.width)
        self.truncated = bool(snap.get("truncated"))
        self.occluded = snap.get("occluded") or []
        self.els: list[El] = [El(d, self) for d in snap.get("els") or []]
        for e in self.els:
            p = e.d.get("p", -1)
            if isinstance(p, int) and 0 <= p < len(self.els) and p != e.i:
                e.parent = self.els[p]
                self.els[p].children.append(e)

    def tags(self, *tags: str) -> list[El]:
        s = set(tags)
        return [e for e in self.els if e.tag in s]

    def headings(self, *levels: int) -> list[El]:
        want = {f"h{n}" for n in (levels or (1, 2, 3, 4, 5, 6))}
        return [e for e in self.els if e.tag in want and e.deep_text_len() > 0]

    def first_screen(self, e: El) -> bool:
        return e.y < self.vh and e.bottom > 0

    def text_els(self) -> list[El]:
        return [e for e in self.els if e.tl > 0 and e.w > 0]

    def sections(self) -> list[El]:
        """The page's bands, outermost first, in reading order: <section> blocks, else the top-level children of main/body."""
        wide = self.width * 0.8
        cands = [e for e in self.els if e.tag == "section" and e.w >= wide and e.h >= 60]
        if len(cands) < 3:
            holders = [e for e in self.els if e.tag == "main"] or [e for e in self.els if e.tag == "body"]
            top: list[El] = []
            for hold in holders[:1]:
                top = [c for c in hold.children if c.w >= wide and c.h >= 60 and c.tag not in ("script", "style")]
            if not top:
                top = [e for e in self.els if e.parent is None and e.w >= wide and e.h >= 60]
                if len(top) == 1:
                    top = [c for c in top[0].children if c.w >= wide and c.h >= 60]
            if len(top) > len(cands):
                cands = top
        inner = set()
        for c in cands:
            for a in c.ancestors():
                if a in cands:
                    inner.add(c.i)
        return sorted((c for c in cands if c.i not in inner), key=lambda e: e.y)


def doms(probe: dict) -> list[Dom]:
    """The snapshots a probe holds, widest first. Entries the browser could not fill (``error``) are skipped."""
    out = []
    for key, snap in ((probe or {}).get("dom") or {}).items():
        if isinstance(snap, dict) and snap.get("els") and not snap.get("error"):
            try:
                out.append(Dom(snap))
            except Exception:  # noqa: BLE001 — a malformed snapshot never sinks the lint
                continue
    return sorted(out, key=lambda d: -d.width)
