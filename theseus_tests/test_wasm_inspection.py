"""Independent original-byte and source-coordinate WASM observation checks."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.native_analysis import engine
from test_native_analysis import wait
from test_portfolio import run


# Hand-authored core module: echo(i32)->i32 plus an opaque custom payload.
ORIGINAL=bytes.fromhex('0061736d0100000001060160017f017f03020100070801046563686f00000a0601040020000b00080374616700ff1080')


def inspect(tmp_path,content=ORIGINAL,parameters=None):
    source=tmp_path/'original.wasm';source.write_bytes(content)
    with TestClient(create_app(tmp_path/'profile',port=64228),base_url='http://127.0.0.1:64228') as client:
        client.get('/');store=client.app.state.store;pid=store.create_project('Original core module')['id']
        artifact=store.add_artifact(pid,source)
        return run(client,pid,artifact['id'],'wasm.artifact',parameters)


def test_original_section_bytes_wat_digest_and_actual_bundled_reader_identity(tmp_path):
    node=engine()['node']
    validation=subprocess.run([node,'--input-type=module','-e',
        'process.stdout.write(String(WebAssembly.validate(Buffer.from(process.argv[1],"hex"))));',ORIGINAL.hex()],check=True,capture_output=True)
    assert validation.stdout==b'true'
    _,value=inspect(tmp_path)
    assert value['validation']=='valid' and value['completion_status']=='complete'
    assert value['artifact']['sha256']==hashlib.sha256(ORIGINAL).hexdigest() and value['artifact']['bytes']==48
    assert [(row['kind'],row['start'],row['end'],row['bytes']) for row in value['sections']]==[
        ('type',10,16,6),('function',18,20,2),('export',22,30,8),('code',32,38,6),('custom',40,48,8)]
    rebuilt=base64.b64decode(value['module_header']['base64'])
    for row in value['sections']:
        header=base64.b64decode(row['header']['base64']);payload=base64.b64decode(row['payload_base64'])
        assert payload==ORIGINAL[row['start']:row['end']] and hashlib.sha256(payload).hexdigest()==row['payload_sha256']
        assert header==ORIGINAL[row['header']['start']:row['start']]
        rebuilt+=header+payload
    assert rebuilt==ORIGINAL and value['sections_complete']
    assert value['wat_sha256']==hashlib.sha256(value['wat'].encode('utf8')).hexdigest()
    assert value['wat_bytes']==len(value['wat'].encode('utf8')) and value['wat_representation']=='decoded-wat'
    assert any(row['name']=='echo' and row['signature']=={'kind':'func','params':['i32'],'results':['i32']} for row in value['interface_entries'])
    profile=value['engine_profile'];assert profile['name']=='wabt.js' and profile['feature_policy']=='all-advertised-features'
    assert {'threads','memory64','multi_memory','function_references','gc'}<=set(profile['enabled_features'])
    for key in ['package_identity','implementation_identity']:
        identity=profile[key];raw=Path(identity['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==identity['sha256'] and len(raw)==identity['bytes']
        assert 'base64' not in identity
    assert json.loads(Path(profile['package_identity']['path']).read_text())['version']==profile['version']
    assert value['runtime_execution']==value['network_fetch']=='not-performed'


def test_directives_templates_exact_coordinates_and_ambiguous_selected_candidates(tmp_path):
    other=tmp_path/'other';other.mkdir();candidate=other/'original.wasm';candidate.write_bytes(b'Candidate identity does not certify a valid module')
    glue=tmp_path/'glue.js'
    source='"original\\x2ewasm";\nconst relative="./original.wasm";\nconst remote="https://unqueried.invalid/original.wasm?build=1";\nconst missing=`missing.wasm`;\nconst dynamic=`${stem}.wasm`;\nfunction nested(){ "original.wasm"; }\n'
    glue.write_text(source,encoding='utf8')
    bom=tmp_path/'bom.js';bom.write_text('\uFEFF#!/usr/bin/env node\n"./original.wasm";\n',encoding='utf8')
    _,value=inspect(tmp_path,parameters={'candidate_paths':[str(candidate)],'glue_paths':[str(glue),str(bom)]})
    principal=str((tmp_path/'original.wasm').resolve());secondary=str(candidate.resolve())
    assert [row['path'] for row in value['candidates']]==[principal,secondary]
    assert value['candidates'][1]['sha256']==hashlib.sha256(candidate.read_bytes()).hexdigest()
    assert 'validation' not in value['candidates'][1]
    first,second=value['glue'];assert first['parse_status']==second['parse_status']=='complete'
    refs=first['references'];assert [row['value'] for row in refs]==[
        'original.wasm','./original.wasm','https://unqueried.invalid/original.wasm?build=1','missing.wasm','original.wasm']
    assert [(row['line'],row['column']) for row in refs]==[
        (1,0),(2,source.splitlines()[1].index('"')),(3,source.splitlines()[2].index('"')),
        (4,source.splitlines()[3].index('`')),(6,source.splitlines()[5].index('"'))]
    assert refs[0]['candidate_paths']==refs[1]['candidate_paths']==refs[4]['candidate_paths']==[principal]
    assert refs[0]['association']=='local-path-candidate'
    assert refs[2]['association']=='basename-candidates' and refs[2]['candidate_paths']==[principal,secondary]
    assert refs[3]['association']=='unresolved' and refs[3]['candidate_paths']==[]
    assert second['references'][0]['line']==2 and second['references'][0]['column']==0
    assert all(row['evidence_kind']=='static-literal' for row in refs)
    assert first['artifact']['sha256']==hashlib.sha256(glue.read_bytes()).hexdigest()
    assert value['glue_complete'] and value['candidates_complete']


@pytest.mark.parametrize('content,status,invalid_utf8,references',[
    (b'const = ; "original.wasm";', 'failed',False,0),
    (b'let name=1; let name=2; "original.wasm";', 'partial',False,1),
    (b'"\xff.wasm";', 'failed',True,0),
])
def test_unreadable_or_partial_glue_does_not_fabricate_complete_reference_facts(tmp_path,content,status,invalid_utf8,references):
    glue=tmp_path/'original-glue.js';glue.write_bytes(content)
    _,value=inspect(tmp_path,parameters={'glue_paths':[str(glue)]})
    observed=value['glue'][0]
    assert observed['parse_status']==status and observed['invalid_utf8'] is invalid_utf8
    assert len(observed['references'])==references and observed['parse_issues']
    assert observed['artifact']['sha256']==hashlib.sha256(content).hexdigest()
    assert value['validation']=='valid' and value['completion_status']=='complete'


def test_valid_empty_module_has_observed_empty_sections_and_interface(tmp_path):
    _,value=inspect(tmp_path,content=bytes.fromhex('0061736d01000000'))
    assert value['sections']==[] and value['sections_complete']
    assert value['interface']['state']=='complete' and value['interface']['entries']==[]
    assert value['imports']==value['exports']==[] and value['completion_status']=='complete'


def test_retained_comparison_binds_both_original_documents_after_transfer_without_source_access(tmp_path,monkeypatch):
    originals=tmp_path/'originals';originals.mkdir()
    left=originals/'echo.wasm';right=originals/'empty.wasm'
    left.write_bytes(ORIGINAL);right.write_bytes(bytes.fromhex('0061736d01000000'))
    expected=[(str(path.resolve()),hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_size) for path in [left,right]]
    with TestClient(create_app(tmp_path/'profile',port=64228),base_url='http://127.0.0.1:64228') as client:
        client.get('/');store=client.app.state.store;pid=store.create_project('Retained original interfaces')['id']
        artifacts=[store.add_artifact(pid,path) for path in [left,right]]
        jobs=[run(client,pid,artifact['id'],'wasm.artifact')[0] for artifact in artifacts]
        documents=[Path(job['result']['analysis_file']).read_bytes() for job in jobs]
        response=client.post('/api/agent/call',json={'tool':'theseus_evidence_export','arguments':{'project_id':pid}})
        response.raise_for_status();bundle=response.json()['result']
        left.unlink();right.unlink();originals.rmdir()
        response=client.post('/api/agent/call',json={'tool':'theseus_evidence_import','arguments':{'bundle':bundle,'name':'Originals retired'}})
        response.raise_for_status();imported=response.json()['result'];mapping=imported['id_map']
        absent={path for path,_,_ in expected};exists=Path.exists;open_path=Path.open
        def forbidden_exists(path):
            assert str(path.absolute()) not in absent,'Retained comparison queried an original artifact path'
            return exists(path)
        def forbidden_open(path,*args,**kwargs):
            assert str(path.absolute()) not in absent,'Retained comparison reopened an original artifact'
            return open_path(path,*args,**kwargs)
        monkeypatch.setattr(Path,'exists',forbidden_exists);monkeypatch.setattr(Path,'open',forbidden_open)
        job,value=run(client,imported['project']['id'],mapping[artifacts[0]['id']],'wasm.compare_interfaces',{
            'reference_job_id':mapping[jobs[0]['id']],'candidate_job_id':mapping[jobs[1]['id']],'query':{'scope':'exports'}})
        assert value['summary']['removed']==1 and value['summary']['unknown']==0
        assert value['coverage']=='complete-within-inputs'
        bindings=value['retained_inputs'];assert [row['side'] for row in bindings]==['reference','candidate']
        for index,row in enumerate(bindings):
            path,sha,size=expected[index]
            assert row['analysis_sha256']==hashlib.sha256(documents[index]).hexdigest()
            assert row['analysis_bytes']==len(documents[index]) and row['artifact_sha256']==sha
            assert row['artifact']=={'path':path,'sha256':sha,'bytes':size}
        page=client.get('/api/jobs/'+job['id']+'/records/retained_inputs')
        page.raise_for_status();assert page.json()['total']==2


@pytest.mark.parametrize('invalid_module', [True,False])
def test_failed_reader_retains_known_prefix_and_diagnostic_through_transfer(tmp_path,invalid_module):
    source=tmp_path/'selected.wasm'
    content=bytes.fromhex('0061736d010000000105016000017f030201000a040102000b') if invalid_module else ORIGINAL
    source.write_bytes(content)
    parameters={} if invalid_module else {'glue_paths':[str(tmp_path/'absent.js')]}
    with TestClient(create_app(tmp_path/'profile',port=64228),base_url='http://127.0.0.1:64228') as client:
        client.get('/');store=client.app.state.store;pid=store.create_project('Reader failure')['id']
        artifact=store.add_artifact(pid,source)
        response=client.post('/api/agent/call',json={'tool':'theseus_analysis_start','arguments':{
            'project_id':pid,'artifact_id':artifact['id'],'operation':'wasm.artifact','parameters':parameters}})
        response.raise_for_status();job=wait(client,response.json()['result'])
        assert job['state']=='failed' and job['result']['execution']['exit_code']!=0
        assert job['result']['execution']['stderr'] and job['result']['error']
        folder=store.directory/'analyses'/job['id'];assert not (folder/'analysis.json').exists()
        retained=Path(job['result']['analysis_file']).read_bytes();document=json.loads(retained);value=document['result']
        assert document['artifact_sha256']==hashlib.sha256(content).hexdigest()
        assert value['sections_complete'] and value['engine_profile']['validation_method']=='WasmModule.validate'
        assert value['completion_status']=='unknown' and value['failure']['message']
        if invalid_module:
            assert value['validation']=='not-established' and value['failure']['phase']=='validating-module'
            assert 'interface' not in value and 'wat' not in value
        else:
            assert value['validation']=='valid' and value['failure']['phase']=='reading-selected-glue'
            assert value['interface']['state']=='complete' and not value['glue_complete']
        exported=client.post('/api/agent/call',json={'tool':'theseus_evidence_export','arguments':{'project_id':pid}})
        exported.raise_for_status();source.unlink()
        imported=client.post('/api/agent/call',json={'tool':'theseus_evidence_import','arguments':{'bundle':exported.json()['result']}})
        imported.raise_for_status();mapping=imported.json()['result']['id_map']
        transferred=client.get('/api/jobs/'+mapping[job['id']]+'/analysis.json');transferred.raise_for_status()
        assert transferred.content==retained


def held_reader(tmp_path):
    """Use the production reader/publisher; pause after a real module has been read."""
    configured=engine();root=Path(configured['entry']).parent
    entry=tmp_path/'held-reader.mjs'
    entry.write_text('''import {readFile,appendFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {inspectWasm} from '''+json.dumps((root/'wasm-inspection.js').as_uri())+''';
import {publishWasmPrefix} from '''+json.dumps((root/'wasm-recording.js').as_uri())+''';
const [input,output]=process.argv.slice(2);
await appendFile(output+'.launches','started\\n');
const request=JSON.parse(await readFile(input,'utf8')),bytes=await readFile(request.path);
const envelope={operation:'wasm.artifact',artifact_sha256:createHash('sha256').update(bytes).digest('hex'),runtime:process.version};
await inspectWasm(bytes,request.path,{},async observation=>{
  await publishWasmPrefix(output,envelope,observation);
  if(observation.phase==='validating-module') {
    setInterval(()=>{},1000);
    await new Promise(()=>{});
  }
});
''',encoding='utf8')
    return {**configured,'entry':str(entry)}


def wait_prefix(output):
    prefix=output.with_name(output.name+'.partial.json');deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        try:
            raw=prefix.read_bytes()
            if json.loads(raw)['result']['phase']=='validating-module':return raw
        except (OSError,ValueError):pass
        time.sleep(.02)
    raise AssertionError('The real reader did not reach its validation prefix')


def test_cancel_keeps_observed_prefix_without_relaunching_reader(tmp_path,monkeypatch):
    import theseus.native_analysis as native
    configured=held_reader(tmp_path);monkeypatch.setattr(native,'engine',lambda:configured)
    source=tmp_path/'original.wasm';source.write_bytes(ORIGINAL)
    with TestClient(create_app(tmp_path/'profile',port=64228),base_url='http://127.0.0.1:64228') as client:
        client.get('/');store=client.app.state.store;pid=store.create_project('Cancellation')['id']
        artifact=store.add_artifact(pid,source)
        response=client.post('/api/agent/call',json={'tool':'theseus_analysis_start','arguments':{
            'project_id':pid,'artifact_id':artifact['id'],'operation':'wasm.artifact'}})
        response.raise_for_status();job=response.json()['result'];output=store.directory/'analyses'/job['id']/'analysis.json'
        recorded=wait_prefix(output);source.unlink()
        cancelled=client.post('/api/jobs/'+job['id']+'/cancel');cancelled.raise_for_status();job=wait(client,cancelled.json())
        assert job['state']=='cancelled' and not output.exists()
        assert Path(job['result']['analysis_file']).read_bytes()==recorded
        assert job['result']['wasm_observation']['validation']=='not-established'
        assert job['result']['original_source_check']=='not-performed-retained-observation'
        assert output.with_name(output.name+'.launches').read_text()=='started\n'
        identity=job['result']['worker_identity_recording'];assert identity['recorded'] and identity['identity']['created']>0
        assert job['id'] not in client.app.state.comparisons.processes


def test_owner_restart_freezes_exact_prefix_stops_only_bound_worker_and_never_opens_original(tmp_path,monkeypatch):
    from theseus.store import Store
    from theseus.wasm_recording import record_worker
    configured=held_reader(tmp_path);profile=tmp_path/'profile';store=Store(profile)
    pid=store.create_project('Interrupted owned reader')['id'];source=tmp_path/'original.wasm';source.write_bytes(ORIGINAL)
    artifact=store.add_artifact(pid,source);job_id='owned-interrupted-wasm'
    folder=profile/'analyses'/job_id;folder.mkdir(parents=True);output=folder/'analysis.json';request=folder/'request.json'
    request.write_text(json.dumps({'operation':'wasm.artifact','path':str(source),'parameters':{}}),encoding='utf8')
    store.save_job(pid,job_id,'running',{'kind':'native_analysis','operation':'wasm.artifact','artifact_id':artifact['id'],'engine':configured})
    command=[configured['node'],configured['entry'],str(request),str(output)]
    process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        assert record_worker(folder,process,command)['recorded'];recorded=wait_prefix(output);source.unlink()
        original=str(source.absolute());open_path=Path.open;exists=Path.exists
        def forbid_open(path,*args,**kwargs):
            assert str(path.absolute())!=original,'Recovery reopened the original module'
            return open_path(path,*args,**kwargs)
        def forbid_exists(path):
            assert str(path.absolute())!=original,'Recovery queried the original module'
            return exists(path)
        monkeypatch.setattr(Path,'open',forbid_open);monkeypatch.setattr(Path,'exists',forbid_exists)
        with TestClient(create_app(profile,port=64228),base_url='http://127.0.0.1:64228') as client:
            client.get('/')
            response=client.get('/api/jobs/'+job_id);response.raise_for_status();job=response.json()
            assert job['state']=='interrupted' and job['result']['recovered_recording']
            assert job['result']['recovery_cleanup']=={'status':'terminated-owned-worker','pid':process.pid}
            assert job['result']['recording_snapshot']['sha256']==hashlib.sha256(recorded).hexdigest()
            assert job['result']['original_source_check']=='not-performed-retained-observation'
            assert Path(job['result']['analysis_file']).read_bytes()==recorded
            response=client.get('/api/jobs/'+job_id+'/analysis.json');response.raise_for_status();assert response.content==recorded
            assert output.with_name(output.name+'.launches').read_text()=='started\n'
            assert process.wait(timeout=5)!=0
    finally:
        if process.poll() is None:process.terminate();process.wait(timeout=5)


def test_mismatched_creation_time_never_terminates_process(tmp_path):
    from theseus.wasm_recording import record_worker,stop_interrupted_worker
    configured=held_reader(tmp_path);source=tmp_path/'original.wasm';source.write_bytes(ORIGINAL)
    request=tmp_path/'request.json';output=tmp_path/'analysis.json'
    request.write_text(json.dumps({'path':str(source)}),encoding='utf8')
    command=[configured['node'],configured['entry'],str(request),str(output)]
    process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        recorded=record_worker(tmp_path,process,command);assert recorded['recorded'];wait_prefix(output)
        identity=recorded['identity'];identity['created']+=1
        Path(recorded['identity_file']).write_text(json.dumps(identity),encoding='utf8')
        assert stop_interrupted_worker(tmp_path,command)=={'status':'worker-identity-mismatch','pid':process.pid}
        assert process.poll() is None
    finally:
        if process.poll() is None:process.terminate()
        process.wait(timeout=5)


def test_spawn_observer_failure_stops_its_child_and_releases_process_registration(tmp_path):
    from theseus.comparison import Comparisons
    from theseus.store import Store
    manager=Comparisons(Store(tmp_path/'profile'));children=[]
    def failure(process):
        children.append(process);raise ValueError('Identity observer failed')
    try:
        with pytest.raises(ValueError,match='Identity observer failed'):
            manager._execute('observer-failure',[engine()['node'],'-e','setInterval(()=>{},1000)'],{'spawn_observer':failure})
        assert len(children)==1 and children[0].poll() is not None and not manager.processes
    finally:manager.shutdown()


def test_incomplete_historical_worker_metadata_does_not_abort_owner_startup(tmp_path):
    from theseus.store import Store
    profile=tmp_path/'profile';store=Store(profile);pid=store.create_project('Missing worker configuration')['id']
    store.save_job(pid,'incomplete-worker','running',{'kind':'native_analysis','operation':'wasm.artifact'})
    with TestClient(create_app(profile,port=64228),base_url='http://127.0.0.1:64228') as client:
        client.get('/');response=client.get('/api/jobs/incomplete-worker');response.raise_for_status()
        job=response.json();assert job['state']=='interrupted' and 'engine' in job['result']['recovery_error']


@pytest.mark.skipif(os.name!='nt',reason='Windows delete-sharing behavior')
@pytest.mark.parametrize('release_reader',[True,False])
def test_real_windows_prefix_publication_contention_preserves_observation(tmp_path,release_reader):
    import ctypes
    from ctypes import wintypes
    output=tmp_path/'analysis.json';prefix=tmp_path/'analysis.json.partial.json';original=b'{"prefix":"old"}';prefix.write_bytes(original)
    entry=tmp_path/'publish.mjs';publisher=Path(engine()['entry']).with_name('wasm-recording.js')
    entry.write_text('''import fs from 'node:fs/promises';
import {syncBuiltinESMExports} from 'node:module';
const [output]=process.argv.slice(2),rename=fs.rename;
let attempts=0;
fs.rename=async(...args)=>{
  attempts++;
  try{return await rename(...args);}
  catch(error){await fs.writeFile(output+'.denied',String(error.code));throw error;}
};
syncBuiltinESMExports();
const {publishWasmPrefix}=await import('''+json.dumps(publisher.as_uri())+''');
try {
  await publishWasmPrefix(output,{operation:'wasm.artifact'},{recorded:'same original prefix'});
  process.stdout.write(JSON.stringify({attempts,published:true}));
} catch(error) {
  process.stdout.write(JSON.stringify({attempts,published:false,code:error.code}));process.exitCode=1;
}
''',encoding='utf8')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE;kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    handle=kernel.CreateFileW(str(prefix),0x80000000,3,None,3,0x80,None)
    assert handle!=ctypes.c_void_p(-1).value
    process=None
    try:
        process=subprocess.Popen([engine()['node'],str(entry),str(output)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        deadline=time.monotonic()+10;denied=tmp_path/'analysis.json.denied'
        while not denied.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.005)
        assert denied.exists(),'The real Windows handle did not cause publication contention'
        if release_reader:assert kernel.CloseHandle(handle);handle=None
        stdout,stderr=process.communicate(timeout=5);observed=json.loads(stdout)
        assert not stderr and observed['published'] is release_reader and observed['attempts']>=2
        assert process.returncode==(0 if release_reader else 1) and not output.exists()
        if release_reader:
            assert json.loads(prefix.read_bytes())=={'operation':'wasm.artifact','result':{'recorded':'same original prefix'}}
        else:
            assert observed['attempts']==50 and prefix.read_bytes()==original
    finally:
        if handle is not None:assert kernel.CloseHandle(handle)
        if process is not None and process.poll() is None:process.terminate();process.wait(timeout=5)
