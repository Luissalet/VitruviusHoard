"""Offline signal recordings through the installed generic sigrok decoder engine."""
import base64
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess


def engine():
    configured = os.environ.get('THESEUS_SIGROK')
    candidates = [configured] if configured else [shutil.which('sigrok-cli'), 'D:/LocalAI/tools/sigrok779/portable-nightly/sigrok-cli.exe']
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), None)


PAGING = {'query': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 0},
          'limit': {'type': ['integer','null'], 'minimum': 0}}
OPERATIONS = [
    {'name': 'signal.decoders', 'title': 'Señales · Decodificadores instalados', 'worker': 'python',
     'description': 'Descubre decodificadores sigrok o consulta la ayuda de uno: canales, opciones y clases. Conserva diagnósticos; no escanea ni adquiere hardware.',
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'properties': {
         **PAGING, 'decoder': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]+$'}}}},
    {'name': 'signal.decode', 'title': 'Señales · Decodificar grabación', 'worker': 'python',
     'description': 'Decodifica un archivo local con pila/canales/opciones explícitos. Conserva texto, rangos de muestras, diagnósticos e identidades; la paginación no acorta la decodificación.',
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['decoder_stack'], 'properties': {
         'decoder_stack': {'type': 'array','minItems': 1,'items': {'type':'string','minLength':1}},
         'input_format': {'type':'string','minLength':1}, 'channels': {'type':'string','minLength':1},
         'annotations': {'type':'string','minLength':1},
         'line_offset': {'type':'integer','minimum':0}, 'line_limit': {'type':['integer','null'],'minimum':0}}}},
]


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def observed(command):
    reply = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL)
    return {'command': command, 'exit_code': reply.returncode,
        'stdout': reply.stdout.decode('utf8', errors='replace'), 'stderr': reply.stderr.decode('utf8', errors='replace'),
        'stdout_base64': base64.b64encode(reply.stdout).decode('ascii'),
        'stderr_base64': base64.b64encode(reply.stderr).decode('ascii')}


def inspect_signal(source, operation, parameters, output, source_sha256):
    executable = engine()
    if not executable:
        raise ValueError('Install sigrok-cli or configure THESEUS_SIGROK with its executable path')
    identity = {'path': executable, 'sha256': sha(executable), 'version': observed([executable, '--version'])}
    if identity['version']['exit_code']:
        raise ValueError('The installed signal decoder did not report its version: '+identity['version']['stderr'])
    if operation == 'signal.decoders':
        decoder = parameters.get('decoder')
        command = [executable, '--protocol-decoders', decoder, '--show'] if decoder else [executable, '--list-supported']
        result = observed(command)
        full_lines = result['stdout'].splitlines()
        if not decoder:
            try:
                first = full_lines.index('Supported protocol decoders:') + 1
            except ValueError:
                return {'status': 'unrecognized-output', 'engine': identity, 'observation': result,
                    'lines': [], 'coverage': {'examined_lines': len(full_lines), 'decoder_count': None},
                    'limitations': ['The installed tool output did not identify its protocol decoder section; decoder availability remains unknown.']}
            examined = [{'line_number': i+1, 'text': text, **({'decoder': match.group(1), 'description': match.group(2)}
                if (match := re.match(r'^\s+(\S+)\s+(.+)$',text)) else {})}
                for i,text in enumerate(full_lines) if i >= first and text.strip()]
        else:
            examined = [{'line_number': i+1,'text': text} for i,text in enumerate(full_lines)]
        query = parameters.get('query','').casefold()
        matches = [row for row in examined if query in row['text'].casefold()]
        offset, limit = parameters.get('offset',0), parameters.get('limit',50)
        selected = matches[offset:] if limit is None else matches[offset:offset+limit]
        return {'status': 'available' if result['exit_code']==0 else 'decoder-error', 'engine': identity,
            'decoder': decoder, 'lines': selected, 'observation': result,
            'coverage': {'examined_lines': len(examined), 'matching_lines': len(matches), 'offset': offset,
                         'returned': len(selected), 'has_more': offset+len(selected)<len(matches)},
            'limitations': ['Discovery does not scan hardware. stderr may identify decoders that failed to load; a listing is not a decoding test.']}
    snapshot = output.parent / ('signal-input'+source.suffix)
    try:
        shutil.copyfile(source,snapshot)
        if sha(snapshot) != source_sha256 or sha(source) != source_sha256:
            raise ValueError('Signal recording changed while capturing its bytes')
        command = [executable, '--input-file', str(snapshot), '--protocol-decoders', ','.join(parameters['decoder_stack']),
                   '--protocol-decoder-samplenum']
        for key,flag in [('input_format','--input-format'),('channels','--channels'),('annotations','--protocol-decoder-annotations')]:
            if key in parameters:
                command.extend([flag,parameters[key]])
        result = observed(command)
    finally:
        snapshot.unlink(missing_ok=True)
    lines = []
    for index,text in enumerate(result['stdout'].splitlines()):
        row = {'line_number': index+1,'text': text}
        if match := re.match(r'^\s*(\d+)-(\d+)\s+([^:]+):\s?(.*)$',text):
            row.update(sample_start=match.group(1),sample_end_display=match.group(2),decoder_alias=match.group(3),annotation=match.group(4))
        lines.append(row)
    offset,limit = parameters.get('line_offset',0),parameters.get('line_limit',50)
    selected = lines[offset:] if limit is None else lines[offset:offset+limit]
    return {'status': 'decoded' if result['exit_code']==0 else 'decoder-error', 'engine': identity,
        'selection': parameters, 'lines': selected, 'observation': result, 'snapshot_sha256': source_sha256,
        'coverage': {'output_lines': len(lines), 'line_offset': offset, 'returned_lines': len(selected),
                     'has_more': offset+len(selected)<len(lines), 'decode_shortened_by_paging': False},
        'limitations': ['Line paging selects display output after complete decoding; lines are not annotation or sample counts.',
            'Sample ranges are the decoder text, with its endpoint convention. Annotations are decoder interpretations of the recording.',
            'A decoder-error retains its full output and diagnostics; it does not establish absence of the protocol. No hardware acquisition was performed.']}
