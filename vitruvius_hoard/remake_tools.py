"""Agent tools for "Rehacer": a reference page (URL or screenshot) remade round by round until it reaches visual parity."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .hoard_link.agentkit import Tool, ann


class RemakeStartArgs(BaseModel):
    url: Optional[str] = Field(None, max_length=2000, description="The public page to remake (http/https).")
    image: Optional[str] = Field(None, max_length=40_000_000, description="Instead of a URL: a full-page screenshot as base64 PNG/JPEG (data: URLs accepted). Forces mode 'rebuild' and needs a vision model.")
    image_width: int = Field(1440, ge=200, le=3000, description="Width in CSS px the screenshot was taken at.")
    mode: Literal["copy", "rebuild"] = Field("copy", description="copy: the page's own rendered HTML, CSS and files, then CSS fixes from the model; rebuild: new hand-written HTML/CSS from the model.")
    widths: list[int] = Field(default_factory=lambda: [1440, 390], max_length=3, description="Viewport widths in px (desktop and mobile by default).")
    max_rounds: Optional[int] = Field(None, ge=1, le=20, description="Rounds including the first one (default 4 for copy, 6 for rebuild).")
    pass_score: float = Field(98.0, ge=50, le=100, description="A screen passes with at least this % of stable pixels within the tolerance.")
    tolerance: float = Field(0.10, ge=0, le=0.5, description="Colour tolerance per channel as a share of 255.")
    keep_scripts: bool = Field(False, description="copy mode: keep the original document and its scripts instead of the static snapshot.")
    note: str = Field("", max_length=2000, description="Extra instructions for the model in every round.")
    label: str = Field("", max_length=200)
    wait_s: float = Field(0, ge=0, le=900, description="Wait up to this many seconds for the job before answering (0 = answer at once and poll remake_get).")


class RemakeIdArgs(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)


class RemakeContinueArgs(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)
    rounds: int = Field(2, ge=1, le=20, description="How many more repair rounds.")
    note: str = Field("", max_length=2000, description="New instructions for the model (replaces the previous note).")
    wait_s: float = Field(0, ge=0, le=900)


class RemakeCodeArgs(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)
    path: str = Field("index.html", max_length=400, description="A file of the result (index.html or something under assets/).")
    max_chars: int = Field(60000, ge=1000, le=400000)


class RemakeListArgs(BaseModel):
    limit: int = Field(20, ge=1, le=200)


def run_remake_start(s, a: RemakeStartArgs) -> dict:
    return s.remake.start(url=a.url, image=a.image, image_width=a.image_width, mode=a.mode, widths=a.widths, max_rounds=a.max_rounds,
                          pass_score=a.pass_score, tolerance=a.tolerance, keep_scripts=a.keep_scripts, note=a.note, label=a.label,
                          wait_s=a.wait_s)


def tools() -> list[Tool]:
    return [
        Tool("remake_start",
             "Remake a web page from a URL or screenshot until it matches it screen by screen. Rehacer una web.\n"
             "Captures the reference frozen at desktop and mobile (layout, texts, palette, fonts, images, CSS), builds a first candidate "
             "(copy: the page's own HTML, CSS and files without trackers; rebuild: new HTML/CSS written by the family's global model), "
             "scores it with visual parity and repairs the first failing screen of each width in a loop (missing files fetched, model "
             "edits with element-by-element differences and pictures) until every screen passes or the rounds run out; a round that "
             "scores lower is undone. Runs in the background: poll remake_get. Pages behind a bot check or with sign-in/payment forms "
             "are refused.\nSinónimos: rehacer, clonar una web, copiar una landing, reconstruir una página, igualar una maqueta.",
             RemakeStartArgs, ann(False, False, False, open_world=True), run_remake_start, timeout_s=960),
        Tool("remake_get",
             "Read a remake: status, rounds with parity scores, best round, result files, assets and licences. Leer rehacer.",
             RemakeIdArgs, ann(True), lambda s, a: s.remake.get(a.id)),
        Tool("remake_list", "List remakes, newest first, with status and best score. Listar rehacer.",
             RemakeListArgs, ann(True), lambda s, a: {"remakes": s.remake.list(a.limit)}),
        Tool("remake_code", "Read the code of a remake's result (index.html or a file under assets/). Código de rehacer.",
             RemakeCodeArgs, ann(True), lambda s, a: s.remake.code(a.id, a.path, a.max_chars)),
        Tool("remake_continue",
             "Run more repair rounds on a remake, from its best round, optionally with new instructions. Seguir corrigiendo.",
             RemakeContinueArgs, ann(False, False, False), lambda s, a: s.remake.continue_(a.id, rounds=a.rounds, note=a.note, wait_s=a.wait_s),
             timeout_s=960),
        Tool("remake_stop", "Stop a running remake after its current step; the best round stays. Parar rehacer.",
             RemakeIdArgs, ann(False, False, True), lambda s, a: s.remake.stop(a.id)),
        Tool("remake_delete", "Delete a remake with its files and its parity runs. Borrar rehacer.",
             RemakeIdArgs, ann(False, True, True), lambda s, a: s.remake.delete(a.id)),
    ]
