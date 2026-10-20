"""Hash-bound observations of saved page steps; never connect or replay."""
import hashlib
import json
import re


KIND='retained-page-scenarios'
FIELDS={'kind','reference_job_id','reference_sha256','candidate_job_id','candidate_sha256'}


def selected(definition):
    return definition.get('kind')==KIND


def literal(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False)


def validate(definition):
    if set(definition)!=FIELDS or not selected(definition):
        raise ValueError('A retained-page-scenarios definition needs both capture IDs and SHA-256 identities')
    for side in ('reference','candidate'):
        if not isinstance(definition[side+'_job_id'],str) or not definition[side+'_job_id']:
            raise ValueError('Choose the '+side+' capture job')
        value=definition[side+'_sha256']
        if not isinstance(value,str) or re.fullmatch('[0-9a-f]{64}',value) is None:
            raise ValueError('The '+side+' capture needs its complete lowercase SHA-256')


def binding(store,project_id,job_id,expected):
    job=store.job(job_id)
    if job['project_id']!=project_id:
        raise ValueError('The retained capture belongs to another project')
    result=job['result']
    if result.get('kind')!='runtime_analysis' or result.get('operation')!='browser.scenario':
        raise ValueError('Choose a retained browser.scenario capture')
    if result.get('analysis_sha256')!=expected:
        raise ValueError('The retained capture SHA-256 differs from the selected identity')
    return job


def validate_bindings(store,project_id,definition):
    validate(definition)
    for side in ('reference','candidate'):
        binding(store,project_id,definition[side+'_job_id'],definition[side+'_sha256'])


def observe(store,project_id,definition,side):
    from .native_analysis import analysis_file
    key,expected=definition[side+'_job_id'],definition[side+'_sha256']
    result={'kind':KIND,'capture_job_id':key,'analysis_sha256':expected,'valid':False,
        'requests':[],'responses':[],'sources':[]}
    try:
        job=binding(store,project_id,key,expected)
        artifact=store.artifact(project_id,job['result']['artifact_id'])
        result['sources']=[{'side':side,'job_id':key,'artifact_id':artifact['id'],'sha256':expected}]
        if job['state'] not in {'finished','imported'}:
            raise ValueError('The selected capture did not finish')
        raw=analysis_file(store,key).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected or artifact['sha256']!=expected:
            raise ValueError('The retained document SHA-256 differs from the selected identity')
        document=json.loads(raw)
        if document['operation']!='browser.scenario':
            raise ValueError('The retained document is not a browser.scenario capture')
        capture=document['result']
        if capture.get('status')!='observed' or 'error' in capture:
            raise ValueError('The retained capture is incomplete or failed')
        if capture.get('journal_recovery',{}).get('gap') is not None:
            raise ValueError('The retained capture has an incomplete protocol journal')
        plan,steps=capture['parameters']['steps'],capture['steps']
        if not isinstance(plan,list) or not plan or not isinstance(steps,list) or len(steps)!=len(plan):
            raise ValueError('The retained scenario needs a nonempty complete step sequence')
        for index,(request,step) in enumerate(zip(plan,steps)):
            if not isinstance(request,dict) or not isinstance(request.get('method'),str) or not request['method'] or not isinstance(request.get('parameters'),dict):
                raise ValueError('The retained step request is malformed')
            if type(step['index']) is not int or step['index']!=index or step['state']!='completed' or 'error' in step:
                raise ValueError('The retained step is incomplete, duplicated or out of order')
            if literal(step['request'])!=literal(request):
                raise ValueError('The retained request and completed receipt disagree')
            response=step['response']
            if not isinstance(response,dict) or not isinstance(response.get('result'),dict) or 'error' in response or 'exceptionDetails' in response['result']:
                raise ValueError('The retained response is incomplete or failed')
            if type(step['command_id']) is not int or type(response.get('id')) is not int or response['id']!=step['command_id']:
                raise ValueError('The retained CDP response does not match its command')
            result['requests'].append(request)
            # Only the protocol envelope ID is local; all payload values stay literal.
            result['responses'].append({k:v for k,v in response.items() if k!='id'})
        literal(result['responses'])
        result['valid']=True
    except (OSError,LookupError,ValueError,TypeError,AttributeError) as exc:
        result['error']=type(exc).__name__+': '+str(exc)
    return result


def valid_pair(reference,candidate):
    return reference['valid'] and candidate['valid'] and literal(reference['requests'])==literal(candidate['requests'])


def differences(reference,candidate):
    if not reference['valid'] or not candidate['valid']:
        return [side+': '+row.get('error','Invalid retained capture') for side,row in
            (('reference',reference),('candidate',candidate)) if not row['valid']]
    if literal(reference['requests'])!=literal(candidate['requests']):
        return ['Saved scenario requests do not align literally by position']
    return ['Recorded responses differ'] if literal(reference['responses'])!=literal(candidate['responses']) else []


def unchanged(store,project_id,observation):
    if observation.get('kind')!=KIND:return False
    definition={'reference_job_id':observation.get('capture_job_id'),'reference_sha256':observation.get('analysis_sha256')}
    current=observe(store,project_id,definition,'reference')
    return current['valid'] and current['analysis_sha256']==observation.get('analysis_sha256')
