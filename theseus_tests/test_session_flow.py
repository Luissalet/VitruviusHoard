import json
import subprocess
import sys

import psutil
from fastapi.testclient import TestClient

from theseus.api import create_app
from theseus.comparison import Comparisons
from theseus.store import Store


def test_composed_cancellation_terminates_both_owned_process_families():
    command = 'import subprocess,sys,time,json; child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); print(json.dumps(child.pid),flush=True); time.sleep(60)'
    parents = [subprocess.Popen([sys.executable, '-c', command], stdout=subprocess.PIPE, text=True) for _ in range(2)]
    try:
        children = [json.loads(process.stdout.readline()) for process in parents]
        assert all(psutil.pid_exists(pid) for pid in children)
        Comparisons._terminate(parents)
        for process in parents:
            process.wait(timeout=5)
        assert all(not psutil.pid_exists(pid) for pid in children)
    finally:
        Comparisons._terminate(parents)
        for process in parents:
            process.wait(timeout=5)
            process.stdout.close()


def test_native_node_source_identity_is_readable_after_legacy_record_import(tmp_path):
    store = Store(tmp_path/'data')
    project = store.create_project('Native source identities')
    path = tmp_path/'original.bin'
    path.write_bytes(b'original-byte-observation')
    artifact = store.add_artifact(project['id'],path)
    job_id = 'trace-job'
    store.save_job(project['id'],job_id,'finished',{'kind':'native_analysis','operation':'binary.trace_native_values',
        'artifact_id':artifact['id'],'artifact_sha256':artifact['sha256']})
    evidence_id = 'ev_'+'1'*64
    source = {'name':'analyze_function · original','evidence':{'evidence_id':evidence_id,'result':{'procedure':'original'}}}
    store.index_analysis(job_id,{'trace':{'nodes':[{'id':'node1','operation':{'opcode':'INT_ADD'},'evidence_id':evidence_id}]},
                                'source_observations':[source]})
    assert store.analysis_records(job_id,'trace.nodes',query='INT_ADD')['total'] == 1
    assert store.analysis_records(job_id,'source_observations',query=evidence_id)['total'] == 1
    assert store.analysis_record(job_id,'source_observations',evidence_id)['record'] == source
    # Earlier retained/imported analyses used the ordinal as their record key.
    with store.db() as db:
        db.execute("UPDATE analysis_records SET record_key='0' WHERE job_id=? AND section='source_observations'",(job_id,))
    assert store.analysis_record(job_id,'source_observations',evidence_id)['record'] == source


def test_native_record_route_preserves_address_and_path_identity(tmp_path):
    data = tmp_path/'data'
    app = create_app(data)
    store = Store(data)
    project = store.create_project('Native path records')
    path = tmp_path/'original.bin'
    path.write_bytes(b'original')
    artifact = store.add_artifact(project['id'],path)
    store.save_job(project['id'],'native-job','finished',{'kind':'native_analysis',
        'artifact_id':artifact['id'],'artifact_sha256':artifact['sha256']})
    record = {'id':'0x180001030/0x180001034#11','operation':{'opcode':'INT_MULT'}}
    store.index_analysis('native-job',{'trace':{'nodes':[record]}})
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        response = client.get('/api/jobs/native-job/records/trace.nodes/0x180001030%2F0x180001034%2311')
        assert response.status_code == 200,response.text
        assert response.json()['record'] == record
