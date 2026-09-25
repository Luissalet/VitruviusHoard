"""Process-level configuration read from the environment (never from the DB)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .guard import parse_allowed_hosts

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 5191


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(raw: str, default: int, low: int, high: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if low <= value <= high else default


def _float(raw: str, default: float, low: float, high: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if low <= value <= high else default


@dataclass
class Config:
    """Everything the process needs before the database exists."""

    data_dir: Path = field(default_factory=lambda: REPO_ROOT / "data")
    port: int = DEFAULT_PORT
    port_strict: bool = False
    render_timeout_s: float = 45.0
    allowed_hosts: tuple[str, ...] = ()
    data_dir_configured: bool = False
    autostart: bool = True  # start the ingest runner with the app
    embed_backend: str = "auto"  # auto (fastembed when installed) | fake | none
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embed_auto: bool = True  # (re)build vectors after an ingest when the model is already on disk

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vitruvius.db"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "mcp-token"

    @property
    def url_path(self) -> Path:
        return self.data_dir / "url"

    @property
    def sources_dir(self) -> Path:
        return self.data_dir / "sources"

    @property
    def renders_dir(self) -> Path:
        return self.data_dir / "renders"

    @property
    def references_dir(self) -> Path:
        return self.data_dir / "references"

    @property
    def backend_json_path(self) -> Path:
        return self.data_dir / "backend.json"

    @classmethod
    def from_env(cls) -> "Config":
        raw_dir = _env("VITRUVIUS_DATA_DIR")
        port = _int(_env("VITRUVIUS_PORT") or _env("PORT") or str(DEFAULT_PORT), DEFAULT_PORT, 1, 65535)
        return cls(
            data_dir=Path(raw_dir).expanduser() if raw_dir else REPO_ROOT / "data",
            port=port,
            port_strict=_env("PORT_STRICT") == "1",
            render_timeout_s=_float(_env("VITRUVIUS_RENDER_TIMEOUT_S"), 45.0, 5.0, 600.0),
            allowed_hosts=parse_allowed_hosts(_env("VITRUVIUS_ALLOWED_HOSTS")),
            data_dir_configured=bool(raw_dir),
            autostart=_env("VITRUVIUS_AUTOSTART", "1") != "0",
            embed_backend=(_env("VITRUVIUS_EMBED", "auto") or "auto").lower(),
            embed_model=_env("VITRUVIUS_EMBED_MODEL") or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            embed_auto=_env("VITRUVIUS_EMBED_AUTO", "1") != "0",
        )
