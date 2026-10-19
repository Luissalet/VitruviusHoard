import base64
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import unquote

from fastapi.testclient import TestClient
import pytest

from browser_fixture import browser_fixture,browser_path
from theseus.api import create_app
from theseus.store import identifier
from test_native_analysis import wait

pytestmark=pytest.mark.skipif(browser_path() is None,reason='Requires owned installed Chromium headless fixture')


def observe(client,project,operation,parameters,expected='finished'):
    response=client.post(f'/api/projects/{project}/runtime',json={'operation':'browser.'+operation,'parameters':parameters})
    response.raise_for_status();job=wait(client,response.json());assert job['state']==expected,job
    return job,client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']


def target_id(client,project,target):
    _,discovery=observe(client,project,'targets',{'inspector_endpoint':target['endpoint']})
    return next(row['id'] for row in discovery['targets'] if row['url']==target['url'])


def test_browser_metadata_does_not_read_dom_bodies_sources_or_screenshot(tmp_path):
    with browser_fixture(tmp_path/'fixture') as target,TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.app.state.store.create_project('Original browser metadata')['id']
        chosen=target_id(client,project,target)
        job,result=observe(client,project,'observe',{'inspector_endpoint':target['endpoint'],'target_id':chosen,'observation_ms':650})
        assert result['capture_mode']=='passive-metadata' and result['connection_closed']
        assert result['dom']['state']==result['screenshot']['state']=='excluded'
        assert not result['listeners'] and all(row['body']['state']=='excluded' for row in result['network'])
        assert any(unquote(row['url']).endswith('/original-ñ.js') for row in result['scripts'])
        assert all(row['source']['state']=='excluded' for row in result['scripts'])
        methods=[row['message']['method'] for row in result['observations'] if row.get('direction')=='sent']
        assert methods==['Page.enable','Network.enable','Runtime.enable','Debugger.enable']
        assert any(row['method']=='Network.loadingFailed' for row in result['events'])
        count=len(target['requests']);time.sleep(.4)
        assert len(target['requests'])>count and target['process'].poll() is None


def test_explicit_browser_dom_listeners_bodies_png_and_transfer(tmp_path):
    with browser_fixture(tmp_path/'fixture') as target,TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Selected browser snapshots')['id']
        chosen=target_id(client,project,target)
        job,result=observe(client,project,'observe',{'inspector_endpoint':target['endpoint'],'target_id':chosen,'observation_ms':650,
            'capture_dom':True,'listener_selector':'#measure','capture_sources':True,'capture_response_bodies':True,'capture_screenshot':True})
        assert result['capture_mode']=='page-metadata-and-selected-snapshots'
        boundary=datetime.fromisoformat(result['observation_window']['ended_at'])
        assert all(datetime.fromisoformat(row['recorded_at'])<=boundary for row in result['events'])
        assert any(datetime.fromisoformat(row['recorded_at'])>boundary for row in result['observations'] if row.get('direction')=='received')
        assert result['dom']['state']=='captured' and result['listener_selection']['matched_nodes']==1
        assert any(row['type']=='click' for row in result['listeners'][0]['listeners'])
        assert 'Measure' in json.dumps(result['dom'])
        script=next(row for row in result['scripts'] if unquote(row['url']).endswith('/original-ñ.js'))
        assert script['source']['text'].encode()==target['script'].read_bytes()
        assert script['source']['sha256']==hashlib.sha256(target['script'].read_bytes()).hexdigest()
        assert script['sourceMapURL']=='original-ñ.js.map' and not any('.map' in request for request in target['requests'])
        captured=[row for row in result['network'] if row['body']['state']=='captured']
        binary=next(row for row in captured if row['name'].endswith('/binary'))
        body=next(row for row in result['artifacts'] if row['name']==binary['body']['artifact_name'])
        assert Path(body['path']).read_bytes()==bytes([0,255,13,10]) and binary['body']['representation']=='cdp-base64-bytes'
        text=next(row for row in captured if row['name'].endswith('/text'))
        text_artifact=next(row for row in result['artifacts'] if row['name']==text['body']['artifact_name'])
        assert Path(text_artifact['path']).read_bytes()=='original ñ😀'.encode()
        assert any(row.get('loading')=='failed' and row['body']['state']=='unavailable' for row in result['network'])
        screenshot=next(row for row in result['artifacts'] if row['name']==result['screenshot']['artifact_name'])
        assert Path(screenshot['path']).read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
        image=next(row for row in job['result']['derived_artifacts'] if row['name']=='observed-page.png')
        png=client.get(f'/api/projects/{project}/artifacts/{image["id"]}/image')
        assert png.status_code==200 and png.content==Path(screenshot['path']).read_bytes()
        assert png.headers['x-content-sha256']==image['sha256'] and png.headers['content-type']=='image/png'
        image_tool=client.post('/api/agent/call',json={'tool':'theseus_artifact_image','arguments':{'project_id':project,'artifact_id':image['id']}}).json()['result']
        assert base64.b64decode(image_tool['base64'])==png.content and image_tool['sha256']==image['sha256']
        assert len(job['result']['derived_artifacts'])==len(result['artifacts'])
        assert len(store.artifact_links(project))==len(result['artifacts'])
        methods=[row['message']['method'] for row in result['observations'] if row.get('direction')=='sent']
        assert not set(methods)&{'Runtime.evaluate','Page.navigate','Page.close','Browser.close','Debugger.pause','Debugger.resume'}
        assert target['process'].poll() is None
        imported=client.app.state.evidence.load(client.app.state.evidence.export(project))
        assert client.get('/api/jobs/'+imported['id_map'][job['id']]+'/analysis.json').json()['result']==result
        assert not client.get('/api/projects/'+imported['project']['id']).json()['runtime_sessions']
        Path(screenshot['path']).unlink()
        moved_image=client.get(f'/api/projects/{imported["project"]["id"]}/artifacts/{imported["id_map"][image["id"]]}/image')
        assert moved_image.status_code==200 and moved_image.content==png.content
        moved_tool=client.post('/api/agent/call',json={'tool':'theseus_artifact_image','arguments':{'project_id':imported['project']['id'],'artifact_id':imported['id_map'][image['id']]}}).json()['result']
        assert moved_tool['source']=='retained-runtime-png' and base64.b64decode(moved_tool['base64'])==png.content
        local=tmp_path/'independent.png';local.write_bytes(png.content)
        local_artifact=store.add_artifact(project,local)
        assert client.get(f'/api/projects/{project}/artifacts/{local_artifact["id"]}/image').content==png.content
        local.write_bytes(png.content+b'changed bytes')
        assert client.get(f'/api/projects/{project}/artifacts/{local_artifact["id"]}/image').status_code==400
        imported_capture=store.job(imported['id_map'][job['id']]);retained=Path(imported_capture['result']['analysis_file'])
        retained.write_bytes(retained.read_bytes()+b'\n')
        assert client.get(f'/api/projects/{imported["project"]["id"]}/artifacts/{imported["id_map"][image["id"]]}/image').status_code==400


def test_saved_browser_comparison_and_source_reconciliation_without_live_page(tmp_path):
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Saved browser comparisons')['id']
        with browser_fixture(tmp_path/'fixture') as target:
            chosen=target_id(client,project,target)
            artifact=client.post(f'/api/projects/{project}/artifacts',json={'path':str(target['root'])}).json()
            source_path=f'/api/projects/{project}/artifacts/{artifact["id"]}/analyses'
            source=wait(client,client.post(source_path,json={'operation':'javascript.application'}).json());assert source['state']=='finished',source
            parameters={'inspector_endpoint':target['endpoint'],'target_id':chosen,'observation_ms':650,'capture_dom':True,'capture_sources':True,'capture_screenshot':True,'capture_response_bodies':True,'listener_selector':'#measure'}
            first,_=observe(client,project,'observe',parameters)
            second,_=observe(client,project,'observe',parameters)
            passive,_=observe(client,project,'observe',{'inspector_endpoint':target['endpoint'],'target_id':chosen,'observation_ms':350})
        # The browser and server are stopped; the originals disappear before comparison.
        for original in target['root'].iterdir():original.unlink()
        reconcile=wait(client,client.post(source_path,json={'operation':'browser.reconcile_sources','parameters':{'reference_job_id':source['id'],'candidate_job_id':first['id']}}).json())
        assert reconcile['state']=='finished',reconcile
        projection=client.get('/api/jobs/'+reconcile['id']+'/analysis.json').json()['result']
        assert any(row['state']=='content-match' and any(c['path']=='original-ñ.js' for c in row['candidates']) for row in projection['scripts'])
        comparison_path=f'/api/projects/{project}/artifacts/{first["result"]["artifact_id"]}/analyses'
        comparison_parameters={'reference_job_id':first['id'],'candidate_job_id':second['id']}
        comparison=wait(client,client.post(comparison_path,json={'operation':'browser.compare','parameters':comparison_parameters}).json())
        assert comparison['state']=='finished',comparison
        result=client.get('/api/jobs/'+comparison['id']+'/analysis.json').json()['result']
        assert result['dom']['state']=='different-recorded-projection'
        assert result['screenshot']['state']=='different-recorded-projection'
        assert result['listeners']['state']=='selected-observations'
        assert any(row['observation'].get('type')=='click' and row['reference_count']==row['candidate_count']==1 for row in result['listeners']['records'])
        assert any(row['observation']['url'].endswith('/binary') and row['observation']['body_sha256']==hashlib.sha256(bytes([0,255,13,10])).hexdigest() for row in result['network'])
        assert any(row['observation']['method']=='POST' and row['observation']['post_data_state']=='observed' and row['observation']['post_data'] and row['state']=='different-recorded-count' for row in result['network'])
        search=client.get('/api/jobs/'+comparison['id']+'/records/network',params={'query':'/submit'}).json()
        assert search['records'] and all('/submit' in row['name'] for row in search['records'])
        headers=client.get('/api/jobs/'+comparison['id']+'/records/network').json()['records']
        citation=client.get('/api/jobs/'+comparison['id']+'/records/network/'+headers[0]['record_key']).json()
        assert {row['side'] for row in citation['sources']}=={'reference','candidate'}
        imported=client.app.state.evidence.load(client.app.state.evidence.export(project))
        assert client.get('/api/jobs/'+imported['id_map'][comparison['id']]+'/analysis.json').json()['result']==result
        unknown=wait(client,client.post(comparison_path,json={'operation':'browser.compare','parameters':{'reference_job_id':first['id'],'candidate_job_id':passive['id']}}).json())
        assert unknown['state']=='finished',unknown
        unknown_result=client.get('/api/jobs/'+unknown['id']+'/analysis.json').json()['result']
        assert unknown_result['dom']['state']==unknown_result['screenshot']['state']=='unknown'
        assert unknown_result['listeners']['state']=='unknown' and not unknown_result['listeners']['records']
        assert any(row['unknown']==['response_body'] for row in unknown_result['network'])
        retained=Path(second['result']['analysis_file']);retained.write_bytes(retained.read_bytes()+b'\n')
        changed=wait(client,client.post(comparison_path,json={'operation':'browser.compare','parameters':comparison_parameters}).json())
        assert changed['state']=='failed' and 'Retained candidate document changed' in changed['result']['execution']['stderr']


def test_cancelled_browser_metadata_keeps_prefix_and_running_page(tmp_path):
    from theseus.inspector_runtime import recording
    with browser_fixture(tmp_path/'fixture') as target,TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Cancelled browser observation')['id']
        chosen=target_id(client,project,target)
        response=client.post(f'/api/projects/{project}/runtime',json={'operation':'browser.observe','parameters':{'inspector_endpoint':target['endpoint'],'target_id':chosen,'observation_ms':30000,'capture_dom':True}})
        response.raise_for_status();job=response.json();folder=store.directory/'analyses'/job['id'];end=time.monotonic()+10
        while True:
            raw=recording(folder)
            if raw and any(row['method']=='Network.responseReceived' for row in json.loads(raw)['result']['events']):break
            assert time.monotonic()<end;time.sleep(.05)
        client.post('/api/jobs/'+job['id']+'/cancel').raise_for_status()
        terminal=wait(client,job);assert terminal['state']=='cancelled',terminal
        result=client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']
        assert result['status']=='incomplete' and result['events'] and 'dom' not in result
        compared=wait(client,client.post(f'/api/projects/{project}/artifacts/{terminal["result"]["artifact_id"]}/analyses',json={'operation':'browser.compare','parameters':{'reference_job_id':job['id'],'candidate_job_id':job['id']}}).json())
        assert compared['state']=='finished',compared
        prefix=client.get('/api/jobs/'+compared['id']+'/analysis.json').json()['result']
        assert prefix['capture_states']=={'reference':'incomplete','candidate':'incomplete'}
        assert prefix['dom']['state']==prefix['screenshot']['state']=='unknown'
        assert any(row['unknown']==['response_body'] for row in prefix['network'])
        count=len(target['requests']);time.sleep(.4);assert len(target['requests'])>count and target['process'].poll() is None


def test_browser_restart_freezes_orphan_without_reconnecting_or_closing_target(tmp_path,monkeypatch):
    import httpx
    from theseus.inspector_runtime import recording
    with browser_fixture(tmp_path/'fixture') as target:
        app=create_app(tmp_path/'data');store=app.state.store;project=store.create_project('Orphan browser observer')['id'];job_id=identifier()
        folder=store.directory/'analyses'/job_id;folder.mkdir(parents=True)
        targets=httpx.get(target['endpoint']+'/json/list',trust_env=False).json();chosen=next(row['id'] for row in targets if row['url']==target['url'])
        request={'operation':'browser.observe','parameters':{'inspector_endpoint':target['endpoint'],'target_id':chosen,'observation_ms':30000}}
        (folder/'request.json').write_text(json.dumps(request),encoding='utf8')
        worker=subprocess.Popen([sys.executable,str(Path(__file__).parents[1]/'theseus/inspector_runtime.py'),str(folder/'request.json'),str(folder/'analysis.json')])
        try:
            end=time.monotonic()+10
            while True:
                raw=recording(folder)
                if raw and json.loads(raw)['result']['scripts']:break
                assert time.monotonic()<end;time.sleep(.05)
            store.save_job(project,job_id,'running',{'kind':'runtime_analysis','operation':'browser.observe','cases':[]})
            monkeypatch.setattr(subprocess,'Popen',lambda *a,**kwargs:pytest.fail('Recovery must not reconnect or replay'))
            restarted=create_app(tmp_path/'data');saved=restarted.state.store.job(job_id)
            assert saved['state']=='interrupted' and saved['result']['observer_recovery']['status']=='owned-observer-stopped'
            assert worker.poll() is not None and target['process'].poll() is None
            captured=Path(saved['result']['analysis_file']).read_bytes();assert json.loads(captured)['result']['scripts']
            (folder/'partial-99999999999999999999.json').write_bytes(b'late invalid recording')
            create_app(tmp_path/'data');assert Path(saved['result']['analysis_file']).read_bytes()==captured
        finally:
            if worker.poll() is None:worker.terminate();worker.wait(timeout=5)


def test_stale_browser_target_is_recorded_without_cdp_attachment(tmp_path):
    with browser_fixture(tmp_path/'fixture') as target,TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.app.state.store.create_project('Stale browser target')['id']
        _,result=observe(client,project,'observe',{'inspector_endpoint':target['endpoint'],'target_id':'not-the-owned-page'},expected='failed')
        assert result['targets'] and not any(row.get('transport')=='cdp' for row in result['observations'])
        assert target['process'].poll() is None
