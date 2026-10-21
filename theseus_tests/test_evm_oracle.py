"""EVM reader against contracts compiled here, checked with the compiler's own ABI and metadata.

solc compiles each contract in a separate Node process. Expected selectors, mutability, payable
entry points, argument types and the CBOR metadata hash come from solc's output, not from the reader.
"""
import hashlib
import json
import subprocess

import pytest

from test_native_formats import inspect
from theseus.native_analysis import ENGINE, engine

# Many external functions push the optimizer to its split selector dispatch.
FUNCTIONS = '\n'.join(f'    function read{i}(uint256 v) external pure returns (uint256) {{ return v + {i}; }}' for i in range(14))
LEDGER = f'''// SPDX-License-Identifier: MIT
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

# Dynamic, small, tuple and byte-word arguments used in different ways.
SHAPES = '''// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;
contract Shapes {
    struct Pair { uint8 a; bool b; }
    mapping(bytes32 => address) public owners;
    uint256 public counter;
    function first(bytes32 tag) external pure returns (bytes1) { return tag[0]; }
    function claim(bytes32 key, address who) external { owners[key] = who; }
    function scale(bytes32 word) external pure returns (uint256) { return uint256(word) * 3; }
    function total(uint256[] calldata values) external pure returns (uint256 sum) { for (uint256 i = 0; i < values.length; i++) sum += values[i]; }
    function length(string calldata text) external pure returns (uint256) { return bytes(text).length; }
    function digest(bytes memory data) public pure returns (bytes32) { return keccak256(data); }
    function narrow(uint8 x, int8 y, bool pick) external pure returns (int256) { return pick ? int256(uint256(x)) : int256(y); }
    function pair(Pair calldata value) external pure returns (uint8) { return value.b ? value.a : 0; }
    function matches(bytes4 selector) external pure returns (bool) { return selector == this.matches.selector; }
    function pay(uint64 amount) external payable { counter += amount + msg.value; }
    function bump() external { counter++; }
}
'''

# Bytecode-level renderings that differ from the ABI, each with its reason. Everything else must match exactly.
INFERRED_ARGUMENTS = {
    'peek(address,bytes32)': 'address,uint256',   # bytes32 used only arithmetically
    'scale(bytes32)': 'uint256',                  # same
    'claim(bytes32,address)': 'uint256,address',  # bytes32 used as a mapping key (hashed as a word)
    'owners(bytes32)': 'uint256',                 # same, in the public getter
    'length(string)': 'bytes',                    # string and bytes share their calldata layout
    'pair((uint8,bool))': 'uint256,bool',         # a static tuple is reported as its words; members can widen
}

COMPILE = r'''
import solc from 'solc';
const [source, name, settings] = process.argv.slice(1);
const input = {language: 'Solidity', sources: {[name + '.sol']: {content: source}}, settings: {
  ...JSON.parse(settings), metadata: {bytecodeHash: 'ipfs'},
  outputSelection: {'*': {'*': ['abi', 'metadata', 'evm.deployedBytecode.object', 'evm.methodIdentifiers']}}}};
const output = JSON.parse(solc.compile(JSON.stringify(input)));
if (output.errors?.some(row => row.severity === 'error')) throw new Error(JSON.stringify(output.errors));
process.stdout.write(JSON.stringify({version: solc.version(), ...output.contracts[name + '.sol'][name]}));
'''

SETTINGS = {'plain': {'optimizer': {'enabled': False}}, 'optimized': {'optimizer': {'enabled': True, 'runs': 200}},
            'via-ir': {'optimizer': {'enabled': True, 'runs': 200}, 'viaIR': True}}


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


def compile_contract(source, name, settings):
    reply = subprocess.run([engine()['node'], '--input-type=module', '-e', COMPILE, source, name, json.dumps(SETTINGS[settings])],
                           cwd=ENGINE, capture_output=True, text=True, encoding='utf8')
    assert reply.returncode == 0, reply.stderr
    return json.loads(reply.stdout)


def compile_ledger(optimize):
    return compile_contract(LEDGER, 'Ledger', 'optimized' if optimize else 'plain')


@pytest.mark.parametrize('settings', sorted(SETTINGS))
@pytest.mark.parametrize('source,name', [(LEDGER, 'Ledger'), (SHAPES, 'Shapes')], ids=['ledger', 'shapes'])
def test_compiled_selectors_mutability_and_metadata_match_solc(tmp_path, source, name, settings):
    compiled = compile_contract(source, name, settings)
    code = bytes.fromhex(compiled['evm']['deployedBytecode']['object'])
    result = inspect(tmp_path, 'evm.interface', code)
    functions = {row['selector']: row for row in result['functions']}
    expected = {selector: signature for signature, selector in compiled['evm']['methodIdentifiers'].items()}
    assert set(expected) == set(functions), sorted(set(expected) ^ set(functions))
    abi = {row['name']: row for row in compiled['abi'] if row['type'] == 'function'}
    for selector, signature in expected.items():
        declared = abi[signature.split('(')[0]]['stateMutability']
        observed = functions[selector]['stateMutability']
        # Static inference may widen pure to view; it must never call a payable entry nonpayable or vice versa.
        assert (observed == 'payable') == (declared == 'payable'), (signature, observed, declared)
        if declared in {'nonpayable', 'payable'}:
            assert observed == declared, (signature, observed, declared)
        # The whole argument list is compared as one string, so a flattened tuple cannot pass as its members.
        declared_arguments = signature[signature.index('(') + 1:-1]
        assert functions[selector]['arguments'] == INFERRED_ARGUMENTS.get(signature, declared_arguments), signature
    assert result['bytecode_sha256'] == hashlib.sha256(code).hexdigest()
    metadata = result['solidity_metadata']
    assert metadata['compiler_version']['value'] == compiled['version'].split('+')[0]
    trailing = int.from_bytes(code[-2:], 'big')
    assert metadata['cbor_bytes'] == trailing and metadata['bytecode_offset'] == len(code) - 2 - trailing
    entries = {row['key']['value']: row['value'] for row in metadata['entries']}
    assert entries['ipfs'] == {'kind': 'bytes', 'value': ipfs_multihash(compiled['metadata'].encode('utf8')).hex()}
    assert entries['solc']['value'] == bytes(int(part) for part in metadata['compiler_version']['value'].split('.')).hex()
    assert result['runtime_execution'] == 'not-performed' and result['discovery_completeness'] == 'unknown'


def test_every_declared_inference_difference_occurs():
    # Keeps the exception table honest: an entry that no longer names a compiled function must go.
    signatures = set()
    for source, name in [(LEDGER, 'Ledger'), (SHAPES, 'Shapes')]:
        signatures |= set(compile_contract(source, name, 'plain')['evm']['methodIdentifiers'])
    assert set(INFERRED_ARGUMENTS) <= signatures


def test_hex_text_with_prefix_and_whitespace_reads_the_same_bytes(tmp_path):
    code = bytes.fromhex(compile_ledger(False)['evm']['deployedBytecode']['object'])
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'hex').mkdir()
    raw = inspect(tmp_path / 'raw', 'evm.interface', code)
    text = inspect(tmp_path / 'hex', 'evm.interface', ('0x' + code.hex().upper() + '\r\n').encode(), {'encoding': 'hex'})
    assert text['bytecode_sha256'] == raw['bytecode_sha256'] == hashlib.sha256(code).hexdigest()
    assert [row['selector'] for row in text['functions']] == [row['selector'] for row in raw['functions']]
