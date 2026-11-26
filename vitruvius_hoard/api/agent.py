"""/api/agent/* — the bridge used by mcp_server.py (Bearer token from <DATA_DIR>/mcp-token). The routes, the token check,
the error envelope and the audit event are the shared agent kit; Vitruvius only supplies its tools."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool

from ..agent_tools import AGENT_INSTRUCTIONS, CanvasActor, call_tool, tool_catalog
from ..app_canvas import ACTOR_TOOLS
from ..compat_mcp import caller_id
from ..hoard_link.agentkit import make_agent_router
from .deps import services


async def call_agent_tool(name, arguments, request):
    service = services(request)
    project = arguments.get("id")
    if name in ACTOR_TOOLS and isinstance(project, str) and project:
        caller = caller_id(request.headers, await request.json())
        if caller:
            raw_actor = arguments.get("actor")
            declared = (CanvasActor.model_validate(raw_actor).model_dump(exclude_none=True, exclude_unset=True)
                        if raw_actor is not None else {})
            actor = service.app_projects.canvas.actor_for(project, caller, declared)
            arguments = {**arguments, "actor": actor}
    return await run_in_threadpool(call_tool, service, name, arguments)


router = make_agent_router(
    tools_fn=tool_catalog,
    call_fn=call_agent_tool,
    token_fn=lambda request: services(request).token,
    instructions=AGENT_INSTRUCTIONS,
    app_name="vitruvius",
)
