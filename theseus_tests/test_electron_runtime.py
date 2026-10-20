import hashlib
import json
from urllib.parse import unquote

from fastapi.testclient import TestClient
import httpx
import pytest

from electron_fixture import electron_fixture,electron_path
from test_browser_scenarios import scenario
from test_inspector_runtime import observe
from test_native_analysis import wait
from theseus.api import create_app

pytestmark=pytest.mark.skipif(electron_path() is None,reason='Requires installed Electron engine for the original private application')


def test_original_electron_main_preload_renderer_ipc_and_retained_source_matches(tmp_path):
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Original Electron boundaries')['id']
        with electron_fixture(tmp_path/'original') as target:
            artifact=client.post(f'/api/projects/{project}/artifacts',json={'path':str(target['root'])}).json()
            path=f'/api/projects/{project}/artifacts/{artifact["id"]}/analyses'
            static=wait(client,client.post(path,json={'operation':'javascript.application'}).json())
            assert static['state']=='finished',static
            application=client.get('/api/jobs/'+static['id']+'/analysis.json').json()['result']
            assert 'gauge:read' in json.dumps(application['graph'])
            summary=application['electron_summary']
            assert [summary[key] for key in ('browser_windows','preload_entrypoints','context_bridge_apis')]==[1,1,1]
            assert summary['ipc']['paired_renderer_transmissions']==1 and summary['ipc']['main_handlers']==1
            assert {'electron-main','electron-preload','electron-renderer','ipc-handler'}.issubset(
                {row['kind'] for row in application['graph']['nodes']})
            _,targets=observe(client,project,'targets',{'inspector_endpoint':target['main_endpoint']})
            chosen=next(row for row in targets['targets'] if row['type']=='node')
            main,main_result=observe(client,project,'observe',{'inspector_endpoint':target['main_endpoint'],
                'target_id':chosen['id'],'observation_ms':100,'capture_sources':True})
            assert any(unquote(row['url']).endswith('main.cjs') for row in main_result['scripts'])
            steps=[{'method':'Runtime.evaluate','parameters':{'expression':
                'Promise.all([window.gauge.read(-1),window.gauge.read(3),window.gauge.read(128)])','awaitPromise':True,'returnByValue':True}}]
            renderer,record=scenario(client,project,target,steps,capture_sources=True,observation_ms=100)
            assert record['steps'][0]['response']['result']['result']['value']==[0,21,896]
            urls=[unquote(row['url']) for row in record['scripts']]
            assert any(url.endswith('preload.cjs') for url in urls) and any(url.endswith('renderer.js') for url in urls)
            for filename in ('preload.cjs','renderer.js'):
                script=next(row for row in record['scripts'] if unquote(row['url']).endswith(filename))
                assert script['source']['sha256']==hashlib.sha256(target['files'][filename].encode('utf8')).hexdigest()
            failed,errors=scenario(client,project,target,[{'method':'Runtime.evaluate','parameters':{
                'expression':"window.gauge.read('error')",'awaitPromise':True,'returnByValue':True}}],expected='failed',observation_ms=0)
            assert 'original-ipc-error' in json.dumps(errors)
            oracle=[json.loads(line) for line in httpx.get(target['oracle_url']+'/oracle',trust_env=False).text.splitlines()]
            assert oracle==[{'channel':'gauge:read','value':-1,'result':0},{'channel':'gauge:read','value':3,'result':21},
                {'channel':'gauge:read','value':128,'result':896},{'channel':'gauge:read','value':'error','error':'original-ipc-error-ñ'}]
            assert target['process'].poll() is None
            originals=list(target['root'].iterdir())
        assert target['process'].poll()==0
        # Stop the original before removing only this fixture's authored sources.
        for original in originals:original.unlink()
        for operation,capture in [('javascript.reconcile_runtime',main),('browser.reconcile_sources',renderer)]:
            job=wait(client,client.post(path,json={'operation':operation,'parameters':{
                'reference_job_id':static['id'],'candidate_job_id':capture['id']}}).json())
            assert job['state']=='finished',job
            result=client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']
            assert any(row['state']=='content-match' for row in result['scripts'])
            records=client.get('/api/jobs/'+job['id']+'/records/scripts').json()['records']
            cited=store.analysis_record(job['id'],'scripts',records[0]['record_key'])
            assert len(cited['sources'])==2
        moved=client.app.state.evidence.load(client.app.state.evidence.export(project))
        assert client.get('/api/jobs/'+moved['id_map'][job['id']]+'/analysis.json').json()['result']==result
        assert not client.get('/api/projects/'+moved['project']['id']).json()['runtime_sessions']


def test_electron_wrong_ipc_return_is_a_retained_response_difference(tmp_path):
    steps=[{'method':'Runtime.evaluate','parameters':{'expression':
        'Promise.all([window.gauge.read(-1),window.gauge.read(3),window.gauge.read(128)])',
        'awaitPromise':True,'returnByValue':True}}]
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Electron IPC return change')['id']
        captures=[]
        for factor in (7,8):
            with electron_fixture(tmp_path/str(factor),factor=factor) as target:
                job,record=scenario(client,project,target,steps,observation_ms=0)
                assert record['steps'][0]['response']['result']['result']['value']==[0,3*factor,128*factor]
                oracle=[json.loads(line) for line in httpx.get(target['oracle_url']+'/oracle',trust_env=False).text.splitlines()]
                assert [row['result'] for row in oracle]==[0,3*factor,128*factor]
                originals=list(target['root'].iterdir())
            assert target['process'].poll()==0
            for original in originals:original.unlink()
            captures.append(job)
        path=f'/api/projects/{project}/artifacts/{captures[0]["result"]["artifact_id"]}/analyses'
        compared=wait(client,client.post(path,json={'operation':'browser.compare','parameters':{
            'reference_job_id':captures[0]['id'],'candidate_job_id':captures[1]['id']}}).json())
        assert compared['state']=='finished',compared
        result=client.get('/api/jobs/'+compared['id']+'/analysis.json').json()['result']
        assert result['scenario_steps'][0]['state']=='different-recorded-response'
        indexed=client.get('/api/jobs/'+compared['id']+'/records/scenario_steps').json()['records']
        assert len(store.analysis_record(compared['id'],'scenario_steps',indexed[0]['record_key'])['sources'])==2
