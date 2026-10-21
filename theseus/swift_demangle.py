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
COMMAND_BUDGET = 24000  # characters per invocation, below the Windows command-line limit
# --classify prefixes a line with {N} (not a Swift symbol), T:<target> (a thunk and the symbol it forwards to) and C (no Swift calling convention).
CLASSIFICATION = re.compile(r'\{((?:N|T:[^,}]*|C)(?:,(?:T:[^,}]*|C))*)\} ')


def engine():
    local = os.environ.get('LOCALAPPDATA')
    installed = sorted(glob.glob(str(Path(local) / 'Programs/Swift/Toolchains/*/usr/bin/swift-demangle.exe'))) if local else []
    candidates = [os.environ.get('THESEUS_SWIFT_DEMANGLE'), shutil.which('swift-demangle'), *reversed(installed),
                  'D:/LocalAI/tools/swift-6.4.1/admin/LocalApp/Programs/Swift/Toolchains/6.4.1+NoAsserts/usr/bin/swift-demangle.exe']
    return next((str(Path(value).resolve()) for value in candidates if value and Path(value).is_file()), None)


def validate(symbols):
    if not isinstance(symbols, list) or not 1 <= len(symbols) <= MAX_SYMBOLS:
        raise ValueError(f'symbols must be a list of 1 to {MAX_SYMBOLS} strings')
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
    batches, current, size = [], [], 0
    for symbol in symbols:
        if current and size + len(symbol) + 3 > COMMAND_BUDGET:
            batches.append(current)
            current, size = [], 0
        current.append(symbol)
        size += len(symbol) + 3
    batches.append(current)
    rows, provenance = [], []
    for batch in batches:
        # '--' ends option parsing, so a symbol that starts with '-' is demangled, not read as an option.
        command = [executable, '--compact', '--classify', '--', *batch]
        started = datetime.datetime.now(datetime.timezone.utc).isoformat()
        reply = subprocess.run(command, capture_output=True, timeout=300)
        lines = reply.stdout.decode('utf8', errors='replace').split('\n')
        provenance.append({'executable': executable, 'sha256': digest, 'version': version.strip(), 'argument_count': len(batch),
                           'exit_code': reply.returncode, 'stderr': reply.stderr.decode('utf8', errors='replace'),
                           'started_at': started, 'finished_at': datetime.datetime.now(datetime.timezone.utc).isoformat()})
        if reply.returncode != 0 or len(lines) != len(batch) + 1 or lines[-1] != '':
            raise ValueError('swift-demangle did not return one line per symbol')
        for symbol, output in zip(batch, lines):
            flags = []
            match = CLASSIFICATION.match(output)
            if match:
                flags, output = match.group(1).split(','), output[match.end():]
            thunk = next((flag[2:] for flag in flags if flag.startswith('T:')), None)
            classification = {'swift_symbol': 'N' not in flags, 'thunk': thunk is not None,
                              'thunk_target': thunk or None, 'foreign_calling_convention': 'C' in flags}
            status = 'demangled' if output != symbol else 'invalid' if symbol.startswith(PREFIXES) else 'unchanged'
            rows.append({'input': symbol, 'output': output, 'status': status, 'classification': classification})
    return {'symbols': rows, 'provenance': provenance,
            'limitations': ['A symbol is invalid when it carries a Swift mangling prefix and swift-demangle returns it unchanged; '
                            'a mangling that decodes to an unexpected but well-formed tree is reported as demangled.',
                            'Classification comes from swift-demangle --classify: swift_symbol is false without a Swift prefix, '
                            'thunk_target names the forwarded symbol when the thunk records one, and foreign_calling_convention marks C or Objective-C entry points.',
                            'Demangling restores declared names and types only; it does not prove the symbol exists in any binary.']}
