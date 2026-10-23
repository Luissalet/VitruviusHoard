"""Retained managed graphs cite selected observations, never original assemblies."""
import base64
import copy
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.native_analysis import engine
from test_native_analysis import wait

FACETS = ['managed.artifact', 'managed.members', 'managed.native_boundaries']


def run(client, project, artifact, operation, parameters=None):
    response = client.post('/api/agent/call', json={'tool': 'theseus_analysis_start', 'arguments': {
        'project_id': project, 'artifact_id': artifact, 'operation': operation, 'parameters': parameters or {}}})
    assert response.is_success, response.text
    return wait(client, response.json()['result'])


def saved(client, job):
    response = client.get('/api/jobs/' + job['id'] + '/analysis.json')
    response.raise_for_status()
    return response.json()


@pytest.fixture(scope='module')
def assembly(tmp_path_factory):
    compiler = shutil.which('csc') or 'C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not Path(compiler).is_file() or not engine()['available']:
        pytest.skip('Requires installed C# compiler and native core')
    directory = tmp_path_factory.mktemp('owned-retained-graph')
    source = directory / 'Original.cs'
    source.write_text('using System.Runtime.InteropServices; public static class Gauge {'
        'public static int Value; public static int Stable() { return 7; } '
        'public static int Changed() { return 17; } '
        '[DllImport("owned-native-missing", EntryPoint="owned_probe")] public static extern int Native(); }', encoding='utf8')
    target = directory / 'Gauge.dll'
    subprocess.run([compiler, '/nologo', '/target:library', '/optimize+', '/debug-', '/out:' + str(target), str(source)],
                   capture_output=True, check=True)
    return target


@pytest.fixture
def retained(tmp_path, assembly, monkeypatch, request):
    app = create_app(tmp_path / 'data')
    # In-process ASGI requests only; no socket or legacy application is opened.
    with TestClient(app, base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        project = app.state.store.create_project('Original retained graph')['id']
        artifact = app.state.store.add_artifact(project, assembly)
        alternate = app.state.store.add_artifact(project, assembly)
        parameters = getattr(request, 'param', {})
        jobs = [run(client, project, artifact['id'], operation, parameters if operation == 'managed.members' else {})
                for operation in FACETS]
        assert all(job['state'] == 'finished' for job in jobs), jobs
        documents = [saved(client, job) for job in jobs]
        # Keep the original binary graph mode observable before hiding the DLL.
        direct = run(client, project, artifact['id'], 'managed.graph')
        assert direct['state'] == 'finished', direct
        transfer = app.state.evidence.load(app.state.evidence.export(project))
        project = transfer['project']['id']
        artifact = app.state.store.artifact(project, transfer['id_map'][artifact['id']])
        alternate = app.state.store.artifact(project, transfer['id_map'][alternate['id']])
        jobs = [app.state.store.job(transfer['id_map'][job['id']]) for job in jobs]
        parked = assembly.with_suffix('.retained-original')
        assert not parked.exists()
        assembly.rename(parked)
        original_exists = Path.exists
        def exists(path):
            assert path.absolute() != assembly, 'Retained graph queried original availability'
            return original_exists(path)
        try:
            with monkeypatch.context() as patcher:
                patcher.setattr(Path, 'exists', exists)
                app.state.owned_alternate_artifact = alternate
                yield client, app, project, artifact, jobs, documents
        finally:
            parked.rename(assembly)


SUBSETS = [list(values) for count in range(1, 4) for values in itertools.combinations(range(3), count)]


@pytest.mark.parametrize('indices', SUBSETS)
def test_selected_facets_are_exact_and_cited_without_originals(retained, indices):
    client, app, project, artifact, jobs, documents = retained
    graph = run(client, project, artifact['id'], 'managed.graph_retained', {
        'source_job_ids': [jobs[index]['id'] for index in indices]})
    assert graph['state'] == 'finished', graph
    value = saved(client, graph)['result']
    assert graph['result']['original_source_check'] == 'not-performed-retained-input'
    assert value['root_artifact_sha256'] == artifact['sha256']
    sources = value['source_evidence']
    for index, key in enumerate(['managed_artifact', 'managed_members', 'managed_native_boundaries']):
        assert (sources[key + '_evidence_id'] is not None) == (index in indices)
        assert value['selection_scope'][key]['selected'] == (index in indices)
    assert value['summary']['methods'] == (len(documents[1]['result']['methods']) if 1 in indices else 0)
    assert value['summary']['fields'] == (1 if 1 in indices else 0)
    assert value['summary']['pinvoke_imports'] == (1 if 2 in indices else 0)
    carriers = {row['evidence_id']: row for row in value['retained_carriers']}
    assert set(value['evidence_links']) == set(carriers)
    for observation in value['source_observations']:
        raw = base64.b64decode(observation['document_base64'], validate=True)
        assert hashlib.sha256(raw).hexdigest() == observation['analysis_sha256']
        carrier = carriers[observation['carrier_evidence_id']]
        assert carrier['parameters']['analysis_sha256'] == observation['analysis_sha256']
        assert carrier['raw_result']['document_base64'] == observation['document_base64']
        assert carrier['confidence'] == 'derived' and carrier['authority'] == 'historical-reference'
    cited = [observation['evidence'] for node in value['graph']['nodes'] for observation in node['observations']]
    cited += [edge['evidence'] for edge in value['graph']['edges']]
    for evidence in cited:
        assert set(evidence['evidence_ids']) <= set(carriers)
    original = Path(graph['result']['analysis_file']).read_bytes()
    for _ in range(2):
        transfer = app.state.evidence.load(app.state.evidence.export(project))
        project = transfer['project']['id']
        artifact = app.state.store.artifact(project, transfer['id_map'][artifact['id']])
        imported_graph = app.state.store.job(transfer['id_map'][graph['id']])
        assert Path(imported_graph['result']['analysis_file']).read_bytes() == original
        jobs = [app.state.store.job(transfer['id_map'][job['id']]) for job in jobs]
        graph = run(client, project, artifact['id'], 'managed.graph_retained', {
            'source_job_ids': [jobs[index]['id'] for index in reversed(indices)]})
        assert graph['state'] == 'finished', graph
        repeated = saved(client, graph)['result']
        assert repeated['projection_id'] == value['projection_id']
        assert repeated['retained_carriers'] == value['retained_carriers']
        original = Path(graph['result']['analysis_file']).read_bytes()


@pytest.mark.parametrize('retained', [
    {'method_limit': 0}, {'method_offset': 1, 'method_limit': 1},
    {'type_names': ['Gauge']}, {'type_names': ['NoSuchOriginalType']}, {}], indirect=True)
def test_member_selection_scope_is_hash_bound_without_changing_helper_coverage(retained):
    client, _, project, artifact, jobs, documents = retained
    scope = documents[1]['observation_scope']
    graph = run(client, project, artifact['id'], 'managed.graph_retained', {'source_job_ids': [jobs[1]['id']]})
    assert graph['state'] == 'finished', graph
    value = saved(client, graph)['result']
    selected = value['selection_scope']['managed_members']
    assert selected['observation_scope'] == scope
    assert selected['scope_status'] == ('selected-window' if scope['method_limit'] is not None or
        scope['method_offset'] or scope['type_names'] is not None else 'all-methods-requested')
    assert value['summary']['methods'] == len(documents[1]['result']['methods'])
    assert value['source_evidence']['managed_native_boundaries_evidence_id'] is None
    if scope['method_limit'] == 0:
        assert value['summary']['methods'] == 0
        # Preserve the helper's finite statement; the envelope explains the empty window.
        assert value['coverage']['status'] == 'complete-within-inputs'
        assert selected['scope_status'] == 'selected-window'


def replace_document(app, project, job, document):
    path = Path(job['result']['analysis_file'])
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf8')
    result = {**job['result'], 'analysis_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    app.state.store.save_job(project, job['id'], job['state'], result)


def test_old_member_document_has_unknown_window_and_closure_does_not_select_facets(retained):
    client, app, project, artifact, jobs, documents = retained
    document = copy.deepcopy(documents[1]); document.pop('observation_scope')
    replace_document(app, project, jobs[1], document)
    job = app.state.store.job(jobs[1]['id'])
    result = {**job['result'], 'source_analyses': [
        {'job_id': jobs[2]['id']}, {'job_id': 'owned-missing-parent'}]}
    app.state.store.save_job(project, job['id'], 'imported', result)
    graph = run(client, project, artifact['id'], 'managed.graph_retained', {'source_job_ids': [job['id']]})
    assert graph['state'] == 'finished', graph
    value = saved(client, graph)['result']
    assert value['selection_scope']['managed_members']['scope_status'] == 'unknown'
    assert value['source_evidence']['managed_native_boundaries_evidence_id'] is None
    assert value['summary']['pinvoke_imports'] == 0
    assert value['retained_closure']['status'] == 'incomplete'
    assert value['retained_closure']['missing'][0]['job_id'] == 'owned-missing-parent'
    closure = next(row for row in value['source_observations'] if row['operation'] == FACETS[2])
    assert closure['carrier_evidence_id'] is None and not closure['occurrences'][0]['selected']


@pytest.mark.parametrize('invalid', ['mvid-conflict', 'internal-null-mvid', 'scope-sha', 'nested-sha',
    'schema', 'duplicate-facet', 'distinct-duplicate-facet', 'wrong-operation', 'foreign-project', 'outer-operation'])
def test_inconsistent_or_inadmissible_sources_fail_instead_of_empty_graph(retained, invalid):
    client, app, project, artifact, jobs, documents = retained
    inputs = [job['id'] for job in jobs]
    if invalid == 'duplicate-facet':
        inputs = [jobs[1]['id'], jobs[1]['id']]
    elif invalid == 'distinct-duplicate-facet':
        duplicate = app.state.store.save_job(project, 'owned-duplicate-members', 'imported', jobs[1]['result'])
        inputs = [jobs[1]['id'], duplicate['id']]
    elif invalid == 'foreign-project':
        transfer = app.state.evidence.load(app.state.evidence.export(project))
        inputs[1] = transfer['id_map'][jobs[1]['id']]
    elif invalid == 'wrong-operation':
        job = jobs[1]
        result = {**job['result'], 'operation': 'wasm.artifact'}
        app.state.store.save_job(project, job['id'], 'imported', result)
    else:
        document = copy.deepcopy(documents[1]); members = document['result']
        if invalid == 'mvid-conflict':
            members['module']['mvid'] = members['identity_scope']['requires_mvid'] = '11111111-1111-1111-1111-111111111111'
        elif invalid == 'internal-null-mvid':
            members['module']['mvid'] = None
        elif invalid == 'scope-sha':
            members['identity_scope']['requires_artifact_sha256'] = '0' * 64
        elif invalid == 'nested-sha':
            members['artifact']['sha256'] = '0' * 64
        elif invalid == 'outer-operation':
            document['operation'] = 'managed.artifact'
        else:
            del members['methods']
        replace_document(app, project, jobs[1], document)
    response = client.post('/api/agent/call', json={'tool': 'theseus_analysis_start', 'arguments': {
        'project_id': project, 'artifact_id': artifact['id'], 'operation': 'managed.graph_retained',
        'parameters': {'source_job_ids': inputs}}})
    if response.is_success:
        job = wait(client, response.json()['result'])
        assert job['state'] == 'failed', job
        assert job['result'].get('error') or job['result']['execution']['stderr']
    else:
        assert response.status_code == 400, response.text


@pytest.mark.parametrize('index', [0, 1, 2])
def test_worker_rechecks_all_document_hashes_after_binding(retained, index, tmp_path):
    from theseus.retained_evidence import bind_inputs
    client, app, project, artifact, jobs, _ = retained
    inputs = bind_inputs(app.state.store, project, [job['id'] for job in jobs])
    path = Path(inputs[index]['path']); original = path.read_bytes()
    request = tmp_path / 'request.json'; output = tmp_path / 'result.json'
    request.write_text(json.dumps({'operation': 'managed.graph_retained', 'path': inputs[0]['path'],
        'expected_input_sha256': inputs[0]['analysis_sha256'], 'source_artifact_sha256': artifact['sha256'],
        'source_inputs': inputs, 'parameters': {}}), encoding='utf8')
    try:
        path.write_bytes(original + b' ')
        configured = engine()
        result = subprocess.run([configured['node'], configured['entry'], str(request), str(output)], capture_output=True)
        assert result.returncode == 1 and not output.exists()
        assert b'hash changed' in result.stderr or b'receipt hash' in result.stderr
    finally:
        path.write_bytes(original)


@pytest.mark.parametrize('state', ['finished', 'failed', 'cancelled', 'interrupted', 'imported', 'running'])
def test_terminal_state_policy_is_enforced_on_valid_documents(retained, state):
    client, app, project, artifact, jobs, _ = retained
    app.state.store.save_job(project, jobs[0]['id'], state, jobs[0]['result'])
    response = client.post('/api/agent/call', json={'tool': 'theseus_analysis_start', 'arguments': {
        'project_id': project, 'artifact_id': artifact['id'], 'operation': 'managed.graph_retained',
        'parameters': {'source_job_ids': [jobs[0]['id']]}}})
    if state == 'running':
        assert response.status_code == 400
    else:
        assert response.is_success, response.text
        assert wait(client, response.json()['result'])['state'] == 'finished'


def test_same_content_different_occurrences_and_unknown_mvid_remain_historical(retained):
    client, app, project, artifact, jobs, documents = retained
    document = copy.deepcopy(documents[1])
    document['result']['artifact']['path'] = 'historical/nonexistent/Gauge.dll'
    document['result']['module']['mvid'] = None
    document['result']['identity_scope']['requires_mvid'] = None
    replace_document(app, project, jobs[1], document)
    member_job = app.state.store.job(jobs[1]['id'])
    result = {**member_job['result'], 'artifact_id': app.state.owned_alternate_artifact['id']}
    app.state.store.save_job(project, member_job['id'], 'imported', result)
    graph = run(client, project, artifact['id'], 'managed.graph_retained', {'source_job_ids': [job['id'] for job in jobs]})
    assert graph['state'] == 'finished', graph
    value = saved(client, graph)['result']
    assert value['coverage']['status'] == 'partial'
    nodes = {row['node_id']: row for row in value['graph']['nodes']}
    edge = next(row for row in value['graph']['edges'] if row['properties'].get('kind') == 'managed-pinvoke')
    # Unknown MVID cannot join even the same MethodDef token to a method.
    assert nodes[edge['source_node_id']]['kind'] == 'artifact'
    assert value['summary']['methods'] == 3 and value['summary']['pinvoke_imports'] == 1
