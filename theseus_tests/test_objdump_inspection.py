import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import types

import pytest

from theseus import objdump_inspection as reader


@pytest.fixture
def selected_reader(tmp_path, monkeypatch):
    executable = tmp_path / 'original-reader.exe'
    executable.write_bytes(b'authored inert reader identity')
    monkeypatch.setattr(reader, 'engine', lambda: {'available': True, 'path': str(executable), 'source': 'explicit-test'})
    return executable


def test_invalid_selectors_and_changed_input_never_invoke_reader(tmp_path, selected_reader, monkeypatch):
    monkeypatch.setattr(reader.process_capture, 'capture_process', lambda *a, **k: pytest.fail('No reader may run'))
    source = tmp_path / 'original.o'
    source.write_bytes(b'original input')
    for operation, kwargs in [('unknown', {}), ('architectures', {'source': source}),
                              ('architectures', {'follow_debug_links': True}), ('symbols', {}),
                              ('symbols', {'source': source, 'expected_sha256': '0' * 64})]:
        with pytest.raises(ValueError):
            reader.inspect(operation, tmp_path / 'job', **kwargs)
    assert not (tmp_path / 'job').exists()


def test_dwarf_command_retains_exact_streams_and_explicit_external_input_policy(tmp_path, selected_reader, monkeypatch):
    source = tmp_path / '-original.o'
    source.write_bytes(b'original artifact')
    observed = []
    def capture(parameters, folder, cancelled, **options):
        assert options == {'include_file_content': False}
        observed.append(parameters)
        return {'status': 'complete', 'stream_complete': True, 'target': {'argv': parameters['argv']},
                'process': {'exit_code': 3},
                'stdout': reader.process_capture._bytes(b'original\xff\x00\r\n'),
                'stderr': reader.process_capture._bytes(b'not an accepted object\n'),
                'files': [{'label': 'artifact', 'before': reader.process_capture._file(source),
                           'after': reader.process_capture._file(source)}]}
    monkeypatch.setattr(reader.process_capture, 'capture_process', capture)
    for follow in [False, True]:
        result = reader.inspect('dwarf', tmp_path / ('job-' + str(follow)), source=source, follow_debug_links=follow)
        args = observed[-1]
        assert args['environment'] == {'DEBUGINFOD_URLS': '', 'LC_ALL': 'C'}
        assert args['argv'][-2:] == ['--', str(source.resolve())]
        assert '--dwarf=do-not-use-debuginfod' in args['argv']
        assert ('--dwarf=follow-links' if follow else '--dwarf=no-follow-links') in args['argv']
        assert result['completion_status'] == 'complete' and result['exit_code'] == 3
        assert result['stdout']['invalid_utf8_replaced'] and base64.b64decode(result['stdout']['base64']) == b'original\xff\x00\r\n'
        assert result['stderr']['text'] == 'not an accepted object\n' and result['artifact_changed'] is False
        assert result['follow_debug_links_effective'] is follow


def test_retained_prefix_does_not_turn_missing_after_state_into_unchanged(tmp_path):
    context = {'operation': 'symbols', 'started_at': 'original-time', 'engine': {},
               'artifact': {'sha256': '1' * 64}, 'follow_debug_links': False}
    capture = {'status': 'partial', 'stream_complete': False, 'target': {'argv': ['reader', '--syms']},
               'process': {'exit_code': None}, 'files': [],
               'stdout': reader.process_capture._bytes(b'partial prefix'), 'stderr': reader.process_capture._bytes(b'')}
    value = reader.normalize(context, capture)
    assert value['completion_status'] == 'unknown' and value['artifact_changed'] is None
    assert value['stdout']['text'] == 'partial prefix' and not value['stream_complete']
    capture['stdout']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='byte identity'):
        reader.normalize(context, capture)


@pytest.mark.parametrize('platform,code,name', [('posix', -15, 'SIGTERM'), ('nt', None, None)])
def test_stream_eof_does_not_certify_signal_termination_or_an_unobserved_exit(monkeypatch, platform, code, name):
    monkeypatch.setattr(reader, 'os', types.SimpleNamespace(name=platform))
    context = {'operation': 'symbols', 'started_at': 'original-time', 'engine': {},
               'artifact': None, 'follow_debug_links': False}
    capture = {'status': 'complete', 'stream_complete': True, 'target': {'argv': ['reader', '--syms']},
               'process': {'exit_code': code}, 'files': [], 'stdout': reader.process_capture._bytes(b'observed prefix'),
               'stderr': reader.process_capture._bytes(b'original diagnostic')}
    result = reader.normalize(context, capture)
    assert result['completion_status'] == 'unknown' and result['exit_code'] is None
    assert result['signal'] == name and result['process_observation']['process']['exit_code'] == code
    assert base64.b64decode(result['stdout']['base64']) == b'observed prefix'


@pytest.fixture(scope='module')
def original_object(tmp_path_factory):
    if not reader.engine()['available'] or not shutil.which('rustc'):
        pytest.skip('GNU objdump and the original-fixture compiler are required')
    directory = tmp_path_factory.mktemp('original-object')
    source = directory / 'original.rs'
    source.write_text('''#![no_std]
extern "C" { fn original_import(value: u64) -> u64; }
#[no_mangle] pub extern "C" fn original_objdump_rule(value: u64) -> u64 {
    unsafe { original_import(value.wrapping_mul(7).wrapping_add(11)) }
}
''', encoding='utf8')
    binary = directory / 'original.o'
    compiled = subprocess.run(['rustc', str(source), '--edition=2021', '--target', 'x86_64-unknown-linux-gnu',
        '--crate-type=lib', '--emit=obj', '-Cpanic=abort', '-g', '-o', str(binary)], capture_output=True)
    assert compiled.returncode == 0, compiled.stderr
    return source, binary, binary.read_bytes()


@pytest.mark.parametrize('operation', [name for name in reader.COMMANDS if name != 'architectures'])
def test_real_gnu_reader_original_headers_symbols_relocations_dwarf_and_code(tmp_path, original_object, operation):
    source, binary, raw = original_object
    result = reader.inspect(operation, tmp_path / 'inspection', source=binary,
                            expected_sha256=hashlib.sha256(raw).hexdigest())
    assert result['completion_status'] == 'complete' and result['exit_code'] == 0
    assert result['artifact_changed'] is False and result['artifact']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert not result['target_executed'] and binary.read_bytes() == raw
    assert 'base64' not in result['engine']['identity']
    assert all('base64' not in row[side] for row in result['process_observation']['files'] for side in ['before', 'after'])
    for key in ['stdout', 'stderr']:
        stream = base64.b64decode(result[key]['base64'])
        assert len(stream) == result[key]['bytes'] and hashlib.sha256(stream).hexdigest() == result[key]['sha256']
    expected = {'file_headers': 'elf64-x86-64', 'section_headers': '.debug_info',
                'symbols': 'original_objdump_rule', 'relocations': 'original_import',
                'dwarf': 'original_objdump_rule', 'disassemble': 'original_objdump_rule',
                'disassemble_all': 'original_objdump_rule'}
    assert expected[operation] in result['stdout']['text']


def test_real_subjectless_targets_and_retained_read_never_reinspect_originals(tmp_path, original_object, monkeypatch):
    source, binary, raw = original_object
    folder = tmp_path / 'job'
    result = reader.inspect('symbols', folder, source=binary)
    # Guard the original paths and executable, while allowing only recorded files.
    blocked = {source.resolve(), binary.resolve(), Path(result['engine']['path']).resolve()}
    previous = Path.is_file
    def only_retained(path):
        assert path.resolve() not in blocked, 'Retained read touched an original path'
        return previous(path)
    monkeypatch.setattr(Path, 'is_file', only_retained)
    assert reader.recording(folder) == result
    monkeypatch.setattr(Path, 'is_file', previous)
    targets = reader.inspect('architectures', tmp_path / 'targets')
    assert targets['artifact'] is None and targets['artifact_sha256_after'] is None and targets['artifact_changed'] is None
    assert targets['completion_status'] == 'complete' and targets['exit_code'] == 0
    assert 'elf64-x86-64' in targets['stdout']['text']


@pytest.mark.parametrize('include_content', [True, False])
def test_file_identity_mode_preserves_default_bodies_and_every_stream_byte(tmp_path, include_content):
    source = tmp_path / 'original.txt'
    before, after = b'original before', b'original after\xff'
    source.write_bytes(before)
    script = 'from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(bytes.fromhex("' + after.hex() + '")); sys.stdout.buffer.write(b"observed\\xff\\n")'
    parameters = {'argv': [sys.executable, '-c', script, str(source)], 'cwd': str(tmp_path),
                  'files': [{'label': 'original', 'path': str(source)}]}
    options = {} if include_content else {'include_file_content': False}
    capture = reader.process_capture.capture_process(parameters, tmp_path / 'capture', **options)
    assert capture['status'] == 'complete' and capture['stream_complete']
    assert base64.b64decode(capture['stdout']['base64']) == b'observed\xff\n'
    observed = capture['files'][0]
    assert observed['before']['sha256'] == hashlib.sha256(before).hexdigest()
    assert observed['after']['sha256'] == hashlib.sha256(after).hexdigest()
    assert ('base64' in observed['before']) is include_content and ('base64' in observed['after']) is include_content
    if include_content:
        assert base64.b64decode(observed['before']['base64']) == before
        assert base64.b64decode(observed['after']['base64']) == after
    else:
        assert capture['file_content_retained'] is False
        assert all('base64' not in row['after'] for row in capture['process']['input_file_changes'])


def test_real_native_api_records_and_transfer_after_original_removed(tmp_path, original_object, monkeypatch):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from test_native_analysis import wait
    binary = tmp_path / 'owned-original.o'
    binary.write_bytes(original_object[2])
    app = create_app(tmp_path / 'profile', port=64222)
    with TestClient(app, base_url='http://127.0.0.1:64222') as client:
        client.get('/')
        pid = app.state.store.create_project('Original binary reader evidence')['id']
        artifact = app.state.store.add_artifact(pid, binary)
        response = client.post('/api/projects/' + pid + '/artifacts/' + artifact['id'] + '/analyses',
            json={'operation': 'binary.objdump', 'parameters': {'facet': 'symbols'}})
        assert response.status_code == 200, response.text
        job = wait(client, response.json())
        assert job['state'] == 'finished', job
        assert job['result']['reader_observation']['completion_status'] == 'complete'
        assert job['result']['reader_observation']['exit_code'] == 0
        document = client.get('/api/jobs/' + job['id'] + '/analysis.json').content
        assert 'original_objdump_rule' in json.loads(document)['result']['stdout']['text']
        bad_source = tmp_path / 'original-unknown.bin'
        bad_source.write_bytes(b'authored non-object input')
        bad_artifact = app.state.store.add_artifact(pid, bad_source)
        rejected = client.post('/api/projects/' + pid + '/artifacts/' + bad_artifact['id'] + '/analyses',
            json={'operation': 'binary.objdump', 'parameters': {'facet': 'file_headers'}})
        rejected.raise_for_status()
        bad_job = wait(client, rejected.json())
        assert bad_job['state'] == 'finished' and bad_job['result']['reader_observation']['exit_code'] != 0
        bad_document = client.get('/api/jobs/' + bad_job['id'] + '/analysis.json').json()['result']
        assert bad_document['stderr']['bytes'] > 0 and bad_document['completion_status'] == 'complete'
        portable = app.state.evidence.export(pid)
        binary.unlink()
        bad_source.unlink()
        loaded = app.state.evidence.load(portable)
        key = loaded['id_map'][job['id']]
        original = Path.exists
        def no_original(path):
            assert path.resolve() != binary.resolve(), 'Retained read inspected the retired original'
            return original(path)
        monkeypatch.setattr(Path, 'exists', no_original)
        assert client.get('/api/jobs/' + key + '/analysis.json').content == document
        page = app.state.store.analysis_records(key, section='stdout', limit=None)
        assert len(page['records']) == 1


def test_real_subjectless_native_tool_and_api_have_no_projects_or_artifacts(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from theseus.api import TOOLS, create_app
    if not reader.engine()['available']:
        pytest.skip('GNU objdump is required')
    app = create_app(tmp_path / 'profile', port=64222)
    with TestClient(app, base_url='http://127.0.0.1:64222') as client:
        client.get('/')
        previous = subprocess.run
        def not_on_discovery(*args, **kwargs):
            pytest.fail('Cold discovery invoked a binary reader')
        monkeypatch.setattr(subprocess, 'run', not_on_discovery)
        client.get('/api/agent/tools').raise_for_status()
        client.get('/api/analyses/catalog').raise_for_status()
        monkeypatch.setattr(subprocess, 'run', previous)
        for path, payload in [('/api/engines/inspect', {'family': 'objdump'}),
                              ('/api/agent/call', {'tool': 'theseus_client_inspect', 'arguments': {'family': 'objdump'}})]:
            response = client.post(path, json=payload)
            assert response.status_code == 200, response.text
            value = response.json().get('result', response.json())
            assert value['family'] == 'objdump' and not value['artifact_accessed'] and not value['target_executed']
            assert value['clients'][0]['status'] == 'ok'
            targets = value['advertised_targets']
            assert targets['artifact'] is None and targets['client_identity_consistent']
            assert targets['exit_code'] == 0 and 'elf64-x86-64' in targets['stdout']['text']
        assert client.get('/api/projects').json()['projects'] == []
    native = next(row for row in TOOLS if row['name'] == 'theseus_client_inspect')
    catalog = json.loads((Path(__file__).resolve().parents[1] / 'vitruvius_hoard/software/catalog.json').read_text(encoding='utf8'))
    assert next(row for row in catalog if row['name'] == native['name']) == {**native, 'module': 'theseus'}


def test_cancelled_reader_retains_prefix_and_recovery_never_replays_command(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from test_native_analysis import wait
    setup = Path('C:/Program Files/Microsoft Visual Studio/18/Community/VC/Auxiliary/Build/vcvars64.bat')
    if not setup.is_file():
        pytest.skip('Windows C compiler is required for the original slow-reader fixture')
    source = tmp_path / 'original-reader.c'
    source.write_text('#include <windows.h>\nint main(void) { DWORD n; const char s[]="original-prefix\\n"; '
        'WriteFile(GetStdHandle(STD_OUTPUT_HANDLE),s,sizeof(s)-1,&n,0); Sleep(30000); return 0; }\n', encoding='utf8')
    script = tmp_path / 'compile.cmd'
    script.write_text('@echo off\ncall "' + str(setup) + '" >nul\nif errorlevel 1 exit /b 1\n'
        'cl /nologo original-reader.c /Feoriginal-reader.exe\nexit /b %errorlevel%\n', encoding='utf8')
    result = subprocess.run(['cmd.exe', '/d', '/c', str(script)], cwd=tmp_path, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    monkeypatch.setenv('THESEUS_OBJDUMP', str(tmp_path / 'original-reader.exe'))
    artifact_path = tmp_path / 'original-input.bin'
    artifact_path.write_bytes(b'authored inert artifact; never executed')
    app = create_app(tmp_path / 'profile', port=64222)
    with TestClient(app, base_url='http://127.0.0.1:64222') as client:
        client.get('/')
        store = app.state.store
        pid = store.create_project('Owned slow-reader prefix')['id']
        artifact = store.add_artifact(pid, artifact_path)
        response = client.post('/api/projects/' + pid + '/artifacts/' + artifact['id'] + '/analyses',
            json={'operation': 'binary.objdump', 'parameters': {'facet': 'symbols'}})
        assert response.status_code == 200, response.text
        job = response.json()
        folder = store.directory / 'analyses' / job['id']
        latest = folder / 'objdump-capture' / 'capture-latest.json'
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    prefix=json.loads(latest.read_text(encoding='utf8'))
                except (FileNotFoundError,PermissionError):
                    prefix=None
                if prefix and prefix['result']['stdout']['bytes']:
                    break
                current=store.job(job['id'])
                assert current['state'] in {'queued','running'},(current,prefix)
                assert time.monotonic() < deadline
                time.sleep(.02)
            client.post('/api/jobs/' + job['id'] + '/cancel').raise_for_status()
            job = wait(client, client.get('/api/jobs/' + job['id']).json())
            assert job['state'] == 'cancelled', job
            assert job['result']['reader_observation']['completion_status'] == 'unknown'
            document = client.get('/api/jobs/' + job['id'] + '/analysis.json').content
            value = json.loads(document)['result']
            assert value['stdout']['text'] == 'original-prefix\n' and value['completion_status'] == 'unknown'
            assert value['artifact_changed'] is None and not value['stream_complete']
            # Reconstruct an interrupted receipt from the persisted prefix and dead
            # worker identities, then prohibit any new decoder launch during recovery.
            interrupted = {k: v for k, v in job['result'].items() if k not in {'analysis_file', 'analysis_sha256', 'sections'}}
            store.save_job(pid, job['id'], 'interrupted', interrupted)
            from theseus import native_analysis
            monkeypatch.setattr(reader.process_capture, 'capture_process', lambda *a, **k: pytest.fail('Recovery replayed a reader'))
            native_analysis.recover(store)
            recovered = store.job(job['id'])
            assert recovered['state'] == 'interrupted' and recovered['result']['recovered_recording']
            retained = json.loads(Path(recovered['result']['analysis_file']).read_text(encoding='utf8'))['result']
            assert retained['stdout']['text'] == 'original-prefix\n' and retained['completion_status'] == 'unknown'
        finally:
            current=store.job(job['id'])
            if current['state'] in {'queued','running'}:
                client.post('/api/jobs/'+job['id']+'/cancel').raise_for_status()
