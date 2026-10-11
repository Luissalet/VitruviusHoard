"""API routers."""

from .agent import router as agent_router
from .health import router as status_router
from .library import router as library_router
from .references import router as references_router
from .render import router as render_router
from .settings import router as settings_router
from .tokens import router as tokens_router
from .motion import router as motion_router
from .diagrams import router as diagrams_router

ROUTERS = [status_router, library_router, render_router, tokens_router, references_router, settings_router, motion_router, diagrams_router, agent_router]
