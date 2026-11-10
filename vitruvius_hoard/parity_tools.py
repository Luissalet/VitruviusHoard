"""Agent tools for visual parity: a candidate page against a reference, screen by screen."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .hoard_link.agentkit import Tool, ann


class VisualParityArgs(BaseModel):
    reference: str = Field(..., min_length=1, max_length=2_000_000, description="The page to match: a URL, inline HTML or the id of a render_preview.")
    candidate: str = Field(..., min_length=1, max_length=2_000_000, description="The page being checked: a URL, inline HTML or the id of a render_preview.")
    widths: list[int] = Field(default_factory=lambda: [1440, 390], max_length=4, description="Viewport widths in px (200..3000); 1440 is desktop (900 px screens), 390 mobile (844 px screens).")
    max_screens: int = Field(12, ge=1, le=40, description="At most this many viewport-high screens per width are scored.")
    tolerance: float = Field(0.10, ge=0, le=0.5, description="Colour tolerance per channel as a share of 255 (0.10 = 10 %).")
    pass_score: float = Field(98.0, ge=50, le=100, description="A screen passes with at least this % of stable pixels within the tolerance.")
    height_tolerance: int = Field(4, ge=0, le=500, description="Allowed difference in total page height, in px.")
    dark: bool = False
    wait_ms: int = Field(600, ge=0, le=20000)
    label: str = Field("", max_length=200)


class ParityIdArgs(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)


class ParityListArgs(BaseModel):
    limit: int = Field(20, ge=1, le=200)


def run_visual_parity(services, args: VisualParityArgs) -> dict:
    return services.visual_parity(args.reference, args.candidate, widths=args.widths, max_screens=args.max_screens, tolerance=args.tolerance,
                                  pass_score=args.pass_score, height_tolerance=args.height_tolerance, dark=args.dark, wait_ms=args.wait_ms,
                                  label=args.label)


def tools() -> list[Tool]:
    return [
        Tool("visual_parity",
             "Score how closely a page matches a reference, per screen, at desktop and mobile. Paridad visual.\n"
             "Both pages load with the clock, random numbers, animations, transitions and videos frozen; lazy content is fired by scrolling; "
             "the reference loads twice and pixels that differ between those loads are left out as noise. Each viewport-high screen passes with "
             "98 % of stable pixels within 10 % per channel (configurable); the page height must match within 4 px. Returns scores, pass/fail per "
             "screen and width, a global verdict, diff images (red = different, blue = noise) and a side-by-side page with a slider at report_url.\n"
             "Sinónimos: paridad, igual que la referencia, comparar con la maqueta, diff visual de página, regresión visual, clonar una web.",
             VisualParityArgs, ann(False, False, False), run_visual_parity, timeout_s=300),
        Tool("visual_parity_get", "Read a stored visual-parity run with scores, failures and image links. Leer paridad visual.",
             ParityIdArgs, ann(True), lambda s, a: s.parity_get(a.id)),
        Tool("visual_parity_list", "List stored visual-parity runs, newest first. Listar comparaciones de paridad.",
             ParityListArgs, ann(True), lambda s, a: {"runs": s.parity_list(a.limit)}),
        Tool("visual_parity_delete", "Delete a stored visual-parity run and its images. Borrar paridad visual.",
             ParityIdArgs, ann(False, True, True), lambda s, a: s.parity_delete(a.id)),
    ]
