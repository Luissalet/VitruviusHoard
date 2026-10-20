import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_retained_scenarios import capture,definition,wait,workspace
from theseus.api import create_app
from theseus.evidence import Evidence


def variant(name,pairs):
    return {'name':name,'captures':[{'scenario_id':scenario['id'],'candidate_job_id':candidate['id'],
        'candidate_sha256':candidate['result']['analysis_sha256']} for scenario,candidate in pairs]}


def prepared(workspace,tmp_path):
    store,manager,flow,pid=workspace
    store.update_project(pid,specification='Return the recorded boundary results for -1,0,3,128. Other inputs are unknown.')
    left=capture(store,pid,[0,0,21,896]);right=capture(store,pid,[0,0,21,896],wire_id=21)
    saved=store.save_scenario(pid,'Original boundary inputs',definition(left,right))
    claim=flow.save_claim(pid,'obligation','Explicit boundary responses',scenario_ids=[saved['id']])
    builder=tmp_path/'builder';builder.mkdir()
    handoff=flow.handoff(pid,str(builder))
    return left,right,saved,claim,handoff


def test_retained_obligation_handoff_sensitivity_and_revised_candidate(workspace,tmp_path,monkeypatch):
    store,manager,flow,pid=workspace
    left,right,saved,claim,handoff=prepared(workspace,tmp_path)
    monkeypatch.setattr(manager,'_execute',lambda *a,**k:pytest.fail('Retained workflow must not execute or reconnect'))
    verified=wait(store,flow.verify(pid,handoff['id']))
    assert verified['result']['passed']==1 and flow.read(pid)['claims'][0]['status']=='verified'
    assert not flow.read(pid)['complete']
    wrong=capture(store,pid,[128,128,128,128])
    selftest=wait(store,flow.selftest(pid,[variant('constant',[(saved,wrong)])]))
    assert selftest['result']['sensitive'] and selftest['result']['detected']==['constant']
    assert len(selftest['result']['cases'][0]['sources'])==2 and flow.read(pid)['complete']
    builder=flow.read_handoff(pid,handoff['id'],True)
    assert left['id'] not in json.dumps(builder) and left['result']['analysis_sha256'] not in json.dumps(builder)
    replacement=capture(store,pid,[0,0,21,896],wire_id=88)
    store.save_scenario(pid,'Reconstructed capture',definition(left,replacement),saved['id'])
    assert flow.read(pid)['claims'][0]['status']=='unknown'
    wait(store,flow.verify(pid,handoff['id']))
    assert flow.read(pid)['complete']  # Reference and its deliberate mutant are unchanged.
    Path(wrong['result']['analysis_file']).unlink()
    assert not flow.read(pid)['complete']  # Do not revive an earlier sensitivity receipt.
    store.update_project(pid,specification='A newer behavior contract')
    retry=wait(store,flow.verify(pid,handoff['id']))
    assert retry['result']['reconstruction']['specification_changed']
    assert flow.read_handoff(pid,handoff['id'],True)==builder


def test_survivor_and_incomplete_mutant_supersede_sensitive_result(workspace,tmp_path):
    store,manager,flow,pid=workspace
    left,right,saved,_,handoff=prepared(workspace,tmp_path)
    wait(store,flow.verify(pid,handoff['id']))
    wrong=capture(store,pid,[999,999,999,999])
    wait(store,flow.selftest(pid,[variant('wrong',[(saved,wrong)])]))
    assert flow.read(pid)['complete']
    survivor=wait(store,flow.selftest(pid,[variant('uncovered boundary',[(saved,right)])]))
    assert survivor['result']['survived']==['uncovered boundary'] and not flow.read(pid)['complete']
    wait(store,flow.selftest(pid,[variant('wrong',[(saved,wrong)])]))
    broken=capture(store,pid,[999,999,999,999],change=lambda d:d['result'].update(status='incomplete'))
    invalid=wait(store,flow.selftest(pid,[variant('broken prefix',[(saved,broken)])]))
    assert invalid['result']['invalid']==['broken prefix'] and not invalid['result']['detected']
    assert not invalid['result']['sensitive'] and not flow.read(pid)['complete']


def test_new_reference_and_missing_reference_invalidate_old_coverage(workspace,tmp_path):
    store,manager,flow,pid=workspace
    left,right,saved,_,handoff=prepared(workspace,tmp_path)
    wrong=capture(store,pid,[999,999,999,999])
    wait(store,flow.verify(pid,handoff['id']));wait(store,flow.selftest(pid,[variant('wrong',[(saved,wrong)])]))
    assert flow.read(pid)['complete']
    reference=capture(store,pid,[0,0,21,896],wire_id=99)
    store.save_scenario(pid,'New reference recording',definition(reference,right),saved['id'])
    wait(store,flow.verify(pid,handoff['id']))
    assert not flow.read(pid)['complete']
    wait(store,flow.selftest(pid,[variant('wrong',[(saved,wrong)])]))
    assert flow.read(pid)['complete']
    Path(reference['result']['analysis_file']).unlink()
    invalid=wait(store,flow.selftest(pid,[variant('wrong',[(saved,wrong)])]))
    assert invalid['result']['invalid']==['wrong'] and not invalid['result']['sensitive']
    assert flow.read(pid)['claims'][0]['status']=='unknown'


def test_perturbations_map_every_selected_case_exactly_once(workspace,tmp_path):
    store,manager,flow,pid=workspace
    left,right,first,_,handoff=prepared(workspace,tmp_path)
    second=store.save_scenario(pid,'Second obligation input',definition(left,right))
    wrong=capture(store,pid,777)
    for pairs in ([(first,wrong)],[(first,wrong),(first,wrong)]):
        with pytest.raises(ValueError,match='exactly one'):flow.selftest(pid,[variant('bad mapping',pairs)])
    incomplete=capture(store,pid,777,change=lambda d:d['result'].update(status='incomplete'))
    result=wait(store,flow.selftest(pid,[variant('one invalid',[(first,wrong),(second,incomplete)])]))['result']
    assert result['invalid']==['one invalid'] and not result['detected']
    assert len(result['cases'])==2 and not result['sensitive']


def test_http_and_tool_schemas_accept_typed_retained_definitions(tmp_path):
    app=create_app(tmp_path/'api-data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=app.state.store;pid=store.create_project('Native typed scenarios')['id']
        left=capture(store,pid,128);right=capture(store,pid,128,wire_id=8)
        reply=client.post(f'/api/projects/{pid}/scenarios',json={'name':'Saved pages','definition':definition(left,right)})
        assert reply.status_code==200,reply.text
        scenario=reply.json();wrong=capture(store,pid,129)
        reply=client.post('/api/agent/call',json={'tool':'theseus_oracle_selftest','arguments':{'project_id':pid,'variants':[variant('changed result',[(scenario,wrong)])]}})
        assert reply.status_code==200,reply.text
        assert wait(store,reply.json()['result'])['result']['detected']==['changed result']
        # Existing command scenarios keep omission of expected_stdout distinct from explicit null.
        legacy=client.post(f'/api/projects/{pid}/scenarios',json={'name':'Legacy','definition':{'reference':['unused'],'candidate':['unused']}})
        assert legacy.status_code==200 and 'expected_stdout' not in legacy.json()['definition']


def test_double_transfer_remaps_only_typed_capture_ids_and_reverifies(workspace,tmp_path,monkeypatch):
    store,manager,flow,pid=workspace
    marker=capture(store,pid,128)
    left=capture(store,pid,{'job_id':marker['id'],'id':marker['id']})
    right=capture(store,pid,{'job_id':marker['id'],'id':marker['id']},wire_id=21)
    mutant=capture(store,pid,{'job_id':marker['id'],'id':'different'})
    saved=store.save_scenario(pid,'Opaque payload IDs',definition(left,right))
    legacy_definition={'reference':['literal',marker['id']],'candidate':['literal',marker['id']],
        'stdin':json.dumps({'job_id':marker['id']})}
    legacy=store.save_scenario(pid,'Legacy opaque inputs',legacy_definition)
    store.update_project(pid,specification='Preserve literal returned IDs; no broader identity claim.')
    builder=tmp_path/'builder';builder.mkdir()
    flow.save_claim(pid,'obligation','Preserve observed payload',scenario_ids=[saved['id']])
    handoff=flow.handoff(pid,str(builder))
    wait(store,flow.verify(pid,handoff['id'],[saved['id']]))
    wait(store,flow.selftest(pid,[variant('payload mutation',[(saved,mutant)])],[saved['id']]))
    assert flow.read(pid)['complete']
    evidence=Evidence(flow);first=evidence.load(evidence.export(pid));moved=first['project']['id']
    assert not flow.read(moved)['complete']
    second=evidence.load(evidence.export(moved));destination=second['project']['id']
    mapping={key:second['id_map'][value] for key,value in first['id_map'].items()}
    frozen={job['id']:Path(job['result']['analysis_file']).read_bytes() for job in (marker,left,right,mutant)}
    for job in (marker,left,right,mutant):Path(job['result']['analysis_file']).unlink()
    scenarios={row['id']:row for row in store.items('scenarios',destination)}
    retained=scenarios[mapping[saved['id']]]
    assert retained['definition']=={**saved['definition'],'reference_job_id':mapping[left['id']],'candidate_job_id':mapping[right['id']]}
    assert scenarios[mapping[legacy['id']]]['definition']==legacy_definition
    for key,raw in frozen.items():
        imported=store.job(mapping[key])
        assert imported['state']=='imported' and Path(imported['result']['analysis_file']).read_bytes()==raw
    assert flow.read_handoff(destination,mapping[handoff['id']],True)==handoff['builder']
    monkeypatch.setattr(manager,'_execute',lambda *a,**k:pytest.fail('Imported page verification must not execute commands'))
    verified=wait(store,flow.verify(destination,mapping[handoff['id']],[retained['id']]))
    assert verified['result']['passed']==1
    imported_mutant=store.job(mapping[mutant['id']])
    wait(store,flow.selftest(destination,[variant('payload mutation',[(retained,imported_mutant)])],[retained['id']]))
    assert flow.read(destination)['complete']


def test_project_read_cannot_pair_finished_jobs_with_precompletion_workflow(tmp_path,monkeypatch):
    app=create_app(tmp_path/'race-data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=app.state.store;manager=app.state.comparisons;flow=app.state.workflow
        pid=store.create_project('Fast retained verification')['id']
        left=capture(store,pid,128);right=capture(store,pid,128,wire_id=9)
        scenario=store.save_scenario(pid,'Exact saved response',definition(left,right))
        flow.save_claim(pid,'obligation','Recorded response',scenario_ids=[scenario['id']])
        release,finished=threading.Event(),threading.Event()
        original_run=manager._run
        def delayed_run(*args):
            assert release.wait(5)
            try:original_run(*args)
            finally:finished.set()
        monkeypatch.setattr(manager,'_run',delayed_run)
        job=manager.start(pid)
        local=threading.local();original_read=flow.read;original_items=store.items
        def reading_workflow(*args):
            local.workflow=True
            try:return original_read(*args)
            finally:local.workflow=False
        def finish_during_project_collection(table,project_id):
            if table=='jobs' and not getattr(local,'workflow',False):
                release.set();assert finished.wait(5)
            return original_items(table,project_id)
        monkeypatch.setattr(flow,'read',reading_workflow)
        monkeypatch.setattr(store,'items',finish_during_project_collection)
        try:
            reply=client.get('/api/projects/'+pid);reply.raise_for_status();snapshot=reply.json()
            assert next(row for row in snapshot['jobs'] if row['id']==job['id'])['state']=='finished'
            assert snapshot['workflow']['claims'][0]['status']=='verified'
        finally:release.set();assert finished.wait(5)
