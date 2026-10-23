"""Literal commands, bounded pipe observations and retained one-shot execution."""
import json
import base64
import hashlib
import os
from pathlib import Path
import sys
import subprocess
import threading
import time

import pytest
import psutil
from jsonschema import ValidationError, validate


def test_execute_catalog_preserves_the_existing_read_only_command():
    from theseus.native_analysis import OPERATIONS
    definitions = {row['name']: row for row in OPERATIONS}
    assert 'rizin.command' in definitions
    assert 'rizin.execute' in definitions
    schema = definitions['rizin.execute']['inputSchema']
    for command in [' ', 'echo Ω café', 'echo ' + 'x' * 800]:
        validate({'command': command}, schema)
    for command in ['', 'a\nb', 'a\rb', 'a\0b', 'a\n', '\rabc']:
        with pytest.raises(ValidationError):
            validate({'command': command}, schema)
    assert definitions['rizin.command']['inputSchema']['properties']['command']['maxLength'] == 400


def capture(tmp_path, code, *, limit=16 * 1024 * 1024, cancelled=None):
    from theseus.rizin_execution import _capture
    path = tmp_path / 'original.bin'
    path.write_bytes(b'original inert command target')
    context = {'artifact': {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()},
               'command': 'caller-selected test', 'combined_output_limit': limit}
    result = _capture([sys.executable, '-u', '-c', code], str(tmp_path), tmp_path, context,
                      limit=limit, cancelled=cancelled)
    for channel in ['stdout', 'stderr']:
        raw = base64.b64decode(result[channel]['base64'], validate=True)
        assert result[channel]['bytes'] == len(raw)
        assert result[channel]['sha256'] == hashlib.sha256(raw).hexdigest()
    return result


@pytest.mark.parametrize('extra', [0, 1])
def test_exact_shared_limit_requires_a_real_excess_byte(tmp_path, extra):
    # Channel order is immaterial: their retained sum must use one raw budget.
    result = capture(tmp_path,
        f'import os; os.write(1,b"a"*4096); os.write(2,b"b"*{4096+extra})', limit=8192)
    assert sum(result[c]['bytes'] for c in ['stdout', 'stderr']) == 8192
    assert result['output_truncated'] is bool(extra)
    assert result['completion_status'] == ('unknown' if extra else 'complete')
    assert result['stream_complete'] is not bool(extra)
    if extra:
        assert result['termination']['reason'] == 'combined-output-limit'


def test_real_contract_budget_and_continuous_writer_are_bounded(tmp_path):
    result = capture(tmp_path, 'import os\nwhile True: os.write(1,b"x"*65536); os.write(2,b"y"*65536)')
    assert result['stdout']['bytes'] + result['stderr']['bytes'] == 16 * 1024 * 1024
    assert result['output_truncated'] and result['completion_status'] == 'unknown'
    assert result['termination']['reason'] == 'combined-output-limit'
    if os.name == 'nt':
        assert result['termination']['cleanup']['owned_process_stopped']
        assert result['owned_group']['active_processes'] == 0


@pytest.mark.parametrize('raw,invalid', [(b'\xef\xbf\xbd', False), (b'\xff\xc3', True)])
def test_literal_replacement_character_and_invalid_utf8_are_distinct(tmp_path, raw, invalid):
    result = capture(tmp_path, 'import os; os.write(1,' + repr(raw) + '); raise SystemExit(7)')
    assert result['stdout']['invalid_utf8_replaced'] is invalid
    assert base64.b64decode(result['stdout']['base64']) == raw
    assert result['exit_code'] == 7 and result['completion_status'] == 'complete'
    assert result['stream_complete']


def test_cancellation_keeps_the_written_prefix_and_owned_descendants_stop(tmp_path):
    latest = tmp_path / 'rizin-latest.json'
    code = ('import os,subprocess,sys,time; '
            'subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
            'os.write(1,b"retained-before-cancel\\n"); time.sleep(60)')
    def cancelled():
        value = json.loads(latest.read_text(encoding='utf8'))['result']
        return value['stdout']['bytes'] > 0
    result = capture(tmp_path, code, cancelled=cancelled)
    assert result['stdout']['text'] == 'retained-before-cancel\n'
    assert result['completion_status'] == 'unknown' and result['termination']['reason'] == 'cancelled'
    if os.name == 'nt':
        assert result['owned_group']['active_processes'] == 0
        assert result['owned_group']['total_processes'] >= 2


def test_retained_reads_need_neither_original_nor_any_new_process(tmp_path, monkeypatch):
    from theseus import rizin_execution as command
    original = capture(tmp_path, 'import os; os.write(1,b"saved once")')
    (tmp_path / 'original.bin').unlink()
    monkeypatch.setattr(command.subprocess, 'Popen', lambda *a, **k: pytest.fail('Retained read replayed execution'))
    monkeypatch.setattr(command, '_file', lambda *a, **k: pytest.fail('Retained read consulted original'))
    saved = command.recording(tmp_path, interrupted=True)
    assert saved['result']['stdout'] == original['stdout']
    assert saved['result']['completion_status'] == 'complete'
    document = json.loads((tmp_path / 'rizin-latest.json').read_text(encoding='utf8'))
    document['result']['phase'] = 'capturing'
    document['result']['completion_status'] = 'unknown'
    (tmp_path / 'rizin-latest.json').write_text(json.dumps(document), encoding='utf8')
    assert command.recording(tmp_path, interrupted=True)['result']['termination']['observer_interrupted']


def test_a_directory_replacing_the_artifact_is_not_walked(tmp_path):
    from theseus.rizin_execution import _file
    folder = tmp_path / 'replacement'
    folder.mkdir()
    (folder / 'not-an-input.txt').write_bytes(b'not observed')
    assert _file(folder) == {'state': 'not-regular-file'}


def test_reader_error_after_bytes_is_not_eof_even_when_the_parent_exited(tmp_path, monkeypatch):
    from theseus import rizin_execution as command
    real_read = os.read
    seen = set()
    def failing_read(fd, count):
        if threading.current_thread().name == 'rizin-stdout':
            if fd in seen:
                raise OSError('original injected pipe failure after bytes')
            data = real_read(fd, count)
            if data:
                seen.add(fd)
            return data
        return real_read(fd, count)
    monkeypatch.setattr(command.os, 'read', failing_read)
    result = capture(tmp_path, 'import os; os.write(1,b"actual prefix"); os.write(2,b"diagnostic")')
    assert result['stdout']['text'] == 'actual prefix'
    assert result['stream_errors']['stdout'] == 'original injected pipe failure after bytes'
    assert 'stdout' not in result['stream_eof']
    assert result['completion_status'] == 'unknown' and not result['stream_complete']
    assert result['termination']['reason'] == 'stream-read-error'


def test_parent_exit_zero_does_not_complete_while_an_owned_child_holds_pipes(tmp_path):
    deadline = time.monotonic() + 15
    def parent_ended():
        assert time.monotonic() < deadline, 'Original parent did not exit'
        path = tmp_path / 'rizin-process.json'
        if not path.is_file():
            return False
        identity = json.loads(path.read_text(encoding='utf8'))
        try:
            process = psutil.Process(identity['pid'])
            return process.create_time() != identity['created'] or process.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return True
    result = capture(tmp_path, 'import subprocess,sys; subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])',
                     cancelled=parent_ended)
    assert result['exit_code'] == 0
    assert result['completion_status'] == 'unknown'
    assert result['termination']['reason'] == 'cancelled'
    if os.name == 'nt':
        assert result['owned_group']['active_processes'] == 0


def test_literal_argv_is_not_file_input_and_disappearing_target_keeps_streams(tmp_path, monkeypatch):
    from theseus import rizin_execution as command
    source = tmp_path / 'original.bin'
    source.write_bytes(b'original own inert bytes')
    selected = 'literal-operand'
    (tmp_path / selected).write_bytes(b'not a declared command input')
    monkeypatch.chdir(tmp_path)
    real_capture, real_file = command._capture, command._file
    inputs = []
    def file_identity(path):
        inputs.append(Path(path))
        return real_file(path)
    def run_selected(argv, cwd, folder, context):
        assert argv == [sys.executable, '-N', '-q', '-c', selected, str(source.resolve())]
        assert cwd == str(tmp_path.resolve())
        code = 'import os; os.write(1,b"before disappearance"); os.unlink(' + repr(str(source)) + ')'
        return real_capture([sys.executable, '-u', '-c', code], cwd, folder, context)
    monkeypatch.setattr(command.rizin, 'engine', lambda: sys.executable)
    monkeypatch.setattr(command, '_capture', run_selected)
    monkeypatch.setattr(command, '_file', file_identity)
    observed = command.inspect(source, {'command': selected}, tmp_path / 'analysis.json', hashlib.sha256(source.read_bytes()).hexdigest())
    assert observed['stdout']['text'] == 'before disappearance'
    assert observed['artifact_after']['state'] == 'absent'
    assert observed['artifact_sha256_after'] is None and observed['artifact_changed'] is None
    assert inputs == [source.resolve(), Path(sys.executable), source.resolve()]
    assert (tmp_path / selected).read_bytes() == b'not a declared command input'


@pytest.mark.parametrize('command_text,expected', [('%vi 37*41', '1517'), ('echo ' + 'L' * 700, 'L' * 700),
                                                  ('echo Ω café 😀', 'Ω café 😀'), ('   ', '')],
                         ids=['arithmetic', 'long-line', 'unicode', 'literal-spaces'])
def test_real_engine_literal_long_and_compound_commands(tmp_path, command_text, expected):
    from theseus import rizin_execution as command
    if command.rizin.engine() is None:
        pytest.skip('Installed free Rizin is required')
    source = tmp_path / 'own-original.bin'
    source.write_bytes(b'original static target; not a program to execute')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    value = command.inspect(source, {'command': command_text}, tmp_path / 'analysis.json', digest)
    assert value['argv'][1:5] == ['-N', '-q', '-c', command_text]
    assert value['stdout']['text'].strip() == expected
    assert value['completion_status'] == 'complete' and value['exit_code'] == 0
    assert value['artifact_sha256_after'] == digest and value['artifact_changed'] is False


def test_real_engine_effects_are_on_the_original_and_history_survives_transfer(tmp_path):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from theseus.rizin import engine
    from test_native_analysis import wait
    if engine() is None:
        pytest.skip('Installed free Rizin is required')
    source = tmp_path / 'owned-effect.bin'
    original = b'original-own-target-4471'
    source.write_bytes(original)
    app = create_app(tmp_path / 'profile', port=64342)
    with TestClient(app, base_url='http://127.0.0.1:64342') as client:
        client.get('/')
        project = app.state.store.create_project('Explicit original command effect')['id']
        artifact = app.state.store.add_artifact(project, source)
        command_text = 'o+ ' + source.as_posix() + '; wx 41424344 @ 0; p8 4 @ 0'
        response = client.post('/api/projects/' + project + '/artifacts/' + artifact['id'] + '/analyses',
            json={'operation': 'rizin.execute', 'parameters': {'command': command_text}})
        response.raise_for_status()
        job = wait(client, response.json())
        assert job['state'] == 'finished', job
        assert source.read_bytes() == b'ABCD' + original[4:]
        document = client.get('/api/jobs/' + job['id'] + '/analysis.json').content
        value = json.loads(document)['result']
        assert '41424344' in value['stdout']['text']
        assert value['artifact_changed'] is True
        assert value['artifact_sha256_after'] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert job['result']['original_source_check'] == 'not-performed-retained-observation'
        portable = app.state.evidence.export(project)
        source.unlink()
        loaded = app.state.evidence.load(portable)
        imported = loaded['id_map'][job['id']]
        assert client.get('/api/jobs/' + imported + '/analysis.json').content == document
        assert app.state.store.analysis_records(imported, section='stdout', limit=None)['records']


@pytest.fixture(scope='module')
def slow_engine(tmp_path_factory):
    setup = Path('C:/Program Files/Microsoft Visual Studio/18/Community/VC/Auxiliary/Build/vcvars64.bat')
    if os.name != 'nt' or not setup.is_file():
        pytest.skip('The original native slow-engine oracle requires the Windows C compiler')
    folder = tmp_path_factory.mktemp('owned-command-engine')
    (folder / 'engine.c').write_text(
        '#include <windows.h>\nint main(void) { DWORD n; const char s[]="command-prefix-1154\\n"; '
        'WriteFile(GetStdHandle(STD_OUTPUT_HANDLE),s,sizeof(s)-1,&n,0); Sleep(60000); return 7; }\n', encoding='ascii')
    batch = folder / 'build.cmd'
    batch.write_text('@echo off\ncall "' + str(setup) + '" >nul\nif errorlevel 1 exit /b 1\n'
                     'cl /nologo engine.c /Feengine.exe\nexit /b %errorlevel%\n', encoding='ascii')
    compiled = subprocess.run(['cmd.exe', '/d', '/c', str(batch)], cwd=folder, capture_output=True, timeout=120)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    return folder / 'engine.exe'


def test_native_cancel_and_interrupted_recovery_keep_prefix_without_original(tmp_path, slow_engine, monkeypatch):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from theseus import native_analysis, rizin_execution
    from test_native_analysis import wait
    monkeypatch.setenv('THESEUS_RIZIN', str(slow_engine))
    source = tmp_path / 'original.bin'
    source.write_bytes(b'own inert input for cancellation')
    app = create_app(tmp_path / 'profile', port=64342)
    with TestClient(app, base_url='http://127.0.0.1:64342') as client:
        client.get('/')
        store = app.state.store
        project = store.create_project('Command prefix without replay')['id']
        artifact = store.add_artifact(project, source)
        response = client.post('/api/projects/' + project + '/artifacts/' + artifact['id'] + '/analyses',
            json={'operation': 'rizin.execute', 'parameters': {'command': 'slow'}})
        response.raise_for_status()
        job = response.json()
        latest = store.directory / 'analyses' / job['id'] / 'rizin-latest.json'
        deadline = time.monotonic() + 20
        try:
            while True:
                try:
                    prefix = json.loads(latest.read_text(encoding='utf8'))['result']
                except (FileNotFoundError, PermissionError):
                    prefix = None
                if prefix and prefix['stdout']['bytes']:
                    break
                assert time.monotonic() < deadline
                time.sleep(.02)
            source.unlink()
            original_digest = native_analysis.digest
            def guarded_digest(path):
                assert Path(path).resolve() != source.resolve(), 'Retention re-read the retired original'
                return original_digest(path)
            monkeypatch.setattr(native_analysis, 'digest', guarded_digest)
            client.post('/api/jobs/' + job['id'] + '/cancel').raise_for_status()
            job = wait(client, client.get('/api/jobs/' + job['id']).json())
            assert job['state'] == 'cancelled' and job['result']['command_observation']['completion_status'] == 'unknown'
            document = client.get('/api/jobs/' + job['id'] + '/analysis.json').content
            assert json.loads(document)['result']['stdout']['text'] == 'command-prefix-1154\n'
            interrupted = {k:v for k,v in job['result'].items() if k not in {'analysis_file','analysis_sha256','sections'}}
            store.save_job(project, job['id'], 'interrupted', interrupted)
            monkeypatch.setattr(rizin_execution, '_capture', lambda *a, **k: pytest.fail('Recovery replayed command'))
            monkeypatch.setattr(rizin_execution, '_file', lambda *a, **k: pytest.fail('Recovery inspected original'))
            native_analysis.recover(store)
            recovered = store.job(job['id'])
            assert recovered['state'] == 'interrupted' and recovered['result']['recovered_recording']
            value = json.loads(Path(recovered['result']['analysis_file']).read_text(encoding='utf8'))['result']
            assert value['stdout']['text'] == 'command-prefix-1154\n' and value['completion_status'] == 'unknown'
            bundle = app.state.evidence.export(project)
            imported = app.state.evidence.load(bundle)
            assert client.get('/api/jobs/' + imported['id_map'][job['id']] + '/analysis.json').content == Path(recovered['result']['analysis_file']).read_bytes()
        finally:
            if store.job(job['id'])['state'] in {'queued','running'}:
                client.post('/api/jobs/' + job['id'] + '/cancel').raise_for_status()


def test_transport_failure_after_an_observation_does_not_discard_its_document(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from theseus.rizin import engine
    from test_native_analysis import wait
    if engine() is None:
        pytest.skip('Installed free Rizin is required')
    source = tmp_path / 'original.bin'
    source.write_bytes(b'own original for completed transport failure')
    app = create_app(tmp_path / 'profile', port=64342)
    real_execute = app.state.comparisons._execute
    calls = []
    def transport(job_id, command, definition):
        calls.append(job_id)
        real_execute(job_id, command, definition)
        source.unlink()
        raise OSError('authored transport error after complete observation')
    monkeypatch.setattr(app.state.comparisons, '_execute', transport)
    with TestClient(app, base_url='http://127.0.0.1:64342') as client:
        client.get('/')
        store = app.state.store
        project = store.create_project('Observed command despite transport failure')['id']
        artifact = store.add_artifact(project, source)
        response = client.post('/api/projects/' + project + '/artifacts/' + artifact['id'] + '/analyses',
            json={'operation':'rizin.execute','parameters':{'command':'%vi 7*9'}})
        response.raise_for_status()
        job = wait(client, response.json())
        assert job['state'] == 'failed' and 'authored transport error' in job['result']['error']
        assert len(calls) == 1 and 'retention_error' not in job['result']
        observed = client.get('/api/jobs/' + job['id'] + '/analysis.json').json()['result']
        assert observed['stdout']['text'].strip() == '63'
        assert observed['completion_status'] == 'complete'
        assert job['result']['original_source_check'] == 'not-performed-retained-observation'


def test_recovery_of_launch_intent_keeps_unknown_effects_without_replay(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from theseus import native_analysis, rizin_execution
    source = tmp_path / 'original.bin'
    source.write_bytes(b'own launch-intent target')
    app = create_app(tmp_path / 'profile', port=64342)
    with TestClient(app, base_url='http://127.0.0.1:64342') as client:
        client.get('/')
        store = app.state.store
        project = store.create_project('Interrupted before launch checkpoint')['id']
        artifact = store.add_artifact(project, source)
        job_id = 'own-launch-intent-1154'
        folder = store.directory / 'analyses' / job_id
        folder.mkdir(parents=True)
        empty = {'bytes':0,'base64':'','sha256':hashlib.sha256(b'').hexdigest(),'text':'','invalid_utf8_replaced':False}
        value = {'phase':'launch-intent','artifact':{'sha256':artifact['sha256']},'stdout':empty,'stderr':empty,
                 'termination':{},'completion_status':'unknown','exit_code':None,'output_truncated':False,
                 'stream_complete':False,'artifact_changed':None}
        (folder / 'rizin-latest.json').write_text(json.dumps({'operation':'rizin.execute',
            'artifact_sha256':artifact['sha256'],'runtime':'original-test','result':value}),encoding='utf8')
        store.save_job(project, job_id, 'interrupted', {'kind':'native_analysis','operation':'rizin.execute',
            'artifact_id':artifact['id'],'artifact_name':artifact['name'],'parameters':{'command':'caller line'}})
        source.unlink()
        monkeypatch.setattr(rizin_execution, '_capture', lambda *a, **k: pytest.fail('Intent replayed'))
        monkeypatch.setattr(rizin_execution, '_file', lambda *a, **k: pytest.fail('Intent reopened original'))
        native_analysis.recover(store)
        recovered = store.job(job_id)
        assert recovered['result']['recovered_recording'] and recovered['state'] == 'interrupted'
        document = client.get('/api/jobs/' + job_id + '/analysis.json').json()['result']
        assert document['phase'] == 'launch-intent' and document['completion_status'] == 'unknown'
        assert document['termination']['observer_interrupted'] and document['stdout']['bytes'] == 0


@pytest.mark.skipif(os.environ.get('THESEUS_TEST_GHIDRA') != '1', reason='Opt-in installed-engine composition')
def test_arbitrary_command_keeps_the_existing_native_session_open(tmp_path):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from theseus.binary_analysis import engines
    from theseus.rizin import engine
    if not engines()['available'] or engine() is None:
        pytest.skip('Installed Ghidra/JDK and Rizin are required')
    native = tmp_path / 'original-native.bin'
    original = bytes.fromhex('b82a000000c3')
    native.write_bytes(original)
    other = tmp_path / 'original-command.bin'
    other.write_bytes(b'own inert command input')
    app = create_app(tmp_path / 'profile', port=64342)
    with TestClient(app, base_url='http://127.0.0.1:64342') as client:
        client.get('/')
        store = app.state.store
        project = store.create_project('Independent native and command sessions')['id']
        artifact = store.add_artifact(project, native)
        second = store.add_artifact(project, other)
        def completed(job):
            deadline = time.monotonic() + 180
            while job['state'] in {'queued','running'}:
                assert time.monotonic() < deadline, job
                time.sleep(.05)
                job = store.job(job['id'])
            assert job['state'] == 'finished', job
            return job
        opened = client.post('/api/projects/' + project + '/artifacts/' + artifact['id'] + '/binary-sessions',
            json={'options': {'raw':True,'language_id':'x86:LE:64:default','base_address':'0x1000'}})
        opened.raise_for_status()
        session = completed(opened.json())['id']
        response = client.post('/api/projects/' + project + '/artifacts/' + second['id'] + '/analyses',
            json={'operation':'rizin.execute','parameters':{'command':'%vi 19*23'}})
        response.raise_for_status()
        command_job = completed(response.json())
        assert client.get('/api/jobs/' + command_job['id'] + '/analysis.json').json()['result']['stdout']['text'].strip() == '437'
        listing = app.state.binary_sessions.list(project_id=project)['sessions']
        assert next(s for s in listing if s['id'] == session)['result']['session_state'] == 'open'
        observed = client.post('/api/binary-sessions/' + session + '/call',
            json={'operation':'read_bytes','parameters':{'address':'0x1000','length':len(original)}})
        observed.raise_for_status()
        read_job = completed(observed.json())
        assert client.get('/api/jobs/' + read_job['id'] + '/analysis.json').json()['result']['bytes_hex'] == original.hex()
        assert native.read_bytes() == original
