"""Native editor bridge. Install this file in the chosen Python plugin folder."""
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import uuid

import cutter
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication


class Bridge(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.session_id = str(uuid.uuid4())
        self.token = secrets.token_urlsafe(40)
        self.generation = 0
        self.identity = None
        self.current_file = None
        self.version = str(cutter.version())
        self.clients = {}
        self.closed = False
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share')))
        self.directory = Path(os.environ.get('THESEUS_CUTTER_BRIDGE_DIR', str(base / 'Vitruvius/cutter-bridge')))
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != 'nt' and self.directory.stat().st_mode & 0o077:
            raise RuntimeError('The bridge credential directory is not private')
        self.path = self.directory / (self.session_id + '.json')
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(16)
        self.listener.setblocking(False)
        self._observe()
        self._publish()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(20)
        cutter.core().refreshAll.connect(self.refreshed)
        parent.aboutToQuit.connect(self.close)

    def _publish(self):
        value = {'protocol': 1, 'session_id': self.session_id, 'pid': os.getpid(),
                 'port': self.listener.getsockname()[1], 'token': self.token,
                 'document_generation': self.generation}
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value), encoding='utf-8')
        os.replace(temporary, self.path)

    def _observe(self):
        values = []
        for command in ('ol.j', 'olj', 'oblj'):
            text = cutter.cmd(command)
            try:
                values.append(json.loads(text) if text else None)
            except (ValueError, TypeError):
                values.append(None)
        identity = json.dumps(values, sort_keys=True)
        if self.identity is not None and identity != self.identity:
            self.generation += 1
            self._publish()
        self.identity = identity
        current = values[0]
        self.current_file = current.get('uri') if isinstance(current, dict) and isinstance(current.get('uri'), str) else None

    def refreshed(self, *args):
        self.generation += 1
        self._observe()
        self._publish()

    def status(self):
        self._observe()
        return {'session_id': self.session_id, 'pid': os.getpid(), 'document_generation': self.generation,
                'current_file': self.current_file, 'cutter_version': self.version, 'identity_status': 'partial'}

    def command(self, parameters):
        self._observe()
        command = parameters.get('command')
        expected = parameters.get('expected_generation')
        as_json = parameters.get('json', False)
        value = {'command': command if isinstance(command, str) else '', 'output': None,
                 'execution_state': 'not_started', 'error': None, 'message': None,
                 'output_truncated': False, 'cutter_version': self.version, 'current_file': self.current_file,
                 'document_generation': self.generation, 'identity_status': 'partial'}
        if (type(expected) is not int or expected < 0 or type(as_json) is not bool
                or not isinstance(command, str) or not command or '\r' in command or '\n' in command):
            return {**value, 'error': 'Invalid command line, generation or JSON selection'}
        if expected != self.generation:
            return {**value, 'error': 'The observed document generation changed; refresh the session before deciding again'}
        try:
            output = cutter.cmd(command)
            if not isinstance(output, str):
                raise TypeError('The editor command API did not return text')
            value.update(output=output, execution_state='complete',
                         message='The engine call returned. Text alone does not establish semantic success or undo effects.')
            if as_json:
                try:
                    value['output'] = json.loads(output)
                except ValueError as error:
                    value.update(execution_state='failed', error='The returned text is not JSON: ' + str(error),
                                 message='The engine returned; the original text is retained. Do not repeat the command automatically.')
        except Exception as error:
            value.update(execution_state='unknown', error=type(error).__name__ + ': ' + str(error),
                         message='The engine call did not yield a complete response. Do not retry automatically.')
        finally:
            self.generation += 1
            self._observe()
            self._publish()
        value.update(current_file=self.current_file, document_generation=self.generation)
        return value

    def _reply(self, raw):
        request = json.loads(raw)
        if (request.get('session_id') != self.session_id or not isinstance(request.get('token'), str)
                or not hmac.compare_digest(request['token'], self.token)):
            raise ValueError('Bridge authentication failed')
        method = request.get('method')
        if method == 'status':
            result = self.status()
        elif method == 'command':
            result = self.command(request.get('parameters', {}))
        else:
            raise ValueError('Unknown bridge method')
        return {'request_id': request['request_id'], 'session_id': self.session_id, 'pid': os.getpid(), 'result': result}

    def poll(self):
        if self.closed:
            return
        while True:
            try:
                peer, _ = self.listener.accept()
                peer.setblocking(False)
                self.clients[peer] = {'input': bytearray(), 'output': None}
            except BlockingIOError:
                break
        for peer, state in list(self.clients.items()):
            try:
                if state['output'] is None:
                    try:
                        part = peer.recv(65536)
                    except BlockingIOError:
                        continue
                    if not part:
                        raise ConnectionError('Client closed')
                    state['input'].extend(part)
                    if b'\n' not in state['input']:
                        continue
                    try:
                        reply = self._reply(bytes(state['input']).split(b'\n', 1)[0])
                    except Exception:
                        reply = {'error': 'The bridge could not admit this request'}
                    state['output'] = memoryview((json.dumps(reply, ensure_ascii=False) + '\n').encode('utf-8'))
                try:
                    sent = peer.send(state['output'])
                except BlockingIOError:
                    continue
                state['output'] = state['output'][sent:]
                if not state['output']:
                    peer.close()
                    del self.clients[peer]
            except OSError:
                peer.close()
                del self.clients[peer]

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        for peer in self.clients:
            peer.close()
        self.clients.clear()
        self.listener.close()
        try:
            current = json.loads(self.path.read_text(encoding='utf-8'))
            if current.get('session_id') == self.session_id and current.get('token') == self.token:
                self.path.unlink()
        except (OSError, ValueError):
            pass


_bridge = None


def start_bridge():
    global _bridge
    app = QApplication.instance()
    if _bridge is None and app is not None:
        _bridge = Bridge(app)
    return _bridge


class InspectionBridge(cutter.CutterPlugin):
    name = 'Vitruvius inspection bridge'
    description = 'Live native command observations'
    author = 'Luissalet'
    version = '1'

    def setupPlugin(self):
        start_bridge()

    def setupInterface(self, main):
        start_bridge()

    def terminate(self):
        if _bridge is not None:
            _bridge.close()


def create_cutter_plugin():
    start_bridge()
    return InspectionBridge()


# Some shipped Python loaders import valid plugins but reject their binding
# instance before setupPlugin is invoked. The same maintained module can serve
# its bridge without relying on a successful registration of a dock widget.
start_bridge()
