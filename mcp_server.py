"""Cold native catalogue; explicit calls use Vitruvius's existing HTTP owner, never autostart."""
import asyncio
import json
import os
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent, CallToolResult
from vitruvius_hoard.software.host import catalog
from vitruvius_hoard.software.runtime import token_path

server = Server('vitruvius')
HTTP_CLIENT = httpx.AsyncClient


@server.list_tools()
async def tools():
    return [Tool(**item) for item in catalog()]


@server.call_tool()
async def call(name, arguments):
    entry = next((t for t in catalog() if t['name'] == name), None)
    sent = False
    try:
        if entry is None:
            raise ValueError('Unknown tool')
        token = token_path().read_text(encoding='utf-8').strip()
        base = os.environ.get('VITRUVIUS_URL', 'http://127.0.0.1:5191').rstrip('/')
        async with HTTP_CLIENT(timeout=entry.get('x-timeout-s', 1800), trust_env=False) as client:
            request = client.build_request('POST', base + '/api/agent/call', headers={'Authorization':'Bearer ' + token},
                                           json={'name':name,'arguments':arguments})
            # A transport hook marks the boundary after the connection is made.
            async def trace(event, info):
                nonlocal sent
                if event.endswith('send_request_headers.started'):
                    sent = True
            request.extensions['trace'] = trace
            response = await client.send(request)
            response.raise_for_status()
            result = response.json()
    except Exception as error:
        if isinstance(error, httpx.HTTPStatusError):
            try:
                result = error.response.json()
            except ValueError:
                result = {'error':str(error),'code':'vitruvius_unavailable'}
            return CallToolResult(content=[TextContent(type='text',text=json.dumps(result))],isError=True)
        uncertain = sent and entry and not entry.get('annotations', {}).get('readOnlyHint', False) and not isinstance(error, httpx.HTTPStatusError)
        result = {'error':str(error), 'code':'outcome_unknown' if uncertain else 'vitruvius_unavailable'}
        if uncertain:
            result.update(outcome_unknown=True, reconcile_action='read_current_state_before_retry')
        return CallToolResult(content=[TextContent(type='text',text=json.dumps(result))],isError=True)
    if name=='theseus_artifact_image':
        data=result['result'].pop('base64')
        return [TextContent(type='text',text=json.dumps(result,ensure_ascii=False)),ImageContent(type='image',data=data,mimeType=result['result']['media_type'])]
    return [TextContent(type='text',text=json.dumps(result,ensure_ascii=False))]


async def main():
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(main())
