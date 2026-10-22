"""Loopback protocol witnesses and historical observation lifecycle."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import socketserver
import threading
import uuid

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.cutter import CutterBridge, PLUGIN
from theseus.comparison import Comparisons
from theseus.evidence import Evidence
from theseus.store import Store
from theseus.workflow import Workflow


@contextmanager
def endpoint(directory, response=None):
    directory.mkdir(mode=0o700)
    session = str(uuid.uuid4())
    calls = []
    status = dict(session_id=session, pid=17001, document_generation=3,
                  current_file='original.elf', cutter_version='fixture', identity_status='partial')

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            request = json.loads(self.rfile.readline())
            calls.append(request)
            assert request['token'] == 'x' * 40
            assert request['session_id'] == session
            if request['method'] == 'status':
                value = status
            else:
                value = response(request) if response else {
                    'command': request['parameters']['command'], 'output': '63\n',
                    'execution_state': 'complete', 'error': None, 'message': 'Returned',
                    'output_truncated': False, **{k: v for k, v in status.items() if k not in {'session_id', 'pid'}}}
                if value is None:
                    return  # Response lost after receipt; no replay is safe.
            self.wfile.write((json.dumps(dict(request_id=request['request_id'], session_id=session,
                                             pid=17001, result=value)) + '\n').encode())

    server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    descriptor = dict(protocol=1, session_id=session, pid=17001, port=server.server_address[1], token='x' * 40)
    (directory / (session + '.json')).write_text(json.dumps(descriptor))
    try:
        yield CutterBridge(directory=directory, timeout=.2), session, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_authenticated_discovery_excludes_credentials_and_dead_descriptors(tmp_path):
    with endpoint(tmp_path / 'bridge') as (bridge, session, calls):
        dead = dict(protocol=1, session_id=str(uuid.uuid4()), pid=999, port=1, token='y' * 40)
        (bridge.directory / (dead['session_id'] + '.json')).write_text(json.dumps(dead))
        observed = bridge.discover()
        assert observed['discovery_status'] == 'sessions_found'
        assert observed['sessions'] == [dict(session_id=session, pid=17001, document_generation=3,
            current_file='original.elf', cutter_version='fixture', identity_status='partial')]
        assert 'token' not in json.dumps(observed) and 'x' * 40 not in json.dumps(observed)
        assert calls[0]['method'] == 'status'


@pytest.mark.parametrize('generation,command,as_json', [
    (True, 'iIj', False), (-1, 'iIj', False), (3, '', False),
    (3, 'iIj\nq', False), (3, 'iIj\rq', False), (3, 'iIj', 'true')])
def test_invalid_input_sends_nothing(tmp_path, generation, command, as_json):
    with endpoint(tmp_path / 'bridge') as (bridge, session, calls):
        with pytest.raises(ValueError):
            bridge.execute(session, generation, command, as_json)
        assert not calls


def test_lost_response_is_unknown_and_never_retried(tmp_path):
    with endpoint(tmp_path / 'bridge', lambda request: None) as (bridge, session, calls):
        observed = bridge.execute(session, 3, 'f own_mark')
        assert observed['execution_state'] == 'unknown'
        assert 'Do not retry' in observed['message']
        assert len(calls) == 1


def test_missing_descriptor_is_not_started(tmp_path):
    result = CutterBridge(directory=tmp_path).execute(str(uuid.uuid4()), 17, 'iIj')
    assert result['execution_state'] == 'not_started'
    assert result['document_generation'] == 17
    assert result['output'] is None


def test_arbitrary_command_and_json_selection_cross_protocol_exactly(tmp_path):
    with endpoint(tmp_path / 'bridge') as (bridge, session, calls):
        command = 'f own_mark 1 @ 0x401000; flj'
        assert bridge.execute(session, 3, command, True)['execution_state'] == 'complete'
        assert calls[0]['parameters'] == dict(expected_generation=3, command=command, json=True)
        assert len(calls) == 1


def test_retained_observation_survives_export_without_live_bridge(tmp_path):
    store = Store(tmp_path / 'data')
    project = store.create_project('Own command')
    with endpoint(tmp_path / 'bridge') as (bridge, session, calls):
        bridge.store = store
        observed = bridge.command(project['id'], session, 3, '%vi 7*9')
        assert len(calls) == 1
    job = store.job(observed['job_id'])
    assert job['state'] == 'finished'
    raw = Path(job['result']['analysis_file']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == job['result']['analysis_sha256']
    assert store.analysis_record(job['id'], 'output', '0')['record'] == '63\n'
    comparisons = Comparisons(store)
    try:
        evidence = Evidence(Workflow(comparisons))
        imported = evidence.load(evidence.export(project['id']))
        assert imported['project']['id'] != project['id']
        imported_jobs = store.items('jobs', imported['project']['id'])
        copied = next(row for row in imported_jobs if row['result'].get('operation') == 'cutter.command')
        assert copied['state'] == 'imported'
        assert Path(copied['result']['analysis_file']).read_bytes() == raw
        assert store.analysis_record(copied['id'], 'output', '0')['record'] == '63\n'
    finally:
        comparisons.shutdown()


def test_recovery_retains_unknown_without_contact_or_execution(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data')
    project = store.create_project('Interrupted own command')
    job_id = uuid.uuid4().hex
    (store.directory / 'analyses' / job_id).mkdir(parents=True)
    store.save_job(project['id'], job_id, 'running', dict(kind='runtime_analysis', operation='cutter.command',
        request=dict(command='f own_mark', expected_generation=2)))
    monkeypatch.setattr(CutterBridge, '_exchange', lambda *args: pytest.fail('Recovery must not connect'))
    app = create_app(store.directory, port=64329, recover=False)
    bridge = app.state.cutter
    job = store.job(job_id)
    assert job['state'] == 'interrupted'
    assert store.analysis_record(job_id, 'execution_state', '0')['record'] == 'unknown'
    before = Path(job['result']['analysis_file']).read_bytes()
    bridge.recover()
    assert Path(job['result']['analysis_file']).read_bytes() == before
    with TestClient(app):
        pass


def test_retention_failure_reports_received_completion_without_replay(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data')
    project = store.create_project('Disk failure')
    with endpoint(tmp_path / 'bridge') as (bridge, session, calls):
        bridge.store = store
        def fail(*args):
            raise OSError('Own injected full disk')
        monkeypatch.setattr(bridge, '_retain', fail)
        result = bridge.command(project['id'], session, 3, 'f own_mark')
        assert result['execution_state'] == 'complete'
        assert result['retention_error']
        assert len(calls) == 1
        assert store.job(result['job_id'])['state'] == 'running'


def test_api_and_tool_share_retention_and_strict_generation(tmp_path, monkeypatch):
    monkeypatch.setenv('HOARD_EVENTS', '0')
    with endpoint(tmp_path / 'bridge') as (bridge, session, calls):
        monkeypatch.setenv('THESEUS_CUTTER_BRIDGE_DIR', str(bridge.directory))
        app = create_app(tmp_path / 'data', port=64329, recover=False)
        token = (app.state.store.directory / 'mcp-token').read_text()
        with TestClient(app, base_url='http://127.0.0.1:64329', headers={'Authorization': 'Bearer ' + token}) as client:
            project = app.state.store.create_project('API own session')
            assert client.get('/api/cutter/plugin.py').content == PLUGIN.read_bytes()
            assert client.get('/api/cutter/sessions').json()['sessions'][0]['session_id'] == session
            body = dict(session_id=session, expected_generation=True, command='iIj')
            assert client.post('/api/projects/' + project['id'] + '/cutter/command', json=body).status_code == 422
            body['expected_generation'] = 3
            result = client.post('/api/agent/call', json={'tool':'theseus_cutter_command',
                'arguments':{**body,'project_id':project['id']}})
            assert result.status_code == 200, result.text
            observation = result.json()['result']
            assert observation['output'] == '63\n'
            assert client.get('/api/jobs/' + observation['job_id'] + '/analysis.json').json()['result']['output'] == '63\n'
            catalog = client.get('/api/agent/tools').json()['tools']
            tool = next(row for row in catalog if row['name'] == 'theseus_cutter_command')
            assert tool['annotations']['destructiveHint'] and not tool['annotations']['readOnlyHint']
