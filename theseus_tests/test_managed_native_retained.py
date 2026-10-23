"""Managed/native composition consumes authenticated history, not live files."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.native_analysis import ENGINE, engine
from test_binary_sessions import wait

pytestmark = pytest.mark.skipif(os.environ.get('THESEUS_TEST_GHIDRA') != '1', reason='Opt-in real retained native observation')
sha = lambda raw: hashlib.sha256(raw).hexdigest()


def start(client, project, artifact, operation, parameters=None, expected='finished'):
    response = client.post('/api/agent/call', json={'tool': 'theseus_analysis_start', 'arguments': {
        'project_id': project, 'artifact_id': artifact, 'operation': operation, 'parameters': parameters or {}}})
    assert response.is_success, response.text
    job = wait(client, response.json()['result'])
    assert job['state'] == expected, job
    return job


def document(client, job):
    response = client.get('/api/jobs/' + job['id'] + '/analysis.json')
    response.raise_for_status()
    return response.json()['result']


@pytest.fixture(scope='module')
def retained(tmp_path_factory):
    folder = tmp_path_factory.mktemp('owned-managed-native')
    source = folder / 'Original.cs'
    source.write_text('using System.Runtime.InteropServices; public static class Gauge {'
        '[DllImport("owned_probe.dll",EntryPoint="owned_probe")] public static extern int Exact(int value); '
        '[DllImport("owned_probe.dll",EntryPoint="wide_probe",CharSet=CharSet.Unicode,ExactSpelling=false)] public static extern int Wide(int value); '
        '[DllImport("owned_probe.dll",EntryPoint="wide_probe",CharSet=CharSet.Unicode,ExactSpelling=true)] public static extern int NoMangle(int value); '
        '[DllImport("wrong.dll",EntryPoint="owned_probe")] public static extern int Wrong(int value); '
        '[DllImport("owned_probe.dll",EntryPoint="missing_export")] public static extern int Missing(int value); }', encoding='utf8')
    assembly = folder / 'Gauge.dll'
    compiler = shutil.which('csc') or 'C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([compiler, '/nologo', '/target:library', '/optimize+', '/debug-', '/out:' + str(assembly), str(source)],
                   check=True, capture_output=True)
    (folder / 'Original.c').write_text('__declspec(dllexport) int owned_probe(int value) { return value+5; } '
        '__declspec(dllexport) int wide_probe(int value) { return value+3; }', encoding='utf8')
    setup = Path('C:/Program Files/Microsoft Visual Studio/18/Community/VC/Auxiliary/Build/vcvars64.bat')
    if not setup.is_file():
        pytest.skip('Requires the installed native fixture compiler')
    script = folder / 'compile.cmd'
    script.write_text('@echo off\ncall "' + str(setup) + '" >nul\nif errorlevel 1 exit /b 1\n'
        'cl /nologo /c /O2 /GS- Original.c /Fooriginal.obj\nif errorlevel 1 exit /b 1\n'
        'link /nologo /DLL /NOENTRY /NODEFAULTLIB /OUT:owned_probe.dll original.obj\nif errorlevel 1 exit /b 1\n'
        'link /nologo /DLL /NOENTRY /NODEFAULTLIB /OUT:other_module.dll original.obj\nexit /b %errorlevel%\n', encoding='utf8')
    compiled = subprocess.run(['cmd.exe', '/d', '/c', str(script)], cwd=folder, capture_output=True)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    paths = [assembly, folder / 'owned_probe.dll', folder / 'other_module.dll']
    hashes = {path: sha(path.read_bytes()) for path in paths}
    app = create_app(folder / 'data', port=64350)
    parked = []
    with TestClient(app, base_url='http://127.0.0.1:64350') as client:
        client.get('/')
        project = app.state.store.create_project('Original retained native verification')['id']
        artifacts = [app.state.store.add_artifact(project, path) for path in paths]
        managed = start(client, project, artifacts[0]['id'], 'managed.native_boundaries')
        native = []
        for index, artifact in enumerate(artifacts[1:]):
            opened = wait(client, client.post('/api/projects/' + project + '/artifacts/' + artifact['id'] + '/binary-sessions', json={}).json())
            assert opened['state'] == 'finished', opened
            try:
                for _ in range(2 if index == 0 else 1):
                    job = wait(client, client.post('/api/binary-sessions/' + opened['id'] + '/call', json={
                        'operation': 'analyze_function', 'parameters': {'procedure': 'owned_probe'}}).json())
                    assert job['state'] == 'finished', job
                    native.append(job)
                if index == 1:
                    job = wait(client, client.post('/api/binary-sessions/' + opened['id'] + '/call', json={
                        'operation': 'analyze_function', 'parameters': {'procedure': 'wide_probe'}}).json())
                    assert job['state'] == 'finished', job
                    native.append(job)
            finally:
                closed = wait(client, client.post('/api/binary-sessions/' + opened['id'] + '/close', json={}).json())
                assert closed['state'] == 'finished', closed
                assert app.state.store.job(opened['id'])['result']['session_state'] == 'closed'
        control = start(client, project, artifacts[0]['id'], 'managed.verify_native', {
            'source_job_id': managed['id'], 'native_job_ids': [native[0]['id']]})
        assert document(client, control)['verification']['summary']['verified'] == 1
        transfer = app.state.evidence.load(app.state.evidence.export(project))
        project = transfer['project']['id']
        artifacts = [app.state.store.artifact(project, transfer['id_map'][row['id']]) for row in artifacts]
        managed = app.state.store.job(transfer['id_map'][managed['id']])
        native = [app.state.store.job(transfer['id_map'][row['id']]) for row in native]
        try:
            for path in paths:
                other = path.with_suffix('.retained-original'); assert not other.exists()
                path.rename(other); parked.append((path, other))
            original_exists = Path.exists
            def retained_exists(path):
                assert path.absolute() not in hashes, 'Retained verification queried original-path availability'
                return original_exists(path)
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(Path, 'exists', retained_exists)
                yield client, app, project, artifacts, managed, native
        finally:
            for path, other in parked:
                other.rename(path)
            assert all(sha(path.read_bytes()) == hashes[path] for path in paths)


def test_imported_jobs_recompose_after_two_transfers_without_originals(retained):
    client, app, project, artifacts, managed, native = retained
    previous = None
    for _ in range(3):
        job = start(client, project, artifacts[0]['id'], 'managed.verify_native', {
            'source_job_id': managed['id'], 'native_job_ids': [native[0]['id'], native[1]['id']]})
        result = document(client, job)
        assert result['verification']['summary']['verified'] == 1
        assert result['verification']['native_observations']['total'] == 1
        assert result['source_observations'][1]['source_job_ids'] == [native[0]['id'], native[1]['id']]
        assert job['result']['original_source_check'] == 'not-performed-retained-input'
        for observation in result['source_observations']:
            raw_document = base64.b64decode(observation['document_base64'], validate=True)
            assert sha(raw_document) == observation['analysis_sha256']
            original = json.loads(raw_document)
            assert observation['evidence']['normalized_result'] == (
                original['result']['value'] if original['operation'] == 'binary.analyze_function' else original['result'])
        if previous is not None:
            assert result['verification']['verification_id'] == previous['verification']['verification_id']
        raw = Path(job['result']['analysis_file']).read_bytes()
        transfer = app.state.evidence.load(app.state.evidence.export(project))
        assert Path(app.state.store.job(transfer['id_map'][job['id']])['result']['analysis_file']).read_bytes() == raw
        project = transfer['project']['id']
        artifacts = [app.state.store.artifact(project, transfer['id_map'][row['id']]) for row in artifacts]
        managed = app.state.store.job(transfer['id_map'][managed['id']])
        native = [app.state.store.job(transfer['id_map'][row['id']]) for row in native]
        previous = result


@pytest.fixture(scope='module')
def export_observation(tmp_path_factory):
    folder = tmp_path_factory.mktemp('owned-native-exports')
    go = os.environ.get('THESEUS_TEST_GO') or shutil.which('go')
    zig = os.environ.get('THESEUS_TEST_ZIG') or shutil.which('zig')
    llvm = os.environ.get('THESEUS_TEST_LLVM_OBJDUMP') or shutil.which('llvm-objdump')
    if not all((go, zig, llvm)):
        pytest.skip('Requires configured Go, Zig and LLVM export-trie observers')
    source = folder / 'Original.c'
    source.write_text('static __attribute__((noinline)) int local_only(int value) { return value+11; }\n'
        'int owned_probe(int value) { return local_only(value)+5; }\nint wide_probeW(int value) { return value+7; }', encoding='utf8')
    binary = folder / 'libowned_probe.dylib'
    env = {**os.environ, 'ZIG_GLOBAL_CACHE_DIR': str(folder / 'zig-global'), 'ZIG_LOCAL_CACHE_DIR': str(folder / 'zig-local'),
           'GOCACHE': str(folder / 'go-cache'), 'GOPATH': str(folder / 'go-path'), 'GOPROXY': 'off', 'GOTOOLCHAIN': 'local', 'GO111MODULE': 'off'}
    subprocess.run([zig, 'cc', '-target', 'x86_64-macos', '-dynamiclib', '-O1', '-o', str(binary), str(source),
                    '-Wl,-install_name,@rpath/libowned_probe.dylib'], env=env, check=True, capture_output=True)
    observer_source = folder / 'observer.go'
    observer_source.write_text('package main\nimport("debug/macho";"encoding/json";"os")\n'
        'func main(){f,e:=macho.Open(os.Args[1]);if e!=nil{panic(e)};defer f.Close();if f.Symtab==nil{panic("No symtab")};'
        'json.NewEncoder(os.Stdout).Encode(map[string]any{"magic":f.Magic,"cpu":f.Cpu,"subcpu":f.SubCpu,"type":f.Type,"flags":f.Flags,"symbols":f.Symtab.Syms})}', encoding='utf8')
    observer = folder / 'observer.exe'
    subprocess.run([go, 'build', '-o', str(observer), str(observer_source)], env=env, check=True, capture_output=True)
    raw = subprocess.run([str(observer), str(binary)], check=True, capture_output=True).stdout
    symbols = json.loads(raw)
    assert symbols['magic'] == 0xfeedfacf and symbols['cpu'] == 0x1000007 and symbols['type'] == 6
    trie = subprocess.run([llvm, '--macho', '--exports-trie', str(binary)], check=True, capture_output=True).stdout
    parsed = {name: {'address': address, 'flags': flags or ''} for address, name, flags in re.findall(
        r'^(0x[0-9A-Fa-f]+)\s+(\S+?)(?:\s+\[([^\]]+)\])?\s*$', trie.decode('utf8'), re.M)}
    external = {row['Name']: row for row in symbols['symbols'] if not row['Type'] & 0xe0 and row['Type'] & 1 and
                not row['Type'] & 0x10 and row['Type'] & 0xe == 0xe and row['Sect']}
    assert set(parsed) == set(external) and {'_owned_probe', '_wide_probeW'} <= set(parsed)
    assert any(row['Name'] == '_local_only' for row in symbols['symbols']) and '_local_only' not in parsed
    for name, row in external.items():
        assert row['Value'] == int(parsed[name]['address'], 16)
        assert bool(row['Desc'] & 0x80) == ('weak_def' in parsed[name]['flags'])
    oracle = {'go': symbols, 'trie': trie.decode('utf8'), 'go_stdout_base64': base64.b64encode(raw).decode(),
        'llvm_stdout_base64': base64.b64encode(trie).decode(), 'binary_sha256': sha(binary.read_bytes()),
        'source_sha256': sha(source.read_bytes()), 'observer_source_sha256': sha(observer_source.read_bytes()),
        'observer_executable_sha256': sha(observer.read_bytes()), 'llvm_executable_sha256': sha(Path(llvm).read_bytes()),
        'observer_command': [str(observer), str(binary)], 'llvm_command': [llvm, '--macho', '--exports-trie', str(binary)],
        'limitations': ['Original reader version1; symbol and export outputs retained; target was not executed.']}
    (folder / 'oracle.json').write_text(json.dumps(oracle, indent=2), encoding='utf8')
    container_request = folder / 'container-request.json'; container_output = folder / 'container.json'
    container_request.write_text(json.dumps({'operation': 'apple.macho', 'path': str(binary), 'parameters': {}}), encoding='utf8')
    subprocess.run([engine()['node'], engine()['entry'], str(container_request), str(container_output)], check=True, capture_output=True)
    container = json.loads(container_output.read_bytes())['result']
    absent = lambda: {'items': [], 'total': None, 'exhaustive': False, 'limitations': ['Facet not observed by this original export reader.']}
    result = {'format': 'mach-o', 'selected_architecture': {'name': 'x86_64', 'container_file_offset': 0},
        'endian': 'little', 'word_size': 64, 'file_type': 'dylib', 'flags': [hex(symbols['flags'])], 'uuid': None,
        **{name: absent() for name in ['entrypoints', 'architectures', 'build_metadata', 'load_commands', 'dependencies', 'imports', 'segments']},
        'exports': {'items': [{'name': name, 'address': row['address'].lower(), 'weak': 'weak_def' in row['flags'],
            'reexport': False, 'source': 'LC_DYLD_EXPORTS_TRIE corroborated by Go LC_SYMTAB'} for name, row in parsed.items()],
            'total': len(parsed), 'exhaustive': True, 'limitations': ['Only this selected thin original dylib was observed.']},
        'provenance': [], 'limitations': ['Only exports and selected header fields were observed; no target code was executed.']}
    builder = folder / 'evidence.mjs'
    builder.write_text("import{readFile,writeFile}from'node:fs/promises';import{createEvidence}from" + json.dumps((ENGINE / 'dist/src/domain/evidence.js').as_uri()) + ";"
        "const x=JSON.parse(await readFile(process.argv[2],'utf8'));const e=createEvidence(x.target??undefined,"
        "{id:'owned-export-observer',name:'Original retained export observation',version:'1'},"
        "{operation:x.operation,parameters:x.parameters,result:x.result,rawResult:x.raw_result,confidence:'observed',authority:'historical-reference',evidenceLinks:x.links??[]});"
        "await writeFile(process.argv[3],JSON.stringify(e));", encoding='utf8')
    def evidence(value=None, target=True, operation='inspect_macho', links=None, parameters=None):
        key = uuid.uuid4().hex
        request = folder / (key + '.json'); output = folder / (key + '-evidence.json')
        request.write_text(json.dumps({'target': {'path': str(binary), 'sha256': sha_original, 'format': 'mach-o'} if target else None,
            'operation': operation, 'result': result if value is None else value, 'links': links or [],
            'parameters': parameters or {}, 'raw_result': oracle}), encoding='utf8')
        subprocess.run([engine()['node'], str(builder), str(request), str(output)], check=True, capture_output=True)
        return json.loads(output.read_bytes())
    sha_original = sha(binary.read_bytes())
    parked = binary.with_suffix('.retained-original'); binary.rename(parked)
    try:
        yield result, evidence, container
    finally:
        parked.rename(binary)
        assert sha(binary.read_bytes()) == sha_original


def test_supplied_exports_preserve_matching_states_and_source_value(retained, export_observation):
    client, _, project, artifacts, managed, _ = retained
    _, evidence, _ = export_observation
    source = evidence(links=['ev_' + '0' * 64])
    job = start(client, project, artifacts[0]['id'], 'managed.verify_native', {
        'source_job_id': managed['id'], 'query': {'native_observations': [source]}})
    result = document(client, job)
    imports = {row['managed']['member_name']: row for row in result['verification']['pinvoke_imports']}
    assert {name: row['status'] for name, row in imports.items()} == {
        'Exact': 'verified', 'Wide': 'inferred', 'NoMangle': 'unresolved', 'Wrong': 'contradicted', 'Missing': 'unresolved'}
    assert imports['Exact']['basis'] == 'exact-export-name' and imports['Wide']['basis'] == 'decorated-name-candidate'
    assert imports['NoMangle']['basis'] == 'no-native-candidate'
    recorded = result['source_observations'][1]
    assert recorded['evidence'] == source and recorded['origin'] == 'caller-supplied-retained-evidence'
    assert json.loads(base64.b64decode(recorded['submitted_value_json_base64'])) == source
    assert sha(base64.b64decode(recorded['submitted_value_json_base64'])) == recorded['submitted_value_sha256']
    assert result['retained_closure']['unresolved_evidence_links'] == ['ev_' + '0' * 64]


@pytest.mark.parametrize('variant', ['same-id', 'same-id-labels', 'mixed', 'mixed-labels'])
def test_duplicate_ids_cannot_choose_module_labels_silently(retained, export_observation, variant):
    client, _, project, artifacts, managed, native = retained
    _, evidence, _ = export_observation
    parameters = {'source_job_id': managed['id']}
    if variant.startswith('mixed'):
        parameters['native_job_ids'] = [native[0]['id']]
        baseline = start(client, project, artifacts[0]['id'], 'managed.verify_native', parameters)
        first = document(client, baseline)['source_observations'][1]['evidence']
        values = [copy.deepcopy(first)]
    else:
        first = evidence(); values = [first, copy.deepcopy(first)]
    if variant.endswith('labels'):
        values[-1]['subject']['name'] = 'wrong.dll'
        values[-1]['subject']['local_path'] = 'historical/wrong.dll'
    parameters['query'] = {'native_observations': values}
    job = start(client, project, artifacts[0]['id'], 'managed.verify_native', parameters, expected='failed')
    assert 'Duplicate native Evidence ID' in job['result']['execution']['stderr']


@pytest.mark.parametrize('kind', ['unknown-module', 'empty-exports', 'unsupported'])
def test_unknown_empty_and_unsupported_inputs_remain_distinct(retained, export_observation, kind):
    client, _, project, artifacts, managed, _ = retained
    result, evidence, _ = export_observation
    if kind == 'unknown-module':
        source = evidence(target=False)
    elif kind == 'empty-exports':
        result = copy.deepcopy(result)
        result['exports'].update(items=[], total=None, exhaustive=False, limitations=['Explicit partial empty observation.'])
        source = evidence(result)
    else:
        source = evidence(operation='owned-unsupported-observation')
    job = start(client, project, artifacts[0]['id'], 'managed.verify_native', {
        'source_job_id': managed['id'], 'query': {'native_observations': [source]}})
    value = document(client, job)
    exact = next(row for row in value['verification']['pinvoke_imports'] if row['managed']['member_name'] == 'Exact')
    assert exact['status'] == 'unresolved'
    assert exact['basis'] == {'unknown-module': 'module-identity-unknown',
        'empty-exports': 'no-native-candidate', 'unsupported': 'unsupported-native-evidence'}[kind]
    if kind == 'empty-exports':
        assert value['input_scope'][1]['exports_coverage'] == {
            'total': None, 'exhaustive': False, 'limitations': ['Explicit partial empty observation.']}
        assert value['input_scope'][1]['exports_coverage']['exhaustive'] is False
        assert value['input_scope'][1]['exports_coverage']['total'] is None
        assert value['verification']['coverage']['status'] == 'complete-within-inputs'


@pytest.mark.parametrize('kind', ['bad-id', 'bad-digest', 'container-payload'])
def test_invalid_supported_evidence_is_not_an_empty_inventory(retained, export_observation, kind):
    client, _, project, artifacts, managed, _ = retained
    _, evidence, container = export_observation
    source = evidence(container) if kind == 'container-payload' else evidence()
    if kind == 'bad-id':
        source['evidence_id'] = 'ev_' + '0' * 64
    elif kind == 'bad-digest':
        source['subject']['digest']['sha256'] = '0' * 64
    job = start(client, project, artifacts[0]['id'], 'managed.verify_native', {
        'source_job_id': managed['id'], 'query': {'native_observations': [source]}}, expected='failed')
    assert job['result']['execution']['stderr']


def native_evidence(client, project, artifact, managed, job):
    comparison = start(client, project, artifact, 'managed.verify_native', {
        'source_job_id': managed['id'], 'native_job_ids': [job['id']]})
    return document(client, comparison)['source_observations'][1]['evidence']


@pytest.mark.parametrize('kind', ['exact-correct-and-wrong', 'decorated-correct-and-wrong-exact',
    'wrong-and-unknown', 'two-compatible', 'two-compatible-reversed'])
def test_combined_candidates_preserve_priority_order_and_conflicts(retained, export_observation, kind):
    client, _, project, artifacts, managed, native = retained
    _, evidence, _ = export_observation
    exact = evidence()
    if kind == 'exact-correct-and-wrong':
        values = [native_evidence(client, project, artifacts[0]['id'], managed, native[2]), exact]
        method, status, matched = 'Exact', 'verified', exact['evidence_id']
    elif kind == 'decorated-correct-and-wrong-exact':
        values = [native_evidence(client, project, artifacts[0]['id'], managed, native[3]), exact]
        method, status, matched = 'Wide', 'inferred', exact['evidence_id']
    elif kind == 'wrong-and-unknown':
        unknown = evidence(target=False)
        values = [native_evidence(client, project, artifacts[0]['id'], managed, native[2]), unknown]
        method, status, matched = 'Exact', 'unresolved', unknown['evidence_id']
    else:
        values = [native_evidence(client, project, artifacts[0]['id'], managed, native[0]), exact]
        if kind.endswith('reversed'):
            values.reverse()
        method, status, matched = 'Exact', 'verified', values[0]['evidence_id']
    job = start(client, project, artifacts[0]['id'], 'managed.verify_native', {
        'source_job_id': managed['id'], 'query': {'native_observations': values}})
    result = document(client, job)
    row = next(row for row in result['verification']['pinvoke_imports'] if row['managed']['member_name'] == method)
    assert row['status'] == status and row['matched_native']['evidence_id'] == matched
    assert len(row['candidates']) == 2 and {value['evidence_id'] for value in row['candidates']} == {value['evidence_id'] for value in values}
    assert [value['evidence_id'] for value in result['input_order']] == [value['evidence_id'] for value in values]
    assert [value['evidence'] for value in result['source_observations'][1:]] == values


@pytest.mark.parametrize('which', ['managed', 'native-first', 'native-second'])
def test_each_retained_document_is_reauthenticated(retained, which):
    client, _, project, artifacts, managed, native = retained
    source = managed if which == 'managed' else native[0 if which == 'native-first' else 2]
    path = Path(source['result']['analysis_file']); raw = path.read_bytes()
    try:
        path.write_bytes(raw + b' ')
        job = start(client, project, artifacts[0]['id'], 'managed.verify_native', {
            'source_job_id': managed['id'], 'native_job_ids': [native[0]['id'], native[2]['id']]}, expected='failed')
        assert 'receipt hash' in job['result']['execution']['stderr']
    finally:
        path.write_bytes(raw)


def test_failed_request_preserves_opaque_supplied_values_during_import(tmp_path):
    """Even invalid historical request values are data, not typed project links."""
    app = create_app(tmp_path / 'data', port=64350)
    with TestClient(app, base_url='http://127.0.0.1:64350') as client:
        client.get('/')
        project = app.state.store.create_project('Opaque historical request')['id']
        path = tmp_path / 'Original.txt'; path.write_text('Owned import fixture', encoding='utf8')
        artifact = app.state.store.add_artifact(project, path)
        job_id = uuid.uuid4().hex
        supplied = {'evidence_id': 'deliberately-invalid-historical-input',
            'subject': {'name': 'declared-module', 'local_path': 'historical/path'},
            'parameters': {'job_id': job_id, 'session_id': job_id, 'artifact_id': artifact['id']},
            'raw_result': {'job_id': job_id}, 'normalized_result': {'artifact_id': artifact['id']}}
        app.state.store.save_job(project, job_id, 'failed', {
            'kind': 'native_analysis', 'operation': 'managed.verify_native', 'artifact_id': artifact['id'],
            'error': 'Synthetic failed request; no native observation is claimed',
            'parameters': {'source_job_id': 'literal-original-request', 'query': {'native_observations': [supplied]}}})
        transfer = app.state.evidence.load(app.state.evidence.export(project))
        retained = app.state.store.job(transfer['id_map'][job_id])['result']
        assert retained['artifact_id'] == transfer['id_map'][artifact['id']]
        assert retained['parameters']['query']['native_observations'] == [supplied]


def test_valid_supplied_values_and_literal_ids_survive_transfer_and_recomposition(retained, export_observation):
    client, app, project, artifacts, managed, native = retained
    _, evidence, _ = export_observation
    supplied = evidence(parameters={'job_id': managed['id'], 'artifact_id': artifacts[0]['id'],
        'session_id': native[0]['result']['session_id']})
    previous = None
    for _ in range(3):
        job = start(client, project, artifacts[0]['id'], 'managed.verify_native', {
            'source_job_id': managed['id'], 'query': {'native_observations': [supplied]}})
        result = document(client, job)
        assert result['source_observations'][1]['evidence'] == supplied
        assert result['source_observations'][1]['submitted_value_sha256'] == sha(base64.b64decode(
            result['source_observations'][1]['submitted_value_json_base64'], validate=True))
        if previous is not None:
            assert result['verification'] == previous['verification']
        raw = Path(job['result']['analysis_file']).read_bytes()
        transfer = app.state.evidence.load(app.state.evidence.export(project))
        imported_job = app.state.store.job(transfer['id_map'][job['id']])
        assert imported_job['result']['parameters']['query']['native_observations'] == [supplied]
        assert Path(imported_job['result']['analysis_file']).read_bytes() == raw
        project = transfer['project']['id']
        artifacts = [app.state.store.artifact(project, transfer['id_map'][row['id']]) for row in artifacts]
        managed = app.state.store.job(transfer['id_map'][managed['id']])
        previous = result


@pytest.mark.parametrize('invalid', ['managed-failed', 'managed-cancelled', 'native-failed', 'native-cancelled',
    'foreign-managed', 'foreign-native', 'native-operation', 'profile-hash', 'profile-project', 'profile-artifact'])
def test_project_state_operation_and_provider_bindings_remain_required(retained, invalid):
    client, app, project, artifacts, managed, native = retained
    parameters = {'source_job_id': managed['id'], 'native_job_ids': [native[0]['id']]}
    restore = []
    try:
        if invalid.startswith('foreign-') or invalid == 'profile-project':
            transfer = app.state.evidence.load(app.state.evidence.export(project))
            if invalid == 'foreign-managed':
                parameters['source_job_id'] = transfer['id_map'][managed['id']]
            elif invalid == 'foreign-native':
                parameters['native_job_ids'] = [transfer['id_map'][native[0]['id']]]
            else:
                row = app.state.store.job(native[0]['id']); restore.append(copy.deepcopy(row))
                result = {**row['result'], 'session_id': transfer['id_map'][row['result']['session_id']]}
                app.state.store.save_job(project, row['id'], row['state'], result)
        elif invalid.startswith('profile-'):
            row = app.state.store.job(native[0]['result']['session_id']); restore.append(copy.deepcopy(row))
            result = copy.deepcopy(row['result'])
            if invalid == 'profile-hash':
                result['profile']['options']['owned_inconsistent_option'] = True
            else:
                result['artifact_sha256'] = '0' * 64
            app.state.store.save_job(project, row['id'], row['state'], result)
        else:
            row = app.state.store.job(managed['id'] if invalid.startswith('managed-') else native[0]['id'])
            restore.append(copy.deepcopy(row)); result = copy.deepcopy(row['result'])
            state = row['state']
            if invalid == 'native-operation':
                result['operation'] = 'managed.members'
            else:
                state = invalid.rsplit('-', 1)[1]
            app.state.store.save_job(project, row['id'], state, result)
        before = set((app.state.store.directory / 'analyses').iterdir())
        response = client.post('/api/agent/call', json={'tool': 'theseus_analysis_start', 'arguments': {
            'project_id': project, 'artifact_id': artifacts[0]['id'], 'operation': 'managed.verify_native', 'parameters': parameters}})
        assert response.status_code == 400, response.text
        assert set((app.state.store.directory / 'analyses').iterdir()) == before
    finally:
        for row in restore:
            app.state.store.save_job(row['project_id'], row['id'], row['state'], row['result'])


def test_unavailable_historical_profile_stays_unknown_without_reopening(retained):
    client, app, project, artifacts, managed, native = retained
    row = app.state.store.job(native[0]['id'])
    try:
        result = {**row['result'], 'session_id': 'owned-unavailable-historical-session'}
        app.state.store.save_job(project, row['id'], row['state'], result)
        job = start(client, project, artifacts[0]['id'], 'managed.verify_native', {
            'source_job_id': managed['id'], 'native_job_ids': [row['id']]})
        result = document(client, job)
        assert result['verification']['summary']['verified'] == 1
        context = result['source_observations'][1]['historical_context']
        assert context['provider_profile'] is None and context['profile_sha256'] is None
        assert context['recorded_provider_version'] is None
    finally:
        app.state.store.save_job(project, row['id'], row['state'], row['result'])
