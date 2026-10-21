import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import struct

from compiler_format_fixtures import CASES,carrier,go_payload,rust_payload
from test_native_formats import inspect
from theseus.native_analysis import ENGINE,engine
import pytest


@pytest.mark.parametrize('kind,bits,order',CASES)
@pytest.mark.parametrize('encoding',['inline','pointer'])
def test_go_supported_containers_and_encodings_keep_exact_locations(tmp_path,kind,bits,order,encoding):
    content=carrier(kind,bits,order,'go',go_payload(kind,bits,order,encoding))
    if kind=='elf':
        from elftools.elf.elffile import ELFFile
        image=ELFFile(io.BytesIO(content))
        assert image.elfclass==bits and image.little_endian==(order=='little')
        assert image.get_section_by_name('.go.buildinfo').data()==go_payload(kind,bits,order,encoding)
    result=inspect(tmp_path,'go.build',content)
    assert (result['format'],result['bits'],result['byte_order'])==(kind,bits,order)
    info=result['build_info']
    assert info['encoding']==encoding and info['go_version']=='go1.original-fixture'
    assert result['module']['path']=='fixture.local/measure' and result['module']['complete']
    for key in ['version','module']:
        at=info[key+'_location']
        assert content[at['offset']:at['offset']+at['bytes']]==base64.b64decode(info['go_'+key+'_bytes_base64'] if key=='version' else info['module_bytes_base64'])


@pytest.mark.parametrize('kind,bits,order',CASES)
def test_rust_auditable_supported_containers_keep_graph_and_inferred_provenance(tmp_path,kind,bits,order):
    content=carrier(kind,bits,order,'rust',rust_payload())
    result=inspect(tmp_path,'rust.dependencies',content)
    assert (result['format'],result['bits'],result['byte_order'])==(kind,bits,order)
    metadata=result['auditable_metadata']
    assert [row['name'] for row in metadata['packages']]==['measure','units']
    assert metadata['dependency_edges']==[{'from_index':0,'to_index':1}] and metadata['root_package_index']==0
    assert metadata['file_offset']==512
    provenance=result['rustc_commit']
    assert provenance['evidence_kind']=='inferred'
    row=provenance['hashes'][0]
    assert content[row['file_offset']:row['file_offset']+47]==b'/rustc/'+b'1'*40 and row['hash']=='1'*40


@pytest.mark.parametrize('prefix',[b'/rustc/',b'\\rustc\\'])
@pytest.mark.parametrize('suffix',[b'/library/measure.rs\0',b'\\library\\measure.rs\0'])
def test_rust_commit_path_separators_keep_exact_source_location(tmp_path,prefix,suffix):
    path=prefix+b'a'*40+suffix
    content=carrier('pe',64,'little','rust',rust_payload(),rust_path=path)
    result=inspect(tmp_path,'rust.dependencies',content)
    row=result['rustc_commit']['hashes'][0]
    assert row['hash']=='a'*40 and content[row['file_offset']:row['file_offset']+len(path)]==path


@pytest.mark.parametrize('path',[b'/rustc/'+b'a'*39+b'/x',b'/rustc/'+b'a'*41+b'/x',b'/rustc/'+b'g'*40+b'/x',b'/rustc/'+b'a'*40+b'X'])
def test_rust_invalid_commit_path_remains_unknown(tmp_path,path):
    content=carrier('elf',64,'little','rust',rust_payload(),rust_path=path)
    assert inspect(tmp_path,'rust.dependencies',content)['rustc_commit'] is None


def solidity_fixture(directory):
    directory.mkdir(parents=True,exist_ok=True)
    source=Path(__file__).parent/'fixtures/compiler/Measure.sol';output=directory/'compiled.json'
    script="""import solc from 'solc';import{readFileSync,writeFileSync}from'node:fs';
const input={language:'Solidity',sources:{'Measure.sol':{content:readFileSync(process.argv[1],'utf8')}},settings:{optimizer:{enabled:false},outputSelection:{'*':{'*':['abi','evm.deployedBytecode','evm.methodIdentifiers','storageLayout']}}}};
const output=JSON.parse(solc.compile(JSON.stringify(input)));
if(output.errors?.some(row=>row.severity==='error'))throw Error(JSON.stringify(output.errors));
writeFileSync(process.argv[2],JSON.stringify({compiler:solc.version(),...output.contracts['Measure.sol'].Measure}));"""
    reply=subprocess.run([engine()['node'],'--input-type=module','-e',script,str(source),str(output)],cwd=ENGINE,capture_output=True)
    assert reply.returncode==0,(reply.stdout,reply.stderr)
    return json.loads(output.read_text(encoding='utf8'))


@pytest.mark.parametrize('encoding',['raw','hex'])
def test_original_solidity_compiler_selectors_arguments_mutability_and_storage(tmp_path,encoding):
    original=solidity_fixture(tmp_path/'compiler');code=bytes.fromhex(original['evm']['deployedBytecode']['object'])
    carrier=code if encoding=='raw' else ('0x'+code.hex()+'\n').encode()
    result=inspect(tmp_path,'evm.interface',carrier,{'encoding':encoding})
    expected=original['evm']['methodIdentifiers']
    functions={row['selector']:row for row in result['functions']}
    assert set(expected.values())<=set(functions),result['functions']
    assert result['solidity_metadata']['compiler_version']['value']=='0.8.30'
    assert result['bytecode_sha256']==hashlib.sha256(code).hexdigest()
    assert result['instructions'] and result['controlFlowGraph']['blocks']
    # Compare independent compiler ABI facts only where the static reader makes a claim.
    assert functions[expected['read(uint256)']]['arguments']=='uint256',functions
    declared=next(row for row in original['abi'] if row.get('name')=='read')['stateMutability']
    assert declared=='pure' and functions[expected['read(uint256)']]['stateMutability'] in {'pure','view'}
    assert result['evidence_kind']=='inferred' and result['runtime_execution']=='not-performed'
    assert all(row['evidence_kind']=='inferred' and row['state_mutability_basis']=='conservative-static-inference' for row in functions.values())
    assert result['discovery_completeness']=='unknown'
    assert any('pure source function' in row for row in result['limitations'])
    assert functions[expected['value()']]['stateMutability']=='view',functions
    assert functions[expected['store(uint256)']]['stateMutability']=='nonpayable',functions
    storage={int(row['slot'],16):row for row in result['storage']}
    for declared in original['storageLayout']['storage']:
        observed=storage[int(declared['slot'])]
        assert observed['evidence_kind']=='inferred'
        assert observed['type']==original['storageLayout']['types'][declared['type']]['label']
    assert expected['store(uint256)'] in storage[0]['writes']
    assert expected['value()'] in storage[0]['reads']
    assert expected['store(uint256)'] in storage[1]['reads']


@pytest.mark.skipif(not shutil.which('rustc'),reason='Requires installed free Rust compiler')
def test_original_rust_compiler_pe_keeps_unknown_dependencies_and_path_provenance(tmp_path):
    source=Path(__file__).parent/'fixtures/compiler/measure.rs'
    binary=tmp_path/'measure.exe'
    compile_result=subprocess.run(['rustc','--edition=2021','--crate-name','measure','-C','opt-level=0',str(source),'-o',str(binary)],capture_output=True)
    assert compile_result.returncode==0,(compile_result.stdout,compile_result.stderr)
    verbose=subprocess.run(['rustc','-vV'],capture_output=True,text=True,check=True).stdout
    commit=next(line.split(': ',1)[1] for line in verbose.splitlines() if line.startswith('commit-hash:'))
    result=inspect(tmp_path,'rust.dependencies',binary.read_bytes())
    assert result['format']=='pe' and result['auditable_metadata'] is None
    assert any(row['hash']==commit for row in result['rustc_commit']['hashes'])
    for row in result['rustc_commit']['hashes']:
        offset=row['file_offset']
        assert binary.read_bytes()[offset+7:offset+47].decode()==row['hash']


@pytest.mark.parametrize('operation',['go.build','rust.dependencies'])
def test_universal_macho_reads_each_slice_at_its_universal_offsets(tmp_path,operation):
    language='go' if operation=='go.build' else 'rust'
    payload=go_payload('macho',64,'little','inline') if language=='go' else rust_payload()
    thin=carrier('macho',64,'little',language,payload)
    # The second entry claims arm64 but carries the x86_64 header: it must fail alone.
    fat=struct.pack('>12I',0xcafebabe,2,0x1000007,3,4096,len(thin),12,0x100000c,0,8192,len(thin),12).ljust(4096,b'\0')
    fat=(fat+thin).ljust(8192,b'\0')+thin
    result=inspect(tmp_path,operation,fat)
    assert result['format']=='macho-universal' and result['fat_magic']==0xcafebabe and not result['wide_table']
    first,second=result['slices']
    assert (first['status'],first['file_offset'],first['file_bytes'],first['cpu_type'])==('read',4096,len(thin),0x1000007)
    assert first['format']=='macho' and first['architecture']=='amd64'
    assert second['status']=='failed' and second['failure']['category']=='malformed'
    assert 'disagrees with its Mach-O header' in second['failure']['reason']
    (tmp_path/'thin').mkdir()
    thin_result=inspect(tmp_path/'thin',operation,thin)
    if language=='go':
        info,alone=first['build_info'],thin_result['build_info']
        assert info['header_offset']==alone['header_offset']+4096 and first['module']==thin_result['module']
        for key in ['version','module']:
            at=info[key+'_location']
            assert fat[at['offset']:at['offset']+at['bytes']]==base64.b64decode(info[key+'_bytes_base64' if key=='module' else 'go_version_bytes_base64'])
    else:
        assert first['auditable_metadata']['file_offset']==thin_result['auditable_metadata']['file_offset']+4096
        assert first['auditable_metadata']['packages']==thin_result['auditable_metadata']['packages']


@pytest.mark.parametrize('operation',['go.build','rust.dependencies'])
def test_universal_macho_with_an_invalid_slice_range_is_reported_as_malformed(tmp_path,operation):
    thin=carrier('macho',64,'little','go',go_payload('macho',64,'little','inline'))
    fat=struct.pack('>7I',0xcafebabe,1,0x1000007,3,4096,len(thin)+4096,12).ljust(4096,b'\0')+thin
    result=inspect(tmp_path,operation,fat,expected_state='failed')
    assert 'slice range extends beyond the file' in result['result']['execution']['stderr']
