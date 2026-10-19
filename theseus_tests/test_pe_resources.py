import hashlib
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest

from test_portfolio import run
from theseus.api import create_app


def test_real_compiled_resource_directory_preserves_original_payload_offsets(tmp_path):
    setup = Path('C:/Program Files/Microsoft Visual Studio/18/Community/VC/Auxiliary/Build/vcvars64.bat')
    if not setup.is_file():
        pytest.skip('Requires installed Windows SDK resource compiler')
    source = tmp_path/'original.rc'
    source.write_text('LANGUAGE 9, 1\n17 RCDATA { 0x0080, 0x0100, "Gauge" }\n')
    script = tmp_path/'build.cmd'
    script.write_text('@echo off\ncall "'+str(setup)+'" >nul\nif errorlevel 1 exit /b 1\n'
        'rc /nologo /fo original.res original.rc\nif errorlevel 1 exit /b 1\n'
        'link /nologo /DLL /NOENTRY /NODEFAULTLIB /MACHINE:X64 /OUT:original.dll original.res\nexit /b %errorlevel%\n')
    compiled = subprocess.run(['cmd.exe', '/d', '/c', str(script)], cwd=tmp_path, capture_output=True)
    assert compiled.returncode == 0, compiled.stdout+compiled.stderr
    target = tmp_path/'original.dll'
    before = target.read_bytes()
    with TestClient(create_app(tmp_path/'data'), base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        store = client.app.state.store
        pid = store.create_project('Original PE resources')['id']
        artifact = store.add_artifact(pid, target)
        _, result = run(client, pid, artifact['id'], 'pe.resources')
        resource = next(row for row in result['resources'] if row['name'] == {'kind': 'id', 'id': 17})
        payload = resource['payload']
        location = payload['location']
        selected = before[location['offset']:location['offset']+location['bytes']]
        assert selected.startswith(bytes.fromhex('80000001')) and b'Gauge' in selected
        assert hashlib.sha256(selected).hexdigest() == payload['sha256']
        assert resource['language']['id'] == 1033
        assert target.read_bytes() == before
