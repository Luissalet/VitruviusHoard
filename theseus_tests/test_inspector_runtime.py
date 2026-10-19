import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import unquote

from fastapi.testclient import TestClient
import pytest

from inspector_fixture import inspector_fixture
from theseus.api import create_app
from theseus.store import identifier
from test_native_analysis import wait


def observe(client,project,operation,parameters,expected='finished'):
    reply=client.post('/api/agent/call',json={'tool':'theseus_runtime_start','arguments':{
        'project_id':project,'operation':'javascript.'+operation,'parameters':parameters}})
    reply.raise_for_status();job=reply.json()['result'];end=time.monotonic()+90
    while job['state'] in {'queued','running'}:
        assert time.monotonic()<end,job
        time.sleep(.05);job=client.get('/api/jobs/'+job['id']).json()
    assert job['state']==expected,json.dumps(job,ensure_ascii=True,indent=2)
    return job,client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']


def test_inspector_catalog_is_disk_only_without_sdk_import(tmp_path):
    root=Path(__file__).resolve().parents[1]
    code='''import builtins
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name=='websocket' or name.startswith('websocket.'): raise AssertionError('WebSocket SDK imported during catalog discovery')
    return original(name,*args,**kwargs)
builtins.__import__=guarded
from theseus.runtime import catalog
rows=catalog()['operations'];assert len([r for r in rows if r['name'].startswith('javascript.')])==2
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=root,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.skipif(not shutil.which('node'),reason='Requires installed Node for owned Inspector fixture')
def test_reconcile_saved_hashes_ambiguity_declarations_and_changed_receipts(tmp_path):
    with inspector_fixture(tmp_path/'fixture') as target, TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Saved static and runtime sources')['id']
        (target['root']/'same.cjs').write_bytes(target['rule'].read_bytes())
        (target['root']/'unloaded.cjs').write_text('exports.unloaded=927;',encoding='utf8')
        artifact=client.post(f'/api/projects/{project}/artifacts',json={'path':str(target['root'])}).json()
        path=f'/api/projects/{project}/artifacts/{artifact["id"]}/analyses'
        static=wait(client,client.post(path,json={'operation':'javascript.application'}).json())
        assert static['state']=='finished',static
        _,targets=observe(client,project,'targets',{'inspector_endpoint':target['endpoint']})
        capture,record=observe(client,project,'observe',{'inspector_endpoint':target['endpoint'],'target_id':targets['targets'][0]['id'],'capture_sources':True})
        rule=next(row for row in record['scripts'] if unquote(row['url']).endswith('rule-ñ😀.cjs'))
        main=next(row for row in record['scripts'] if unquote(row['url']).endswith('main.cjs'))
        parameters={'reference_job_id':static['id'],'candidate_job_id':capture['id'],
            'mappings':[{'runtime_url':main['url'],'source_path':'unloaded.cjs'},
                        {'runtime_url':main['url'],'source_path':'absent.cjs'}]}
        # Originals can disappear; reconciliation must use the two retained, hash-bound documents.
        for original in target['root'].iterdir(): original.unlink()
        job=wait(client,client.post(path,json={'operation':'javascript.reconcile_runtime','parameters':parameters}).json())
        assert job['state']=='finished',job
        result=client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']
        matched=next(row for row in result['scripts'] if row['script_id']==rule['scriptId'])
        assert matched['state']=='ambiguous-content' and {row['path'] for row in matched['candidates']}=={'same.cjs','rule-ñ😀.cjs'}
        mapped=next(row for row in result['scripts'] if row['script_id']==main['scriptId'])
        assert mapped['state']=='content-match' and mapped['contradictions'][0]['path']=='unloaded.cjs'
        assert mapped['missing_declared_paths']==['absent.cjs']
        assert 'unloaded.cjs' in [row['path'] for row in result['unobserved_files']]
        assert result['capture_sha256']==capture['result']['analysis_sha256']
        matching=client.get('/api/jobs/'+job['id']+'/records/scripts',params={'query':'rule-'}).json()
        assert len(matching['records'])==1 and 'rule-' in matching['records'][0]['name']
        citation=client.get('/api/jobs/'+job['id']+'/records/scripts/0').json()
        assert {row['side'] for row in citation['sources']}=={'reference','candidate'}
        imported=client.app.state.evidence.load(client.app.state.evidence.export(project))
        assert client.get('/api/jobs/'+imported['id_map'][job['id']]+'/analysis.json').json()['result']==result
        # Same retained script inventory without text cannot claim content equivalence.
        passive_job,passive=observe(client,project,'observe',{'inspector_endpoint':target['endpoint'],'target_id':targets['targets'][0]['id']})
        assert all(row['source']['state']=='excluded' for row in passive['scripts'])
        declared_parameters={**parameters,'candidate_job_id':passive_job['id']}
        declared=wait(client,client.post(path,json={'operation':'javascript.reconcile_runtime','parameters':declared_parameters}).json())
        assert declared['state']=='finished',declared
        passive_result=client.get('/api/jobs/'+declared['id']+'/analysis.json').json()['result']
        assert not any(row['state'] in {'content-match','ambiguous-content'} for row in passive_result['scripts'])
        assert next(row for row in passive_result['scripts'] if row['url']==main['url'])['state']=='declared-unverified'
        assert any(row['state']=='unresolved' for row in passive_result['scripts'])
        other=store.create_project('Other project')['id']
        foreign_artifact=client.post(f'/api/projects/{other}/artifacts',json={'path':str(target['root'])}).json()
        foreign=client.post(f'/api/projects/{other}/artifacts/{foreign_artifact["id"]}/analyses',json={'operation':'javascript.reconcile_runtime','parameters':parameters})
        assert foreign.status_code==400
        reference_path=Path(static['result']['analysis_file']);reference_bytes=reference_path.read_bytes()
        reference_path.write_bytes(reference_bytes+b'\n')
        changed_reference=wait(client,client.post(path,json={'operation':'javascript.reconcile_runtime','parameters':parameters}).json())
        assert changed_reference['state']=='failed' and 'Retained analysis document changed' in changed_reference['result']['execution']['stderr']
        reference_path.write_bytes(reference_bytes)
        saved=Path(capture['result']['analysis_file']);saved.write_bytes(saved.read_bytes()+b'\n')
        rejected=wait(client,client.post(path,json={'operation':'javascript.reconcile_runtime','parameters':parameters}).json())
        assert rejected['state']=='failed' and 'Retained candidate document changed' in rejected['result']['execution']['stderr']


def test_inspector_explicit_endpoint_validation_before_recording(tmp_path):
    from theseus.inspector_runtime import websocket_address
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Invalid endpoint')['id']
        for address in ['file:///tmp/inspector','http://user:secret@127.0.0.1:9229','http://127.0.0.1:9229/?token=secret']:
            response=client.post(f'/api/projects/{project}/runtime',json={'operation':'javascript.targets','parameters':{'inspector_endpoint':address}})
            assert response.status_code==400
        assert not store.items('jobs',project)
    assert websocket_address('http://127.0.0.1:9229','ws://127.0.0.1:9229/current')=='ws://127.0.0.1:9229/current'
    with pytest.raises(ValueError,match='different endpoint'):
        websocket_address('http://127.0.0.1:9229','ws://127.0.0.1:9230/current')


def test_interruption_during_final_publication_preserves_complete_checkpoint(tmp_path):
    root=Path(__file__).resolve().parents[1]
    request=tmp_path/'request.json';output=tmp_path/'analysis.json'
    request.write_text(json.dumps({'operation':'javascript.targets','parameters':{'inspector_endpoint':'http://127.0.0.1:1'}}))
    code='''import os,sys
from pathlib import Path
from theseus import inspector_runtime as worker
original=Path.write_text
def interrupted(path,*args,**kwargs):
    if path.name=='analysis.tmp':
        original(path,'{"interrupted":',encoding='utf8')
        os._exit(19)
    return original(path,*args,**kwargs)
Path.write_text=interrupted
worker.Capture.run=lambda self: None
worker.main()
'''
    result=subprocess.run([sys.executable,'-c',code,str(request),str(output)],cwd=root,capture_output=True)
    assert result.returncode==19,result.stdout+result.stderr
    assert not output.exists() and (tmp_path/'analysis.tmp').read_text()=='{"interrupted":'
    from theseus.inspector_runtime import recording
    recovered=json.loads(recording(tmp_path))
    assert recovered['operation']=='javascript.targets' and recovered['result']['status']=='incomplete'


def test_protocol_journal_keeps_large_unsnapshotted_prefix_and_truncated_bytes(tmp_path):
    import base64
    from theseus.inspector_runtime import Capture,recording
    request={'operation':'javascript.observe','parameters':{'inspector_endpoint':'http://127.0.0.1:1','target_id':'original'}}
    capture=Capture(request,tmp_path/'analysis.json')
    for index in range(2000):
        capture.protocol({'transport':'cdp','direction':'received','recorded_at':'2026-10-18T17:00:00+00:00',
            'message':{'method':'Debugger.scriptParsed','params':{'scriptId':str(index),'url':'original-ñ-'+str(index)+'.js'}}})
    with (tmp_path/'protocol.jsonl').open('ab') as journal:journal.write(b'{"incomplete":')
    raw=recording(tmp_path);result=json.loads(raw)['result']
    assert len(result['scripts'])==len(result['events'])==2000
    assert result['scripts'][0]['url']=='original-ñ-0.js' and result['scripts'][-1]['scriptId']=='1999'
    assert result['journal_recovery']['applied_entries']==2000
    assert base64.b64decode(result['journal_recovery']['gap']['raw_base64'])==b'{"incomplete":'
    assert (tmp_path/'protocol.jsonl').read_bytes().endswith(b'{"incomplete":')


@pytest.mark.skipif(not shutil.which('node'),reason='Requires installed Node for owned Inspector fixture')
def test_passive_node_metadata_preserves_sources_and_running_target(tmp_path):
    with inspector_fixture(tmp_path/'fixture') as target, TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Original Inspector metadata')['id']
        _,discovery=observe(client,project,'targets',{'inspector_endpoint':target['endpoint']})
        selected=next(row for row in discovery['targets'] if row['type']=='node')
        assert selected['location_state']=='reported-unverified'
        job,record=observe(client,project,'observe',{'inspector_endpoint':target['endpoint'],'target_id':selected['id'],'observation_ms':300})
        assert record['capture_mode']=='passive-metadata' and record['connection_closed']
        assert record['contexts'] and any(unquote(s['url']).endswith('main.cjs') for s in record['scripts'])
        assert any(unquote(s['url']).endswith('rule-ñ😀.cjs') for s in record['scripts'])
        assert all(s['source']['state']=='excluded' for s in record['scripts'])
        methods=[row['message']['method'] for row in record['observations'] if row.get('direction')=='sent']
        assert methods==['Runtime.enable','Debugger.enable']
        tick=json.loads(target['marker'].read_text())['tick'];deadline=time.monotonic()+2
        while True:
            assert target['process'].poll() is None
            try:
                if json.loads(target['marker'].read_text())['tick']>tick:break
            except json.JSONDecodeError:pass  # The independent fixture may be writing its marker.
            assert time.monotonic()<deadline,'The live fixture heartbeat did not advance'
            time.sleep(.025)
        cited=client.get(f'/api/jobs/{job["id"]}/records/scripts/0').json();assert cited['sources'][0]['kind']=='runtime-observation'
        imported=client.app.state.evidence.load(client.app.state.evidence.export(project))
        moved=client.get(f'/api/jobs/{imported["id_map"][job["id"]]}/records/scripts/0').json()
        assert moved['record']==cited['record']


@pytest.mark.skipif(not shutil.which('node'),reason='Requires installed Node for owned Inspector fixture')
def test_explicit_source_capture_keeps_crlf_unicode_hash_and_derived_links(tmp_path):
    with inspector_fixture(tmp_path/'fixture') as target, TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Selected Inspector texts')['id']
        _,targets=observe(client,project,'targets',{'inspector_endpoint':target['endpoint']});target_id=targets['targets'][0]['id']
        before=target['rule'].read_bytes()
        job,record=observe(client,project,'observe',{'inspector_endpoint':target['endpoint'],'target_id':target_id,'capture_sources':True})
        script=next(row for row in record['scripts'] if unquote(row['url']).endswith('rule-ñ😀.cjs'))
        source=script['source'];assert source['state']=='captured' and source['text'].encode()==before
        assert source['sha256']==hashlib.sha256(before).hexdigest()
        assert source['utf8_bytes']==len(before) and source['utf16_units']==len(source['text'].encode('utf-16-le'))//2
        assert source['utf16_units']!=len(source['text'])
        assert job['result']['derived_artifacts'] and store.artifact_links(project)
        assert len(store.artifact_links(project))==len(record['artifacts'])
        assert target['rule'].read_bytes()==before
        imported=client.app.state.evidence.load(client.app.state.evidence.export(project))
        moved=client.get('/api/jobs/'+imported['id_map'][job['id']]+'/analysis.json').json()['result']
        assert moved==record


@pytest.mark.skipif(not shutil.which('node'),reason='Requires installed Node for owned Inspector fixture')
def test_stale_inspector_target_retains_discovery_without_attaching(tmp_path):
    with inspector_fixture(tmp_path/'fixture') as target, TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.app.state.store.create_project('Stale Inspector target')['id']
        job,record=observe(client,project,'observe',{'inspector_endpoint':target['endpoint'],'target_id':'not-this-target'},expected='failed')
        assert record['targets'] and 'current target ID' in record['error']
        assert not any(row.get('transport')=='cdp' for row in record['observations'])
        assert target['process'].poll() is None


@pytest.mark.skipif(not shutil.which('node'),reason='Requires installed Node for owned Inspector fixture')
def test_cancelled_inspector_retains_partial_metadata_and_leaves_target_running(tmp_path):
    with inspector_fixture(tmp_path/'fixture') as target, TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Cancel Inspector capture')['id']
        _,targets=observe(client,project,'targets',{'inspector_endpoint':target['endpoint']})
        reply=client.post(f'/api/projects/{project}/runtime',json={'operation':'javascript.observe','parameters':{
            'inspector_endpoint':target['endpoint'],'target_id':targets['targets'][0]['id'],'observation_ms':30000}})
        reply.raise_for_status();job_id=reply.json()['id'];folder=store.directory/'analyses'/job_id
        from theseus.inspector_runtime import recording
        end=time.monotonic()+10
        while True:
            raw=recording(folder)
            if raw and json.loads(raw)['result']['scripts']: break
            assert time.monotonic()<end;time.sleep(.05)
        client.post('/api/jobs/'+job_id+'/cancel').raise_for_status()
        while store.job(job_id)['state'] in {'queued','running'}:
            assert time.monotonic()<end;time.sleep(.05)
        job=store.job(job_id);assert job['state']=='cancelled'
        record=json.loads(Path(job['result']['analysis_file']).read_text(encoding='utf8'))['result']
        assert record['scripts'] and record['status']=='incomplete'
        assert target['process'].poll() is None


@pytest.mark.skipif(not shutil.which('node'),reason='Requires installed Node for owned Inspector fixture')
def test_restart_stops_only_matching_orphan_observer_and_freezes_recording(tmp_path,monkeypatch):
    import httpx
    from theseus.inspector_runtime import recording
    worker=None
    with inspector_fixture(tmp_path/'fixture') as target:
        app=create_app(tmp_path/'data');store=app.state.store;project=store.create_project('Orphaned Inspector observation')['id'];job_id=identifier()
        folder=store.directory/'analyses'/job_id;folder.mkdir(parents=True)
        targets=httpx.get(target['endpoint']+'/json/list',trust_env=False).json()
        request={'operation':'javascript.observe','parameters':{'inspector_endpoint':target['endpoint'],'target_id':targets[0]['id'],'observation_ms':30000}}
        (folder/'request.json').write_text(json.dumps(request),encoding='utf8')
        script=Path(__file__).parents[1]/'theseus/inspector_runtime.py'
        worker=subprocess.Popen([sys.executable,str(script),str(folder/'request.json'),str(folder/'analysis.json')])
        try:
            end=time.monotonic()+10
            while True:
                raw=recording(folder)
                if raw and json.loads(raw)['result']['scripts']: break
                assert time.monotonic()<end;time.sleep(.05)
            store.save_job(project,job_id,'running',{'kind':'runtime_analysis','operation':'javascript.observe','cases':[]})
            monkeypatch.setattr(subprocess,'Popen',lambda *a,**kw:pytest.fail('Recovery must not reconnect or replay'))
            reopened=create_app(tmp_path/'data');saved=reopened.state.store.job(job_id)
            assert saved['state']=='interrupted' and saved['result']['observer_recovery']['status']=='owned-observer-stopped'
            assert worker.poll() is not None and target['process'].poll() is None
            captured=Path(saved['result']['analysis_file']).read_bytes();assert json.loads(captured)['result']['scripts']
            (folder/'partial-99999999999999999999.json').write_bytes(b'changed after recovery')
            create_app(tmp_path/'data');assert Path(saved['result']['analysis_file']).read_bytes()==captured
        finally:
            if worker.poll() is None: worker.terminate();worker.wait(timeout=5)
