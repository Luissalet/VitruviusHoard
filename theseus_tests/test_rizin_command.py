"""Rizin static commands against an ELF linked here and read independently with pyelftools.

The fixture is a small C program linked with zig for x86-64 Linux (musl, static). Rizin's JSON
answers for headers, sections, symbols, strings, bytes and functions are compared with what
pyelftools reads from the same file; commands outside the read-only grammar must never run.
"""
import json
import os
import subprocess

import pytest

from test_pcap_oracle import Lab  # noqa: F401  (job helper shared with the capture tests)
from test_native_analysis import wait
from theseus.api import create_app
from theseus.rizin import COMMANDS, admit, engine

from fastapi.testclient import TestClient

elftools = pytest.importorskip('elftools')
from elftools.elf.elffile import ELFFile  # noqa: E402

ZIG = os.environ.get('THESEUS_TEST_ZIG')
pytestmark = [pytest.mark.skipif(engine() is None, reason='Requires Rizin (THESEUS_RIZIN)'),
              pytest.mark.skipif(not ZIG, reason='Requires zig (THESEUS_TEST_ZIG) to link the fixture')]

SOURCE = r'''
#include <stdio.h>
const char banner[] = "THESEUS-RIZIN-ORACLE-4471";
__attribute__((noinline)) int gauge_leaf(int x) { return x * 7 + 3; }
__attribute__((noinline)) int gauge_route(int x) { return gauge_leaf(x) + gauge_leaf(x + 1); }
int main(int argc, char **argv) { puts(banner); return gauge_route(argc); }
'''
BANNER = b'THESEUS-RIZIN-ORACLE-4471'


@pytest.fixture(scope='module')
def fixture(tmp_path_factory):
    folder = tmp_path_factory.mktemp('rizin-fixture')
    (folder / 'gauge.c').write_text(SOURCE, encoding='ascii')
    subprocess.run([ZIG, 'cc', '-target', 'x86_64-linux-musl', '-O1', '-o', str(folder / 'gauge.elf'), str(folder / 'gauge.c')],
                   check=True, capture_output=True, cwd=folder)
    return folder / 'gauge.elf'


@pytest.fixture(scope='module')
def elf(fixture):
    with open(fixture, 'rb') as handle:
        image = ELFFile(handle)
        symbols = {symbol.name: symbol for symbol in image.get_section_by_name('.symtab').iter_symbols() if symbol.name}
        return {
            'class': image.elfclass, 'little': image.little_endian, 'machine': image['e_machine'], 'entry': image['e_entry'],
            'sections': {section.name: (section['sh_addr'], section['sh_offset'], section['sh_size'], section['sh_type'])
                         for section in image.iter_sections() if section.name},
            'symbols': {name: (symbol['st_value'], symbol['st_size'], symbol['st_info']['type'],
                               next(image.address_offsets(symbol['st_value']), None) if symbol['st_value'] else None)
                        for name, symbol in symbols.items()},
            'bytes': fixture.read_bytes(),
        }


@pytest.fixture(scope='module')
def lab(tmp_path_factory):
    root = tmp_path_factory.mktemp('rizin-lab')
    with TestClient(create_app(root / 'data'), base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        store = client.app.state.store
        (root / 'files').mkdir()
        yield Lab(client, store, store.create_project('Rizin oracle')['id'], root / 'files')


def rizin(lab, fixture, command, **parameters):
    return lab.run('gauge.elf', 'rizin.command', {'command': command, **parameters}, content=fixture.read_bytes())


def test_binary_information_matches_the_elf_header(lab, fixture, elf):
    info = rizin(lab, fixture, 'iIj')['json']
    assert (info['bintype'], info['class'], info['bits'], info['endian']) == ('elf', elf['class'] == 64 and 'ELF64', 64, 'LE' if elf['little'] else 'BE')
    assert elf['machine'] == 'EM_X86_64' and info['arch'] == 'x86'
    assert info['static'] is True and info['stripped'] is False
    entries = rizin(lab, fixture, 'iej')['json']
    assert [row['vaddr'] for row in entries] == [elf['entry']]


def test_sections_match_the_section_headers(lab, fixture, elf):
    sections = {row['name']: (row['vaddr'], row['paddr'], row['size'], row['vsize']) for row in rizin(lab, fixture, 'iSj')['json'] if row['name']}
    for name, (address, offset, size, kind) in elf['sections'].items():
        if name in sections and size:
            # size counts file bytes, vsize memory bytes: an SHT_NOBITS section such as .bss has none in the file
            assert sections[name][1:3] == (offset, 0 if kind == 'SHT_NOBITS' else size), name
            if address:
                assert sections[name][0] == address and sections[name][3] == size, name
    assert {'.text', '.rodata', '.symtab'} <= set(sections)


@pytest.mark.parametrize('name', ['gauge_leaf', 'gauge_route', 'main', 'banner'])
def test_symbols_match_the_symbol_table(lab, fixture, elf, name):
    rows = {row['name']: row for row in rizin(lab, fixture, 'isj')['json']}
    address, size, kind, offset = elf['symbols'][name]
    assert (rows[name]['vaddr'], rows[name]['size'], rows[name]['paddr']) == (address, size, offset)
    assert rows[name]['type'] == {'STT_FUNC': 'FUNC', 'STT_OBJECT': 'OBJ'}[kind]


def test_bytes_at_a_symbol_are_the_file_bytes(lab, fixture, elf):
    address, size, _, offset = elf['symbols']['banner']
    result = rizin(lab, fixture, f'p8 {size} @ {hex(address)}')
    assert bytes.fromhex(result['stdout'].strip()) == elf['bytes'][offset:offset + size] == BANNER + b'\0'


def test_strings_report_the_planted_banner_at_its_offset(lab, fixture, elf):
    rows = [row for row in rizin(lab, fixture, 'izj')['json'] if row['string'] == BANNER.decode()]
    assert [(row['paddr'], row['vaddr']) for row in rows] == [(elf['bytes'].index(BANNER), elf['symbols']['banner'][0])]


def test_analysis_finds_the_functions_and_the_calls_between_them(lab, fixture, elf):
    # The fixture carries DWARF, so analysis names functions after their debug entries (dbg.<name>).
    functions = {row['name']: row for row in rizin(lab, fixture, 'aflj', analysis='aaa')['json']}
    for name in ('gauge_leaf', 'gauge_route', 'main'):
        assert functions['dbg.' + name]['offset'] == elf['symbols'][name][0], name
        assert functions['dbg.' + name]['size'] == elf['symbols'][name][1], name
    callers = rizin(lab, fixture, 'axtj @ sym.gauge_leaf', analysis='aaa')['json']
    route, route_size = elf['symbols']['gauge_route'][:2]
    calls = [row for row in callers if row['type'] == 'CALL']
    assert len(calls) == 2 and all(route <= row['from'] < route + route_size for row in calls)
    assert {row['to'] for row in calls} == {elf['symbols']['gauge_leaf'][0]}
    disassembly = rizin(lab, fixture, 'pdfj @ sym.gauge_route', analysis='aaa')['json']
    start, size = elf['symbols']['gauge_route'][3], elf['symbols']['gauge_route'][1]
    joined = bytes.fromhex(''.join(row['bytes'] for row in disassembly['ops']))
    assert joined == elf['bytes'][start:start + len(joined)] and len(joined) <= size


def test_the_artifact_is_never_changed_and_raw_output_is_hashed(lab, fixture, elf):
    import hashlib
    result = rizin(lab, fixture, 'iIj')
    assert result['artifact']['changed'] is False
    assert result['artifact']['sha256_before'] == result['artifact']['sha256_after'] == hashlib.sha256(elf['bytes']).hexdigest()
    assert result['stdout_sha256'] == hashlib.sha256(result['stdout'].encode()).hexdigest()
    assert result['completion'] == 'complete' and result['exit_code'] == 0
    assert '-NN' in result['argv'] and 'cfg.sandbox=true' in result['argv']


def test_output_beyond_the_limit_is_cut_and_completion_is_unknown(lab, fixture):
    result = rizin(lab, fixture, 'px 65536 @ 0', max_output_bytes=256)
    assert (result['stdout_bytes'], result['stdout_truncated'], result['completion']) == (256, True, 'unknown')
    assert result['json'] is None


@pytest.mark.parametrize('command', [
    '!echo hi', 'iI; !echo hi', 'iI | more', 'iI > out.txt', 'pd 3 @@ sym.*', 'pd 3 @e:cfg.sandbox=false', 'wx 90', 'o C:/Windows/win.ini',
    'e cfg.sandbox=false', '. script.rz', '`!echo hi`', 'pd 3 @ $(echo)', 'iO d', '#!python', 'L', 'oo+', 'iI\npd 1', 'pd "x"', 'ps @ 0x10:4'])
def test_commands_outside_the_read_only_grammar_are_rejected_before_any_run(lab, fixture, command):
    with pytest.raises(ValueError):
        admit(command)
    job = lab.job('gauge.elf', fixture.read_bytes(), 'rizin.command', {'command': command})
    assert job['state'] == 'failed'


def test_every_admitted_family_keeps_its_name_and_output_modes():
    for name in COMMANDS:
        assert admit(name) == name
    assert admit('aflj') == 'aflj' and admit('afiq @ main') == 'afiq @ main'
    assert admit('  pdf   @  sym.main  ') == 'pdf @ sym.main'
    assert admit('izz~?') == 'izz~?'
