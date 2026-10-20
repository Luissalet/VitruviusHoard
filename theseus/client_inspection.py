"""Explicit decoder version observations, independent of a target artifact."""
import base64
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from . import android, packets


def fingerprint(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    fields = ('st_size', 'st_mtime_ns', 'st_ino', 'st_dev')
    if any(getattr(before, key) != getattr(after, key) for key in fields):
        raise ValueError('Selected decoder file changed while observing its identity')
    return {'path': str(path), 'bytes': after.st_size, 'sha256': digest.hexdigest()}


def candidate(path, source):
    return {'path': str(path) if path else None, 'source': source}


def selected(path, candidates):
    chosen = str(Path(path).resolve()) if path else None
    found = False
    for row in candidates:
        row['exists'] = bool(row['path'] and Path(row['path']).is_file())
        row['selected'] = bool(not found and chosen and row['exists'] and str(Path(row['path']).resolve()) == chosen)
        found = found or row['selected']
    first = next((row for row in candidates if row['selected']), None)
    return {'path': chosen, 'source': first['source'] if first else None, 'candidates': candidates}


def selection(family):
    if family == 'objdump':
        from .objdump_inspection import engine
        tool = engine()
        return [('objdump', selected(tool['path'], tool['candidates']))]
    if family == 'apktool':
        tools = android.engines()
        home_source = 'THESEUS_JAVA_HOME' if 'THESEUS_JAVA_HOME' in os.environ else 'JAVA_HOME' if 'JAVA_HOME' in os.environ else 'bundled-default'
        home = os.environ.get('THESEUS_JAVA_HOME', os.environ.get('JAVA_HOME', 'D:/LocalAI/tools/jdk21/jdk-21.0.12.1+1'))
        java_candidates = [candidate(Path(home)/'bin'/('java.exe' if os.name == 'nt' else 'java'), home_source), candidate(shutil.which('java'), 'PATH')]
        jar = os.environ.get('THESEUS_APKTOOL', 'D:/LocalAI/tools/apktool779/apktool_3.0.3.jar')
        return [('java', selected(tools['java'], java_candidates)),
                ('apktool', selected(tools['apktool'], [candidate(jar, 'THESEUS_APKTOOL' if 'THESEUS_APKTOOL' in os.environ else 'bundled-default')]))]
    if family == 'pcap':
        tshark = packets.engine()
        tshark_candidates = [candidate(os.environ.get('THESEUS_TSHARK'), 'THESEUS_TSHARK'), candidate(shutil.which('tshark'), 'PATH'),
            candidate('D:/LocalAI/tools/wireshark779/portable/App/Wireshark/tshark.exe', 'bundled-default'), candidate('C:/Program Files/Wireshark/tshark.exe', 'system-default')]
        suffix = '.exe' if os.name == 'nt' else ''
        cap_candidates = [candidate(os.environ.get('THESEUS_CAPINFOS'), 'THESEUS_CAPINFOS'),
            candidate(Path(tshark).with_name('capinfos'+suffix) if tshark else None, 'selected-tshark-directory'),
            candidate(shutil.which('capinfos'), 'PATH'), candidate('C:/Program Files/Wireshark/capinfos.exe', 'system-default')]
        capinfos = next((row['path'] for row in cap_candidates if row['path'] and Path(row['path']).is_file()), None)
        return [('tshark', selected(tshark, tshark_candidates)), ('capinfos', selected(capinfos, cap_candidates))]
    raise ValueError('Select apktool, pcap or objdump')


def output(raw):
    raw = raw or b''
    return {'text': raw.decode('utf8', errors='replace'), 'bytes': len(raw),
            'base64': base64.b64encode(raw).decode('ascii'), 'sha256': hashlib.sha256(raw).hexdigest()}


def inspect_clients(family):
    selections = selection(family)
    paths = {name: value['path'] for name, value in selections}
    clients = []
    for name, value in selections:
        row = {'client': name, 'selection': value, 'identity': None, 'command': None,
               'status': 'unavailable', 'exit_code': None, 'stdout': output(b''), 'stderr': output(b''),
               'observed_at': datetime.now(timezone.utc).isoformat()}
        clients.append(row)
        if not value['path']:
            row['reason'] = 'No installed client was selected'
            continue
        try:
            row['identity'] = fingerprint(value['path'])
            if name == 'apktool':
                if not paths['java']:
                    row['reason'] = 'The selected Apktool JAR requires an available Java executable'
                    continue
                row['java_identity'] = fingerprint(paths['java'])
                command = [paths['java'], '-jar', value['path'], '--version']
            else:
                command = [value['path'], '-version' if name == 'java' else '--version']
            row['command'] = command
            started = time.monotonic()
            # CLI tools receive no selected artifact, stdin, project directory,
            # capture interface, network endpoint or decoder action.
            with tempfile.TemporaryDirectory(prefix='vitruvius-client-version-') as directory:
                try:
                    observed = subprocess.run(command, cwd=directory, stdin=subprocess.DEVNULL, capture_output=True,
                        timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    row.update(status='ok' if observed.returncode == 0 else 'nonzero-exit', exit_code=observed.returncode,
                               stdout=output(observed.stdout), stderr=output(observed.stderr))
                except subprocess.TimeoutExpired as error:
                    row.update(status='timeout', stdout=output(error.stdout), stderr=output(error.stderr), reason='Version observation timed out')
            row['duration_seconds'] = time.monotonic() - started
            if fingerprint(value['path']) != row['identity'] or name == 'apktool' and fingerprint(paths['java']) != row['java_identity']:
                row.update(status='changed-during-inspection', reason='Selected executable or JAR identity changed during its version observation')
        except (OSError, ValueError) as error:
            row.update(status='error', reason=str(error))
    result = {'format': 'vitruvius.decoder-client-inspection/1', 'family': family, 'clients': clients,
        'artifact_accessed': False, 'target_executed': False,
        'limitations': ['Versions and diagnostics describe these selected local client invocations, not successful decoding of a target.',
            'Reported program output is untrusted data. File hashes identify observed bytes and do not authenticate the software publisher.']}
    if family == 'objdump':
        from .objdump_inspection import inspect
        if clients[0]['status'] != 'ok':
            result['advertised_targets'] = {'status': 'unavailable', 'reason': 'Selected reader version query did not succeed'}
        else:
            try:
                with tempfile.TemporaryDirectory(prefix='vitruvius-bfd-targets-') as directory:
                    observed = inspect('architectures', directory)
                observed['client_identity_consistent'] = (observed['engine']['path'] == clients[0]['selection']['path'] and
                    observed['engine']['identity']['sha256'] == clients[0]['identity']['sha256'])
                result['advertised_targets'] = observed
            except (OSError, ValueError) as error:
                result['advertised_targets'] = {'status': 'unavailable', 'reason': str(error)}
    return result
