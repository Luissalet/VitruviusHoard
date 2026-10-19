from fastapi.testclient import TestClient

from theseus.api import create_app


def test_candidate_and_joint_records_keep_their_own_artifact_identities(tmp_path):
    app = create_app(tmp_path / 'data')
    with TestClient(app, base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        store = app.state.store
        project = store.create_project('Two different sources')
        artifacts = []
        for name, value in (('reference', b'128'), ('candidate', b'256')):
            source = tmp_path / (name + '.bin')
            source.write_bytes(value)
            artifacts.append(store.add_artifact(project['id'], source))
        before, after = artifacts
        store.save_job(project['id'], 'comparison', 'finished', {'kind': 'native_analysis',
            'operation': 'binary.compare', 'artifact_id': before['id'], 'artifact_sha256': before['sha256'],
            'candidate_artifact_id': after['id'], 'candidate_artifact_sha256': after['sha256']})
        store.index_analysis('comparison', {'candidate_projection': [{'name': 'constant', 'value': 256}],
            'differences': [{'name': 'constant', 'reference': 128, 'candidate': 256}]})
        candidate = client.get('/api/jobs/comparison/records/candidate_projection/0').json()
        assert candidate['artifact_id'] == after['id'] and candidate['artifact_sha256'] == after['sha256']
        headers = client.get('/api/jobs/comparison/records/candidate_projection').json()
        assert headers['artifact_sha256'] == after['sha256']
        joint = client.get('/api/jobs/comparison/records/differences/0').json()
        assert {row['sha256'] for row in joint['sources']} == {before['sha256'], after['sha256']}
        saved = client.post('/api/agent/call', json={'tool': 'theseus_finding_add', 'arguments': {
            'project_id': project['id'], 'artifact_id': joint['artifact_id'], 'source_sha256': joint['artifact_sha256'],
            'location': 'comparison/differences/0', 'observation': 'Referenced constant changed', 'source_refs': joint['sources']}})
        saved.raise_for_status()
        assert saved.json()['result']['source_refs'] == joint['sources']
        exported = store.export(project['id'])
        assert exported['findings'][0]['source_refs'] == joint['sources']
        unrelated = store.create_project('Unrelated')
        alien = store.add_artifact(unrelated['id'], tmp_path / 'reference.bin')
        invalid = client.post('/api/projects/' + project['id'] + '/findings', json={
            'artifact_id': before['id'], 'location': 'test', 'observation': 'Invalid relation',
            'source_refs': [{'artifact_id': alien['id'], 'sha256': alien['sha256']}]})
        assert invalid.status_code == 404
        assert len(store.items('findings', project['id'])) == 1
