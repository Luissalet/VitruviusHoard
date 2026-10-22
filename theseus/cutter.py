"""Live native editor bridges and retained command observations."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json as jsonlib
import os
from pathlib import Path
import socket
import sqlite3
import stat
import sys
import uuid

from .store import identifier

PLUGIN = Path(__file__).resolve().parents[1] / 'software_native/engine/bridge/cutter/vitruvius_bridge.py'
SESSION_FIELDS = ('session_id', 'pid', 'document_generation', 'current_file', 'cutter_version', 'identity_status')
RESULT_FIELDS = ('command', 'output', 'execution_state', 'error', 'message', 'output_truncated',
                 'cutter_version', 'current_file', 'document_generation', 'identity_status')


def bridge_directory():
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share')))
    return Path(os.environ.get('THESEUS_CUTTER_BRIDGE_DIR', str(base / 'Vitruvius/cutter-bridge')))


def validate_command(session_id, expected_generation, command, json=False):
    try:
        session_id = str(uuid.UUID(session_id))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError('Select a valid live editor session UUID') from error
    if type(expected_generation) is not int or expected_generation < 0:
        raise ValueError('expected_generation must be a nonnegative integer')
    if not isinstance(command, str) or not command or '\r' in command or '\n' in command:
        raise ValueError('A single Rizin command line is required')
    if type(json) is not bool:
        raise ValueError('json must be a boolean')
    return session_id


class ExchangeError(Exception):
    def __init__(self, sent, cause):
        self.sent = sent
        super().__init__(type(cause).__name__ + ': bridge response unavailable')


class CutterBridge:
    def __init__(self, store=None, directory=None, timeout=30):
        self.store = store
        self.directory = Path(directory) if directory is not None else bridge_directory()
        self.timeout = timeout

    def _descriptor(self, path):
        if path.stat().st_size > 65536:
            raise ValueError('Bridge descriptor exceeds its declared byte budget')
        value = jsonlib.loads(path.read_text(encoding='utf-8'))
        session_id = str(uuid.UUID(value['session_id']))
        if path.stem != session_id or value.get('protocol') != 1:
            raise ValueError('Unsupported bridge descriptor')
        if type(value['pid']) is not int or value['pid'] <= 0:
            raise ValueError('Invalid bridge process')
        if type(value['port']) is not int or not 0 < value['port'] < 65536:
            raise ValueError('Invalid loopback port')
        if not isinstance(value['token'], str) or len(value['token']) < 32:
            raise ValueError('Invalid bridge credential')
        return value

    def _exchange(self, descriptor, method, parameters, timeout):
        request_id = uuid.uuid4().hex
        request = {'request_id': request_id, 'session_id': descriptor['session_id'],
                   'token': descriptor['token'], 'method': method, 'parameters': parameters}
        sent = False
        try:
            with socket.create_connection(('127.0.0.1', descriptor['port']), timeout=timeout) as connection:
                # sendall can fail after sending a prefix. Completion is already
                # uncertain at that point; never automatically resend a command.
                sent = True
                connection.sendall((jsonlib.dumps(request, ensure_ascii=False) + '\n').encode('utf-8'))
                with connection.makefile('rb') as stream:
                    raw = stream.readline()
                response = jsonlib.loads(raw)
                if (not isinstance(response, dict) or response.get('request_id') != request_id or response.get('session_id') != descriptor['session_id']
                        or response.get('pid') != descriptor['pid']):
                    raise ValueError('The bridge response belongs to another request or process')
                return response['result']
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ExchangeError(sent, error) from error

    def _probe(self, path):
        try:
            descriptor = self._descriptor(path)
            value = self._exchange(descriptor, 'status', {}, 1)
            if (value['session_id'] != descriptor['session_id'] or value['pid'] != descriptor['pid']
                    or type(value['document_generation']) is not int or value['document_generation'] < 0
                    or value['identity_status'] != 'partial'):
                return None
            return {key: value[key] for key in SESSION_FIELDS}
        except (OSError, ValueError, KeyError, TypeError, ExchangeError):
            return None

    def discover(self):
        result = {'sessions': [], 'bridge_directory': str(self.directory),
                  'discovery_status': 'no_live_bridge_found', 'bridge_directory_security': 'not_checked'}
        try:
            mode = self.directory.stat().st_mode
            if not stat.S_ISDIR(mode):
                raise OSError('Not a directory')
            if os.name == 'nt':
                result['bridge_directory_security'] = 'unverified_platform_acl'
            elif mode & 0o077:
                result.update(discovery_status='bridge_directory_insecure', bridge_directory_security='not_private')
                return result
            else:
                result['bridge_directory_security'] = 'private_verified'
            paths = []
            for path in self.directory.glob('*.json'):
                paths.append(path)
                if len(paths) > 256:
                    result['discovery_status'] = 'bridge_directory_capacity_exceeded'
                    return result
        except FileNotFoundError:
            return result
        except OSError:
            result['discovery_status'] = 'bridge_directory_unavailable'
            return result
        with ThreadPoolExecutor(max_workers=8) as pool:
            result['sessions'] = [row for row in pool.map(self._probe, sorted(paths)) if row is not None]
        if result['sessions']:
            result['discovery_status'] = 'sessions_found'
        return result

    def execute(self, session_id, expected_generation, command, json=False):
        session_id = validate_command(session_id, expected_generation, command, json)
        fallback = {'command': command, 'output': None, 'execution_state': 'not_started',
                    'error': None, 'message': None, 'output_truncated': False, 'cutter_version': None,
                    'current_file': None, 'document_generation': expected_generation, 'identity_status': 'partial'}
        try:
            descriptor = self._descriptor(self.directory / (session_id + '.json'))
        except (OSError, ValueError, KeyError, TypeError):
            return {**fallback, 'error': 'The selected live bridge descriptor is unavailable',
                    'message': 'No command was sent. Generation is the caller\'s last observation.'}
        try:
            value = self._exchange(descriptor, 'command', {'expected_generation': expected_generation,
                                   'command': command, 'json': json}, self.timeout)
            if (value['command'] != command or value['execution_state'] not in {'not_started', 'complete', 'failed', 'unknown'}
                    or type(value['document_generation']) is not int or value['document_generation'] < 0
                    or value['identity_status'] != 'partial' or type(value['output_truncated']) is not bool
                    or any(value[key] is not None and not isinstance(value[key], str)
                           for key in ('error', 'message', 'cutter_version', 'current_file'))):
                raise ExchangeError(True, ValueError('Invalid command observation'))
            return {key: value[key] for key in RESULT_FIELDS}
        except (ExchangeError, KeyError, TypeError) as error:
            uncertain = not isinstance(error, ExchangeError) or error.sent
            return {**fallback, 'execution_state': 'unknown' if uncertain else 'not_started', 'error': str(error),
                    'message': 'Do not retry automatically. The command may still have effects.' if uncertain else
                               'The connection failed before sending. Generation is the caller\'s last observation.'}

    def _retain(self, project_id, job_id, result, value):
        folder = self.store.directory / 'analyses' / job_id
        output = folder / 'analysis.json'
        document = {'operation': 'cutter.command', 'artifact_sha256': None,
                    'runtime': sys.version.split()[0], 'result': value}
        raw = (jsonlib.dumps(document, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        output.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        result.update(analysis_file=str(output), analysis_sha256=digest, artifact_sha256=digest,
                      sections=self.store.index_analysis(job_id, value),
                      observation_status=value['execution_state'], error=value['error'])
        state = {'complete': 'finished', 'not_started': 'failed', 'failed': 'failed', 'unknown': 'interrupted'}[value['execution_state']]
        self.store.save_job(project_id, job_id, state, result)

    def command(self, project_id, session_id, expected_generation, command, json=False):
        session_id = validate_command(session_id, expected_generation, command, json)
        self.store.project(project_id)
        job_id = identifier()
        folder = self.store.directory / 'analyses' / job_id
        folder.mkdir(parents=True)
        result = {'kind': 'runtime_analysis', 'operation': 'cutter.command', 'title': 'Cutter · Orden',
                  'artifact_name': 'Sesión ' + session_id[:8], 'folder': str(folder),
                  'source_identity': {'kind': 'cutter', 'session_id': session_id, 'identity_status': 'partial'},
                  'request': {'session_id': session_id, 'expected_generation': expected_generation,
                              'command': command, 'json': json}}
        self.store.save_job(project_id, job_id, 'running', result)
        value = self.execute(session_id, expected_generation, command, json)
        try:
            self._retain(project_id, job_id, result, value)
        except (OSError, sqlite3.Error) as error:
            # Effects already happened. Return the observed completion even if
            # local retention fails; a restart must never replay this request.
            return {**value, 'job_id': job_id,
                    'retention_error': type(error).__name__ + ': the observation could not be fully retained',
                    'message': 'Do not retry automatically. Retention failed after the bridge response.'}
        return {**value, 'job_id': job_id}

    def recover(self):
        for project in self.store.projects():
            for job in self.store.items('jobs', project['id']):
                result = job['result']
                if (job['state'] not in {'queued', 'running', 'interrupted'} or result.get('operation') != 'cutter.command'
                        or result.get('analysis_file')):
                    continue
                request = result['request']
                value = {'command': request['command'], 'output': None, 'execution_state': 'unknown',
                         'error': 'The host stopped before recording the command response',
                         'message': 'Do not retry automatically; the bridge command may have had effects.',
                         'output_truncated': False, 'cutter_version': None, 'current_file': None,
                         'document_generation': request['expected_generation'], 'identity_status': 'partial'}
                self._retain(project['id'], job['id'], result, value)
