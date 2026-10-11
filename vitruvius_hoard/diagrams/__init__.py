"""Diagrams: the model gives structure (or Mermaid / Excalidraw / draw.io), code does layout, routing, brand colours and gates.

``make(diagram, profile)`` returns the light and dark SVG plus the gate report; ``DiagramStore`` keeps each result under
``<data>/diagrams/<id>/`` (``diagram.json``, ``light.svg``, ``dark.svg``, ``report.json``) so the UI and other apps can fetch it.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .brand import ProfileStore, from_folder, from_probe
from .importers import load as import_source
from .render import DEFAULT, FONT_STACK, gates, layout_of, profile_from_colors, profile_from_tokens, svg
from .spec import CARDS, PATTERNS, Diagram, catalogue, pick_type, type_card

DEFAULT_PROFILE = {"name": "default", "font": FONT_STACK, "light": DEFAULT["light"], "dark": DEFAULT["dark"]}


def make(diagram: Diagram, profile: Optional[dict] = None, modes: tuple[str, ...] = ("light", "dark")) -> dict[str, Any]:
    profile = profile or DEFAULT_PROFILE
    lay = layout_of(diagram)
    out = {mode: svg(diagram, profile, mode, lay) for mode in modes}
    report = gates(diagram, profile, lay)
    failed = [g["id"] for g in report if not g["ok"]]
    return {"svg": out, "gates": report, "ok": not failed, "failed": failed}


class DiagramStore:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir) / "diagrams"

    def save(self, diagram: Diagram, result: dict[str, Any], profile_name: str, source: str = "") -> dict[str, Any]:
        did = uuid.uuid4().hex[:12]
        folder = self.dir / did
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "diagram.json").write_text(diagram.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
        for mode, text in result["svg"].items():
            (folder / f"{mode}.svg").write_text(text, encoding="utf-8")
        meta = {"id": did, "created_ts": time.time(), "type": diagram.type, "title": diagram.title, "profile": profile_name,
                "ok": result["ok"], "failed": result["failed"], "gates": result["gates"], "source": source,
                "modes": sorted(result["svg"])}
        (folder / "report.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    def _folder(self, did: str) -> Path:
        if not did or not all(c in "0123456789abcdef" for c in did):
            raise LookupError(f"Unknown diagram '{did}'.")
        folder = self.dir / did
        if not (folder / "report.json").exists():
            raise LookupError(f"Unknown diagram '{did}'.")
        return folder

    def get(self, did: str, *, with_svg: bool = False) -> dict[str, Any]:
        folder = self._folder(did)
        meta = json.loads((folder / "report.json").read_text(encoding="utf-8"))
        meta["diagram"] = json.loads((folder / "diagram.json").read_text(encoding="utf-8"))
        if with_svg:
            meta["svg"] = {m: (folder / f"{m}.svg").read_text(encoding="utf-8") for m in meta.get("modes", [])}
        return meta

    def svg_path(self, did: str, mode: str) -> Path:
        if mode not in ("light", "dark"):
            raise LookupError(f"Unknown mode '{mode}'.")
        path = self._folder(did) / f"{mode}.svg"
        if not path.exists():
            raise LookupError(f"Diagram '{did}' has no {mode} drawing.")
        return path

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.dir.exists():
            return []
        rows = []
        for folder in self.dir.iterdir():
            report = folder / "report.json"
            if folder.name != "profiles" and report.exists():
                meta = json.loads(report.read_text(encoding="utf-8"))
                rows.append({k: meta.get(k) for k in ("id", "created_ts", "type", "title", "profile", "ok", "failed")})
        rows.sort(key=lambda r: r["created_ts"] or 0, reverse=True)
        return rows[:limit]

    def delete(self, did: str) -> bool:
        folder = self._folder(did)
        for p in folder.iterdir():
            p.unlink()
        folder.rmdir()
        return True


__all__ = [
    "CARDS", "DEFAULT_PROFILE", "Diagram", "DiagramStore", "PATTERNS", "ProfileStore", "catalogue", "from_folder", "from_probe",
    "gates", "import_source", "make", "pick_type", "profile_from_colors", "profile_from_tokens", "svg", "type_card",
]
