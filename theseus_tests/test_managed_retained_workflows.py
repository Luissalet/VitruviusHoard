"""Imported member observations remain usable without either original assembly."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.native_analysis import engine
from test_native_analysis import wait


@pytest.fixture(scope='module')
def assemblies(tmp_path_factory):
    compiler = shutil.which('csc') or 'C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not Path(compiler).is_file() or not engine()['available']:
        pytest.skip('Requires the native core and installed C# compiler')
    folder = tmp_path_factory.mktemp('owned-retained-members')
    result = []
    for side, constant in [('left', 17), ('right', 19)]:
        directory = folder / side
        directory.mkdir()
        source = directory / 'Original.cs'
        source.write_text('public static class RetainedGauge { public static int Stable() { return 7; } '
                          'public static int Changed() { return ' + str(constant) + '; } }', encoding='utf8')
        target = directory / 'RetainedGauge.dll'
        subprocess.run([compiler, '/nologo', '/target:library', '/optimize+', '/debug-',
                        '/out:' + str(target), str(source)], check=True, capture_output=True)
        result.append(target)
    return result


def start(client, project, artifact, operation, parameters):
    response = client.post('/api/agent/call', json={'tool': 'theseus_analysis_start', 'arguments': {
        'project_id': project, 'artifact_id': artifact, 'operation': operation, 'parameters': parameters}})
    assert response.is_success, response.text
    return wait(client, response.json()['result'])


def document(client, job):
    response = client.get('/api/jobs/' + job['id'] + '/analysis.json')
    response.raise_for_status()
    return response.json()['result']


@pytest.fixture
def imported(tmp_path, assemblies, monkeypatch):
    app = create_app(tmp_path / 'data')
    with TestClient(app, base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        store = app.state.store
        project = store.create_project('Original retained member fixtures')['id']
        artifacts, jobs, members = [], [], []
        for path, constant in zip(assemblies, [17, 19]):
            artifact = store.add_artifact(project, path)
            job = start(client, project, artifact['id'], 'managed.members', {})
            assert job['state'] == 'finished', job
            value = document(client, job)
            changed = next(row for row in value['methods'] if row['name'] == 'Changed')
            instructions = changed['body']['instructions']
            # These two authored methods compile to ldc.i4.s <17|19>; ret.
            raw = b''.join(bytes.fromhex(row['bytes']) for row in instructions)
            assert raw == bytes([0x1f, constant, 0x2a])
            original = path.read_bytes()
            for row in instructions:
                body = bytes.fromhex(row['bytes'])
                assert original[row['file_offset']:row['file_offset'] + len(body)] == body
            artifacts.append(artifact); jobs.append(job); members.append(value)
        bundle = app.state.evidence.export(project)
        transfer = app.state.evidence.load(bundle)
        project = transfer['project']['id']
        mapping = transfer['id_map']
        artifacts = [store.artifact(project, mapping[row['id']]) for row in artifacts]
        jobs = [store.job(mapping[row['id']]) for row in jobs]
        assert all(row['state'] == 'imported' for row in jobs)
        parked = []
        try:
            for path in assemblies:
                other = path.with_suffix('.retained-original')
                assert not other.exists()
                path.rename(other)
                parked.append((path, other))
            assert all(not path.exists() for path in assemblies)
            original_exists = Path.exists
            def retained_exists(path):
                assert path.absolute() not in assemblies, 'Retained workflows must not inspect original-path availability'
                return original_exists(path)
            with monkeypatch.context() as patcher:
                patcher.setattr(Path, 'exists', retained_exists)
                yield client, app, project, artifacts, jobs, members
        finally:
            for path, other in parked:
                other.rename(path)


def test_imported_comparison_retains_changes_sources_and_second_transfer(imported):
    client, app, project, artifacts, jobs, _ = imported
    job = start(client, project, artifacts[0]['id'], 'managed.compare', {
        'reference_job_id': jobs[0]['id'], 'candidate_job_id': jobs[1]['id']})
    assert job['state'] == 'finished', job
    result = document(client, job)
    methods = {row['left']['name']: row for row in result['methods'] if row.get('left')}
    assert methods['Stable']['status'] == 'unchanged'
    assert methods['Changed']['status'] == 'changed' and 'cil' in methods['Changed']['dimensions']
    assert result['left']['artifact_sha256'] == artifacts[0]['sha256']
    assert result['right']['artifact_sha256'] == artifacts[1]['sha256']
    assert job['result']['original_source_check'] == 'not-performed-retained-input'
    assert all(app.state.store.job(row['id'])['state'] == 'imported' for row in jobs)
    original = Path(job['result']['analysis_file']).read_bytes()
    transfer = app.state.evidence.load(app.state.evidence.export(project))
    retained = app.state.store.job(transfer['id_map'][job['id']])
    assert Path(retained['result']['analysis_file']).read_bytes() == original
    assert {row['job_id'] for row in retained['result']['source_analyses']} == {
        transfer['id_map'][row['id']] for row in jobs}


def reconstruction_query(members, kind='semantic-pseudocode', language='pseudocode'):
    method = next(row for row in members['methods'] if row['name'] == 'Changed')
    return {'decompiler': {'name': 'Original retained method notes', 'family': 'other'}, 'methods': [{
        'token': method['token'], 'signature_sha256': method['signature']['raw_sha256'],
        'normalized_il_sha256': method['body']['normalized_il_sha256'],
        'reconstruction': {'kind': kind, 'language': language, 'text': 'Año 😀\r\nreturn 17;\r\n'}}]}


@pytest.mark.parametrize(('kind', 'language'), [
    ('decompiled-csharp', 'csharp'), ('decompiled-il', 'il'), ('semantic-pseudocode', 'pseudocode')])
def test_imported_reconstruction_keeps_exact_build_and_text(imported, kind, language):
    client, app, project, artifacts, jobs, members = imported
    query = reconstruction_query(members[0], kind, language)
    job = start(client, project, artifacts[0]['id'], 'managed.reconstruction', {'source_job_id': jobs[0]['id'], 'query': query})
    assert job['state'] == 'finished', job
    result = document(client, job)
    assert result['executed'] is False and result['static_observation']['mvid'] == members[0]['module']['mvid']
    assert result['static_observation']['artifact_sha256'] == artifacts[0]['sha256']
    recorded = result['methods'][0]
    assert recorded['validation']['canonical_observation'] is False
    expected = query['methods'][0]['reconstruction']['text']
    assert recorded['reconstruction']['text'] == expected
    assert recorded['reconstruction']['text_sha256'] == hashlib.sha256(expected.encode('utf8')).hexdigest()
    assert recorded['reconstruction']['kind'] == kind
    assert job['result']['original_source_check'] == 'not-performed-retained-input'
    transfer = app.state.evidence.load(app.state.evidence.export(project))
    retained = app.state.store.job(transfer['id_map'][job['id']])
    assert Path(retained['result']['analysis_file']).read_bytes() == Path(job['result']['analysis_file']).read_bytes()
    assert retained['result']['source_analysis_job_id'] == transfer['id_map'][jobs[0]['id']]


@pytest.mark.parametrize('lock', ['token', 'signature_sha256', 'normalized_il_sha256', 'text_sha256'])
def test_imported_reconstruction_rejects_false_method_or_text_lock(imported, lock):
    client, _, project, artifacts, jobs, members = imported
    query = reconstruction_query(members[0])
    method = query['methods'][0]
    if lock == 'text_sha256':
        method['reconstruction'][lock] = '0' * 64
    else:
        method[lock] = '0x0600ffff' if lock == 'token' else '0' * 64
    job = start(client, project, artifacts[0]['id'], 'managed.reconstruction', {'source_job_id': jobs[0]['id'], 'query': query})
    assert job['state'] == 'failed', job
    assert 'does not match' in job['result']['execution']['stderr'] or 'hash mismatch' in job['result']['execution']['stderr']


@pytest.mark.parametrize('side', [0, 1])
def test_imported_comparison_reauthenticates_each_document(imported, side):
    client, _, project, artifacts, jobs, _ = imported
    retained = Path(jobs[side]['result']['analysis_file'])
    original = retained.read_bytes()
    try:
        retained.write_bytes(original + b' ')
        job = start(client, project, artifacts[0]['id'], 'managed.compare', {
            'reference_job_id': jobs[0]['id'], 'candidate_job_id': jobs[1]['id']})
        assert job['state'] == 'failed', job
        expected = 'Retained analysis document changed' if side == 0 else 'Candidate analysis changed'
        assert expected in job['result']['execution']['stderr']
    finally:
        retained.write_bytes(original)


@pytest.mark.parametrize('invalid', ['foreign-reference', 'foreign-candidate', 'wrong-operation', 'failed-reference', 'cancelled-candidate'])
def test_imported_workflows_keep_source_admission_checks(imported, invalid):
    client, app, project, artifacts, jobs, _ = imported
    parameters = {'reference_job_id': jobs[0]['id'], 'candidate_job_id': jobs[1]['id']}
    if invalid.startswith('foreign-'):
        transfer = app.state.evidence.load(app.state.evidence.export(project))
        side = 'reference' if invalid.endswith('reference') else 'candidate'
        source = jobs[0 if side == 'reference' else 1]
        parameters[side + '_job_id'] = transfer['id_map'][source['id']]
    else:
        index = 1 if invalid == 'cancelled-candidate' else 0
        source = jobs[index]
        result = {**source['result']}
        if invalid == 'wrong-operation':
            result['operation'] = 'managed.artifact'
        app.state.store.save_job(project, source['id'],
            'cancelled' if index else 'failed' if invalid == 'failed-reference' else 'imported', result)
    before = set((app.state.store.directory / 'analyses').iterdir())
    response = client.post('/api/agent/call', json={'tool': 'theseus_analysis_start', 'arguments': {
        'project_id': project, 'artifact_id': artifacts[0]['id'], 'operation': 'managed.compare', 'parameters': parameters}})
    assert response.status_code == 400 and 'analysis' in response.text.lower()
    assert set((app.state.store.directory / 'analyses').iterdir()) == before
