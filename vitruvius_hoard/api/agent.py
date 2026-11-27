"""/api/agent/* — the bridge used by mcp_server.py (Bearer token from <DATA_DIR>/mcp-token). The routes, the token check,
the error envelope and the audit event are the shared agent kit; Vitruvius only supplies its tools."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool

from ..agent_tools import AGENT_INSTRUCTIONS, CanvasActor, call_tool, tool_catalog
from ..app_canvas import ACTOR_TOOLS, CALLER_TOOLS, PROJECT_HISTORY_TOOLS, project_tool_caller
from ..compat_mcp import caller_id
from ..hoard_link.agentkit import make_agent_router
from .deps import services


async def call_agent_tool(name, arguments, request):
    service = services(request)
    caller = caller_id(request.headers, await request.json()) if name in CALLER_TOOLS else ""
    project = arguments.get("id")
    if caller and name in ACTOR_TOOLS and isinstance(project, str) and project:
        raw_actor = arguments.get("actor")
        declared = (CanvasActor.model_validate(raw_actor).model_dump(exclude_none=True, exclude_unset=True)
                    if raw_actor is not None else {})
        actor = service.app_projects.canvas.actor_for(project, caller, declared)
        arguments = {**arguments, "actor": actor}
    if name not in PROJECT_HISTORY_TOOLS or project_tool_caller.get() is None:
        return await run_in_threadpool(call_tool, service, name, arguments)
    context = project_tool_caller.set(caller)
    try:
        return await run_in_threadpool(call_tool, service, name, arguments)
    finally:
        project_tool_caller.reset(context)


router = make_agent_router(
    tools_fn=tool_catalog,
    call_fn=call_agent_tool,
    token_fn=lambda request: services(request).token,
    instructions=AGENT_INSTRUCTIONS,
    app_name="vitruvius",
)
