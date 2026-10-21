"""Mach-O container reader against images linked here, checked with Go's debug/macho.

zig links small macOS executables and dylibs for arm64 and x86_64 with install names, versions,
rpaths and a weak dependency; Go links a darwin binary of its own. The expected load commands come
from fixtures/macho_oracle.go, which reads the same files with the Go standard library.
"""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from fastapi.testclient import TestClient

from test_compiled_oracles import universal
from test_portfolio import run
from theseus.api import create_app
from test_native_formats import inspect

GO = os.environ.get('THESEUS_TEST_GO') or shutil.which('go')
ZIG = os.environ.get('THESEUS_TEST_ZIG') or shutil.which('zig')
pytestmark = pytest.mark.skipif(not (GO and ZIG), reason='Requires zig (THESEUS_TEST_ZIG) and Go (THESEUS_TEST_GO)')

DEPENDENCIES = {0xc: 'LC_LOAD_DYLIB', 0x80000018: 'LC_LOAD_WEAK_DYLIB', 0x8000001f: 'LC_REEXPORT_DYLIB',
                0x20: 'LC_LAZY_LOAD_DYLIB', 0x80000023: 'LC_LOAD_UPWARD_DYLIB'}
MINIMUM_PLATFORMS = {0x24: 1, 0x25: 2, 0x2f: 3, 0x30: 4}
FILE_TYPES = {2: 'execute', 6: 'dylib', 8: 'bundle'}


@pytest.fixture(scope='module')
def images(tmp_path_factory):
    root = tmp_path_factory.mktemp('macho-oracle')
    env = {**os.environ, 'ZIG_GLOBAL_CACHE_DIR': str(root / 'zig-cache'), 'ZIG_LOCAL_CACHE_DIR': str(root / 'zig-local')}
    (root / 'units.c').write_text('int scale(int value) { return value * 3; }\n', encoding='utf8')
    (root / 'extra.c').write_text('int extra(void) { return 2; }\n', encoding='utf8')
    (root / 'main.c').write_text('int scale(int);\nint main(void) { return scale(14); }\n', encoding='utf8')
    (root / 'weak.c').write_text('int scale(int);\nint extra(void) __attribute__((weak_import));\n'
                                 'int main(void) { return scale(14) + (extra ? extra() : 0); }\n', encoding='utf8')

    def zig(*arguments):
        subprocess.run([ZIG, 'cc', *arguments], cwd=root, env=env, check=True, capture_output=True)

    zig('-target', 'aarch64-macos', '-dynamiclib', '-o', 'libunits-arm64.dylib', 'units.c', '-Wl,-install_name,@rpath/libunits.dylib')
    zig('-target', 'x86_64-macos', '-dynamiclib', '-o', 'libunits-x86_64.dylib', 'units.c', '-Wl,-install_name,@rpath/libunits.dylib')
    zig('-target', 'x86_64-macos', '-dynamiclib', '-o', 'libextra.dylib', 'extra.c', '-Wl,-install_name,/opt/measure/lib/libextra.dylib',
        '-Wl,-current_version,2.3.4', '-Wl,-compatibility_version,2.0.0')
    zig('-target', 'aarch64-macos', '-o', 'measure-arm64', 'main.c', 'libunits-arm64.dylib',
        '-Wl,-rpath,@executable_path/../lib', '-Wl,-rpath,/opt/measure/lib')
    zig('-target', 'x86_64-macos', '-o', 'measure-x86_64', 'weak.c', 'libunits-x86_64.dylib', '-L.', '-Wl,-weak-lextra', '-Wl,-rpath,@loader_path/lib')
    content, _ = universal([(0x0100000c, 0, (root / 'libunits-arm64.dylib').read_bytes()), (0x01000007, 3, (root / 'libunits-x86_64.dylib').read_bytes())])
    (root / 'libunits-universal.dylib').write_bytes(content)
    (root / 'hello.go').write_text('package main\n\nfunc main() { println("measure") }\n', encoding='utf8')
    go_env = {key: value for key, value in os.environ.items() if not key.startswith('GO')}
    go_env.update(GOCACHE=str(root / 'go-cache'), GOPATH=str(root / 'go-path'), GOPROXY='off', GOTOOLCHAIN='local', GO111MODULE='off',
                  CGO_ENABLED='0', GOOS='darwin', GOARCH='arm64')
    subprocess.run([GO, 'build', '-trimpath', '-o', str(root / 'go-darwin-arm64'), str(root / 'hello.go')], cwd=root, env=go_env, check=True, capture_output=True)
    host = {key: value for key, value in go_env.items() if key not in ('GOOS', 'GOARCH')}
    oracle = root / 'macho-oracle.exe'
    subprocess.run([GO, 'build', '-o', str(oracle), str(Path(__file__).parent / 'fixtures' / 'macho_oracle.go')], cwd=root, env=host, check=True, capture_output=True)
    return root, oracle


def expected_slice(row, fat):
    loads = row['loads']
    dependencies = [{'command': DEPENDENCIES[load['cmd']], 'install_name': load['name'], 'weak': load['cmd'] == 0x80000018,
                     'upward': load['cmd'] == 0x80000023, 'reexport': load['cmd'] == 0x8000001f,
                     'current_version': load['current_version'], 'compatibility_version': load['compatibility_version']}
                    for load in loads if load['cmd'] in DEPENDENCIES]
    identity = [load['name'] for load in loads if load['cmd'] == 0xd]
    platforms = [load['value'] if load['cmd'] == 0x32 else MINIMUM_PLATFORMS[load['cmd']] for load in loads
                 if load['cmd'] == 0x32 or load['cmd'] in MINIMUM_PLATFORMS]
    return {'slice_offset': row['offset'], 'slice_size': row['size'], 'cpu_type': row['cpu_type'], 'cpu_subtype': row['cpu_subtype'],
            'fat_cpu_type': row['cpu_type'] if fat else None, 'file_type_code': row['file_type'], 'file_type': FILE_TYPES[row['file_type']],
            'install_name': identity[0] if identity else None, 'dependencies': dependencies,
            'rpaths': [load['name'] for load in loads if load['cmd'] == 0x8000001c], 'platforms': platforms,
            'dyld_environment': [load['name'] for load in loads if load['cmd'] == 0x27],
            'code_signature_present': any(load['cmd'] == 0x1d for load in loads)}


@pytest.mark.parametrize('name', ['measure-arm64', 'measure-x86_64', 'libunits-arm64.dylib', 'libextra.dylib',
                                  'libunits-universal.dylib', 'go-darwin-arm64'])
def test_load_commands_match_go_debug_macho(tmp_path, images, name):
    root, oracle = images
    path = root / name
    expected = json.loads(subprocess.run([str(oracle), str(path)], check=True, capture_output=True, text=True).stdout)
    result = inspect(tmp_path, 'apple.macho', path.read_bytes())
    assert result['status'] == 'parsed' and len(result['slices']) == len(expected)
    fat = name.endswith('universal.dylib')
    for observed, row in zip(result['slices'], expected):
        wanted = expected_slice(row, fat)
        dependencies = wanted.pop('dependencies')
        assert {key: observed[key] for key in wanted} == wanted
        assert [{key: row[key] for key in dependencies[0]} for row in observed['dependencies']] == dependencies
        # Fields the oracle does not report hold their plain values for these linked images.
        assert all(row['encoding'] == 'dylib_command' and not row['delayed_init'] for row in observed['dependencies'])
    if fat:
        header = path.read_bytes()[:8 + 20 * len(expected)]
        table = [struct.unpack('>5I', header[8 + 20 * index:28 + 20 * index]) for index in range(len(expected))]
        assert [slice_['fat_alignment_exponent'] for slice_ in result['slices']] == [row[4] for row in table]
        assert [slice_['fat_cpu_subtype'] for slice_ in result['slices']] == [row[1] for row in table]


def test_weak_dependency_versions_and_rpaths_are_the_linked_ones(tmp_path, images):
    root, _ = images
    slice_ = inspect(tmp_path, 'apple.macho', (root / 'measure-x86_64').read_bytes())['slices'][0]
    rows = {row['install_name']: row for row in slice_['dependencies']}
    assert rows['/opt/measure/lib/libextra.dylib']['weak'] and rows['/opt/measure/lib/libextra.dylib']['current_version'] == '2.3.4'
    assert rows['/opt/measure/lib/libextra.dylib']['compatibility_version'] == '2.0.0'
    assert not rows['@rpath/libunits.dylib']['weak'] and slice_['rpaths'] == ['@loader_path/lib']


def trace(tmp_path, target):
    app = create_app(tmp_path / 'data')
    project = app.state.store.create_project('Dylib resolution')
    artifact = app.state.store.add_artifact(project['id'], target)
    with TestClient(app, base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        return run(client, project['id'], artifact['id'], 'apple.dylibs', {})[1]


def edges(result):
    return {row['install_name']: row for row in result['edges']}


def test_selected_image_resolves_inside_its_bundle(tmp_path, images):
    root, _ = images
    bundle = tmp_path / 'Measure.app' / 'Contents'
    (bundle / 'MacOS').mkdir(parents=True)
    (bundle / 'lib').mkdir()
    shutil.copy(root / 'measure-arm64', bundle / 'MacOS' / 'measure')
    shutil.copy(root / 'libunits-arm64.dylib', bundle / 'lib' / 'libunits.dylib')
    result = trace(tmp_path, bundle / 'MacOS' / 'measure')
    assert Path(result['root_path']).name == 'Measure.app' and result['roots'] == [{'image': 'Contents/MacOS/measure', 'architecture': 'arm64'}]
    units = edges(result)['@rpath/libunits.dylib']
    # dyld tries rpaths in load-command order: @executable_path/../lib first, then the absolute one.
    assert [(row['rpath'], row['outcome']) for row in units['candidates']][0][0] == '@executable_path/../lib'
    assert units['resolution'] == {'status': 'resolved', 'image': 'Contents/lib/libunits.dylib'}
    assert units['install_name_matches'] is True
    assert edges(result)['/usr/lib/libSystem.B.dylib']['resolution']['status'] == 'undetermined'
    library = next(image for image in result['images'] if image['path'] == 'Contents/lib/libunits.dylib')
    assert library['slices'][0]['install_name'] == '@rpath/libunits.dylib' and library['parse_status'] == 'parsed'


def test_selected_folder_traces_every_executable_with_loader_path_and_weak_libraries(tmp_path, images):
    root, _ = images
    tool = tmp_path / 'Tool'
    (tool / 'bin' / 'lib').mkdir(parents=True)
    shutil.copy(root / 'measure-x86_64', tool / 'bin' / 'measure')
    shutil.copy(root / 'libunits-x86_64.dylib', tool / 'bin' / 'lib' / 'libunits.dylib')
    result = trace(tmp_path, tool)
    assert result['roots'] == [{'image': 'bin/measure', 'architecture': 'x86_64'}]
    rows = edges(result)
    assert rows['@rpath/libunits.dylib']['resolution'] == {'status': 'resolved', 'image': 'bin/lib/libunits.dylib'}
    weak = rows['/opt/measure/lib/libextra.dylib']
    assert weak['weak'] and weak['command'] == 'LC_LOAD_WEAK_DYLIB' and weak['resolution']['status'] == 'undetermined'


def test_missing_library_inside_the_root_is_unresolved(tmp_path, images):
    root, _ = images
    tool = tmp_path / 'Broken'
    (tool / 'bin').mkdir(parents=True)
    shutil.copy(root / 'measure-x86_64', tool / 'bin' / 'measure')
    result = trace(tmp_path, tool)
    units = edges(result)['@rpath/libunits.dylib']
    assert units['resolution'] == {'status': 'unresolved', 'image': None}
    assert [row['outcome'] for row in units['candidates']] == ['absent']
