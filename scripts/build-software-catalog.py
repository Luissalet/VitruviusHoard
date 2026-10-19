"""Freeze metadata from native definitions without invoking factories."""
import asyncio
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['HOARD_EVENTS']='0'
from vitruvius_hoard.agent_tools import tool_catalog
from babels_hoard.mcp_server import mcp
from theseus.api import TOOLS
async def main():
    sources={'design':tool_catalog(),'babel':[t.model_dump(exclude_none=True) for t in await mcp.list_tools()],'theseus':TOOLS}
    rows=[{**tool,'module':name} for name,tools in sources.items() for tool in tools]
    if len(rows)!=len({r['name'] for r in rows}):raise ValueError('Duplicate native tool names')
    (ROOT/'vitruvius_hoard/software/catalog.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print({name:len(tools) for name,tools in sources.items()})
asyncio.run(main())
