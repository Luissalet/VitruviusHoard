import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient

from test_native_analysis import managed_fixture, wait
from test_portfolio import run
from theseus.api import create_app
from theseus.native_analysis import ENGINE, engine


def test_source_to_bundle_preserves_positive_and_changed_byte_evidence(tmp_path):
    source=tmp_path/'source'
    source.mkdir()
    (source/'package.json').write_text(json.dumps({'name':'source-fixture','main':'rule.cjs'}))
    (source/'rule.cjs').write_text('exports.normalize=n=>n<10?n+128:-1;')
    asar=tmp_path/'app.asar'
    def pack():
        subprocess.run([engine()['node'],'--input-type=module','-e',
            "import {createPackage} from '@electron/asar';await createPackage(process.argv[1],process.argv[2]);",
            str(source),str(asar)],cwd=ENGINE,check=True,capture_output=True)
    pack()
    app=create_app(tmp_path/'data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        store=app.state.store
        pid=store.create_project('Source and distribution')['id']
        reference=store.add_artifact(pid,source)
        candidate=store.add_artifact(pid,asar)
        left,_=run(client,pid,reference['id'],'source.graph')
        right,_=run(client,pid,candidate['id'],'javascript.application')
        _,same=run(client,pid,reference['id'],'javascript.compare_source',{'reference_job_id':left['id'],'candidate_job_id':right['id']})
        assert any(row['source_path']=='rule.cjs' and row['status']=='unchanged' for row in same['items']),same
        (source/'rule.cjs').write_text('exports.normalize=n=>n<10?n+256:-1;')
        pack()
        changed,_=run(client,pid,candidate['id'],'javascript.application')
        # The source commitment is the earlier observation, not the edited tree.
        _,different=run(client,pid,reference['id'],'javascript.compare_source',{'reference_job_id':left['id'],'candidate_job_id':changed['id']})
        assert any(row['source_path']=='rule.cjs' and row['status']=='modified' for row in different['items']),different


def test_wasm_interface_comparison_uses_types_and_retains_changed_signature(tmp_path):
    modules=[]
    for index,kind in enumerate(('i32','i64')):
        path=tmp_path/('fixture'+str(index)+'.wasm')
        script="import wabtFactory from 'wabt';import{writeFile}from'node:fs/promises';let w=await wabtFactory();let m=w.parseWat('fixture.wat',process.argv[1]);await writeFile(process.argv[2],m.toBinary({}).buffer);m.destroy();"
        wat=f'(module (func (export "normalize") (param {kind}) (result {kind}) local.get 0))'
        subprocess.run([engine()['node'],'--input-type=module','-e',script,wat,str(path)],cwd=ENGINE,check=True,capture_output=True)
        modules.append(path)
    app=create_app(tmp_path/'data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        store=app.state.store
        pid=store.create_project('WASM typed interface')['id']
        artifacts=[store.add_artifact(pid,path) for path in modules]
        analyses=[run(client,pid,row['id'],'wasm.artifact')[0] for row in artifacts]
        _,same=run(client,pid,artifacts[0]['id'],'wasm.compare_interfaces',{'reference_job_id':analyses[0]['id'],'candidate_job_id':analyses[0]['id']})
        assert same['summary']['unchanged']==1 and same['summary']['unknown']==0
        _,changed=run(client,pid,artifacts[0]['id'],'wasm.compare_interfaces',{'reference_job_id':analyses[0]['id'],'candidate_job_id':analyses[1]['id']})
        assert changed['summary']['changed']==1 and changed['summary']['unchanged']==0


def test_managed_reconstruction_is_bound_to_exact_il_not_caller_claims(tmp_path,managed_fixture):
    app=create_app(tmp_path/'data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        store=app.state.store
        pid=store.create_project('Managed reconstruction')['id']
        artifact=store.add_artifact(pid,managed_fixture)
        analysis,members=run(client,pid,artifact['id'],'managed.members')
        method=next(row for row in members['methods'] if row['body'].get('normalized_il_sha256'))
        query={'decompiler':{'name':'Original fixture notes','family':'other'},'methods':[{
            'token':method['token'],'signature_sha256':method['signature']['raw_sha256'],
            'normalized_il_sha256':method['body']['normalized_il_sha256'],
            'reconstruction':{'kind':'semantic-pseudocode','language':'pseudocode','text':'Observed CIL method; behavior remains subject to oracle verification.'}}]}
        _,result=run(client,pid,artifact['id'],'managed.reconstruction',{'source_job_id':analysis['id'],'query':query})
        assert result['executed'] is False and result['methods'][0]['validation']['canonical_observation'] is False
        query['methods'][0]['normalized_il_sha256']='f'*64
        reply=client.post(f'/api/projects/{pid}/artifacts/{artifact["id"]}/analyses',json={'operation':'managed.reconstruction',
            'parameters':{'source_job_id':analysis['id'],'query':query}})
        bad=wait(client,reply.json())
        assert bad['state']=='failed' and 'does not match' in bad['result']['execution']['stderr']
