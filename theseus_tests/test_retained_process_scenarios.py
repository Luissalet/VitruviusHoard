"""Real original boundary programs, a constant mutant and portable workflow evidence."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

from theseus.comparison import Comparisons
from theseus.evidence import Evidence
from theseus.process_capture import capture_process
from theseus.store import Store,identifier
from theseus.workflow import Workflow
from test_retained_scenarios import wait


@pytest.fixture
def workspace(tmp_path):
    store=Store(tmp_path/'data');manager=Comparisons(store);workflow=Workflow(manager)
    project=store.create_project('Original process boundaries')
    try:yield store,manager,workflow,project['id']
    finally:manager.shutdown()


def capture(store,pid,root,name,expression):
    folder=root/name;folder.mkdir();program=folder/'original.py'
    program.write_text('import json,sys\nfrom pathlib import Path\nvalues=json.loads(sys.stdin.buffer.read())\nresult='+expression+'\nraw=json.dumps(result,separators=(",",":")).encode()\nPath("output.bin").write_bytes(raw)\nsys.stdout.buffer.write(raw)\n',encoding='utf8')
    key=identifier();saved=store.directory/'analyses'/key
    result=capture_process({'argv':[sys.executable,str(program)],'cwd':str(folder),'timeout_seconds':5,
        'steps':[{'kind':'input','text':'[-1,0,3,128]'}, {'kind':'close_stdin'}],
        'files':[{'label':'result','path':'output.bin'}]},saved)
    assert result['status']=='complete'
    artifact=store.add_artifact(pid,saved/'analysis.json')
    store.save_job(pid,key,'finished',{'kind':'runtime_analysis','operation':'process.capture','analysis_file':str(saved/'analysis.json'),
        'analysis_sha256':artifact['sha256'],'artifact_sha256':artifact['sha256'],'artifact_id':artifact['id']})
    store.index_analysis(key,result);return store.job(key)


def definition(reference,candidate):
    return {'kind':'retained-process-scenarios','reference_job_id':reference['id'],'reference_sha256':reference['result']['analysis_sha256'],
        'candidate_job_id':candidate['id'],'candidate_sha256':candidate['result']['analysis_sha256'],
        'query':{'dimensions':['stdout','stderr','exit','files']}}


def test_process_workflow_detects_constant_mutant_then_requires_fresh_transfer_verification(workspace,tmp_path,monkeypatch):
    store,manager,flow,pid=workspace
    reference=capture(store,pid,tmp_path,'reference','[x*7 for x in values]')
    candidate=capture(store,pid,tmp_path,'candidate','[sum([x]*7) for x in values]')
    mutant=capture(store,pid,tmp_path,'constant-mutant','[21 for x in values]')
    scenario=store.save_scenario(pid,'Boundary values',definition(reference,candidate))
    claim=flow.save_claim(pid,'obligation','Selected boundary responses and output file',scenario_ids=[scenario['id']])
    store.update_project(pid,specification='For -1,0,3,128 return -7,0,21,896 and retain the corresponding output file. Other inputs are unknown.')
    builder=tmp_path/'builder';builder.mkdir();handoff=flow.handoff(pid,str(builder))
    builder_view=json.dumps(flow.read_handoff(pid,handoff['id'],True))
    assert reference['id'] not in builder_view and reference['result']['analysis_sha256'] not in builder_view
    monkeypatch.setattr(manager,'_execute',lambda *args:pytest.fail('Retained verification must not start a program'))
    compared=wait(store,flow.verify(pid,handoff['id']));assert compared['result']['passed']==1
    variants=[{'name':'Constant output','captures':[{'scenario_id':scenario['id'],'candidate_job_id':mutant['id'],
        'candidate_sha256':mutant['result']['analysis_sha256']}]}]
    tested=wait(store,flow.selftest(pid,variants));assert tested['result']['sensitive'] and tested['result']['detected']==['Constant output']
    assert flow.read(pid)['claims'][0]['complete']
    evidence=Evidence(flow);portable=evidence.export(pid);loaded=evidence.load(portable);new_pid=loaded['project']['id']
    imported=flow.read(new_pid)['claims'][0];assert imported['status']=='unknown' and not imported['complete']
    # Remove only the authored originals. Imported analyses contain their full byte evidence.
    for name in ('reference','candidate','constant-mutant'):(tmp_path/name/'original.py').unlink()
    fresh=wait(store,manager.start(new_pid));assert fresh['result']['passed']==1
    moved=loaded['id_map'];new_scenario=moved[scenario['id']]
    imported_test=store.job(moved[tested['id']])
    variants=imported_test['result']['variants']
    assert variants[0]['captures'][0]['candidate_job_id']==moved[mutant['id']]
    assert variants[0]['captures'][0]['scenario_id']==new_scenario
    assert variants[0]['captures'][0]['candidate_sha256']==mutant['result']['analysis_sha256']
    fresh_test=wait(store,flow.selftest(new_pid,variants));assert fresh_test['result']['sensitive']
    assert flow.read(new_pid)['claims'][0]['complete']
    assert all(job['state'] not in {'queued','running'} for job in store.items('jobs',new_pid))
    # Current evidence cannot silently fall back to the old successful mutant receipt.
    path=Path(store.job(moved[mutant['id']])['result']['analysis_file']);path.write_bytes(path.read_bytes()+b' ')
    current=flow.read(new_pid)['claims'][0];assert not current['complete'] and current['oracle_unchecked']==[new_scenario]


def test_changed_input_contract_is_unknown_not_a_detected_defect(workspace,tmp_path):
    store,manager,flow,pid=workspace
    reference=capture(store,pid,tmp_path,'original','[x*7 for x in values]')
    candidate=capture(store,pid,tmp_path,'changed-input','[x*7 for x in values]')
    path=Path(candidate['result']['analysis_file']);document=json.loads(path.read_bytes())
    document['result']['contract']['steps'][0]['text']='[1,2,3,4]'
    document['result']['contract_sha256']=hashlib.sha256(json.dumps(document['result']['contract'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    path.write_text(json.dumps(document),encoding='utf8');raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    # A different valid document is a new observation identity, not an altered bound receipt.
    artifact=store.add_artifact(pid,path)
    value={**candidate['result'],'analysis_sha256':sha,'artifact_sha256':sha,'artifact_id':artifact['id']}
    store.save_job(pid,candidate['id'],'finished',value);candidate=store.job(candidate['id'])
    scenario=store.save_scenario(pid,'Changed input',definition(reference,candidate))
    result=wait(store,manager.start(pid))['result'];assert not result['cases'][0]['valid'] and result['passed']==0
    variants=[{'name':'Changed input is not a mutant','captures':[{'scenario_id':scenario['id'],'candidate_job_id':candidate['id'],'candidate_sha256':sha}]}]
    tested=wait(store,flow.selftest(pid,variants));assert tested['result']['invalid']==['Changed input is not a mutant'] and not tested['result']['sensitive']
