"""The same evaluation operations for MCP and the workbench."""

from typing import Literal
from pydantic import BaseModel, Field
from ..hoard_link.agentkit import Empty, Tool, ann


class Start(BaseModel):
    runtime_kind: Literal["container", "native"] = Field(
        "container",
        description="Linux container for all reference fixtures. Native uses the current interpreter and installed reference dependencies.",
    )
    version: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Version being measured, e.g. a release or commit.",
    )
    cases: list[str] | None = Field(
        None,
        max_length=70,
        description="Corpus ids. Omit to run all 70 frozen references.",
    )
    mode: Literal["copy", "rebuild"] = "copy"
    max_rounds: int = Field(1, ge=1, le=20)
    widths: list[int] = Field(
        default_factory=lambda: [1440, 390], min_length=1, max_length=3
    )
    pass_score: float = Field(98, ge=50, le=100)
    tolerance: float = Field(0.10, ge=0, le=0.5)
    note: str = Field("", max_length=2000)


class Id(BaseModel):
    id: str = Field(..., pattern="^[a-f0-9]{12}$")


class Compare(BaseModel):
    before: str = Field(..., pattern="^[a-f0-9]{12}$")
    after: str = Field(..., pattern="^[a-f0-9]{12}$")


class ListArgs(BaseModel):
    limit: int = Field(50, ge=1, le=200)


def tools():
    return [
        Tool(
            "benchmark_catalog",
            "Read pinned reconstruction references. Leer corpus congelado.\nAll 70 reference ids, provenance, case counts and measurement scope. No downloads or reference processes start.",
            Empty,
            ann(True),
            lambda s, a: s.benchmarks.catalog(),
        ),
        Tool(
            "benchmark_start",
            "Measure Rehacer by version. Evaluar Rehacer por versión.\nDownloads requested reference fixtures once, starts each locally with fresh state, runs normal Rehacer and closes it. Copy defaults to one round. Rebuild uses the global model. Metric is Vitruvius stable-pixel parity at each width. Official functional/SSIM reward remains unmeasured. Poll benchmark_get.",
            Start,
            ann(False, False, False, open_world=True),
            lambda s, a: s.benchmarks.start(**a.model_dump()),
        ),
        Tool(
            "benchmark_get",
            "Read a versioned evaluation. Leer evaluación.\nCoverage, failures, configuration, source hashes, per-round scores and evidence links.",
            Id,
            ann(True),
            lambda s, a: s.benchmarks.get(a.id),
        ),
        Tool(
            "benchmark_list",
            "List reconstruction evaluations. Listar evaluaciones.\nVersions and measured coverage.",
            ListArgs,
            ann(True),
            lambda s, a: s.benchmarks.list(a.limit),
        ),
        Tool(
            "benchmark_compare",
            "Compare measured versions. Comparar versiones.\nPairs measured cases when corpus, selection, settings and reference hashes match. Returns coverage and score deltas.",
            Compare,
            ann(True),
            lambda s, a: s.benchmarks.compare(a.before, a.after),
        ),
        Tool(
            "benchmark_stop",
            "Stop an evaluation. Parar evaluación.\nStops its current remake and retains completed case scores.",
            Id,
            ann(False, False, True),
            lambda s, a: s.benchmarks.stop(a.id),
        ),
        Tool(
            "benchmark_resume",
            "Resume pending corpus cases. Reanudar evaluación.\nRequires the same implementation. Measured and failed results stay retained. Start a new version after code changes or to repeat failures.",
            Id,
            ann(False, False, False),
            lambda s, a: s.benchmarks.resume(a.id),
        ),
    ]
