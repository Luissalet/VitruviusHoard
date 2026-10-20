"""Original retained documents; record membership is separate from behavior."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from theseus.retained_evidence import make_bundle,compare_bundles


def source(key,value,operation='original.observation'):
    raw=json.dumps({'operation':operation,'result':value},ensure_ascii=False).encode()
    return {'job_id':key,'operation':operation,'analysis_sha256':hashlib.sha256(raw).hexdigest(),
        'artifact_sha256':'a'*64,'provider':None,'document_base64':base64.b64encode(raw).decode()}


def test_bundle_is_canonical_and_keeps_original_bytes_literal_ids_and_duplicates():
    a=source('first',{'job_id':'first','candidate_job_id':'second','value':'ñ😀'})
    b={**a,'job_id':'second'}
    bundle=make_bundle([b,a]);assert len(bundle['records'])==1 and len(bundle['occurrences'])==2
    assert base64.b64decode(bundle['records'][0]['document_base64'])==base64.b64decode(a['document_base64'])
    assert make_bundle([a,b])==bundle
    assert bundle['occurrences'][0]['job_id']=='first'
    with pytest.raises(ValueError,match='duplicate'):make_bundle([a,a])


def test_same_records_with_new_local_bindings_do_not_claim_current_behavior():
    a=source('before',{'value':21});b={**a,'job_id':'after'}
    left,right=make_bundle([a]),make_bundle([b]);assert left['sha256']!=right['sha256']
    result=compare_bundles(left,right)
    assert result['status']=='unchanged' and result['behavior_status']=='not-evaluated'
    assert result['occurrence_bindings_changed'] and result['changes']==[]


def test_omitted_members_are_unknown_and_explicit_pairs_are_one_to_one():
    a,b=source('a',{'value':21}),source('b',{'value':22})
    left,right=make_bundle([a]),make_bundle([b])
    result=compare_bundles(left,right)
    assert result['status']=='unknown' and {row['classification'] for row in result['changes']}=={'added','removed'}
    pair={'left_record_id':left['records'][0]['record_id'],'right_record_id':right['records'][0]['record_id']}
    result=compare_bundles(left,right,[pair]);assert result['status']=='changed' and len(result['changes'])==1
    assert result['changes'][0]['classification']=='paired-record-changed'
    assert len(result['closure']['left']['records'])==len(result['closure']['right']['records'])==1
    with pytest.raises(ValueError,match='one-to-one'):compare_bundles(left,right,[pair,pair])
    with pytest.raises(ValueError,match='missing'):compare_bundles(left,right,[{**pair,'left_record_id':'missing'}])


def test_tampered_document_record_and_bundle_hashes_never_compare():
    a=source('first',{'value':21});a['document_base64']=base64.b64encode(b'changed').decode()
    with pytest.raises(ValueError,match='hash'):make_bundle([a])
    good=make_bundle([source('valid',{'value':21})]);bad=copy.deepcopy(good);bad['records'][0]['operation']='wrong'
    with pytest.raises(ValueError,match='hash|identity'):compare_bundles(good,bad)


def test_unknown_histories_keep_every_revision_and_require_their_evidence_closure():
    original=make_bundle([source('original',{'value':21})]);key=original['records'][0]['record_id']
    first={'unknown_id':'boundary','history':[{'revision':1,'state':'open','statement':'Other inputs remain unknown','evidence_ids':[key]}]}
    second=copy.deepcopy(first);second['history'].append({'revision':2,'state':'resolved','statement':'Only the selected boundary was checked',
        'resolution':'Caller declares this narrow question answered','evidence_ids':[key]})
    left=make_bundle([source('original',{'value':21})],[first]);right=make_bundle([source('original',{'value':21})],[second])
    result=compare_bundles(left,right);row=result['changes'][0]
    assert row['classification']=='history-advanced' and row['right_history']==second['history']
    assert result['behavior_status']=='not-evaluated'
    gap=copy.deepcopy(second);gap['history'][1]['revision']=3
    with pytest.raises(ValueError,match='complete|revision'):make_bundle([source('original',{'value':21})],[gap])
    missing=copy.deepcopy(first);missing['history'][0]['evidence_ids']=['missing']
    with pytest.raises(ValueError,match='missing'):make_bundle([source('original',{'value':21})],[missing])


def test_diverging_unknown_histories_do_not_discard_a_resolution():
    item=source('original',{'value':21});key=make_bundle([item])['records'][0]['record_id']
    a={'unknown_id':'boundary','history':[{'revision':1,'state':'open','statement':'Unresolved A','evidence_ids':[key]}]}
    b=copy.deepcopy(a);b['history'][0]['statement']='Unresolved B'
    result=compare_bundles(make_bundle([item],[a]),make_bundle([item],[b]))
    assert result['status']=='unknown' and result['changes'][0]['classification']=='history-diverged'


@pytest.mark.parametrize('kind',['unknowns','pairs'])
def test_empty_wrong_container_types_are_rejected_instead_of_becoming_defaults(kind):
    item=source('original',{'value':21});bundle=make_bundle([item])
    with pytest.raises(ValueError,match='list'):
        if kind=='unknowns':make_bundle([item],{})
        else:compare_bundles(bundle,bundle,{})


def function_document(address,callees=(),complete=True,session='original-context'):
    def identity(value):return {'address':value,'name':'duplicate-label','classification':None,
        'body':{'available':False,'reason':'Original synthetic address-only fixture'}}
    value={'procedure':{**identity(address),'signature':None,'locals':[]},'pseudocode':'','assembly':[],
        'comments':[],'callers':[],'callees':[identity(value) for value in callees],
        'incoming_references':[],'outgoing_references':[],'referenced_strings':[],'referenced_names':[],
        'basic_blocks':[],'native_api':None,'native_value_flow':None,'facet_availability':{'callees':{'available':True}},'limitations':[]}
    return {'operation':'binary.analyze_function','artifact_sha256':'a'*64,'session_id':session,
        'result':{'value':value,'limitations':[],'relationship_coverage':{'status':'complete'} if complete else {
            'status':'partial','limited_directions':['callees'],'limitations':['Missing indirect targets']}}}


def call_paths(tmp_path,documents,start='0x1',goal='0x4',change_input=None):
    from theseus.native_analysis import engine
    configured=engine()
    if not configured['available']:pytest.skip('Requires built native analysis core')
    inputs=[]
    for index,document in enumerate(documents):
        raw=json.dumps(document,ensure_ascii=False).encode();path=tmp_path/f'function-{index}.json';path.write_bytes(raw)
        inputs.append({'job_id':'function-'+str(index),'selected':True,'path':str(path),'operation':'binary.analyze_function',
            'artifact_id':'original-artifact','artifact_sha256':'a'*64,'analysis_sha256':hashlib.sha256(raw).hexdigest(),
            'provider':{'id':'original-fixture','version':'1','profile_sha256':'b'*64,'analysis_revision':0}})
    if change_input:change_input(inputs)
    request=tmp_path/'request.json';output=tmp_path/'output.json'
    request.write_text(json.dumps({'operation':'evidence.call_paths','path':inputs[0]['path'],
        'expected_input_sha256':inputs[0]['analysis_sha256'],'source_artifact_sha256':'a'*64,
        'source_inputs':inputs,'parameters':{'query':{'start':start,'goal':goal}}}),encoding='utf8')
    result=subprocess.run([configured['node'],configured['entry'],str(request),str(output)],capture_output=True,text=True,encoding='utf8',timeout=30)
    assert result.returncode==0,result.stderr[-3500:]
    return json.loads(output.read_text(encoding='utf8'))['result']


def test_all_shortest_diamond_paths_keep_address_identity_and_cite_every_edge(tmp_path):
    result=call_paths(tmp_path,[function_document('0x01',['0x2','0x3','0x5']),function_document('0x2',['0x4']),
        function_document('0x3',['0x4']),function_document('0x4'),function_document('0x5',['0x6']),function_document('0x6',['0x4'])],start='0X0001')
    assert result['status']=='found' and result['shortest_hops']==2 and result['search_scope']['exhaustive']
    assert [[node['address'] for node in path['nodes']] for path in result['paths']]==[['0x1','0x2','0x4'],['0x1','0x3','0x4']]
    assert all(edge['evidence_links'] for path in result['paths'] for edge in path['edges'])
    assert len(result['closure'])==6 and all(row['document_base64'] and 'path' not in row for row in result['closure'])


@pytest.mark.parametrize('failure',['missing-dossier','partial','provider','revision','context','incomplete-shape','ambiguous'])
def test_incomplete_or_mixed_call_graphs_never_certify_a_known_path(tmp_path,failure):
    documents=[function_document('0x1',['0x2','0x3']),function_document('0x2',['0x4']),
        function_document('0x3',['0x4']),function_document('0x4')]
    change=None
    if failure=='missing-dossier':documents.pop(2)
    elif failure=='partial':documents[2]=function_document('0x3',['0x4'],False)
    elif failure=='provider':change=lambda rows:rows[2]['provider'].update(version='2')
    elif failure=='revision':change=lambda rows:rows[2]['provider'].update(analysis_revision=1)
    elif failure=='context':documents[2]['session_id']='different-context'
    elif failure=='incomplete-shape':del documents[2]['result']['value']['procedure']['body']
    else:documents.append(function_document('0x3',[]))
    result=call_paths(tmp_path,documents,change_input=change)
    assert result['status']=='unknown' and result['paths']==[] and result['shortest_hops'] is None
    assert not result['search_scope']['exhaustive'] and result['blockers']


def test_call_graph_cycles_unreachable_and_zero_hop_are_explicit(tmp_path):
    documents=[function_document('0x1',['0x2']),function_document('0x2',['0x1']),function_document('0x4')]
    result=call_paths(tmp_path,documents)
    assert result['status']=='not_found' and result['search_scope']['exhaustive']
    result=call_paths(tmp_path,documents,goal='0x1')
    assert result['status']=='found' and result['shortest_hops']==0 and len(result['paths'])==1


def test_call_path_long_chain_does_not_depend_on_recursive_depth(tmp_path):
    count=1100
    documents=[function_document(hex(index),[hex(index+1)] if index<count else []) for index in range(1,count+1)]
    result=call_paths(tmp_path,documents,goal=hex(count))
    assert result['status']=='found' and result['shortest_hops']==count-1 and len(result['paths'][0]['nodes'])==count


def test_aggregation_recomputes_runtime_and_preserves_missing_or_tampered_observations():
    from theseus.retained_evidence import aggregate,record
    from theseus.process_compare import compare_results
    from test_process_compare import observation
    def row(key,operation,value,selected=True):
        original=source(key,value,operation)
        return {'source':original,'record':record(original),'document':json.loads(base64.b64decode(original['document_base64'])),'selected':selected}
    a=row('reference','process.capture',observation(b'21'),False);b=row('candidate','process.capture',observation(b'22'),False)
    checked=compare_results(a['document']['result'],b['document']['result'],{'dimensions':['stdout','exit']})
    checked.update(reference_analysis_sha256=a['record']['analysis_sha256'],candidate_analysis_sha256=b['record']['analysis_sha256'])
    comparison=row('comparison','process.compare',checked)
    result=aggregate([comparison,a,b],[])
    assert result['comparisons'][0]['status']=='different-selected-observations'
    assert len(result['closure']['records'])==3
    assert aggregate([comparison,a],[])['status']=='unknown'
    bad=copy.deepcopy(comparison);bad['document']['result']['dimensions'][0]['state']='same'
    assert aggregate([bad,a,b],[])['comparisons'][0]['status']=='unknown'


def test_explicit_correlation_has_no_name_matching_or_causality_and_keeps_uncertainty():
    from theseus.retained_evidence import correlate
    static={'job_id':'s','record_id':'rec_static','scope':'static-candidates','status':'validated-static-candidates',
        'dimensions':[{'logical_path':'module.py','classification':'changed'}],'evidence_links':['rec_static']}
    runtime={'job_id':'r','record_id':'rec_runtime','scope':'runtime-observations','status':'different-selected-observations',
        'dimensions':[{'dimension':'stdout','state':'different'}],'evidence_links':['rec_runtime']}
    summary={'comparisons':[static,runtime],'closure':{'all':'retained'},'limitations':[]}
    hypothesis={'id':'h','static_record_id':'rec_static','logical_path':'module.py','runtime_record_id':'rec_runtime','dimension':'stdout','expected':'both-changed'}
    result=correlate(summary,[hypothesis]);assert result['hypotheses'][0]['status']=='consistent-with-declared-association'
    assert result['causality']=='not-established' and result['closure']==summary
    wrong={**hypothesis,'id':'wrong','logical_path':'same-label-but-another-module.py'}
    assert correlate(summary,[wrong])['hypotheses'][0]['status']=='unknown'
    assert correlate(summary,[{**hypothesis,'expected':'static-only'}])['hypotheses'][0]['status']=='contradicts-declared-association'
    runtime['dimensions'][0]['state']='unknown'
    assert correlate(summary,[hypothesis])['hypotheses'][0]['status']=='unknown'


def test_multi_input_api_rechecks_comparisons_and_transfers_without_original_paths(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from theseus.evidence import Evidence
    from theseus.workflow import Workflow
    from test_native_analysis import wait
    from test_retained_process_scenarios import capture
    app=create_app(tmp_path/'data',port=64190)
    with TestClient(app,base_url='http://127.0.0.1:64190') as client:
        # A test client exercises the same product API and workers; live MCP and
        # browser acceptance are recorded separately, never inferred from this.
        client.get('/')
        store=app.state.comparisons.store
        pid=store.create_project('Retained evidence transfer')['id'];base='/api/projects/'+pid
        left_dir=tmp_path/'left';right_dir=tmp_path/'right';left_dir.mkdir();right_dir.mkdir()
        (left_dir/'rule.py').write_text('def rule(x): return x*7\n',encoding='utf8')
        (right_dir/'rule.py').write_text('def rule(x): return x*8\n',encoding='utf8')
        a=store.add_artifact(pid,left_dir);b=store.add_artifact(pid,right_dir)
        def run(operation,artifact,parameters):
            response=client.post(base+'/artifacts/'+artifact+'/analyses',json={'operation':operation,'parameters':parameters})
            assert response.status_code==200,response.text[:600]
            job=wait(client,response.json());assert job['state']=='finished',job
            return job
        inventories=[run('artifact.inventory',artifact['id'],{}) for artifact in (a,b)]
        static=run('artifact.compare',a['id'],{'reference_job_id':inventories[0]['id'],'candidate_job_id':inventories[1]['id']})
        captures=[capture(store,pid,tmp_path,name,expression) for name,expression in (
            ('reference','[x*7 for x in values]'),('candidate','[x*8 for x in values]'))]
        runtime=run('process.compare',captures[0]['result']['artifact_id'],{
            'reference_job_id':captures[0]['id'],'candidate_job_id':captures[1]['id'],'query':{'dimensions':['stdout','exit']}})
        left=run('evidence.bundle',a['id'],{'source_job_ids':[inventories[0]['id'],static['id']]})
        right=run('evidence.bundle',b['id'],{'source_job_ids':[inventories[1]['id']]})
        bundles=run('evidence.compare_bundles',a['id'],{'reference_job_id':left['id'],'candidate_job_id':right['id']})
        assert client.get('/api/jobs/'+bundles['id']+'/analysis.json').json()['result']['behavior_status']=='not-evaluated'
        selected=[static['id'],runtime['id']]
        summary=run('evidence.changed_behavior',a['id'],{'source_job_ids':selected})
        document=client.get('/api/jobs/'+summary['id']+'/analysis.json').json()['result']
        by_op={row['operation']:row for row in document['comparisons']}
        assert by_op['artifact.compare']['status']=='validated-static-candidates'
        assert by_op['process.compare']['status']=='different-selected-observations'
        hypothesis={'id':'original-rule','static_record_id':by_op['artifact.compare']['record_id'],'logical_path':'rule.py',
            'runtime_record_id':by_op['process.compare']['record_id'],'dimension':'stdout','expected':'both-changed'}
        correlated=run('evidence.correlate',a['id'],{'source_job_ids':selected,'query':{'hypotheses':[hypothesis]}})
        assert client.get('/api/jobs/'+correlated['id']+'/analysis.json').json()['result']['hypotheses'][0]['status']=='consistent-with-declared-association'
        evidence=Evidence(Workflow(app.state.comparisons));portable=evidence.export(pid);loaded=evidence.load(portable)
        new_pid=loaded['project']['id'];mapping=loaded['id_map']
        old_paths={str(left_dir),str(right_dir)}
        for directory in (left_dir,right_dir):(directory/'rule.py').unlink();directory.rmdir()
        for name in ('reference','candidate'):(tmp_path/name/'original.py').unlink()
        original_exists=Path.exists
        def guarded(path):
            if str(path) in old_paths:pytest.fail('Retained operation checked an original artifact path')
            return original_exists(path)
        monkeypatch.setattr(Path,'exists',guarded)
        base='/api/projects/'+new_pid
        imported=run('evidence.correlate',mapping[a['id']],{'source_job_ids':[mapping[key] for key in selected],
            'query':{'hypotheses':[hypothesis]}})
        retained=client.get('/api/jobs/'+imported['id']+'/analysis.json').json()['result']
        assert retained['hypotheses'][0]['status']=='consistent-with-declared-association' and retained['causality']=='not-established'
        assert imported['result']['original_source_check']=='not-performed-retained-input'
        # Duplicated source IDs are rejected before a job is created.
        before=len(store.items('jobs',new_pid))
        response=client.post(base+'/artifacts/'+mapping[a['id']]+'/analyses',json={'operation':'evidence.bundle',
            'parameters':{'source_job_ids':[mapping[static['id']],mapping[static['id']]]}})
        assert response.status_code==400 and len(store.items('jobs',new_pid))==before
