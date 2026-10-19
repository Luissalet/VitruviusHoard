import datetime
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from test_portfolio import run
from test_native_analysis import wait
from theseus.api import create_app
from theseus.native_analysis import catalog

ZIG = Path(os.environ.get('THESEUS_TEST_ZIG', 'D:/LocalAI/tools/zig779/zig-x86_64-windows-0.15.2/zig.exe'))


@pytest.mark.skipif(not ZIG.is_file(), reason='Requires original fixture cross compiler')
@pytest.mark.parametrize('architecture', ['x86_64', 'arm64'])
def test_original_cross_compiled_objc_dispatch_protocol_and_property_locations(tmp_path, architecture):
    source = Path(__file__).parent/'fixtures/apple_gauge.m'
    target = tmp_path/'gauge.dylib'
    compiled = subprocess.run([str(ZIG), 'cc', '-target', ('aarch64' if architecture == 'arm64' else 'x86_64')+'-macos',
        '-dynamiclib', '-nostdlib', '-fno-objc-arc', '-Wl,-undefined,dynamic_lookup', str(source.resolve()), '-o', str(target)],
        capture_output=True)
    assert compiled.returncode == 0, compiled.stdout+compiled.stderr
    before = target.read_bytes()
    with TestClient(create_app(tmp_path/'data'), base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        store = client.app.state.store
        pid = store.create_project('Original Objective-C metadata')['id']
        artifact = store.add_artifact(pid, target)
        _, result = run(client, pid, artifact['id'], 'apple.dispatch', {'architecture': architecture})
        cls = next(row for row in result['objc_classes'] if row['name'] == 'Gauge')
        assert 'GaugeRule' in cls['protocols']
        assert any(row['name'] == 'base' for row in cls['properties'])
        assert any(row['selector'] == 'normalize:' for row in cls['methods'])
        assert any(row['name'] == 'GaugeRule' for row in result['objc_protocols'])
        assert any(row['name'] == 'Extra' for row in result['objc_categories'])
        assert result['objc_dispatch_implementations']
        assert target.read_bytes() == before
        bad = tmp_path/'truncated.dylib'
        bad.write_bytes(before[:96])
        invalid = store.add_artifact(pid, bad)
        response = client.post(f'/api/projects/{pid}/artifacts/{invalid["id"]}/analyses',json={'operation':'apple.dispatch'})
        assert wait(client,response.json())['state'] == 'failed'


@pytest.mark.parametrize('binary', [False, True])
def test_property_list_values_preserve_data_dates_large_integers_and_special_reals(tmp_path, binary):
    target = tmp_path/'original.plist'
    document = {'title': 'Niño', 'integer': 9007199254740993, 'data': b'\0\xff',
        'date': datetime.datetime(2026,10,18,12,34,56), 'reals': [-0.0,float('inf')], 'nested': {'enabled': False}}
    if binary:
        document['uid'] = plistlib.UID(1)
    original = plistlib.dumps(document,fmt=plistlib.FMT_BINARY if binary else plistlib.FMT_XML,sort_keys=False)
    target.write_bytes(original)
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        store = client.app.state.store
        pid = store.create_project('Original property list')['id']
        artifact = store.add_artifact(pid,target)
        _, result = run(client,pid,artifact['id'],'apple.plist')
        values = {row['name']:row['value'] for row in result['entries']}
        assert values['title'] == 'Niño'
        assert values['integer']['decimal'] == '9007199254740993'
        assert values['data']['base64'] == 'AP8='
        assert values['date']['iso8601'] == '2026-10-18T12:34:56'
        assert values['reals'] == [{'type':'real','representation':'-0.0'},{'type':'real','representation':'inf'}]
        assert values['nested'] == {'enabled':False}
        if binary:
            assert values['uid'] == {'type':'uid','decimal':'1'}
        assert target.read_bytes() == original


def test_codesign_is_an_explicit_macos_capability():
    row = next(row for row in catalog()['operations'] if row['name'] == 'apple.signature')
    assert row['platforms'] == ['darwin']
    if sys.platform != 'darwin':
        assert not row['available'] and 'darwin' in row['availability_reason']
