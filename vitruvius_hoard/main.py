"""FastAPI application factory: request guard, API routers, static SPA."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api import ROUTERS
from .config import Config
from .guard import install_guard
from .hoard_link import family
from .ingest.runner import IngestRunner  # noqa: F401 (imported for side effects/typing clarity)
from .services import Services

STATIC_DIR = Path(__file__).resolve().parent / "static"
SEEDS_PATH = Path(__file__).resolve().parent / "seeds.json"


def create_app(config: Config | None = None, services: Services | None = None) -> FastAPI:
    """``services`` lets tests inject a pre-built instance (fake browser, fake link)."""
    config = config or (services.config if services else Config.from_env())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = services or Services(config)
        app.state.services = svc
        _seed_sources(svc)
        svc.start()
        logging.getLogger("vitruvius").info("Vitruvius's Hoard %s — data in %s", __version__, config.data_dir)
        try:
            yield
        finally:
            svc.stop()

    app = FastAPI(title="Vitruvius's Hoard", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.config = config
    family.configure("vitruvius", str(config.data_dir), token_file=str(config.token_path))

    install_guard(app, config.allowed_hosts)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        issues = "; ".join(f"{'.'.join(str(p) for p in e['loc'] if p != 'body') or 'input'}: {e['msg']}" for e in exc.errors())
        return JSONResponse({"error": issues}, status_code=400)

    for router in ROUTERS:
        app.include_router(router)

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"error": "Not found."}, status_code=404)
        candidate = (STATIC_DIR / path).resolve() if path else None
        if candidate and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"error": "The client is not built yet: run `npm install && npm run build`."}, status_code=503)

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
