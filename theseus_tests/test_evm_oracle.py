"""EVM reader against contracts compiled here, checked with the compiler's own ABI and metadata.

solc compiles each contract in a separate Node process. Expected selectors, mutability, payable
entry points and the CBOR metadata hash come from solc's output, not from the reader.
"""
import hashlib
import json
import subprocess

import pytest

from test_native_formats import inspect
from theseus.native_analysis import ENGINE, engine

# Many external functions push the optimizer to its split selector dispatch.
FUNCTIONS = '\n'.join(f'    function read{i}(uint256 v) external pure returns (uint256) {{ return v + {i}; }}' for i in range(14))
SOURCE = f'''// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;
contract Ledger {{
    uint256 public total;
    mapping(address => uint256) public balances;
    event Deposited(address indexed who, uint256 amount);
    function deposit() external payable {{ balances[msg.sender] += msg.value; total += msg.value; emit Deposited(msg.sender, msg.value); }}
    function setTotal(uint256 value) external {{ total = value; }}
    function peek(address who, bytes32 tag) external view returns (uint256) {{ return balances[who] + uint256(tag); }}
{FUNCTIONS}
    receive() external payable {{ total += msg.value; }}
    fallback() external {{ total += 1; }}
}}
'''

COMPILE = r'''
import solc from 'solc';
const [source, optimize] = process.argv.slice(1);
const input = {language: 'Solidity', sources: {'Ledger.sol': {content: source}}, settings: {
  optimizer: {enabled: optimize === 'true', runs: 200},
  metadata: {bytecodeHash: 'ipfs'},
  outputSelection: {'*': {'*': ['abi', 'metadata', 'evm.deployedBytecode.object', 'evm.methodIdentifiers']}}}};
const output = JSON.parse(solc.compile(JSON.stringify(input)));
if (output.errors?.some(row => row.severity === 'error')) throw new Error(JSON.stringify(output.errors));
process.stdout.write(JSON.stringify({version: solc.version(), ...output.contracts['Ledger.sol'].Ledger}));
'''


def varint(value):
    out = bytearray()
    while True:
        out.append((value & 0x7f) | (0x80 if value > 0x7f else 0))
        value >>= 7
        if not value:
            return bytes(out)


def ipfs_multihash(content):
    # solc hashes its metadata as a single-chunk UnixFS file inside a DAG-PB node (CIDv0, sha2-256).
    unixfs = b'\x08\x02\x12' + varint(len(content)) + content + b'\x18' + varint(len(content))
    node = b'\x0a' + varint(len(unixfs)) + unixfs
    return b'\x12\x20' + hashlib.sha256(node).digest()


def compile_ledger(optimize):
    reply = subprocess.run([engine()['node'], '--input-type=module', '-e', COMPILE, SOURCE, str(optimize).lower()],
                           cwd=ENGINE, capture_output=True, text=True, encoding='utf8')
    assert reply.returncode == 0, reply.stderr
    return json.loads(reply.stdout)


@pytest.mark.parametrize('optimize', [False, True])
def test_compiled_selectors_mutability_and_metadata_match_solc(tmp_path, optimize):
    compiled = compile_ledger(optimize)
    code = bytes.fromhex(compiled['evm']['deployedBytecode']['object'])
    result = inspect(tmp_path, 'evm.interface', code)
    functions = {row['selector']: row for row in result['functions']}
    expected = {selector: signature for signature, selector in compiled['evm']['methodIdentifiers'].items()}
    assert set(expected) <= set(functions), sorted(set(expected) - set(functions))
    abi = {row['name']: row for row in compiled['abi'] if row['type'] == 'function'}
    for selector, signature in expected.items():
        declared = abi[signature.split('(')[0]]['stateMutability']
        observed = functions[selector]['stateMutability']
        # Static inference may widen pure to view; it must never call a payable entry nonpayable or vice versa.
        assert (observed == 'payable') == (declared == 'payable'), (signature, observed, declared)
        if declared in {'nonpayable', 'payable'}:
            assert observed == declared, (signature, observed, declared)
        declared_types = signature.split('(', 1)[1].rstrip(')').split(',') if '()' not in signature else []
        observed_types = functions[selector]['arguments'].split(',') if functions[selector]['arguments'] else []
        # A bytes32 word used only arithmetically is indistinguishable from uint256 in the bytecode.
        assert len(observed_types) == len(declared_types) and all(
            seen == declared or (declared == 'bytes32' and seen == 'uint256')
            for seen, declared in zip(observed_types, declared_types)), (signature, observed_types)
    assert result['bytecode_sha256'] == hashlib.sha256(code).hexdigest()
    metadata = result['solidity_metadata']
    assert metadata['compiler_version']['value'] == compiled['version'].split('+')[0]
    trailing = int.from_bytes(code[-2:], 'big')
    assert metadata['cbor_bytes'] == trailing and metadata['bytecode_offset'] == len(code) - 2 - trailing
    entries = {row['key']['value']: row['value'] for row in metadata['entries']}
    assert entries['ipfs'] == {'kind': 'bytes', 'value': ipfs_multihash(compiled['metadata'].encode('utf8')).hex()}
    assert entries['solc']['value'] == bytes(int(part) for part in metadata['compiler_version']['value'].split('.')).hex()
    assert result['runtime_execution'] == 'not-performed' and result['discovery_completeness'] == 'unknown'


def test_hex_text_with_prefix_and_whitespace_reads_the_same_bytes(tmp_path):
    code = bytes.fromhex(compile_ledger(False)['evm']['deployedBytecode']['object'])
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'hex').mkdir()
    raw = inspect(tmp_path / 'raw', 'evm.interface', code)
    text = inspect(tmp_path / 'hex', 'evm.interface', ('0x' + code.hex().upper() + '\r\n').encode(), {'encoding': 'hex'})
    assert text['bytecode_sha256'] == raw['bytecode_sha256'] == hashlib.sha256(code).hexdigest()
    assert [row['selector'] for row in text['functions']] == [row['selector'] for row in raw['functions']]
