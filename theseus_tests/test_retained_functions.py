"""Original complete dossiers and explicit native/static/runtime associations."""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from test_retained_evidence import function_document


def compare_functions(tmp_path,left,right,mutate=None):
    from theseus.native_analysis import engine
    configured=engine()
    if not configured['available']:pytest.skip('Requires built native analysis core')
    inputs=[]
    for index,document in enumerate([left,right]):
        raw=json.dumps(document,ensure_ascii=False).encode();path=tmp_path/f'function-{index}.json';path.write_bytes(raw)
        inputs.append({'job_id':str(index),'selected':True,'path':str(path),'operation':'binary.analyze_function',
            'artifact_id':'fixture-'+str(index),'artifact_sha256':document['artifact_sha256'],
            'analysis_sha256':hashlib.sha256(raw).hexdigest(),
            'provider':{'id':'original-provider','version':'1','profile_sha256':'b'*64,'analysis_revision':0}})
    if mutate:mutate(inputs)
    request=tmp_path/'request.json';output=tmp_path/'output.json'
    request.write_text(json.dumps({'operation':'evidence.compare_functions','path':inputs[0]['path'],
        'expected_input_sha256':inputs[0]['analysis_sha256'],'source_artifact_sha256':inputs[0]['artifact_sha256'],
        'candidate_path':inputs[1]['path'],'expected_candidate_sha256':inputs[1]['analysis_sha256'],
        'source_inputs':inputs,'source_input_roles':{'reference_job_id':'0','candidate_job_id':'1'},'parameters':{}}),encoding='utf8')
    result=subprocess.run([configured['node'],configured['entry'],str(request),str(output)],capture_output=True,text=True,encoding='utf8',timeout=30)
    assert result.returncode==0,result.stderr[-2500:]
    return json.loads(output.read_text(encoding='utf8'))['result']


def complete_function(expression):
    document=function_document('0x1000');value=document['result']['value']
    value['procedure']['name']='original_rule';value['procedure']['signature']='int original_rule(int x)'
    value['pseudocode']='return '+expression+';';value['assembly']=['original fixture instruction '+expression]
    value['facet_availability']={key:{'available':True} for key in ('pseudocode','assembly','comments','callers','callees','references','strings_names','cfg')}
    return document


def test_retained_function_comparison_preserves_all_dimensions_and_exact_text(tmp_path):
    a,b=complete_function('x*7'),complete_function('x*8');b['artifact_sha256']='c'*64
    result=compare_functions(tmp_path,a,b)
    dimensions={row['dimension']:row for row in result['dimensions']}
    assert result['format']=='vitruvius.retained-function-comparison/1' and len(dimensions)==8
    assert dimensions['pseudocode']['status']==dimensions['assembly']['status']=='changed'
    assert dimensions['identity']['status']=='unchanged'
    assert result['behavior_status']=='not-evaluated' and len(result['closure'])==2
    assert all(row['analysis_sha256'] and row['document_base64'] for row in result['closure'])
    assert all(row['evidence_links'] for row in result['dimensions'])


@pytest.mark.parametrize('cause',['provider','profile','missing-provider','facet','dossier'])
def test_mixed_or_missing_function_facts_remain_unknown(tmp_path,cause):
    a,b=complete_function('x*7'),complete_function('x*7');change=None
    if cause=='provider':change=lambda rows:rows[1]['provider'].update(version='2')
    elif cause=='profile':change=lambda rows:rows[1]['provider'].update(profile_sha256='d'*64)
    elif cause=='missing-provider':change=lambda rows:rows[1].update(provider=None)
    elif cause=='facet':b['result']['value']['facet_availability']['pseudocode']={'available':False,'reason':'Not observed'}
    else:del b['result']['value']['procedure']['body']
    result=compare_functions(tmp_path,a,b,change)
    assert result['status']=='unknown'
    assert not result['dimensions'] or next(row for row in result['dimensions'] if row['dimension']=='pseudocode')['status']=='unknown'


def test_api_recomputes_functions_and_unchanged_occurrences_then_correlates_after_transfer(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from theseus.store import identifier
    from test_native_analysis import wait
    from test_process_compare import observation
    app=create_app(tmp_path/'data',port=64200)
    with TestClient(app,base_url='http://127.0.0.1:64200') as client:
        client.get('/');store=app.state.store;pid=store.create_project('Original synthetic function evidence')['id']
        base='/api/projects/'+pid
        def run(operation,artifact,parameters):
            response=client.post(base+'/artifacts/'+artifact+'/analyses',json={'operation':operation,'parameters':parameters})
            assert response.status_code==200,response.text[:500]
            job=wait(client,response.json());assert job['state']=='finished',job
            return job
        def document(job):return client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']
        def saved(operation,value,artifact=None,session=None):
            key=identifier();folder=store.directory/'analyses'/key;folder.mkdir(parents=True);path=folder/'analysis.json'
            payload=value if operation=='binary.analyze_function' else {'operation':operation,'result':value}
            path.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf8')
            artifact=artifact or store.add_artifact(pid,path)
            result={'kind':'native_analysis' if session else 'runtime_analysis','operation':operation,
                'artifact_id':artifact['id'],'artifact_sha256':artifact['sha256'],'artifact_name':artifact['name'],
                'analysis_file':str(path),'analysis_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'parameters':{},'cases':[]}
            if session:result.update(session_id=session,analysis_revision=0)
            store.save_job(pid,key,'finished',result);store.index_analysis(key,payload['result']);return store.job(key)
        functions=[];directories=[]
        for label,expression in [('left','x*7'),('right','x*8')]:
            directory=tmp_path/label;directory.mkdir();directories.append(directory)
            (directory/'stable.py').write_text('unchanged original bytes\n',encoding='utf8')
            native=directory/'native.c';native.write_text('int original_rule(int x) { return '+expression+'; }\n',encoding='utf8')
            artifact=store.add_artifact(pid,native);session=identifier()
            profile={'engine':'original-provider','version':'1','options':{}}
            store.save_job(pid,session,'finished',{'kind':'binary_session','artifact_id':artifact['id'],
                'profile':profile,'profile_sha256':'b'*64,'revision':0,'session_state':'closed'})
            dossier=complete_function(expression);dossier.update(artifact_sha256=artifact['sha256'],session_id=session)
            functions.append(saved('binary.analyze_function',dossier,artifact,session))
        function_compare=run('evidence.compare_functions',functions[0]['result']['artifact_id'],{
            'reference_job_id':functions[0]['id'],'candidate_job_id':functions[1]['id']})
        assert next(row for row in document(function_compare)['dimensions'] if row['dimension']=='pseudocode')['status']=='changed'
        captures=[saved('process.capture',observation(value)) for value in (b'21',b'24')]
        process_compare=run('process.compare',captures[0]['result']['artifact_id'],{
            'reference_job_id':captures[0]['id'],'candidate_job_id':captures[1]['id'],'query':{'dimensions':['stdout','exit']}})
        artifacts=[store.add_artifact(pid,directory) for directory in directories]
        inventories=[run('artifact.inventory',artifact['id'],{}) for artifact in artifacts]
        static=run('artifact.compare',artifacts[0]['id'],{'reference_job_id':inventories[0]['id'],'candidate_job_id':inventories[1]['id']})
        selected=[function_compare['id'],process_compare['id'],static['id']];aid=functions[0]['result']['artifact_id']
        summary=run('evidence.changed_behavior',aid,{'source_job_ids':selected});reports={row['operation']:row for row in document(summary)['comparisons']}
        assert reports['evidence.compare_functions']['status']=='validated-static-candidates'
        assert next(row for row in reports['artifact.compare']['dimensions'] if row['logical_path']=='stable.py')['classification']=='unchanged'
        runtime_id=reports['process.compare']['record_id'];function_id=reports['evidence.compare_functions']['record_id'];static_id=reports['artifact.compare']['record_id']
        hypotheses=[{'id':'native-text','static_record_id':function_id,'static_dimension':'pseudocode','runtime_record_id':runtime_id,
            'dimension':'stdout','expected':'both-changed','side_alignment':'left_to_left','statement':'Explicit selected versions correspond'},
            {'id':'stable-file','static_record_id':static_id,'logical_path':'stable.py','runtime_record_id':runtime_id,
            'dimension':'stdout','expected':'runtime-only','side_alignment':'left_to_right','statement':'Compare the explicitly reversed run sides'}]
        correlated=run('evidence.correlate',aid,{'source_job_ids':selected,'query':{'hypotheses':hypotheses}})
        result=document(correlated)
        assert all(row['status']=='consistent-with-declared-association' for row in result['hypotheses'])
        assert result['hypotheses'][1]['aligned_inputs'][0]['runtime_side']=='candidate' and result['causality']=='not-established'
        absent_alignment={key:value for key,value in hypotheses[0].items() if key!='side_alignment'}
        unresolved=run('evidence.correlate',aid,{'source_job_ids':selected,'query':{'hypotheses':[absent_alignment]}})
        assert document(unresolved)['hypotheses'][0]['status']=='unknown'
        loaded=app.state.evidence.load(app.state.evidence.export(pid));new_pid=loaded['project']['id'];mapping=loaded['id_map']
        old_paths={str(path) for directory in directories for path in [directory,*directory.iterdir()]}
        for directory in directories:
            for path in directory.iterdir():path.unlink()
            directory.rmdir()
        original_exists=Path.exists
        def guarded(path):
            if str(path) in old_paths:pytest.fail('Retained function operation checked an original artifact path')
            return original_exists(path)
        monkeypatch.setattr(Path,'exists',guarded);base='/api/projects/'+new_pid
        fresh=run('evidence.correlate',mapping[aid],{'source_job_ids':[mapping[key] for key in selected],
            'query':{'hypotheses':hypotheses}})
        assert all(row['status']=='consistent-with-declared-association' for row in document(fresh)['hypotheses'])
        fresh_pair=run('evidence.compare_functions',mapping[aid],{'reference_job_id':mapping[functions[0]['id']],
            'candidate_job_id':mapping[functions[1]['id']]})
        assert document(fresh_pair)==document(function_compare)
