import json
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.native_analysis import ENGINE, engine
from test_native_analysis import wait


def analyze(client, project, path, operation, parameters=None):
    artifact = client.post('/api/projects/' + project['id'] + '/artifacts', json={'path': str(path)}).json()
    job = start(client, project, artifact['id'], operation, parameters)
    return artifact, job


def start(client, project, artifact_id, operation, parameters=None):
    response = client.post('/api/agent/call', json={'tool': 'theseus_analysis_start', 'arguments': {
        'project_id': project['id'], 'artifact_id': artifact_id, 'operation': operation, 'parameters': parameters or {}}})
    response.raise_for_status()
    job = wait(client, response.json()['result'])
    assert job['state'] == 'finished', json.dumps(job, ensure_ascii=True, indent=2)
    return job


def document(client, job):
    response = client.get('/api/jobs/' + job['id'] + '/analysis.json')
    response.raise_for_status()
    return response.json()['result']


def test_managed_retained_comparison_keeps_literal_changes_and_two_sources(tmp_path):
    compiler = shutil.which('csc') or 'C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not Path(compiler).is_file() or not engine()['available']:
        pytest.skip('Requires C# compiler and native core')
    source = (Path(__file__).parent / 'fixtures/ManagedFixture.cs').read_text(encoding='utf-8')
    artifacts, jobs = [], []
    with TestClient(create_app(tmp_path / 'data'), base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        project = client.post('/api/projects', json={'name': 'Managed versions'}).json()
        for name, constant in (('reference', '128.0'), ('same', '128.0'), ('changed', '256.0')):
            directory = tmp_path / name
            directory.mkdir()
            code, target = directory / 'Gauge.cs', directory / 'Gauge.dll'
            code.write_text(source.replace('128.0', constant), encoding='utf-8')
            subprocess.run([compiler, '/nologo', '/target:library', '/optimize+', '/debug-', '/codepage:65001',
                            '/out:' + str(target), str(code)], check=True, capture_output=True)
            artifact, job = analyze(client, project, target, 'managed.members')
            artifacts.append(artifact); jobs.append(job)
            target.unlink()  # Comparisons depend on retained observations.
        for index in (1, 2):
            job = start(client, project, artifacts[0]['id'], 'managed.compare', {
                'reference_job_id': jobs[0]['id'], 'candidate_job_id': jobs[index]['id']})
            result = document(client, job)
            methods = client.get('/api/jobs/' + job['id'] + '/records/methods', params={'query': '.ctor'}).json()
            assert methods['total'] > 0 and '.ctor' in methods['records'][0]['name']
            if index == 1:
                assert result['summary']['changed'] == 0 and result['summary']['unchanged'] > 0, result
            else:
                assert result['summary']['changed'] > 0, result
                assert any(row['status'] == 'changed' and row['left']['name'] == '.ctor' for row in result['methods'])
            headers = client.get('/api/jobs/' + job['id'] + '/records/right').json()
            assert headers['artifact_sha256'] == artifacts[index]['sha256']
            row = client.get('/api/jobs/' + job['id'] + '/records/right/0').json()
            assert row['artifact_id'] == artifacts[index]['id']
            assert job['result']['source_analyses'][1]['analysis_sha256'] == jobs[index]['result']['analysis_sha256']
        saved = Path(jobs[2]['result']['analysis_file'])
        saved.write_text(saved.read_text(encoding='utf-8') + ' ', encoding='utf-8')
        response = client.post('/api/projects/' + project['id'] + '/artifacts/' + artifacts[0]['id'] + '/analyses',
            json={'operation': 'managed.compare', 'parameters': {'reference_job_id': jobs[0]['id'], 'candidate_job_id': jobs[2]['id']}})
        job = wait(client, response.json())
        assert job['state'] == 'failed' and 'Candidate analysis changed' in job['result']['execution']['stderr']


def test_javascript_versions_and_export_shapes_use_saved_graphs(tmp_path):
    if not engine()['available']:
        pytest.skip('Requires native core')
    jobs, artifacts = [], []
    with TestClient(create_app(tmp_path / 'data'), base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        project = client.post('/api/projects', json={'name': 'JavaScript versions'}).json()
        for name, shape in (('reference', '{kind:"gauge",limit:128}'), ('candidate', '{kind:"gauge",limit:256,units:"mm"}')):
            directory = tmp_path / name
            directory.mkdir()
            (directory / 'package.json').write_text(json.dumps({'name': 'gauge', 'version': '1.0.0', 'main': 'main.js', 'type': 'module'}))
            (directory / 'main.js').write_text('export function describe(){return ' + shape + ';}', encoding='utf-8')
            archive = tmp_path / (name + '.asar')
            subprocess.run([engine()['node'], '--input-type=module', '-e',
                "import {createPackage} from '@electron/asar';await createPackage(process.argv[1],process.argv[2]);",
                str(directory), str(archive)], cwd=ENGINE, check=True, capture_output=True)
            artifact, job = analyze(client, project, archive, 'javascript.application')
            artifacts.append(artifact); jobs.append(job)
            archive.unlink()
        parameters = {'reference_job_id': jobs[0]['id'], 'candidate_job_id': jobs[1]['id']}
        versions = start(client, project, artifacts[0]['id'], 'javascript.compare_versions', parameters)
        result = document(client, versions)
        assert result['items'] and any(row['status'] == 'changed' for row in result['items']), result
        shapes = start(client, project, artifacts[0]['id'], 'javascript.compare_exports', {**parameters,
            'query': {side: {'module_path': 'main.js', 'export_name': 'describe'} for side in ('reference', 'candidate')}})
        result = document(client, shapes)
        assert result['left']['status'] == result['right']['status'] == 'selected', result
        assert result['changes'] and 'units' in json.dumps(result), result
        assert '256' in json.dumps(result), result
