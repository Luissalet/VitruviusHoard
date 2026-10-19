import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from fastapi.testclient import TestClient
import pytest

from browser_fixture import browser_fixture,browser_path
from test_browser_runtime import target_id
from test_native_analysis import wait
from theseus.api import create_app
from theseus.inspector_runtime import Capture,recording
from theseus.store import identifier

pytestmark=pytest.mark.skipif(browser_path() is None,reason='Requires owned installed Chromium headless fixture')


def scenario(client,project,target,steps,expected='finished',**options):
    chosen=target_id(client,project,target)
    reply=client.post(f'/api/projects/{project}/runtime',json={'operation':'browser.scenario','parameters':{
        'inspector_endpoint':target['endpoint'],'target_id':chosen,'steps':steps,'observation_ms':100,**options}})
    reply.raise_for_status();job=wait(client,reply.json())
    assert job['state']==expected,json.dumps(job,ensure_ascii=True,indent=2)
    document=client.get('/api/jobs/'+job['id']+'/analysis.json').json()
    return job,document['result']


def test_explicit_scenario_navigation_input_click_return_and_portable_png(tmp_path):
    with browser_fixture(tmp_path/'fixture') as target,TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.app.state.store.create_project('Original page scenario')['id']
        steps=[{'method':'Page.navigate','parameters':{'url':target['url']}},
            {'method':'Runtime.evaluate','parameters':{'expression':"new Promise(resolve=>{const focus=()=>{document.querySelector('#entry').focus();resolve(true)};if(document.readyState==='complete')focus();else addEventListener('load',focus,{once:true})})",'awaitPromise':True,'returnByValue':True,'timeout':5000}},
            {'method':'Input.insertText','parameters':{'text':'ñ😀42'}},
            {'method':'Input.dispatchMouseEvent','parameters':{'type':'mousePressed','x':40,'y':75,'button':'left','buttons':1,'clickCount':1}},
            {'method':'Input.dispatchMouseEvent','parameters':{'type':'mouseReleased','x':40,'y':75,'button':'left','buttons':0,'clickCount':1},'observe_ms':150},
            {'method':'Runtime.evaluate','parameters':{'expression':"console.log('scenario-original-ñ');({input:document.querySelector('#entry').value,lastAction:globalThis.lastAction})",'returnByValue':True}}]
        job,result=scenario(client,project,target,steps,capture_sources=True,capture_dom=True,capture_response_bodies=True,capture_screenshot=True)
        assert job['result']['mutates_device'] and result['capture_mode']=='explicit-scenario-and-selected-snapshots'
        assert all(step['state']=='completed' for step in result['steps']) and [step['request'] for step in result['steps']]==steps
        final=result['steps'][-1]['response']['result']['result']['value']
        assert final=={'input':'ñ😀42','lastAction':{'value':'ñ😀42','limit':128}},final
        posts=[row for row in target['posts'] if row['path']=='/action']
        assert len(posts)==1 and json.loads(posts[0]['body'])==final['lastAction']
        sent=[row['message'] for row in result['observations'] if row.get('direction')=='sent']
        assert [row['method'] for row in sent[:4]]==['Page.enable','Network.enable','Runtime.enable','Debugger.enable']
        assert [{'method':row['method'],'parameters':row['params']} for row in sent[4:4+len(steps)]]==[{'method':step['method'],'parameters':step['parameters']} for step in steps]
        assert any(row['method']=='Runtime.consoleAPICalled' for row in result['events'])
        assert any(row['request'].get('url','').endswith('/action') and row['body']['state']=='captured' for row in result['network'])
        image=next(row for row in job['result']['derived_artifacts'] if row['name']=='observed-page.png')
        original=client.app.state.store.artifact(project,image['id']);Path(original['path']).unlink()
        moved=client.app.state.evidence.load(client.app.state.evidence.export(project))
        reply=client.post('/api/agent/call',json={'tool':'theseus_artifact_image','arguments':{'project_id':moved['project']['id'],'artifact_id':moved['id_map'][image['id']]}})
        reply.raise_for_status();payload=reply.json()['result']
        assert payload['source']=='retained-runtime-png' and hashlib.sha256(base64.b64decode(payload['base64'])).hexdigest()==image['sha256']
        assert not client.get('/api/projects/'+moved['project']['id']).json()['runtime_sessions']


@pytest.mark.parametrize('failure',[{'method':'Original.notACommand','parameters':{}},
    {'method':'Runtime.evaluate','parameters':{'expression':"throw new Error('original-error-ñ')",'returnByValue':True}}])
def test_protocol_and_javascript_errors_stop_remaining_steps(tmp_path,failure):
    with browser_fixture(tmp_path/'fixture') as target,TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.app.state.store.create_project('Stop on scenario error')['id']
        post=lambda path:{'method':'Runtime.evaluate','parameters':{'expression':"fetch('"+path+"',{method:'POST',body:'once'}).then(()=>true)",'awaitPromise':True,'returnByValue':True}}
        steps=[post('/before-error'),failure,post('/after-error')]
        _,result=scenario(client,project,target,steps,expected='failed')
        assert result['status']=='incomplete' and len(result['steps'])==2
        assert result['steps'][0]['state']=='completed' and result['steps'][1]['state'] in {'protocol-error','javascript-exception'}
        assert len([row for row in target['posts'] if row['path']=='/before-error'])==1 and '/after-error' not in target['requests']
        assert not any(row.get('direction')=='sent' and '/after-error' in json.dumps(row['message']) for row in result['observations'])
        assert target['process'].poll() is None


def test_invalid_scenario_definition_creates_no_job_or_connection(tmp_path):
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Invalid steps')['id']
        for steps in ([],[{'method':'Page.navigate'}],[{'method':'Page.getFrameTree','parameters':{},'observe_ms':-1}]):
            reply=client.post(f'/api/projects/{project}/runtime',json={'operation':'browser.scenario','parameters':{'inspector_endpoint':'http://127.0.0.1:1','target_id':'unused','steps':steps}})
            assert reply.status_code==400,reply.text
        assert not store.items('jobs',project)


def test_scenario_cancellation_preserves_effect_once_and_incomplete_step(tmp_path):
    with browser_fixture(tmp_path/'fixture') as target,TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.app.state.store.create_project('Cancel explicit scenario')['id'];chosen=target_id(client,project,target)
        steps=[{'method':'Runtime.evaluate','parameters':{'expression':"fetch('/once',{method:'POST',body:'once'}).then(()=>true)",'awaitPromise':True,'returnByValue':True},'observe_ms':30000},
            {'method':'Runtime.evaluate','parameters':{'expression':"fetch('/must-not-run',{method:'POST',body:'late'})"}}]
        reply=client.post(f'/api/projects/{project}/runtime',json={'operation':'browser.scenario','parameters':{'inspector_endpoint':target['endpoint'],'target_id':chosen,'steps':steps}})
        reply.raise_for_status();job=reply.json();deadline=time.monotonic()+10
        try:
            while '/once' not in target['requests']:
                assert time.monotonic()<deadline;time.sleep(.05)
            client.post('/api/jobs/'+job['id']+'/cancel').raise_for_status();terminal=wait(client,job)
            assert terminal['state']=='cancelled',terminal
            result=client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']
            assert result['status']=='incomplete' and len(result['steps'])==1 and result['steps'][0]['state']!='completed'
            assert len([row for row in target['posts'] if row['path']=='/once'])==1 and '/must-not-run' not in target['requests']
            compared=wait(client,client.post(f'/api/projects/{project}/artifacts/{terminal["result"]["artifact_id"]}/analyses',json={'operation':'browser.compare','parameters':{'reference_job_id':job['id'],'candidate_job_id':job['id']}}).json())
            assert compared['state']=='finished',compared
            prefix=client.get('/api/jobs/'+compared['id']+'/analysis.json').json()['result']
            assert len(prefix['scenario_steps'])==2 and all(row['state']=='unknown-incomplete-step' for row in prefix['scenario_steps'])
            assert target['process'].poll() is None
        finally:
            current=client.get('/api/jobs/'+job['id']).json()
            if current['state'] in {'queued','running'}:client.post('/api/jobs/'+job['id']+'/cancel')


def test_scenario_orphan_recovery_does_not_repeat_applied_steps(tmp_path,monkeypatch):
    import httpx
    with browser_fixture(tmp_path/'fixture') as target:
        app=create_app(tmp_path/'data');store=app.state.store;project=store.create_project('Orphan scenario')['id'];job_id=identifier()
        chosen=next(row['id'] for row in httpx.get(target['endpoint']+'/json/list',trust_env=False).json() if row['url']==target['url'])
        steps=[{'method':'Runtime.evaluate','parameters':{'expression':"fetch('/once',{method:'POST',body:'once'}).then(()=>true)",'awaitPromise':True,'returnByValue':True},'observe_ms':30000},
            {'method':'Runtime.evaluate','parameters':{'expression':"fetch('/must-not-run',{method:'POST'})"}}]
        folder=store.directory/'analyses'/job_id;folder.mkdir(parents=True)
        request={'operation':'browser.scenario','parameters':{'inspector_endpoint':target['endpoint'],'target_id':chosen,'steps':steps}}
        (folder/'request.json').write_text(json.dumps(request),encoding='utf8')
        worker=subprocess.Popen([sys.executable,str(Path(__file__).parents[1]/'theseus/inspector_runtime.py'),str(folder/'request.json'),str(folder/'analysis.json')],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            deadline=time.monotonic()+10
            while True:
                raw=recording(folder);result=json.loads(raw)['result'] if raw else {}
                if '/once' in target['requests'] and result.get('steps') and 'response' in result['steps'][0]:break
                assert time.monotonic()<deadline;time.sleep(.05)
            store.save_job(project,job_id,'running',{'kind':'runtime_analysis','operation':'browser.scenario','parameters':request['parameters'],'cases':[]})
            monkeypatch.setattr(subprocess,'Popen',lambda *args,**kwargs:pytest.fail('Recovery must not reconnect or replay'))
            recovered=create_app(tmp_path/'data').state.store.job(job_id)
            assert recovered['state']=='interrupted' and recovered['result']['observer_recovery']['status']=='owned-observer-stopped'
            worker.wait(timeout=5);assert target['process'].poll() is None
            frozen=Path(recovered['result']['analysis_file']).read_bytes();prefix=json.loads(frozen)['result']
            assert len(prefix['steps'])==1 and prefix['steps'][0]['state']!='completed'
            assert len([row for row in target['posts'] if row['path']=='/once'])==1 and '/must-not-run' not in target['requests']
            (folder/'partial-99999999999999999999.json').write_bytes(b'late invalid checkpoint')
            create_app(tmp_path/'data');assert Path(recovered['result']['analysis_file']).read_bytes()==frozen
        finally:
            if worker.poll() is None:worker.terminate();worker.wait(timeout=5)


def test_response_between_checkpoint_and_receipt_is_recovered_without_completion(tmp_path):
    folder=tmp_path/'capture';folder.mkdir();request={'method':'Runtime.evaluate','parameters':{'expression':'128','returnByValue':True},'observe_ms':30000}
    capture=Capture({'operation':'browser.scenario','parameters':{'steps':[request]}},folder/'analysis.json')
    capture.result['steps']=[{'index':0,'name':'0 · Runtime.evaluate','request':request,'command_id':1,'state':'started'}];capture.checkpoint()
    capture.protocol({'transport':'cdp','direction':'received','recorded_at':'2026-10-18T18:00:00+00:00','raw_base64':base64.b64encode(b'{"id":1,"result":{"result":{"type":"number","value":128}}}').decode(),'message':{'id':1,'result':{'result':{'type':'number','value':128}}}})
    restored=json.loads(recording(folder))['result']['steps'][0]
    assert restored['response']['result']['result']['value']==128 and restored['state']=='response-recovered'
    assert 'unknown' in restored['recovery_note'] and 'finished_at' not in restored


def test_saved_scenario_comparison_keeps_types_and_detects_changed_return(tmp_path):
    from test_browser_runtime import observe
    with browser_fixture(tmp_path/'reference',rule_limit=128) as reference,browser_fixture(tmp_path/'candidate',rule_limit=256) as candidate,TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.app.state.store.create_project('Saved scenario returns')['id']
        steps=[{'method':'Runtime.evaluate','parameters':{'expression':"new Promise(resolve=>{const read=()=>resolve(globalThis.ruleLimit);if(document.readyState==='complete')read();else addEventListener('load',read,{once:true})})",'awaitPromise':True,'returnByValue':True}}]
        first,_=scenario(client,project,reference,steps,capture_sources=True)
        same,_=scenario(client,project,reference,steps)
        changed,_=scenario(client,project,candidate,steps)
        unaligned,_=scenario(client,project,reference,[{**steps[0],'observe_ms':0}])
        passive,_=observe(client,project,'observe',{'inspector_endpoint':reference['endpoint'],'target_id':target_id(client,project,reference),'observation_ms':100})
        artifact=client.post(f'/api/projects/{project}/artifacts',json={'path':str(reference['root'])}).json()
        static=wait(client,client.post(f'/api/projects/{project}/artifacts/{artifact["id"]}/analyses',json={'operation':'javascript.application'}).json());assert static['state']=='finished',static
        for source in (reference,candidate):
            for path in source['root'].iterdir():path.unlink()
        for other,state in ((same,'same-recorded-response'),(changed,'different-recorded-response'),(unaligned,'unknown-unaligned-literal-request')):
            compared=wait(client,client.post(f'/api/projects/{project}/artifacts/{first["result"]["artifact_id"]}/analyses',json={'operation':'browser.compare','parameters':{'reference_job_id':first['id'],'candidate_job_id':other['id']}}).json())
            assert compared['state']=='finished',compared
            result=client.get('/api/jobs/'+compared['id']+'/analysis.json').json()['result']
            assert result['capture_operations']=={'reference':'browser.scenario','candidate':'browser.scenario'} and result['scenario_steps'][0]['state']==state,result
            row=client.get('/api/jobs/'+compared['id']+'/records/scenario_steps/0').json();assert {source['side'] for source in row['sources']}=={'reference','candidate'}
        mixed=wait(client,client.post(f'/api/projects/{project}/artifacts/{passive["result"]["artifact_id"]}/analyses',json={'operation':'browser.compare','parameters':{'reference_job_id':passive['id'],'candidate_job_id':first['id']}}).json())
        assert mixed['state']=='finished',mixed
        result=client.get('/api/jobs/'+mixed['id']+'/analysis.json').json()['result']
        assert result['capture_operations']=={'reference':'browser.observe','candidate':'browser.scenario'} and result['scenario_steps']==[] and result['scenario_step_alignment']['state'].startswith('unknown')
        reconciled=wait(client,client.post(f'/api/projects/{project}/artifacts/{artifact["id"]}/analyses',json={'operation':'browser.reconcile_sources','parameters':{'reference_job_id':static['id'],'candidate_job_id':first['id']}}).json())
        assert reconciled['state']=='finished',reconciled
        result=client.get('/api/jobs/'+reconciled['id']+'/analysis.json').json()['result']
        assert result['capture_operation']=='browser.scenario' and any(row['state']=='content-match' for row in result['scripts'])
