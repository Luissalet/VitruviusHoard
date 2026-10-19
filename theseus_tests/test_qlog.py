import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.qlog import inspect_qlog
from test_portfolio import run


def frame(offset,length,fin=False,stream_id=4):
    return {'frame_type':'stream','stream_id':stream_id,'offset':offset,'length':length,'fin':fin}


def event(frames,name='transport:packet_sent'):
    return {'name':name,'time':1.25,'data':{'frames':frames}}


def document(events):
    return {'qlog_version':'0.3','qlog_format':'JSON','traces':[{
        'vantage_point':{'type':'client'},'common_fields':{'ODCID':'0123'},'events':events}]}


def save(tmp_path,doc):
    path=tmp_path/'original.qlog';path.write_text(json.dumps(doc),encoding='utf8');return path


def test_qlog_real_producer_exact_events_ranges_and_loss(tmp_path):
    from aioquic.quic.logger import QuicLogger
    from aioquic.quic.packet import QuicStreamFrame
    producer=QuicLogger();trace=producer.start_trace(True,b'\x01\x23')
    for offset,data,fin in [(0,b'abcd',False),(2,b'cdef',False),(8,b'ij',True)]:
        packet={'frames':[trace.encode_stream_frame(QuicStreamFrame(offset=offset,data=data,fin=fin),4)]}
        trace.log_event(category='transport',event='packet_sent',data=packet)
    trace.log_event(category='recovery',event='packet_lost',data={'packet_number':'9007199254740993','packet_type':'1RTT'})
    producer.end_trace(trace)
    doc=producer.to_dict();path=save(tmp_path,doc);before=path.read_bytes()
    result=inspect_qlog(path,{'profile':'aioquic-json-0.3','event_name':'lost','limit':1})
    assert result['status']=='observed' and result['coverage']['recorded_events']==4
    assert len(result['events'])==1 and result['events'][0]['name']=='recovery:packet_lost'
    stream=result['streams'][0]
    assert stream['covered_ranges']==[{'start':'0','end':'6'},{'start':'8','end':'10'}]
    assert (stream['frame_length_sum'],stream['unique_bytes'],stream['repeated_bytes'])==('10','8','2')
    assert stream['reported_final_sizes']==['10'] and stream['delivery_complete']=='unknown'
    assert result['loss_declarations'][0]['data']['packet_number']=='9007199254740993'
    assert result['traces'][0]['metadata']['common_fields']['ODCID']=='0123'
    assert result['profile']['clock']['domain']=='unix-epoch' and not result['profile']['producer_authenticated']
    assert path.read_bytes()==before


def test_qlog_numeric_tokens_unknown_fields_and_direction_separation(tmp_path):
    path=tmp_path/'exact.qlog'
    path.write_bytes(b'{"qlog_version":"0.3","traces":[{"events":[{"name":"transport:packet_sent","time":-0.00e+4,"data":{"frames":[{"frame_type":"stream","stream_id":9007199254740993,"offset":9007199254740993,"length":7,"fin":true}],"opaque":1.234567890123456789}},{"name":"transport:packet_received","time":2,"data":{"frames":[{"frame_type":"stream","stream_id":9007199254740993,"offset":0,"length":1}]}}]}]}')
    result=inspect_qlog(path,{})
    assert result['events'][0]['event']['time']=={'type':'json-number','lexeme':'-0.00e+4'}
    assert result['events'][0]['event']['data']['opaque']['lexeme']=='1.234567890123456789'
    sent,received=result['streams']
    assert sent['stream_id']=='9007199254740993'
    assert sent['covered_ranges']==[{'start':'9007199254740993','end':'9007199254741000'}]
    assert received['direction']=='received' and received['unique_bytes']=='1'
    assert result['profile']['clock']['domain']=='unknown'


def test_qlog_sequence_partial_records_exact_offsets_and_invalid_frame(tmp_path):
    path=tmp_path/'partial.sqlog'
    parts=[{'qlog_version':'0.3','qlog_format':'JSON-SEQ','trace':{'vantage_point':{'type':'server'}}},
        event([frame(0,4)]),event([frame(2,6),frame(-1,3),frame(0,1,fin='yes')])]
    records=[json.dumps(part).encode()+b'\n' for part in parts]
    raw=b'\x1e'+b'\x1e'.join(records)+b'\x1e{"broken":\n'+b'\x1e'+json.dumps(event([frame(10,0,True)])).encode()+b'\n'
    path.write_bytes(raw)
    result=inspect_qlog(path,{})
    assert result['format']=='JSON-SEQ' and result['status']=='partial'
    assert len(result['events'])==3 and len(result['diagnostics'])==3
    for row in result['events']:
        location=row['location'];piece=raw[location['byte_offset']:location['byte_offset']+location['byte_length']]
        assert json.loads(piece)['name']==row['name']
    stream=result['streams'][0]
    assert stream['unique_bytes']=='8' and stream['repeated_bytes']=='2' and stream['reported_final_sizes']==['10']
    assert result['coverage']['network_completeness']=='unknown'


@pytest.mark.parametrize('content',[
    b'{"qlog_version":"0.3","qlog_version":"0.3","traces":[]}',
    b'{"qlog_version":"0.3","traces":[{"events":NaN}]}',b'{"qlog_version":',
    b'\x1e{"broken":\n\x1e{"name":"transport:packet_sent","data":{"frames":[]}}\n'])
def test_qlog_invalid_input_does_not_silently_make_complete_empty_capture(tmp_path,content):
    path=tmp_path/'invalid.qlog';path.write_bytes(content)
    result=inspect_qlog(path,{})
    assert result['status']=='invalid-or-unsupported' and result['diagnostics'] and not result['streams']


def test_qlog_trace_indices_unknown_version_and_inconsistent_fin(tmp_path):
    doc=document([]);doc['traces']=[None,{'events':[event([frame(0,4,True),frame(4,2,True)])]}]
    path=save(tmp_path,doc)
    result=inspect_qlog(path,{'trace_index':1})
    assert result['traces'][0]['trace_index']==1 and result['events'][0]['location']['pointer']=='/traces/1/events/0'
    assert result['streams'][0]['inconsistent_final_sizes']
    assert inspect_qlog(path,{'trace_index':0})['coverage']['returned_events']==0
    for version in ['0.4',0.3]:
        doc['qlog_version']=version;path=save(tmp_path,doc)
        result=inspect_qlog(path,{})
        assert result['events'] and not result['streams'] and not result['profile']['transport_facts']


def test_qlog_invalid_protocol_ranges_remain_raw_without_derived_bytes(tmp_path):
    path=save(tmp_path,document([event([frame(2**62-1,1),frame(0,1,stream_id='9'*5000)])]))
    result=inspect_qlog(path,{})
    assert result['status']=='partial' and len(result['diagnostics'])==2
    assert not result['streams'] and len(result['events'][0]['event']['data']['frames'][1]['stream_id'])==5000


def test_qlog_native_api_paged_source_record_and_transfer(tmp_path):
    doc=document([event([frame(0,4)]),event([frame(0,4)],'transport:packet_received')])
    path=save(tmp_path,doc)
    app=create_app(tmp_path/'data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        pid=app.state.store.create_project('Offline original qlog')['id']
        artifact=app.state.store.add_artifact(pid,path)
        job,result=run(client,pid,artifact['id'],'network.qlog',{'offset':1,'limit':1})
        assert result['coverage']['recorded_events']==2 and result['coverage']['returned_events']==1
        records=client.get('/api/jobs/'+job['id']+'/records/events').json()
        row=client.get('/api/jobs/'+job['id']+'/records/events/'+records['records'][0]['record_key']).json()
        assert row['sources'][0]['sha256']==artifact['sha256']
        assert row['record']['location']['pointer']=='/traces/0/events/1'
        app.state.store.add_finding(pid,artifact['id'],row['record']['location']['pointer'],'Recorded received STREAM frame','Delivery remains unknown')
        imported=app.state.evidence.load(app.state.evidence.export(pid))
        moved=client.get('/api/jobs/'+imported['id_map'][job['id']]+'/analysis.json').json()
        assert moved['result']==result and path.read_bytes()==json.dumps(doc).encode()
