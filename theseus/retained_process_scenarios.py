"""Reconstruction obligations from hash-bound process captures, without replay."""
import hashlib
import json
import re

from jsonschema import validate as validate_json,ValidationError

from .process_compare import QUERY,compare_results,canonical

KIND='retained-process-scenarios'
FIELDS={'kind','reference_job_id','reference_sha256','candidate_job_id','candidate_sha256','query'}


def validate(definition):
    if set(definition)!=FIELDS:raise ValueError('Retained process scenarios need both capture IDs/hashes and an explicit comparison query')
    for side in ('reference','candidate'):
        if not isinstance(definition[side+'_job_id'],str) or not definition[side+'_job_id']:raise ValueError('Choose the '+side+' capture')
        sha=definition[side+'_sha256']
        if not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('Choose the complete '+side+' SHA-256')
    try:validate_json(definition['query'],QUERY)
    except ValidationError as error:raise ValueError('Invalid process comparison query: '+error.message) from error


def binding(store,project_id,key,expected):
    job=store.job(key);result=job['result']
    if job['project_id']!=project_id:raise ValueError('The process capture belongs to another project')
    if result.get('kind')!='runtime_analysis' or result.get('operation')!='process.capture':raise ValueError('Choose a process.capture observation')
    if result.get('analysis_sha256')!=expected:raise ValueError('The retained process SHA-256 differs from the selected identity')
    return job


def validate_bindings(store,project_id,definition):
    validate(definition)
    for side in ('reference','candidate'):binding(store,project_id,definition[side+'_job_id'],definition[side+'_sha256'])


def observe(store,project_id,definition,side):
    from .native_analysis import analysis_file
    key,expected=definition[side+'_job_id'],definition[side+'_sha256']
    result={'kind':KIND,'capture_job_id':key,'analysis_sha256':expected,'valid':False,'query':definition['query'],'sources':[]}
    try:
        job=binding(store,project_id,key,expected)
        artifact=store.artifact(project_id,job['result']['artifact_id'])
        result['sources']=[{'side':side,'job_id':key,'artifact_id':artifact['id'],'sha256':expected}]
        if job['state'] not in {'finished','imported'}:raise ValueError('The selected process capture did not finish')
        raw=analysis_file(store,key).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected or artifact['sha256']!=expected:raise ValueError('The retained process document differs from its SHA-256')
        document=json.loads(raw)
        if document.get('operation')!='process.capture':raise ValueError('The retained document is not a process capture')
        record=document['result'];result['record']=record
        check=compare_results(record,record,definition['query'])
        if check['state']=='unknown':raise ValueError('The selected process dimensions are incomplete or unavailable')
        if side=='reference' and check['state']!='same-selected-observations':raise ValueError('The reference does not satisfy its declared trace obligations')
        result['valid']=True
    except (OSError,LookupError,ValueError,TypeError,AttributeError) as error:
        result['error']=type(error).__name__+': '+str(error)
    return result


def comparison(reference,candidate):
    if not reference['valid'] or not candidate['valid'] or canonical(reference['query'])!=canonical(candidate['query']):return None
    return compare_results(reference['record'],candidate['record'],reference['query'])


def valid_pair(reference,candidate):
    report=comparison(reference,candidate)
    return report is not None and report['state']!='unknown'


def differences(reference,candidate):
    report=comparison(reference,candidate)
    if report is None:return [side+': '+row.get('error','Different comparison query') for side,row in (('reference',reference),('candidate',candidate)) if not row['valid']] or ['Comparison queries differ']
    if report['state']=='unknown':return ['Selected process observations cannot be compared completely with aligned inputs']
    return [row['dimension']+' differs' for row in report['dimensions'] if row['state']=='different']


def unchanged(store,project_id,observation):
    definition={'reference_job_id':observation.get('capture_job_id'),'reference_sha256':observation.get('analysis_sha256'),'query':observation['query']}
    # Mutants may contradict trace obligations. Check their unchanged identity as candidates.
    definition.update(candidate_job_id=definition['reference_job_id'],candidate_sha256=definition['reference_sha256'])
    current=observe(store,project_id,definition,'candidate')
    return current['valid'] and current['analysis_sha256']==observation.get('analysis_sha256')
