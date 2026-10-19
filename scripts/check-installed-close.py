"""Run only owned shutdown regressions against an external installed target.

The source test file is a harness, loaded without pytest discovery/conftest.
Every imported product file must reside in TARGET; no checkout imports allowed.
"""
import argparse
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import runpy
import socket
import sys
import zipfile
import pytest


async def verify(args, report):
    target=args.target.resolve()
    assert not Path.cwd().resolve().is_relative_to(args.source.resolve())
    sys.path.insert(0,str(target))
    os.environ.update(HOARD_EVENTS='0', COASE_OFFLINE='1', VITRUVIUS_EMBED='none')
    package='vitruvius_hoard.software' if args.case=='933' else 'coase_hoard.consolidation'
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='installed-close-',dir=Path.cwd()) as temporary:
        assert Path(temporary).resolve().is_relative_to(Path.cwd().resolve())
        cold=Path(temporary)/'cold'
        env='VITRUVIUS_PROFILE_DIR' if args.case=='933' else 'COASE_PROFILE_DIR'
        os.environ[env]=str(cold)
        host=importlib.import_module(package+'.host')
        importlib.import_module('mcp_server')
        assert len(host.catalog())==(110 if args.case=='933' else 86)
        assert not cold.exists()
        pair_code=getattr(socket.socketpair,'__code__',None)
        def guard(original):
            def blocked(*a,**kw):
                frame=sys._getframe(1)
                while frame is not None:
                    if frame.f_code is pair_code:return original(*a,**kw)
                    frame=frame.f_back
                raise AssertionError('No external sockets in installed shutdown QA')
            return blocked
        socket.socket.connect=guard(socket.socket.connect)
        socket.socket.bind=guard(socket.socket.bind)
        tests=runpy.run_path(str(args.tests.resolve()))
        cases=['design','babel','theseus'] if args.case=='933' else ['dossiers','markets']
        test_name='test_real_native_factory_two_failures_and_effective_third_off' if args.case=='933' else 'test_real_factory_two_failed_closes_then_success'
        report['real_factories']=[]
        for name in cases:
            with pytest.MonkeyPatch.context() as patch:
                await tests[test_name](name,Path(temporary)/name,patch)
            report['real_factories'].append({'module':name,'failed_off':2,'effective_close':3,'duplicate_on_rejected':True})
        if args.case=='933':
            await tests['test_failed_generic_lifespan_is_retained_without_retry_callback']()
            await tests['test_retry_cleanup_keeps_successful_steps_and_survives_caller_cancel']()
            report['generic_retained_and_cancel_join']=True
        else:
            with pytest.MonkeyPatch.context() as patch:
                paths=Path(temporary)/'paths';paths.mkdir()
                tests['test_profile_and_token_selection_preserve_checkout_and_explicit_values'](paths,patch)
            workflow=runpy.run_path(str(args.source/'tests/test_consolidation.py'))
            with pytest.MonkeyPatch.context() as patch:
                await workflow['test_native_workflow_and_revisions'](Path(temporary)/'workflow',patch)
            report['installed_native_workflow_and_revisions']=True
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        code='import sys,runpy;sys.path.insert(0,'+repr(str(target))+');runpy.run_module("mcp_server",run_name="__main__")'
        params=StdioServerParameters(command=sys.executable,args=['-I','-c',code],cwd=str(Path.cwd()),env={**os.environ,env:str(cold)})
        async with stdio_client(params) as (reader,writer):
            async with ClientSession(reader,writer) as session:
                await session.initialize()
                tools=(await session.list_tools()).tools
                assert {tool.name:tool.inputSchema for tool in tools}=={tool['name']:tool['inputSchema'] for tool in host.catalog()}
        assert not cold.exists()
        report['installed_stdio_cold_exact_schemas']=len(tools)
        prefixes=('vitruvius_hoard','babels_hoard','theseus','software_native','babel_client','hoard_link','mcp_server') if args.case=='933' else ('coase_hoard','midas_hoard','hoard_link','mcp_server')
        imports={name:str(Path(module.__file__).resolve()) for name,module in sys.modules.items()
                 if name.split('.')[0] in prefixes and getattr(module,'__file__',None)}
        assert imports and all(Path(path).is_relative_to(target) for path in imports.values()),imports
        report['imports']=imports
    with zipfile.ZipFile(args.wheel) as wheel:
        names=wheel.namelist()
        assert 'mcp_server.py' in names
        assert not [n for n in names if {'node_modules','data','__pycache__','.venv','.env','.git'}.intersection(Path(n).parts) or Path(n).name.endswith(('.db','.pyc'))]
        for name in names:
            if not name.endswith('/') and not name.endswith('.dist-info/RECORD'):
                assert wheel.read(name)==(target/name).read_bytes(),name
        report['wheel']={'bytes':args.wheel.stat().st_size,'sha256':hashlib.sha256(args.wheel.read_bytes()).hexdigest(),'members':len(names)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['932','933'],required=True)
    for key in ('target','source','tests','wheel','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();report={'status':'STARTED','case':args.case,'cwd':str(Path.cwd())}
    try:
        asyncio.run(verify(args,report));report['status']='PASS'
    except BaseException as error:
        report.update(status='FAIL',error=repr(error));raise
    finally:args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({key:value for key,value in report.items() if key!='imports'},indent=2))
