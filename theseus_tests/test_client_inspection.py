import base64
import hashlib
import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest

from theseus import client_inspection as clients
from theseus.api import TOOLS, create_app


@pytest.fixture
def original_clients(tmp_path,monkeypatch):
    home=tmp_path/'jdk';(home/'bin').mkdir(parents=True)
    java=home/'bin'/('java.exe' if clients.os.name=='nt' else 'java');java.write_bytes(b'original inert Java identity\0')
    jar=tmp_path/'original.jar';jar.write_bytes(b'original inert archive identity\xff')
    monkeypatch.setenv('THESEUS_JAVA_HOME',str(home));monkeypatch.setenv('THESEUS_APKTOOL',str(jar))
    return java,jar


def test_versions_preserve_stderr_invalid_utf8_and_actual_selected_identity(original_clients,monkeypatch):
    java,jar=original_clients;calls=[]
    def observed(command,**kwargs):
        calls.append(command);assert kwargs['stdin']==subprocess.DEVNULL and kwargs['capture_output']
        return subprocess.CompletedProcess(command,0,b'original version\xff\r\n',b'java diagnostic\x00\n')
    monkeypatch.setattr(subprocess,'run',observed)
    result=clients.inspect_clients('apktool');assert not result['artifact_accessed'] and not result['target_executed']
    assert calls==[[str(java.resolve()),'-version'],[str(java.resolve()),'-jar',str(jar.resolve()),'--version']]
    for row,path in zip(result['clients'],(java,jar)):
        assert row['status']=='ok' and row['identity']['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
        assert base64.b64decode(row['stdout']['base64'])==b'original version\xff\r\n'
        assert base64.b64decode(row['stderr']['base64'])==b'java diagnostic\x00\n'
        assert sum(c['selected'] for c in row['selection']['candidates'])==1


def test_explicit_missing_java_can_fall_back_to_path_but_missing_jar_remains_unavailable(tmp_path,monkeypatch):
    java=tmp_path/'fallback.exe';java.write_bytes(b'original fallback')
    monkeypatch.setenv('THESEUS_JAVA_HOME',str(tmp_path/'missing'))
    monkeypatch.setenv('THESEUS_APKTOOL',str(tmp_path/'missing.jar'))
    monkeypatch.setattr(clients.shutil,'which',lambda name:str(java) if name=='java' else None)
    selected=dict(clients.selection('apktool'));assert selected['java']['source']=='PATH'
    assert selected['java']['candidates'][0]['exists'] is False
    assert selected['apktool']['path'] is None


def test_nonzero_timeout_and_changed_files_are_not_versions(original_clients,monkeypatch):
    java,jar=original_clients
    def failed(command,**kwargs):return subprocess.CompletedProcess(command,2,b'',b'not a version')
    monkeypatch.setattr(subprocess,'run',failed)
    assert all(r['status']=='nonzero-exit' and r['exit_code']==2 for r in clients.inspect_clients('apktool')['clients'])
    def timeout(command,**kwargs):raise subprocess.TimeoutExpired(command,15,output=b'partial\xff',stderr=b'partial err')
    monkeypatch.setattr(subprocess,'run',timeout)
    rows=clients.inspect_clients('apktool')['clients'];assert all(r['status']=='timeout' and r['exit_code'] is None for r in rows)
    assert base64.b64decode(rows[0]['stdout']['base64'])==b'partial\xff'
    def changing(command,**kwargs):
        java.write_bytes(java.read_bytes()+b' changed');return subprocess.CompletedProcess(command,0,b'v1',b'')
    monkeypatch.setattr(subprocess,'run',changing)
    assert all(r['status']=='changed-during-inspection' for r in clients.inspect_clients('apktool')['clients'])


def test_missing_java_prevents_apktool_execution(original_clients,monkeypatch):
    java,jar=original_clients;java.unlink();monkeypatch.setattr(clients.shutil,'which',lambda _:None)
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('No available Java executable should run'))
    rows=clients.inspect_clients('apktool')['clients'];assert all(r['status']=='unavailable' for r in rows)
    assert rows[1]['identity']['sha256']==hashlib.sha256(jar.read_bytes()).hexdigest() and rows[1]['command'] is None


def test_pcap_companion_selection_and_explicit_override(tmp_path,monkeypatch):
    suffix='.exe' if clients.os.name=='nt' else '';shark=tmp_path/('tshark'+suffix);cap=tmp_path/('capinfos'+suffix)
    shark.write_bytes(b'original shark');cap.write_bytes(b'original companion')
    monkeypatch.setenv('THESEUS_TSHARK',str(shark));monkeypatch.delenv('THESEUS_CAPINFOS',raising=False)
    monkeypatch.setattr(clients.shutil,'which',lambda _:None)
    rows=dict(clients.selection('pcap'));assert rows['tshark']['source']=='THESEUS_TSHARK' and rows['capinfos']['source']=='selected-tshark-directory'
    explicit=tmp_path/'other.exe';explicit.write_bytes(b'original explicit');monkeypatch.setenv('THESEUS_CAPINFOS',str(explicit))
    rows=dict(clients.selection('pcap'));assert rows['capinfos']['source']=='THESEUS_CAPINFOS' and rows['capinfos']['path']==str(explicit.resolve())


def test_api_has_no_artifact_requirement_and_cold_catalog_does_not_probe(tmp_path,original_clients,monkeypatch):
    calls=[]
    def observed(command,**kwargs):calls.append(command);return subprocess.CompletedProcess(command,0,b'original-v1',b'')
    monkeypatch.setattr(subprocess,'run',observed)
    app=create_app(tmp_path/'profile',port=64212)
    with TestClient(app,base_url='http://127.0.0.1:64212') as client:
        client.get('/');catalog=client.get('/api/agent/tools').json()['tools'];assert any(r['name']=='theseus_client_inspect' for r in catalog)
        client.get('/api/engines');client.get('/api/analyses/catalog');assert not calls
        reply=client.post('/api/engines/inspect',json={'family':'apktool'});assert reply.status_code==200
        assert len(reply.json()['clients'])==2 and len(calls)==2
        reply=client.post('/api/agent/call',json={'tool':'theseus_client_inspect','arguments':{'family':'apktool'}})
        assert reply.status_code==200 and reply.json()['result']['family']=='apktool' and len(calls)==4
        assert client.get('/api/projects').json()['projects']==[]
        assert client.post('/api/engines/inspect',json={'family':'unknown'}).status_code==422
    native=next(r for r in TOOLS if r['name']=='theseus_client_inspect')
    snapshot=json.loads((Path(__file__).resolve().parents[1]/'vitruvius_hoard/software/catalog.json').read_text(encoding='utf8'))
    retained=next(r for r in snapshot if r['name']==native['name']);assert retained=={**native,'module':'theseus'}


@pytest.mark.parametrize('family',['apktool','pcap'])
def test_actual_installed_free_decoders_without_a_target(family):
    result=clients.inspect_clients(family)
    if any(r['selection']['path'] is None for r in result['clients']):pytest.skip('Selected free decoder is not installed on this host')
    assert all(r['status']=='ok' and r['exit_code']==0 for r in result['clients']),result
    for row in result['clients']:
        assert row['identity']['sha256'] and (row['stdout']['bytes'] or row['stderr']['bytes'])
        assert all(arg in {'-version','--version','-jar'} or Path(arg).is_file() for arg in row['command'])
