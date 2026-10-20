"""Original byte fixtures and a separately decoded compiler-produced ELF."""
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from theseus.elf_layout import ElfReader, inspect_layout

ROOT = Path(__file__).resolve().parents[1]


def fixture_elf(kind=1, relr=(0x2000, 0b1011), extended=False):
    names = b'\0.text\0.strtab\0.symtab\0.rela.text\0.relr.dyn\0.shstrtab\0'
    strings = b'\0original_rule\0bad\xffname\0__stack_chk_fail\0'
    symbol = lambda name, info, sh, val, size: struct.pack('<IBBHQQ', name, info, 0, sh, val, size)
    symbols = bytes(24) + symbol(1, 0x12, 1, 0xfffffffffffffff0, 8) + symbol(15, 0x11, 1, 0, 8) + symbol(24, 0x12, 0, 0, 0)
    relocs = struct.pack('<QQq', 0x2008, (1 << 32) | 7, -(1 << 63)) + struct.pack('<QQq', 0x2010, 8, 0)
    bodies = [b'', b'\xc3', strings, symbols, relocs, b''.join(struct.pack('<Q', n) for n in relr), names]
    types = [0, 1, 3, 2, 4, 19, 3]
    raw = bytearray(64); sections=[]
    for i, body in enumerate(bodies):
        at=len(raw);raw.extend(body)
        name=0 if i==0 else names.index([b'',b'.text',b'.strtab',b'.symtab',b'.rela.text',b'.relr.dyn',b'.shstrtab'][i])
        sections.append([name,types[i],6 if i==1 else 0,0,at,len(body),2 if i==3 else 3 if i==4 else 0,1 if i==4 else 0,8,24 if i in {3,4} else 8 if i==5 else 0])
    shoff=len(raw)
    if extended: sections[0][5]=len(sections);sections[0][6]=6
    raw.extend(b''.join(struct.pack('<IIQQQQIIQQ',*s) for s in sections))
    raw[:64]=struct.pack('<16sHHIQQQIHHHHHH',b'\x7fELF\x02\x01\x01'+bytes(9),kind,62,1,0,0,shoff,0,64,56,0,64,0 if extended else len(sections),0xffff if extended else 6)
    return bytes(raw)


@pytest.fixture(scope='module')
def schema_validator(tmp_path_factory):
    folder=tmp_path_factory.mktemp('elf-schema');target=folder/'validate.cjs'
    script="""const {buildSync}=require('./node_modules/esbuild');
    buildSync({stdin:{contents:`import {readFileSync} from 'node:fs';
      import {binaryLayoutSchema} from './src/domain/native/binaryLayout.ts';
      for(const path of process.argv.slice(2)){const value=JSON.parse(readFileSync(path,'utf8'));delete value.original_records;binaryLayoutSchema.parse(value);}`,
      resolveDir:process.cwd(),sourcefile:'elf-validator.ts',loader:'ts'},platform:'node',format:'cjs',bundle:true,outfile:process.argv[1]});"""
    subprocess.run(['node','-e',script,str(target)],cwd=ROOT/'software_native/engine',check=True,capture_output=True)
    def validate(value):
        path=folder/(hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()+'.json')
        path.write_text(json.dumps(value),encoding='utf8')
        checked=subprocess.run(['node',str(target),str(path)],capture_output=True,text=True)
        assert checked.returncode==0,checked.stderr
    return validate


@pytest.mark.parametrize('kind',[1,2,3])
@pytest.mark.parametrize('extended',[False,True])
def test_original_ranges_symbols_and_relr(kind,extended,schema_validator):
    raw=fixture_elf(kind,extended=extended);value=ElfReader(raw).parse('original.elf');schema_validator(value)
    assert value['artifact']['sha256']==hashlib.sha256(raw).hexdigest()
    assert value['symbols'][1]['value']=='0xfffffffffffffff0'
    assert value['symbols'][1]['value_meaning']==('section-offset' if kind==1 else 'linked-virtual-address')
    assert base64.b64decode(value['symbols'][2]['name']['bytes_base64'])==b'bad\xffname'
    assert value['relocations'][0]['addend']==str(-(1<<63))
    assert value['relocations'][1]['symbol_reference_meaning']=='zero-symbol-value'
    assert value['packed_relative_relocations'][0]['entries']==[
        {'decoded_index':0,'reported_offset':'0x2000'},{'decoded_index':1,'reported_offset':'0x2008'},{'decoded_index':2,'reported_offset':'0x2018'}]
    for record in value['original_records']:
        start=int(record['location']['offset'],16);size=int(record['location']['bytes'],16)
        assert base64.b64decode(record['bytes_base64'])==raw[start:start+size]
        assert record['sha256']==hashlib.sha256(raw[start:start+size]).hexdigest()
    assert value['runtime_load_base'] is None and value['relocation_inventory_completeness']=='unknown'


@pytest.mark.parametrize('words',[(3,), (0xfffffffffffffffe, 3)])
def test_invalid_relr_is_rejected(words):
    with pytest.raises(ValueError,match='RELR'):ElfReader(fixture_elf(relr=words)).parse('bad.elf')


def test_bad_physical_and_symbol_references():
    raw=bytearray(fixture_elf());shoff=struct.unpack_from('<Q',raw,40)[0]
    struct.pack_into('<Q',raw,shoff+64+24,len(raw)+1)
    with pytest.raises(ValueError,match='range'):ElfReader(bytes(raw)).parse('bad.elf')
    raw=bytearray(fixture_elf());struct.pack_into('<I',raw,shoff+3*64+40,99)
    with pytest.raises(ValueError,match='section index'):ElfReader(bytes(raw)).parse('bad.elf')


def test_extended_symbol_indices_and_unused_headers(schema_validator):
    raw=bytearray(fixture_elf());shoff=struct.unpack_from('<Q',raw,40)[0]
    symoff=struct.unpack_from('<Q',raw,shoff+3*64+24)[0]
    # Reuse the RELR payload section as a full SHNDX table; the raw symbol still
    # retains SHN_XINDEX and a zero symbol index remains SHN_UNDEF.
    extra=struct.unpack_from('<Q',raw,shoff+5*64+24)[0]
    struct.pack_into('<H',raw,symoff+24+6,0xffff)
    struct.pack_into('<IIII',raw,extra,0,1,0,0)
    struct.pack_into('<I',raw,shoff+5*64+4,18)
    struct.pack_into('<I',raw,shoff+5*64+40,3)
    struct.pack_into('<Q',raw,shoff+5*64+56,4)
    value=ElfReader(bytes(raw)).parse('extended.elf');schema_validator(value)
    assert value['symbols'][1]['section_index']==1 and value['symbols'][1]['value_meaning']=='section-offset'
    original=next(r for r in value['original_records'] if r['kind']=='symbol' and r['identity']=={'table_index':3,'entry_index':1})
    assert struct.unpack_from('<H',base64.b64decode(original['bytes_base64']),6)[0]==0xffff


@pytest.mark.parametrize('field,value',[(4,1),(5,2),(18,40)])
def test_unsupported_elf_does_not_fall_back(field,value):
    raw=bytearray(fixture_elf());raw[field]=value
    with pytest.raises(ValueError,match='supports ELF64'):ElfReader(bytes(raw)).parse('unsupported.elf')


def test_rel_addends_remain_unobserved_and_inactive_owner_unknown(schema_validator):
    raw=bytearray(fixture_elf());shoff=struct.unpack_from('<Q',raw,40)[0]
    struct.pack_into('<I',raw,shoff+4*64+4,9)
    struct.pack_into('<Q',raw,shoff+4*64+32,16)
    struct.pack_into('<Q',raw,shoff+4*64+56,16)
    struct.pack_into('<I',raw,shoff+4*64+44,0)
    value=ElfReader(bytes(raw)).parse('original.o');schema_validator(value)
    assert value['relocations'][0]['addend'] is None
    assert value['relocations'][0]['target']['unknown_reason']=='undefined-section-reference'


def test_api_layout_records_and_portable_bytes_after_original_removed(tmp_path):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from test_native_analysis import wait
    app=create_app(tmp_path/'profile',port=64208);source=tmp_path/'original.o';raw=fixture_elf();source.write_bytes(raw)
    with TestClient(app,base_url='http://127.0.0.1:64208') as client:
        client.get('/');store=app.state.store;pid=store.create_project('Original ELF evidence')['id']
        artifact=store.add_artifact(pid,source)
        response=client.post('/api/projects/'+pid+'/artifacts/'+artifact['id']+'/analyses',json={'operation':'binary.layout','parameters':{}})
        assert response.status_code==200,response.text
        job=wait(client,response.json());assert job['state']=='finished',job
        document=client.get('/api/jobs/'+job['id']+'/analysis.json').content
        value=json.loads(document)['result'];assert value['artifact']['sha256']==hashlib.sha256(raw).hexdigest()
        assert source.read_bytes()==raw
        portable=app.state.evidence.export(pid);source.unlink()
        loaded=app.state.evidence.load(portable);key=loaded['id_map'][job['id']]
        retained=client.get('/api/jobs/'+key+'/analysis.json');assert retained.status_code==200
        assert retained.content==document
        page=store.analysis_records(key,section='original_records',limit=None)
        assert len(page['records'])==len(value['original_records'])


def test_sectionless_linkage_and_scoped_mitigations(schema_validator):
    # A valid sectionless dynamic image with a high linked address and duplicate
    # physical LOAD views mapping to the same bytes, not a runtime load address.
    base=0xffff800000000000;raw=bytearray(768);names=b'\0liboriginal.so\0'
    raw[512:512+len(names)]=names;raw[600:613]=b'/own/loader\0\0'
    dynamic=[(5,base+512),(10,len(names)),(1,1),(1,1),(30,8),(0,0)]
    raw[384:480]=b''.join(struct.pack('<qQ',*v) for v in dynamic)
    ph=[(1,5,0,base,base,768,768,4096),(2,6,384,base+384,base+384,96,96,8),
        (3,4,600,base+600,base+600,13,13,1),(0x6474e551,6,0,0,0,0,0,16),(0x6474e552,4,0,base,base,768,768,1)]
    raw[:64]=struct.pack('<16sHHIQQQIHHHHHH',b'\x7fELF\x02\x01\x01'+bytes(9),3,62,1,base,64,0,0,64,56,len(ph),64,0,0)
    raw[64:64+56*len(ph)]=b''.join(struct.pack('<IIQQQQQQ',*p) for p in ph)
    value=ElfReader(bytes(raw)).parse('original.so');schema_validator(value)
    assert [n['display'] for n in value['linkage']['needed_libraries']]==['liboriginal.so','liboriginal.so']
    assert value['linkage']['interpreters'][0]['display']=='/own/loader'
    assert value['mitigations']=={'evidence_kind':'inferred','position_independent':True,'nx_indicator':True,'executable_stack_indicator':False,'stack_canary_indicator':False,'relro':'Full'}
    assert value['entry_point']['reported_value']==hex(base) and value['runtime_load_base'] is None


def test_independent_compiler_elf_oracle(tmp_path,schema_validator):
    rust=shutil.which('rustc')
    if not rust:pytest.skip('Rust cross compiler is not installed')
    sysroot=Path(subprocess.check_output([rust,'--print','sysroot'],text=True).strip())
    target='x86_64-unknown-linux-gnu';installed=subprocess.check_output(['rustup','target','list','--installed'],text=True)
    if target not in installed:pytest.skip('Linux x86-64 cross target is not installed')
    linker=sysroot/'lib/rustlib/x86_64-pc-windows-msvc/bin/rust-lld.exe'
    if not linker.is_file():pytest.skip('ELF linker is not installed on this host')
    source=tmp_path/'original.rs';binary=tmp_path/'original.so'
    source.write_text('''#![no_std]
#[panic_handler] fn panic(_: &core::panic::PanicInfo) -> ! { loop {} }
#[unsafe(no_mangle)] pub extern "C" fn original_rule(value: u64) -> u64 { value.wrapping_mul(7).wrapping_add(11) }
#[used] #[unsafe(no_mangle)] pub static ORIGINAL_CALLBACK: extern "C" fn(u64)->u64 = original_rule;
''',encoding='utf8')
    completed=subprocess.run([rust,str(source),'--edition=2024','--target',target,'--crate-type=cdylib','-Cpanic=abort',
        '-Clinker='+str(linker),'-Clinker-flavor=ld.lld','-Clink-arg=--pack-dyn-relocs=relr','-o',str(binary)],capture_output=True,text=True)
    assert completed.returncode==0,completed.stderr
    raw=binary.read_bytes();value=inspect_layout(binary);schema_validator(value)
    from elftools.elf.elffile import ELFFile
    oracle=ELFFile(io.BytesIO(raw));assert oracle.num_sections()==len(value['sections']) and oracle.num_segments()==len(value['segments'])
    for i,section in enumerate(oracle.iter_sections()):
        observed=value['sections'][i];assert observed['name']['display']==section.name
        assert int(observed['offset'],16)==section['sh_offset'] and int(observed['size'],16)==section['sh_size']
        if section['sh_type'] in {'SHT_SYMTAB','SHT_DYNSYM'}:
            rows=[s for s in value['symbols'] if s['table_index']==i]
            assert [(s['name']['display'],int(s['value'],16),int(s['size'],16)) for s in rows]==[(s.name,s['st_value'],s['st_size']) for s in section.iter_symbols()]
    assert any(s['name']['display']=='original_rule' for s in value['symbols'])
    assert binary.read_bytes()==raw
