"""Swift symbol demangling with swift-demangle from the free official Swift toolchain."""
import datetime
import glob
import hashlib
import os
import re
from pathlib import Path
import shutil
import subprocess

# Mangling prefixes the demangler recognises: the original Swift 1-3 scheme (_T), Swift 4 (_T0), 4.2 ($S), 5 and later ($s), Embedded Swift ($e) and macro expansions.
PREFIXES = ('_T0', '$s', '$S', '$e', '_$s', '_$S', '_$e', '@__swiftmacro_', '_T')
MAX_SYMBOLS = 10000
MAX_INPUT_BYTES = 8 * 1024 * 1024
# --classify prefixes a line with {N} (not a Swift symbol), T:<target> (a thunk and the symbol it forwards to) and C (no Swift calling convention).
CLASSIFICATION = re.compile(r'(\s*)\{((?:N|T:[^,}]*|C)(?:,(?:T:[^,}]*|C))*)\} ')


def engine():
    local = os.environ.get('LOCALAPPDATA')
    installed = sorted(glob.glob(str(Path(local) / 'Programs/Swift/Toolchains/*/usr/bin/swift-demangle.exe'))) if local else []
    candidates = [os.environ.get('THESEUS_SWIFT_DEMANGLE'), shutil.which('swift-demangle'), *reversed(installed),
                  'D:/LocalAI/tools/swift-6.4.1/admin/LocalApp/Programs/Swift/Toolchains/6.4.1+NoAsserts/usr/bin/swift-demangle.exe']
    return next((str(Path(value).resolve()) for value in candidates if value and Path(value).is_file()), None)


def validate(symbols):
    if not isinstance(symbols, list) or not 1 <= len(symbols) <= MAX_SYMBOLS:
        raise ValueError(f'symbols must be a list of 1 to {MAX_SYMBOLS} strings')
    if sum(len(symbol.encode('utf8')) + 1 for symbol in symbols if isinstance(symbol, str)) > MAX_INPUT_BYTES:
        raise ValueError(f'symbols must total at most {MAX_INPUT_BYTES} bytes')
    for symbol in symbols:
        if not isinstance(symbol, str) or not symbol:
            raise ValueError('Each Swift symbol must be a nonempty string')
        if '\n' in symbol or '\r' in symbol or '\0' in symbol:
            raise ValueError('Each Swift symbol must be one line without NUL')


def demangle(symbols):
    validate(symbols)
    executable = engine()
    if not executable:
        raise ValueError('Install the Swift toolchain or set THESEUS_SWIFT_DEMANGLE to swift-demangle')
    digest = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    version = subprocess.run([executable, '--version'], capture_output=True, timeout=60).stdout.decode('utf8', errors='replace')
    # Symbols travel on standard input, one per line, as in the Swift release suite. Never on the command line:
    # there the runtime expands @response files and wildcards and adds a $ to names that start with s or S.
    streams, provenance = [], []
    for mode, options in [('compact', []), ('classify', ['--classify'])]:
        started = datetime.datetime.now(datetime.timezone.utc).isoformat()
        reply = subprocess.run([executable, '--compact', *options], input=('\n'.join(symbols) + '\n').encode('utf8'), capture_output=True, timeout=300)
        lines = [line[:-1] if line.endswith('\r') else line for line in reply.stdout.decode('utf8', errors='replace').split('\n')]
        provenance.append({'executable': executable, 'sha256': digest, 'version': version.strip(), 'argument_count': len(symbols), 'input': 'stdin', 'mode': mode,
                   'exit_code': reply.returncode, 'stderr': reply.stderr.decode('utf8', errors='replace'),
                   'started_at': started, 'finished_at': datetime.datetime.now(datetime.timezone.utc).isoformat()})
        if reply.returncode != 0 or len(lines) != len(symbols) + 1 or lines[-1] != '':
            raise ValueError('swift-demangle did not return one line per symbol')
        streams.append(lines)
    rows = []
    for symbol, output, classified in zip(symbols, *streams):
        flags = []
        match = CLASSIFICATION.match(classified)
        # Classification markers can also be literal user text. Only consume a
        # prefix when removing it reproduces the independent compact stream.
        if match and match.group(1) + classified[match.end():] == output:
            flags = match.group(2).split(',')
        thunk = next((flag[2:] for flag in flags if flag.startswith('T:')), None)
        status = 'demangled' if output != symbol else 'invalid' if symbol.lstrip().startswith(PREFIXES) else 'unchanged'
        classification = {'swift_symbol': status != 'unchanged', 'thunk': thunk is not None,
                          'thunk_target': thunk or None, 'foreign_calling_convention': 'C' in flags}
        rows.append({'input': symbol, 'output': output, 'status': status, 'classification': classification})
    return {'symbols': rows, 'provenance': provenance,
            'limitations': ['A symbol is invalid when it carries a Swift mangling prefix and swift-demangle returns it unchanged; '
                            'a mangling that decodes to an unexpected but well-formed tree is reported as demangled.',
                            'Each line is read as text, as swift-demangle reads standard input: Swift symbols inside a line are replaced in place and the rest is kept.',
                            'Classification comes from swift-demangle --classify: thunk_target names the forwarded symbol when the thunk records one, '
                            'and foreign_calling_convention marks entry points without the Swift calling convention, such as C, Objective-C and value witness functions.',
                            'Demangling restores declared names and types only; it does not prove the symbol exists in any binary.']}
