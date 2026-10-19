"""Verify a wheel installed with pip --target, from outside its source checkout.

Run with the candidate's Python -I. Only product modules from --target are
accepted. HTTP stays in ASGI memory; real Node analysis reads synthetic source.
Install engine runtime dependencies in TARGET/software_native/engine first.
"""
import argparse
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import socket
import sys
import threading
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


async def verify(args, report):
    target, profile = args.target.resolve(), args.profile.resolve()
    source = Path(__file__).resolve().parents[1]
    assert not Path.cwd().resolve().is_relative_to(source), 'Run outside the worktree'
    assert not target.is_relative_to(source) and not profile.is_relative_to(target)
    assert not profile.exists(), 'Use a fresh synthetic profile'
    sys.path.insert(0, str(target))
    os.environ.update(VITRUVIUS_PROFILE_DIR=str(profile), HOARD_EVENTS='0',
                      VITRUVIUS_EMBED='none', VITRUVIUS_AUTOSTART='0', VITRUVIUS_EMBED_AUTO='0')
    before = set(threading.enumerate())
    from vitruvius_hoard.software.host import catalog, create_app
    import mcp_server
    from vitruvius_hoard.software import runtime
    assert runtime.ROOT == target
    assert len(catalog()) == 110
    assert not any(n in sys.modules for n in ('vitruvius_hoard.main', 'babels_hoard.api', 'theseus.api'))
    assert not profile.exists() and set(threading.enumerate()) == before
    report['cold_catalog'] = 110
    # Check installed default without creating it, then restore explicit profile.
    del os.environ['VITRUVIUS_PROFILE_DIR']
    os.environ['LOCALAPPDATA'] = str(profile.parent / 'synthetic-localappdata')
    assert runtime.profile() == profile.parent / 'synthetic-localappdata/VitruviusHoard/data'
    os.environ['VITRUVIUS_PROFILE_DIR'] = str(profile)
    report['installed_default_external'] = True
    with zipfile.ZipFile(args.wheel) as wheel:
        members = wheel.namelist()
        assert 'mcp_server.py' in members
        forbidden = {'node_modules', '__pycache__', 'data', '.venv', '.env', '.git', '.pytest_cache'}
        assert not [p for p in members if forbidden.intersection(Path(p).parts) or Path(p).name.endswith(('.db', '.pyc'))]
        assert not [p for p in members if Path(p).name.startswith('.env')]
        rows = []
        for name in members:
            if name.endswith('/'):
                continue
            data = wheel.read(name)
            # pip rewrites RECORD to account for installed scripts/bytecode.
            if not name.endswith('.dist-info/RECORD'):
                assert (target/name).read_bytes() == data, name
            rows.append({'path':name, 'bytes':len(data), 'sha256':digest(data)})
        report['wheel'] = {'sha256':digest(args.wheel.read_bytes()), 'bytes':args.wheel.stat().st_size,
                           'members':len(rows), 'inventory':rows}
        builds = json.loads(args.assets.read_text(encoding='utf8'))['builds']
        for build in builds.values():
            for row in build['files']:
                data = wheel.read(row['path'])
                assert len(data) == row['size'] and digest(data) == row['sha256'], row['path']
        report['real_builds_exact'] = {name:len(build['files']) for name,build in builds.items()}
    # Block every TCP connection after asyncio's private bootstrap socketpair.
    # ASGI requests and subprocess pipes need no TCP listener or personal service.
    pair_code = getattr(socket.socketpair, '__code__', None)
    def guard(original):
        def blocked(*a, **kw):
            frame = sys._getframe(1)
            while frame is not None:
                if frame.f_code is pair_code:
                    return original(*a, **kw)
                frame = frame.f_back
            raise AssertionError('External socket access is forbidden in installed QA')
        return blocked
    socket.socket.connect = guard(socket.socket.connect)
    socket.socket.bind = guard(socket.socket.bind)
    import httpx
    app = create_app()
    async with app.router.lifespan_context(app):
        call = app.state.execute
        initial = await call('software_modules', {})
        assert all(row['state']=='off' and not row['automatic'] for row in initial['modules'])
        report['initial'] = initial
        for name in ('design', 'babel', 'theseus'):
            assert (await call('software_module_set', {'module':name, 'enabled':True}))['state']=='on'
        # Every module imports from the installed product, never its retired repo.
        report['imports'] = {}
        for name in ('vitruvius_hoard', 'babels_hoard', 'theseus', 'hoard_link', 'software_native', 'babel_client', 'mcp_server'):
            path = Path(importlib.import_module(name).__file__).resolve()
            assert path.is_relative_to(target), (name, path)
            report['imports'][name] = str(path)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:5191') as client:
            assets = []
            for name in ('design', 'babel', 'theseus'):
                page = await client.get('/'+name+'/')
                # Vite emits a small real HTML bootstrap; its exact build and
                # substantial JS/CSS are checked separately, not a 1KB HTML cap.
                assert page.status_code == 200 and len(page.content)>500, (name,page.status_code,len(page.content))
                if name=='theseus': assert 'pausado' in page.text
                urls = re.findall(r'(?:src|href)=["\']([^"\']+\.(?:js|css)(?:\?[^"\']*)?)["\']',page.text)
                assert urls, (name,page.text)
                for url in urls:
                    if not url.startswith('/'): url='/'+name+'/'+url.lstrip('./')
                    resource = await client.get(url)
                    assert resource.status_code == 200 and len(resource.content)>100, (url,resource.status_code)
                    assert 'text/html' not in resource.headers.get('content-type',''), url
                    assets.append({'url':url,'bytes':len(resource.content),'sha256':digest(resource.content)})
            assert (await client.get('/api/software/theseus-limits')).status_code==200
            report['ui_assets'] = assets
        project = await call('app_project_create', {'name':'Installed synthetic source'})
        marker = profile/'must-not-execute'
        source_text = 'import fs from "node:fs";\nfs.writeFileSync('+json.dumps(str(marker))+',"executed");\nexport function greet(name){return `Hello ${name}`;}\n'
        project = await call('app_project_update', {'id':project['id'],'expected_revision':project['selected_revision'],
                                                   'files':{'fixture.js':source_text,'utility.py':'def title(): return "/api/exact"\n'}})
        revision = {'project_id':project['id'],'source_revision':project['selected_revision']}
        environment = (await call('docs_libraries',{}))['environments'][0]['id']
        await call('software_environment_link', {**revision,'environment_id':environment})
        check = await call('software_check', {**revision,'environment_id':environment,'file':'utility.py'})
        assert check['source_sha256']==project['source_sha256'] and check['environment_id']==environment
        assert check['file_sha256']==digest(project['files']['utility.py'].encode())
        artifact = await call('software_inspect', {**revision,'file':'.'})
        native = {'native_project_id':artifact['native_project_id'],'artifact_id':artifact['artifact_id'],'file':'.'}
        started = await call('software_analysis_start', {**revision,**native,'operation':'javascript.application'})
        for _ in range(1000):
            job = (await call('theseus_job_read',{'job_id':started['native']['id']}))['result']
            if job['state'] not in ('queued','running'): break
            await asyncio.sleep(.01)
        assert job['state']=='finished', job
        assert not marker.exists()
        assert job['result']['artifact_sha256']==artifact['source_tree_sha256']
        result = await call('software_result_retain', {**revision,**native,'job_id':job['id']})
        assert result['native']['retained_analysis']['artifact_sha256']==artifact['source_tree_sha256']
        assert result['native_sha256'] and result['source_tree_sha256']==artifact['source_tree_sha256']
        changed = await call('app_project_update', {'id':project['id'],'expected_revision':project['selected_revision'],'files':{'utility.py':'def title(): return "changed"\n'}})
        assert changed['selected_revision']!=project['selected_revision']
        for name in ('design','babel','theseus'):
            assert (await call('software_module_set',{'module':name,'enabled':False}))['state']=='off'
            assert app.state.runtime.modules[name].app is None
        refs = (await call('software_references',{'project_id':project['id']}))['references']
        assert any(r['native_sha256']==result['native_sha256'] for r in refs)
        assert all(r['source_revision']==project['selected_revision'] for r in refs)
        for name in ('design','babel','theseus'):
            await call('software_module_set',{'module':name,'enabled':True})
        reopened = (await call('software_project_read',revision))['project']
        assert reopened['files']['fixture.js']==source_text and reopened['id']==project['id']
        assert (await call('theseus_job_read',{'job_id':job['id']}))['result']['id']==job['id']
        report['roundtrip'] = {'project_id':project['id'],'source_revision':project['selected_revision'],
                               'source_sha256':project['source_sha256'],'environment_id':environment,
                               **native,'tree_sha256':artifact['source_tree_sha256'],'job_id':job['id'],
                               'retained_sha256':result['native_sha256'],'historical_references':len(refs)}
    assert all(m.app is None and m.state=='off' for m in app.state.runtime.modules.values())
    report['on_off_on_closed'] = True
    # Real stdio discovery from installed module with an independent cold profile.
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    cold_profile = profile.parent / (profile.name+'-stdio')
    code = 'import sys,runpy;sys.path.insert(0,'+repr(str(target))+');runpy.run_module("mcp_server",run_name="__main__")'
    params = StdioServerParameters(command=sys.executable,args=['-I','-c',code],cwd=str(Path.cwd()),
                                  env={**os.environ,'VITRUVIUS_PROFILE_DIR':str(cold_profile)})
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            assert len(tools)==110
            assert {t.name for t in tools}=={t['name'] for t in catalog()}
    assert not cold_profile.exists()
    report['installed_stdio_cold'] = 110


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('target','wheel','profile','assets','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    report={'status':'STARTED','cwd':str(Path.cwd()),'target':str(args.target),'profile':str(args.profile)}
    try:
        asyncio.run(verify(args,report))
        report['status']='PASS'
    except BaseException as error:
        report['status']='FAIL'
        report['error']=repr(error)
        raise
    finally:
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('wheel','ui_assets')},ensure_ascii=True,indent=2))
