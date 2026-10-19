"""Real stdio adapter and ASGI host with no sockets, services or model access."""
import asyncio
import os
import socket
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
# The real HTTP owner and stdio adapter are separate processes. This fixture
# colocates them through ASGI, so initialize native numeric DLLs before stdin
# begins waiting (avoids Windows pipe contention during DLL import).
import numpy
import httpx
import mcp_server
from vitruvius_hoard.software.host import create_app


async def run():
    # Proactor's private bootstrap socketpair already exists; forbid all later
    # connections. The only HTTP transport in this fixture is ASGI in memory.
    pair_code = getattr(socket.socketpair, '__code__', None)
    def guard(original):
        def guarded(*args, **kwargs):
            frame = sys._getframe(1)
            while frame is not None:
                if frame.f_code is pair_code:
                    return original(*args, **kwargs)
                frame = frame.f_back
            raise AssertionError('Network is disabled in the synthetic MCP fixture')
        return guarded
    socket.socket.connect = guard(socket.socket.connect)
    socket.socket.bind = guard(socket.socket.bind)
    os.environ['HOARD_EVENTS'] = '0'
    app = create_app()
    mcp_server.HTTP_CLIENT = lambda **kwargs: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)
    async with app.router.lifespan_context(app):
        await mcp_server.main()


asyncio.run(run())
