"""Swift demangling against the Swift project's own test vectors for the same release.

fixtures/swift_manglings.txt is test/Demangle/Inputs/manglings.txt from swiftlang/swift at tag
swift-6.4.1-RELEASE (Apache License 2.0 with Runtime Library Exception): each line is
`mangled ---> demangled`, the output swift-demangle must produce for that input.
"""
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.swift_demangle import COMMAND_BUDGET, PREFIXES, engine

pytestmark = pytest.mark.skipif(engine() is None, reason='Requires swift-demangle (THESEUS_SWIFT_DEMANGLE)')
# Split each line exactly as the release suite's sed commands do: input is the text before ' *--->', expectation after the last '---> *'.
VECTORS = [(re.sub(r' *--->.*$', '', line), re.sub(r'^.*---> *', '', line))
           for line in (Path(__file__).parent / 'fixtures' / 'swift_manglings.txt').read_text(encoding='utf8').split('\n') if '--->' in line]


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    with TestClient(create_app(tmp_path_factory.mktemp('swift') / 'data'), base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        yield client


def call(client, symbols):
    reply = client.post('/api/agent/call', json={'tool': 'theseus_swift_demangle', 'arguments': {'symbols': symbols}})
    reply.raise_for_status()
    return reply.json()['result']


PLAIN = {'swift_symbol': True, 'thunk': False, 'thunk_target': None, 'foreign_calling_convention': False}


def classified(row):
    flags = row['classification']
    # Read from standard input, as the release suite does, swift-demangle classifies only text it recognises as a Swift
    # symbol, so the suite never shows the {N} that an argument outside the Swift manglings receives; swift_symbol keeps it.
    parts = (['T:' + (flags['thunk_target'] or '')] if flags['thunk'] else []) \
        + (['C'] if flags['foreign_calling_convention'] else [])
    return ('{' + ','.join(parts) + '} ' if parts else '') + row['output']


def test_every_release_vector_demangles_as_the_swift_test_suite_expects(client):
    result = call(client, [mangled for mangled, _ in VECTORS])
    assert [row['input'] for row in result['symbols']] == [mangled for mangled, _ in VECTORS]
    # The release suite runs swift-demangle --classify, so each expected line carries the classification prefix.
    assert [classified(row) for row in result['symbols']] == [demangled for _, demangled in VECTORS]
    assert any(row['classification']['thunk_target'] for row in result['symbols'])
    assert any(row['classification']['foreign_calling_convention'] for row in result['symbols'])
    for row, (mangled, demangled) in zip(result['symbols'], VECTORS):
        demangled = demangled[len(classified(row)) - len(row['output']):]
        expected = 'demangled' if demangled != mangled else 'invalid' if mangled.startswith(PREFIXES) else 'unchanged'
        assert row['status'] == expected, row
        assert row['classification']['swift_symbol'] == (expected != 'unchanged'), row
    assert {row['status'] for row in result['symbols']} >= {'demangled', 'invalid'}
    assert all(row['exit_code'] == 0 and len(row['sha256']) == 64 for row in result['provenance'])


def test_lists_longer_than_one_command_line_keep_order_across_invocations(client):
    symbols = [mangled for mangled, _ in VECTORS] * 4
    assert sum(len(symbol) + 3 for symbol in symbols) > COMMAND_BUDGET
    single = call(client, [mangled for mangled, _ in VECTORS])['symbols']
    result = call(client, symbols)
    assert result['symbols'] == single * 4
    assert len(result['provenance']) > 1 and sum(row['argument_count'] for row in result['provenance']) == len(symbols)


def test_plain_names_options_and_text_are_never_read_as_manglings(client):
    result = call(client, ['main', '-help', '--version', 'ñandú', '$s4Test3fooyyF'])
    assert [(row['output'], row['status']) for row in result['symbols']] == [
        ('main', 'unchanged'), ('-help', 'unchanged'), ('--version', 'unchanged'), ('ñandú', 'unchanged'), ('Test.foo() -> ()', 'demangled')]


def test_the_rest_endpoint_used_by_the_page_returns_the_same_rows(client):
    symbols = ['$sSS', 'plain']
    reply = client.post('/api/swift/demangle', json={'symbols': symbols},
                        headers={'X-Hoard-Request': '1'})
    reply.raise_for_status()
    assert reply.json()['symbols'] == call(client, symbols)['symbols']


@pytest.mark.parametrize('symbols', [[], ['two\nlines'], ['carriage\rreturn'], ['nul\0byte'], ['']])
def test_malformed_symbol_lists_are_rejected(client, symbols):
    reply = client.post('/api/agent/call', json={'tool': 'theseus_swift_demangle', 'arguments': {'symbols': symbols}})
    assert reply.status_code >= 400
