"""Cold software-workspace host; all native lifetimes are explicitly owned."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from jsonschema import validate, ValidationError
from .runtime import Runtime,profile,token_path,ROOT,NativeError
from .cancellation import owned

HERE=Path(__file__).parent
S={'type':'string'}
PROJECT={'project_id':S,'source_revision':S}
VERSION={'reference_id':S,'expected_revision':{'type':'integer','minimum':0}}
ARTIFACT={**PROJECT,**VERSION,'file':S,'native_project_id':S,'artifact_id':S}


def control(name,description,props,required=(),read=False):
    return {'name':name,'description':description,'inputSchema':{'type':'object','properties':props,'required':list(required),'additionalProperties':False},'annotations':{'readOnlyHint':read,'destructiveHint':False,'idempotentHint':read,'openWorldHint':False}}


CONTROLS=[
 control('software_modules','Read independent module states and Theseus incomplete/paused status without loading engines.',{},read=True),
 control('software_module_set','Explicitly enable or drain a native module.',{'module':{'enum':['design','babel','theseus']},'enabled':{'type':'boolean'},'automatic':{'type':'boolean'}},('module','enabled')),
 control('software_projects','List native source projects.',{},read=True),
 control('software_project_read','Read selected project revision, files and retained linked results.',PROJECT,('project_id',),True),
 control('software_references','Read retained historical source/environment/results while engines are OFF.',{'project_id':S,'reference_id':S},read=True),
 control('software_environment_link','Bind an explicit existing or newly registered Babel environment to a project source revision.',{**PROJECT,**VERSION,'environment_id':S,'path':S},('project_id',)),
 control('software_check','Check a retained source file against its explicitly linked Babel environment and retain exact findings.',{**PROJECT,**VERSION,'environment_id':S,'file':S,'language':{'enum':['python','typescript']}},('project_id','file','environment_id')),
 control('software_inspect','Associate a retained source file with a native Theseus project/artifact, preserving exact SHA and revision.',{**PROJECT,**VERSION,'file':S,'native_project_id':S},('project_id','file')),
 control('software_analysis_start','Request an existing Theseus operation for an associated source artifact; no paused-scope development.',{**ARTIFACT,'operation':S,'parameters':{'type':'object'}},('project_id','file','native_project_id','artifact_id','operation')),
 control('software_result_retain','Retain a native analysis job/result under its original project/source revision and artifact hash.',{**ARTIFACT,'job_id':S},('project_id','file','native_project_id','artifact_id','job_id')),
]


def catalog():
    return [{k:v for k,v in row.items() if k!='module'} for row in json.loads((HERE/'catalog.json').read_text(encoding='utf8'))]+CONTROLS


def create_app(runtime=None):
    runtime=runtime or Runtime()
    @asynccontextmanager
    async def lifespan(app):
        from hoard_link.tokens import read_or_create_token
        read_or_create_token(token_path())
        try:
            yield
        finally:
            await runtime.close()
    app=FastAPI(title="Vitruvius's Hoard",lifespan=lifespan)
    app.state.runtime=runtime
    from hoard_link.guard import install_guard
    from .native import port
    install_guard(app,port_getter=port,allowed_env='VITRUVIUS_ALLOWED_HOSTS')

    async def execute(name,args):
        entry=next((t for t in catalog() if t['name']==name),None)
        if not entry:
            raise ValueError('Unknown tool')
        validate(args,entry['inputSchema'])
        if name=='software_modules':
            return {**runtime.status(),'theseus_status':'Existing capabilities; development incomplete and paused by Luis due to usage.'}
        if name=='software_module_set':
            return await runtime.modules[args['module']].set(args['enabled'],args.get('automatic',False))
        if name=='software_references':
            from .projects import retained
            return await owned(asyncio.to_thread(retained,**args))
        if name=='software_projects':
            owner=runtime.modules['design']
            if owner.state!='on':
                raise ValueError('Enable design explicitly first')
            owner.active+=1;owner.idle.clear()
            try:
                return {'projects':await owned(asyncio.to_thread(owner.app.state.services.app_projects.list))}
            finally:
                owner.active-=1
                if not owner.active: owner.idle.set()
        if name in {t['name'] for t in CONTROLS}:
            from .projects import Projects
            owners=[m for m in runtime.modules.values() if m.state=='on']
            for owner in owners:
                owner.active+=1;owner.idle.clear()
            try:
                return await owned(Projects(runtime,admitted=[m.name for m in owners]).execute(name,args))
            finally:
                for owner in owners:
                    owner.active-=1
                    if not owner.active: owner.idle.set()
        return await runtime.call(name,args)
    app.state.execute=execute

    @app.get('/api/software/theseus-limits')
    async def limits():
        return FileResponse(ROOT/'software_native/theseus-limits.md',media_type='text/plain')
    @app.get('/api/health')
    async def health():
        return {'ok':True,'service':'vitruvius-hoard',**runtime.status()}
    @app.get('/api/agent/tools')
    async def tools(): return {'tools':catalog()}
    @app.post('/api/ui/call')
    @app.post('/api/agent/call')
    async def call(request:Request):
        if request.url.path=='/api/agent/call':
            import secrets
            paths=[token_path()]+[profile()/name/'mcp-token' for name in runtime.modules]
            tokens=[p.read_text(encoding='utf8').strip() for p in paths if p.is_file()]
            if not any(secrets.compare_digest(request.headers.get('authorization',''),'Bearer '+token) for token in tokens):
                raise HTTPException(401,'Invalid bridge token')
        body=await request.json()
        return await execute(body['name'],body.get('arguments',{}))
    @app.exception_handler(ValueError)
    @app.exception_handler(LookupError)
    @app.exception_handler(ValidationError)
    @app.exception_handler(NativeError)
    async def error(request,error):
        if callable(getattr(error,'to_dict',None)):
            return JSONResponse(error.to_dict(),status_code=error.status)
        return JSONResponse({'error':str(error)},status_code=400)
    @app.get('/')
    async def home():
        if not getattr(app.state,'copilot_installed',False):
            from hoard_link.copilot import install_copilot
            install_copilot(app,'vitruvius',str(profile()/'design'),app_name="Vitruvius's Hoard",inject=False)
            app.state.copilot_installed=True
        return FileResponse(HERE/'web/index.html')
    app.mount('/workbench',StaticFiles(directory=HERE/'web'))
    app.mount('/theme',StaticFiles(directory=ROOT/'hoard_link/ui'))
    @app.get('/icon.png')
    @app.get('/icon-192.png')
    async def icon(): return FileResponse(ROOT/'vitruvius_hoard/static/icon-192.png')
    for name,module in runtime.modules.items(): app.mount('/'+name,module)
    return app


app=create_app()
