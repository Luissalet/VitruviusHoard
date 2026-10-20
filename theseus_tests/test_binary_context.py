import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest

from theseus.binary_context import compose
from theseus.api import create_app

ADDRESS = 'ram:0xffff800000001000'
OTHER = 'ram:0xffff800000002000'
SESSION = {'id':'original-session', 'result':{'artifact_sha256':'a'*64,'profile_sha256':'b'*64,'revision':7}}


class Provider:
    def __init__(self, outside=False, unavailable=(), move_cursor=False):
        self.requests=[];self.unavailable=set(unavailable);self.outside=outside
        self.cursor=ADDRESS;self.move_cursor=move_cursor
        self.marks=[{'address':ADDRESS,'type':'Note','category':'A','text':'Original ñ😀'},
                    {'address':OTHER,'type':'Note','category':'A','text':'Other address'},
                    {'address':ADDRESS,'type':'Note','category':'B','text':'Second occurrence'}]

    def request(self, method, parameters):
        self.requests.append((method,copy.deepcopy(parameters)));key=len(self.requests)
        if method!='current_document' and parameters.get('document')!='bound.dll':
            return {'id':key,'ok':False,'error':{'code':'not_found','message':'Wrong bound document'}}
        if method in self.unavailable:
            return {'id':key,'ok':False,'error':{'code':'unsupported_capability','message':'Facet not supported'}}
        if method=='current_document':value='bound.dll'
        elif method=='current_address':
            value=self.cursor
            if self.move_cursor:self.cursor=OTHER
        elif method=='resolve_containing_procedure':
            # This query must follow the address actually observed, even if the
            # provider's cursor moved immediately after returning that address.
            address=parameters['address']
            value={'query_address':address,'found':not self.outside,
                   'procedure':None if self.outside else {'address':address,'name':'original_rule'}}
            if self.outside:value['reason']='not_in_procedure'
        elif method=='address_name':value='analyst_name'
        elif method=='comment':value='PRE ñ😀\r\nsecond line'
        elif method=='inline_comment':value=None
        elif method=='list_bookmarks':value=copy.deepcopy(self.marks)
        else:pytest.fail('Unexpected provider request: '+method)
        return {'id':key,'ok':True,'result':value}


def run(provider, operation='inspect_address_context', parameters=None):
    return compose(provider,SESSION,operation,parameters if parameters is not None else ({'address':ADDRESS} if operation=='inspect_address_context' else {}),lambda:None)


def test_navigation_uses_observed_address_after_cursor_moves_and_preserves_sequence():
    provider=Provider(move_cursor=True);reply=run(provider,'get_navigation_context');value=reply['result']
    assert value['document']=='bound.dll' and value['address']==ADDRESS and provider.cursor==OTHER
    assert value['procedure']['address']==ADDRESS
    assert provider.requests==[('current_document',{}),('current_address',{'document':'bound.dll'}),
        ('resolve_containing_procedure',{'document':'bound.dll','address':ADDRESS})]
    assert value['observation_consistency']=='sequential-provider-observations'
    assert [r['response']['id'] for r in value['observations']]==[1,2,3]
    assert value['binding']['analysis_revision']==7 and SESSION['result']['revision']==7
    assert value['observations'][1]['response']['result']==ADDRESS


def test_address_context_retains_exact_values_and_every_matching_bookmark():
    provider=Provider();value=run(provider)['result']
    assert value['name']=='analyst_name' and value['comment']=='PRE ñ😀\r\nsecond line' and value['inline_comment'] is None
    assert value['facets']['inline_comment']['status']=='available'
    assert value['bookmarks']==[provider.marks[0],provider.marks[2]]
    source=value['observations'][value['facets']['bookmarks']['source_observation']]
    assert source['response']['result']==provider.marks
    assert provider.cursor==ADDRESS and all(not method.startswith(('set_','goto_')) for method,_ in provider.requests)


@pytest.mark.parametrize('operation',['get_navigation_context','inspect_address_context'])
def test_no_containing_procedure_is_an_observed_null_not_an_unavailable_facet(operation):
    value=run(Provider(outside=True),operation)['result']
    assert value['procedure'] is None and value['facets']['procedure']['status']=='available'
    assert value['facets']['procedure']['absence_reason']=='not_in_procedure'


def test_unsupported_facets_are_typed_and_do_not_invent_empty_comments_or_bookmarks():
    value=run(Provider(unavailable={'address_name','comment','inline_comment','list_bookmarks'}))['result']
    for name in ['name','comment','inline_comment','bookmarks']:
        assert value[name] is None and value['facets'][name]['status']=='unavailable'
        source=value['observations'][value['facets'][name]['source_observation']]
        assert source['response']['error']['code']=='unsupported_capability'


def test_unsupported_procedure_retains_unknown_canonical_address_and_bookmark_matching():
    value=run(Provider(unavailable={'resolve_containing_procedure'}))['result']
    assert value['requested_address']==ADDRESS and value['address'] is None and value['procedure'] is None
    assert value['facets']['procedure']['status']==value['facets']['address']['status']=='unavailable'
    assert value['bookmarks'] is None and value['facets']['bookmarks']['status']=='unavailable'
    assert len(value['observations'][-1]['response']['result'])==3
    navigation=run(Provider(unavailable={'resolve_containing_procedure'}),'get_navigation_context')['result']
    assert navigation['address']==ADDRESS and navigation['facets']['address']['status']=='available'


def test_wrong_document_fails_with_completed_observations_and_no_other_queries():
    provider=Provider();reply=run(provider,parameters={'document':'other.dll','address':ADDRESS})
    assert reply['ok'] is False and reply['error']['code']=='not_found'
    assert [row['operation'] for row in reply['observations']]==['current_document','resolve_containing_procedure']
    assert len(provider.requests)==2


@pytest.mark.parametrize('parameters',[{},{'address':''},{'address':None},{'address':1},{'address':ADDRESS,'document':''},{'address':ADDRESS,'extra':True}])
def test_invalid_input_is_rejected_before_any_native_request(parameters):
    provider=Provider()
    with pytest.raises(ValueError):run(provider,parameters=parameters)
    assert provider.requests==[]


def test_cancellation_never_repeats_completed_reads():
    provider=Provider();calls=0
    def active():
        nonlocal calls
        calls+=1
        if calls==3:raise InterruptedError('Original cancellation')
    with pytest.raises(InterruptedError):compose(provider,SESSION,'inspect_address_context',{'address':ADDRESS},active)
    assert [method for method,_ in provider.requests]==['current_document','resolve_containing_procedure']


@pytest.mark.skipif(os.environ.get('THESEUS_TEST_GHIDRA')!='1',reason='Opt-in installed Ghidra/native compiler integration')
def test_real_native_context_annotations_navigation_records_and_transfer(tmp_path,monkeypatch):
    from theseus.binary_analysis import engines
    from test_binary_sessions import wait
    setup=Path('C:/Program Files/Microsoft Visual Studio/18/Community/VC/Auxiliary/Build/vcvars64.bat')
    if not setup.is_file() or not engines()['available']:pytest.skip('Requires installed native compiler/Ghidra/JDK')
    original=tmp_path/'original';original.mkdir();source=original/'original.c'
    source.write_text('__declspec(dllexport) __declspec(noinline) int original_rule(int x) { return x*7+11; }\n'
        '__declspec(dllexport) const char *original_text="Original native context fixture";\n',encoding='utf8')
    script=original/'compile.cmd';script.write_text('@echo off\ncall "'+str(setup)+'" >nul\nif errorlevel 1 exit /b 1\n'
        'cl /nologo /c /Od /GS- original.c /Fooriginal.obj\nif errorlevel 1 exit /b 1\n'
        'link /nologo /DLL /NOENTRY /NODEFAULTLIB /OUT:original.dll original.obj\nexit /b %errorlevel%\n',encoding='utf8')
    compiled=subprocess.run(['cmd.exe','/d','/c',str(script)],cwd=original,capture_output=True)
    assert compiled.returncode==0,(compiled.stdout+compiled.stderr).decode(errors='replace')
    binary=original/'original.dll';raw=binary.read_bytes();app=create_app(tmp_path/'profile',port=64218)
    with TestClient(app,base_url='http://127.0.0.1:64218') as client:
        client.get('/');store=app.state.store;pid=store.create_project('Original native context')['id']
        artifact=store.add_artifact(pid,binary)
        session=wait(client,client.post('/api/projects/'+pid+'/artifacts/'+artifact['id']+'/binary-sessions',json={}).json())
        assert session['state']=='finished',session
        def call(operation,parameters=None,expected='finished'):
            response=client.post('/api/binary-sessions/'+session['id']+'/call',json={'operation':operation,'parameters':parameters or {}})
            assert response.status_code==200,response.text
            job=wait(client,response.json());assert job['state']==expected,job
            return job,None if expected!='finished' else client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']
        _,address=call('procedure_address',{'procedure':'original_rule'})
        _,segments=call('list_segments');outside=None
        for segment in segments:
            if segment['executable']:continue
            _,observed=call('resolve_containing_procedure',{'address':segment['start']})
            if observed['found'] is False:outside=segment['start'];break
        assert outside is not None,'Original fixture must provide a mapped non-function address'
        call('set_address_name',{'address':address,'name':'analyst_rule'})
        call('set_comment',{'address':address,'text':'PRE observado ñ😀\nsegunda línea'})
        call('set_inline_comment',{'address':address,'text':'EOL observado'})
        for category,target in [('A',address),('B',address),('Elsewhere',outside)]:
            call('set_bookmark',{'address':target,'type':'Note','category':category,'text':'Marca '+category})
        call('goto_address',{'address':address});revision=store.job(session['id'])['result']['revision']
        nav_job,navigation=call('get_navigation_context')
        assert navigation['address']==address and navigation['procedure']['address']==address
        assert navigation['procedure']['name']=='analyst_rule' and navigation['document']==binary.name
        context_job,context=call('inspect_address_context',{'address':address})
        assert context['name']=='analyst_rule' and context['comment']=='PRE observado ñ😀\nsegunda línea'
        assert context['inline_comment']=='EOL observado' and {'A','B'}.issubset({r['category'] for r in context['bookmarks']})
        _,all_marks=call('list_bookmarks')
        assert context['bookmarks']==[row for row in all_marks if row['address']==address]
        assert all(r['address']==address for r in context['bookmarks'])
        assert store.job(session['id'])['result']['revision']==revision
        _,selected=call('current_address');assert selected==address
        call('goto_address',{'address':outside});_,outside_navigation=call('get_navigation_context')
        assert outside_navigation['procedure'] is None and outside_navigation['facets']['procedure']['status']=='available'
        failed,_=call('inspect_address_context',{'address':address,'document':'not-the-bound-program'},expected='failed')
        assert failed['result']['engine_response']['observations']
        catalogue=client.get('/api/binary-sessions/catalog').json()['operations']
        for row in catalogue:
            if row['name'] in {'get_navigation_context','inspect_address_context'}:
                assert not row['writes_analysis_project'] and row['source']=='product-composition'
        document=client.get('/api/jobs/'+context_job['id']+'/analysis.json').content
        assert binary.read_bytes()==raw and context['binding']['artifact_sha256']==hashlib.sha256(raw).hexdigest()
        call('shutdown');portable=app.state.evidence.export(pid)
        retired_paths={str(original),*[str(path) for path in original.iterdir()]}
        for path in original.iterdir():
            assert path.is_file() and not path.is_symlink();path.unlink()
        original.rmdir()
        real_exists=Path.exists
        def guarded_exists(path):
            if str(path) in retired_paths:pytest.fail('Retained context checked an original source path')
            return real_exists(path)
        monkeypatch.setattr(Path,'exists',guarded_exists)
        loaded=app.state.evidence.load(portable);key=loaded['id_map'][context_job['id']]
        assert client.get('/api/jobs/'+key+'/analysis.json').content==document
        assert not client.get('/api/projects/'+loaded['project']['id']).json()['runtime_sessions']
        rows=store.analysis_records(key,section='observations',limit=None)
        assert len(rows['records'])==len(context['observations'])
