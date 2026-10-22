"""Flutter / Dart AOT operations against ELF files and APKs built here and read back by independent parsers.

Nothing is downloaded and no pub get runs. The fixtures are built inside the test:
  * real Dart AOT ELFs (arm64 and x64) from `dart compile aot-snapshot` over a local package whose
    .dart_tool/package_config.json is written by hand (needs THESEUS_TEST_DART);
  * split-layout snapshot ELFs and a fake libflutter.so linked with zig (needs THESEUS_TEST_ZIG);
  * APKs written with zipfile.

The expectations never come from the product's own regexes. They come from
  * pyelftools: dynamic symbols (values mapped to file offsets through PT_LOAD) and GNU build-id notes;
  * zipfile + hashlib: APK members, sizes and SHA-256;
  * struct: the snapshot header as laid out by Dart's runtime/vm/snapshot.h, i.e. at the data symbol
      +0  uint32 LE magic 0xdcdcf5f5 (bytes f5 f5 dc dc)
      +4  int64 length (does not count the 4 magic bytes)
      +12 int64 kind (Dart 3.13: kFullAOT = 2 in the unified layout; the older split layout uses 3)
      +20 32 lowercase hex characters, the snapshot hash
      +52 NUL terminated features string
  * the strings written into the Dart sources / C sources (package: URI, dart: libraries, GaugeWidget).
The zod schema of the reference implementation is bundled with esbuild and every result is validated by it.
"""
import hashlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import zipfile

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import NoteSection
from fastapi.testclient import TestClient
import pytest

from test_native_analysis import wait
from theseus.api import create_app
from theseus.native_analysis import ENGINE

DART = os.environ.get('THESEUS_TEST_DART') or shutil.which('dart')
ZIG = os.environ.get('THESEUS_TEST_ZIG') or shutil.which('zig')

MAGIC = bytes.fromhex('f5f5dcdc')  # uint32 LE 0xdcdcf5f5
UNIFIED_KIND, SPLIT_KIND = 2, 3
SPLIT_NAMES = ['_kDartVmSnapshotData', '_kDartVmSnapshotInstructions', '_kDartIsolateSnapshotData', '_kDartIsolateSnapshotInstructions']
UNIFIED_NAMES = ['_kDartSnapshotData', '_kDartSnapshotText', '_kDartSnapshotBuildId']
HASH_A, HASH_B = '0123456789abcdef0123456789abcdef', 'fedcba9876543210fedcba9876543210'
FEATURES = 'product no-asan no-msan no-tsan arm64 android no-compressed-pointers'
BUILD_ARM64, BUILD_V7, BUILD_X86, BUILD_SPLIT = ('00112233445566778899aabbccddeeff', 'a1b2c3d4e5f60718293a4b5c6d7e8f90',
                                                 '0badc0de0badc0de0badc0de0badc0de', 'feedfacecafebeef0102030405060708')
DART_VERSION = 'Dart VM version: 3.13.6 (stable) (Tue Oct 20 01:00:48 2026 -0700) on "android_arm64"'
ANDROID_LINE = 'Android (12345678, based on r530567) clang version 19.0.1 (https://example.invalid/llvm abcdef)'
LLVM_LINE = 'based on LLVM 19.0.1git (https://example.invalid/llvm abcdef)'
DECOYS = ['see Dart VM version: 9.9.9 (decoy)', 'was based on LLVM 12 (decoy)', 'Ubuntu clang version 19.0.1 (decoy)']
GARBAGE = b'MZ this is named libapp.so but is not an ELF file at all' * 3
ABI_ORDER = ['arm64-v8a', 'x86_64', 'x86', 'armeabi-v7a', 'armeabi', 'mips']  # the documented four, then the rest alphabetically
STORED, DEFLATED = zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED
VARIANTS = ['split-writable', 'split-nosections', 'split-uppercase', 'split-kind2', 'split-toolong']


# ----------------------------------------------------------------------------- independent oracles

def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_elf(data):
    """(dynamic symbols {name: (file offset, size)}, distinct GNU build ids in file order), all from pyelftools."""
    elf = ELFFile(io.BytesIO(data))
    loads = [(s['p_vaddr'], s['p_filesz'], s['p_offset']) for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']

    def file_offset(value):
        for vaddr, size, offset in loads:
            if vaddr <= value < vaddr + size:
                return value - vaddr + offset
        raise AssertionError('symbol value %#x is not inside a PT_LOAD segment' % value)

    if elf.num_sections():
        dynsym = elf.get_section_by_name('.dynsym')
        symbol_rows = list(dynsym.iter_symbols()) if dynsym else []
        note_owners = [section for section in elf.iter_sections() if isinstance(section, NoteSection)]
    else:  # section headers stripped: the loader's view, PT_DYNAMIC and PT_NOTE
        dynamic = [segment for segment in elf.iter_segments() if segment['p_type'] == 'PT_DYNAMIC'][0]
        symbol_rows = list(dynamic.iter_symbols())
        note_owners = [segment for segment in elf.iter_segments() if segment['p_type'] == 'PT_NOTE']
    symbols = {}
    for symbol in symbol_rows:
        if symbol.name and symbol['st_shndx'] != 'SHN_UNDEF':
            symbols[symbol.name] = (file_offset(symbol['st_value']), symbol['st_size'])
    ids = []
    for owner in note_owners:
        ids += [note['n_desc'] for note in owner.iter_notes() if note['n_type'] == 'NT_GNU_BUILD_ID']
    return symbols, list(dict.fromkeys(ids))


def is_elf(data):
    try:
        ELFFile(io.BytesIO(data))
        return True
    except Exception:  # pyelftools raises ELFError / struct.error on anything that is not an ELF image
        return False


def header_at(data, offset):
    """The snapshot header at `offset`, read with struct per runtime/vm/snapshot.h (see the module docstring)."""
    out = {'magic': data[offset:offset + 4] == MAGIC, 'length': None, 'kind': None, 'hash': None, 'features': None}
    if len(data) < offset + 52:
        return out
    out['length'], out['kind'] = struct.unpack_from('<qq', data, offset + 4)
    raw = data[offset + 20:offset + 52]
    out['hash'] = raw.decode('ascii') if re.fullmatch(rb'[0-9a-f]{32}', raw) else None
    end = data.find(b'\0', offset + 52)
    out['features'] = data[offset + 52:end].decode('ascii', 'replace') if end > 0 else None
    return out


def header_complete(data, offset, kind):
    head = header_at(data, offset)
    return bool(head['magic'] and head['hash'] and offset + 4 + head['length'] <= len(data) and head['kind'] == kind)


def magic_records(data):
    """Every f5f5dcdc occurrence followed by 32 lowercase hex characters at +20, in file order."""
    found, position = [], 0
    while True:
        at = data.find(MAGIC, position)
        if at < 0:
            return found
        raw = data[at + 20:at + 52]
        if re.fullmatch(rb'[0-9a-f]{32}', raw):
            found.append(raw.decode())
        position = at + 1


def printable_runs(data):
    return re.findall(rb'[\x20-\x7e]{4,}', data)


# ----------------------------------------------------------------------------- fixture builders

def c_array(name, payload, align=16, const=True):
    return '__attribute__((used, aligned(%d))) %sunsigned char %s[%d] = {%s};\n' % (align, 'const ' if const else '', name, len(payload), ','.join(str(b) for b in payload))


def snapshot_data(kind, hash_, magic=MAGIC, features=FEATURES, size=160, length=None):
    out = bytearray(size)
    out[0:4] = magic
    struct.pack_into('<qq', out, 4, size - 4 if length is None else length, kind)
    out[20:52] = hash_.encode()
    out[52:52 + len(features) + 1] = features.encode() + b'\0'
    return bytes(out)


def split_source(vm_hash=HASH_A, isolate_hash=HASH_A, isolate_magic=MAGIC, partial=False, kind=SPLIT_KIND, isolate_length=None, writable=False):
    text = c_array('_kDartVmSnapshotData', snapshot_data(kind, vm_hash), const=not writable) + c_array('_kDartVmSnapshotInstructions', bytes([0xcc]) * 64)
    if not partial:
        text += c_array('_kDartIsolateSnapshotData', snapshot_data(kind, isolate_hash, magic=isolate_magic, length=isolate_length), const=not writable)
        text += c_array('_kDartIsolateSnapshotInstructions', bytes([0xcd]) * 64)
    for index, value in enumerate(['package:split_pkg/split.dart', 'dart:typed_data', 'SplitGauge']):
        text += c_array('split_string_%d' % index, b'\0' + value.encode() + b'\0', align=1)
    return text


SECOND_BUILD_ID = bytes(range(0x40, 0x50))


def flutter_source(toolchain_lines, second_build_id=False):
    strings = [DART_VERSION, *toolchain_lines, *DECOYS] if toolchain_lines is not None else [DART_VERSION, ANDROID_LINE, LLVM_LINE, *DECOYS]
    text = ''.join(c_array('flutter_run_%d' % index, b'\0' + value.encode() + b'\0', align=1) for index, value in enumerate(strings))
    if second_build_id:  # a second, different NT_GNU_BUILD_ID note (type 3, owner "GNU") next to the linker's own
        text += ('struct note { unsigned namesz, descsz, type; char name[4]; unsigned char desc[16]; };\n'
                 '__attribute__((used, section(".note.gauge2"), aligned(4))) const struct note second = {4, 16, 3, "GNU", {%s}};\n'
                 % ','.join(str(b) for b in SECOND_BUILD_ID))
    return text


def strip_section_headers(data):
    out = bytearray(data)  # ELF64 little endian: e_shoff at 0x28, e_shnum at 0x3c, e_shstrndx at 0x3e
    out[0x28:0x30] = bytes(8)
    out[0x3c:0x40] = bytes(4)
    return bytes(out)


def make_apk(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data, method in members:
            archive.writestr(name, data, compress_type=method)
    return buffer.getvalue()


def run_tool(command, cwd, env=None):
    done = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, '%s\n%s%s' % (command, done.stdout, done.stderr)


@pytest.fixture(scope='module')
def work(tmp_path_factory):
    return tmp_path_factory.mktemp('flutter-oracle')


@pytest.fixture(scope='module')
def dart_elfs(work):
    if not DART:
        pytest.skip('Requires the Dart SDK (THESEUS_TEST_DART)')
    root = work / 'dart'
    package, app = root / 'gauge_pkg', root / 'app'
    for folder in (package / 'lib', app / 'bin', app / '.dart_tool'):
        folder.mkdir(parents=True)
    (package / 'pubspec.yaml').write_text("name: gauge_pkg\nenvironment:\n  sdk: '>=3.0.0 <4.0.0'\n")
    (package / 'lib' / 'gauge_pkg.dart').write_text(
        "library gauge_pkg;\n\nclass GaugeWidget {\n  final String label;\n  GaugeWidget(this.label);\n  String describe() => 'GaugeWidget ' + label;\n}\n")
    (app / 'pubspec.yaml').write_text("name: gauge_app\nenvironment:\n  sdk: '>=3.0.0 <4.0.0'\ndependencies:\n  gauge_pkg:\n    path: ../gauge_pkg\n")
    (app / '.dart_tool' / 'package_config.json').write_text(json.dumps({'configVersion': 2, 'generated': '2026-10-22T00:00:00Z', 'generator': 'manual', 'packages': [
        {'name': 'gauge_app', 'rootUri': '../', 'packageUri': 'lib/', 'languageVersion': '3.0'},
        {'name': 'gauge_pkg', 'rootUri': '../../gauge_pkg', 'packageUri': 'lib/', 'languageVersion': '3.0'}]}))
    (app / 'bin' / 'main.dart').write_text(
        "import 'dart:convert';\nimport 'package:gauge_pkg/gauge_pkg.dart';\n\nvoid main(List<String> args) {\n"
        "  final widget = GaugeWidget(args.isEmpty ? 'speed' : args.first);\n  print(jsonEncode({'text': widget.describe()}));\n}\n")
    env = {**os.environ, 'DART_SUPPRESS_ANALYTICS': 'true'}
    built = {}
    for arch in ('arm64', 'x64'):
        output = root / (arch + '.aot')
        run_tool([DART, 'compile', 'aot-snapshot', '--target-os', 'linux', '--target-arch', arch, '-o', str(output), str(app / 'bin' / 'main.dart')], app, env)
        built[arch] = output.read_bytes()
    return built


@pytest.fixture(scope='module')
def zig(work):
    if not ZIG:
        pytest.skip('Requires zig (THESEUS_TEST_ZIG)')
    env = {**os.environ, 'ZIG_GLOBAL_CACHE_DIR': str(work / 'zig-cache'), 'ZIG_LOCAL_CACHE_DIR': str(work / 'zig-local')}

    def build(name, source, build_id, target='aarch64-linux-gnu'):
        src, out = work / (name + '.c'), work / (name + '.so')
        src.write_text(source)
        flag = '-Wl,--build-id=0x' + build_id if build_id else '-Wl,--build-id=none'
        run_tool([ZIG, 'cc', '-target', target, '-shared', '-fPIC', '-o', str(out), str(src), flag], work, env)
        return out.read_bytes()
    return build


@pytest.fixture(scope='module')
def elfs(zig):
    """Linked shared objects: split-layout snapshots (agreeing, disagreeing, bad magic, only the VM half) and fake libflutter variants."""
    many = ['Android (%d, based on r530567) clang version 19.0.1 (https://example.invalid/llvm cap%d)' % (100000 + n, n) for n in range(6)]
    ok = zig('split-ok', split_source(), BUILD_SPLIT)
    return {
        'split-ok': ok,
        # header variants that are each wrong in exactly one way
        'split-writable': zig('split-writable', split_source(writable=True), BUILD_SPLIT),  # data in a segment whose vaddr differs from its file offset
        'split-nosections': strip_section_headers(ok),
        'split-uppercase': zig('split-uppercase', split_source(vm_hash=HASH_A.upper()), BUILD_SPLIT),  # magic fine, hash not lowercase hex
        'split-kind2': zig('split-kind2', split_source(kind=UNIFIED_KIND), BUILD_SPLIT),  # kind is not FullAOT of the split family
        'split-toolong': zig('split-toolong', split_source(isolate_length=10 ** 9), BUILD_SPLIT),  # declared length runs past the file
        'flutter-conflict': zig('flutter-conflict', flutter_source(None, second_build_id=True), BUILD_ARM64),
        'split-disagree': zig('split-disagree', split_source(HASH_A, HASH_B), BUILD_SPLIT),
        'split-badmagic': zig('split-badmagic', split_source(isolate_magic=b'\xf5\xf5\xdc\xdd'), BUILD_SPLIT),
        'split-partial': zig('split-partial', split_source(partial=True), BUILD_SPLIT),
        'flutter-arm64': zig('flutter-arm64', flutter_source(None), BUILD_ARM64),
        'flutter-v7': zig('flutter-v7', flutter_source(None), BUILD_V7, 'arm-linux-gnueabihf'),
        'flutter-x86': zig('flutter-x86', flutter_source(None), BUILD_X86, 'x86_64-linux-gnu'),
        'flutter-capped': zig('flutter-capped', flutter_source(many), BUILD_ARM64),
        'flutter-nobuildid': zig('flutter-nobuildid', flutter_source(None), None),
        'many-lines': many,
    }


@pytest.fixture(scope='module')
def apks(dart_elfs, elfs):
    arm64, x64 = dart_elfs['arm64'], dart_elfs['x64']
    base = [('AndroidManifest.xml', b'<manifest package="gauge.fixture"/>', STORED), ('classes.dex', b'dex\n035\0' + bytes(range(64)) * 8, DEFLATED)]
    flutter = elfs['flutter-arm64']
    variants = {'variant-' + name: make_apk(base + [('lib/arm64-v8a/libapp.so', elfs[name], DEFLATED)]) for name in VARIANTS}
    return {
        **variants,
        'garbage-libapp': make_apk(base + [('lib/arm64-v8a/libapp.so', GARBAGE, DEFLATED)]),
        'conflict': make_apk(base + [('lib/arm64-v8a/libflutter.so', elfs['flutter-conflict'], DEFLATED)]),
        # zip order is deliberately not the expected ABI order; arm64 libapp is stored, the other members are deflated or stored mixed
        'multi': make_apk(base + [
            ('lib/mips/libapp.so', GARBAGE, DEFLATED), ('lib/x86/libflutter.so', elfs['flutter-x86'], DEFLATED),
            ('lib/riscv64/libother.so', b'x' * 100, STORED), ('lib/armeabi/libapp.so', elfs['split-ok'], DEFLATED),
            ('lib/armeabi-v7a/libflutter.so', elfs['flutter-v7'], STORED), ('lib/x86_64/libapp.so', x64, DEFLATED),
            ('lib/arm64-v8a/libflutter.so', flutter, DEFLATED), ('lib/arm64-v8a/libapp.so', arm64, STORED),
            ('assets/libapp.so', b'not under lib/', STORED)]),
        'plain': make_apk(base + [('lib/arm64-v8a/libother.so', b'x' * 64, DEFLATED), ('assets/libapp.so', b'decoy', STORED)]),
        'split-ok': make_apk(base + [('lib/arm64-v8a/libapp.so', elfs['split-ok'], DEFLATED), ('lib/arm64-v8a/libflutter.so', flutter, DEFLATED)]),
        'split-disagree': make_apk(base + [('lib/arm64-v8a/libapp.so', elfs['split-disagree'], DEFLATED)]),
        'split-badmagic': make_apk(base + [('lib/arm64-v8a/libapp.so', elfs['split-badmagic'], STORED)]),
        'capped': make_apk(base + [('lib/arm64-v8a/libflutter.so', elfs['flutter-capped'], DEFLATED), ('lib/arm64-v8a/libapp.so', arm64, DEFLATED)]),
        'nobuildid': make_apk(base + [('lib/arm64-v8a/libflutter.so', elfs['flutter-nobuildid'], STORED)]),
        # libapp only in x86_64 and mips: the default for flutter.aot is x86_64 (documented order), explicit mips still works
        'order-x86_64': make_apk(base + [('lib/mips/libapp.so', elfs['split-ok'], DEFLATED), ('lib/x86_64/libapp.so', x64, DEFLATED)]),
        # only odd ABIs: alphabetical, so armeabi wins over mips
        'order-tail': make_apk(base + [('lib/mips/libapp.so', elfs['split-disagree'], DEFLATED), ('lib/armeabi/libapp.so', elfs['split-ok'], DEFLATED)]),
        'flutter-only': make_apk(base + [('lib/arm64-v8a/libflutter.so', flutter, DEFLATED)]),
        'notzip': b'PK is not a zip file, just text that says so' * 4,
    }


# ----------------------------------------------------------------------------- job plumbing

class Lab:
    def __init__(self, client, store, project, root):
        self.client, self.store, self.project, self.root = client, store, project, root
        self.artifacts, self.results = {}, {}

    def artifact(self, name, content):
        if name not in self.artifacts:
            path = self.root / name
            path.write_bytes(content)
            self.artifacts[name] = self.store.add_artifact(self.project, path)
        return self.artifacts[name]

    def job(self, name, content, operation, parameters=None):
        artifact = self.artifact(name, content)
        reply = self.client.post('/api/agent/call', json={'tool': 'theseus_analysis_start', 'arguments': {
            'project_id': self.project, 'artifact_id': artifact['id'], 'operation': operation, 'parameters': parameters or {}}})
        body = reply.json() if reply.headers.get('content-type', '').startswith('application/json') else {}
        started = body.get('result') if isinstance(body, dict) else None
        if reply.status_code >= 400 or not isinstance(started, dict) or 'state' not in started:
            return {'state': 'rejected', 'result': {'execution': {'stderr': reply.text}}}  # refused before a job existed
        return wait(self.client, started)

    def run(self, name, content, operation, parameters=None):
        key = (name, operation, json.dumps(parameters or {}, sort_keys=True))
        if key not in self.results:
            job = self.job(name, content, operation, parameters)
            assert job['state'] == 'finished', job['result'].get('execution', {}).get('stderr', job)
            self.results[key] = self.client.get('/api/jobs/' + job['id'] + '/analysis.json').json()['result']
        return self.results[key]

    def refused(self, name, content, operation, parameters=None):
        job = self.job(name, content, operation, parameters)
        assert job['state'] in ('failed', 'rejected'), job
        return job


@pytest.fixture(scope='module')
def lab(tmp_path_factory):
    root = tmp_path_factory.mktemp('flutter-lab')
    with TestClient(create_app(root / 'data'), base_url='http://127.0.0.1:5217') as client:  # in-process, nothing listens
        client.get('/')
        store = client.app.state.store
        (root / 'files').mkdir()
        yield Lab(client, store, store.create_project('Flutter oracle')['id'], root / 'files')


@pytest.fixture(scope='module')
def schema_check(work):
    node, esbuild = shutil.which('node'), ENGINE / 'node_modules' / 'esbuild' / 'bin' / 'esbuild'
    source = ENGINE / 'src' / 'domain' / 'flutter' / 'flutterBuildAnalysis.ts'
    if not (node and esbuild.is_file() and source.is_file()):
        pytest.skip('Requires node and the engine esbuild to bundle the reference zod schema')
    entry, bundle, probe = work / 'schema-entry.mjs', work / 'schema-check.mjs', work / 'schema-probe.json'
    entry.write_text("import { flutterResultSchemas } from %s;\nimport { readFileSync } from 'node:fs';\n"
                     "const [operation, file] = process.argv.slice(2);\n"
                     "const parsed = flutterResultSchemas[operation].safeParse(JSON.parse(readFileSync(file, 'utf8')));\n"
                     "console.log(JSON.stringify(parsed.success ? [] : parsed.error.issues.map((i) => i.path.join('.') + ': ' + i.message)));\n"
                     % json.dumps(source.as_posix()))
    run_tool([node, str(esbuild), str(entry), '--bundle', '--platform=node', '--format=esm', '--outfile=' + str(bundle), '--log-level=warning'], ENGINE)

    def check(operation, result):
        probe.write_text(json.dumps(result))
        done = subprocess.run([node, str(bundle), {'flutter.build': 'identify_flutter_build', 'flutter.aot': 'inspect_dart_aot'}[operation], str(probe)],
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)
    return check


# ----------------------------------------------------------------------------- flutter.elf

def elf_truth(data, layout):
    symbols, ids = read_elf(data)
    present = {name: value for name, value in symbols.items() if name in SPLIT_NAMES + UNIFIED_NAMES}
    kind = {'unified': UNIFIED_KIND, 'split': SPLIT_KIND}[layout]
    snapshots = {}
    for name, (offset, _size) in present.items():
        if name.endswith('Data'):
            head = header_at(data, offset)
            snapshots[name] = dict(name=name, file_offset=offset, magicValid=head['magic'], kind=head['kind'], headerLength=head['length'],
                                   hash=head['hash'], features=head['features'], complete=header_complete(data, offset, kind))
    return present, ids, snapshots


def check_elf(result, data, layout, bad=(), skip=()):
    present, ids, snapshots = elf_truth(data, layout)
    assert result['layout'] == layout
    assert len(result['symbols']) == len(present)
    assert {row['name']: (row['offset'], row['size']) for row in result['symbols']} == present
    assert result['symbol_failures'] == []  # the other family's names are not failures, and nothing of this family is missing
    assert result['build_ids'] == ids and ids
    assert result['build_id_failures'] == []
    got = {row['name']: row for row in result['snapshots']}
    assert len(result['snapshots']) == len(got) == len(snapshots) and set(got) == set(snapshots)
    for name, want in snapshots.items():
        if name in bad:
            assert got[name]['magicValid'] is False and got[name]['complete'] is False
            assert got[name]['file_offset'] == want['file_offset']
        else:
            assert {key: got[name].get(key) for key in want if key not in skip} == {key: value for key, value in want.items() if key not in skip}, name
    assert result['header'] and isinstance(result['limitations'], list) and result['limitations']
    return got


@pytest.mark.parametrize('arch', ['arm64', 'x64'])
def test_real_dart_unified_elf_matches_pyelftools_and_the_snapshot_header(lab, dart_elfs, arch):
    data = dart_elfs[arch]
    got = check_elf(lab.run('dart-%s.aot' % arch, data, 'flutter.elf'), data, 'unified')
    row = got['_kDartSnapshotData']
    assert row['kind'] == UNIFIED_KIND and row['complete'] is True and row['magicValid'] is True  # Dart 3.13.6: kFullAOT = 2
    assert re.fullmatch(r'[0-9a-f]{32}', row['hash']) and arch in row['features'] and 'linux' in row['features']
    assert row['headerLength'] == struct.unpack_from('<q', data, row['file_offset'] + 4)[0] > 0
    assert set(got) == {'_kDartSnapshotData'}


def test_one_dart_sdk_gives_arm64_and_x64_the_same_snapshot_hash(dart_elfs):
    # guards the premise of the fixtures: the hash is the SDK / runtime identity, not the architecture
    hashes = {arch: header_at(data, read_elf(data)[0]['_kDartSnapshotData'][0])['hash'] for arch, data in dart_elfs.items()}
    assert hashes['arm64'] == hashes['x64'] and hashes['arm64']


def test_split_layout_with_agreeing_headers_is_complete_at_kind_3(lab, elfs):
    data = elfs['split-ok']
    got = check_elf(lab.run('split-ok.so', data, 'flutter.elf'), data, 'split')
    assert set(got) == {'_kDartVmSnapshotData', '_kDartIsolateSnapshotData'}
    assert all(row['complete'] and row['kind'] == SPLIT_KIND and row['hash'] == HASH_A and row['features'] == FEATURES for row in got.values())
    assert read_elf(data)[1] == [BUILD_SPLIT]  # the linked build id is the one asked of the linker


def test_split_layout_with_disagreeing_hashes_reports_both(lab, elfs):
    data = elfs['split-disagree']
    got = check_elf(lab.run('split-disagree.so', data, 'flutter.elf'), data, 'split')
    assert {got['_kDartVmSnapshotData']['hash'], got['_kDartIsolateSnapshotData']['hash']} == {HASH_A, HASH_B}
    assert all(row['complete'] for row in got.values())  # completeness is per header; agreement is a property of the pair


def test_split_layout_with_one_bad_magic_is_incomplete_only_there(lab, elfs):
    data = elfs['split-badmagic']
    got = check_elf(lab.run('split-badmagic.so', data, 'flutter.elf'), data, 'split', bad=('_kDartIsolateSnapshotData',))
    assert got['_kDartVmSnapshotData']['complete'] is True


def test_split_layout_missing_members_are_failures_but_the_unified_names_are_not(lab, elfs):
    result = lab.run('split-partial.so', elfs['split-partial'], 'flutter.elf')
    assert result['layout'] == 'split'
    assert sorted(row['name'] for row in result['symbols']) == ['_kDartVmSnapshotData', '_kDartVmSnapshotInstructions']
    failures = json.dumps(result['symbol_failures'])
    assert '_kDartIsolateSnapshotData' in failures and '_kDartIsolateSnapshotInstructions' in failures
    assert not any(name in failures for name in UNIFIED_NAMES)
    assert [row['name'] for row in result['snapshots']] == ['_kDartVmSnapshotData']


def test_library_without_snapshot_symbols_has_no_layout_but_keeps_its_build_id(lab, elfs):
    result = lab.run('flutter-arm64.so', elfs['flutter-arm64'], 'flutter.elf')
    assert result['layout'] is None and result['symbols'] == [] and result['snapshots'] == []
    assert result['build_ids'] == [BUILD_ARM64] == read_elf(elfs['flutter-arm64'])[1]


def test_selected_symbols_restrict_the_symbols_and_snapshots_and_name_the_missing_one(lab, elfs):
    data = elfs['split-ok']
    result = lab.run('split-ok.so', data, 'flutter.elf', {'symbols': ['_kDartIsolateSnapshotData', '_kDartNoSuchSymbol']})
    want = read_elf(data)[0]['_kDartIsolateSnapshotData']
    assert [(row['name'], row['offset'], row['size']) for row in result['symbols']] == [('_kDartIsolateSnapshotData', *want)]
    assert [row['name'] for row in result['snapshots']] == ['_kDartIsolateSnapshotData']
    assert '_kDartNoSuchSymbol' in json.dumps(result['symbol_failures'])
    assert result['build_ids'] == [BUILD_SPLIT]


def test_selected_offsets_are_read_like_symbols_when_the_layout_is_known(lab, dart_elfs):
    data = dart_elfs['arm64']
    offset = read_elf(data)[0]['_kDartSnapshotData'][0]
    result = lab.run('dart-arm64.aot', data, 'flutter.elf', {'snapshot_offsets': [offset, 0]})
    at_symbol = [row for row in result['snapshots'] if row['file_offset'] == offset]
    assert len(at_symbol) >= 1 and all(row['complete'] and row['kind'] == UNIFIED_KIND for row in at_symbol)
    elsewhere = [row for row in result['snapshots'] if row['file_offset'] == 0]
    assert len(elsewhere) == 1 and elsewhere[0]['magicValid'] is False and elsewhere[0]['complete'] is False  # offset 0 is the ELF header


def test_selected_offset_with_unknown_layout_is_never_complete(lab, dart_elfs):
    data = dart_elfs['x64']
    offset = read_elf(data)[0]['_kDartSnapshotData'][0]
    result = lab.run('dart-x64.aot', data, 'flutter.elf', {'symbols': ['_kDartNoSuchSymbol'], 'snapshot_offsets': [offset]})
    assert result['layout'] is None and result['symbols'] == []
    assert len(result['snapshots']) == 1
    row, head = result['snapshots'][0], header_at(data, offset)
    assert row['file_offset'] == offset and row['magicValid'] is True and row['kind'] == head['kind'] == UNIFIED_KIND
    assert row['hash'] == head['hash'] and row['features'] == head['features'] and row['headerLength'] == head['length']
    assert row['complete'] is False


# ----------------------------------------------------------------------------- APK helpers (zipfile + hashlib + pyelftools)

def member(apk, name):
    with zipfile.ZipFile(io.BytesIO(apk)) as archive:
        return archive.read(name) if name in archive.namelist() else None


def check_target(result, apk):
    assert set(result['target']) == {'path', 'bytes', 'sha256'}
    assert result['target']['bytes'] == len(apk) and result['target']['sha256'] == sha(apk)
    assert isinstance(result['target']['path'], str) and result['target']['path']


def libapp_expect(data):
    if data is None:
        return dict(present=False, bytes=None, sha256=None, elf_header_valid=None, snapshot_hash_sources=0, snapshot_hash_candidates=[], snapshot_hash=None)
    records = magic_records(data)
    candidates = list(dict.fromkeys(records))
    return dict(present=True, bytes=len(data), sha256=sha(data), elf_header_valid=is_elf(data), snapshot_hash_sources=len(records),
                snapshot_hash_candidates=candidates, snapshot_hash=candidates[0] if len(candidates) == 1 else None)


def libflutter_expect(data, toolchain=(ANDROID_LINE, LLVM_LINE)):
    if data is None:
        return dict(present=False, bytes=None, sha256=None, build_id=None, build_id_candidates=[], dart_version=None, toolchain_lines=[],
                    dart_version_capped=False, toolchain_capped=False)
    ids = read_elf(data)[1]
    return dict(present=True, bytes=len(data), sha256=sha(data), build_id=ids[0] if len(ids) == 1 else None, build_id_candidates=ids,
                dart_version=DART_VERSION, toolchain_lines=sorted(toolchain), dart_version_capped=False, toolchain_capped=False)


def sorted_lines(row):
    return {**row, 'toolchain_lines': sorted(row['toolchain_lines'])}


def check_abi_entry(entry, apk, abi, toolchain=(ANDROID_LINE, LLVM_LINE)):
    assert set(entry) == {'abi', 'libapp', 'libflutter'} and entry['abi'] == abi
    assert entry['libapp'] == libapp_expect(member(apk, 'lib/%s/libapp.so' % abi)), abi
    assert sorted_lines(entry['libflutter']) == libflutter_expect(member(apk, 'lib/%s/libflutter.so' % abi), toolchain), abi


# ----------------------------------------------------------------------------- flutter.build

def test_build_orders_abis_and_matches_every_member_of_a_multi_abi_apk(lab, apks):
    apk = apks['multi']
    result = lab.run('multi.apk', apk, 'flutter.build')
    assert set(result) == {'target', 'flutter_detected', 'abis', 'coverage'}
    check_target(result, apk)
    assert result['flutter_detected'] is True and result['coverage'] in ('complete', 'partial')
    # riscv64 holds only libother.so and assets/libapp.so is outside lib/: neither may appear
    assert [row['abi'] for row in result['abis']] == ABI_ORDER
    for entry in result['abis']:
        check_abi_entry(entry, apk, entry['abi'])


def test_build_reports_stored_and_deflated_members_by_their_uncompressed_bytes(lab, apks):
    apk = apks['multi']
    with zipfile.ZipFile(io.BytesIO(apk)) as archive:  # guards the fixture: both compression methods are really present
        methods = {info.filename: info.compress_type for info in archive.infolist()}
    assert methods['lib/arm64-v8a/libapp.so'] == STORED and methods['lib/arm64-v8a/libflutter.so'] == DEFLATED
    assert methods['lib/x86_64/libapp.so'] == DEFLATED and methods['lib/armeabi-v7a/libflutter.so'] == STORED
    result = {row['abi']: row for row in lab.run('multi.apk', apk, 'flutter.build')['abis']}
    arm64 = member(apk, 'lib/arm64-v8a/libapp.so')
    assert result['arm64-v8a']['libapp']['sha256'] == sha(arm64) and result['arm64-v8a']['libapp']['bytes'] == len(arm64)
    assert result['arm64-v8a']['libflutter']['sha256'] == sha(member(apk, 'lib/arm64-v8a/libflutter.so'))
    assert result['x86_64']['libapp']['sha256'] == sha(member(apk, 'lib/x86_64/libapp.so'))
    assert result['armeabi-v7a']['libflutter']['sha256'] == sha(member(apk, 'lib/armeabi-v7a/libflutter.so'))


def test_build_real_dart_libapp_has_one_snapshot_header_and_its_hash(lab, apks, dart_elfs):
    result = {row['abi']: row for row in lab.run('multi.apk', apks['multi'], 'flutter.build')['abis']}
    for abi, arch in (('arm64-v8a', 'arm64'), ('x86_64', 'x64')):
        data = dart_elfs[arch]
        want = header_at(data, read_elf(data)[0]['_kDartSnapshotData'][0])['hash']
        libapp = result[abi]['libapp']
        assert libapp['elf_header_valid'] is True and libapp['snapshot_hash_sources'] == 1
        assert libapp['snapshot_hash_candidates'] == [want] and libapp['snapshot_hash'] == want


def test_build_non_elf_libapp_is_flagged_and_has_no_snapshot_hash(lab, apks):
    mips = {row['abi']: row for row in lab.run('multi.apk', apks['multi'], 'flutter.build')['abis']}['mips']
    assert mips['libapp']['present'] is True and mips['libapp']['elf_header_valid'] is False
    assert mips['libapp']['snapshot_hash_sources'] == 0 and mips['libapp']['snapshot_hash'] is None
    assert mips['libflutter']['present'] is False and mips['libflutter']['build_id'] is None


def test_build_libflutter_ids_versions_and_toolchain_lines_per_abi(lab, apks):
    entries = {row['abi']: row['libflutter'] for row in lab.run('multi.apk', apks['multi'], 'flutter.build')['abis']}
    for abi, build_id in (('arm64-v8a', BUILD_ARM64), ('armeabi-v7a', BUILD_V7), ('x86', BUILD_X86)):
        assert entries[abi]['build_id'] == build_id and entries[abi]['build_id_candidates'] == [build_id], abi
        assert entries[abi]['dart_version'] == DART_VERSION and entries[abi]['dart_version_capped'] is False
        # only runs that are exactly "Android (...) clang version ..." or "based on LLVM <digit>..."; the decoys embedded in longer runs do not count
        assert sorted(entries[abi]['toolchain_lines']) == sorted([ANDROID_LINE, LLVM_LINE]) and entries[abi]['toolchain_capped'] is False
    assert entries['x86_64']['present'] is False and entries['x86_64']['dart_version'] is None


def test_build_toolchain_lines_are_capped_at_four(lab, apks, elfs):
    apk = apks['capped']
    abi = lab.run('capped.apk', apk, 'flutter.build')['abis'][0]
    assert abi['abi'] == 'arm64-v8a'
    flutter = abi['libflutter']
    assert len(flutter['toolchain_lines']) == 4 and len(set(flutter['toolchain_lines'])) == 4
    assert set(flutter['toolchain_lines']) <= set(elfs['many-lines']) and flutter['toolchain_capped'] is True
    assert flutter['dart_version'] == DART_VERSION and flutter['build_id'] == BUILD_ARM64
    assert abi['libapp'] == libapp_expect(member(apk, 'lib/arm64-v8a/libapp.so'))


def test_build_libflutter_without_a_build_id_has_no_candidates(lab, apks):
    result = lab.run('nobuildid.apk', apks['nobuildid'], 'flutter.build')
    assert [row['abi'] for row in result['abis']] == ['arm64-v8a']
    flutter = result['abis'][0]['libflutter']
    assert flutter['present'] is True and flutter['build_id'] is None and flutter['build_id_candidates'] == []
    assert flutter['sha256'] == sha(member(apks['nobuildid'], 'lib/arm64-v8a/libflutter.so'))
    assert result['abis'][0]['libapp'] == libapp_expect(None)


def test_build_apk_without_flutter_libraries_is_not_flutter(lab, apks):
    result = lab.run('plain.apk', apks['plain'], 'flutter.build')
    check_target(result, apks['plain'])
    assert result['flutter_detected'] is False and result['abis'] == [] and result['coverage'] == 'complete'


@pytest.mark.parametrize('name,hashes', [('split-ok', [HASH_A]), ('split-disagree', [HASH_A, HASH_B]), ('split-badmagic', [HASH_A])])
def test_build_split_libapp_counts_magic_records_and_distinct_hashes(lab, apks, name, hashes):
    apk = apks[name]
    result = lab.run(name + '.apk', apk, 'flutter.build')
    libapp = result['abis'][0]['libapp']
    assert libapp == libapp_expect(member(apk, 'lib/arm64-v8a/libapp.so'))
    assert libapp['snapshot_hash_sources'] == (1 if name == 'split-badmagic' else 2)  # the damaged header is no longer a magic record
    assert sorted(libapp['snapshot_hash_candidates']) == sorted(hashes)
    assert libapp['snapshot_hash'] == (hashes[0] if len(hashes) == 1 else None)
    if name == 'split-ok':
        assert result['coverage'] == 'complete'


def test_build_rejects_a_file_that_is_not_a_zip(lab, apks):
    job = lab.refused('notzip.apk', apks['notzip'], 'flutter.build')
    assert job['result']['execution']['stderr']


# ----------------------------------------------------------------------------- flutter.aot

def aot_truth(libapp):
    symbols, _ = read_elf(libapp)
    family = 'unified' if '_kDartSnapshotData' in symbols else 'split'
    kind = {'unified': UNIFIED_KIND, 'split': SPLIT_KIND}[family]
    rows, hashes, complete = {}, [], True
    for name, (offset, size) in symbols.items():
        if not name.startswith('_kDart') or name == '_kDartSnapshotBuildId':
            continue
        if name.endswith('Data'):
            head = header_at(libapp, offset)
            rows[name] = (dict(name=name, offset=offset, size=size, magic_valid=head['magic'], kind=head['kind'], header_length=head['length']), head)
            if head['magic'] and head['hash']:
                hashes.append(head['hash'])
            complete = complete and header_complete(libapp, offset, kind)
        else:  # instructions are code: no header to read
            rows[name] = (dict(name=name, offset=offset, size=size, magic_valid=False, kind=None, header_length=None), None)
    candidates = list(dict.fromkeys(hashes))
    required = SPLIT_NAMES if family == 'split' else ['_kDartSnapshotData', '_kDartSnapshotText']
    complete = complete and all(name in rows for name in required) and len(candidates) == 1
    return dict(rows=rows, sources=len(hashes), candidates=candidates, coverage='complete' if complete else 'partial')


def check_pool(pool, packages, dart_libraries, tokens):
    assert set(pool) == {'coverage', 'package_uris', 'package_uri_count_at_least', 'dart_uris', 'dart_uri_count_at_least', 'class_like_tokens',
                         'class_like_token_count_at_least', 'printable_run_count'}
    assert pool['coverage'] in ('complete', 'partial')
    assert pool['package_uris'] == sorted(set(pool['package_uris'])) and pool['dart_uris'] == sorted(set(pool['dart_uris']))
    assert all(uri.startswith('package:') for uri in pool['package_uris']) and all(uri.startswith('dart:') for uri in pool['dart_uris'])
    assert set(packages) <= set(pool['package_uris']) and set(dart_libraries) <= set(pool['dart_uris'])
    assert set(tokens) <= set(pool['class_like_tokens'])
    assert pool['package_uri_count_at_least'] >= len(pool['package_uris']) >= 1
    assert pool['dart_uri_count_at_least'] >= len(pool['dart_uris']) >= 1
    assert pool['class_like_token_count_at_least'] >= len(pool['class_like_tokens']) >= 1
    assert pool['printable_run_count'] > 0


def check_aot(result, apk, abi, packages, dart_libraries, tokens):
    libapp = member(apk, 'lib/%s/libapp.so' % abi)
    assert set(result) == {'target', 'abi', 'libapp', 'string_pool', 'coverage'}
    check_target(result, apk)
    assert result['abi'] == abi
    section = result['libapp']
    assert set(section) == {'coverage', 'bytes', 'sha256', 'snapshot_hash', 'snapshot_hash_candidates', 'snapshot_hash_sources', 'sections'}
    truth = aot_truth(libapp)
    assert section['bytes'] == len(libapp) and section['sha256'] == sha(libapp)
    assert section['snapshot_hash_sources'] == truth['sources']
    assert sorted(section['snapshot_hash_candidates']) == sorted(truth['candidates'])
    assert section['snapshot_hash'] == (truth['candidates'][0] if len(truth['candidates']) == 1 else None)
    assert section['coverage'] == truth['coverage']
    rows = {row['name']: row for row in section['sections']}
    assert len(rows) == len(section['sections'])
    assert set(truth['rows']) <= set(rows) <= set(truth['rows']) | {'_kDartSnapshotBuildId'}
    for name, (want, head) in truth['rows'].items():
        if head is not None and not head['magic']:
            assert (rows[name]['name'], rows[name]['offset'], rows[name]['size'], rows[name]['magic_valid']) == (name, want['offset'], want['size'], False)
        else:
            assert rows[name] == want, name
    if section['coverage'] == 'partial':
        assert result['coverage'] == 'partial'
    check_pool(result['string_pool'], packages, dart_libraries, tokens)
    return truth


GAUGE = (['package:gauge_pkg/gauge_pkg.dart'], ['dart:core', 'dart:convert'], ['GaugeWidget'])
SPLIT = (['package:split_pkg/split.dart'], ['dart:typed_data'], ['SplitGauge'])


def test_aot_defaults_to_arm64_and_reads_the_real_unified_snapshot(lab, apks):
    result = lab.run('multi.apk', apks['multi'], 'flutter.aot')
    truth = check_aot(result, apks['multi'], 'arm64-v8a', *GAUGE)
    assert truth['coverage'] == 'complete' and result['libapp']['coverage'] == 'complete'
    rows = {row['name']: row for row in result['libapp']['sections']}
    assert rows['_kDartSnapshotData']['kind'] == UNIFIED_KIND and rows['_kDartSnapshotData']['magic_valid'] is True
    assert rows['_kDartSnapshotText']['magic_valid'] is False and rows['_kDartSnapshotText']['kind'] is None
    assert result['libapp']['snapshot_hash_sources'] == 1


@pytest.mark.parametrize('abi,expected', [('x86_64', GAUGE), ('armeabi', SPLIT)])
def test_aot_explicit_abi_reads_that_abis_libapp(lab, apks, abi, expected):
    result = lab.run('multi.apk', apks['multi'], 'flutter.aot', {'abi': abi})
    truth = check_aot(result, apks['multi'], abi, *expected)
    assert truth['coverage'] == 'complete'
    assert result['libapp']['sha256'] == sha(member(apks['multi'], 'lib/%s/libapp.so' % abi))


def test_aot_split_sections_list_all_four_symbols_with_kind_3(lab, apks):
    result = lab.run('split-ok.apk', apks['split-ok'], 'flutter.aot')
    check_aot(result, apks['split-ok'], 'arm64-v8a', *SPLIT)
    rows = {row['name']: row for row in result['libapp']['sections']}
    assert {name for name in rows if name != '_kDartSnapshotBuildId'} == set(SPLIT_NAMES)
    for name in ('_kDartVmSnapshotData', '_kDartIsolateSnapshotData'):
        assert rows[name]['magic_valid'] is True and rows[name]['kind'] == SPLIT_KIND and rows[name]['header_length'] == 156
    for name in ('_kDartVmSnapshotInstructions', '_kDartIsolateSnapshotInstructions'):
        assert rows[name]['magic_valid'] is False and rows[name]['kind'] is None and rows[name]['header_length'] is None and rows[name]['size'] == 64
    assert result['libapp']['snapshot_hash_sources'] == 2 and result['libapp']['snapshot_hash'] == HASH_A
    assert result['libapp']['coverage'] == 'complete'


def test_aot_disagreeing_hashes_are_partial_and_have_no_single_hash(lab, apks):
    result = lab.run('split-disagree.apk', apks['split-disagree'], 'flutter.aot')
    check_aot(result, apks['split-disagree'], 'arm64-v8a', *SPLIT)
    libapp = result['libapp']
    assert sorted(libapp['snapshot_hash_candidates']) == [HASH_A, HASH_B] and libapp['snapshot_hash'] is None
    assert libapp['snapshot_hash_sources'] == 2 and libapp['coverage'] == 'partial' and result['coverage'] == 'partial'
    rows = {row['name']: row for row in libapp['sections']}
    assert rows['_kDartVmSnapshotData']['magic_valid'] and rows['_kDartIsolateSnapshotData']['magic_valid']


def test_aot_bad_magic_in_one_data_header_is_partial_and_not_counted(lab, apks):
    apk = apks['split-badmagic']
    result = lab.run('split-badmagic.apk', apk, 'flutter.aot')
    check_aot(result, apk, 'arm64-v8a', *SPLIT)
    libapp = result['libapp']
    rows = {row['name']: row for row in libapp['sections']}
    assert rows['_kDartIsolateSnapshotData']['magic_valid'] is False and rows['_kDartVmSnapshotData']['magic_valid'] is True
    assert libapp['snapshot_hash_sources'] == 1 and libapp['snapshot_hash_candidates'] == [HASH_A]
    assert libapp['coverage'] == 'partial' and result['coverage'] == 'partial'
    for key, want in aot_truth(member(apk, 'lib/arm64-v8a/libapp.so'))['rows'].items():
        assert rows[key]['offset'] == want[0]['offset'] and rows[key]['size'] == want[0]['size']


@pytest.mark.parametrize('name,abi', [('order-x86_64', 'x86_64'), ('order-tail', 'armeabi')])
def test_aot_default_abi_follows_the_documented_order_among_abis_with_libapp(lab, apks, name, abi):
    result = lab.run(name + '.apk', apks[name], 'flutter.aot')
    assert result['abi'] == abi
    assert result['libapp']['sha256'] == sha(member(apks[name], 'lib/%s/libapp.so' % abi))


def test_aot_can_still_select_the_lower_priority_abi_explicitly(lab, apks):
    result = lab.run('order-x86_64.apk', apks['order-x86_64'], 'flutter.aot', {'abi': 'mips'})
    check_aot(result, apks['order-x86_64'], 'mips', *SPLIT)


@pytest.mark.parametrize('name,parameters', [
    ('multi', {'abi': 'riscv64'}),            # valid spelling, no such directory with libapp
    ('multi', {'abi': 'x86'}),                # libflutter only
    ('multi', {'abi': 'armeabi-v7a'}),        # libflutter only
    ('multi', {'abi': 'ARM64'}),              # outside ^[a-z0-9_-]+$
    ('multi', {'abi': 'arm64/../x86_64'}),    # path syntax is not an ABI name
    ('multi', {'abi': 'a'}),                  # shorter than 2
    ('multi', {'abi': 'abcdefghijklmnopq'}),  # longer than 16
    ('plain', {}),                            # no Flutter libraries at all
    ('flutter-only', {}),                     # libflutter without libapp
    ('notzip', {}),
])
def test_aot_refuses_unknown_abis_apks_without_libapp_and_non_zip_input(lab, apks, name, parameters):
    lab.refused(name + '.apk', apks[name], 'flutter.aot', parameters)


# ----------------------------------------------------------------------------- the reference zod schema

@pytest.mark.parametrize('name,operation,parameters', [
    ('multi', 'flutter.build', {}), ('plain', 'flutter.build', {}), ('split-disagree', 'flutter.build', {}), ('capped', 'flutter.build', {}),
    ('nobuildid', 'flutter.build', {}), ('multi', 'flutter.aot', {}), ('multi', 'flutter.aot', {'abi': 'armeabi'}),
    ('split-badmagic', 'flutter.aot', {}), ('split-disagree', 'flutter.aot', {}), ('order-tail', 'flutter.aot', {})])
def test_results_satisfy_the_reference_zod_schema(lab, apks, schema_check, name, operation, parameters):
    result = lab.run(name + '.apk', apks[name], operation, parameters)
    assert schema_check(operation, result) == []


# ----------------------------------------------------------------------------- hostile variants (each is wrong in one way the format allows)

def symbol_values(data):
    return {symbol.name: symbol['st_value'] for symbol in ELFFile(io.BytesIO(data)).get_section_by_name('.dynsym').iter_symbols() if symbol.name}


EXPECTED_COMPLETE = {'split-writable': (True, True), 'split-nosections': (True, True), 'split-uppercase': (False, True),
                     'split-kind2': (False, False), 'split-toolong': (True, False)}  # (VM data header complete, isolate data header complete)


@pytest.mark.parametrize('name', VARIANTS)
def test_elf_header_variants_follow_the_independent_header_reading(lab, elfs, name):
    data = elfs[name]
    if name == 'split-writable':  # guard: the data lives where the virtual address and the file offset differ, so a naive "address = offset" fails
        values, offsets = symbol_values(data), read_elf(data)[0]
        assert values['_kDartVmSnapshotData'] != offsets['_kDartVmSnapshotData'][0] and values['_kDartIsolateSnapshotData'] != offsets['_kDartIsolateSnapshotData'][0]
    if name == 'split-nosections':  # guard: really no section header table, yet the independent loader-view parse still finds everything
        assert ELFFile(io.BytesIO(data)).num_sections() == 0 and len(read_elf(data)[0]) >= 4
    got = check_elf(lab.run(name + '.so', data, 'flutter.elf'), data, 'split', skip=('hash', 'features') if name == 'split-uppercase' else ())
    assert (got['_kDartVmSnapshotData']['complete'], got['_kDartIsolateSnapshotData']['complete']) == EXPECTED_COMPLETE[name]
    if name == 'split-uppercase':
        assert got['_kDartVmSnapshotData']['magicValid'] is True


@pytest.mark.parametrize('name', VARIANTS)
def test_apk_with_a_hostile_libapp_agrees_with_the_independent_reading_in_build_and_aot(lab, apks, name):
    apk = apks['variant-' + name]
    build = lab.run(name + '.apk', apk, 'flutter.build')
    assert build['abis'][0]['libapp'] == libapp_expect(member(apk, 'lib/arm64-v8a/libapp.so'))
    aot = lab.run(name + '.apk', apk, 'flutter.aot')
    check_aot(aot, apk, 'arm64-v8a', *SPLIT)
    assert aot['libapp']['coverage'] == ('complete' if EXPECTED_COMPLETE[name] == (True, True) else 'partial')
    assert aot['libapp']['snapshot_hash_sources'] == (1 if name == 'split-uppercase' else 2)


def test_conflicting_build_ids_stay_explicit_instead_of_picking_one(lab, apks, elfs):
    data = elfs['flutter-conflict']
    ids = read_elf(data)[1]
    assert sorted(ids) == sorted([BUILD_ARM64, SECOND_BUILD_ID.hex()])  # guard: both notes really are in the linked file
    flutter = lab.run('conflict.apk', apks['conflict'], 'flutter.build')['abis'][0]['libflutter']
    assert flutter['build_id'] is None and sorted(flutter['build_id_candidates']) == sorted(ids)
    assert sorted(lab.run('flutter-conflict.so', data, 'flutter.elf')['build_ids']) == sorted(ids)


def test_aot_of_a_libapp_that_is_not_an_elf_reports_what_it_can(lab, apks):
    apk = apks['garbage-libapp']
    result = lab.run('garbage-libapp.apk', apk, 'flutter.aot')
    libapp = result['libapp']
    assert libapp['bytes'] == len(GARBAGE) and libapp['sha256'] == sha(GARBAGE)
    assert libapp['sections'] == [] and libapp['snapshot_hash_sources'] == 0 and libapp['snapshot_hash_candidates'] == [] and libapp['snapshot_hash'] is None
    assert libapp['coverage'] == 'partial' and result['coverage'] == 'partial'
    assert result['string_pool']['package_uris'] == [] and result['string_pool']['printable_run_count'] > 0


def test_selected_offset_too_close_to_the_end_for_a_header_is_never_complete(lab, dart_elfs):
    data = dart_elfs['arm64']
    offset = len(data) - 8
    job = lab.job('dart-arm64.aot', data, 'flutter.elf', {'snapshot_offsets': [offset]})
    if job['state'] == 'finished':  # reporting it unreadable and incomplete, or refusing, are both honest; reporting it complete is not
        snapshots = lab.client.get('/api/jobs/' + job['id'] + '/analysis.json').json()['result']['snapshots']
        rows = [row for row in snapshots if row['file_offset'] == offset]
        assert rows and all(row['complete'] is False and row['magicValid'] is False for row in rows)
    else:
        assert job['state'] in ('failed', 'rejected')
