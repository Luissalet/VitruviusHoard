"""Synthetic retained producer documents; live capture acceptance is separate."""
import json
import time
from copy import deepcopy
from pathlib import Path

import pytest

from theseus.comparison import Comparisons
from theseus.store import Store,identifier
from theseus.workflow import Workflow


REQUEST={'method':'Runtime.evaluate','parameters':{'expression':'readBoundary(-1,0,3,128)','returnByValue':True}}


def capture(store,pid,value,*,plan=None,change=None,state='finished',wire_id=7):
    plan=deepcopy([REQUEST] if plan is None else plan)
    steps=[{'index':i,'request':deepcopy(request),'command_id':wire_id+i,'state':'completed',
            'response':{'id':wire_id+i,'result':{'result':{'type':'object','value':value}}}}
           for i,request in enumerate(plan)]
    document={'operation':'browser.scenario','runtime':'page-cdp','result':{'status':'observed',
        'capture_mode':'explicit-scenario-and-selected-snapshots','parameters':{'steps':plan},
        'steps':steps,'events':[],'observations':[],'scripts':[]}}
    if change:change(document)
    key=identifier();folder=store.directory/'analyses'/key;folder.mkdir(parents=True)
    path=folder/'analysis.json';path.write_text(json.dumps(document,ensure_ascii=False),encoding='utf8')
    artifact=store.add_artifact(pid,path)
    result={'kind':'runtime_analysis','operation':'browser.scenario','parameters':document['result']['parameters'],
        'analysis_file':str(path),'analysis_sha256':artifact['sha256'],'artifact_id':artifact['id'],
        'artifact_sha256':artifact['sha256'],'cases':[]}
    store.save_job(pid,key,state,result);store.index_analysis(key,document['result'])
    return store.job(key)


def definition(left,right):
    return {'kind':'retained-page-scenarios','reference_job_id':left['id'],
        'reference_sha256':left['result']['analysis_sha256'],'candidate_job_id':right['id'],
        'candidate_sha256':right['result']['analysis_sha256']}


def wait(store,job):
    deadline=time.monotonic()+10
    while job['state'] in {'queued','running'}:
        assert time.monotonic()<deadline;time.sleep(.01);job=store.job(job['id'])
    assert job['state']=='finished',job
    return job


@pytest.fixture
def workspace(tmp_path):
    store=Store(tmp_path/'data');manager=Comparisons(store);flow=Workflow(manager)
    project=store.create_project('Retained page boundaries')
    try:yield store,manager,flow,project['id']
    finally:manager.shutdown()


def test_retained_responses_compare_without_running_programs(workspace,monkeypatch):
    store,manager,flow,pid=workspace
    left=capture(store,pid,[0,0,21,896]);right=capture(store,pid,[0,0,21,896],wire_id=19)
    case=store.save_scenario(pid,'Boundary responses',definition(left,right))
    monkeypatch.setattr(manager,'_execute',lambda *a,**k:pytest.fail('Retained scenarios must not run commands'))
    observed=wait(store,manager.start(pid))
    assert observed['result']['passed']==1 and observed['result']['failed']==0
    record=observed['result']['cases'][0]
    assert record['valid'] and record['scenario_id']==case['id']
    assert [row['sha256'] for row in record['sources']]==[left['result']['analysis_sha256'],right['result']['analysis_sha256']]
    assert record['reference']['responses'][0]['result']['result']['value']==[0,0,21,896]
    changed=capture(store,pid,[0,0,21,897])
    store.save_scenario(pid,'Changed boundary',definition(left,changed),case['id'])
    difference=wait(store,manager.start(pid))['result']['cases'][0]
    assert difference['valid'] and not difference['passed'] and difference['differences']


@pytest.mark.parametrize('side',['reference','candidate'])
@pytest.mark.parametrize('damage',['missing','changed'])
def test_changed_or_missing_capture_never_passes(workspace,side,damage):
    store,manager,flow,pid=workspace
    pair={s:capture(store,pid,128) for s in ('reference','candidate')}
    scenario=store.save_scenario(pid,'Keep identities',definition(pair['reference'],pair['candidate']))
    flow.save_claim(pid,'obligation','Selected recorded response',scenario_ids=[scenario['id']])
    path=Path(pair[side]['result']['analysis_file'])
    original=path.read_bytes()
    if damage=='missing':path.unlink()
    else:path.write_bytes(path.read_bytes()+b' ')
    result=wait(store,manager.start(pid))['result'];case=result['cases'][0]
    assert result['passed']==0 and not case['valid'] and case['state']=='unknown'
    path.write_bytes(original)
    # Restoring a document does not turn an invalid receipt into a measured difference.
    assert flow.read(pid)['claims'][0]['status']=='unknown'


@pytest.mark.parametrize('change',[
    lambda d:d['result'].update(status='incomplete'),
    lambda d:d['result']['steps'][0].update(state='response-recovered'),
    lambda d:d['result'].update(steps=[]),
    lambda d:d['result']['steps'].append(deepcopy(d['result']['steps'][0])),
    lambda d:d['result']['steps'][0].update(index=True),
    lambda d:d['result']['steps'][0]['response'].update(id=999),
    lambda d:d['result']['steps'][0]['response'].update(error={'message':'failed'}),
    lambda d:d['result']['steps'][0]['response']['result'].update(exceptionDetails={'text':'failed'}),
    lambda d:d['result']['steps'][0].pop('response'),
    lambda d:d['result'].update(error='truncated recording'),
    lambda d:d['result'].update(journal_recovery={'gap':{'byte_offset':128,'raw_base64':'eA=='}}),
])
def test_incomplete_or_inconsistent_step_is_unknown(workspace,change):
    store,manager,_,pid=workspace
    left=capture(store,pid,128);right=capture(store,pid,128,change=change)
    store.save_scenario(pid,'Invalid prefix',definition(left,right))
    case=wait(store,manager.start(pid))['result']['cases'][0]
    assert not case['passed'] and not case['valid'] and case['state']=='unknown'


def test_requests_align_literally_and_local_payload_ids_remain_literal(workspace):
    store,manager,_,pid=workspace
    left=capture(store,pid,{'id':True});right=capture(store,pid,{'id':1})
    saved=store.save_scenario(pid,'Payload id is not envelope id',definition(left,right))
    case=wait(store,manager.start(pid))['result']['cases'][0]
    assert case['valid'] and not case['passed']
    request=deepcopy(REQUEST);request['observe_ms']=0
    right=capture(store,pid,{'id':True},plan=[request])
    store.save_scenario(pid,'Literal request',definition(left,right),saved['id'])
    case=wait(store,manager.start(pid))['result']['cases'][0]
    assert not case['valid'] and case['state']=='unknown'


def test_empty_and_foreign_captures_and_hash_mismatch(workspace):
    store,manager,_,pid=workspace
    left=capture(store,pid,128);empty=capture(store,pid,128,plan=[])
    store.save_scenario(pid,'No observations',definition(left,empty))
    assert not wait(store,manager.start(pid))['result']['cases'][0]['valid']
    foreign=capture(store,store.create_project('Foreign')['id'],128)
    with pytest.raises(ValueError,match='project'):store.save_scenario(pid,'Foreign',definition(left,foreign))
    changed=definition(left,left);changed['reference_sha256']='0'*64
    with pytest.raises(ValueError,match='SHA-256'):store.save_scenario(pid,'Wrong hash',changed)
