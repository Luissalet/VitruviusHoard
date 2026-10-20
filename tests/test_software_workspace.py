from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.responses import StreamingResponse
import asyncio
import io
import zipfile
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

ROOT=Path(__file__).resolve().parents[1]
os.environ['HOARD_EVENTS']='0'


def test_cold_discovery_no_factories_stores_threads(tmp_path):
    code="""
import sys,os,threading
from pathlib import Path
before=set(threading.enumerate())
from vitruvius_hoard.software.host import catalog
import mcp_server
assert len(catalog())==124
assert len({t['name'] for t in catalog()})==124
assert any(t['name']=='theseus_client_inspect' for t in catalog())
assert not any(n in sys.modules for n in ('vitruvius_hoard.main','vitruvius_hoard.services','babels_hoard.api','theseus.api'))
assert not Path(os.environ['VITRUVIUS_PROFILE_DIR']).exists()
assert set(threading.enumerate())==before
print('cold124 PASS')
"""
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env={**os.environ,'VITRUVIUS_PROFILE_DIR':str(tmp_path/'profile')},capture_output=True,text=True)
    assert result.returncode==0,result.stderr


@pytest.mark.asyncio
async def test_native_project_revision_environment_artifact_result_roundtrip(tmp_path,monkeypatch):
    monkeypatch.setenv('VITRUVIUS_PROFILE_DIR',str(tmp_path))
    from vitruvius_hoard.software.host import create_app
    app=create_app()
    async with app.router.lifespan_context(app):
        call=app.state.execute
        for module in ('design','babel','theseus'):
            await call('software_module_set',{'module':module,'enabled':True})
        project=await call('app_project_create',{'name':'Synthetic software project'})
        project=await call('app_project_update',{'id':project['id'],'expected_revision':project['selected_revision'],
            'files':{'utility.py':'def title():\n    return "/api/keep-exact"\n','fixture.plist':'<?xml version="1.0"?><plist version="1.0"><dict><key>name</key><string>synthetic</string></dict></plist>'}})
        args={'project_id':project['id'],'source_revision':project['selected_revision']}
        env=(await call('docs_libraries',{}))['environments'][0]['id']
        link=await call('software_environment_link',{**args,'environment_id':env})
        check=await call('software_check',{**args,'environment_id':env,'file':'utility.py'})
        assert check['source_sha256']==project['source_sha256']
        assert check['file_sha256']==hashlib.sha256(project['files']['utility.py'].encode()).hexdigest()
        assert check['environment_id']==env and check['kind']=='check'
        revision=await call('software_environment_link',{**args,'environment_id':env,'reference_id':link['id'],'expected_revision':1})
        assert revision['revision']==2
        with pytest.raises(ValueError,match='Reference changed'):
            await call('software_environment_link',{**args,'environment_id':env,'reference_id':link['id'],'expected_revision':1})
        artifact=await call('software_inspect',{**args,'file':'fixture.plist'})
        assert artifact['native']['sha256']==artifact['file_sha256']
        native={'native_project_id':artifact['native_project_id'],'artifact_id':artifact['artifact_id'],'file':'fixture.plist'}
        started=await call('software_analysis_start',{**args,**native,'operation':'apple.plist'})
        for _ in range(200):
            job=(await call('theseus_job_read',{'job_id':started['native']['id']}))['result']
            if job['state'] not in ('queued','running'):break
            await asyncio.sleep(.01)
        assert job['state']=='finished',job
        result=await call('software_result_retain',{**args,**native,'job_id':job['id']})
        assert result['native']['result']['artifact_sha256']==artifact['file_sha256']
        assert result['native']['retained_analysis']['artifact_sha256']==artifact['file_sha256']
        assert result['native_sha256']
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:5191') as client:
            for module,marker in [('design','/design/assets/'),('babel','/babel/assets/'),('theseus','/theseus/static/app.js')]:
                page=await client.get('/'+module+'/')
                assert page.status_code==200,page.text
                assert marker in page.text
                assert '/'+module+'/'+module+'/' not in page.text
            assert 'incompleto y en curso' in (await client.get('/theseus/')).text
            assert '20 de octubre de 2026' in (await client.get('/theseus/')).text
            fetched=await client.get('/design/api/app-projects/'+project['id'])
            # The normal JSON source API must not rewrite user literals.
            assert '/api/keep-exact' in fetched.text and '/design/api/keep-exact' not in fetched.text
            bundle=await client.post('/design/api/app-projects/'+project['id']+'/export',json={'revision':project['selected_revision']})
            assert bundle.status_code==200,bundle.text
            path='/design'+bundle.json()['download_url']
            full=await client.get(path)
            assert full.status_code==200
            with zipfile.ZipFile(io.BytesIO(full.content)) as archive:
                assert archive.read('utility.py')==project['files']['utility.py'].encode()
            partial=await client.get(path,headers={'Range':'bytes=0-9'})
            assert partial.status_code==206 and partial.content==full.content[:10]
        changed=await call('app_project_update',{'id':project['id'],'expected_revision':project['selected_revision'],'files':{'utility.py':'def title(): return "changed"\n'}})
        assert changed['selected_revision']!=project['selected_revision']
        with pytest.raises(ValueError,match='Link the explicit environment'):
            await call('software_check',{'project_id':project['id'],'environment_id':env,'file':'utility.py'})
        for module in ('design','babel','theseus'):
            await call('software_module_set',{'module':module,'enabled':False})
        refs=(await call('software_references',{'project_id':project['id']}))['references']
        assert any(r['native_sha256']==result['native_sha256'] for r in refs)
        assert all(r['source_revision']==project['selected_revision'] for r in refs)
        await call('software_module_set',{'module':'design','enabled':True})
        historical=(await call('software_project_read',args))['project']
        assert historical['files']['utility.py']==project['files']['utility.py']


@pytest.mark.asyncio
async def test_theseus_native_frontend_uses_mounted_api_and_owner_limits(tmp_path,monkeypatch):
    monkeypatch.setenv('VITRUVIUS_PROFILE_DIR',str(tmp_path))
    from vitruvius_hoard.software.host import create_app
    app=create_app()
    async with app.router.lifespan_context(app):
        await app.state.execute('software_module_set',{'module':'theseus','enabled':True})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://127.0.0.1:5191') as client:
            page=await client.get('/theseus/')
            assert page.status_code==200
            assert 'href="/api/software/theseus-limits"' in page.text
            limits=await client.get('/api/software/theseus-limits')
            assert limits.status_code==200 and limits.content==(ROOT/'software_native/theseus-limits.md').read_bytes()
            script=await client.get('/theseus/static/app.js')
            helper=script.text[script.text.index('async function api('):script.text.index('\nfunction notice(')]
            # Run the shipped request helper, then route its captured URL through
            # the actual mounted application. No browser or engine is simulated.
            probe='const calls=[];const fetch=async(url)=>{calls.push(url);return {ok:true,json:async()=>({})}};const json=JSON.stringify;'+helper+';api("/projects").then(()=>console.log(JSON.stringify(calls)));'
            result=subprocess.run(['node','-e',probe],capture_output=True,text=True,check=True)
            assert json.loads(result.stdout)==['/theseus/api/projects']
            created=await client.post('/theseus/api/projects',json={'name':'Mounted native project'})
            assert created.status_code==200,created.text
            projects=await client.get(json.loads(result.stdout)[0])
            assert created.json()['id'] in [p['id'] for p in projects.json()['projects']]
            assert all(m.state=='off' for name,m in app.state.runtime.modules.items() if name!='theseus')


@pytest.mark.asyncio
async def test_stdio_catalog_and_native_handlers(tmp_path):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    from vitruvius_hoard.software.host import catalog
    params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'tests/fixtures/software_mcp.py')],cwd=str(ROOT),env={**os.environ,'VITRUVIUS_PROFILE_DIR':str(tmp_path),'HOARD_EVENTS':'0','PYTHONUTF8':'1'})
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer) as session:
            await session.initialize()
            tools=(await session.list_tools()).tools
            assert len(tools)==124
            for native in catalog():
                assert next(t for t in tools if t.name==native['name']).inputSchema==native['inputSchema']
            async def call(name,args=None):
                res=await session.call_tool(name,args or {})
                assert not res.isError,res.content
                return json.loads(res.content[0].text)
            status=await call('software_modules')
            assert all(not m['enabled'] for m in status['modules'])
            assert 'incomplete and in progress' in status['theseus_status']
            assert '20 October 2026' in status['theseus_status']
            await call('software_module_set',{'module':'design','enabled':True})
            project=await call('app_project_create',{'name':'MCP synthetic project'})
            await call('software_module_set',{'module':'theseus','enabled':True})
            ref=await call('software_inspect',{'project_id':project['id'],'file':'server.py'})
            assert ref['artifact_id'] and ref['native']['sha256']==ref['file_sha256']
            for module in ('design','theseus'):await call('software_module_set',{'module':module,'enabled':False})
            assert (await call('software_references',{'project_id':project['id']}))['references'][0]['id']==ref['id']


@pytest.mark.asyncio
async def test_cancel_drain_and_independent_close():
    from vitruvius_hoard.software.runtime import Module
    module = Module('theseus')
    entered, released, closing, release_close = (asyncio.Event() for _ in range(4))
    @asynccontextmanager
    async def lifetime(app):
        yield
        assert released.is_set()
        closing.set()
        await release_close.wait()
    app = FastAPI(lifespan=lifetime)
    async def chunks():
        try:
            entered.set()
            yield b'partial'
            await asyncio.Event().wait()
        finally:
            released.set()
    @app.get('/retained')
    async def retained():
        return StreamingResponse(chunks())
    module.create = lambda: app
    await module.set(True)
    async def receive():
        await asyncio.Event().wait()
    async def send(message):
        pass
    scope={'type':'http','asgi':{'spec_version':'2.4'},'method':'GET','path':'/retained','root_path':'','query_string':b'','headers':[],'scheme':'http','server':('127.0.0.1',5219),'client':('127.0.0.1',1),'http_version':'1.1'}
    request=asyncio.create_task(module(scope,receive,send))
    await entered.wait()
    off=asyncio.create_task(module.set(False))
    await closing.wait()
    assert not off.done() and module.state=='stopping'
    other=Module('design')
    other.create=lambda:FastAPI()
    await other.set(True)
    assert other.status()['enabled']
    release_close.set()
    await off
    assert module.state=='off' and module.active==0
    await asyncio.gather(request,return_exceptions=True)
    await module.set(True)
    await module.set(False)
    await other.set(False)



@pytest.mark.asyncio
async def test_owned_node_analysis_reads_source_without_executing_it(tmp_path,monkeypatch):
    monkeypatch.setenv('VITRUVIUS_PROFILE_DIR',str(tmp_path))
    from vitruvius_hoard.software.host import create_app
    app=create_app()
    async with app.router.lifespan_context(app):
        call=app.state.execute
        for module in ('design','theseus'):
            await call('software_module_set',{'module':module,'enabled':True})
        project=await call('app_project_create',{'name':'Synthetic Node source'})
        marker=tmp_path/'must-not-execute'
        source='import fs from "node:fs";\nfs.writeFileSync('+json.dumps(str(marker))+',"executed");\nexport function greet(name){return `Hello ${name}`;}\n'
        project=await call('app_project_update',{'id':project['id'],'expected_revision':project['selected_revision'],'files':{'fixture.js':source}})
        args={'project_id':project['id'],'source_revision':project['selected_revision'],'file':'.'}
        artifact=await call('software_inspect',args)
        native={'native_project_id':artifact['native_project_id'],'artifact_id':artifact['artifact_id']}
        started=await call('software_analysis_start',{**args,**native,'operation':'javascript.application'})
        for _ in range(1000):
            job=(await call('theseus_job_read',{'job_id':started['native']['id']}))['result']
            if job['state'] not in ('queued','running'):break
            await asyncio.sleep(.01)
        assert job['state']=='finished',job
        assert not marker.exists()
        assert job['result']['artifact_sha256']==artifact['source_tree_sha256']
        retained=await call('software_result_retain',{**args,**native,'job_id':job['id']})
        assert retained['native_sha256'] and retained['source_tree_sha256']==artifact['source_tree_sha256']

@pytest.mark.asyncio
async def test_cancel_off_and_close_join_one_retained_cleanup():
    from vitruvius_hoard.software.runtime import Module,Runtime
    entered,cleaning,released,finished=(asyncio.Event() for _ in range(4))
    module=Module('theseus')
    app=FastAPI()
    async def content():
        try:
            entered.set()
            yield b'first'
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await released.wait()
            finished.set()
    @app.get('/held')
    async def held():return StreamingResponse(content())
    module.create=lambda:app
    runtime=Runtime();runtime.modules['theseus']=module
    await module.set(True)
    async def receive():await asyncio.Event().wait()
    async def send(message):pass
    scope={'type':'http','asgi':{'spec_version':'2.4'},'method':'GET','path':'/held','root_path':'','query_string':b'','headers':[],'scheme':'http','server':('127.0.0.1',5191),'client':('127.0.0.1',1),'http_version':'1.1'}
    request=asyncio.create_task(module(scope,receive,send))
    await entered.wait();request.cancel();await cleaning.wait()
    off=asyncio.create_task(module.set(False))
    close=asyncio.create_task(runtime.close())
    await asyncio.sleep(0)
    request.cancel();off.cancel();close.cancel()
    await asyncio.sleep(0)
    assert module.state=='stopping' and not finished.is_set()
    assert not off.done() and not close.done()
    released.set()
    await asyncio.gather(request,off,close,return_exceptions=True)
    assert finished.is_set() and module.state=='off' and module.active==0
