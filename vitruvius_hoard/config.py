"""Process-level configuration read from the environment (never from the DB)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .hoard_link.appconfig import env_flag, env_float, env_int, env_str
from .hoard_link.guard import parse_allowed_hosts

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 5191


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
    embed_backend: str = "auto"  # auto (Borges through the hub, else the in-process fastembed) | family | local | fake | none
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embed_auto: bool = True  # (re)build vectors after an ingest when the model is already on disk
    allow_local_urls: bool = False  # let render / reference_add / page_assay open localhost and private-network pages

    @property
    def url_profile(self) -> str:
        """The `hoard_link.web.safety` profile for URLs the assistant asks to open."""
        return "operator_local" if self.allow_local_urls else "public"

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
        raw_dir = env_str("VITRUVIUS_DATA_DIR")
        return cls(
            data_dir=Path(raw_dir).expanduser() if raw_dir else REPO_ROOT / "data",
            port=env_int("VITRUVIUS_PORT", "PORT", default=DEFAULT_PORT, minimum=1, maximum=65535),
            port_strict=env_flag("PORT_STRICT", False),
            render_timeout_s=env_float("VITRUVIUS_RENDER_TIMEOUT_S", default=45.0, minimum=5.0, maximum=600.0),
            allowed_hosts=parse_allowed_hosts(env_str("VITRUVIUS_ALLOWED_HOSTS")),
            data_dir_configured=bool(raw_dir),
            autostart=env_flag("VITRUVIUS_AUTOSTART", True),
            embed_backend=(env_str("VITRUVIUS_EMBED", default="auto") or "auto").lower(),
            embed_model=env_str("VITRUVIUS_EMBED_MODEL", default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
            embed_auto=env_flag("VITRUVIUS_EMBED_AUTO", True),
            allow_local_urls=env_flag("VITRUVIUS_ALLOW_LOCAL_URLS", False),
        )
