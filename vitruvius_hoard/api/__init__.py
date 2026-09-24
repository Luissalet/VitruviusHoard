"""API routers."""

from .agent import router as agent_router
from .health import router as health_router
from .library import router as library_router
from .pwa import router as pwa_router
from .references import router as references_router
from .render import router as render_router
from .settings import router as settings_router
from .tokens import router as tokens_router

ROUTERS = [health_router, library_router, render_router, tokens_router, references_router, settings_router,
          agent_router, pwa_router]
