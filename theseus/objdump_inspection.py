"""Explicit GNU binary-reader observations using the retained process recorder."""
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil

try:
    from . import process_capture
except ImportError:
    import process_capture

COMMANDS = {'file_headers': '--file-headers', 'section_headers': '--section-headers',
            'symbols': '--syms', 'relocations': '--reloc', 'dwarf': '--dwarf',
            'disassemble': '--disassemble', 'disassemble_all': '--disassemble-all',
            'architectures': '--info'}
OPERATIONS = [{'name': 'binary.objdump', 'title': 'Binarios · Inspección GNU', 'worker': 'python',
    'description': 'Consulta cabeceras, símbolos, relocaciones, DWARF o desensamblado con GNU objdump. Conserva salida original y diagnósticos completos, hashes y estado de finalización; no ejecuta el artefacto.',
    'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['facet'],
        'properties': {'facet': {'enum': [key for key in COMMANDS if key != 'architectures']},
                       'follow_debug_links': {'type': 'boolean'}}},
    'example': {'facet': 'file_headers'}}]


def engine():
    candidates = [{'path': os.environ.get('THESEUS_OBJDUMP'), 'source': 'THESEUS_OBJDUMP'},
                  {'path': shutil.which('objdump'), 'source': 'PATH'},
                  {'path': 'D:/LocalAI/tools/binutils1076/ucrt64/bin/objdump.exe', 'source': 'bundled-default'}]
    chosen = None
    for row in candidates:
        row['exists'] = bool(row['path'] and Path(row['path']).is_file())
        row['selected'] = chosen is None and row['exists']
        if row['selected']:
            chosen = row
    return {'available': chosen is not None, 'path': str(Path(chosen['path']).resolve()) if chosen else None,
            'source': chosen['source'] if chosen else None, 'candidates': candidates}


def _write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    temporary.replace(path)


def _stream(value):
    raw = base64.b64decode(value['base64'], validate=True)
    if len(raw) != value['bytes'] or hashlib.sha256(raw).hexdigest() != value['sha256']:
        raise ValueError('Retained reader stream no longer matches its byte identity')
    try:
        text = raw.decode('utf8')
        invalid = False
    except UnicodeDecodeError:
        text, invalid = raw.decode('utf8', errors='replace'), True
    return {**value, 'text': text, 'invalid_utf8_replaced': invalid}


def normalize(context, capture):
    observed = {row['label']: row for row in capture.get('files', [])}
    artifact = context['artifact']
    after = observed.get('artifact', {}).get('after', {})
    before = observed.get('artifact', {}).get('before', {})
    after_hash = after.get('sha256') if after.get('state') == 'file' else None
    changed = None if artifact is None or after_hash is None else after_hash != artifact['sha256']
    if artifact is not None and before.get('sha256') not in {None, artifact['sha256']}:
        changed = True
    complete = capture.get('status') == 'complete' and capture.get('stream_complete') is True
    code = capture['process'].get('exit_code')
    return {'format': 'vitruvius.binary-reader-observation/1', 'operation': context['operation'],
            'started_at': context['started_at'],
            'engine': context['engine'], 'command': capture['target']['argv'],
            'artifact': artifact, 'artifact_sha256_after': after_hash, 'artifact_changed': changed,
            'follow_debug_links_requested': context['follow_debug_links'],
            'follow_debug_links_effective': context['operation'] == 'dwarf' and context['follow_debug_links'],
            'stdout': _stream(capture['stdout']), 'stderr': _stream(capture['stderr']),
            'exit_code': code, 'signal': int(-code) if os.name != 'nt' and isinstance(code, int) and code < 0 else None,
            'completion_status': 'complete' if complete else 'unknown',
            'output_truncated': False, 'stream_complete': capture.get('stream_complete', False),
            'process_observation': capture, 'target_executed': False,
            'limitations': [
                'Raw observed output is authoritative; no stable normalized GNU text format is claimed.',
                'All collected stream bytes are retained without a delivery cap; incomplete collection remains unknown.',
                'Endpoint file hashes do not rule out transient concurrent changes during the reader invocation.',
                'Declared debug-link following can read external files whose identities are not bound here.',
                'Reader executable identity does not bind every dynamically loaded library or ambient input.',
                'Advertised BFD targets are subjectless declarations, not successful inspection of an artifact.']}


def inspect(operation, folder, source=None, expected_sha256=None, follow_debug_links=False, cancelled=None):
    if operation not in COMMANDS or type(follow_debug_links) is not bool:
        raise ValueError('Select a known binary-reader operation and a boolean debug-link option')
    if operation == 'architectures' and (source is not None or expected_sha256 is not None or follow_debug_links):
        raise ValueError('BFD discovery has no artifact or debug-link selector')
    if operation != 'architectures' and source is None:
        raise ValueError('An artifact is required for this binary-reader operation')
    selected = engine()
    if not selected['available']:
        raise ValueError('GNU objdump is unavailable; configure THESEUS_OBJDUMP or install the free binary reader')
    reader = process_capture._file(Path(selected['path']), include_content=False)
    if reader.get('state') != 'file':
        raise ValueError('Selected binary reader identity is unavailable or unstable')
    selected['identity'] = reader
    artifact = None
    if source is not None:
        source = Path(source).resolve()
        observed = process_capture._file(source, include_content=False)
        if observed.get('state') != 'file' or expected_sha256 is not None and observed['sha256'] != expected_sha256:
            raise ValueError('Artifact changed or has no stable readable file identity')
        artifact = {'path': str(source), 'sha256': observed['sha256'], 'bytes': observed['bytes']}
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    context_file = folder / 'objdump-context.json'
    if context_file.exists():
        raise FileExistsError('This binary inspection already started; read its retained observation')
    context = {'operation': operation, 'engine': selected, 'artifact': artifact, 'follow_debug_links': follow_debug_links,
               'started_at': datetime.now(timezone.utc).isoformat()}
    command = [selected['path'], COMMANDS[operation]]
    if operation == 'dwarf':
        command += ['--dwarf=follow-links' if follow_debug_links else '--dwarf=no-follow-links',
                    '--dwarf=do-not-use-debuginfod']
    if source is not None:
        command += ['--', str(source)]
    parameters = {'argv': command, 'mode': 'pipes', 'cwd': str(folder.resolve()),
                  'environment': {'DEBUGINFOD_URLS': '', 'LC_ALL': 'C'},
                  'steps': [{'kind': 'close_stdin'}],
                  'files': [{'label': 'reader', 'path': selected['path']}] +
                           ([{'label': 'artifact', 'path': str(source)}] if source else [])}
    _write(context_file, context)
    _write(folder / 'objdump-observer.json', process_capture._identity(os.getpid()))
    capture = process_capture.capture_process(parameters, folder / 'objdump-capture', cancelled, include_file_content=False)
    return normalize(context, capture)


def recording(folder, interrupted=False):
    """Read only retained JSON and stream bytes; never inspect an original path."""
    folder = Path(folder)
    source = process_capture.latest(folder / 'objdump-capture')
    if source is None or not (folder / 'objdump-context.json').is_file():
        return None
    if interrupted:
        source = process_capture.freeze_recording(folder / 'objdump-capture')
    context = json.loads((folder / 'objdump-context.json').read_text(encoding='utf8'))
    capture = json.loads(source.read_text(encoding='utf8'))['result']
    return normalize(context, capture)


def stop_interrupted_worker(folder):
    folder = Path(folder)
    path = folder / 'objdump-observer.json'
    if not path.is_file():
        return {'owned_process_stopped': False, 'reason': 'observer-identity-unavailable'}
    identity = json.loads(path.read_text(encoding='utf8'))
    command = identity.get('command', [])
    if str(Path(__file__).with_name('structured.py').resolve()) not in command or str(folder / 'request.json') not in command:
        return {'owned_process_stopped': False, 'reason': 'observer-command-not-bound-to-job'}
    observer = process_capture._stop(identity)
    owner = folder / 'objdump-capture' / 'process-owner.json'
    reader = None
    if owner.is_file():
        child = json.loads(owner.read_text(encoding='utf8'))
        source = process_capture.latest(folder / 'objdump-capture')
        recorded = json.loads(source.read_text(encoding='utf8'))['result'] if source else None
        if recorded is None or child.get('command') != recorded['target']['argv']:
            return {'owned_process_stopped': False, 'reason': 'reader-command-not-bound-to-recording', 'observer': observer}
        reader = process_capture._stop(child)
    return {'owned_process_stopped': observer['owned_process_stopped'] and (reader is None or reader['owned_process_stopped']),
            'observer': observer, 'reader': reader}
