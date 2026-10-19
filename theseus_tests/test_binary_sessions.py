import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.binary_analysis import engines


def wait(client, job):
    started = time.monotonic()
    while job['state'] in ('queued', 'running'):
        assert time.monotonic() - started < 180, job
        time.sleep(.1)
        job = client.get('/api/jobs/' + job['id']).json()
    return job


@pytest.mark.skipif(os.environ.get('THESEUS_TEST_GHIDRA') != '1', reason='Opt-in installed-engine integration')
def test_retained_native_project_bytes_annotations_and_reopen(tmp_path):
    setup = Path('C:/Program Files/Microsoft Visual Studio/18/Community/VC/Auxiliary/Build/vcvars64.bat')
    if not setup.is_file() or not engines()['available']:
        pytest.skip('Requires installed Ghidra/JDK and native fixture compiler')
    source = Path(__file__).parent.resolve() / 'fixtures/native_rule.c'
    script = tmp_path / 'compile.cmd'
    script.write_text('@echo off\ncall "' + str(setup) + '" >nul\nif errorlevel 1 exit /b 1\n'
        'cl /nologo /c /O2 /GS- "' + str(source) + '" /Fonative_rule.obj\nif errorlevel 1 exit /b 1\n'
        'link /nologo /DLL /NOENTRY /NODEFAULTLIB /OUT:native_rule.dll native_rule.obj\nif errorlevel 1 exit /b 1\n'
        'link /nologo /DLL /NOENTRY /NODEFAULTLIB /BASE:0x190000000 /OUT:relocated.dll native_rule.obj\nif errorlevel 1 exit /b 1\n'
        'cl /nologo /c /O2 /GS- /DBOUND=256.0 "' + str(source) + '" /Fowrong.obj\nif errorlevel 1 exit /b 1\n'
        'link /nologo /DLL /NOENTRY /NODEFAULTLIB /OUT:wrong.dll wrong.obj\nexit /b %errorlevel%\n')
    compiled = subprocess.run(['cmd.exe', '/d', '/c', str(script)], cwd=tmp_path, capture_output=True, stdin=subprocess.DEVNULL)
    assert compiled.returncode == 0, (compiled.stdout + compiled.stderr).decode(errors='replace')
    binary = tmp_path / 'native_rule.dll'
    original = binary.read_bytes()
    with TestClient(create_app(tmp_path / 'data'), base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        project = client.post('/api/projects', json={'name': 'Native project integration'}).json()
        base = '/api/projects/' + project['id']
        artifact = client.post(base + '/artifacts', json={'path': str(binary)}).json()
        session = wait(client, client.post(base + '/artifacts/' + artifact['id'] + '/binary-sessions', json={}).json())
        assert session['state'] == 'finished', session
        assert session['result']['info']['analysis_complete'] and not session['result']['info']['read_only']
        def call(operation, parameters=None, expected='finished', current=None):
            response = client.post('/api/binary-sessions/' + (current or session)['id'] + '/call',
                                   json={'operation': operation, 'parameters': parameters or {}})
            response.raise_for_status()
            job = wait(client, response.json())
            assert job['state'] == expected, job
            if expected != 'finished': return job
            return client.get('/api/jobs/' + job['id'] + '/analysis.json').json()['result']
        address = call('procedure_address', {'procedure': 'normalize_value'})
        assert call('current_document') == binary.name
        assert call('goto_address', {'address': address}) == address
        assert call('current_address') == address
        assert call('current_procedure')['address'] == address
        following = call('next_address')
        assert following != address and call('prev_address') == address
        assert call('set_comment', {'address': address, 'text': 'Previa año 779'}) == 'Previa año 779'
        assert call('set_inline_comment', {'address': address, 'text': 'En línea 779'}) == 'En línea 779'
        assert call('comment', {'address': address}) == 'Previa año 779'
        assert call('inline_comment', {'address': address}) == 'En línea 779'
        call('set_bookmark', {'address': address, 'text': 'Revisar entrada'})
        marks = call('list_bookmarks', {'type': 'Note', 'category': 'Theseus'})
        assert any(row['address'] == address and row['text'] == 'Revisar entrada' for row in marks)
        graph = call('get_call_graph')
        route = call('procedure_address', {'procedure': 'route_value'})
        assert any(edge['from'] == route and edge['to'] == address for edge in graph['edges'])
        path = call('trace_call_path', {'from_procedure': 'route_value', 'to_procedure': 'normalize_value'})
        assert path['status'] == 'observed-static-path' and len(path['path']) == 2
        limited = call('trace_call_path', {'from_procedure': 'route_value', 'to_procedure': 'normalize_value', 'max_depth': 0})
        assert limited['status'] == 'not-observed' and limited['depth_limited']
        absent = call('trace_call_path', {'from_procedure': 'normalize_value', 'to_procedure': 'route_value'})
        assert absent['status'] == 'not-observed'
        batch = call('batch_decompile', {'procedures': ['normalize_value', 'missing_fixture_function']})
        assert batch[0]['result']['pseudocode'] and batch[1]['error']
        assert call('inspect_native_api', {'procedure': address})['available']
        values = call('trace_native_values', {'procedure': 'route_value'})
        trace = values['trace']
        assert len(trace['procedures']) == 2 and not trace['truncated']
        assert any(edge['kind'] == 'argument-binding' for edge in trace['edges'])
        assert any(edge['kind'] == 'return-binding' for edge in trace['edges'])
        evidence_ids = {row['evidence']['evidence_id'] for row in values['source_observations'] if 'evidence' in row}
        assert {row['evidence_id'] for row in trace['nodes']} <= evidence_ids
        assert any(row['operation'] and row['operation']['opcode'] == 'INT_MULT' for row in trace['nodes'])
        limited_values = call('trace_native_values', {'procedure': 'route_value', 'query': {'max_depth': 0}})['trace']
        assert limited_values['truncated'] and len(limited_values['procedures']) == 1
        page_values = call('trace_native_values', {'procedure': 'route_value', 'query': {'limit': 1}})['trace']
        assert len(page_values['nodes']) == 1 and page_values['next_offset'] == 1
        call('trace_native_values', {'procedure': 'missing_fixture_function'}, expected='failed')
        assert call('current_address') == address
        mapped = call('address_to_file_offset', {'address': address})
        memory = call('read_bytes', {'address': address, 'length': 12})
        assert bytes.fromhex(memory['bytes_hex']) == original[mapped['file_offset']:mapped['file_offset'] + 12]
        dossier = call('analyze_function', {'procedure': address})['value']
        assert dossier['native_api']['available']
        assert dossier['native_value_flow']['available']
        operations = dossier['native_value_flow']['operations']
        assert any(row['opcode'] == 'INT_MULT' for row in operations)
        assert any(row['opcode'] == 'INT_ADD' for row in operations)
        constants = {int(value['constant_hex'], 16) for row in operations for value in row['inputs'] if value.get('constant_hex') is not None}
        assert {2, 7} <= constants
        typed = call('inspect_native_instruction', {'address': address})
        assert typed['status'] == 'decoded' and typed['address'] == address
        assert typed['mnemonic'] and typed['bytes']
        others = {}
        for name in ('relocated', 'wrong'):
            added = client.post(base + '/artifacts', json={'path': str(tmp_path / (name + '.dll'))}).json()
            opened = wait(client, client.post(base + '/artifacts/' + added['id'] + '/binary-sessions', json={}).json())
            assert opened['state'] == 'finished', opened
            others[name] = opened
        evidence = call('read_function_byte_evidence', {'procedure': 'clamp_value'})
        assert any(ref.get('bytes_hex') == '0000000000006040' for row in evidence['instructions'] for ref in row['referenced_targets'])
        for name, status in (('relocated', 'equal-observed'), ('wrong', 'different')):
            response = client.post('/api/agent/call', json={'tool': 'theseus_binary_compare', 'arguments': {
                'reference_session_id': session['id'], 'candidate_session_id': others[name]['id'],
                'reference_procedure': 'clamp_value', 'candidate_procedure': 'clamp_value'}})
            response.raise_for_status()
            comparison = wait(client, response.json()['result'])
            assert comparison['state'] == 'finished', comparison
            observed = client.get('/api/jobs/' + comparison['id'] + '/analysis.json').json()
            assert observed['status'] == status, observed
            if name == 'wrong':
                assert observed['differences'] and not observed['unknowns']
                assert any(ref.get('bytes_hex') == '0000000000007040' for row in observed['candidate']['instructions'] for ref in row['referenced_targets'])
            closed_other = wait(client, client.post('/api/binary-sessions/' + others[name]['id'] + '/close', json={}).json())
            assert closed_other['state'] == 'finished', closed_other
        call('procedure_address', {'procedure': 'missing_fixture_function'}, expected='failed')
        assert call('procedure_address', {'procedure': 'normalize_value'}) == address
        annotation = call('annotate_native_function', {'procedure': address, 'name': 'GaugeRule', 'comment': 'Medición año 779'})
        assert annotation['effects']['source_bytes_modified'] is False
        closed = wait(client, client.post('/api/binary-sessions/' + session['id'] + '/close', json={}).json())
        assert closed['state'] == 'finished', closed
        reopened = wait(client, client.post(base + '/artifacts/' + artifact['id'] + '/binary-sessions',
                                            json={'options': {'analysis_job_id': session['id']}}).json())
        assert reopened['state'] == 'finished', reopened
        assert call('procedure_address', {'procedure': 'GaugeRule'}, current=reopened) == address
        assert call('current_address', current=reopened) == address
        assert call('comment', {'address': address}, current=reopened) == 'Medición año 779'
        assert call('inline_comment', {'address': address}, current=reopened) == 'En línea 779'
        assert any(row['text'] == 'Revisar entrada' for row in call('list_bookmarks', current=reopened))
        call('unset_bookmark', {'address': address}, current=reopened)
        assert not call('list_bookmarks', {'type': 'Note', 'category': 'Theseus'}, current=reopened)
        restored = call('analyze_function', {'procedure': address}, current=reopened)
        assert 'Medición año 779' in json.dumps(restored, ensure_ascii=False)
        assert binary.read_bytes() == original
        assert artifact['sha256'] == hashlib.sha256(original).hexdigest()


@pytest.mark.skipif(os.environ.get('THESEUS_TEST_GHIDRA') != '1', reason='Opt-in installed-engine integration')
def test_raw_6502_context_and_exact_image(tmp_path):
    if not engines()['available']:
        pytest.skip('Requires installed Ghidra/JDK')
    binary = tmp_path / 'original6502.bin'
    original = bytes.fromhex('a97f6901851060')
    binary.write_bytes(original)
    with TestClient(create_app(tmp_path / 'data'), base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        project = client.post('/api/projects', json={'name': 'Raw 6502'}).json()
        base = '/api/projects/' + project['id']
        artifact = client.post(base + '/artifacts', json={'path': str(binary)}).json()
        route = base + '/artifacts/' + artifact['id'] + '/binary-sessions'
        assert client.post(route, json={'options': {'raw': True}}).status_code == 400
        opened = wait(client, client.post(route, json={'options': {'raw': True,
            'language_id': '6502:LE:16:default', 'base_address': '0x8000'}}).json())
        assert opened['state'] == 'finished', opened
        for operation, parameters in (('read_bytes', {'address': '0x8000', 'length': len(original)}),
                                      ('inspect_native_instruction', {'address': '0x8000'})):
            job = wait(client, client.post('/api/binary-sessions/' + opened['id'] + '/call',
                       json={'operation': operation, 'parameters': parameters}).json())
            assert job['state'] == 'finished', job
            result = client.get('/api/jobs/' + job['id'] + '/analysis.json').json()['result']
            if operation == 'read_bytes': assert result['bytes_hex'] == original.hex()
            else: assert result['mnemonic'] == 'LDA' and result['bytes'] == 'a97f'
        assert binary.read_bytes() == original
