import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from fastapi.testclient import TestClient
import pytest

from android_fixture import android_fixture,BUILD
from theseus.adb_runtime import engine
from theseus.android import engines
from theseus.api import create_app
from theseus.comparison import Comparisons
from theseus.store import identifier
from theseus import runtime


def run(client,pid,operation,parameters=None,wait_seconds=120):
    response=client.post('/api/agent/call',json={'tool':'theseus_runtime_start','arguments':{
        'project_id':pid,'operation':operation,'parameters':parameters or {}}})
    response.raise_for_status()
    job=response.json()['result']
    end=time.monotonic()+wait_seconds
    while job['state'] in {'queued','running'}:
        assert time.monotonic()<end,job
        time.sleep(.1)
        job=client.get('/api/jobs/'+job['id']).json()
    assert job['state']=='finished',job
    document=client.get('/api/jobs/'+job['id']+'/analysis.json').json()
    return job,document['result']


def test_runtime_catalog_missing_engine_and_explicit_target(monkeypatch,tmp_path):
    monkeypatch.setenv('THESEUS_ADB',str(tmp_path/'absent.exe'))
    app=create_app(tmp_path/'data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        rows=[row for row in client.get('/api/runtime/catalog').json()['operations'] if row['name'].startswith('adb.')]
        assert len(rows)==24 and not any(row['available'] for row in rows)
        assert len([row for row in rows if row['mutates_device']])==6
        pid=app.state.store.create_project('Runtime')['id']
        before=list((app.state.store.directory/'analyses').glob('*'))
        missing=client.post('/api/projects/'+pid+'/runtime',json={'operation':'adb.device'})
        assert missing.status_code==400 and 'serial' in missing.json()['detail']
        assert list((app.state.store.directory/'analyses').glob('*'))==before


def test_cancelling_a_runtime_client_preserves_a_shared_adb_daemon(monkeypatch):
    import psutil
    terminated=[]
    class Process:
        def __init__(self,pid,executable,args): self.pid,self.executable,self.args=pid,executable,args
        def exe(self): return self.executable
        def cmdline(self): return self.args
        def terminate(self): terminated.append(self.pid)
        def children(self,recursive=False): return [daemon,client]
    parent=Process(1,'python.exe',['python','adb_runtime.py'])
    client=Process(2,'adb.exe',['adb','-s','own','bugreport'])
    daemon=Process(3,'adb.exe',['adb','-L','tcp:localhost:5037','fork-server','server'])
    monkeypatch.setattr(psutil,'Process',lambda _:parent)
    monkeypatch.setattr(psutil,'wait_procs',lambda targets,timeout:(targets,[]))
    handle=type('Handle',(),{'pid':1,'_theseus_preserve_adb_server':True})()
    Comparisons._terminate(handle)
    assert set(terminated)=={1,2} and 3 not in terminated


def test_interrupted_runtime_recovers_only_recorded_bytes_without_replay(tmp_path,monkeypatch):
    app=create_app(tmp_path/'data');store=app.state.store
    pid=store.create_project('Interrupted runtime')['id'];job_id=identifier()
    folder=store.directory/'analyses'/job_id;folder.mkdir(parents=True)
    (folder/'request.json').write_text(json.dumps({'operation':'adb.device','parameters':{'serial':'never-connect'}}))
    document={'operation':'adb.device','runtime':'fixture','engine':'recorded fixture',
        'result':{'status':'incomplete','observations':[{'stdout':'already recorded\n','exit_code':0}]}}
    raw=json.dumps(document).encode();(folder/'partial.json').write_bytes(raw)
    store.save_job(pid,job_id,'running',{'kind':'runtime_analysis','operation':'adb.device','cases':[]})
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**kw:pytest.fail('Recovery must not run a client'))
    reopened=create_app(tmp_path/'data');record=reopened.state.store.job(job_id)
    assert record['state']=='interrupted' and record['result']['recovered_recording']
    assert Path(record['result']['analysis_file']).read_bytes()==raw
    # A later orphaned writer cannot change the frozen recovered observation.
    (folder/'partial.json').write_text('{}')
    assert Path(record['result']['analysis_file']).read_bytes()==raw
    saved=reopened.state.store.analysis_record(job_id,'observations','0')
    assert saved['record']['stdout']=='already recorded\n'
    create_app(tmp_path/'data')
    assert len(reopened.state.store.items('artifacts',pid))==1


def test_cancelled_runtime_keeps_completed_observations_and_removes_private_upload(tmp_path,monkeypatch):
    app=create_app(tmp_path/'data');store=app.state.store;manager=Comparisons(store)
    pid=store.create_project('Cancel capture')['id'];job_id=identifier()
    folder=store.directory/'analyses'/job_id;folder.mkdir(parents=True)
    result={'kind':'runtime_analysis','operation':'adb.push_file','cases':[]}
    store.save_job(pid,job_id,'queued',result)
    raw=json.dumps({'runtime':'fixture','operation':'adb.push_file','result':{'status':'incomplete','observations':[{'stdout':'completed before cancellation'}]}}).encode()
    def execute(*args):
        (folder/'partial.json').write_bytes(raw)
        (folder/'upload-input.bin').write_bytes(b'private capture')
        manager.cancelled.add(job_id)
        return {'exit_code':-15,'stdout':'','stderr':''}
    monkeypatch.setattr(manager,'_execute',execute)
    try:
        runtime._run(manager,pid,job_id,folder,result)
        saved=store.job(job_id)
        assert saved['state']=='cancelled' and saved['result']['observation_status']=='incomplete'
        assert store.analysis_record(job_id,'observations','0')['record']['stdout']=='completed before cancellation'
        assert not (folder/'upload-input.bin').exists()
        assert Path(saved['result']['analysis_file']).read_bytes()==raw
    finally:
        manager.shutdown()


@pytest.mark.parametrize('outcome',['finished','cancelled','interrupted','failed'])
def test_terminal_runtime_publication_follows_private_input_cleanup(tmp_path,monkeypatch,outcome):
    app=create_app(tmp_path/'data');store=app.state.store;manager=Comparisons(store)
    pid=store.create_project('Terminal capture lifecycle')['id'];job_id=identifier()
    folder=store.directory/'analyses'/job_id;folder.mkdir(parents=True)
    capture=folder/'upload-input.bin'
    result={'kind':'runtime_analysis','operation':'adb.push_file','cases':[]}
    store.save_job(pid,job_id,'queued',result)
    def execute(*args):
        capture.write_bytes(b'private capture')
        if outcome=='interrupted': raise InterruptedError()
        if outcome=='failed': raise OSError('client failed')
        (folder/'analysis.json').write_text(json.dumps({'runtime':'fixture','result':{'status':'observed'}}))
        if outcome=='cancelled': manager.cancelled.add(job_id)
        return {'exit_code':0,'stdout':'','stderr':''}
    save=store.save_job;published=[]
    def observe(project_id,current_id,state,value):
        if state in {'finished','failed','cancelled'}:
            assert not capture.exists(),'Terminal readers can still observe the private input'
            assert current_id not in manager.cancelled,'Cancellation cleanup must precede terminal publication'
            published.append(state)
        return save(project_id,current_id,state,value)
    monkeypatch.setattr(manager,'_execute',execute)
    monkeypatch.setattr(store,'save_job',observe)
    try:
        runtime._run(manager,pid,job_id,folder,result)
        expected='cancelled' if outcome=='interrupted' else outcome
        assert published==[expected]
        assert store.job(job_id)['state']==expected
    finally:
        manager.shutdown()


def test_runtime_cleanup_failure_is_retained_and_terminal(tmp_path,monkeypatch):
    app=create_app(tmp_path/'data');store=app.state.store;manager=Comparisons(store)
    pid=store.create_project('Cleanup diagnostic')['id'];job_id=identifier()
    folder=store.directory/'analyses'/job_id;folder.mkdir(parents=True)
    capture=folder/'upload-input.bin';capture.write_bytes(b'private capture')
    result={'kind':'runtime_analysis','operation':'adb.push_file','cases':[]}
    store.save_job(pid,job_id,'queued',result)
    def execute(*args):
        (folder/'analysis.json').write_text(json.dumps({'runtime':'fixture','result':{'status':'observed'}}))
        return {'exit_code':0,'stdout':'','stderr':''}
    unlink=Path.unlink
    def refuse(path,*args,**kwargs):
        if path==capture: raise PermissionError('private input still held by an external reader')
        return unlink(path,*args,**kwargs)
    monkeypatch.setattr(manager,'_execute',execute)
    monkeypatch.setattr(Path,'unlink',refuse)
    try:
        runtime._run(manager,pid,job_id,folder,result)
        saved=store.job(job_id)
        assert saved['state']=='failed'
        assert 'external reader' in saved['result']['cleanup_error']
        assert saved['result']['observation_status']=='observed'
        assert capture.exists()
    finally:
        manager.shutdown()


@pytest.mark.skipif(not engine(),reason='Requires installed free Android platform-tools')
def test_real_client_recording_artifact_citation_and_historical_transfer(tmp_path):
    app=create_app(tmp_path/'data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        pid=app.state.store.create_project('Local ADB client')['id']
        job,result=run(client,pid,'adb.client')
        assert result['status']=='observed' and len(result['observations'])==1
        assert result['engine']['sha256'] and 'Android Debug Bridge version' in result['engine']['version']['stdout']
        assert not job['result']['mutates_device']
        snapshot=app.state.store.artifact(pid,job['result']['artifact_id'])
        assert snapshot['sha256']==job['result']['analysis_sha256']
        record=client.get(f'/api/jobs/{job["id"]}/records/engine/0').json()
        assert record['sources'][0]['kind']=='runtime-observation' and record['artifact_id']==snapshot['id']
        finding=app.state.store.add_finding(pid,snapshot['id'],'record:engine/0','Installed client observed','')
        bundle=app.state.evidence.export(pid)
        imported=app.state.evidence.load(bundle)
        moved=client.get('/api/jobs/'+imported['id_map'][job['id']]+'/analysis.json').content
        assert json.loads(moved)['result']==result
        imported_record=client.get('/api/jobs/'+imported['id_map'][job['id']]+'/records/engine/0').json()
        assert imported_record['record']==record['record']
        assert imported_record['artifact_id']==imported['id_map'][snapshot['id']]
        assert app.state.store.items('findings',imported['project']['id'])[0]['source_sha256']==snapshot['sha256']


def signed_fixture(directory):
    source=android_fixture(directory)
    java=engines()['java']
    keytool=str(Path(java).with_name('keytool.exe' if os.name=='nt' else 'keytool'))
    keystore=directory/'test-only.jks'
    signed=directory/'signed-fixture.apk'
    for command in [
        [keytool,'-genkeypair','-alias','fixture','-keyalg','RSA','-keysize','2048','-validity','2','-dname','CN=Theseus Format Fixture',
            '-keystore',str(keystore),'-storepass','fixture-test-only','-keypass','fixture-test-only','-noprompt'],
        [java,'-jar',str(BUILD/'lib/apksigner.jar'),'sign','--ks',str(keystore),'--ks-pass','pass:fixture-test-only',
            '--out',str(signed),str(source)]]:
        result=subprocess.run(command,capture_output=True)
        assert result.returncode==0,(result.stdout,result.stderr)
    return signed


@pytest.mark.skipif(not os.environ.get('THESEUS_TEST_ADB_SERIAL'),reason='Requires explicit owned fixture emulator')
def test_real_runtime_cancellation_retains_capture_and_shared_server(tmp_path):
    import psutil
    serial=os.environ['THESEUS_TEST_ADB_SERIAL']
    check=subprocess.run([engine(),'-s',serial,'emu','avd','name'],capture_output=True)
    assert check.returncode==0 and check.stdout.decode().splitlines()[0]=='Theseus779'
    servers={row.pid for row in psutil.net_connections(kind='tcp') if row.status=='LISTEN' and row.laddr.port==5037}
    assert servers
    app=create_app(tmp_path/'data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        pid=app.state.store.create_project('Cancel owned emulator observation')['id']
        job=client.post('/api/projects/'+pid+'/runtime',json={
            'operation':'adb.bugreport','parameters':{'serial':serial}}).json()
        partial=app.state.store.directory/'analyses'/job['id']/'partial.json'
        deadline=time.monotonic()+30
        while not partial.is_file():
            assert time.monotonic()<deadline
            time.sleep(.05)
        # At least the actual SDK client version response has been checkpointed.
        assert json.loads(partial.read_text(encoding='utf8'))['result']['observations']
        app.state.comparisons.cancel(job['id'])
        while app.state.store.job(job['id'])['state'] in {'queued','running'}:
            assert time.monotonic()<deadline
            time.sleep(.05)
        saved=app.state.store.job(job['id'])
        assert saved['state']=='cancelled' and saved['result']['observation_status']=='incomplete'
        assert client.get('/api/jobs/'+job['id']+'/analysis.json').status_code==200
        after={row.pid for row in psutil.net_connections(kind='tcp') if row.status=='LISTEN' and row.laddr.port==5037}
        assert after==servers
        assert subprocess.run([engine(),'-s',serial,'get-state'],capture_output=True).returncode==0


@pytest.mark.skipif(not os.environ.get('THESEUS_TEST_ADB_SERIAL'),reason='Requires explicit owned fixture emulator; never selects a default device')
def test_owned_emulator_runtime_packages_transfers_screen_launch_and_cleanup(tmp_path):
    serial=os.environ['THESEUS_TEST_ADB_SERIAL']
    check=subprocess.run([engine(),'-s',serial,'emu','avd','name'],capture_output=True)
    assert check.returncode==0 and check.stdout.decode().splitlines()[0]=='Theseus779','Do not mutate an unrelated emulator'
    signed=signed_fixture(tmp_path/'original')
    app=create_app(tmp_path/'data')
    package='com.theseus.fixture'
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        pid=app.state.store.create_project('Owned Android emulator')['id']
        def invoke(operation,**parameters):
            job,result=run(client,pid,'adb.'+operation,{'serial':serial,**parameters})
            assert result['status']=='observed',result
            return job,result
        _,devices=run(client,pid,'adb.devices')
        assert any(row['serial']==serial and row['state']=='device' for row in devices['devices'])
        _,device=invoke('device')
        assert device['target']['build_fingerprint']
        assert any(row['name']=='ro.kernel.qemu' and row['value']=='1' for row in device['properties'])
        _,installed=invoke('install',local_path=str(signed))
        assert installed['verdict']=='success' and installed['replaced'] is None
        try:
            _,packages=invoke('resolve_packages',query='THESEUS.FIXTURE')
            assert [r['package_name'] for r in packages['packages']]==[package]
            _,listed=invoke('packages',query=package,scope='third-party')
            assert [r['package_name'] for r in listed['packages']]==[package]
            _,metadata=invoke('package',package_name=package)
            assert any('versionName=1.0' in row['text'] for row in metadata['declared_facts'])
            _,pulled=invoke('pull_package',package_name=package)
            assert len(pulled['artifacts'])==1
            assert Path(pulled['artifacts'][0]['path']).read_bytes()==signed.read_bytes()
            local=tmp_path/'payload.bin';local.write_bytes(b'Original\x00A5\n128')
            remote='/data/local/tmp/theseus779-'+uuid.uuid4().hex+" quote'\nfile.bin"
            _,pushed=invoke('push_file',local_path=str(local),remote_path=remote)
            assert pushed['verified'] is True and not pushed['local_source_changed']
            _,listing=invoke('directory',remote_path='/data/local/tmp',query='theseus779-')
            assert any(row['path']==remote and row['kind']=='file' for row in listing['entries'])
            _,links=run(client,pid,'adb.directory',{'serial':serial,'remote_path':'/','query':'sdcard'})
            # Android can deny attributes of other root entries; partial rows
            # remain usable and the nonzero result must not be hidden.
            assert links['status'] in {'observed','command-error'}
            assert any(row.get('kind')=='symlink' and row.get('symlink_target') for row in links['entries'])
            _,absent=run(client,pid,'adb.directory',{'serial':serial,'remote_path':'/theseus779-does-not-exist'})
            assert absent['status']=='command-error' and any(row.get('device_exit_code') not in (None,0) for row in absent['observations'])
            local.write_bytes(b'Changed version')
            _,refused=run(client,pid,'adb.push_file',{'serial':serial,'local_path':str(local),'remote_path':remote})
            assert refused['status']=='destination-exists'
            _,got=invoke('pull_file',remote_path=remote)
            assert Path(got['artifacts'][0]['path']).read_bytes()==b'Original\x00A5\n128'
            _,overwritten=invoke('push_file',local_path=str(local),remote_path=remote,overwrite=True)
            assert overwritten['verified'] is True
            _,started=invoke('start_app',package_name=package)
            assert started['verdict']=='success' and started['resolved_components']
            _,processes=invoke('processes')
            assert any(package in row.values() for row in processes['processes'])
            _,intent=invoke('start_activity',action='android.intent.action.MAIN',component=package+'/.GaugeActivity',extras=[
                {'name':'text','type':'string','value':"Single ' quote & newline\nvalue"},
                {'name':'enabled','type':'boolean','value':True},{'name':'count','type':'int','value':128},
                {'name':'large','type':'long','value':'9223372036854775807'},{'name':'ratio','type':'float','value':1.5}])
            assert intent['verdict']=='success'
            screen_job,screen=invoke('screen')
            assert screen['dimensions']=={'width':720,'height':1280}
            assert Path(screen['artifacts'][0]['path']).read_bytes().startswith(b'\x89PNG')
            for name in ['features','services','display','window','logcat']:
                invoke(name)
            _,bugreport=run(client,pid,'adb.bugreport',{'serial':serial},wait_seconds=300)
            assert bugreport['status']=='observed' and any(row['name'].endswith('.zip') for row in bugreport['artifacts'])
            _,setting=invoke('setting',namespace='global',key='theseus779_absent_key')
            assert setting['value']=='null'
            invoke('stop_app',package_name=package)
            bundle=app.state.evidence.export(pid)
            imported=app.state.evidence.load(bundle)
            retained=client.get('/api/jobs/'+imported['id_map'][screen_job['id']]+'/analysis.json').json()
            assert retained['result']==screen
            assert len(app.state.store.artifact_links(imported['project']['id']))==len(app.state.store.artifact_links(pid))
        finally:
            _,removed=invoke('uninstall',package_name=package)
            assert removed['verdict']=='success'
