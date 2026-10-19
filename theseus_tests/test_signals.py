from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from signal_fixture import uart_recording
from test_portfolio import run
from theseus.api import create_app
from theseus.native_analysis import catalog
from theseus.signals import engine


def test_signal_engine_missing_is_an_explicit_availability_reason(monkeypatch,tmp_path):
    monkeypatch.setenv('THESEUS_SIGROK',str(tmp_path/'missing.exe'))
    rows = [row for row in catalog()['operations'] if row['name'].startswith('signal.')]
    assert len(rows)==2 and all(not row['available'] and 'THESEUS_SIGROK' in row['availability_reason'] for row in rows)


@pytest.mark.skipif(not engine(),reason='Requires installed free sigrok-cli engine')
def test_real_signal_discovery_uart_paging_failures_and_evidence_transfer(tmp_path):
    source = tmp_path/'original-uart.bin'
    original = uart_recording()
    source.write_bytes(original)
    app = create_app(tmp_path/'data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        project = app.state.store.create_project('Recorded UART')
        artifact = app.state.store.add_artifact(project['id'],source)
        _, discovered = run(client,project['id'],artifact['id'],'signal.decoders',{'query':'UaRt','limit':None})
        assert discovered['status']=='available'
        assert any(row.get('decoder')=='uart' for row in discovered['lines'])
        assert discovered['engine']['sha256'] and discovered['engine']['version']['stdout'].startswith('sigrok-cli ')
        # The installed package can warn about an unrelated decoder; preserve that diagnostic.
        assert 'stderr' in discovered['observation'] and discovered['observation']['stderr_base64'] is not None
        _, help = run(client,project['id'],artifact['id'],'signal.decoders',{'decoder':'uart','query':'baudrate','limit':None})
        assert any('Baud rate' in row['text'] for row in help['lines'])
        parameters = {'decoder_stack':['uart:rx=0:baudrate=9600'],
            'input_format':'binary:numchannels=1:samplerate=96000','annotations':'uart=rx-data','line_limit':None}
        job, decoded = run(client,project['id'],artifact['id'],'signal.decode',parameters)
        assert decoded['status']=='decoded',decoded
        assert [row['annotation'] for row in decoded['lines']] == ['41','35']
        assert [row['sample_start'] for row in decoded['lines']] == ['30','130']
        assert not decoded['coverage']['decode_shortened_by_paging']
        assert decoded['snapshot_sha256']==artifact['sha256'] and source.read_bytes()==original
        assert not list(Path(job['result']['analysis_file']).parent.glob('signal-input*'))
        _, page = run(client,project['id'],artifact['id'],'signal.decode',{**parameters,'line_offset':1,'line_limit':1})
        assert page['lines']==decoded['lines'][1:] and page['coverage']['output_lines']==2
        _, empty = run(client,project['id'],artifact['id'],'signal.decode',{**parameters,'line_offset':2,'line_limit':0})
        assert not empty['lines'] and empty['coverage']['output_lines']==2
        _, failed = run(client,project['id'],artifact['id'],'signal.decode',{**parameters,'decoder_stack':['theseus_no_such_decoder']})
        assert failed['status']=='decoder-error' and failed['observation']['exit_code'] != 0
        assert failed['observation']['stderr'] and not failed['lines']
        bundle = client.get(f'/api/projects/{project["id"]}/evidence').json()
        imported = client.post('/api/evidence/import',json={'bundle':bundle,'name':'Recorded signals import'}).json()
        rows = client.get(f'/api/jobs/{imported["id_map"][job["id"]]}/records/lines').json()
        assert rows['total']==2
        line = client.get(f'/api/jobs/{imported["id_map"][job["id"]]}/records/lines/{rows["records"][0]["record_key"]}').json()
        assert line['record']==decoded['lines'][0] and source.read_bytes()==original
