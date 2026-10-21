"""Go and Rust metadata readers against binaries built here and the toolchains' own readers.

Each binary is compiled in the test from small local sources, without network access. The
expected facts come from the toolchain that wrote them: `go version -m -json` for Go build
information and `rust-audit-info` for cargo-auditable dependency data.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from test_native_formats import inspect


def tool(variable, name):
    value = os.environ.get(variable) or shutil.which(name)
    return value if value and Path(value).is_file() else None


GO = tool('THESEUS_TEST_GO', 'go')
CARGO = tool('THESEUS_TEST_CARGO', 'cargo')
AUDIT_INFO = tool('THESEUS_TEST_RUST_AUDIT_INFO', 'rust-audit-info')
ZIG = tool('THESEUS_TEST_ZIG', 'zig')

GO_TARGETS = [
    ('windows', 'amd64', 'pe', 64, 'little', 'amd64'),
    ('windows', '386', 'pe', 32, 'little', '386'),
    ('linux', 'amd64', 'elf', 64, 'little', 'amd64'),
    ('linux', '386', 'elf', 32, 'little', '386'),
    ('linux', 'ppc64', 'elf', 64, 'big', 'ppc64'),
    ('linux', 'mips', 'elf', 32, 'big', 'mips'),
    ('darwin', 'arm64', 'macho', 64, 'little', 'arm64'),
    ('darwin', 'amd64', 'macho', 64, 'little', 'amd64'),
]


@pytest.fixture(scope='session')
def go_workspace(tmp_path_factory):
    if GO is None:
        pytest.skip('Requires an installed Go toolchain (THESEUS_TEST_GO or go on PATH)')
    root = tmp_path_factory.mktemp('go-oracle')
    source = root / 'source'
    (source / 'helper').mkdir(parents=True)
    (source / 'go.mod').write_text('module example.local/oracle\n\ngo 1.22\n\nrequire example.local/helper v1.4.2\n\n'
                                   'replace example.local/helper v1.4.2 => ./helper\n', encoding='utf8')
    (source / 'main.go').write_text('package main\n\nimport (\n\t"fmt"\n\n\t"example.local/helper"\n)\n\nvar stamp = "unset"\n\n'
                                    'func main() { fmt.Println(helper.Double(21), stamp) }\n', encoding='utf8')
    (source / 'helper' / 'go.mod').write_text('module example.local/helper\n\ngo 1.22\n', encoding='utf8')
    (source / 'helper' / 'helper.go').write_text('package helper\n\nfunc Double(value int) int { return value * 2 }\n', encoding='utf8')
    env = {key: value for key, value in os.environ.items() if not key.startswith('GO')}
    env.update(GOCACHE=str(root / 'cache'), GOMODCACHE=str(root / 'modules'), GOPATH=str(root / 'path'),
               GOFLAGS='-mod=mod', GOPROXY='off', GOSUMDB='off', GOTOOLCHAIN='local', CGO_ENABLED='0')
    return source, env


def go_build(go_workspace, goos, goarch):
    source, env = go_workspace
    output = source.parent / f'oracle-{goos}-{goarch}'
    if not output.exists():
        subprocess.run([GO, 'build', '-trimpath', '-buildvcs=false', '-ldflags=-X main.stamp=oracle', '-o', str(output), '.'],
                       cwd=source, env={**env, 'GOOS': goos, 'GOARCH': goarch}, check=True, capture_output=True)
    oracle = json.loads(subprocess.run([GO, 'version', '-m', '-json', str(output)], cwd=source, env=env,
                                       check=True, capture_output=True, text=True).stdout)
    return output, oracle


def module_identity(row):
    return None if row is None else {'path': row['Path'], 'version': row.get('Version', ''), 'sum': row.get('Sum')}


def observed_identity(row):
    # The reader keeps an empty sum column verbatim; the Go reader omits an empty Sum.
    return None if row is None else {'path': row['path'], 'version': row['version'], 'sum': row['sum'] or None}


@pytest.mark.parametrize('goos,goarch,kind,bits,order,architecture', GO_TARGETS)
def test_go_build_information_matches_the_go_toolchain_reader(tmp_path, go_workspace, goos, goarch, kind, bits, order, architecture):
    binary, oracle = go_build(go_workspace, goos, goarch)
    content = binary.read_bytes()
    result = inspect(tmp_path, 'go.build', content)
    assert (result['format'], result['bits'], result['byte_order'], result['architecture']) == (kind, bits, order, architecture)
    info = result['build_info']
    assert info['go_version'] == oracle['GoVersion']
    module = result['module']
    assert module['complete'] and module['unparsed_lines'] == [] and module['unparsed_line_bytes_base64'] == []
    assert module['path'] == oracle['Path']
    expected_main = module_identity(oracle['Main'])
    assert observed_identity(module['main']) == expected_main
    assert [{**observed_identity(row), 'replacement': observed_identity(row['replacement'])} for row in module['dependencies']] == [
        {**module_identity(row), 'replacement': module_identity(row.get('Replace'))} for row in oracle['Deps']]
    assert module['dependencies'][0]['replacement']['path'] == './helper'
    assert module['settings'] == [{'key': row['Key'], 'value': row['Value']} for row in oracle['Settings']]
    assert {'key': 'GOOS', 'value': goos} in module['settings'] and {'key': 'GOARCH', 'value': goarch} in module['settings']
    for field, location in [('go_version_bytes_base64', 'version_location'), ('module_bytes_base64', 'module_location')]:
        at = info[location]
        assert content[at['offset']:at['offset'] + at['bytes']] == base64.b64decode(info[field])
    assert base64.b64decode(info['go_version_bytes_base64']).decode() == oracle['GoVersion']


def test_go_binary_without_build_information_is_not_called_non_go(tmp_path, go_workspace):
    binary, _ = go_build(go_workspace, 'linux', 'amd64')
    content = bytearray(binary.read_bytes())
    marker = b'\xff Go buildinf:'
    offset = content.find(marker)
    assert offset >= 0 and content.find(marker, offset + 1) < 0
    content[offset:offset + len(marker)] = b'\0' * len(marker)
    result = inspect(tmp_path, 'go.build', bytes(content))
    assert result['format'] == 'elf' and result['build_info'] is None
    assert result['module'] is None
    assert any('does not establish that the image is not go' in row.lower() for row in result['limitations'])


@pytest.fixture(scope='session')
def rust_crate(tmp_path_factory):
    if CARGO is None or AUDIT_INFO is None or shutil.which('cargo-auditable', path=str(Path(CARGO).parent)) is None:
        pytest.skip('Requires cargo, cargo-auditable and rust-audit-info')
    root = tmp_path_factory.mktemp('rust-oracle')
    for name, body in [('units', 'pub fn scale(value: u64) -> u64 { value * 3 }\n'),
                       ('stamp', 'pub fn label() -> &\'static str { "oracle" }\n')]:
        (root / name / 'src').mkdir(parents=True)
        (root / name / 'Cargo.toml').write_text(f'[package]\nname = "{name}"\nversion = "0.3.1"\nedition = "2021"\n', encoding='utf8')
        (root / name / 'src' / 'lib.rs').write_text(body, encoding='utf8')
    app = root / 'measure'
    (app / 'src').mkdir(parents=True)
    (app / 'Cargo.toml').write_text('[package]\nname = "measure"\nversion = "1.2.0"\nedition = "2021"\nbuild = "build.rs"\n\n'
                                    '[dependencies]\nunits = { path = "../units" }\n\n[build-dependencies]\nstamp = { path = "../stamp" }\n',
                                    encoding='utf8')
    (app / 'build.rs').write_text('fn main() { println!("cargo:rustc-env=MEASURE_STAMP={}", stamp::label()); }\n', encoding='utf8')
    (app / 'src' / 'main.rs').write_text('fn main() { println!("{} {}", units::scale(43), env!("MEASURE_STAMP")); }\n', encoding='utf8')
    return app


def rust_build(app, target, extra_env=None):
    env = {**os.environ, 'CARGO_TARGET_DIR': str(app.parent / 'target'), **(extra_env or {})}
    subprocess.run([CARGO, 'auditable', 'build', '--offline', '--release', '--target', target], cwd=app, env=env,
                   check=True, capture_output=True)
    folder = app.parent / 'target' / target / 'release'
    binary = folder / ('measure.exe' if 'windows' in target else 'measure')
    oracle = json.loads(subprocess.run([AUDIT_INFO, str(binary)], check=True, capture_output=True, text=True).stdout)
    return binary, oracle


def assert_rust_matches(tmp_path, binary, oracle, kind):
    content = binary.read_bytes()
    result = inspect(tmp_path, 'rust.dependencies', content)
    assert result['format'] == kind and result['bits'] == 64 and result['byte_order'] == 'little'
    metadata = result['auditable_metadata']
    assert metadata['format_version'] == oracle.get('format')
    assert [{key: row[key] for key in ['name', 'version', 'source', 'kind', 'dependencies', 'root']} for row in metadata['packages']] == [
        {'name': row['name'], 'version': row['version'], 'source': row['source'], 'kind': row.get('kind'),
         'dependencies': row.get('dependencies', []), 'root': row.get('root', False)} for row in oracle['packages']]
    assert [row['name'] for row in metadata['packages'] if row['root']] == ['measure']
    assert {row['name']: row['kind'] for row in metadata['packages']}['stamp'] == 'build'
    section = content[metadata['file_offset']:metadata['file_offset'] + metadata['section_bytes']]
    import zlib
    assert json.loads(zlib.decompress(section)) == oracle
    verbose = subprocess.run(['rustc', '-vV'], capture_output=True, text=True, check=True).stdout
    commit = next(line.split(': ', 1)[1] for line in verbose.splitlines() if line.startswith('commit-hash:'))
    assert any(row['hash'] == commit for row in result['rustc_commit']['hashes'])


def test_rust_auditable_windows_binary_matches_the_audit_reader(tmp_path, rust_crate):
    binary, oracle = rust_build(rust_crate, 'x86_64-pc-windows-msvc')
    assert_rust_matches(tmp_path, binary, oracle, 'pe')


def test_rust_auditable_linux_binary_matches_the_audit_reader(tmp_path, rust_crate):
    if ZIG is None:
        pytest.skip('Requires zig as the Linux linker (THESEUS_TEST_ZIG)')
    installed = subprocess.run(['rustup', 'target', 'list', '--installed'], capture_output=True, text=True).stdout.split()
    if 'x86_64-unknown-linux-gnu' not in installed:
        pytest.skip('Requires the x86_64-unknown-linux-gnu Rust target')
    linker = rust_crate.parent / 'zig-linker.cmd'
    linker.write_text(f'@"{ZIG}" cc -target x86_64-linux-gnu %*\r\n', encoding='utf8')
    binary, oracle = rust_build(rust_crate, 'x86_64-unknown-linux-gnu', {'CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER': str(linker)})
    assert_rust_matches(tmp_path, binary, oracle, 'elf')
