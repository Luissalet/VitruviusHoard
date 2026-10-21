"""Artifact inventory and extraction against trees and archives built here.

The expected entries come from the file system walk, Python's zipfile and the bytes written in the test;
executables are linked by zig so their container formats are known from the target.
"""
import hashlib
import io
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import zipfile

from fastapi.testclient import TestClient
import pytest

from test_compiled_oracles import universal
from test_portfolio import run
from theseus.api import create_app

ZIG = os.environ.get('THESEUS_TEST_ZIG') or shutil.which('zig')
TARGETS = {'tool.elf': ('x86_64-linux-musl', 'elf'), 'tool.exe': ('x86_64-windows-gnu', 'pe'), 'tool-macho': ('aarch64-macos', 'mach-o')}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def deflated_zip():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('docs/readme.md', '# measure\n' * 30)
        script = zipfile.ZipInfo('bin/run.sh')
        script.external_attr = (stat.S_IFREG | 0o755) << 16
        archive.writestr(script, '#!/bin/sh\necho measure\n', compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr('data/table.bin', bytes(range(256)) * 8)
        inner = io.BytesIO()
        with tarfile.open(fileobj=inner, mode='w:gz') as tar:
            body = b'nested body\n'
            entry = tarfile.TarInfo('inner/a.txt')
            entry.size = len(body)
            tar.addfile(entry, io.BytesIO(body))
        archive.writestr('pack.tar.gz', inner.getvalue(), compress_type=zipfile.ZIP_STORED)
    return stream.getvalue()


@pytest.fixture(scope='module')
def tree(tmp_path_factory):
    root = tmp_path_factory.mktemp('artifact-oracle') / 'Tree'
    (root / 'bin').mkdir(parents=True)
    (root / 'empty').mkdir()
    (root / 'notes.txt').write_bytes('measure ñ\r\n'.encode())
    (root / 'bundle.zip').write_bytes(deflated_zip())
    if ZIG:
        work = root.parent / 'zig'
        work.mkdir()
        (work / 'main.c').write_text('int main(void) { return 3; }\n', encoding='utf8')
        env = {**os.environ, 'ZIG_GLOBAL_CACHE_DIR': str(work / 'cache'), 'ZIG_LOCAL_CACHE_DIR': str(work / 'local')}
        for name, (target, _) in TARGETS.items():
            subprocess.run([ZIG, 'cc', '-target', target, '-o', str(work / name), str(work / 'main.c')], check=True, capture_output=True, env=env)
            shutil.copy(work / name, root / 'bin' / name)
        (work / 'lib.c').write_text('int scale(int value) { return value * 3; }\n', encoding='utf8')
        slices = []
        for target, cpu, subtype in [('aarch64-macos', 0x0100000c, 0), ('x86_64-macos', 0x01000007, 3)]:
            output = work / ('lib-' + target + '.dylib')
            subprocess.run([ZIG, 'cc', '-target', target, '-dynamiclib', '-o', str(output), str(work / 'lib.c')], check=True, capture_output=True, env=env)
            slices.append((cpu, subtype, output.read_bytes()))
        (root / 'bin' / 'universal.dylib').write_bytes(universal(slices)[0])
    return root


def analyze(tmp_path, target, operation):
    app = create_app(tmp_path / 'data')
    project = app.state.store.create_project('Artifact oracle')
    artifact = app.state.store.add_artifact(project['id'], target)
    with TestClient(app, base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        return run(client, project['id'], artifact['id'], operation, {})[1]


def test_directory_inventory_matches_the_file_tree(tmp_path, tree):
    result = analyze(tmp_path, tree, 'artifact.inventory')
    assert result['coverage'] == {'scope': 'container-entries', 'status': 'complete'}
    nodes = {row['artifact_id']: row for row in result['nodes']}
    occurrences = {row['logical_path']: row for row in result['occurrences']}
    expected = {'.': 'directory'}
    for path in tree.rglob('*'):
        expected[path.relative_to(tree).as_posix()] = 'directory' if path.is_dir() else 'file'
    assert {path: row['entry_kind'] for path, row in occurrences.items()} == expected
    for path, kind in expected.items():
        if kind != 'file':
            continue
        data, row = (tree / path).read_bytes(), occurrences[path]
        assert nodes[row['artifact_id']]['sha256'] == sha(data) and row['declared_size'] == len(data) and row['hash_status'] == 'verified'
    formats = {'bundle.zip': 'zip', 'notes.txt': 'file'}
    if ZIG:
        formats.update({'bin/' + name: kind for name, (_, kind) in TARGETS.items()})
        formats['bin/universal.dylib'] = 'mach-o-universal'
    assert {path: occurrences[path]['artifact_format'] for path in formats} == formats
    # A nested archive is one occurrence; its members are not listed from a directory root.
    assert not any(path.startswith('bundle.zip/') for path in occurrences)
    parents = {row['occurrence_id']: row['logical_path'] for row in result['occurrences']}
    for path, row in occurrences.items():
        parent = parents.get(row['parent_occurrence_id'])
        assert parent == (None if path == '.' else (Path(path).parent.as_posix() if '/' in path else '.'))


def test_zip_inventory_matches_the_central_directory(tmp_path, tree):
    archive = tree / 'bundle.zip'
    result = analyze(tmp_path, archive, 'artifact.inventory')
    occurrences = {row['logical_path']: row for row in result['occurrences'] if row['logical_path'] != '.'}
    nodes = {row['artifact_id']: row for row in result['nodes']}
    with zipfile.ZipFile(archive) as reader:
        infos = {info.filename: info for info in reader.infolist()}
        expected_files = {name: reader.read(name) for name in infos}
    files = {path: row for path, row in occurrences.items() if row['entry_kind'] == 'file'}
    assert set(files) == set(infos)
    for name, info in infos.items():
        row = files[name]
        assert (row['declared_size'], row['compressed_size']) == (info.file_size, info.compress_size)
        assert nodes[row['artifact_id']]['sha256'] == sha(expected_files[name]) and row['hash_status'] == 'verified'
        assert row['executable'] == bool((info.external_attr >> 16) & 0o111)
        assert row['encrypted'] is False
    assert any('central-directory entries only' in text for text in result['limitations'])


def test_extraction_writes_every_member_with_its_original_bytes(tmp_path, tree):
    archive = tree / 'bundle.zip'
    result = analyze(tmp_path, archive, 'artifact.extract')
    output = Path(result['output_root'])
    assert result['containment_verified'] and result['integrity_contradictions'] == []
    with zipfile.ZipFile(archive) as reader:
        expected = {info.filename: reader.read(info) for info in reader.infolist() if not info.is_dir()}
    written = {row['relative_path']: row for row in result['artifacts']}
    assert set(written) == set(expected)
    for name, data in expected.items():
        assert (output / name).read_bytes() == data
        assert written[name]['sha256'] == sha(data) and written[name]['bytes_written'] == len(data) and written[name]['created']
    assert {path.relative_to(output).as_posix() for path in output.rglob('*') if path.is_file()} == set(expected)
    assert any('nested archive contents remain represented by their containing file' in text for text in result['limitations'])


def test_a_tar_root_is_observed_without_claiming_it_has_no_entries(tmp_path):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        body = b'tar member\n'
        entry = tarfile.TarInfo('member.txt')
        entry.size = len(body)
        archive.addfile(entry, io.BytesIO(body))
    target = tmp_path / 'archive.tar'
    target.write_bytes(stream.getvalue())
    (tmp_path / 'run').mkdir()
    result = analyze(tmp_path / 'run', target, 'artifact.inventory')
    assert [row['logical_path'] for row in result['occurrences']] == ['.']
    assert result['coverage']['scope'] == 'root'
    assert result['limitations'] == ['No entry reader applies to this format; entries it may contain are not listed.']
    assert not any('no child container entries' in text for text in result['limitations'])
