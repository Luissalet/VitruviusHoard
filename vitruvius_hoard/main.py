"""FastAPI application factory: request guard, API routers, PWA files, static SPA. The guard, the error envelope, the PWA files
and the single-page-app server are the shared `hoard_link.guard` / `hoard_link.service`."""

from __future__ import annotations

import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from . import SERVICE, __version__
from .api import ROUTERS
from .api.health import health_extra
from .config import Config
from .hoard_link import family
from .hoard_link.guard import install_guard
from .hoard_link.service import health_router, install_error_handlers, install_pwa, install_spa
from .ingest.runner import IngestRunner  # noqa: F401 (imported for side effects/typing clarity)
from .services import Services

STATIC_DIR = Path(__file__).resolve().parent / "static"
SEEDS_PATH = Path(__file__).resolve().parent / "seeds.json"


def create_app(config: Config | None = None, services: Services | None = None) -> FastAPI:
    """``services`` lets tests inject a pre-built instance (fake browser, fake link)."""
    config = config or (services.config if services else Config.from_env())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = services or await asyncio.to_thread(Services, config, autostart_ingest=config.autostart)
        app.state.services = svc
        _seed_sources(svc)
        await asyncio.to_thread(svc.start)
        logging.getLogger("vitruvius").info("Vitruvius's Hoard %s — data in %s", __version__, config.data_dir)
        try:
            yield
        finally:
            await asyncio.to_thread(svc.stop)

    app = FastAPI(title="Vitruvius's Hoard", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.config = config
    family.configure("vitruvius", str(config.data_dir), token_file=str(config.token_path))

    install_guard(app, port_getter=lambda: config.port, allowed_hosts=config.allowed_hosts, allowed_env="VITRUVIUS_ALLOWED_HOSTS")
    install_error_handlers(app)
    app.include_router(health_router(SERVICE, __version__, extra=health_extra))
    for router in ROUTERS:
        app.include_router(router)
    install_pwa(app, name="Vitruvius's Hoard", short_name="Vitruvius", theme="#1b2f9e", background="#0b1130",
                cache="vitruvius-hoard-assets", lang="en", static_dir=STATIC_DIR, version=__version__)
    install_spa(app, STATIC_DIR)
    return app


def _seed_sources(svc: Services) -> None:
    if not SEEDS_PATH.is_file():
        return
    try:
        import json
        seeds = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
        svc.seed_sources(seeds)
    except Exception:  # noqa: BLE001 — seeding is best-effort, never blocks startup
        logging.getLogger("vitruvius").warning("could not seed sources from %s", SEEDS_PATH, exc_info=True)
