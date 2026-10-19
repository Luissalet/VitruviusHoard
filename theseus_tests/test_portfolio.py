import hashlib
import json
from pathlib import Path
import plistlib
import zipfile

from fastapi.testclient import TestClient
import pytest

from native_fixtures import macho_image, nib_archive
from test_native_analysis import managed_fixture, wait
from theseus.api import create_app
from theseus.inspection import digest
from theseus.evidence import fingerprint


def run(client, pid, artifact_id, operation, parameters=None):
    reply = client.post('/api/agent/call', json={'tool': 'theseus_analysis_start', 'arguments': {
        'project_id': pid, 'artifact_id': artifact_id, 'operation': operation, 'parameters': parameters or {}}})
    reply.raise_for_status()
    job = wait(client, reply.json()['result'])
    assert job['state'] == 'finished', job
    return job, client.get('/api/jobs/' + job['id'] + '/analysis.json').json()['result']


def test_directory_graph_identity_excerpts_and_extraction_relationships(tmp_path):
    source = tmp_path / 'application'
    source.mkdir()
    (source / 'empty').mkdir()
    (source / 'package.json').write_text(json.dumps({'name': 'original-fixture', 'main': 'rule.cjs'}))
    (source / 'rule.cjs').write_text('exports.normalize=n=>n<10?n+128:-1;')
    before = digest(source)
    app = create_app(tmp_path / 'data')
    with TestClient(app, base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        store = app.state.store
        pid = store.create_project('Directory application')['id']
        artifact = store.add_artifact(pid, source)
        assert artifact['inspection']['format'] == 'directory'
        excerpt = client.get(f'/api/projects/{pid}/artifacts/{artifact["id"]}/excerpt', params={'member': 'rule.cjs'}).json()
        assert excerpt['text'].endswith('n+128:-1;') and not excerpt['source_changed']
        job, graph = run(client, pid, artifact['id'], 'javascript.application')
        assert graph['format'] == 'directory' and graph['statistics']['parsed_javascript_files'] == 1
        assert job['result']['artifact_sha256'] == before
        assert not job['result']['source_changed'] and not job['result']['source_unavailable']
        extracted, result = run(client, pid, artifact['id'], 'artifact.extract')
        assert {r['relative_path'] for r in result['artifacts']} == {'package.json', 'rule.cjs'}
        links = store.artifact_links(pid)
        assert len(links) == 2 and all(row['parent_id'] == artifact['id'] for row in links)
        assert len(extracted['result']['derived_artifacts']) == 2
        for link in links:
            child = store.artifact(pid, link['child_id'])
            assert Path(child['path']).read_bytes() == (source / link['source_location']).read_bytes()
        exported = app.state.evidence.export(pid)
        transferred = app.state.evidence.load(exported)
        assert len(store.artifact_links(transferred['project']['id'])) == 2
        invalid = json.loads(json.dumps(exported))
        invalid['payload']['artifact_links'].append({**invalid['payload']['artifact_links'][0], 'source_location': 'different'})
        invalid['manifest']['sha256'] = fingerprint(invalid['payload'])
        with pytest.raises(ValueError, match='Duplicate extracted artifact relationship'):
            app.state.evidence.load(invalid)
        assert digest(source) == before
        (source / 'rule.cjs').write_text('exports.normalize=n=>n+256;')
        current = client.get(f'/api/projects/{pid}/artifacts/{artifact["id"]}/excerpt', params={'member': 'rule.cjs'}).json()
        assert current['source_changed']
        assert client.get(f'/api/projects/{pid}/artifacts/{artifact["id"]}/excerpt', params={'member': '../outside'}).status_code == 400


@pytest.mark.parametrize(('suffix', 'operation', 'files', 'component'), [
    ('.apk', 'android.application', {'AndroidManifest.xml': b'<manifest/>', 'classes.dex': b'dex\n035\0'+bytes(104)}, 'dex'),
    ('.hap', 'harmony.application', {'module.json': b'{"module":{"name":"entry"}}', 'ets/modules.abc': b'PANDA\0fixture'}, 'bytecode'),
    ('.ipa', 'apple.application', {'Payload/Gauge.app/Info.plist': plistlib.dumps({'CFBundleExecutable': 'Gauge'}),
                                 'Payload/Gauge.app/Gauge': macho_image()}, 'bundle_metadata'),
])
def test_mobile_package_inventory_projects_original_identities(tmp_path, suffix, operation, files, component):
    target = tmp_path / ('original' + suffix)
    with zipfile.ZipFile(target, 'w') as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    before = target.read_bytes()
    app = create_app(tmp_path / 'data')
    with TestClient(app, base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        pid = app.state.store.create_project(operation)['id']
        artifact = app.state.store.add_artifact(pid, target)
        _, inventory = run(client, pid, artifact['id'], 'artifact.inventory')
        assert inventory['manifest']['root_sha256'] == hashlib.sha256(before).hexdigest()
        _, graph = run(client, pid, artifact['id'], operation)
        assert graph['components'][component]
        assert graph['root_sha256'] == artifact['sha256']
        assert graph['coverage']['inventory_complete'] if 'inventory_complete' in graph['coverage'] else True
        assert target.read_bytes() == before


def test_managed_graph_contains_cil_calls_and_pinvoke_without_loading_clr(tmp_path, managed_fixture):
    app = create_app(tmp_path / 'data')
    before = managed_fixture.read_bytes()
    with TestClient(app, base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        pid = app.state.store.create_project('Managed graph')['id']
        artifact = app.state.store.add_artifact(pid, managed_fixture)
        _, graph = run(client, pid, artifact['id'], 'managed.graph')
        assert graph['summary']['methods'] > 4
        assert graph['summary']['pinvoke_imports'] > 0
        assert any(row['kind'] == 'managed-method' for row in graph['graph']['nodes'])
        assert graph['graph']['edges']
        assert managed_fixture.read_bytes() == before


def test_interface_builder_decodes_original_nib_and_assets_report_host_condition(tmp_path):
    bundle = tmp_path / 'Gauge.app'
    (bundle / 'Contents/Resources').mkdir(parents=True)
    (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'Gauge'}))
    nib = bundle / 'Contents/Resources/Main.nib'
    nib.write_bytes(nib_archive())
    app = create_app(tmp_path / 'data')
    with TestClient(app, base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        pid = app.state.store.create_project('Interface Builder')['id']
        artifact = app.state.store.add_artifact(pid, bundle)
        _, result = run(client, pid, artifact['id'], 'apple.interface_builder')
        assert result['documents'] and result['graph']['nodes']
        assert nib.read_bytes() == nib_archive()
        import sys
        if sys.platform != 'darwin':
            reply = client.post(f'/api/projects/{pid}/artifacts/{artifact["id"]}/analyses', json={'operation': 'apple.assets'})
            assert reply.status_code == 400 and 'darwin' in reply.text
