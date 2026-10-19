import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.frida_runtime import engine
from theseus.store import identifier


def observe(client,project_id,operation,parameters=None,expected='finished'):
    response=client.post('/api/agent/call',json={'tool':'theseus_runtime_start','arguments':{
        'project_id':project_id,'operation':'frida.'+operation,'parameters':parameters or {}}})
    response.raise_for_status();job=response.json()['result'];end=time.monotonic()+30
    while job['state'] in {'queued','running'}:
        assert time.monotonic()<end,job
        time.sleep(.05);job=client.get('/api/jobs/'+job['id']).json()
    assert job['state']==expected,job
    return job,client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']


def test_runtime_discovery_does_not_import_or_connect_sdk(tmp_path):
    root=Path(__file__).resolve().parents[1]
    code='''import builtins
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name=='frida' or name.startswith('frida.'): raise AssertionError('SDK imported during discovery')
    return original(name,*args,**kwargs)
builtins.__import__=guarded
from theseus.runtime import catalog
rows=catalog()['operations']
assert len([r for r in rows if r['name'].startswith('adb.')])==24
assert len([r for r in rows if r['name'].startswith('frida.')])==9
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=root,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_runtime_recovery_freezes_journal_without_sdk_or_replay(tmp_path,monkeypatch):
    from theseus.store import Store
    from theseus import frida_runtime
    store=Store(tmp_path/'data');project=store.create_project('Historical instrumentation')['id'];session_id=identifier()
    folder=store.directory/'analyses'/session_id;folder.mkdir(parents=True)
    (folder/'frida-session.json').write_text(json.dumps({'session_id':session_id,'project_id':project,'target':{'pid':111,'mode':'attach'}}))
    (folder/'events.jsonl').write_bytes(b'{"sequence":1,"kind":"script-message","message":{"payload":128}}\n{"truncated":')
    store.save_job(project,session_id,'finished',{'kind':'runtime_analysis','operation':'frida.start','session_state':'open','cases':[]})
    monkeypatch.setattr(frida_runtime,'engine',lambda:pytest.fail('Recovery must not discover/import/connect SDK'))
    frida_runtime.recover(store)
    start=store.job(session_id);recovered=store.job(start['result']['recovered_recording_job_id'])
    saved=Path(recovered['result']['analysis_file']).read_bytes();document=json.loads(saved)['result']
    assert document['events'][0]['message']['payload']==128
    assert document['events'][1]['kind']=='recording-gap'
    assert not document['connection_restored'] and recovered['state']=='interrupted'
    (folder/'events.jsonl').write_bytes(b'changed after restart')
    frida_runtime.recover(store)
    assert Path(recovered['result']['analysis_file']).read_bytes()==saved
    assert len(store.items('jobs',project))==2


@pytest.fixture(scope='module')
def executable(tmp_path_factory):
    if os.name!='nt' or not shutil.which('rustc'): pytest.skip('Original MSVC Rust fixture requires Windows rustc')
    folder=tmp_path_factory.mktemp('original-frida-target');target=folder/'instrumentation-original.exe'
    source=Path(__file__).parent/'fixtures/compiler/instrumentation.rs'
    command=['rustc',str(source),'-o',str(target),'-C','opt-level=0','-C','link-arg=/EXPORT:measure']
    result=subprocess.run(command,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
    return target


@pytest.mark.skipif(not engine()['available'],reason='Requires installed free Frida SDK')
def test_real_original_process_instrumentation_messages_errors_unload_close_and_transfer(tmp_path,executable):
    child=subprocess.Popen([str(executable)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
            client.get('/');store=client.app.state.store;project=store.create_project('Owned original instrumentation')['id']
            _,devices=observe(client,project,'devices')
            assert any(d['id']=='local' for d in devices['devices'])
            _,processes=observe(client,project,'processes',{'device_id':'local'})
            assert any(p['pid']==child.pid for p in processes['processes'])
            opened,record=observe(client,project,'start',{'device_id':'local','mode':'attach','pid':child.pid})
            session_id=record['session_id'];assert record['session_state']=='open' and not record['spawn_paused']
            other=store.create_project('Other project')['id']
            wrong=client.post(f'/api/projects/{other}/runtime',json={'operation':'frida.status','parameters':{'session_id':session_id}})
            assert wrong.status_code==400
            source='''Interceptor.attach(Process.getModuleByName('instrumentation-original.exe').getExportByName('measure'), {
                onEnter(args) { this.value=args[0].toInt32(); },
                onLeave(retval) { send({input:this.value,result:retval.toInt32()},new Uint8Array([0,255,13,10]).buffer); }
            }); send({armed:true});'''
            _,loaded=observe(client,project,'load',{'session_id':session_id,'source':source,'name':'Original measure observer'})
            script_id=loaded['script_id'];assert 'source' not in loaded['parameters']
            for value,expected in [(-1,0),(128,131),(256,255)]:
                child.stdin.write(str(value)+'\n');child.stdin.flush();assert int(child.stdout.readline())==expected
            end=time.monotonic()+5
            while True:
                status_job,status=observe(client,project,'status',{'session_id':session_id})
                messages=[e for e in status['events'] if e['kind']=='script-message' and 'input' in e['message'].get('payload',{})]
                if len(messages)==3: break
                assert time.monotonic()<end,status
            assert [m['message']['payload'] for m in messages]==[{'input':-1,'result':0},{'input':128,'result':131},{'input':256,'result':255}]
            assert all(base64.b64decode(m['data']['data'])==b'\0\xff\r\n' for m in messages)
            _,errors=observe(client,project,'load',{'session_id':session_id,'source':'throw new Error("original fixture error")'})
            assert any(e.get('message',{}).get('type')=='error' for e in errors['events'])
            _,unloaded=observe(client,project,'unload',{'session_id':session_id,'script_id':script_id})
            assert not any(s['script_id']==script_id for s in unloaded['scripts'])
            previous=len(messages)
            child.stdin.write('10\n');child.stdin.flush();assert child.stdout.readline().strip()=='13'
            _,after=observe(client,project,'status',{'session_id':session_id})
            assert len([e for e in after['events'] if e['kind']=='script-message' and 'input' in e['message'].get('payload',{})])==previous
            closed,record=observe(client,project,'close',{'session_id':session_id})
            assert record['session_state']=='closed' and record['target_final_state']=='unknown'
            assert child.poll() is None
            assert store.job(opened['id'])['result']['session_state']=='closed'
            assert not any(j['result'].get('session_state') in {'open','starting','closing'} for j in store.items('jobs',project)), 'Historical operation receipts must not advertise live connections after close'
            cited=client.get(f'/api/jobs/{status_job["id"]}/records/events/0').json();assert cited['sources'][0]['kind']=='runtime-observation'
            snapshot=store.artifact(project,status_job['result']['artifact_id'])
            store.add_finding(project,snapshot['id'],'events/0','Recorded SDK event','')
            imported=client.app.state.evidence.load(client.app.state.evidence.export(project))
            moved=client.get(f'/api/jobs/{imported["id_map"][status_job["id"]]}/records/events/0').json()
            assert moved['record']==cited['record']
            imported_start=store.job(imported['id_map'][session_id])
            assert imported_start['result']['session_state']=='imported'
            assert not client.get('/api/projects/'+imported['project']['id']).json()['runtime_sessions']
            missing=client.post(f'/api/projects/{imported["project"]["id"]}/runtime',json={'operation':'frida.status','parameters':{'session_id':imported['id_map'][session_id]}})
            assert missing.status_code==400
            _,finite=observe(client,project,'observe',{'device_id':'local','pid':child.pid,'source':'send({finite:true});','duration_seconds':1})
            assert finite['session_state']=='closed' and child.poll() is None
            assert any(e.get('message',{}).get('payload')=={'finite':True} for e in finite['events'])
    finally:
        child.stdin.close()
        try: child.wait(timeout=3)
        except subprocess.TimeoutExpired: child.terminate();child.wait(timeout=3)


@pytest.mark.skipif(not engine()['available'],reason='Requires installed free Frida SDK')
@pytest.mark.parametrize('resume_first',[False,True])
def test_closing_paused_spawn_resumes_before_detach_and_never_kills_target(tmp_path,executable,resume_first):
    import psutil
    marker=tmp_path/'resumed.txt';pid=None
    try:
        with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
            client.get('/');store=client.app.state.store;project=store.create_project('Owned paused spawn')['id']
            job,record=observe(client,project,'start',{'device_id':'local','mode':'spawn','argv':[str(executable),'--marker',str(marker)]})
            pid=record['target']['pid'];assert record['spawn_paused'] and not marker.exists()
            if resume_first:
                _,resumed=observe(client,project,'resume',{'session_id':record['session_id']})
                assert not resumed['spawn_paused'] and any(e['kind']=='resumed' for e in resumed['events'])
            _,closed=observe(client,project,'close',{'session_id':record['session_id']})
            end=time.monotonic()+3
            while not marker.exists(): assert time.monotonic()<end;time.sleep(.05)
            assert marker.read_bytes()==b'original process resumed'
            assert not closed['spawn_paused'] and closed['session_state']=='closed'
            assert any(e['kind']=='resumed' if resume_first else e['kind']=='resumed-before-detach' for e in closed['events'])
            assert psutil.Process(pid).is_running()
    finally:
        if pid and psutil.pid_exists(pid):
            process=psutil.Process(pid)
            if Path(process.exe()).resolve()==executable.resolve(): process.terminate();process.wait(timeout=3)


@pytest.mark.skipif(not engine()['available'],reason='Requires installed free Frida SDK')
def test_real_observation_window_cancellation_detaches_without_killing_original(tmp_path,executable):
    child=subprocess.Popen([str(executable)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
            client.get('/');store=client.app.state.store;project=store.create_project('Cancel instrumentation window')['id']
            response=client.post(f'/api/projects/{project}/runtime',json={'operation':'frida.observe','parameters':{
                'device_id':'local','pid':child.pid,'source':'send({original:128});','duration_seconds':60}})
            response.raise_for_status();job_id=response.json()['id'];end=time.monotonic()+10
            while True:
                rows=client.get('/api/projects/'+project).json()['runtime_sessions']
                folder=store.directory/'analyses'/job_id;events=folder/'events.jsonl'
                if rows and events.is_file() and 'script-loaded' in events.read_text(encoding='utf8'): break
                assert time.monotonic()<end;time.sleep(.05)
            cancelled=client.post('/api/jobs/'+job_id+'/cancel');cancelled.raise_for_status()
            while True:
                job=store.job(job_id)
                if job['state'] not in {'queued','running'}: break
                assert time.monotonic()<end;time.sleep(.05)
            assert job['state']=='cancelled' and child.poll() is None
            record=client.get('/api/jobs/'+job_id+'/analysis.json').json()['result']
            assert record['session_state']=='closed'
            assert any(e.get('message',{}).get('payload')=={'original':128} for e in record['events'])
            assert not client.get('/api/projects/'+project).json()['runtime_sessions']
    finally:
        child.stdin.close()
        try: child.wait(timeout=3)
        except subprocess.TimeoutExpired: child.terminate();child.wait(timeout=3)


@pytest.mark.skipif(not engine()['available'],reason='Requires installed free Frida SDK')
def test_remote_auth_is_excluded_from_recording_and_diagnostic(tmp_path,monkeypatch):
    from theseus.frida_runtime import FridaSessions
    secret='test-only-ephemeral-token-779'
    def fail(self,project_id,job_id,operation,parameters,folder): raise ValueError('remote diagnostic '+parameters['token'])
    monkeypatch.setattr(FridaSessions,'operate',fail)
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Credential recording boundary')['id']
        job,record=observe(client,project,'processes',{'device_id':'remote','remote_endpoint':'127.0.0.1:1','token':secret},expected='failed')
        assert secret not in json.dumps(job) and secret not in json.dumps(record)
        assert '[redacted]' in record['error'] and 'token' not in record['parameters']
        assert secret.encode() not in Path(job['result']['analysis_file']).read_bytes()
        assert secret.encode() not in store.path.read_bytes()


@pytest.mark.skipif(not engine()['available'],reason='Requires installed free Frida SDK')
def test_application_shutdown_resumes_paused_spawn_and_retains_final_capture(tmp_path,executable):
    import psutil
    marker=tmp_path/'shutdown-resumed.txt';pid=None
    try:
        app=create_app(tmp_path/'data');store=app.state.store
        with TestClient(app,base_url='http://127.0.0.1:5217') as client:
            client.get('/');project=store.create_project('Shutdown instrumentation cleanup')['id']
            _,record=observe(client,project,'start',{'device_id':'local','mode':'spawn','argv':[str(executable),'--marker',str(marker)]})
            pid=record['target']['pid'];assert record['spawn_paused'] and not marker.exists()
        end=time.monotonic()+3
        while not marker.exists(): assert time.monotonic()<end;time.sleep(.05)
        final=next(j for j in store.items('jobs',project) if j['result'].get('shutdown_capture'))
        assert final['state']=='finished'
        captured=json.loads(Path(final['result']['analysis_file']).read_text(encoding='utf8'))['result']
        assert captured['session_state']=='closed' and any(e['kind']=='resumed-before-detach' for e in captured['events'])
        assert psutil.Process(pid).is_running()
    finally:
        if pid and psutil.pid_exists(pid):
            process=psutil.Process(pid)
            if Path(process.exe()).resolve()==executable.resolve(): process.terminate();process.wait(timeout=3)
