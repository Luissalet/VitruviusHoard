import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

import pytest

from theseus.native_inventory import compose

SESSION = {'id': 'owned-session', 'result': {'artifact_sha256': 'a' * 64,
    'revision': 7, 'profile_sha256': 'b' * 64, 'info': {'target': {'default_address_space': 'ram'}}}}


class Provider:
    def __init__(self, names=(), refs=(), summary=None, error=None):
        self.names = list(names)
        self.refs = list(refs)
        self.summary = summary or {'document': 'original.elf', 'procedure_count': 4,
            'string_count': 26, 'segments': [{'name': '.text', 'image_base': '0x1000000'},
                                          {'name': '.data', 'image_base': '0x01000000'}]}
        self.error = error
        self.calls = []

    def request(self, method, arguments):
        self.calls.append((method, copy.deepcopy(arguments)))
        if self.error and method == self.error[0]:
            return {'ok': False, 'error': copy.deepcopy(self.error[1])}
        values = {'current_document': 'original.elf', 'list_names': self.names,
                  'xrefs': self.refs, 'read_binary_inventory_summary': self.summary}
        return {'id': len(self.calls), 'ok': True, 'result': copy.deepcopy(values[method])}


def run(provider, name='target', operation='resolve_name_references', session=SESSION):
    return compose(provider, session, operation, {'name': name} if operation == 'resolve_name_references' else {}, lambda: None)


def test_exact_names_preserve_unicode_case_namespace_and_matching_aliases():
    provider = Provider(names=[{'value': 'target_suffix', 'address': '0x10'},
        {'value': 'Target', 'address': '0x20'}, {'value': 'ns::café😀', 'address': '0x30'},
        {'value': 'ns::café😀', 'address': '0x30', 'symbol': {'primary': False}}], refs=['0x40', '0x48'])
    result = run(provider, 'ns::café😀')['result']
    assert result['status'] == 'resolved' and result['address'] == '0x30'
    assert result['references'] == ['0x40', '0x48']
    assert result['matches'] == provider.names[2:] and result['addresses'] == ['0x30']
    assert provider.calls == [('current_document', {}), ('list_names', {'document': 'original.elf', 'address': None}),
                              ('xrefs', {'document': 'original.elf', 'address': '0x30'})]
    assert result['observations'][1]['response']['result'] == provider.names
    assert result['binding']['analysis_revision'] == 7


def test_missing_exact_name_does_not_fall_back_to_prefix_case_or_namespace():
    provider = Provider(names=[{'value': 'target_suffix', 'address': '0x10'},
        {'value': 'Target', 'address': '0x20'}, {'value': 'ns::target', 'address': '0x30'}])
    result = run(provider)['result']
    assert result['status'] == 'unresolved' and result['reason'] == 'name_not_found'
    assert result['matches'] == result['references'] == []
    assert [r[0] for r in provider.calls] == ['current_document', 'list_names']


def test_distinct_addresses_are_ambiguous_without_requesting_any_xrefs():
    provider = Provider(names=[{'value': 'target', 'address': '0x10'},
        {'value': 'target', 'address': '0x10'}, {'value': 'target', 'address': '0x20'}])
    result = run(provider)['result']
    assert result['reason'] == 'ambiguous_name' and result['addresses'] == ['0x10', '0x20']
    assert [r[0] for r in provider.calls] == ['current_document', 'list_names']


def test_resolved_name_with_zero_references_remains_resolved():
    result = run(Provider(names=[{'value': 'target', 'address': '0x10'}]))['result']
    assert result['status'] == 'resolved' and result['references'] == [] and result['reason'] is None


def test_equivalent_numeric_forms_are_one_address_and_keep_all_observations():
    provider = Provider(names=[{'value': 'target', 'address': '0x0010'},
        {'value': 'target', 'address': 'ram:0X10'}, {'value': 'target', 'address': 'r%61m:0x10'},
        {'value': 'target', 'address': '0x10'}])
    result = run(provider)['result']
    assert result['status'] == 'resolved' and result['addresses'] == ['0x0010']
    assert result['matches'] == provider.names
    assert provider.calls[-1] == ('xrefs', {'document': 'original.elf', 'address': '0x0010'})


@pytest.mark.parametrize('address', ['not-an-address', '0xzz', 'bad%ff:0x10',
    'bad%GG:0x10', 'bad%:0x10', 'a:b:0x10', 'space name:0x10'])
def test_invalid_native_address_is_not_a_resolved_symbol(address):
    provider = Provider(names=[{'value': 'target', 'address': address}])
    reply = run(provider)
    assert reply['ok'] is False and reply['error']['code'] == 'invalid_observation'
    assert reply['observations'][-1]['response']['result'] == provider.names
    assert [r[0] for r in provider.calls] == ['current_document', 'list_names']


@pytest.mark.parametrize('address', ['not-an-address', 'bad%GG:0x10', 'bad%:0x10',
    'a:b:0x10', 'space name:0x10'])
def test_invalid_reference_observation_is_retained_as_error(address):
    provider = Provider(names=[{'value': 'target', 'address': '0x10'}], refs=[address])
    reply = run(provider)
    assert reply['ok'] is False and reply['error']['code'] == 'invalid_observation'
    assert reply['observations'][-1]['response']['result'] == [address]


@pytest.mark.parametrize('method', ['current_document', 'list_names', 'xrefs'])
def test_provider_error_is_retained_without_inventing_name_absence(method):
    error = {'code': 'unsupported_capability', 'message': 'Original provider diagnostic'}
    provider = Provider(names=[{'value': 'target', 'address': '0x10'}], error=(method, error))
    reply = run(provider)
    assert reply['ok'] is False and reply['error'] == error
    assert reply['observations'][-1]['response']['error'] == error
    assert 'result' not in reply


@pytest.mark.parametrize('names', [None, {}, [{'value': 'target'}], [{'value': 1, 'address': '0x10'}]])
def test_incomplete_inventory_is_not_name_not_found(names):
    provider = Provider(); provider.names = names
    reply = run(provider)
    assert reply['ok'] is False and reply['error']['code'] == 'invalid_observation'
    assert reply['observations'][-1]['response']['result'] == names
    assert [r[0] for r in provider.calls] == ['current_document', 'list_names']


def test_overview_keeps_raw_inventory_and_canonical_common_base():
    provider = Provider()
    value = run(provider, operation='binary_overview')['result']
    assert value['segment_count'] == 2 and value['image_base'] == '0x1000000'
    assert value['image_base_address_space'] == 'ram' and value['image_base_status'] == 'observed'
    assert value['segments'] == provider.summary['segments']
    assert value['procedure_count'] == 4 and value['string_count'] == 26
    assert value['observations'][0]['response']['result'] == provider.summary
    assert provider.calls == [('read_binary_inventory_summary', {})]


@pytest.mark.parametrize('segments,reason', [([], 'no_segments'),
    ([{'start': '0x1000'}], 'incomplete_base_observation'),
    ([{'image_base': '0x1000'}, {'image_base': '0x2000'}], 'conflicting_base_observations'),
    ([{'image_base': 'left:0x1000'}, {'image_base': 'right:0x1000'}], 'conflicting_base_observations')])
def test_unknown_base_never_uses_first_segment_or_lowest_address(segments, reason):
    provider = Provider(summary={'segments': segments, 'procedure_count': 0, 'string_count': 0})
    value = run(provider, operation='binary_overview')['result']
    assert value['segment_count'] == len(segments) and value['segments'] == segments
    assert value['image_base'] is None and value['image_base_address_space'] is None
    assert value['image_base_status'] == 'unknown' and value['image_base_reason'] == reason


def test_unqualified_base_without_observed_default_space_is_unknown():
    session = copy.deepcopy(SESSION); session['result'].pop('info')
    value = run(Provider(), operation='binary_overview', session=session)['result']
    assert value['image_base'] is None and value['image_base_reason'] == 'incomplete_base_observation'


def test_explicit_space_is_preserved_independently_of_segment_names():
    provider = Provider(summary={'segments': [{'name': 'data', 'image_base': 'unicode%20%C3%B1:0x0010'},
                                            {'name': 'code', 'image_base': 'unicode%20%C3%B1:0x10'}]})
    value = run(provider, operation='binary_overview')['result']
    assert value['image_base'] == '0x10' and value['image_base_address_space'] == 'unicode ñ'


@pytest.mark.parametrize('address', ['bad%GG:0x10', 'bad%:0x10', 'a:b:0x10', 'space name:0x10'])
def test_invalid_base_space_is_a_retained_error(address):
    summary = {'segments': [{'image_base': address}]}
    reply = run(Provider(summary=summary), operation='binary_overview')
    assert reply['ok'] is False and reply['error']['code'] == 'invalid_observation'
    assert reply['observations'][0]['response']['result'] == summary


def test_admitted_query_binds_revision_observed_after_prior_annotation(tmp_path):
    from theseus.binary_sessions import BinarySessions
    from theseus.store import Store
    store = Store(tmp_path / 'profile'); project = store.create_project('Owned revision control')['id']
    pending = []
    manager = SimpleNamespace(store=store, pool=SimpleNamespace(submit=lambda f, *args: pending.append((f, args))),
        lock=threading.Lock(), processes={}, cancelled=set())
    sessions = BinarySessions(manager)
    class MutableProvider(Provider):
        lock = threading.RLock()
        process = SimpleNamespace(poll=lambda: None)
        def request(self, method, arguments):
            if method == 'set_address_name':
                self.names = [{'value': arguments['name'], 'address': '0x10'}]
                return {'ok': True, 'result': {'name': arguments['name']}}
            return super().request(method, arguments)
    provider = MutableProvider(names=[{'value': 'old', 'address': '0x10'}])
    sessions.runtimes[SESSION['id']] = provider
    result = copy.deepcopy(SESSION['result'])
    result.update(kind='binary_session', session_state='open', artifact_id='original-artifact', artifact_name='original.elf')
    store.save_job(project, SESSION['id'], 'finished', result)
    mutation = sessions.call(SESSION['id'], 'set_address_name', {'address': '0x10', 'name': 'changed'})
    query = sessions.call(SESSION['id'], 'resolve_name_references', {'name': 'changed'})
    assert len(pending) == 2
    for function, arguments in pending:
        function(*arguments)
    assert store.job(mutation['id'])['state'] == 'finished'
    job = store.job(query['id']); assert job['state'] == 'finished', job
    document = json.loads(Path(job['result']['analysis_file']).read_bytes())['result']
    assert document['status'] == 'resolved' and document['matches'][0]['value'] == 'changed'
    assert document['binding']['analysis_revision'] == job['result']['analysis_revision'] == 8


@pytest.mark.parametrize('parameters', [{}, {'name': ''}, {'name': None}, {'name': True},
    {'name': 'target', 'document': ''}, {'name': 'target', 'extra': 1}])
def test_invalid_selector_has_no_provider_effect(parameters):
    provider = Provider()
    with pytest.raises(ValueError): compose(provider, SESSION, 'resolve_name_references', parameters, lambda: None)
    assert provider.calls == []


def test_cancelled_composition_does_not_repeat_or_advance_observations():
    provider = Provider(names=[{'value': 'target', 'address': '0x10'}]); count = 0
    def active():
        nonlocal count
        count += 1
        if count == 3: raise InterruptedError('Original cancellation')
    with pytest.raises(InterruptedError):
        compose(provider, SESSION, 'resolve_name_references', {'name': 'target'}, active)
    assert [r[0] for r in provider.calls] == ['current_document', 'list_names']


@pytest.mark.skipif(os.environ.get('THESEUS_TEST_GHIDRA') != '1', reason='Opt-in installed Ghidra and original ELF compiler')
def test_original_elf_compositions_records_and_transfer(tmp_path, monkeypatch):
    from elftools.elf.elffile import ELFFile
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from theseus.binary_analysis import engines
    from test_binary_sessions import wait
    zig = os.environ.get('THESEUS_TEST_ZIG', '')
    if not zig or not Path(zig).is_file() or not engines()['available']:
        pytest.skip('Requires installed original ELF compiler/Ghidra/JDK')
    source, image = tmp_path / 'original.c', tmp_path / 'original.elf'
    source.write_text('volatile int observed_value;\n'
        '__attribute__((noinline)) int original_leaf(int x) { return x*7+3; }\n'
        '__attribute__((noinline)) int original_route(int x) { observed_value=x; return original_leaf(x+5)+11; }\n'
        '__attribute__((noinline)) int original_entry(int x) { return original_route(x)+original_leaf(x-1); }\n', encoding='utf8')
    env = {**os.environ, 'ZIG_GLOBAL_CACHE_DIR': str(tmp_path / 'zig-global'),
           'ZIG_LOCAL_CACHE_DIR': str(tmp_path / 'zig-local')}
    compiled = subprocess.run([zig, 'cc', '-target', 'x86_64-linux-gnu', '-nostdlib', '-no-pie',
        '-fno-sanitize=all', '-g', '-O0', '-fno-inline', '-Wl,-e,original_entry',
        '-o', str(image), str(source)], env=env, capture_output=True, timeout=180)
    (tmp_path / 'compiler.stdout').write_bytes(compiled.stdout)
    (tmp_path / 'compiler.stderr').write_bytes(compiled.stderr)
    assert compiled.returncode == 0, compiled.stderr
    original = image.read_bytes(); digest = hashlib.sha256(original).hexdigest()
    elf = ELFFile(io.BytesIO(original)); assert elf['e_type'] == 'ET_EXEC'
    symbols = {r.name: (r['st_value'], r['st_size']) for r in elf.get_section_by_name('.symtab').iter_symbols()
               if r['st_shndx'] != 'SHN_UNDEF'}
    leaf, route = symbols['original_leaf'], symbols['original_route']
    base = min(r['p_vaddr'] for r in elf.iter_segments() if r['p_type'] == 'PT_LOAD')
    text = elf.get_section_by_name('.text')
    oracle = {'sha256': digest, 'symbols': symbols, 'base': base,
              'text_address': text['sh_addr'], 'text_size': text['sh_size']}
    (tmp_path / 'original-oracle.json').write_text(json.dumps(oracle, indent=2), encoding='utf8')
    app = create_app(tmp_path / 'profile', port=64402)
    with TestClient(app, base_url='http://127.0.0.1:64402') as client:
        client.get('/'); project = app.state.store.create_project('Original native inventory')['id']
        artifact = app.state.store.add_artifact(project, image)
        def agent(tool, **arguments):
            response = client.post('/api/agent/call', json={'tool': tool, 'arguments': arguments})
            response.raise_for_status(); return response.json()['result']
        session = wait(client, agent('theseus_binary_open', project_id=project, artifact_id=artifact['id']))
        assert session['state'] == 'finished', session
        catalogue = client.get('/api/binary-sessions/catalog').json()['operations']
        compositions = {row['name']: row for row in catalogue
                        if row['name'] in {'resolve_name_references', 'binary_overview'}}
        assert set(compositions) == {'resolve_name_references', 'binary_overview'}
        assert all(row['source'] == 'product-composition' and not row['writes_analysis_project']
                   for row in compositions.values())
        def call(operation, parameters=None, expected='finished'):
            job = wait(client, agent('theseus_binary_call', session_id=session['id'],
                operation=operation, parameters=parameters or {}))
            assert job['state'] == expected, job
            return job, None if expected != 'finished' else client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']
        names_job, named = call('resolve_name_references', {'name': 'original_leaf'})
        assert named['status'] == 'resolved' and int(named['address'], 16) == leaf[0]
        assert any(route[0] <= int(address, 16) < route[0] + route[1] for address in named['references'])
        missing_job, missing = call('resolve_name_references', {'name': 'original_lea'})
        assert missing['status'] == 'unresolved' and missing['reason'] == 'name_not_found'
        failed, _ = call('resolve_name_references', {'document': 'another-program', 'name': 'original_leaf'}, expected='failed')
        assert failed['result']['engine_response']['observations'][-1]['response']['ok'] is False
        overview_job, overview = call('binary_overview')
        _, segments = call('list_segments')
        assert overview['segments'] == segments and overview['segment_count'] == len(segments)
        assert overview['image_base_status'] == 'observed' and int(overview['image_base'], 16) == base
        assert overview['image_base_address_space'] == session['result']['info']['target']['default_address_space']
        assert any(int(row['start'], 16) == text['sh_addr'] and int(row['end'], 16) - int(row['start'], 16) == text['sh_size']
                   for row in segments if row['name'] == '.text')
        native = app.state.binary_sessions.runtimes[session['id']]
        request = native.request; entered = threading.Event(); release = threading.Event()
        before_revision = app.state.store.job(session['id'])['result']['revision']
        def held_annotation(method, arguments):
            if method == 'set_address_name':
                entered.set()
                assert release.wait(10), 'The controlled annotation was not released'
            return request(method, arguments)
        monkeypatch.setattr(native, 'request', held_annotation)
        mutation = agent('theseus_binary_call', session_id=session['id'], operation='set_address_name',
                         parameters={'address': named['address'], 'name': 'renamed_leaf'})
        try:
            assert entered.wait(10), 'The controlled annotation did not enter the provider'
            queued = agent('theseus_binary_call', session_id=session['id'], operation='resolve_name_references',
                           parameters={'name': 'renamed_leaf'})
        finally:
            release.set()
        assert wait(client, mutation)['state'] == 'finished'
        queued = wait(client, queued); assert queued['state'] == 'finished', queued
        current = client.get('/api/jobs/'+queued['id']+'/analysis.json').json()['result']
        assert current['status'] == 'resolved' and current['matches'][0]['value'] == 'renamed_leaf'
        assert current['binding']['analysis_revision'] == queued['result']['analysis_revision'] == before_revision + 1
        monkeypatch.setattr(native, 'request', request)
        documents = {row['id']: client.get('/api/jobs/'+row['id']+'/analysis.json').content
                     for row in (names_job, missing_job, overview_job, queued)}
        for job, result in [(names_job, named), (missing_job, missing), (overview_job, overview), (queued, current)]:
            records = app.state.store.analysis_records(job['id'], section='observations', limit=None)['records']
            assert [app.state.store.analysis_record(job['id'], 'observations', row['record_key'])['record']
                    for row in records] == result['observations']
        closed = wait(client, agent('theseus_binary_close', session_id=session['id']))
        assert closed['state'] == 'finished', closed
        actual = app.state.store.job(session['id'])['result']
        assert actual['session_state'] == 'closed' and actual['exit_code'] == 0
        assert image.read_bytes() == original
        parked = image.with_suffix('.parked-original'); image.rename(parked)
        original_exists = Path.exists
        def guarded_exists(path):
            if path == image: pytest.fail('Historical inventory consulted the absent original')
            return original_exists(path)
        monkeypatch.setattr(Path, 'exists', guarded_exists)
        portable = app.state.evidence.export(project)
        for _ in range(2):
            loaded = app.state.evidence.load(portable)
            for old_id, document in documents.items():
                assert client.get('/api/jobs/'+loaded['id_map'][old_id]+'/analysis.json').content == document
            assert not client.get('/api/projects/'+loaded['project']['id']).json()['runtime_sessions']
            portable = app.state.evidence.export(loaded['project']['id'])
            documents = {loaded['id_map'][old]: document for old, document in documents.items()}
        assert parked.read_bytes() == original
