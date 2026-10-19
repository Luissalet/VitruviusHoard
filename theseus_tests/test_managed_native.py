import json
import os
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest

from test_native_analysis import managed_fixture
from test_portfolio import run
from test_binary_sessions import wait
from theseus.api import create_app
from theseus.binary_analysis import engines


@pytest.mark.skipif(os.environ.get('THESEUS_TEST_GHIDRA')!='1',reason='Opt-in real Ghidra integration')
def test_managed_native_names_modules_retained_hashes_and_transfer(tmp_path,managed_fixture):
    setup = Path('C:/Program Files/Microsoft Visual Studio/18/Community/VC/Auxiliary/Build/vcvars64.bat')
    if not setup.is_file() or not engines()['available']:
        pytest.skip('Requires installed Ghidra/JDK and native fixture compiler')
    source = Path(__file__).parent.resolve()/'fixtures/native_clock.c'
    script = tmp_path/'compile.cmd'
    script.write_text('@echo off\ncall "'+str(setup)+'" >nul\nif errorlevel 1 exit /b 1\n'
        'cl /nologo /c /O2 /GS- "'+str(source)+'" /Foclock.obj\nif errorlevel 1 exit /b 1\n'
        'link /nologo /DLL /NOENTRY /NODEFAULTLIB /OUT:kernel32.dll clock.obj\nif errorlevel 1 exit /b 1\n'
        'link /nologo /DLL /NOENTRY /NODEFAULTLIB /OUT:other_module.dll clock.obj\nexit /b %errorlevel%\n')
    compiled = subprocess.run(['cmd.exe','/d','/c',str(script)],cwd=tmp_path,capture_output=True)
    assert compiled.returncode==0,(compiled.stdout+compiled.stderr).decode(errors='replace')
    paths = [managed_fixture,tmp_path/'kernel32.dll',tmp_path/'other_module.dll']
    originals = {p:p.read_bytes() for p in paths}
    app = create_app(tmp_path/'data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        pid = app.state.store.create_project('Managed/native observations')['id']
        artifacts = [app.state.store.add_artifact(pid,path) for path in paths]
        managed,_ = run(client,pid,artifacts[0]['id'],'managed.native_boundaries')
        native_jobs = []
        for artifact in artifacts[1:]:
            opened = wait(client,client.post(f'/api/projects/{pid}/artifacts/{artifact["id"]}/binary-sessions',json={}).json())
            assert opened['state']=='finished',opened
            reply = client.post(f'/api/binary-sessions/{opened["id"]}/call',json={'operation':'analyze_function','parameters':{'procedure':'GetTickCount'}})
            job = wait(client,reply.json())
            assert job['state']=='finished',job
            native_jobs.append(job)
            if len(native_jobs)==1:
                duplicate = wait(client,client.post(f'/api/binary-sessions/{opened["id"]}/call',json={'operation':'analyze_function','parameters':{'procedure':'GetTickCount'}}).json())
                assert duplicate['state']=='finished',duplicate
            closed = wait(client,client.post(f'/api/binary-sessions/{opened["id"]}/close',json={}).json())
            assert closed['state']=='finished'
        params = {'source_job_id':managed['id'],'native_job_ids':[native_jobs[0]['id']]}
        job,result = run(client,pid,artifacts[0]['id'],'managed.verify_native',params)
        verification = result['verification']
        assert verification['algorithm']['name']=='theseus-managed-native-verification'
        assert verification['summary']['verified']==1 and verification['summary']['contradicted']==0
        item = verification['pinvoke_imports'][0]
        assert item['managed']['import_name']=='GetTickCount' and item['matched_native']['module_name']=='kernel32.dll'
        assert len(item['evidence_links'])==2 and len(result['source_observations'])==2
        _,wrong = run(client,pid,artifacts[0]['id'],'managed.verify_native',{**params,'native_job_ids':[native_jobs[1]['id']]})
        assert wrong['verification']['summary']['contradicted']==1
        assert wrong['verification']['pinvoke_imports'][0]['basis']=='module-mismatch'
        _,dedup = run(client,pid,artifacts[0]['id'],'managed.verify_native',{**params,'native_job_ids':[native_jobs[0]['id'],duplicate['id']]})
        assert dedup['verification']['native_observations']['total']==1
        assert dedup['source_observations'][1]['source_job_ids']==[native_jobs[0]['id'],duplicate['id']]
        before = set((app.state.store.directory/'analyses').iterdir())
        invalid = client.post(f'/api/projects/{pid}/artifacts/{artifacts[0]["id"]}/analyses',json={
            'operation':'managed.verify_native','parameters':{**params,'native_job_ids':[managed['id']]}})
        assert invalid.status_code==400 and set((app.state.store.directory/'analyses').iterdir())==before
        # The worker authenticates the retained document again, not just its saved record index.
        retained = Path(native_jobs[0]['result']['analysis_file'])
        content = retained.read_bytes()
        try:
            retained.write_bytes(content+b' ')
            bad = wait(client,client.post(f'/api/projects/{pid}/artifacts/{artifacts[0]["id"]}/analyses',json={
                'operation':'managed.verify_native','parameters':params}).json())
            assert bad['state']=='failed' and 'Retained native observation changed' in json.dumps(bad)
        finally:
            retained.write_bytes(content)
        rows = client.get(f'/api/jobs/{job["id"]}/records/verification.pinvoke_imports').json()
        assert rows['total']==1
        bundle = client.get(f'/api/projects/{pid}/evidence').json()
        imported = client.post('/api/evidence/import',json={'bundle':bundle,'name':'Native boundary import'}).json()
        read = client.get(f'/api/jobs/{imported["id_map"][job["id"]]}/records/verification.pinvoke_imports/{rows["records"][0]["record_key"]}').json()
        assert read['record']==item and len(read['sources'])==2
        assert {p:p.read_bytes() for p in paths}==originals
