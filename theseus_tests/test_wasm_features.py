"""Signature, feature and validity cases over hand-encoded modules, checked against the host validator.

Every module below is encoded in this file from the core binary format; the bundled reader is
never used to build a fixture. The host oracle is Node's own WebAssembly.validate, run in a
separate process from the product's reader.
"""
import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.native_analysis import engine
from test_native_analysis import wait
from test_portfolio import run


def uleb(value):
    out = bytearray()
    while True:
        byte = value & 0x7f
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def vec(items):
    return uleb(len(items)) + b''.join(items)


def name(text):
    raw = text.encode('utf8')
    return uleb(len(raw)) + raw


def section(identifier, payload):
    return bytes([identifier]) + uleb(len(payload)) + payload


def value_types(values):
    return vec([bytes([value]) if isinstance(value, int) else value for value in values])


def functype(params, results):
    return b'\x60' + value_types(params) + value_types(results)


def module(*sections):
    return bytes.fromhex('0061736d01000000') + b''.join(sections)


def code(*instructions):
    body = b'\x00' + b''.join(instructions) + b'\x0b'
    return uleb(len(body)) + body


I32, I64, F32, F64, V128, EXTERNREF = 0x7f, 0x7e, 0x7d, 0x7c, 0x7b, 0x6f
FUNC, TABLE, MEMORY, GLOBAL, TAG = 0, 1, 2, 3, 4


def func_sig(params, results, kind='func'):
    return {'kind': kind, 'params': params, 'results': results}


def memory_sig(minimum, maximum, shared=False, address='i32'):
    return {'kind': 'memory', 'page_size': '65536', 'address_type': address, 'minimum': minimum, 'maximum': maximum, 'shared': shared}


def table_sig(minimum, maximum, element):
    return {'kind': 'table', 'address_type': 'i32', 'minimum': minimum, 'maximum': maximum, 'shared': False, 'element': element}


def global_sig(value_type, mutable):
    return {'kind': 'global', 'value_type': value_type, 'mutable': mutable}


def tables_memories_globals(global_mutable=True, memory_maximum=4):
    return module(
        section(2, vec([
            name('env') + name('tab') + bytes([TABLE, EXTERNREF]) + b'\x01' + uleb(2) + uleb(10),
            name('env') + name('mem') + bytes([MEMORY]) + b'\x03' + uleb(1) + uleb(memory_maximum),
            name('env') + name('g') + bytes([GLOBAL, I64, int(global_mutable)])])),
        section(6, vec([bytes([F32, 0]) + b'\x43' + b'\x00\x00\x80\x3f' + b'\x0b'])),
        section(7, vec([name('tab') + bytes([TABLE]) + uleb(0), name('mem') + bytes([MEMORY]) + uleb(0),
                        name('g_in') + bytes([GLOBAL]) + uleb(0), name('g_def') + bytes([GLOBAL]) + uleb(1)])))


FEATURE_CASES = {
    'multi-value-and-simd': (module(
        section(1, vec([functype([I32, I64], [F32, F64]), functype([V128], [V128])])),
        section(2, vec([name('env') + name('mv') + bytes([FUNC]) + uleb(0)])),
        section(3, vec([uleb(1)])),
        section(7, vec([name('simd') + bytes([FUNC]) + uleb(1)])),
        section(10, vec([code(b'\x20\x00')]))), [
        ('import', 'env', 'mv', 'func', 0, func_sig(['i32', 'i64'], ['f32', 'f64'])),
        ('export', None, 'simd', 'func', 1, func_sig(['v128'], ['v128']))]),
    'reference-table-shared-memory-globals': (tables_memories_globals(), [
        ('import', 'env', 'tab', 'table', 0, table_sig('2', '10', 'externref')),
        ('import', 'env', 'mem', 'memory', 0, memory_sig('1', '4', shared=True)),
        ('import', 'env', 'g', 'global', 0, global_sig('i64', True)),
        ('export', None, 'tab', 'table', 0, table_sig('2', '10', 'externref')),
        ('export', None, 'mem', 'memory', 0, memory_sig('1', '4', shared=True)),
        ('export', None, 'g_in', 'global', 0, global_sig('i64', True)),
        ('export', None, 'g_def', 'global', 1, global_sig('f32', False))]),
    'memory64-and-multiple-memories': (module(
        section(5, vec([b'\x04' + uleb(1), b'\x01' + uleb(0) + uleb(1)])),
        section(7, vec([name('m64') + bytes([MEMORY]) + uleb(0), name('m32') + bytes([MEMORY]) + uleb(1)]))), [
        ('export', None, 'm64', 'memory', 0, memory_sig('1', None, address='i64')),
        ('export', None, 'm32', 'memory', 1, memory_sig('0', '1'))]),
    'exception-tags': (module(
        section(1, vec([functype([I32, F64], [])])),
        section(2, vec([name('env') + name('exc') + bytes([TAG]) + b'\x00' + uleb(0)])),
        section(13, vec([b'\x00' + uleb(0)])),
        section(7, vec([name('exc_in') + bytes([TAG]) + uleb(0), name('exc_def') + bytes([TAG]) + uleb(1)]))), [
        ('import', 'env', 'exc', 'tag', 0, func_sig(['i32', 'f64'], [], 'tag')),
        ('export', None, 'exc_in', 'tag', 0, func_sig(['i32', 'f64'], [], 'tag')),
        ('export', None, 'exc_def', 'tag', 1, func_sig(['i32', 'f64'], [], 'tag'))]),
}

INVALID_CASES = {
    'function-without-body': (module(section(1, vec([functype([], [])])), section(3, vec([uleb(0)]))), 'reading-module'),
    'sections-out-of-order': (module(section(7, vec([])), section(1, vec([]))), 'reading-module'),
    'export-index-out-of-range': (module(section(7, vec([name('x') + bytes([FUNC]) + uleb(3)]))), 'validating-module'),
    'duplicate-export-name': (module(section(5, vec([b'\x00' + uleb(0)])),
                                     section(7, vec([name('m') + bytes([MEMORY]) + uleb(0)] * 2))), 'validating-module'),
    'shared-memory-without-maximum': (module(section(5, vec([b'\x02' + uleb(1)]))), 'validating-module'),
}

# (ref null func) parameter: valid for the host runtime, outside what the pinned reader decodes.
TYPED_REFERENCE = module(section(1, vec([functype([b'\x63\x70'], [])])),
                         section(2, vec([name('env') + name('r') + bytes([FUNC]) + uleb(0)])))


def duplicate_imports(order):
    signatures = {'empty': functype([], []), 'i32': functype([I32], [])}
    return module(section(1, vec([signatures[key] for key in order])),
                  section(2, vec([name('env') + name('f') + bytes([FUNC]) + uleb(index) for index in range(len(order))])))


def host_valid(content):
    result = subprocess.run([engine()['node'], '--input-type=module', '-e',
                             'process.stdout.write(String(WebAssembly.validate(Buffer.from(process.argv[1],"hex"))))',
                             content.hex()], check=True, capture_output=True, text=True)
    return {'true': True, 'false': False}[result.stdout]


def project(client, title):
    client.get('/')
    store = client.app.state.store
    return store, store.create_project(title)['id']


def started(client, pid, artifact_id, parameters=None):
    response = client.post('/api/agent/call', json={'tool': 'theseus_analysis_start', 'arguments': {
        'project_id': pid, 'artifact_id': artifact_id, 'operation': 'wasm.artifact', 'parameters': parameters or {}}})
    response.raise_for_status()
    return wait(client, response.json()['result'])


def client_for(tmp_path):
    return TestClient(create_app(tmp_path / 'profile', port=64228), base_url='http://127.0.0.1:64228')


@pytest.mark.parametrize('case', sorted(FEATURE_CASES))
def test_enabled_features_validate_and_type_exact_signatures(tmp_path, case):
    content, expected = FEATURE_CASES[case]
    assert host_valid(content) is True
    source = tmp_path / (case + '.wasm')
    source.write_bytes(content)
    with client_for(tmp_path) as client:
        store, pid = project(client, case)
        _, value = run(client, pid, store.add_artifact(pid, source)['id'], 'wasm.artifact')
    assert value['validation'] == 'valid' and value['validators_agree'] is True
    assert value['host_validation']['valid'] is True and value['host_validation']['method'] == 'WebAssembly.validate'
    assert {'threads', 'memory64', 'multi_memory', 'exceptions'} <= set(value['engine_profile']['enabled_features'])
    assert value['interface']['state'] == 'complete' and value['interface']['issues'] == []
    observed = [(row['direction'], row['module'], row['name'], row['kind'], row['index'], row['signature'])
                for row in value['interface']['entries']]
    assert observed == expected
    assert all(row['issue'] is None for row in value['interface']['entries'])


@pytest.mark.parametrize('case', sorted(INVALID_CASES))
def test_invalid_modules_are_never_reported_valid(tmp_path, case):
    content, phase = INVALID_CASES[case]
    assert host_valid(content) is False
    source = tmp_path / (case + '.wasm')
    source.write_bytes(content)
    with client_for(tmp_path) as client:
        store, pid = project(client, case)
        job = started(client, pid, store.add_artifact(pid, source)['id'])
    assert job['state'] == 'failed' and job['result']['execution']['exit_code'] != 0
    value = json.loads(Path(job['result']['analysis_file']).read_bytes())['result']
    assert value['validation'] == 'not-established' and value['completion_status'] == 'unknown'
    assert value['host_validation']['valid'] is False and value['validators_agree'] is True
    assert value['failure']['phase'] == phase and value['failure']['message']
    assert 'interface' not in value and 'wat' not in value


def test_host_valid_module_outside_reader_decoding_is_a_reported_disagreement(tmp_path):
    assert host_valid(TYPED_REFERENCE) is True
    source = tmp_path / 'typed-reference.wasm'
    source.write_bytes(TYPED_REFERENCE)
    with client_for(tmp_path) as client:
        store, pid = project(client, 'Typed reference parameter')
        job = started(client, pid, store.add_artifact(pid, source)['id'])
    value = json.loads(Path(job['result']['analysis_file']).read_bytes())['result']
    # The pinned reader rejects this encoding; the product records the host's opposite verdict
    # instead of calling the module invalid or fabricating a decoded interface.
    assert job['state'] == 'failed' and value['validation'] == 'not-established'
    assert value['host_validation']['valid'] is True and value['validators_agree'] is False
    assert value['failure']['phase'] == 'reading-module' and 'interface' not in value


def test_reader_inspects_exact_bytes_of_a_view_into_a_larger_buffer(tmp_path):
    reader = Path(engine()['entry']).with_name('wasm-inspection.js')
    content = FEATURE_CASES['memory64-and-multiple-memories'][0]
    script = ('import {inspectWasm} from ' + json.dumps(reader.as_uri()) + ';'
              'const backing=Buffer.alloc(4096,0);const bytes=backing.subarray(64,64+process.argv[1].length/2);'
              'Buffer.from(process.argv[1],"hex").copy(bytes);'
              'const value=await inspectWasm(bytes,"view.wasm");'
              'process.stdout.write(JSON.stringify([bytes.buffer.byteLength,value.validation,value.artifact.bytes,value.sections.length]));')
    result = subprocess.run([engine()['node'], '--input-type=module', '-e', script, content.hex()],
                            cwd=tmp_path, check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == [4096, 'valid', len(content), 2]


def test_repeated_imports_compare_as_ordered_occurrences_and_signature_changes_are_detected(tmp_path):
    fixtures = {
        'reference': duplicate_imports(['empty', 'i32']),
        'same': duplicate_imports(['empty', 'i32']),
        'swapped': duplicate_imports(['i32', 'empty']),
        'single': duplicate_imports(['empty']),
        'globals': tables_memories_globals(),
        'immutable': tables_memories_globals(global_mutable=False, memory_maximum=8),
    }
    for content in fixtures.values():
        assert host_valid(content) is True
    with client_for(tmp_path) as client:
        store, pid = project(client, 'Repeated imports')
        jobs, artifacts = {}, {}
        for key, content in fixtures.items():
            path = tmp_path / (key + '.wasm')
            path.write_bytes(content)
            artifacts[key] = store.add_artifact(pid, path)['id']
            jobs[key] = run(client, pid, artifacts[key], 'wasm.artifact')[0]['id']

        def compare(left, right):
            return run(client, pid, artifacts[left], 'wasm.compare_interfaces', {
                'reference_job_id': jobs[left], 'candidate_job_id': jobs[right], 'query': {'scope': 'both'}})[1]

        same, swapped, single = compare('reference', 'same'), compare('reference', 'swapped'), compare('reference', 'single')
        changed = compare('globals', 'immutable')
    for value, state in [(same, 'unchanged'), (swapped, 'changed'), (single, 'changed')]:
        assert len(value['changes']) == 1 and value['changes'][0]['state'] == state
        assert value['coverage'] == 'complete-within-inputs' and value['summary']['unknown'] == 0
    assert same['changes'][0]['occurrences'] == {'left': 2, 'right': 2}
    assert single['changes'][0]['occurrences'] == {'left': 2, 'right': 1}
    states = {json.loads(row['key'])[2] + ':' + json.loads(row['key'])[0]: row['state'] for row in changed['changes']}
    assert states == {'g:import': 'changed', 'g_in:export': 'changed', 'mem:import': 'changed', 'mem:export': 'changed',
                      'tab:import': 'unchanged', 'tab:export': 'unchanged', 'g_def:export': 'unchanged'}
