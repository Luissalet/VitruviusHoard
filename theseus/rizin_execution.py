"""Caller-selected command observations with a shared raw output budget."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import threading
import time

import psutil

try:
    from . import process_capture, rizin
except ImportError:
    import process_capture
    import rizin

OUTPUT_LIMIT = 16 * 1024 * 1024
OPERATIONS = [{'name': 'rizin.execute', 'title': 'Rizin · Ejecutar orden', 'worker': 'python',
    'description': 'Ejecuta una línea literal con plugins sobre el archivo original. Puede cambiar archivos, ejecutar código o acceder a entradas externas. Conserva hasta 16 MiB combinados de salida y error; las interrupciones mantienen su incertidumbre sin repetir la orden.',
    'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['command'],
        'properties': {'command': {'type': 'string', 'minLength': 1, 'not': {'pattern': '[\\r\\n\\u0000]'}}}},
    'example': {'command': 'iI'}}]


def _stream(raw):
    try:
        text, invalid = raw.decode('utf8'), False
    except UnicodeDecodeError:
        text, invalid = raw.decode('utf8', errors='replace'), True
    return {**process_capture._bytes(raw), 'text': text, 'invalid_utf8_replaced': invalid}


def _document(context, result):
    return {'operation': 'rizin.execute', 'artifact_sha256': context['artifact']['sha256'],
            'runtime': sys.version.split()[0], 'result': result}


def _file(path):
    """Hash one regular file; a replaced directory is never recursively read."""
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or getattr(before, 'st_file_attributes', 0) & 0x400:
            return {'state': 'not-regular-file'}
        digest = hashlib.sha256()
        size = 0
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
                size += len(chunk)
        after = path.lstat()
        stable = (before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns)
        return {'state': 'file' if stable else 'unstable', 'bytes': size, 'sha256': digest.hexdigest()}
    except FileNotFoundError:
        return {'state': 'absent'}
    except OSError as error:
        return {'state': 'unavailable', 'error': str(error)}


def _capture(argv, cwd, folder, context, *, limit=OUTPUT_LIMIT, cancelled=None):
    """Apply the common byte budget inside the readers, before any buffering."""
    folder = Path(folder)
    latest = folder / 'rizin-latest.json'
    assert limit > 0
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    eof, errors, threads = set(), {}, []
    guard = threading.Lock()
    exceeded = threading.Event()
    process, job = None, None
    state = {**context, 'phase': 'launch-intent', 'exit_code': None, 'signal': None,
             'completion_status': 'unknown', 'output_truncated': False,
             'artifact_sha256_after': None, 'artifact_changed': None,
             'termination': {}, 'process_identity': None}

    def persist():
        with guard:
            value = {**state, 'stdout': _stream(bytes(buffers['stdout'])),
                     'stderr': _stream(bytes(buffers['stderr'])),
                     'output_truncated': exceeded.is_set(), 'stream_errors': dict(errors),
                     'stream_complete': eof == {'stdout', 'stderr'} and not errors and not exceeded.is_set(),
                     'stream_eof': sorted(eof)}
        process_capture._write(latest, _document(context, value))
        return value

    def reader(channel, stream):
        try:
            while True:
                data = os.read(stream.fileno(), 65536)
                if not data:
                    with guard:
                        eof.add(channel)
                    break
                with guard:
                    room = limit - sum(len(raw) for raw in buffers.values())
                    buffers[channel].extend(data[:room])
                    if len(data) > room:
                        exceeded.set()
                        break
        except OSError as error:
            with guard:
                errors[channel] = str(error)
        finally:
            stream.close()

    def owned_active():
        if job is not None:
            observed = job.accounting()
            state['owned_group'] = observed
            return observed['active_processes'] > 0
        # Only this invocation's new POSIX process group is observed. Detached
        # groups and external brokers remain outside the declared ownership.
        for child in psutil.process_iter(['pid', 'status']):
            try:
                if child.info['status'] != psutil.STATUS_ZOMBIE and os.getpgid(child.pid) == process.pid:
                    return True
            except (psutil.Error, ProcessLookupError, PermissionError):
                pass
        return False

    def stop(reason):
        state['termination']['reason'] = reason
        state['termination']['imposed'] = True
        if job is not None:
            state['termination']['cleanup'] = job.stop()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)

    # Intent and empty streams precede process creation. A lost observer never
    # turns the launch/checkpoint gap into a claim that effects did not occur.
    persist()
    try:
        process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
            creationflags=(subprocess.CREATE_NO_WINDOW | 0x4) if os.name == 'nt' else 0,
            start_new_session=os.name != 'nt')
        state['process_identity'] = process_capture._identity(process.pid)
        process_capture._write(folder / 'rizin-process.json', state['process_identity'])
        if os.name == 'nt':
            try:
                from .process_windows import WindowsJob
            except ImportError:
                from process_windows import WindowsJob
            job = WindowsJob()
            job.assign(process.pid)
        state['phase'] = 'capturing'
        persist()
        for channel, stream in [('stdout', process.stdout), ('stderr', process.stderr)]:
            thread = threading.Thread(target=reader, args=(channel, stream), name='rizin-' + channel, daemon=True)
            thread.start()
            threads.append(thread)
        if job is not None:
            initial_threads = psutil.Process(process.pid).threads()
            if len(initial_threads) != 1:
                raise OSError('The suspended command does not have one initial thread')
            job.resume(thread_id=initial_threads[0].id)
        last_checkpoint = time.monotonic()
        while True:
            if exceeded.is_set():
                stop('combined-output-limit')
                break
            if cancelled is not None and cancelled():
                stop('cancelled')
                break
            with guard:
                failed = bool(errors)
                drained = eof == {'stdout', 'stderr'}
            if failed:
                stop('stream-read-error')
                break
            code = process.poll()
            if code is not None and drained and not owned_active():
                state['completion_status'] = 'complete' if code >= 0 else 'unknown'
                break
            if time.monotonic() - last_checkpoint >= .1:
                persist()
                last_checkpoint = time.monotonic()
            time.sleep(.01)
    except Exception as error:
        state['observer_error'] = type(error).__name__ + ': ' + str(error)
        if process is not None:
            try:
                if job is not None:
                    stop('observer-error')
                elif os.name == 'nt':
                    # Assignment may have failed while the new child is still
                    # suspended: it cannot have spawned any descendants.
                    process.kill()
                    process.wait(timeout=5)
                    state['termination'] = {'reason': 'launch-setup-error', 'imposed': True}
                else:
                    stop('observer-error')
            except (OSError, subprocess.TimeoutExpired) as cleanup_error:
                state['termination']['cleanup_error'] = str(cleanup_error)
    finally:
        for thread in threads:
            thread.join(timeout=1)
        if process is not None:
            code = process.poll()
            state['exit_code'] = code if code is not None and code >= 0 else None
            if code is not None and code < 0:
                state['signal'] = signal.Signals(-code).name
            if job is not None:
                try:
                    remaining = job.accounting()
                    state['owned_group'] = remaining
                    if remaining['active_processes']:
                        state['completion_status'] = 'unknown'
                        state['termination'].update(reason='owned-group-close', imposed=True)
                except OSError as error:
                    state['completion_status'] = 'unknown'
                    state['termination']['accounting_error'] = str(error)
                finally:
                    job.close()
            if not threads:
                process.stdout.close()
                process.stderr.close()
        with guard:
            if errors or exceeded.is_set() or eof != {'stdout', 'stderr'} or state['termination'].get('imposed'):
                state['completion_status'] = 'unknown'
        state['phase'] = 'complete' if state['completion_status'] == 'complete' else 'partial'
    return persist()


def inspect(source, parameters, output, expected_sha256):
    command = parameters.get('command')
    if not isinstance(command, str) or not command or any(c in command for c in '\r\n\0'):
        raise ValueError('A nonempty literal command line is required')
    executable = rizin.engine()
    if executable is None:
        raise ValueError('Install free Rizin or set THESEUS_RIZIN')
    source = Path(source).resolve()
    artifact = _file(source)
    if artifact.get('state') != 'file' or artifact['sha256'] != expected_sha256:
        raise ValueError('Artifact changed before command admission')
    folder = Path(output).parent
    if (folder / 'rizin-context.json').exists():
        raise FileExistsError('This command already started; read its retained observation')
    identity = _file(Path(executable))
    if identity.get('state') != 'file':
        raise ValueError('The command engine identity is unavailable')
    cwd = str(Path.cwd().resolve())
    argv = [executable, '-N', '-q', '-c', command, str(source)]
    context = {'format': 'vitruvius.rizin-command/1', 'command': command, 'argv': argv, 'cwd': cwd,
        'started_at': datetime.now(timezone.utc).isoformat(),
        'engine': {'executable': executable, 'identity': identity},
        'artifact': {'path': str(source), 'sha256': expected_sha256, 'bytes': artifact['bytes']},
        'combined_output_limit': OUTPUT_LIMIT,
        'limitations': ['Raw command output is authoritative; no stable normalized or command-specific JSON format is claimed.',
            'The literal command and retained plugins may execute code, mutate files, use the network and read external inputs whose identities are not bound here.',
            'Endpoint artifact hashes do not rule out transient changes or describe external effects.',
            'Settings/scripts are suppressed with -N; plugins and the ambient environment remain available.',
            'Stream collection order does not establish a temporal order between stdout and stderr.',
            'Ownership covers normal Windows Job descendants or the new POSIX process group; external brokers and detached groups are not covered.',
            'An interrupted observation is never replayed and cannot undo command effects.']}
    process_capture._write(folder / 'rizin-context.json', context)
    process_capture._write(folder / 'rizin-observer.json', process_capture._identity(os.getpid()))
    value = _capture(argv, cwd, folder, context)
    # Publish the streams before observing a possibly removed/changed artifact.
    after = _file(source)
    value['artifact_after'] = after
    value['artifact_sha256_after'] = after.get('sha256') if after.get('state') == 'file' else None
    value['artifact_changed'] = None if value['artifact_sha256_after'] is None else value['artifact_sha256_after'] != expected_sha256
    process_capture._write(folder / 'rizin-latest.json', _document(context, value))
    return value


def recording(folder, interrupted=False):
    path = Path(folder) / 'rizin-latest.json'
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding='utf8'))
    value = document['result']
    for channel in ['stdout', 'stderr']:
        stream = value[channel]
        raw = base64.b64decode(stream['base64'], validate=True)
        if len(raw) != stream['bytes'] or hashlib.sha256(raw).hexdigest() != stream['sha256']:
            raise ValueError('Retained command stream identity changed')
    if interrupted and value['phase'] != 'complete':
        value['completion_status'] = 'unknown'
        value['termination'] = {**value['termination'], 'observer_interrupted': True}
    return document


def record_worker(folder, process, command):
    identity = process_capture._identity(process.pid)
    if identity['command'] != command:
        raise ValueError('The launched command observer identity changed')
    process_capture._write(Path(folder) / 'rizin-worker.json', identity)
    return identity


def stop_interrupted_worker(folder):
    folder = Path(folder)
    receipts = {}
    for label in ['worker', 'observer']:
        observer_path = folder / ('rizin-' + label + '.json')
        if observer_path.is_file():
            identity = json.loads(observer_path.read_text(encoding='utf8'))
            if str(Path(__file__).with_name('structured.py').resolve()) not in identity['command'] or str(folder / 'request.json') not in identity['command']:
                raise ValueError('Recorded observer is not bound to this command job')
            receipts[label] = process_capture._stop(identity)
    child_path = folder / 'rizin-process.json'
    if child_path.is_file():
        context = json.loads((folder / 'rizin-context.json').read_text(encoding='utf8'))
        identity = json.loads(child_path.read_text(encoding='utf8'))
        if identity['command'] != context['argv']:
            raise ValueError('Recorded command process is not bound to this job')
        receipts['command'] = process_capture._stop(identity)
    return receipts
