"""Firmware regions and extraction on an image assembled here from real encoders.

The expected facts come from outside the product: where each stream was placed and what it
decodes to (Python's own gzip/xz/bzip2/zip/tar writers and readers), pyelftools for a zig-built ELF,
and the official Binwalk command line for its own signature map.
"""
import bz2
import gzip
import hashlib
import io
import json
import lzma
import math
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import zipfile
import zlib
from collections import Counter

from fastapi.testclient import TestClient
import pytest

from test_portfolio import run
from theseus.api import create_app
from theseus.firmware import engines

SEVEN_ZIP = engines()['seven_zip']

CLI = os.environ.get('THESEUS_TEST_BINWALK') or shutil.which('binwalk')
ZIG = os.environ.get('THESEUS_TEST_ZIG') or shutil.which('zig')
pytestmark = pytest.mark.skipif(not engines()['binwalk'], reason='Requires the firmware scanner')

ZIP_MEMBERS = {'etc/config.txt': b'mode=measure\n' * 20, 'bin/units.dat': bytes(range(256)) * 4}
TAR_MEMBERS = {'rootfs/version': b'1.4.2\n', 'rootfs/table.bin': bytes(range(200))}
STREAMS = {'gzip': b'kernel measure ' * 300, 'xz': b'initrd measure ' * 300, 'bzip2': b'data measure ' * 300}


def zipped():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in ZIP_MEMBERS.items():
            archive.writestr(name, body)
    return stream.getvalue()


def tarred():
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, body in TAR_MEMBERS.items():
            entry = tarfile.TarInfo(name)
            entry.size, entry.mtime = len(body), 0
            archive.addfile(entry, io.BytesIO(body))
    return stream.getvalue()


def elf(tmp_path):
    if not ZIG:
        return None
    source = tmp_path / 'probe.c'
    source.write_text('int measure(int value) { return value * 3; }\nint main(void) { return measure(14); }\n', encoding='utf8')
    output = tmp_path / 'probe.elf'
    env = {**os.environ, 'ZIG_GLOBAL_CACHE_DIR': str(tmp_path / 'zig-cache'), 'ZIG_LOCAL_CACHE_DIR': str(tmp_path / 'zig-local')}
    subprocess.run([ZIG, 'cc', '-target', 'x86_64-linux-musl', '-O2', '-s', '-o', str(output), str(source)],
                   check=True, capture_output=True, env=env)
    return output.read_bytes()


@pytest.fixture(scope='module')
def image(tmp_path_factory):
    root = tmp_path_factory.mktemp('firmware-oracle')
    parts = [('gzip', gzip.compress(STREAMS['gzip'], mtime=0)), ('xz', lzma.compress(STREAMS['xz'])),
             ('bzip2', bz2.compress(STREAMS['bzip2'])), ('zip', zipped()), ('tarball', tarred())]
    executable = elf(root)
    if executable is not None:
        parts.append(('elf', executable))
    content, placed = bytearray(b'FWHDR'.ljust(0x200, b'\xff')), []
    for name, data in parts:
        content += b'\xff' * (-len(content) % 0x1000)
        placed.append({'name': name, 'offset': len(content), 'bytes': data})
        content += data
    content += b'\xff' * 0x100
    return root, bytes(content), placed


def regions_and_extraction(tmp_path, content, parameters, extract=True):
    app = create_app(tmp_path / 'data')
    source = tmp_path / 'original-image.bin'
    source.write_bytes(content)
    project = app.state.store.create_project('Firmware oracle')
    artifact = app.state.store.add_artifact(project['id'], source)
    with TestClient(app, base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        _, regions = run(client, project['id'], artifact['id'], 'firmware.regions', parameters)
        if not extract:
            return regions, None, None
        job, extracted = run(client, project['id'], artifact['id'], 'firmware.extract', {'search_all': True})
    return regions, extracted, Path(job['result']['analysis_file']).parent / 'extracted'


def elf_extent(data):
    from elftools.elf.elffile import ELFFile
    image = ELFFile(io.BytesIO(data))
    header = image.header
    ends = [header['e_shoff'] + header['e_shnum'] * header['e_shentsize'], header['e_phoff'] + header['e_phnum'] * header['e_phentsize']]
    ends += [section['sh_offset'] + section['sh_size'] for section in image.iter_sections() if section['sh_type'] != 'SHT_NOBITS']
    return max(ends)


def test_regions_match_placement_official_binwalk_and_recomputed_entropy(tmp_path, image):
    root, content, placed = image
    regions, _, _ = regions_and_extraction(tmp_path, content, {'search_all': True, 'entropy_window': 4096})
    assert regions['status'] == 'observed' and regions['selection']['sha256'] == hashlib.sha256(content).hexdigest()
    found = {row['name']: row for row in regions['regions']}
    for part in placed:
        row = found[part['name']]
        assert row['offset'] == part['offset'] and row['root_file_range'] == {'offset': row['offset'], 'length': row['size']}
        if part['name'] == 'tarball':
            # Binwalk ends a tar region after the last member block; the writer's zero padding stays outside.
            assert len(TAR_MEMBERS) * 512 + sum(-(-len(body) // 512) * 512 for body in TAR_MEMBERS.values()) <= row['size'] <= len(part['bytes'])
        elif part['name'] == 'elf':
            # Binwalk estimates an ELF extent from its headers and can run into following filler bytes;
            # the reported region must still start at the image and cover all of it.
            assert elf_extent(part['bytes']) == len(part['bytes']) <= row['size']
        else:
            assert row['size'] == len(part['bytes'])
    windows = regions['entropy']
    assert [row['file_offset'] for row in windows] == list(range(0, len(content), 4096))
    for row in windows:
        block = content[row['file_offset']:row['file_offset'] + row['bytes']]
        expected = -sum(n / len(block) * math.log2(n / len(block)) for n in Counter(block).values())
        assert math.isclose(row['bits_per_byte'], expected, abs_tol=1e-12)
    covered = sorted((row['offset'], row['offset'] + row['size']) for row in regions['regions'])
    gaps = [(row['offset'], row['offset'] + row['length']) for row in regions['unclassified_ranges'] if row['parent_relative_path'] is None]
    spans = sorted(covered + gaps)
    # Regions and unclassified ranges partition the whole file without overlap.
    assert spans[0][0] == 0 and spans[-1][1] == len(content)
    assert all(left[1] == right[0] for left, right in zip(spans, spans[1:]))
    if CLI:
        log = tmp_path / 'official.json'
        subprocess.run([CLI, '--quiet', '--threads', '1', '--log', str(log), str(tmp_path / 'original-image.bin')], check=True, capture_output=True)
        official = json.loads(log.read_text(encoding='utf8'))[0]['Analysis']['file_map']
        assert [(row['name'], row['offset'], row['size'], row['confidence'], row['description']) for row in official] == [
            (row['name'], row['offset'], row['size'], row['confidence'], row['description']) for row in regions['regions']]


def test_extraction_carves_exact_ranges_and_decodes_to_the_original_bodies(tmp_path, image):
    root, content, placed = image
    _, extracted, folder = regions_and_extraction(tmp_path, content, {'search_all': True})
    # An ELF region is carved but has no member decoder; that is the only gap and it makes the run partial.
    has_elf = any(part['name'] == 'elf' for part in placed)
    assert extracted['status'] == ('partial' if has_elf else 'observed')
    assert [row['kind'] for row in extracted['gaps']] == (['extractor-unavailable-for-region'] if has_elf else [])
    rows = extracted['artifacts']
    carved = {row['classification']: row for row in rows if row.get('classification')}
    for part in placed:
        row = carved[part['name']]
        span = row['root_file_range']
        body = (folder / row['relative_path']).read_bytes()
        assert body == content[span['offset']:span['offset'] + span['length']] and hashlib.sha256(body).hexdigest() == row['sha256']
        if part['name'] == 'tarball':
            assert part['bytes'].startswith(body) and not part['bytes'][len(body):].strip(b'\0')
        else:
            assert body.startswith(part['bytes'])
    if has_elf:
        assert extracted['gaps'][0]['parent_relative_path'] == carved['elf']['relative_path']
    children = {}
    for row in rows:
        if row.get('archive_entry'):
            children.setdefault(row['parent_relative_path'], []).append(row)
    def members(name):
        return {row['archive_entry']['name']: (folder / row['relative_path']).read_bytes() for row in children[carved[name]['relative_path']]}
    for name, body in STREAMS.items():
        assert list(members(name).values()) == [body]
    assert members('zip') == ZIP_MEMBERS
    assert members('tarball') == TAR_MEMBERS
    for row in children[carved['zip']['relative_path']]:
        assert row['archive_entry']['crc32'] == zlib.crc32(ZIP_MEMBERS[row['archive_entry']['name']])
    assert all(hashlib.sha256((folder / row['relative_path']).read_bytes()).hexdigest() == row['sha256'] for row in rows)


def newc(entries):
    """cpio "newc" archive written field by field from the format description (as initramfs uses)."""
    out = bytearray()
    for inode, (name, mode, body) in enumerate([*entries, ('TRAILER!!!', 0, b'')], start=1):
        encoded = name.encode() + b'\0'
        fields = [inode if name != 'TRAILER!!!' else 0, mode, 0, 0, 1, 0, len(body), 0, 0, 0, 0, len(encoded), 0]
        out += b'070701' + b''.join(b'%08X' % value for value in fields) + encoded
        out += b'\0' * (-len(out) % 4) + body
        out += b'\0' * (-len(out) % 4)
    return bytes(out)


@pytest.mark.skipif(not SEVEN_ZIP, reason='Requires the optional 7-Zip decoder')
def test_cpio_members_are_extracted_with_archive_names_and_links_stay_gaps(tmp_path):
    members = {'etc/init.sh': b'#!/bin/sh\necho measure\n', 'usr/share/table.bin': bytes(range(256))}
    archive = newc([('etc', 0o040755, b''), *[(name, 0o100644, body) for name, body in members.items()],
                    ('bin/sh', 0o120777, b'busybox')])
    content = b'FWHDR'.ljust(0x1000, b'\xff') + archive + b'\xff' * 0x100
    _, extracted, folder = regions_and_extraction(tmp_path, content, {'search_all': True})
    region = next(row for row in extracted['regions'] if row['name'] == 'cpio')
    assert region['offset'] == 0x1000 and region['size'] == len(archive)
    rows = {row['archive_entry']['name']: row for row in extracted['artifacts'] if row.get('archive_entry')}
    assert {name: (folder / row['relative_path']).read_bytes() for name, row in rows.items()} == members
    assert [(row['kind'], row['entry']['name']) for row in extracted['gaps']] == [('link-not-created', 'bin/sh')]


def test_bzip2_stream_cut_at_the_end_of_the_file_finishes_without_a_region(tmp_path):
    stream = bz2.compress(STREAMS['bzip2'])
    content = b'FWHDR'.ljust(0x1000, b'\xff') + gzip.compress(STREAMS['gzip'], mtime=0) + stream[:len(stream) // 2]
    regions, _, _ = regions_and_extraction(tmp_path, content, {'search_all': True, 'timeout_seconds': 60}, extract=False)
    assert [row['name'] for row in regions['regions']] == ['gzip'] and regions['gaps'] == []
    assert all(not row['timed_out'] for row in regions['observations'])


@pytest.mark.skipif(not ZIG, reason='Requires zig to build a scanner stand-in that never finishes')
def test_a_scanner_that_never_finishes_is_stopped_and_recorded_as_a_gap(tmp_path, monkeypatch):
    source = tmp_path / 'stall.c'
    source.write_text('#include <windows.h>\nint main(void) { Sleep(600000); return 0; }\n' if os.name == 'nt' else
                      '#include <unistd.h>\nint main(void) { sleep(600); return 0; }\n', encoding='utf8')
    stall = tmp_path / ('stall.exe' if os.name == 'nt' else 'stall')
    env = {**os.environ, 'ZIG_GLOBAL_CACHE_DIR': str(tmp_path / 'zig-cache'), 'ZIG_LOCAL_CACHE_DIR': str(tmp_path / 'zig-local')}
    subprocess.run([ZIG, 'cc', '-o', str(stall), str(source)], check=True, capture_output=True, env=env)
    monkeypatch.setenv('THESEUS_BINWALK', str(stall))
    started = time.monotonic()
    regions, _, _ = regions_and_extraction(tmp_path, b'FWHDR'.ljust(0x1000, b'\xff'), {'timeout_seconds': 2}, extract=False)
    assert time.monotonic() - started < 60
    assert regions['status'] == 'partial' and [row['kind'] for row in regions['gaps']] == ['scanner-timeout']
    assert regions['gaps'][0]['timeout_seconds'] == 2 and regions['gaps'][0]['command'][0] == str(stall)
    assert any(row['timed_out'] for row in regions['observations'])


def iso9660(files):
    """ISO 9660 image written field by field from ECMA-119: system area, primary volume descriptor at
    sector 16, terminator, both path tables, the root directory and one extent per file."""
    sector = 2048
    both16 = lambda value: value.to_bytes(2, 'little') + value.to_bytes(2, 'big')
    both32 = lambda value: value.to_bytes(4, 'little') + value.to_bytes(4, 'big')

    def record(name, extent, size, directory=False):
        body = (bytes([0]) + both32(extent) + both32(size) + bytes(7) + bytes([2 if directory else 0, 0, 0])
                + both16(1) + bytes([len(name)]) + name)
        body += b'\0' * ((len(body) + 1) % 2)  # the record length, padding included, is even
        return bytes([len(body) + 1]) + body

    extents, cursor = [], 21
    for name, body in files.items():
        extents.append((name, body, cursor))
        cursor += -(-len(body) // sector)
    root = record(b'\0', 20, sector, True) + record(b'\1', 20, sector, True)
    root += b''.join(record(name.upper().encode() + b';1', extent, len(body)) for name, body, extent in extents)
    path_table = lambda order: bytes([1, 0]) + (20).to_bytes(4, order) + (1).to_bytes(2, order) + b'\0\0'
    descriptor = (bytes([1]) + b'CD001' + bytes([1, 0]) + b' ' * 32 + b'MEASURE'.ljust(32) + bytes(8) + both32(cursor) + bytes(32)
                  + both16(1) + both16(1) + both16(sector) + both32(10) + (18).to_bytes(4, 'little') + bytes(4)
                  + (19).to_bytes(4, 'big') + bytes(4) + record(b'\0', 20, sector, True)
                  + b' ' * (128 * 4 + 37 * 3) + (b'0' * 16 + b'\0') * 4 + bytes([1, 0]))
    image = bytearray(sector * 16) + descriptor.ljust(sector, b'\0') + (bytes([255]) + b'CD001' + bytes([1])).ljust(sector, b'\0')
    image += path_table('little').ljust(sector, b'\0') + path_table('big').ljust(sector, b'\0') + root.ljust(sector, b'\0')
    for _, body, _ in extents:
        image += body.ljust(-(-len(body) // sector) * sector, b'\0')
    return bytes(image)


@pytest.mark.skipif(not SEVEN_ZIP, reason='Requires the optional 7-Zip decoder')
def test_iso9660_members_are_extracted_and_not_read_as_an_empty_tar(tmp_path):
    files = {'readme.txt': b'Measure volume\n' * 40, 'table.bin': bytes(range(256)) * 9}
    volume = iso9660(files)
    content = b'FWHDR'.ljust(0x8000, b'\xff') + volume + b'\xff' * 0x200
    _, extracted, folder = regions_and_extraction(tmp_path, content, {'search_all': True})
    region = next(row for row in extracted['regions'] if row['name'] == 'iso9660')
    assert region['offset'] == 0x8000 and region['size'] == len(volume)
    rows = {row['archive_entry']['name'].split(';')[0].lower(): row for row in extracted['artifacts'] if row.get('archive_entry')}
    assert {name: (folder / row['relative_path']).read_bytes() for name, row in rows.items()} == files
    assert all(row['archive_entry']['reader'] == '7zip' for row in rows.values())
    assert extracted['gaps'] == [] and extracted['status'] == 'observed'


@pytest.mark.skipif(not SEVEN_ZIP, reason='Requires the optional 7-Zip decoder')
def test_a_container_without_members_is_an_explicit_gap(tmp_path):
    volume = iso9660({})
    _, extracted, _ = regions_and_extraction(tmp_path, b'FWHDR'.ljust(0x8000, b'\xff') + volume + b'\xff' * 0x200, {'search_all': True})
    carved = next(row for row in extracted['artifacts'] if row.get('classification') == 'iso9660')
    assert [(row['kind'], row['parent_relative_path']) for row in extracted['gaps']] == [('container-without-members', carved['relative_path'])]
    assert extracted['status'] == 'partial'
