"""Static Ghidra-backed binary session tools against binaries built here and independent readers.

A small C program (known call graph, recursion, a function-pointer table, a jump table, strings, a global
table) is built with zig for ELF x86_64, PE x86_64 and ELF aarch64. The expected facts come from pyelftools
and pefile (symbols, sections, offsets), GNU objdump (x86 disassembly), the raw aarch64 instruction words,
and the C source itself. Nothing is executed. Opt-in: THESEUS_TEST_GHIDRA=1 and THESEUS_TEST_ZIG.
"""
import hashlib
import io
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time
from collections import namedtuple
from functools import cached_property

import pytest
from fastapi.testclient import TestClient

from theseus.api import create_app
from theseus.binary_analysis import engines

pefile = pytest.importorskip('pefile')
elffile = pytest.importorskip('elftools.elf.elffile')
pytestmark = pytest.mark.skipif(os.environ.get('THESEUS_TEST_GHIDRA') != '1', reason='Opt-in installed-engine integration')


def tool(variable, name, fallback=None):
    value = os.environ.get(variable) or shutil.which(name) or fallback
    return value if value and Path(value).is_file() else None


ZIG = tool('THESEUS_TEST_ZIG', 'zig')
OBJDUMP = tool('THESEUS_TEST_OBJDUMP', 'objdump', 'D:/LocalAI/tools/binutils1076/ucrt64/bin/objdump.exe')

SOURCE = r'''#include <stdio.h>
#define NI __attribute__((noinline))

const char oracle_banner[] = "THESEUS-ORACLE-BANNER-7791";
const char oracle_leaf_text[] = "leaf-string-alpha-4410";
const char oracle_mid_text[] = "mid-string-bravo-5521";
const char oracle_top_text[] = "top-string-charlie-6632";
const unsigned int oracle_table[8] = {0x11223344u, 0x55667788u, 0x99aabbccu, 0xddeeff00u,
                                      0x0badf00du, 0xcafebabeu, 0xdeadbeefu, 0x8badf00du};
volatile int oracle_counter = 5;

NI int oracle_leaf(int x) {
    oracle_counter = oracle_counter + x;
    return (int)(oracle_table[x & 7] ^ (unsigned)oracle_counter);
}

NI int oracle_loop(int n) {
    int total = 0;
    for (int i = 0; i < n; i++) total += oracle_leaf(i) % 97;
    return total;
}

NI int oracle_fib(int n) {
    if (n < 2) return n;
    return oracle_fib(n - 1) + oracle_fib(n - 2);
}

NI int oracle_switch(int v) {
    switch (v) {
    case 0: return 1000;
    case 1: return 2111;
    case 2: return 3999;
    case 3: return 4333;
    case 4: return 17;
    case 5: return 6555;
    case 6: return 123456;
    default: return -1;
    }
}

NI int oracle_route(int v) {
    switch (v) {
    case 0: return oracle_leaf(10);
    case 1: return oracle_fib(7);
    case 2: puts(oracle_leaf_text); return 2;
    case 3: return oracle_loop(3);
    case 4: return oracle_switch(4);
    case 5: oracle_counter += 77; return 5;
    default: return -1;
    }
}

NI int oracle_mid(int x) {
    puts(oracle_mid_text);
    return oracle_leaf(x) + oracle_loop(x);
}

NI int oracle_top(int x) {
    puts(oracle_top_text);
    return oracle_mid(x) + oracle_leaf(x + 1);
}

NI int oracle_handler_a(int x) { return oracle_leaf(x) + 1; }
NI int oracle_handler_b(int x) { return oracle_switch(x) + 2; }
NI int oracle_handler_c(int x) { return oracle_fib(x) + 3; }

int (*const oracle_handlers[3])(int) = {oracle_handler_a, oracle_handler_b, oracle_handler_c};

NI int oracle_dispatch(int i) { return oracle_handlers[i % 3](i); }

int main(int argc, char **argv) {
    puts(oracle_banner);
    return oracle_top(argc) + oracle_dispatch(argc + 1) + oracle_route(argc) + (int)(argv != 0);
}
'''
USER = ['oracle_leaf', 'oracle_loop', 'oracle_fib', 'oracle_switch', 'oracle_route', 'oracle_mid', 'oracle_top',
        'oracle_handler_a', 'oracle_handler_b', 'oracle_handler_c', 'oracle_dispatch', 'main']
# Direct calls written in the source. oracle_dispatch calls through oracle_handlers[]: no direct callee.
GRAPH = {'oracle_leaf': set(), 'oracle_loop': {'oracle_leaf'}, 'oracle_fib': {'oracle_fib'}, 'oracle_switch': set(),
         'oracle_route': {'oracle_leaf', 'oracle_fib', 'puts', 'oracle_loop', 'oracle_switch'},
         'oracle_mid': {'puts', 'oracle_leaf', 'oracle_loop'}, 'oracle_top': {'puts', 'oracle_mid', 'oracle_leaf'},
         'oracle_handler_a': {'oracle_leaf'}, 'oracle_handler_b': {'oracle_switch'}, 'oracle_handler_c': {'oracle_fib'},
         'oracle_dispatch': set(), 'main': {'oracle_top', 'oracle_dispatch', 'oracle_route', 'puts'}}
HANDLERS = ['oracle_handler_a', 'oracle_handler_b', 'oracle_handler_c']
STRINGS = {'oracle_banner': 'THESEUS-ORACLE-BANNER-7791', 'oracle_leaf_text': 'leaf-string-alpha-4410',
           'oracle_mid_text': 'mid-string-bravo-5521', 'oracle_top_text': 'top-string-charlie-6632'}
STRING_USER = {'oracle_banner': 'main', 'oracle_leaf_text': 'oracle_route', 'oracle_mid_text': 'oracle_mid',
               'oracle_top_text': 'oracle_top'}
PARAMETER = {'oracle_leaf': 'x', 'oracle_loop': 'n', 'oracle_fib': 'n', 'oracle_switch': 'v', 'oracle_route': 'v',
             'oracle_mid': 'x', 'oracle_top': 'x', 'oracle_handler_a': 'x', 'oracle_handler_b': 'x',
             'oracle_handler_c': 'x', 'oracle_dispatch': 'i'}
TABLE = struct.pack('<8I', 0x11223344, 0x55667788, 0x99aabbcc, 0xddeeff00, 0x0badf00d, 0xcafebabe, 0xdeadbeef, 0x8badf00d)
RELOCATED = ('.got', '.got.plt')
TARGETS = {'elf': ('x86_64-linux-gnu', 'oracle_x64.elf'), 'pe': ('x86_64-windows-gnu', 'oracle_x64.exe'),
           'arm': ('aarch64-linux-gnu', 'oracle_a64.elf')}


def plain(name):
    """Ghidra qualifies imports and thunks as '<EXTERNAL>::puts' or 'DLL.DLL::puts'; the call graph uses the bare name."""
    return name.split('::')[-1]


def unwrap(result):
    return result['value'] if isinstance(result, dict) and 'value' in result else result


def number(address):
    return int(address, 16)


class Session:
    def __init__(self, lab, path):
        self.lab = lab
        artifact = lab.client.post(lab.base + '/artifacts', json={'path': str(path)}).json()
        job = lab.wait(lab.agent('theseus_binary_open', project_id=lab.project, artifact_id=artifact['id'], options={}))
        assert job['state'] == 'finished', job
        self.id, self.info, self.job = job['id'], job['result']['info'], job

    def run(self, operation, **parameters):
        job = self.lab.wait(self.lab.agent('theseus_binary_call', session_id=self.id, operation=operation, parameters=parameters))
        return job, (self.lab.client.get('/api/jobs/' + job['id'] + '/analysis.json').json()['result'] if job['state'] == 'finished' else None)

    def call(self, operation, **parameters):
        job, result = self.run(operation, **parameters)
        assert job['state'] == 'finished', (operation, parameters, job['result'].get('error'))
        return result

    def fails(self, operation, **parameters):
        job, _ = self.run(operation, **parameters)
        assert job['state'] == 'failed', (operation, parameters, job['state'])
        return job['result']['error']

    def close(self):
        return self.lab.wait(self.lab.agent('theseus_binary_close', session_id=self.id))


class Lab:
    def __init__(self, client, project, built):
        self.client, self.project, self.built, self.targets = client, project, built, {}
        self.base = '/api/projects/' + project

    def agent(self, name, **arguments):
        response = self.client.post('/api/agent/call', json={'tool': name, 'arguments': arguments})
        response.raise_for_status()
        return response.json()['result']

    def wait(self, job):
        started = time.monotonic()
        while job['state'] in ('queued', 'running'):
            assert time.monotonic() - started < 600, job
            time.sleep(.1)
            job = self.client.get('/api/jobs/' + job['id']).json()
        return job

    def target(self, kind):
        if kind not in self.targets:
            self.targets[kind] = Target(self, kind, self.built[kind])
        return self.targets[kind]


Row = namedtuple('Row', 'addr mnemonic branch label rip text')
PREFIXES = {'rep', 'repz', 'repnz', 'repe', 'repne', 'lock', 'cs', 'ds', 'es', 'ss', 'fs', 'gs', 'data16', 'notrack', 'bnd', 'addr32'}
# Same condition code, different spelling between GNU and Ghidra mnemonics (representation only).
SYNONYM = {'jb': 'jc', 'jnae': 'jc', 'jae': 'jnc', 'jnb': 'jnc', 'je': 'jz', 'jne': 'jnz', 'cmovb': 'cmovc', 'cmovae': 'cmovnc',
           'cmove': 'cmovz', 'cmovne': 'cmovnz', 'sete': 'setz', 'setne': 'setnz', 'movabs': 'mov'}


def objdump_rows(path, start, stop):
    out = subprocess.run([OBJDUMP, '-d', '-M', 'intel', '--no-show-raw-insn', '--start-address=%#x' % start,
                          '--stop-address=%#x' % stop, str(path)], capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.splitlines():
        found = re.match(r'\s*([0-9a-f]+):\t(.+)$', line)
        if not found:
            continue
        body, _, comment = found[2].partition('#')
        words = body.split()
        first = 0
        while words[first] in PREFIXES or words[first].startswith('rex'):
            first += 1
        mnemonic, operand = words[first], ' '.join(words[first + 1:])
        # ELF output prints bare hex, PE output prints 0x-prefixed hex.
        branch = re.fullmatch(r'(?:0x)?([0-9a-f]+)(?: <([^>]*)>)?', operand) if mnemonic == 'call' or mnemonic.startswith('j') else None
        rip = re.match(r'\s*(?:0x)?([0-9a-f]+)', comment)
        rows.append(Row(int(found[1], 16), SYNONYM.get(mnemonic, mnemonic), int(branch[1], 16) if branch else None,
                        branch[2] if branch else None, int(rip[1], 16) if rip else None, body.strip()))
    return rows


def ghidra_listing(lines):
    parsed = []
    for line in lines:
        address, text = line.split(': ', 1)
        words = text.split()
        first = 0
        while words[first].lower() in PREFIXES:
            first += 1
        parsed.append((number(address), words[first].lower(), text))
    return parsed


def assert_listing_matches(rows, lines, where):
    listing = ghidra_listing(lines)
    assert [row.addr for row in rows] == [address for address, _, _ in listing], where
    for row, (address, mnemonic, text) in zip(rows, listing):
        assert mnemonic == row.mnemonic, (where, hex(address), row.text, text)
        if row.branch is not None:
            assert number(re.search(r'0x[0-9a-f]+', text)[0]) == row.branch, (where, hex(address), row.text, text)
        if row.rip is not None:
            assert row.rip in {number(item) for item in re.findall(r'0x[0-9a-f]+', text)}, (where, hex(address), row.text, text)


class ElfFacts:
    def __init__(self, data):
        self.data = data
        self.elf = elf = elffile.ELFFile(io.BytesIO(data))
        symbols = [s for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name and s['st_shndx'] != 'SHN_UNDEF']
        self.funcs = {s.name: (s['st_value'], s['st_size']) for s in symbols if s['st_info']['type'] == 'STT_FUNC'}
        self.objects = {s.name: (s['st_value'], s['st_size']) for s in symbols if s['st_info']['type'] == 'STT_OBJECT'}
        self.imports = sorted(s.name for s in elf.get_section_by_name('.dynsym').iter_symbols() if s['st_shndx'] == 'SHN_UNDEF' and s.name)
        self.blocks = [dict(name=s.name, start=s['sh_addr'], size=s['sh_size'], offset=s['sh_offset'], raw=s['sh_size'] if s['sh_type'] != 'SHT_NOBITS' else 0,
                            write=bool(s['sh_flags'] & 1), exec=bool(s['sh_flags'] & 4), initialized=s['sh_type'] != 'SHT_NOBITS')
                       for s in elf.iter_sections() if s['sh_flags'] & 2 and s['sh_size']]
        self.loads = [(g['p_vaddr'], g['p_offset'], g['p_filesz'], g['p_memsz']) for g in elf.iter_segments() if g['p_type'] == 'PT_LOAD']
        self.relro = [(g['p_vaddr'], g['p_vaddr'] + g['p_memsz']) for g in elf.iter_segments() if g['p_type'] == 'PT_GNU_RELRO']
        self.base = min(vaddr for vaddr, _, _, _ in self.loads)

    def offset_of(self, address):
        for vaddr, offset, filesz, _ in self.loads:
            if vaddr <= address < vaddr + filesz:
                return offset + address - vaddr

    def regions(self, skip=()):
        """File-backed runs: one per section plus the loaded header bytes that belong to no section."""
        out = [(b['start'], self.data[b['offset']:b['offset'] + b['raw']]) for b in self.blocks if b['initialized'] and b['name'] not in skip]
        for vaddr, offset, filesz, _ in self.loads:
            cursor = vaddr
            covered = sorted((b['start'], b['start'] + b['raw']) for b in self.blocks if b['initialized'] and vaddr <= b['start'] < vaddr + filesz)
            for start, end in covered + [(vaddr + filesz, vaddr + filesz)]:
                if start > cursor:
                    out.append((cursor, self.data[offset + cursor - vaddr:offset + start - vaddr]))
                cursor = max(cursor, end)
        return out

    def plt_name(self, target):
        """aarch64 PLT: a 32-byte header, then 16-byte stubs in .rela.plt order."""
        plt, relocations = self.elf.get_section_by_name('.plt'), self.elf.get_section_by_name('.rela.plt')
        dynsym = self.elf.get_section_by_name('.dynsym')
        index = (target - plt['sh_addr'] - 32) // 16
        return dynsym.get_symbol(list(relocations.iter_relocations())[index]['r_info_sym']).name


class PeFacts:
    def __init__(self, data):
        self.data = data
        pe = pefile.PE(data=data)
        self.base = pe.OPTIONAL_HEADER.ImageBase
        headers = pe.OPTIONAL_HEADER.SizeOfHeaders
        self.blocks = [dict(name='Headers', start=self.base, size=headers, offset=0, raw=headers, write=False, exec=False, initialized=True)]
        for s in pe.sections:
            self.blocks.append(dict(name=s.Name.rstrip(b'\0').decode(), start=self.base + s.VirtualAddress, size=s.Misc_VirtualSize,
                                    offset=s.PointerToRawData, raw=s.SizeOfRawData, write=bool(s.Characteristics & 0x80000000),
                                    exec=bool(s.Characteristics & 0x20000000), initialized=s.SizeOfRawData > 0))
        self.pdata = {self.base + e.struct.BeginAddress: self.base + e.struct.EndAddress for e in pe.DIRECTORY_ENTRY_EXCEPTION}
        self.relro = []

    def offset_of(self, address):
        for b in self.blocks:
            if b['start'] <= address < b['start'] + b['raw']:
                return b['offset'] + address - b['start']

    def address_of(self, offset):
        for b in self.blocks:
            if b['offset'] <= offset < b['offset'] + b['raw']:
                return b['start'] + offset - b['offset']

    def regions(self, skip=()):
        return [(b['start'], self.data[b['offset']:b['offset'] + b['raw']]) for b in self.blocks if b['initialized'] and b['name'] not in skip]


class Target:
    def __init__(self, lab, kind, path):
        self.kind, self.path = kind, path
        self.data = path.read_bytes()
        self.sha = hashlib.sha256(self.data).hexdigest()
        self.facts = PeFacts(self.data) if kind == 'pe' else ElfFacts(self.data)
        self.s = Session(lab, path)
        self.row_cache = {}

    @cached_property
    def procs(self):
        return self.s.call('list_procedures')

    @cached_property
    def names(self):
        return {r['address']: plain(r['value']) for r in self.procs}

    @cached_property
    def funcs(self):
        if self.kind != 'pe':
            return {name: self.facts.funcs[name] for name in USER}
        # PE symbols come from the PDB read by Ghidra; pdata and string references check them independently.
        by_name = {r['value']: r['address'] for r in self.procs if not r['procedure']['external'] and not r['procedure']['thunk']}
        return {name: (number(by_name[name]), unwrap(self.s.call('procedure_info', procedure=by_name[name]))['length']) for name in USER}

    @cached_property
    def places(self):
        if self.kind != 'pe':
            return {name: value[0] for name, value in self.facts.objects.items() if name.startswith('oracle_')}
        places = {name: self.facts.address_of(self.data.index(text.encode() + b'\0')) for name, text in STRINGS.items()}
        places['oracle_table'] = self.facts.address_of(self.data.index(TABLE))
        places['oracle_handlers'] = next(r.rip for r in self.rows('oracle_dispatch') if r.rip is not None)
        return places

    def rows(self, name):
        if name not in self.row_cache:
            entry, size = self.funcs[name]
            self.row_cache[name] = objdump_rows(self.path, entry, entry + size)
        return self.row_cache[name]

    def read(self, address, length):
        offset = self.facts.offset_of(address)
        return self.data[offset:offset + length]

    def user_at(self, address):
        return next((name for name, (entry, size) in self.funcs.items() if entry <= address < entry + size), None)

    def block_at(self, address):
        return next((b for b in self.facts.blocks if b['start'] <= address < b['start'] + max(b['size'], b['raw'])), None)

    def decode(self, name):
        """aarch64: (address, kind, target) for the branch instructions found in the raw words."""
        entry, size = self.funcs[name]
        out = []
        for index, word in enumerate(struct.unpack('<%dI' % (size // 4), self.read(entry, size))):
            pc, imm = entry + 4 * index, word & 0x3ffffff
            imm = (imm - (1 << 26) if imm & 0x2000000 else imm) * 4
            if word >> 26 == 0b100101: out.append((pc, 'bl', pc + imm))
            elif word >> 26 == 0b000101: out.append((pc, 'b', pc + imm))
            elif word == 0xd65f03c0: out.append((pc, 'ret', None))
            elif word & 0xfffffc1f == 0xd61f0000: out.append((pc, 'br', None))
            elif word & 0xfffffc1f == 0xd63f0000: out.append((pc, 'blr', None))
        return out

    def call_sites(self, name, tails=True):
        """(address, target) of direct calls; with tails, also unconditional jumps to another function's entry
        (clang compiles `return f(x);` as a jump, and Ghidra treats such a jump as a terminal call)."""
        entry, size = self.funcs[name]
        entries = {e for e, _ in self.funcs.values()}
        def tail(target):
            return tails and target in entries and not entry <= target < entry + size
        if self.kind == 'arm':
            return [(pc, target) for pc, kind, target in self.decode(name) if kind == 'bl' or (kind == 'b' and tail(target))]
        return [(row.addr, row.branch) for row in self.rows(name) if row.branch is not None and (row.mnemonic == 'call' or (row.mnemonic == 'jmp' and tail(row.branch)))]

    def callee_name(self, target, name):
        if self.kind == 'pe':
            return self.names[hex(target)]
        for symbol, (address, _) in self.facts.funcs.items():
            if address == target:
                return symbol
        if self.kind == 'arm':
            return self.facts.plt_name(target)
        return next(row.label for row in self.rows(name) if row.branch == target).split('@')[0]

    def disassembled_graph(self):
        return {name: {self.callee_name(target, name) for _, target in self.call_sites(name)} for name in USER}


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    if ZIG is None or OBJDUMP is None:
        pytest.skip('Requires zig (THESEUS_TEST_ZIG) and GNU objdump (THESEUS_TEST_OBJDUMP)')
    root = tmp_path_factory.mktemp('ghidra-oracle')
    (root / 'oracle.c').write_text(SOURCE, encoding='utf8')
    env = {**os.environ, 'ZIG_GLOBAL_CACHE_DIR': str(root / 'zig-global'), 'ZIG_LOCAL_CACHE_DIR': str(root / 'zig-local')}
    out = {}
    for kind, (triple, name) in TARGETS.items():
        subprocess.run([ZIG, 'cc', '-target', triple, '-O1', '-o', name, 'oracle.c'], cwd=root, env=env, check=True, capture_output=True, timeout=900)
        out[kind] = root / name
    return out


@pytest.fixture(scope='module')
def lab(tmp_path_factory, built):
    if not engines()['available']:
        pytest.skip('Requires installed Ghidra/JDK')
    with TestClient(create_app(tmp_path_factory.mktemp('theseus-data')), base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        project = client.post('/api/projects', json={'name': 'Ghidra oracle'}).json()
        lab = Lab(client, project['id'], built)
        yield lab
        for item in lab.targets.values():
            try:
                item.s.close()
            except Exception:
                pass


@pytest.fixture(scope='module', params=['elf', 'pe', 'arm'])
def target(request, lab):
    return lab.target(request.param)


@pytest.fixture(scope='module')
def elf(lab):
    return lab.target('elf')


def inclusive_range(entry, size):
    return {'start': hex(entry), 'end': hex(entry + size - 1)}


# ---------------------------------------------------------------- session, catalog, segments

OPERATIONS = ['address_name', 'comment', 'current_address', 'current_procedure', 'current_document', 'goto_address', 'inline_comment',
              'list_bookmarks', 'list_documents', 'list_names', 'list_procedures', 'list_segments', 'list_strings', 'next_address',
              'prev_address', 'procedure_address', 'procedure_assembly', 'procedure_callees', 'procedure_callers', 'procedure_info',
              'read_function_instructions', 'search_bytes', 'read_bytes', 'address_to_file_offset', 'procedure_references',
              'procedure_pseudo_code', 'resolve_containing_procedure', 'search_procedures', 'search_strings', 'set_address_name',
              'set_addresses_names', 'set_bookmark', 'set_comment', 'set_inline_comment', 'unset_bookmark', 'xrefs', 'batch_decompile',
              'get_call_graph', 'analyze_function', 'inspect_native_api', 'read_binary_inventory_summary', 'trace_call_path',
              'trace_native_values', 'annotate_native_function', 'inspect_native_load_image', 'inspect_native_data_type',
              'inspect_native_instruction', 'resolve_native_call_targets']
READ_ONLY = [name for name in OPERATIONS if not name.startswith(('set_', 'unset_', 'annotate', 'goto', 'next_', 'prev_'))]


def test_session_identity_and_listing(lab, target):
    t, s = target, target.s
    language = {'elf': 'x86:LE:64:default', 'pe': 'x86:LE:64:default', 'arm': 'AARCH64:LE:64:v8A'}[t.kind]
    assert (s.info['target']['name'], s.info['target']['sha256'], s.info['target']['language_id']) == (t.path.name, t.sha, language)
    assert s.info['target']['image_base'] == hex(t.facts.base) and s.info['analysis_complete'] and not s.info['analysis_timed_out']
    mine = next(row for row in lab.agent('theseus_binary_sessions', project_id=lab.project)['sessions'] if row['id'] == s.id)
    assert mine['result']['session_state'] == 'open' and mine['result']['artifact_sha256'] == t.sha
    assert unwrap(s.call('current_document')) == t.path.name and unwrap(s.call('list_documents')) == [t.path.name]
    summary = s.call('read_binary_inventory_summary')
    assert summary['document'] == t.path.name and summary['segments'] == unwrap(s.call('list_segments'))
    if t.kind != 'pe':
        assert sorted(plain(r['value']) for r in t.procs if r['address'].startswith('EXTERNAL')) == t.facts.imports


def test_catalog_names_every_operation_and_its_parameters_are_callable(lab, elf):
    catalog = {row['name']: row['parameters'] for row in lab.client.get('/api/binary-sessions/catalog').json()['operations']}
    assert set(OPERATIONS) <= set(catalog)
    sample = {'procedure': 'oracle_leaf', 'address': hex(elf.funcs['oracle_leaf'][0]), 'pattern': 'oracle', 'length': 8, 'limit': 5,
              'from_procedure': 'main', 'to_procedure': 'oracle_leaf', 'procedures': ['oracle_leaf']}
    rejected = {}
    for name in READ_ONLY:
        # Only keys the catalog advertises are supplied; the catalog defaults fill the rest.
        parameters = {key: ('e8' if (name, key) == ('search_bytes', 'pattern') else sample[key]) for key in catalog[name] if key in sample}
        job, _ = elf.s.run(name, **parameters)
        if job['state'] != 'finished':
            rejected[name] = (parameters, job['result'].get('error'))
    assert not rejected


def test_segments_match_container_sections(target):
    t = target
    got = {r['name']: r for r in unwrap(t.s.call('list_segments'))}
    for b in t.facts.blocks:
        r = got[b['name']]
        length = number(r['end']) - number(r['start'])
        assert number(r['start']) == b['start'], b['name']
        # Ghidra maps a PE section over the larger of its virtual size and file-aligned raw size.
        assert (b['size'] <= length <= max(b['size'], b['raw'])) if t.kind == 'pe' else length == b['size'], (b['name'], length, b['size'], b['raw'])
        # PT_GNU_RELRO ranges are read-only once relocated; Ghidra reports that runtime protection for initialized
        # sections. The NOBITS .relro_padding inside the range keeps its section flag (writable) in Ghidra.
        relro = b['initialized'] and any(low <= b['start'] < high for low, high in t.facts.relro)
        assert (r['readable'], r['writable'], r['executable'], r['initialized']) == (True, b['write'] and not relro, b['exec'], b['initialized']), b['name']
    if t.kind != 'pe':
        # Non-loaded sections (.comment, ...) are overlay blocks addressed as 'name:0x0'; they are not part of the load image.
        loaded = {n: (number(r['start']), number(r['end'])) for n, r in got.items() if re.fullmatch(r'0x[0-9a-f]+', r['start'])}
        # Ghidra adds 'segment_N.M' blocks for PT_LOAD bytes that belong to no section (ELF headers, tail after the last section).
        # The synthetic EXTERNAL block holds one pointer-sized slot per undefined dynamic symbol and is outside the container.
        external = loaded.pop('EXTERNAL', None)
        assert ((external[1] - external[0]) if external else 0) == 8 * len(t.facts.imports)
        sections = sorted(span for n, span in loaded.items() if not n.startswith('segment_'))
        extras = sorted(span for n, span in loaded.items() if n.startswith('segment_'))
        assert sections == sorted((b['start'], b['start'] + b['size']) for b in t.facts.blocks)
        for start, end in sections + extras:
            assert any(vaddr <= start and end <= vaddr + memsz for vaddr, _, _, memsz in t.facts.loads), (hex(start), hex(end))
        assert not [(a, b) for a in extras for b in sections if a[0] < b[1] and b[0] < a[1]], 'segment_* block overlaps a section'


def test_load_image_mappings_hash_the_container_bytes(target):
    t = target
    image = t.s.call('inspect_native_load_image')
    assert image['image_base'] == hex(t.facts.base)
    source = image['source_files'][0]
    assert (source['name'], source['size'], source['original_sha256']) == (t.path.name, len(t.data), t.sha)
    by_name = {b['name']: b for b in t.facts.blocks}
    changed = set()
    for mapping in image['mappings']:
        b = by_name.get(mapping['block'])
        if b is None or not mapping['initialized']:
            continue
        if mapping['file_offset'] is None:
            # The part of a PE section beyond its raw data is zero fill, not file bytes.
            assert t.kind == 'pe' and number(mapping['start']) >= b['start'] + b['raw'], mapping['block']
            assert mapping['sha256'] == hashlib.sha256(bytes(mapping['length'])).hexdigest(), mapping['block']
            continue
        assert number(mapping['start']) == b['start'] and mapping['file_offset'] == b['offset'], mapping['block']
        if mapping['sha256'] != hashlib.sha256(t.data[b['offset']:b['offset'] + mapping['length']]).hexdigest():
            changed.add(mapping['block'])
    # Ghidra writes import addresses into the GOT slots of its memory image; every other mapping is the file's bytes.
    assert changed <= {'.got', '.got.plt'}, changed
    assert (source['modified_sha256'] != source['original_sha256']) == bool(changed)


# ---------------------------------------------------------------- procedures

def test_procedures_match_container_symbols(target):
    t, s = target, target.s
    expected = t.funcs if t.kind == 'pe' else t.facts.funcs
    listed = {number(r['address']): r for r in t.procs if not r['address'].startswith('EXTERNAL')}
    for name, (entry, size) in expected.items():
        row = listed[entry]
        assert row['value'] == name and not row['procedure']['thunk'] and not row['procedure']['external'], name
        info = unwrap(s.call('procedure_info', procedure=name))
        assert (info['name'], info['entrypoint']) == (name, hex(entry)), name
        if size:  # hand-written startup code carries st_size 0; Ghidra measures the body itself
            assert info['length'] == size and info['body']['ranges'] == [inclusive_range(entry, size)] and info['body']['total_bytes'] == size, name
        assert not info['body']['non_contiguous'] and info['basicblock_count'] >= 1 and info['classification']['external'] is False
        assert s.call('procedure_address', procedure=name) == hex(entry) == s.call('procedure_address', procedure=hex(entry))
        assert unwrap(s.call('procedure_info', procedure=hex(entry)))['name'] == name
    if t.kind != 'pe':
        # Ghidra names code without a symbol FUN_<address> and shows import stubs as thunks to <EXTERNAL> names.
        for address, row in listed.items():
            if address not in {entry for entry, _ in expected.values()}:
                assert row['value'].startswith('FUN_') or row['procedure']['thunk'], row
    s.fails('procedure_address', procedure='no_such_function')


def test_pe_function_bounds_and_names_agree_with_unwind_data_and_string_references(lab):
    t = lab.target('pe')
    leaf_free = {'main', 'oracle_top', 'oracle_mid', 'oracle_route', 'oracle_dispatch'}
    for name, (entry, size) in t.funcs.items():
        if entry in t.facts.pdata:
            assert t.facts.pdata[entry] - entry == size, name
        assert t.rows(name)[-1].mnemonic in ('ret', 'jmp'), name
    assert leaf_free <= {name for name, (entry, _) in t.funcs.items() if entry in t.facts.pdata}
    for string, user in STRING_USER.items():
        references = {name for name in USER for row in t.rows(name) if row.rip == t.places[string]}
        assert references == {user}, (string, references)
    table = t.read(t.places['oracle_handlers'], 24)
    assert list(struct.unpack('<3Q', table)) == [t.funcs[name][0] for name in HANDLERS]


def test_search_procedures_filters_by_name(elf):
    s, names = elf.s, list(elf.facts.funcs)
    def found(**kwargs):
        return [(r['address'], r['value']) for r in s.call('search_procedures', **kwargs)]
    def wanted(test):
        return sorted((hex(elf.facts.funcs[n][0]), n) for n in names if test(n))
    assert sorted(found(pattern='oracle_h')) == wanted(lambda n: 'oracle_h' in n.lower()) and len(found(pattern='oracle_h')) == 3
    assert sorted(found(pattern='ORACLE_H')) == sorted(found(pattern='oracle_h'))
    assert found(pattern='ORACLE_H', case_sensitive=True) == []
    assert sorted(found(pattern='^oracle_(leaf|loop)$', mode='regex')) == wanted(lambda n: n in ('oracle_leaf', 'oracle_loop'))
    assert found(pattern='^main$', mode='regex', case_sensitive=True) == [(hex(elf.facts.funcs['main'][0]), 'main')]


def test_resolve_containing_procedure_for_addresses_inside_and_outside_functions(target):
    t, s = target, target.s
    for name, (entry, size) in t.funcs.items():
        if t.kind == 'arm':
            inside = [entry + 4 * i for i in range(size // 4)] if name in ('oracle_route', 'oracle_mid') else [entry, entry + size - 4]
        else:
            inside = [row.addr for row in t.rows(name)] if name in ('oracle_route', 'oracle_mid') else [entry, entry + size - 1]
        for address in inside:
            r = s.call('resolve_containing_procedure', address=hex(address))
            assert r['found'] and r['procedure']['name'] == name and r['procedure']['address'] == hex(entry), (name, hex(address))
        # The first byte past a function is alignment padding or the next function, never this one.
        after = s.call('resolve_containing_procedure', address=hex(entry + size))
        assert not after['found'] or after['procedure']['name'] != name
    data = t.places['oracle_banner']
    assert s.call('resolve_containing_procedure', address=hex(data)) == {'query_address': hex(data), 'found': False, 'procedure': None, 'reason': 'not_in_procedure'}
    assert s.call('resolve_containing_procedure', address='0x7f000000')['reason'] == 'outside_segments'


# ---------------------------------------------------------------- strings, bytes, offsets

def test_strings_match_the_data_section(target):
    t, s = target, target.s
    rows = s.call('list_strings')
    listed = {number(r['address']): r for r in rows if r['address'].startswith('0x')}
    for name, text in STRINGS.items():
        address = t.places[name]
        assert t.read(address, len(text) + 1) == text.encode() + b'\0'
        assert listed[address]['value'] == text and listed[address]['string']['byte_length'] == len(text) + 1, name
        assert s.call('list_strings', address=hex(address)) == [listed[address]]
        assert [r['address'] for r in s.call('search_strings', pattern=text)] == [hex(address)]
    addresses = [t.places[name] for name in STRINGS]
    assert sorted(a for a in listed if min(addresses) <= a <= max(addresses) + 32) == sorted(addresses)
    cases = [({'pattern': 'STRING'}, lambda v: 'string' in v.lower()), ({'pattern': 'STRING', 'case_sensitive': True}, lambda v: 'STRING' in v),
             ({'pattern': '^(leaf|mid)-string-\\w+-\\d+$', 'mode': 'regex'}, lambda v: re.search(r'^(leaf|mid)-string-\w+-\d+$', v, re.I)),
             ({'pattern': '^(leaf|mid)-string-\\w+-\\d+$', 'mode': 'regex', 'case_sensitive': True}, lambda v: re.search(r'^(leaf|mid)-string-\w+-\d+$', v))]
    for parameters, test in cases:
        assert sorted(r['address'] for r in s.call('search_strings', **parameters)) == sorted(r['address'] for r in rows if test(r['value'])), parameters
    assert {hex(t.places[n]) for n in ('oracle_leaf_text', 'oracle_mid_text', 'oracle_top_text')} <= {r['address'] for r in s.call('search_strings', pattern='string')}


def test_read_bytes_and_file_offsets_match_the_container(target):
    t, s = target, target.s
    probes = [(t.places[name], len(text) + 1) for name, text in STRINGS.items()] + [(t.places['oracle_table'], 32)]
    probes += [(entry, size) for entry, size in t.funcs.values()]
    for address, length in probes:
        want = t.read(address, length)
        assert len(want) == length
        assert s.call('read_bytes', address=hex(address), length=length) == {
            'address': hex(address), 'requested_bytes': length, 'returned_bytes': length, 'bytes_hex': want.hex(), 'complete': True}, hex(address)
        assert s.call('address_to_file_offset', address=hex(address)) == {'address': hex(address), 'file_offset': t.facts.offset_of(address)}
    if 'oracle_counter' in t.places:
        assert s.call('read_bytes', address=hex(t.places['oracle_counter']), length=4)['bytes_hex'] == '05000000'
    for b in t.facts.blocks:
        if b['initialized']:
            assert s.call('address_to_file_offset', address=hex(b['start']))['file_offset'] == b['offset'], b['name']
        else:
            assert 'file-backed' in s.fails('address_to_file_offset', address=hex(b['start']))
            assert s.call('read_bytes', address=hex(b['start']), length=4)['returned_bytes'] == 0
    assert 'file-backed' in s.fails('address_to_file_offset', address='0x7f000000')
    gone = s.call('read_bytes', address='0x7f000000', length=4)
    assert (gone['returned_bytes'], gone['bytes_hex'], gone['complete']) == (0, '', False)


def scan(regions, pattern, mask=None):
    """Every address whose bytes match pattern ('??' is a wildcard) under an optional hex mask, regions searched one by one."""
    tokens = [pattern[i:i + 2] for i in range(0, len(pattern), 2)]
    classes = []
    for index, token in enumerate(tokens):
        keep = 0 if token == '??' else (int(mask[2 * index:2 * index + 2], 16) if mask else 255)
        value = 0 if token == '??' else int(token, 16)
        classes.append(b'[' + b''.join(re.escape(bytes([b])) for b in range(256) if b & keep == value & keep) + b']' if keep else b'.')
    expression = re.compile(b'(?=' + b''.join(classes) + b')', re.S)
    return {start + m.start() for start, data in regions for m in expression.finditer(data)}


def test_search_bytes_matches_a_scan_of_the_container(target):
    t, s = target, target.s
    # Ghidra's memory image differs from the file in the GOT (import addresses); see the file-offset test below.
    regions = t.facts.regions(skip=RELOCATED)
    call, mask = ('e8??????00', None) if t.kind != 'arm' else ('94', 'fc')
    cases = [(STRINGS['oracle_banner'].encode().hex(), None), (TABLE[24:28].hex(), None), (TABLE[4:12].hex(), None),
             (call, mask), ('e8' if t.kind != 'arm' else '94', 'ff' if t.kind != 'arm' else 'fc'), ('40', 'f0')]
    for pattern, pattern_mask in cases:
        parameters = {'pattern': pattern, 'limit': 100000, **({'mask': pattern_mask} if pattern_mask else {})}
        result = s.call('search_bytes', **parameters)
        assert result['complete'] and result['next_cursor'] is None
        found = {number(m['address']) for m in result['matches'] if (t.block_at(number(m['address'])) or {'name': ''})['name'] not in RELOCATED}
        assert found == scan(regions, pattern, pattern_mask), parameters
    banner = t.places['oracle_banner']
    only = s.call('search_bytes', pattern=STRINGS['oracle_banner'].encode().hex())['matches']
    assert only == [{'address': hex(banner), 'segment': t.block_at(banner)['name'], 'file_offset': t.facts.offset_of(banner), 'procedure': None}]
    for match in s.call('search_bytes', pattern=call, **({'mask': mask} if mask else {}), limit=100000)['matches']:
        if t.user_at(number(match['address'])):
            assert match['procedure']['name'] == t.user_at(number(match['address'])) and match['segment'] == t.block_at(number(match['address']))['name']
            assert match['file_offset'] == t.facts.offset_of(number(match['address']))
    # Pages follow the cursor without gaps or repeats; bounds restrict the search range.
    everything = sorted(number(m['address']) for m in s.call('search_bytes', pattern=call, limit=100000, **({'mask': mask} if mask else {}))['matches'])
    pages, cursor = [], None
    while True:
        page = s.call('search_bytes', pattern=call, limit=2, **({'mask': mask} if mask else {}), **({'cursor': cursor} if cursor else {}))
        assert len(page['matches']) <= 2
        pages += [number(m['address']) for m in page['matches']]
        cursor = page['next_cursor']
        if page['complete']:
            break
        assert cursor
    assert pages == everything
    low, high = t.funcs['oracle_mid'][0], t.funcs['oracle_top'][0]
    bounded = s.call('search_bytes', pattern=call, start=hex(low), end=hex(high), limit=100000, **({'mask': mask} if mask else {}))
    assert {number(m['address']) for m in bounded['matches']} == {a for a in everything if low <= a <= high}
    assert 'constrain' in s.fails('search_bytes', pattern='????')
    s.fails('search_bytes', pattern='abc')
    s.fails('search_bytes', pattern='zz')


def test_search_bytes_file_offsets_point_at_bytes_that_match(target):
    t, s = target, target.s
    matches = s.call('search_bytes', pattern='40', mask='f0', limit=100000)['matches']
    wrong = [(m['address'], m['segment'], m['file_offset']) for m in matches
             if (m['file_offset'] is None and not m.get('memory_differs_from_file'))
             or (m['file_offset'] is not None and t.data[m['file_offset']] & 0xf0 != 0x40)]
    assert not wrong, wrong
    # Matches that exist only because the loader rewrote memory (import slots) carry no file offset and say so.
    rewritten = {m['segment'] for m in matches if m.get('memory_differs_from_file')}
    assert rewritten <= {'.got', '.got.plt'}, rewritten


# ---------------------------------------------------------------- call graph and references

def test_call_graph_matches_disassembly_and_source(target):
    t, s = target, target.s
    disassembled = t.disassembled_graph()
    # The MinGW front end injects a call to __main at the top of main; it is not in the C source.
    assert {name: callees - ({'__main'} if t.kind == 'pe' else set()) for name, callees in disassembled.items()} == GRAPH
    for name in USER:
        result = s.call('procedure_callees', procedure=name)
        assert {t.names[a] for a in result['value']} == disassembled[name], name
    for name in USER[:-1]:
        callers = {caller for caller, callees in disassembled.items() if name in callees}
        assert {t.names[a] for a in s.call('procedure_callers', procedure=name)['value']} == callers, name
    graph = s.call('get_call_graph')
    node = {n['address']: plain(n['name']) for n in graph['nodes']}
    edges = {(node.get(e['from'], e['from']), node.get(e['to'], e['to'])) for e in graph['edges']}
    assert {e for e in edges if e[0] in USER} == {(name, callee) for name in USER for callee in disassembled[name]}
    assert {n['address']: n['body']['total_bytes'] for n in graph['nodes'] if n['name'] in USER} == {hex(entry): size for entry, size in t.funcs.values()}
    assert ('oracle_fib', 'oracle_fib') in edges


def test_trace_call_path_follows_the_known_graph(target):
    s = target.s
    def hops(source, goal):
        frontier, seen = [[source]], {source}
        while frontier:
            path = frontier.pop(0)
            if path[-1] == goal:
                return path
            for callee in sorted(GRAPH.get(path[-1], ())):
                if callee not in seen:
                    seen.add(callee)
                    frontier.append(path + [callee])
    for source, goal in (('main', 'oracle_leaf'), ('main', 'oracle_fib'), ('oracle_top', 'oracle_loop'), ('oracle_route', 'oracle_switch')):
        path = s.call('trace_call_path', from_procedure=source, to_procedure=goal)
        names = [plain(n['name']) for n in path['path']]
        assert path['status'] == 'observed-static-path' and len(names) == len(hops(source, goal)), (source, goal, names)
        assert names[0] == source and names[-1] == goal and all(b in GRAPH[a] for a, b in zip(names, names[1:]))
    assert s.call('trace_call_path', from_procedure='oracle_leaf', to_procedure='main')['status'] == 'not-observed'
    shallow = s.call('trace_call_path', from_procedure='main', to_procedure='oracle_leaf', max_depth=1)
    assert shallow['status'] == 'not-observed' and shallow['depth_limited']
    assert s.call('trace_call_path', from_procedure='main', to_procedure='oracle_leaf', max_depth=2)['status'] == 'observed-static-path'
    # main reaches oracle_fib at run time through oracle_dispatch -> handler_c, but only the pointer table links them.
    assert s.call('trace_call_path', from_procedure='oracle_dispatch', to_procedure='oracle_fib')['status'] == 'not-observed'


def test_function_pointer_table_is_visible_as_data_references(target):
    t, s = target, target.s
    table = t.places['oracle_handlers']
    assert list(struct.unpack('<3Q', t.read(table, 24))) == [t.funcs[name][0] for name in HANDLERS]
    for index, name in enumerate(HANDLERS):
        references = {number(a) for a in s.call('xrefs', address=hex(t.funcs[name][0])) if a.startswith('0x')}
        assert table + 8 * index in references, name
    dispatch = {number(a) for a in s.call('xrefs', address=hex(table)) if a.startswith('0x')}
    assert any(t.user_at(a) == 'oracle_dispatch' for a in dispatch)


def test_unresolved_indirect_branch_is_not_reported_as_a_complete_call_list(target):
    t, s = target, target.s
    result = s.call('procedure_callees', procedure='oracle_dispatch')
    assert result['value'] == []
    # oracle_dispatch ends in a computed branch through oracle_handlers[]; an empty list marked 'complete' with no
    # limitation says the function calls nothing.
    assert result['limitations'] or result['relationship_coverage']['status'] != 'complete', result


def test_unresolved_computed_branch_is_listed_in_outgoing_references(target):
    references = unwrap(target.s.call('procedure_references', procedure='oracle_dispatch', direction='outgoing'))
    assert references['unresolved_calls'], 'the computed jump through oracle_handlers[] is not reported as unresolved'


def test_xrefs_match_instruction_references(target):
    t, s = target, target.s
    def sources(address):
        return {number(a) for a in s.call('xrefs', address=hex(address)) if a.startswith('0x')}
    def user(items):
        return {a for a in items if t.user_at(a)}
    if t.kind == 'arm':
        calls = {name: [(pc, target_) for pc, target_ in t.call_sites(name)] for name in USER}
        for string, name in STRING_USER.items():
            assert {t.user_at(a) for a in user(sources(t.places[string]))} == {name}, string
        for name, (entry, _) in t.funcs.items():
            assert user(sources(entry)) == {pc for items in calls.values() for pc, target_ in items if target_ == entry}, name
        return
    code = [(name, row) for name in USER for row in t.rows(name)]
    for string, name in STRING_USER.items():
        want = {row.addr for _, row in code if row.rip == t.places[string]}
        assert want and {t.user_at(a) for a in want} == {name}
        assert user(sources(t.places[string])) == want, string
    for name, (entry, _) in t.funcs.items():
        assert user(sources(entry)) == {row.addr for _, row in code if row.branch == entry}, name
    for datum in ('oracle_table', 'oracle_counter'):
        if datum not in t.places:
            continue
        want = {row.addr for _, row in code if row.rip == t.places[datum]}
        got = user(sources(t.places[datum]))
        assert want and want <= got, datum
        # Ghidra also records the instruction that dereferences the register the LEA loaded (constant propagation).
        assert all(any(t.user_at(a) == t.user_at(w) and a > w for w in want) for a in got - want), (datum, got - want)
    if t.kind == 'elf':
        outside = sources(t.funcs['oracle_leaf'][0]) - user(sources(t.funcs['oracle_leaf'][0]))
        assert outside and {t.block_at(a)['name'] for a in outside} <= {'.eh_frame_hdr', '.eh_frame'}


def test_procedure_references_describe_incoming_and_outgoing_edges(elf):
    s, t = elf.s, elf
    entry = t.funcs['oracle_leaf'][0]
    incoming = unwrap(s.call('procedure_references', procedure='oracle_leaf', direction='incoming'))
    calls = {number(r['source_address']) for r in incoming['references'] if r['kind']['call']}
    assert calls == {addr for name in USER for addr, target in t.call_sites(name) if target == entry}
    for r in incoming['references']:
        if r['kind']['call']:
            assert r['source_procedure']['name'] == t.user_at(number(r['source_address'])) and r['target_procedure']['address'] == hex(entry)
    outgoing = unwrap(s.call('procedure_references', procedure='oracle_route', direction='outgoing'))
    assert {number(r['source_address']) for r in outgoing['references'] if r['kind']['call']} == {a for a, _ in t.call_sites('oracle_route')}
    s.fails('procedure_references', procedure='oracle_route', direction='sideways')


# ---------------------------------------------------------------- instructions

def test_assembly_matches_objdump(target):
    t, s = target, target.s
    if t.kind == 'arm':
        pytest.skip('GNU objdump here has no aarch64 support; see test_aarch64_listing_matches_instruction_words')
    for name in USER:
        entry, size = t.funcs[name]
        rows = t.rows(name)
        assert rows[-1].mnemonic in ('ret', 'jmp') and rows[-1].addr + 1 <= entry + size
        listing = unwrap(s.call('procedure_assembly', procedure=name)).split('\n')
        assert_listing_matches(rows, listing, name)
        info = unwrap(s.call('read_function_instructions', procedure=name))
        assert info['procedure']['address'] == hex(entry) and info['instructions'] == listing
        assert info['procedure']['body']['ranges'] == [inclusive_range(entry, size)]


def test_aarch64_listing_matches_instruction_words(lab):
    t = lab.target('arm')
    for name in USER:
        entry, size = t.funcs[name]
        assert size % 4 == 0
        info = unwrap(t.s.call('read_function_instructions', procedure=name))
        listing = ghidra_listing(info['instructions'])
        assert [a for a, _, _ in listing] == [entry + 4 * i for i in range(size // 4)], name
        assert unwrap(t.s.call('procedure_assembly', procedure=name)).split('\n') == info['instructions']
        kinds = {pc: (kind, target) for pc, kind, target in t.decode(name)}
        for address, mnemonic, text in listing:
            if address in kinds:
                kind, target = kinds[address]
                assert mnemonic == kind and (target is None or number(re.search(r'0x[0-9a-f]+', text)[0]) == target), (name, hex(address), text)
            else:
                assert mnemonic not in ('bl', 'b', 'ret', 'br', 'blr'), (name, hex(address), text)


def test_instruction_inspection_and_call_target_resolution(target):
    t, s = target, target.s
    for name in ('oracle_mid', 'oracle_top', 'oracle_loop', 'oracle_dispatch', 'main'):
        entry, size = t.funcs[name]
        if t.kind == 'arm':
            starts = [entry + 4 * i for i in range(size // 4)]
            rows = [(a, a + 4) for a in starts]
        else:
            rows = [(r.addr, (t.rows(name)[i + 1].addr if i + 1 < len(t.rows(name)) else entry + size)) for i, r in enumerate(t.rows(name))]
        sites, tails = dict(t.call_sites(name, tails=False)), dict(t.call_sites(name))
        for address, following in rows:
            instruction = s.call('inspect_native_instruction', address=hex(address))
            assert instruction['status'] == 'decoded' and instruction['procedure'] == hex(entry) and instruction['length'] == following - address
            assert instruction['bytes'] == t.read(address, following - address).hex(), hex(address)
            resolved = s.call('resolve_native_call_targets', address=hex(address))
            if address in sites:
                assert instruction['flow']['kind'] == 'call' and not instruction['flow']['computed'], hex(address)
                assert resolved['status'] == 'direct' and [x['address'] for x in resolved['targets']] == [hex(sites[address])], hex(address)
                assert resolved['targets'][0]['procedure'] == hex(sites[address]) and resolved['procedure'] == hex(entry)
            else:
                # A tail jump is a jump instruction; the call graph counts it, the instruction-level resolver does not.
                assert resolved['status'] == 'not-call' and instruction['flow']['kind'] != 'call', hex(address)
                assert (address in tails) <= (instruction['flow']['kind'] == 'jump'), hex(address)
        if t.kind != 'arm':
            for row in t.rows(name):
                if row.mnemonic == 'jmp' and row.branch is None:
                    assert s.call('inspect_native_instruction', address=hex(row.addr))['flow']['computed']
                if row.mnemonic.startswith('j') and row.mnemonic != 'jmp':
                    assert s.call('inspect_native_instruction', address=hex(row.addr))['flow']['conditional']
        inside = rows[1][0] + 1 if rows[1][1] - rows[1][0] > 1 else None
        if inside:
            assert s.call('inspect_native_instruction', address=hex(inside))['status'] == 'not-instruction-boundary'
            assert s.call('resolve_native_call_targets', address=hex(inside))['status'] == 'unavailable'


# ---------------------------------------------------------------- decompiler and analysis dossiers

def test_pseudo_code_names_callees_strings_and_constants(target):
    t, s = target, target.s
    graph = t.disassembled_graph()
    batch = s.call('batch_decompile', procedures=USER + ['no_such_function'])
    assert [row['selector'] for row in batch] == USER + ['no_such_function'] and batch[-1]['error']
    code = {}
    for row in batch[:-1]:
        name, code[name] = row['selector'], row['result']['pseudocode']
        assert code[name] == unwrap(s.call('procedure_pseudo_code', procedure=name)), name
        for callee in graph[name]:
            assert re.search(r'\b%s\(' % re.escape(callee), code[name]), (name, callee)
        assert {plain(c['name']) for c in row['result']['callees']} == graph[name], name
        if t.kind != 'arm':
            assert [x.split(': ', 1)[0] for x in row['result']['assembly']] == [hex(r.addr) for r in t.rows(name)], name
    for string, name in STRING_USER.items():
        assert '"%s"' % STRINGS[string] in code[name], string
    # x86 and PE builds keep a jump table (switch/case in the decompiler output); the aarch64 build compares in a chain.
    selectors = re.findall(r'case (0x[0-9a-f]+|\d+):', code['oracle_route']) + re.findall(r'\bv == (0x[0-9a-f]+|\d+)\)', code['oracle_route'])
    assert {int(n, 0) for n in selectors} == {0, 1, 2, 3, 4, 5}
    for call in ('oracle_leaf(10)', 'oracle_fib(7)', 'oracle_loop(3)', 'oracle_switch(4)'):
        assert call in code['oracle_route'], call
    assert re.search(r'\b(for|while|do)\b', code['oracle_loop']) and 'oracle_leaf(' in code['oracle_loop']
    assert not re.search(r'oracle_handler_\w\(', code['oracle_dispatch']) and re.search(r'%\s*3', code['oracle_dispatch'])
    if t.kind != 'pe':
        assert 'oracle_counter' in code['oracle_route'] and 'oracle_counter' in code['oracle_leaf'] and 'oracle_table' in code['oracle_leaf']
        assert 'oracle_handlers' in code['oracle_dispatch']


def test_function_dossier_reports_signature_flow_and_neighbours(elf):
    t, s = elf, elf.s
    for name in USER:
        dossier = unwrap(s.call('analyze_function', procedure=name))
        assert dossier['procedure']['name'] == name and dossier['procedure']['body']['ranges'] == [inclusive_range(*t.funcs[name])]
        assert dossier['pseudocode'] == unwrap(s.call('procedure_pseudo_code', procedure=name))
        assert dossier['assembly'] == unwrap(s.call('procedure_assembly', procedure=name)).split('\n')
        assert {plain(c['name']) for c in dossier['callees']} == GRAPH[name], name
        if name != 'main':
            assert {plain(c['name']) for c in dossier['callers']} == {caller for caller, callees in GRAPH.items() if name in callees}, name
        api = s.call('inspect_native_api', procedure=name)
        assert api['available'] and (api['return_type']['data_type'], api['return_type']['size_bytes']) == ('int', 4), name
        assert [(p['name'], p['data_type'], p['size_bytes']) for p in api['parameters']] == (
            [('argc', 'int', 4), ('argv', 'char * *', 8)] if name == 'main' else [(PARAMETER[name], 'int', 4)]), name
        assert len(api['jump_tables']) == (1 if name == 'oracle_route' else 0), name
        assert dossier['native_api']['available'] and dossier['native_value_flow']['available']
    flow = unwrap(s.call('analyze_function', procedure='oracle_route'))['native_value_flow']['operations']
    assert {10, 7, 3, 4, 77} <= {int(v['constant_hex'], 16) for row in flow for v in row['inputs'] if v.get('constant_hex') is not None}


def test_trace_native_values_covers_the_call_sites_of_the_seed(elf):
    t, s = elf, elf.s
    values = s.call('trace_native_values', procedure='oracle_top')
    trace = values['trace']
    assert trace['seed'] == 'oracle_top' and trace['target_sha256'] == t.sha and not trace['truncated']
    operations = [n for n in trace['nodes'] if n.get('operation')]
    assert {a for a, _ in t.call_sites('oracle_top')} <= {number(n['operation']['address']) for n in operations if n['operation']['opcode'] == 'CALL'}
    assert hex(t.funcs['oracle_top'][0]) in {n['procedure'] for n in trace['nodes']}
    evidence = {row['evidence']['evidence_id'] for row in values['source_observations'] if 'evidence' in row}
    assert {n['evidence_id'] for n in trace['nodes']} <= evidence


def test_data_types_of_strings_and_the_table_follow_the_c_declarations(elf):
    t, s = elf, elf.s
    table = s.call('inspect_native_data_type', address=hex(t.places['oracle_table']))
    assert (table['status'], table['kind'], table['size_bytes'], table['array_count'], table['array_stride_bytes']) == ('available', 'array', 32, 8, 4)
    assert s.call('inspect_native_data_type', type=table['id'])['size_bytes'] == 32
    for name, text in STRINGS.items():
        item = s.call('inspect_native_data_type', address=hex(t.places[name]))
        assert (item['kind'], item['size_bytes'], item['array_count']) == ('array', len(text) + 1, len(text) + 1), name
    assert s.call('inspect_native_data_type', type='/no_such_type')['status'] == 'unavailable'
    s.fails('inspect_native_data_type', type=table['id'], address=hex(t.places['oracle_table']))


# ---------------------------------------------------------------- navigation and annotations (private copy)

@pytest.fixture(scope='module')
def scratch(lab, built, tmp_path_factory):
    folder = tmp_path_factory.mktemp('ghidra-rw')
    copy = folder / built['elf'].name
    shutil.copy(built['elf'], copy)
    return Target(lab, 'elf', copy)


def test_navigation_moves_a_cursor_in_address_order(scratch):
    t, s = scratch, scratch.s
    start = t.funcs['oracle_mid'][0]
    assert s.call('goto_address', address=hex(start)) == hex(start) == s.call('current_address')
    assert s.call('current_procedure')['name'] == 'oracle_mid'
    sequence = [start]
    for _ in range(3):
        sequence.append(number(s.call('next_address')))
        assert s.call('current_address') == hex(sequence[-1])
    assert sequence == sorted(set(sequence)) and t.user_at(sequence[-1]) == 'oracle_mid'
    for expected in reversed(sequence[:-1]):
        assert number(s.call('prev_address')) == expected
    assert number(s.call('next_address', address=hex(start))) > start > number(s.call('prev_address', address=hex(start)))
    s.fails('goto_address', address='0x7f000000')


def test_names_comments_and_bookmarks_round_trip_inside_the_session(scratch):
    t, s = scratch, scratch.s
    table, leaf, banner, top = t.places['oracle_table'], t.funcs['oracle_leaf'][0], t.places['oracle_banner'], t.funcs['oracle_top'][0]
    baseline = {'procedures': s.call('list_procedures'), 'names': [(r['address'], r['value']) for r in s.call('list_names')]}
    assert s.call('set_address_name', address=hex(table), name='renamed_table') is True
    assert s.call('address_name', address=hex(table)) == 'renamed_table'
    assert [r['value'] for r in s.call('list_names', address=hex(table))] == ['renamed_table']
    leaf_code = unwrap(s.call('procedure_pseudo_code', procedure='oracle_leaf'))
    assert 'renamed_table' in leaf_code and 'oracle_table' not in leaf_code
    assert s.call('set_address_name', address=hex(leaf), name='renamed_leaf') is True
    assert s.call('procedure_address', procedure='renamed_leaf') == hex(leaf)
    s.fails('procedure_address', procedure='oracle_leaf')
    assert [r['address'] for r in s.call('search_procedures', pattern='renamed_leaf')] == [hex(leaf)]
    assert unwrap(s.call('procedure_info', procedure=hex(leaf)))['name'] == 'renamed_leaf'
    assert {r['address'] for r in s.call('list_procedures') if r['value'] == 'renamed_leaf'} == {hex(leaf)}
    top_code = unwrap(s.call('procedure_pseudo_code', procedure='oracle_top'))
    assert 'renamed_leaf(' in top_code and 'oracle_leaf(' not in top_code
    assert s.call('set_addresses_names', names={hex(banner): 'renamed_banner', '0x7f000000': 'unmapped'}) == {hex(banner): True, '0x7f000000': False}
    assert s.call('address_name', address=hex(banner)) == 'renamed_banner'
    s.fails('set_address_name', address='0x7f000000', name='unmapped')
    for address, name in ((table, 'oracle_table'), (leaf, 'oracle_leaf'), (banner, 'oracle_banner')):
        assert s.call('set_address_name', address=hex(address), name=name) is True
    assert s.call('list_procedures') == baseline['procedures']
    assert [(r['address'], r['value']) for r in s.call('list_names')] == baseline['names']

    plate, inline = 'Plate: línea 1\nlínea 2 — año 779', 'En línea: ñandú'
    assert s.call('set_comment', address=hex(leaf), text=plate) == plate and s.call('set_inline_comment', address=hex(leaf), text=inline) == inline
    assert (s.call('comment', address=hex(leaf)), s.call('inline_comment', address=hex(leaf))) == (plate, inline)
    assert not s.call('comment', address=hex(top)) and not s.call('inline_comment', address=hex(top))
    assert 'año 779' in str(unwrap(s.call('analyze_function', procedure='oracle_leaf'))['comments'])
    s.call('set_comment', address=hex(leaf), text='')
    s.call('set_inline_comment', address=hex(leaf), text='')
    assert not s.call('comment', address=hex(leaf)) and not s.call('inline_comment', address=hex(leaf))
    s.fails('set_comment', address='0x7f000000', text='x')

    assert s.call('list_bookmarks') == []
    assert s.call('set_bookmark', address=hex(leaf), text='Revisar entrada') is True
    assert s.call('set_bookmark', address=hex(table), text='tabla', category='Oráculo') is True
    first = {'address': hex(leaf), 'type': 'Note', 'category': 'Theseus', 'text': 'Revisar entrada'}
    second = {'address': hex(table), 'type': 'Note', 'category': 'Oráculo', 'text': 'tabla'}
    assert sorted(s.call('list_bookmarks'), key=lambda m: m['address']) == sorted([first, second], key=lambda m: m['address'])
    assert s.call('list_bookmarks', category='Theseus') == [first] and s.call('list_bookmarks', category='Oráculo') == [second]
    assert s.call('list_bookmarks', type='Warning') == []
    s.call('set_bookmark', address=hex(leaf), text='Otra nota')
    assert s.call('list_bookmarks', category='Theseus') == [{**first, 'text': 'Otra nota'}]
    assert s.call('unset_bookmark', address=hex(leaf)) is True
    assert s.call('list_bookmarks') == [second]
    assert s.call('unset_bookmark', address=hex(table), category='Oráculo') is True
    assert s.call('list_bookmarks') == []


def test_annotations_never_touch_the_original_file(scratch, built):
    t, s = scratch, scratch.s
    top = t.funcs['oracle_top'][0]
    result = s.call('annotate_native_function', procedure='oracle_top', name='annotated_top', comment='Nota año 779', inline_comment='En línea')
    assert result['effects']['source_bytes_modified'] is False
    assert (result['annotations']['address'], result['annotations']['name'], result['annotations']['comment']) == (hex(top), 'annotated_top', 'Nota año 779')
    assert s.call('procedure_address', procedure='annotated_top') == hex(top)
    assert s.call('comment', address=hex(top)) == 'Nota año 779' and s.call('inline_comment', address=hex(top)) == 'En línea'
    assert 'annotated_top(' in unwrap(s.call('procedure_pseudo_code', procedure='main'))
    assert s.call('set_address_name', address=hex(top), name='oracle_top') is True
    assert s.call('read_bytes', address=hex(top), length=t.funcs['oracle_top'][1])['bytes_hex'] == t.read(top, t.funcs['oracle_top'][1]).hex()
    assert s.call('inspect_native_load_image')['source_files'][0]['original_sha256'] == t.sha
    assert hashlib.sha256(t.path.read_bytes()).hexdigest() == t.sha == hashlib.sha256(built['elf'].read_bytes()).hexdigest()


def test_closing_a_session_ends_it(lab, scratch):
    job = scratch.s.close()
    assert job['state'] == 'finished'
    mine = next(row for row in lab.agent('theseus_binary_sessions', project_id=lab.project)['sessions'] if row['id'] == scratch.s.id)
    assert mine['result']['session_state'] == 'closed'
    response = lab.client.post('/api/agent/call', json={'tool': 'theseus_binary_call', 'arguments': {
        'session_id': scratch.s.id, 'operation': 'current_address', 'parameters': {}}})
    assert response.status_code == 400 and 'not open' in response.json()['detail']
