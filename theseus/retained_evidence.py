"""Canonical sets of retained bytes; membership never substitutes for behavior."""
import base64
import hashlib
import json
import re
from pathlib import Path


SET_PARAMETERS={'type':'object','additionalProperties':False,'required':['source_job_ids'],'properties':{
    'source_job_ids':{'type':'array','minItems':1,'uniqueItems':True,'items':{'type':'string','minLength':1}},
    'query':{'type':'object'}}}
STATES=['finished','failed','cancelled','interrupted','imported']
OPERATIONS=[{'name':name,'title':title,'input':'set','worker':'python','retained_only':True,
    'source_states':STATES,'inputSchema':SET_PARAMETERS,'description':description,'example':{'query':example},
    **({'requires_operation':required} if required else {})}
    for name,title,description,example,required in [
        ('evidence.bundle','Evidencias · Guardar conjunto canónico',
         'Conserva los documentos seleccionados con sus bytes, hashes, ocurrencias e historial completo de incógnitas. No consulta las rutas originales.',{'unknowns':[]},None),
        ('evidence.changed_behavior','Evidencias · Agregar cambios observados',
         'Agrega comparaciones guardadas con su cierre de evidencias. Recalcula las dimensiones de procesos y separa los candidatos estáticos de las observaciones. Las ausencias siguen desconocidas.',{},['process.compare','artifact.compare']),
        ('evidence.correlate','Evidencias · Contrastar hipótesis estáticas y de ejecución',
         'Contrasta asociaciones declaradas entre un cambio estático y una dimensión observada. Conserva hipótesis desconocidas; una coincidencia no prueba causalidad.',
         {'hypotheses':[{'id':'hypothesis-1','static_record_id':'rec_sha256-from-aggregation','logical_path':'module.py','runtime_record_id':'rec_sha256-from-aggregation','dimension':'stdout','expected':'both-changed'}]},['process.compare','artifact.compare']),
    ]]
OPERATIONS += [{'name':'evidence.call_paths','title':'Evidencias · Todas las vías directas más cortas','input':'set',
    'retained_only':True,'source_states':STATES,'requires_operation':'binary.analyze_function','inputSchema':SET_PARAMETERS,
    'example':{'query':{'start':'0x1000','goal':'0x2000'}},
    'description':'Valida dossieres completos y enumera todas las vías directas más cortas, con citas por nodo y arista. Las funciones, coberturas o identidades ausentes quedan desconocidas; no conecta con el motor binario.'},
    {'name':'evidence.compare_bundles','title':'Evidencias · Comparar conjuntos guardados','input':'pair','worker':'python',
    'retained_only':True,'source_states':STATES,'requires_operation':'evidence.bundle',
    'inputSchema':{'type':'object','additionalProperties':False,'required':['reference_job_id','candidate_job_id'],
        'properties':{'reference_job_id':{'type':'string'},'candidate_job_id':{'type':'string'},'query':{'type':'object'}}},
    'example':{'query':{'record_pairs':[]}},
    'description':'Compara miembros, parejas explícitas uno a uno e historial completo de incógnitas. La omisión de un documento no demuestra un cambio de comportamiento.'}]


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(value):return hashlib.sha256(canonical(value).encode('utf8')).hexdigest()


def loads(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Retained JSON has duplicate object keys')
            result[key]=value
        return result
    def invalid(value):raise ValueError('Retained JSON has a non-finite number: '+value)
    return json.loads(raw.decode('utf8') if isinstance(raw,bytes) else raw,object_pairs_hook=pairs,parse_constant=invalid)


def digest(value):
    if not isinstance(value,str) or re.fullmatch('[a-f0-9]{64}',value) is None:raise ValueError('Invalid retained SHA-256 identity')
    return value


def record(source):
    try:raw=base64.b64decode(source['document_base64'],validate=True)
    except (KeyError,ValueError,TypeError) as error:raise ValueError('Invalid retained document bytes') from error
    if hashlib.sha256(raw).hexdigest()!=digest(source['analysis_sha256']):raise ValueError('Retained document hash differs from its identity')
    document=loads(raw)
    if not isinstance(document,dict) or document.get('operation')!=source['operation']:raise ValueError('Retained operation identity differs from its document')
    artifact=digest(source['artifact_sha256'])
    if 'artifact_sha256' in document and document['artifact_sha256']!=artifact:raise ValueError('Retained artifact identity differs from its document')
    provider=source.get('provider')
    if provider is not None and (not isinstance(provider,dict) or not isinstance(provider.get('id'),str) or not provider['id']):
        raise ValueError('Retained provider identity is malformed')
    value={'operation':source['operation'],'analysis_sha256':source['analysis_sha256'],'artifact_sha256':artifact,
        'provider':loads(canonical(provider)),'document_base64':base64.b64encode(raw).decode('ascii')}
    return {'record_id':'rec_'+sha(value),**value}


def unknown_histories(values,ids):
    if not isinstance(values,list):raise ValueError('Unknown histories must be a list')
    histories=[];names=set()
    for value in values:
        if not isinstance(value,dict) or set(value)!={'unknown_id','history'}:raise ValueError('Unknown history needs an ID and complete revisions')
        key=value['unknown_id'];history=value['history']
        if not isinstance(key,str) or not key or key in names:raise ValueError('Unknown history IDs must be nonempty and unique')
        names.add(key)
        if not isinstance(history,list) or not history:raise ValueError('Unknown history must contain every revision from 1')
        for index,revision in enumerate(history,1):
            if not isinstance(revision,dict) or set(revision)-{'revision','state','statement','evidence_ids','resolution'} or not {'revision','state','statement','evidence_ids'}<=set(revision):
                raise ValueError('Malformed unknown history revision')
            if type(revision['revision']) is not int or revision['revision']!=index:raise ValueError('Unknown history must contain complete consecutive revisions from 1')
            if revision['state'] not in {'open','resolved'} or not isinstance(revision['statement'],str) or not revision['statement']:
                raise ValueError('Unknown history state or statement is malformed')
            links=revision['evidence_ids']
            if not isinstance(links,list) or any(not isinstance(link,str) for link in links) or len(set(links))!=len(links):
                raise ValueError('Unknown history evidence links must be unique IDs')
            if set(links)-ids:raise ValueError('Unknown history references missing evidence')
            if 'resolution' in revision and not isinstance(revision['resolution'],str):raise ValueError('Unknown resolution must be text')
            if revision['state']=='resolved' and (not links or not revision.get('resolution','').strip()):
                raise ValueError('A declared resolution needs its evidence and explanation')
        histories.append(loads(canonical(value)))
    return sorted(histories,key=lambda value:value['unknown_id'])


def make_bundle(sources,unknowns=None):
    if not isinstance(sources,list) or not sources:raise ValueError('Choose at least one retained document')
    ids=[source.get('job_id') for source in sources]
    if any(not isinstance(key,str) or not key for key in ids) or len(set(ids))!=len(ids):raise ValueError('Retained inputs have missing or duplicate job IDs')
    records={};occurrences=[]
    for source in sources:
        item=record(source);records[item['record_id']]=item
        occurrences.append({'job_id':source['job_id'],'record_id':item['record_id']})
    value={'format':'vitruvius.retained-evidence-bundle/1','records':[records[key] for key in sorted(records)],
        'occurrences':sorted(occurrences,key=lambda row:row['job_id']),
        'unknowns':unknown_histories([] if unknowns is None else unknowns,set(records))}
    return {**value,'sha256':sha(value)}


def validate_bundle(value):
    if not isinstance(value,dict) or set(value)!={'format','records','occurrences','unknowns','sha256'} or value.get('format')!='vitruvius.retained-evidence-bundle/1':
        raise ValueError('Select a native retained evidence bundle')
    body={key:item for key,item in value.items() if key!='sha256'}
    if sha(body)!=digest(value['sha256']):raise ValueError('Retained bundle hash differs from its identity')
    records={}
    for item in value['records']:
        expected=record(item)
        if canonical(item)!=canonical(expected) or item['record_id'] in records:raise ValueError('Retained record identity is invalid or duplicated')
        records[item['record_id']]=item
    if not records:raise ValueError('Retained bundle has no records')
    occurrences=value['occurrences'];jobs=[]
    for row in occurrences:
        if not isinstance(row,dict) or set(row)!={'job_id','record_id'} or not isinstance(row['job_id'],str) or not row['job_id']:
            raise ValueError('Malformed retained occurrence identity')
        if row['record_id'] not in records:raise ValueError('Retained occurrence references missing evidence')
        jobs.append(row['job_id'])
    if len(set(jobs))!=len(jobs):raise ValueError('Retained occurrences have duplicate job IDs')
    if {row['record_id'] for row in occurrences}!=set(records):raise ValueError('Retained record has no occurrence binding')
    histories=unknown_histories(value['unknowns'],set(records))
    if histories!=value['unknowns'] or list(records)!=sorted(records) or occurrences!=sorted(occurrences,key=lambda row:row['job_id']):
        raise ValueError('Retained bundle is not in canonical order')
    return loads(canonical(value)),records


def compare_bundles(left,right,record_pairs=None):
    left,a=validate_bundle(left);right,b=validate_bundle(right);pairs=[] if record_pairs is None else record_pairs
    if not isinstance(pairs,list):raise ValueError('Explicit record pairs must be a list')
    selected_a=set();selected_b=set();changes=[]
    for pair in pairs:
        if not isinstance(pair,dict) or set(pair)!={'left_record_id','right_record_id'}:raise ValueError('Record pairs need exact left/right record IDs')
        x,y=pair['left_record_id'],pair['right_record_id']
        if x not in a or y not in b:raise ValueError('Explicit pair references a missing record')
        if x in selected_a or y in selected_b:raise ValueError('Explicit record pairs must be one-to-one')
        selected_a.add(x);selected_b.add(y)
        if canonical(a[x])!=canonical(b[y]):changes.append({'entity':'record','classification':'paired-record-changed',
            'left_record_id':x,'right_record_id':y,'evidence_links':[x,y],
            'interpretation':'The explicitly paired retained bytes or producer metadata differ; behavior was not evaluated'})
    for key in sorted((set(a)&set(b))-selected_a-selected_b):selected_a.add(key);selected_b.add(key)
    for side,records,selected in [('left',a,selected_a),('right',b,selected_b)]:
        for key in sorted(set(records)-selected):changes.append({'entity':'record','classification':'removed' if side=='left' else 'added',
            'left_record_id':key if side=='left' else None,'right_record_id':key if side=='right' else None,
            'evidence_links':[key],'interpretation':'Membership omission/addition only; this does not establish a behavioral change or equivalence'})
    unknown_a={row['unknown_id']:row['history'] for row in left['unknowns']};unknown_b={row['unknown_id']:row['history'] for row in right['unknowns']}
    for key in sorted(set(unknown_a)|set(unknown_b)):
        x,y=unknown_a.get(key,[]),unknown_b.get(key,[])
        if canonical(x)==canonical(y):continue
        classification='history-added' if not x else 'history-removed' if not y else 'history-advanced' if len(y)>len(x) and canonical(y[:len(x)])==canonical(x) else 'history-rewound' if len(x)>len(y) and canonical(x[:len(y)])==canonical(y) else 'history-diverged'
        changes.append({'entity':'unknown','unknown_id':key,'classification':classification,'left_history':x,'right_history':y,
            'evidence_links':sorted({link for revision in x+y for link in revision['evidence_ids']}),
            'interpretation':'Complete caller-declared histories are retained; a declared resolution is not a behavioral proof'})
    unknown=any(row['classification']!='paired-record-changed' for row in changes)
    return {'format':'vitruvius.retained-bundle-comparison/1','status':'unknown' if unknown else 'changed' if changes else 'unchanged',
        'behavior_status':'not-evaluated','left_bundle_sha256':left['sha256'],'right_bundle_sha256':right['sha256'],
        'query_sha256':sha({'record_pairs':sorted(pairs,key=canonical)}),'record_pairs':pairs,'changes':changes,
        'occurrence_bindings_changed':canonical(left['occurrences'])!=canonical(right['occurrences']),
        'closure':{'left':left,'right':right},'comparison_basis':'Canonical record membership, explicit one-to-one pairs and complete unknown histories',
        'limitations':['Only retained JSON documents and recorded producer metadata were compared; no original path or program was accessed.',
            'Record identity checks retained byte integrity; source authenticity and observation truth remain unknown.',
            'Equal membership is not behavioral equivalence. Missing members describe omissions.',
            'Repeated source jobs with identical immutable records retain all their separate occurrence bindings.']}


def bind_inputs(store,project_id,selected):
    """Bind stored receipts, including their closure, without reading original artifacts."""
    from .native_analysis import analysis_file
    result=[];seen=set();pending=list(reversed(selected));selected=set(selected)
    while pending:
        key=pending.pop()
        if key in seen:continue
        seen.add(key)
        try:
            job=store.job(key);value=job['result']
            if job['project_id']!=project_id or job['state'] not in STATES:raise ValueError('Retained input is outside the project or not terminal')
            path=analysis_file(store,key)
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=value['analysis_sha256']:raise ValueError('Retained document hash changed')
            document=loads(raw)
            if not isinstance(document,dict) or document.get('operation')!=value['operation']:
                raise ValueError('Retained operation identity differs')
            if 'artifact_sha256' in document and document['artifact_sha256']!=value['artifact_sha256']:
                raise ValueError('Retained artifact identity differs')
            provider=None
            if value.get('operation')=='binary.analyze_function':
                try:
                    session=store.job(value['session_id'])
                    if session['project_id']!=project_id:raise ValueError('Provider context is outside the project')
                    profile=session['result']['profile']
                    provider={'id':profile['engine'],'version':profile['version'],
                        'profile_sha256':session['result']['profile_sha256'],'analysis_revision':value.get('analysis_revision')}
                except (KeyError,LookupError):provider=None
            result.append({'job_id':key,'selected':key in selected,'path':str(path),'operation':value['operation'],
                'artifact_id':value['artifact_id'],'artifact_sha256':value['artifact_sha256'],
                'analysis_sha256':value['analysis_sha256'],'provider':provider})
            parents=[row['job_id'] for row in value.get('source_analyses',[])]
            if value.get('source_analysis_job_id'):parents.append(value['source_analysis_job_id'])
            pending.extend(reversed(parents))
        except (ValueError,LookupError,KeyError,OSError) as error:
            if key in selected:raise ValueError('Selected retained document is unavailable: '+key) from error
            result.append({'job_id':key,'selected':False,'error':str(error)})
    return result


def read_inputs(inputs):
    sources=[];missing=[]
    for value in inputs:
        if 'error' in value:missing.append({'job_id':value['job_id'],'reason':value['error']});continue
        raw=Path(value['path']).read_bytes()
        source={key:value[key] for key in ('job_id','operation','analysis_sha256','artifact_sha256','provider')}
        source['document_base64']=base64.b64encode(raw).decode('ascii')
        item=record(source)
        sources.append({'source':source,'record':item,'document':loads(raw),'selected':value['selected']})
    return sources,missing


def aggregate(sources,missing,validate_static=None):
    try:from .process_compare import compare_results
    except ImportError:from process_compare import compare_results
    by_hash={row['record']['analysis_sha256']:row for row in sources}
    reports=[]
    for row in sources:
        if not row['selected']:continue
        document=row['document'];operation=document['operation'];value=document.get('result',{})
        item={'job_id':row['source']['job_id'],'record_id':row['record']['record_id'],'operation':operation,
            'scope':'runtime-observations' if operation=='process.compare' else 'static-candidates',
            'status':'unknown','dimensions':[],'reasons':[]}
        if operation=='process.compare':
            parents=[by_hash.get(value.get(side+'_analysis_sha256')) for side in ('reference','candidate')]
            if any(parent is None or parent['document']['operation']!='process.capture' for parent in parents):
                item['reasons'].append('Missing hash-bound process capture closure')
            else:
                try:
                    checked=compare_results(parents[0]['document']['result'],parents[1]['document']['result'],value['query'])
                    retained={key:value.get(key) for key in checked}
                    if canonical(checked)!=canonical(retained):raise ValueError('Saved comparison differs from recomputed observations')
                    item.update(status=checked['state'],dimensions=checked['dimensions'],query_sha256=checked['query_sha256'],
                        evidence_links=[row['record']['record_id'],*[parent['record']['record_id'] for parent in parents]])
                except (ValueError,KeyError,TypeError) as error:item['reasons'].append(str(error))
        elif operation=='artifact.compare':
            bindings=value.get('retained_inputs',[])
            parents=[by_hash.get(binding.get('analysis_sha256')) for binding in bindings]
            valid=(len(parents)==2 and {binding.get('side') for binding in bindings}=={'reference','candidate'}
                and all(parent and parent['document']['operation']=='artifact.inventory' for parent in parents))
            changes=value.get('changes')
            if not valid or not isinstance(changes,list):item['reasons'].append('Missing or malformed static inventory comparison closure')
            else:
                known=value.get('status') in {'unchanged','added','removed','changed'}
                validated=False
                if validate_static:
                    try:
                        checked=validate_static(bindings)
                        if canonical(checked)!=canonical(value):raise ValueError('Saved static comparison differs from recomputed inventories')
                        validated=True
                    except (ValueError,OSError,KeyError) as error:item['reasons'].append(str(error))
                else:item['reasons'].append('Static inventory comparison has not been recomputed')
                item.update(status='validated-static-candidates' if known and validated else 'unknown',
                    dimensions=changes,producer_status=value.get('status'),
                    evidence_links=[row['record']['record_id'],*[parent['record']['record_id'] for parent in parents]])
        else:item['reasons'].append('Unsupported comparison document')
        reports.append(item)
    return {'format':'vitruvius.retained-changes/1','status':'unknown' if missing or any(row['status']=='unknown' for row in reports) else 'selected-comparisons-read',
        'comparisons':reports,'missing_closure':missing,
        'closure':make_bundle([row['source'] for row in sources]),
        'limitations':['Process dimensions are recomputed from retained captures; no program or original path is accessed.',
            'Static candidates are recomputed from retained inventories; they do not establish observed behavior.',
            'Missing, partial, unaligned or altered comparisons remain unresolved. No causal relation is inferred.']}


def correlate(summary,hypotheses):
    if not isinstance(hypotheses,list) or not hypotheses:raise ValueError('Declare at least one explicit correlation hypothesis')
    reports={row['record_id']:row for row in summary['comparisons']};ids=set();rows=[]
    expected_states={'both-changed':(True,True),'static-only':(True,False),'runtime-only':(False,True),'both-unchanged':(False,False)}
    for hypothesis in hypotheses:
        required={'id','static_record_id','logical_path','runtime_record_id','dimension','expected'}
        if not isinstance(hypothesis,dict) or set(hypothesis)!=required or any(not isinstance(value,str) or not value for value in hypothesis.values()):
            raise ValueError('A hypothesis needs exact static/runtime record IDs, logical path, dimension and expectation')
        key=hypothesis['id']
        if key in ids:raise ValueError('Hypothesis IDs must be unique')
        ids.add(key)
        if hypothesis['expected'] not in expected_states:raise ValueError('Unknown correlation expectation')
        static=reports.get(hypothesis['static_record_id']);runtime=reports.get(hypothesis['runtime_record_id'])
        row={'hypothesis':hypothesis,'status':'unknown','static_changed':None,'runtime_changed':None,'evidence_links':[],
            'interpretation':'The association is caller-declared; no causal relationship is established'}
        if static and runtime and static['scope']=='static-candidates' and runtime['scope']=='runtime-observations':
            findings=[item for item in static['dimensions'] if item.get('logical_path')==hypothesis['logical_path']]
            observed=[item for item in runtime['dimensions'] if item.get('dimension')==hypothesis['dimension']]
            if static['status']=='validated-static-candidates' and len(findings)==len(observed)==1 and observed[0]['state'] in {'same','different'}:
                classification=findings[0].get('classification')
                if classification in {'added','removed','changed','unchanged'}:
                    a=classification!='unchanged';b=observed[0]['state']=='different'
                    row.update(static_changed=a,runtime_changed=b,
                        status='consistent-with-declared-association' if (a,b)==expected_states[hypothesis['expected']] else 'contradicts-declared-association',
                        evidence_links=sorted(set(static.get('evidence_links',[])+runtime.get('evidence_links',[]))))
        rows.append(row)
    return {'format':'vitruvius.static-runtime-hypotheses/1','hypotheses':rows,'query_sha256':sha(hypotheses),
        'causality':'not-established','closure':summary,'limitations':summary['limitations']}


def execute(request,folder=None):
    operation=request['operation'];query=request['parameters'].get('query',{})
    if operation=='evidence.compare_bundles':
        left=Path(request['path']).read_bytes();right=Path(request['candidate_path']).read_bytes()
        if hashlib.sha256(left).hexdigest()!=request['expected_input_sha256'] or hashlib.sha256(right).hexdigest()!=request['expected_candidate_sha256']:
            raise ValueError('Retained bundle document hash changed')
        a,b=loads(left),loads(right)
        if a['operation']!='evidence.bundle' or b['operation']!='evidence.bundle':raise ValueError('Select native evidence bundles')
        if set(query)-{'record_pairs'}:raise ValueError('Unknown bundle comparison query')
        return compare_bundles(a['result'],b['result'],query.get('record_pairs'))
    sources,missing=read_inputs(request['source_inputs'])
    if operation=='evidence.bundle':
        if set(query)-{'unknowns'}:raise ValueError('Unknown bundle query')
        return make_bundle([row['source'] for row in sources if row['selected']],query.get('unknowns'))
    def validate_static(bindings):
        import subprocess
        engine=request.get('validation_engine',{})
        if not engine.get('available') or folder is None:raise ValueError('Build the native inventory core to validate static comparisons')
        chosen=[]
        for side in ('reference','candidate'):
            binding=next(value for value in bindings if value['side']==side)
            matches=[value for value in request['source_inputs'] if value.get('analysis_sha256')==binding['analysis_sha256'] and 'path' in value]
            if not matches:raise ValueError('Missing retained inventory input')
            chosen.append(matches[0])
        serial=len(list(folder.glob('static-recheck-*-request.json')))
        source=folder/f'static-recheck-{serial}-request.json';target=folder/f'static-recheck-{serial}-output.json'
        source.write_text(canonical({'operation':'artifact.compare','path':chosen[0]['path'],'expected_input_sha256':chosen[0]['analysis_sha256'],
            'source_artifact_sha256':chosen[0]['artifact_sha256'],'candidate_path':chosen[1]['path'],
            'expected_candidate_sha256':chosen[1]['analysis_sha256'],'parameters':{}}),encoding='utf8')
        result=subprocess.run([engine['node'],engine['entry'],str(source),str(target)],capture_output=True,text=True,encoding='utf8')
        if result.returncode or not target.is_file():raise ValueError('Native retained inventory validation failed: '+result.stderr[-1500:])
        return loads(target.read_bytes())['result']
    summary=aggregate(sources,missing,validate_static)
    if operation=='evidence.changed_behavior':
        if query:raise ValueError('Changed behavior aggregation needs no implicit matching query')
        return summary
    if operation=='evidence.correlate':
        if set(query)!={'hypotheses'}:raise ValueError('Declare explicit hypotheses')
        return correlate(summary,query['hypotheses'])
    raise ValueError('Unknown retained evidence operation')
