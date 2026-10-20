import base64
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from browser_fixture import browser_fixture,browser_path
from test_browser_scenarios import scenario
from test_native_analysis import wait
from websocket_fixture import websocket_fixture,expression
from theseus.api import create_app
from theseus.browser_capture import network_inventory
from theseus.browser_websocket import compare,inventory


def event(method,key,**params):
    return {'method':'Network.webSocket'+method,'parameters':{'requestId':key,**params}}


def stream(key,payload='A',url='ws://localhost/same'):
    return [event('Created',key,url=url),event('FrameSent',key,
        response={'opcode':1,'mask':True,'payloadData':payload}),event('FrameReceived',key,
        response={'opcode':1,'mask':False,'payloadData':'echo:'+payload}),event('Closed',key)]


def capture(events,**fields):return {'status':'observed','events':events,**fields}


def test_same_url_streams_ignore_cross_connection_order_and_preserve_multiplicity():
    left=capture(stream('old1','A')+stream('old2','B'))
    right=capture(stream('new2','B')+stream('new1','A'))
    records=compare(left,right)
    assert len(records)==2 and all(row['state']=='same-recorded-stream-count' for row in records)
    assert all(row['reference_count']==row['candidate_count']==1 for row in records)
    assert all(row['unknown']==['whole-connection-completeness'] for row in records)
    extra=compare(left,capture(right['events']+stream('new3','B')))
    assert len([row for row in extra if row['state']=='different-recorded-stream-count'])==1
    changed=next(row for row in extra if row['state']=='different-recorded-stream-count')
    assert (changed['reference_count'],changed['candidate_count'])==(1,2)


@pytest.mark.parametrize('change',['payload','order','direction','opcode','mask'])
def test_literal_message_content_direction_opcode_mask_and_order_are_not_normalized(change):
    left=stream('left','{"id":1}')
    right=stream('right','{"id":1}')
    if change=='payload':right[1]['parameters']['response']['payloadData']='{"id":2}'
    elif change=='order':right[1],right[2]=right[2],right[1]
    elif change=='direction':right[1]['method']='Network.webSocketFrameReceived'
    elif change=='opcode':right[1]['parameters']['response']['opcode']=2
    else:right[1]['parameters']['response']['mask']=False
    records=compare(capture(left),capture(right))
    assert len(records)==2 and all(row['state']=='different-recorded-stream-count' for row in records)
    assert sum(row['reference_count'] for row in records)==sum(row['candidate_count'] for row in records)==1


def test_message_bytes_and_unknown_boundaries_preserve_raw_values():
    binary=bytes([0,255,1,128]);encoded=base64.b64encode(binary).decode()
    events=[event('FrameReceived','partial',response={'opcode':1,'mask':False,'payloadData':'ñ😀'}),
        event('FrameReceived','partial',response={'opcode':2,'mask':False,'payloadData':encoded}),
        event('FrameReceived','partial',response={'opcode':2,'mask':False,'payloadData':'not base64!'}),
        event('FrameError','partial',errorMessage='original diagnostic')]
    result=capture(events,status='incomplete',journal_recovery={'gap':{'raw_base64':'YQ=='}})
    row=inventory(result)[0]
    assert row['url'] is None and row['event_indices']==list(range(4))
    assert row['events'][0]['payload_bytes']==len('ñ😀'.encode())
    assert row['events'][1]['payload_sha256']==hashlib.sha256(binary).hexdigest()
    assert row['events'][2]['payload_state']=='unavailable' and row['events'][2]['reported_message']['payloadData']=='not base64!'
    assert row['events'][3]=={'kind':'error','message':'original diagnostic'}
    assert set(row['unknown'])=={'whole-connection-completeness','start-not-observed','end-not-observed',
        'incomplete-capture','protocol-journal-gap','payload-bytes-unavailable'}
    same=compare(result,result)[0]
    assert same['state']=='same-recorded-stream-count' and same['unknown']==sorted(row['unknown'])


def test_websocket_events_do_not_create_phantom_http_inventory_rows():
    events=stream('ws')+[{'method':'Network.requestWillBeSent','parameters':{'requestId':'http',
        'request':{'url':'http://localhost/original','method':'POST','postData':'ñ😀'}}},
        {'method':'Network.loadingFinished','parameters':{'requestId':'http'}}]
    rows=network_inventory(events)
    assert len(rows)==1 and rows[0]['request_id']=='http' and rows[0]['loading']=='finished'
    assert rows[0]['request']['postData']=='ñ😀'


def test_old_saved_http_projection_keeps_recorded_body_and_excludes_websocket_placeholder(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'theseus'))
    from browser_compare import network
    original=capture(stream('ws'),network=[
        {'request_id':'ws','event_indices':[0,1,2,3],'body':{'state':'unavailable'}},
        {'request_id':'http','request':{'url':'http://localhost/retained','method':'POST','postData':'{"id":1}'},
            'loading':'finished','body':{'state':'captured','sha256':'exact-original-body','representation':'reported-utf8-text'}}])
    projected=network(original)
    assert len(projected)==1 and projected[0]['url']=='http://localhost/retained'
    assert projected[0]['body_sha256']=='exact-original-body' and projected[0]['post_data']=='{"id":1}'
    assert original['network'][0]['request_id']=='ws'  # The historical receipt remains unchanged.


@pytest.mark.skipif(browser_path() is None,reason='Requires owned installed software Chromium fixture')
def test_native_saved_websocket_streams_oracle_citations_and_transfer_after_original_closes(tmp_path):
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Original WebSocket streams')['id']
        jobs=[]
        with websocket_fixture() as server,browser_fixture(tmp_path/'fixture') as target:
            for order in (['A','B'],['B','A'],['A','C'],['A','B','B']):
                steps=[{'method':'Runtime.evaluate','parameters':{'expression':expression(server['url'],order),
                    'awaitPromise':True,'returnByValue':True,'timeout':5000}}]
                job,result=scenario(client,project,target,steps,observation_ms=0,capture_response_bodies=True)
                assert result['steps'][0]['response']['result']['result']['value']==[
                    value for label in order for value in ('echo:'+label+'ñ😀',[0,255,1,128])]
                socket_ids={row['parameters']['requestId'] for row in result['events'] if row['method']=='Network.webSocketCreated'}
                assert len(socket_ids)==len(order)
                assert not socket_ids.intersection(row['request_id'] for row in result['network'])
                assert all(row['message']['params']['requestId'] not in socket_ids for row in result['observations']
                    if row.get('direction')=='sent' and row['message']['method']=='Network.getResponseBody')
                jobs.append(job)
            assert sum(row['kind']=='opened' for row in server['oracle'])==9
            assert sum(row['kind']=='received' for row in server['oracle'])==18
            assert sum(row['kind']=='closed' for row in server['oracle'])==9
            assert len([row for row in server['oracle'] if row['kind']=='received' and row['type']=='binary'])==9
        # Every comparison below reads retained JSON with the original browser
        # and independent message server already closed.
        def saved(candidate):
            job=wait(client,client.post(f'/api/projects/{project}/artifacts/{jobs[0]["result"]["artifact_id"]}/analyses',
                json={'operation':'browser.compare','parameters':{'reference_job_id':jobs[0]['id'],'candidate_job_id':candidate['id']}}).json())
            assert job['state']=='finished',job
            return job,client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']
        equal,result=saved(jobs[1]);rows=result['websocket_streams']
        assert len(rows)==2 and all(row['state']=='same-recorded-stream-count' for row in rows)
        assert all(row['reference_count']==row['candidate_count']==1 for row in rows)
        assert all(row['unknown']==['whole-connection-completeness'] for row in rows)
        assert result['websocket_scope']['ordering']=='exact-inside-each-stream'
        assert len([row for row in saved(jobs[2])[1]['websocket_streams'] if row['state']=='different-recorded-stream-count'])==2
        multiple=saved(jobs[3])[1]['websocket_streams']
        assert len([row for row in multiple if row['reference_count']==1 and row['candidate_count']==2])==1
        indexed=client.get('/api/jobs/'+equal['id']+'/records/websocket_streams',params={'query':'/same'}).json()
        assert len(indexed['records'])==2
        key=indexed['records'][0]['record_key'];record=store.analysis_record(equal['id'],'websocket_streams',key)
        assert len(record['sources'])==2 and all(row['sha256'] for row in record['sources'])
        moved=client.app.state.evidence.load(client.app.state.evidence.export(project))
        imported=store.analysis_record(moved['id_map'][equal['id']],'websocket_streams',key)
        assert imported['record']==record['record'] and len(imported['sources'])==2
        assert not client.get('/api/projects/'+moved['project']['id']).json()['runtime_sessions']
