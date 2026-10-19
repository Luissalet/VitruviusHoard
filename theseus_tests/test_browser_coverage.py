import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from fastapi.testclient import TestClient
import httpx
import pytest
import websocket

from browser_fixture import browser_fixture,browser_path
from test_browser_runtime import target_id
from test_native_analysis import wait
from theseus.api import create_app
from theseus.store import identifier


pytestmark=pytest.mark.skipif(browser_path() is None,reason='Requires owned installed Chromium fixture')
SCRIPT='\r\nfunction preciseRule(value){if(value>=128){fetch("/coverage-hit",{method:"POST",body:String(value)});return "high"}return "low"}\r\nfunction neverRule(){return "untouched"}\r\n'


def armed(client,job):
    deadline=time.monotonic()+10
    while True:
        current=client.get('/api/jobs/'+job['id']).json()
        receipt=current['result'].get('progress',{})
        if receipt.get('state')=='armed':return current
        assert current['state'] in {'queued','running'} and time.monotonic()<deadline,current
        time.sleep(.02)


def external_command(target,chosen,method,params):
    page=next(row for row in httpx.get(target['endpoint']+'/json/list',trust_env=False).json() if row['id']==chosen)
    socket=websocket.create_connection(page['webSocketDebuggerUrl'],suppress_origin=True,http_no_proxy=['*'],timeout=5)
    try:
        socket.send(json.dumps({'id':1,'method':method,'params':params}))
        while True:
            reply=json.loads(socket.recv())
            if reply.get('id')==1:return reply
    finally:socket.close()


@pytest.mark.parametrize('value,expected',[(131,'high'),(42,'low')])
def test_armed_precise_ranges_sources_and_initiators(tmp_path,value,expected):
    with browser_fixture(tmp_path/'fixture',extra_script=SCRIPT) as target,TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.app.state.store.create_project('Owned precise coverage')['id'];chosen=target_id(client,project,target)
        job=client.post(f'/api/projects/{project}/runtime',json={'operation':'browser.coverage','parameters':{'inspector_endpoint':target['endpoint'],'target_id':chosen,'observation_ms':1500}}).json()
        current=armed(client,job)
        listed=client.get('/api/projects/'+project).json();assert next(row for row in listed['jobs'] if row['id']==job['id'])['result']['progress']['state']=='armed'
        assert '/coverage-hit' not in target['requests']
        reply=external_command(target,chosen,'Runtime.evaluate',{'expression':f'preciseRule({value})','returnByValue':True})
        assert reply['result']['result']['value']==expected,reply
        terminal=wait(client,job);assert terminal['state']=='finished',terminal
        result=client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']
        assert result['coverage_window']['armed_at']==current['result']['progress']['armed_at']
        assert result['instrumentation']['cleanup']=='confirmed' and not result['instrumentation']['executes_selected_code']
        script=next(row for row in result['coverage']['scripts'] if row['reported_url'].endswith('original-%C3%B1.js'))
        indexed=client.get('/api/jobs/'+job['id']+'/records/coverage.scripts',params={'query':'original-'}).json()
        assert len(indexed['records'])==1,indexed
        item=client.get('/api/jobs/'+job['id']+'/records/coverage.scripts/'+indexed['records'][0]['record_key']).json()
        assert item['record']==script and item['sources'][0]['kind']=='runtime-observation'
        raw=target['script'].read_bytes();assert script['source']['sha256']==hashlib.sha256(raw).hexdigest()
        precise=next(row for row in script['functions'] if row['functionName']=='preciseRule')
        functions=client.get('/api/jobs/'+job['id']+'/records/coverage_functions',params={'query':'preciseRule'}).json()
        assert len(functions['records'])==1,functions
        function=client.get('/api/jobs/'+job['id']+'/records/coverage_functions/'+functions['records'][0]['record_key']).json()['record']
        assert function['ranges']==precise['ranges'] and function['source_sha256']==script['source']['sha256']
        assert precise['ranges'][0]['count']==1,precise
        assert any(row['count']==0 for row in precise['ranges']),precise
        utf16=script['source']['text'].encode('utf-16-le')
        untouched=[utf16[row['startOffset']*2:row['endOffset']*2].decode('utf-16-le') for row in precise['ranges'] if row['count']==0]
        assert any(('return "low"' if value>=128 else 'fetch(') in text for text in untouched),untouched
        # V8 can omit an uncompiled lazy function altogether; absence is not zero.
        assert result['coverage']['coverage_absence']=='unknown'
        text=raw.decode();offset=len(text[:text.index('function preciseRule')].encode('utf-16-le'))//2
        assert precise['ranges'][0]['startOffset']==offset and offset!=text.index('function preciseRule')
        assert all(r['source_bounds']=='verified' for row in script['functions'] for r in row['ranges'])
        sent=[row['message']['method'] for row in result['observations'] if row.get('direction')=='sent']
        assert sent==['Page.enable','Network.enable','Runtime.enable','Debugger.enable','Page.getFrameTree','Profiler.enable','Profiler.startPreciseCoverage','Profiler.takePreciseCoverage','Profiler.stopPreciseCoverage']+['Debugger.getScriptSource']*len(result['coverage']['scripts']),sent
        hits=[row for row in result['coverage_requests'] if row['request']['url'].endswith('/coverage-hit')]
        if value>=128:
            assert len(hits)==1 and any(row['scriptId']==script['script_id'] and row['source_sha256']==script['source']['sha256'] for row in hits[0]['callsites'])
        else:assert not hits
        assert target['process'].poll() is None


def test_cancelled_coverage_retains_armed_prefix_without_repeating_effect(tmp_path):
    with browser_fixture(tmp_path/'fixture',extra_script=SCRIPT) as target,TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.app.state.store.create_project('Cancel precise coverage')['id'];chosen=target_id(client,project,target)
        job=client.post(f'/api/projects/{project}/runtime',json={'operation':'browser.coverage','parameters':{'inspector_endpoint':target['endpoint'],'target_id':chosen,'observation_ms':30000}}).json()
        armed(client,job)
        external_command(target,chosen,'Runtime.evaluate',{'expression':"fetch('/once',{method:'POST',body:'once'}).then(()=>true)",'awaitPromise':True,'returnByValue':True})
        client.post('/api/jobs/'+job['id']+'/cancel').raise_for_status();terminal=wait(client,job)
        assert terminal['state']=='cancelled',terminal
        result=client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']
        assert result['status']=='incomplete' and result['coverage']['state']=='unavailable'
        assert result['instrumentation']['cleanup']=='not-confirmed' and result['progress']['state']=='armed'
        assert len([row for row in target['posts'] if row['path']=='/once'])==1 and target['process'].poll() is None


def test_navigation_ends_document_window_with_transition_unknown(tmp_path):
    with browser_fixture(tmp_path/'fixture',extra_script=SCRIPT) as target,TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.app.state.store.create_project('Document changes during coverage')['id'];chosen=target_id(client,project,target)
        job=client.post(f'/api/projects/{project}/runtime',json={'operation':'browser.coverage','parameters':{'inspector_endpoint':target['endpoint'],'target_id':chosen,'observation_ms':30000}}).json()
        armed(client,job);external_command(target,chosen,'Page.navigate',{'url':target['url']+'?new-document'})
        terminal=wait(client,job);assert terminal['state']=='failed',terminal
        result=client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']
        assert result['status']=='incomplete' and result['coverage_window']['end_reason']=='document_changed'
        assert result['coverage']['document_scope']=='transition-unknown' and result['progress']['state']=='incomplete'
        assert result['instrumentation']['cleanup']=='confirmed' and target['process'].poll() is None


def test_orphan_coverage_stops_only_observer_and_keeps_cleanup_unknown(tmp_path,monkeypatch):
    with browser_fixture(tmp_path/'fixture',extra_script=SCRIPT) as target:
        app=create_app(tmp_path/'data');store=app.state.store;project=store.create_project('Orphan precise coverage')['id'];job_id=identifier()
        chosen=next(row['id'] for row in httpx.get(target['endpoint']+'/json/list',trust_env=False).json() if row['url']==target['url'])
        folder=store.directory/'analyses'/job_id;folder.mkdir(parents=True)
        request={'operation':'browser.coverage','parameters':{'inspector_endpoint':target['endpoint'],'target_id':chosen,'observation_ms':30000}}
        (folder/'request.json').write_text(json.dumps(request),encoding='utf8')
        worker=subprocess.Popen([sys.executable,str(Path(__file__).parents[1]/'theseus/inspector_runtime.py'),str(folder/'request.json'),str(folder/'analysis.json')],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            deadline=time.monotonic()+10
            while not (folder/'progress.json').exists():assert worker.poll() is None and time.monotonic()<deadline;time.sleep(.02)
            assert json.loads((folder/'progress.json').read_text())['state']=='armed'
            external_command(target,chosen,'Runtime.evaluate',{'expression':"fetch('/once',{method:'POST',body:'once'}).then(()=>true)",'awaitPromise':True,'returnByValue':True})
            store.save_job(project,job_id,'running',{'kind':'runtime_analysis','operation':'browser.coverage'})
            def no_spawn(*args,**kwargs):raise AssertionError('Recovery must not start a replacement observer')
            monkeypatch.setattr(subprocess,'Popen',no_spawn)
            with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
                client.get('/')
                response=client.get('/api/jobs/'+job_id);response.raise_for_status();terminal=response.json()
                assert terminal['state']=='interrupted' and terminal['result']['recovered_recording'],terminal
                result=client.get('/api/jobs/'+job_id+'/analysis.json').json()['result']
                assert result['status']=='incomplete' and result['instrumentation']['cleanup']=='not-confirmed'
                assert len([row for row in target['posts'] if row['path']=='/once'])==1 and target['process'].poll() is None
            worker.wait(timeout=5)
        finally:
            if worker.poll() is None:worker.terminate();worker.wait(timeout=5)


def test_coverage_sources_reconcile_and_transfer_without_originals(tmp_path):
    with browser_fixture(tmp_path/'fixture',extra_script=SCRIPT) as target,TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Retain precise sources')['id'];chosen=target_id(client,project,target)
        artifact=store.add_artifact(project,target['root'])
        source=wait(client,client.post(f'/api/projects/{project}/artifacts/{artifact["id"]}/analyses',json={'operation':'javascript.application'}).json());assert source['state']=='finished',source
        job=client.post(f'/api/projects/{project}/runtime',json={'operation':'browser.coverage','parameters':{'inspector_endpoint':target['endpoint'],'target_id':chosen,'observation_ms':500}}).json()
        armed(client,job);terminal=wait(client,job);assert terminal['state']=='finished',terminal
        document=client.get('/api/jobs/'+job['id']+'/analysis.json').json()
        for path in target['root'].iterdir():path.unlink()
        reconciled=wait(client,client.post(f'/api/projects/{project}/artifacts/{artifact["id"]}/analyses',json={'operation':'browser.reconcile_sources','parameters':{'reference_job_id':source['id'],'candidate_job_id':job['id']}}).json());assert reconciled['state']=='finished',reconciled
        pair=client.get('/api/jobs/'+reconciled['id']+'/analysis.json').json()['result'];assert pair['capture_operation']=='browser.coverage'
        rows=store.analysis_records(reconciled['id'],'scripts',query='original-',limit=None)['records'];assert len(rows)==1,rows
        row=store.analysis_record(reconciled['id'],'scripts',rows[0]['record_key']);assert row['record']['state']=='content-match' and len(row['sources'])==2
        moved=client.app.state.evidence.load(client.app.state.evidence.export(project))
        assert client.get('/api/jobs/'+moved['id_map'][job['id']]+'/analysis.json').json()==document
        assert not client.get('/api/projects/'+moved['project']['id']).json()['runtime_sessions']
