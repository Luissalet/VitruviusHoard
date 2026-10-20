"""Explicit, hash-bound projections of retained process observations."""
import base64
import hashlib
import json

from jsonschema import validate, ValidationError

DIMENSIONS=['stdout','stderr','exit','terminal','files','http','websocket','commands','trace']
QUERY={'type':'object','additionalProperties':False,'required':['dimensions'],'properties':{
    'dimensions':{'type':'array','minItems':1,'uniqueItems':True,'items':{'enum':DIMENSIONS}},
    'terminal_view':{'enum':['rendered','raw']},
    'http_headers':{'type':'array','uniqueItems':True,'items':{'type':'string','minLength':1}},
    'websocket_headers':{'type':'array','uniqueItems':True,'items':{'type':'string','minLength':1}},
    'command_working_directory':{'type':'boolean'},
    'normalizations':{'type':'array','items':{'type':'object','additionalProperties':False,
        'required':['dimension','side','from','to'],'properties':{'dimension':{'enum':['stdout','stderr','terminal']},
        'side':{'enum':['reference','candidate']},'from':{'type':'string','minLength':1},'to':{'type':'string'}}}},
    'trace':{'type':'object','additionalProperties':False,'required':['nodes','before'],'properties':{
        'nodes':{'type':'array','minItems':1,'items':{'type':'object','additionalProperties':False,'required':['id','match'],
            'properties':{'id':{'type':'string','minLength':1},'match':{'type':'object','minProperties':1},'occurrence':{'type':'integer','minimum':0}}}},
        'before':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['before','after'],
            'properties':{'before':{'type':'string'},'after':{'type':'string'}}}}}}}}


def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def sha(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def bytes_value(value):
    try:data=base64.b64decode(value['base64'],validate=True)
    except (KeyError,TypeError,ValueError) as error:raise ValueError('Captured byte identity is invalid') from error
    if type(value.get('bytes')) is not int or value.get('bytes')!=len(data) or value.get('sha256')!=hashlib.sha256(data).hexdigest():
        raise ValueError('Captured byte hash or length differs from its identity')
    return data


def file_value(value):
    state=value.get('state')
    if state=='file':
        bytes_value(value)
        return {'state':state,'sha256':value['sha256'],'bytes':value['bytes'],'mode':value.get('mode')},False
    if state=='directory':
        members=value.get('members',[]);names=[row['name'] for row in members]
        if len(set(names))!=len(names):return {'state':'ambiguous-member-names'},True
        rows=[];unknown=False
        for row in sorted(members,key=lambda row:row['name']):
            child,missing=file_value(row);rows.append({'name':row['name'],**child});unknown|=missing
        return {'state':state,'members':rows},unknown
    return {'state':state},state not in {'absent','directory'}


def files(value):
    rows=value.get('files');unknown=not isinstance(rows,list)
    if unknown:return [],True
    labels=[row.get('label') for row in rows]
    if len(set(labels))!=len(labels) or any(not label for label in labels):return rows,True
    projected=[]
    for row in sorted(rows,key=lambda row:row['label']):
        before,a=file_value(row.get('before',{}));after,b=file_value(row.get('after',{}));unknown|=a or b
        projected.append({'label':row['label'],'before':before,'after':after})
    return projected,unknown


def subset(actual,expected):
    return isinstance(actual,dict) and all(key in actual and (subset(actual[key],value) if isinstance(value,dict) else actual[key]==value)
        for key,value in expected.items())


def communication(value,dimension,query):
    configuration=value.get('contract',{})
    configured=bool(configuration.get('commands')) if dimension=='commands' else any(row.get(dimension) for row in configuration.get('services',[]))
    status=value.get('services',{});unknown=not configured or not status.get('closed') or bool(status.get('errors'))
    groups={}
    for event in value.get('events',[]):
        if event['kind'].startswith(('service.','http.','websocket.','command.')):groups.setdefault(event['channel'],[]).append(event)
    rows=[]
    def identity(blob):
        bytes_value(blob);return {'sha256':blob['sha256'],'bytes':blob['bytes']}
    def headers(pairs):
        selected={name.lower().encode('ascii') for name in query.get(dimension+'_headers',[])}
        return [{'name':bytes_value(name).decode('ascii'),'value':identity(content)} for name,content in pairs if bytes_value(name).lower() in selected]
    for events in groups.values():
        connection=next((row for row in events if row['kind']=='service.connection'),None)
        invocation=next((row for row in events if row['kind']=='command.invoked'),None)
        if dimension=='commands':
            if not invocation:continue
            reply=next((row for row in events if row['kind']=='command.response-sent'),None)
            unknown|=reply is None
            rows.append({'command':invocation['command'],'argv':invocation['argv'],
                **({'cwd':invocation['cwd']} if query.get('command_working_directory',True) else {}),
                'stdin':identity(invocation['stdin']),'response':None if reply is None else {
                    'stdout':identity(reply['stdout']),'stderr':identity(reply['stderr']),'exit_code':reply['exit_code']}})
        elif dimension=='http':
            if invocation or not connection or connection['protocol']!='http':continue
            request=next((row for row in events if row['kind']=='http.request'),None)
            response=next((row for row in events if row['kind']=='http.response'),None)
            unknown|=request is None or response is None
            rows.append({'service':connection['service'],'path':connection['path'],'query':identity(connection['query']),
                'request_headers':headers(connection['headers']),'request':None if request is None else {
                    'method':request['method'],'body':identity(request['body'])},
                'response':None if response is None else {'status':response['status'],'headers':headers(response['headers']),'body':identity(response['body'])}})
        else:
            if not connection or connection['protocol']!='websocket':continue
            messages=[]
            for row in events:
                if not row['kind'].startswith('websocket.'):continue
                messages.append({'kind':row['kind'],**{key:row[key] for key in ('representation','code','subprotocol') if key in row},
                    **({'body':identity(row['body'])} if 'body' in row else {})})
            unknown|=not any(row['kind'] in {'websocket.closed','websocket.rejected','websocket.disconnected'} for row in messages)
            rows.append({'service':connection['service'],'path':connection['path'],'query':identity(connection['query']),
                'headers':headers(connection['headers']),'messages':messages})
    # Each request/socket/invocation is an occurrence. Independent channels have
    # no invented global order; duplicates remain repeated in this sorted bag.
    return sorted(rows,key=canonical),unknown


def trace(value,spec):
    events=value.get('events',[]);ids=[row.get('id') for row in events];nodes={};rows=[];unknown=False
    if len(set(ids))!=len(ids) or any(not key for key in ids):return {'state':'unknown','reason':'ambiguous-event-identities'}
    names=[row['id'] for row in spec['nodes']]
    if len(set(names))!=len(names):raise ValueError('Trace node labels must be unique')
    for definition in spec['nodes']:
        matches=[row['id'] for row in events if subset(row,definition['match'])]
        index=definition.get('occurrence')
        selected=matches[index] if index is not None and index<len(matches) else matches[0] if index is None and len(matches)==1 else None
        nodes[definition['id']]=selected
        rows.append({'id':definition['id'],'matches':matches,'selected':selected})
        unknown|=selected is None
    adjacency={key:set() for key in ids};invalid=[]
    for edge in value.get('order',{}).get('edges',[]):
        before,after=edge.get('before'),edge.get('after')
        if before not in adjacency or after not in adjacency or before==after or not edge.get('basis'):
            invalid.append(edge);continue
        adjacency[before].add(after)
    def reachable(before,after):
        seen=set();pending=list(adjacency[before])
        while pending:
            key=pending.pop()
            if key==after:return True
            if key not in seen:seen.add(key);pending.extend(adjacency[key])
        return False
    incoming={key:0 for key in adjacency}
    for successors in adjacency.values():
        for key in successors:incoming[key]+=1
    ready=[key for key,count in incoming.items() if count==0];visited=0
    while ready:
        key=ready.pop();visited+=1
        for successor in adjacency[key]:
            incoming[successor]-=1
            if not incoming[successor]:ready.append(successor)
    cycle=visited!=len(adjacency)
    unknown|=bool(invalid) or cycle
    obligations=[];contradiction=False
    for relation in spec['before']:
        if relation['before'] not in nodes or relation['after'] not in nodes:raise ValueError('Trace order refers to an undeclared node')
        before,after=nodes[relation['before']],nodes[relation['after']]
        state='unknown'
        if before and after and not invalid and not cycle:
            if reachable(before,after):state='observed'
            elif reachable(after,before):state='contradicted';contradiction=True
        unknown|=state=='unknown';obligations.append({**relation,'state':state})
    return {'state':'contradicted' if contradiction else 'unknown' if unknown else 'observed',
        'nodes':rows,'order':obligations,'invalid_edges':invalid,'cyclic_order':cycle}


def contract(value):
    captured=value.get('contract',{})
    expected=hashlib.sha256(json.dumps(captured,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if value.get('contract_sha256')!=expected:raise ValueError('Captured input contract hash differs from its identity')
    try:
        try:from .process_capture import PARAMETERS
        except ImportError:from process_capture import PARAMETERS
        validate(captured,PARAMETERS)
    except ValidationError as error:raise ValueError('Captured input contract is malformed: '+error.message) from error
    return {'mode':captured.get('mode','pipes'),'steps':captured.get('steps',[]),
        'terminal':{'columns':80,'rows':24,'scrollback':1000,**captured.get('terminal',{})} if captured.get('mode')=='pty' else None,
        'environment':captured.get('environment',{}),'services':captured.get('services',[]),'commands':captured.get('commands',[])}


def complete_receipt(value):
    if value.get('status')!='complete' or value.get('stream_complete') is not True or value.get('process',{}).get('input_file_changes'):return False
    if type(value.get('process',{}).get('exit_code')) is not int:return False
    plan=value['contract'].get('steps',[]);steps=value.get('steps')
    if not isinstance(steps,list) or len(steps)!=len(plan):return False
    for index,(request,receipt) in enumerate(zip(plan,steps)):
        if type(receipt.get('index')) is not int or receipt['index']!=index or receipt.get('state')!='dispatched' or canonical(receipt.get('definition'))!=canonical(request):return False
        if request['kind']=='input':
            data=base64.b64decode(request['data_base64'],validate=True) if 'data_base64' in request else request['text'].encode('utf8')
            if type(receipt.get('accepted_bytes')) is not int or receipt['accepted_bytes']!=len(data):return False
    return True


def equal(left,right):
    return left==right if isinstance(left,bytes) or isinstance(right,bytes) else canonical(left)==canonical(right)


def compare_results(reference,candidate,query):
    try:validate(query,QUERY)
    except ValidationError as error:raise ValueError('Invalid process comparison query: '+error.message) from error
    for value in (reference,candidate):
        if value.get('format')!='vitruvius.process-capture/1':raise ValueError('Select native process capture documents')
    compatible=canonical(contract(reference))==canonical(contract(candidate))
    complete=all(complete_receipt(value) for value in (reference,candidate))
    reports=[];normalizations=[]
    def normalize(value,dimension,side):
        for ordinal,rule in enumerate(query.get('normalizations',[])):
            if rule['dimension']!=dimension or rule['side']!=side:continue
            before,after=rule['from'].encode('utf8'),rule['to'].encode('utf8')
            count=value.count(before);original=hashlib.sha256(value).hexdigest();value=value.replace(before,after)
            normalizations.append({'rule':ordinal,**rule,'occurrences':count,'before_sha256':original,'after_sha256':hashlib.sha256(value).hexdigest()})
        return value
    for dimension in query['dimensions']:
        unknown=False;detail={}
        if dimension in {'stdout','stderr'}:
            values=[normalize(bytes_value(value.get(dimension,{})),dimension,side) for value,side in ((reference,'reference'),(candidate,'candidate'))]
            a,b=values;detail={'reference_sha256':hashlib.sha256(a).hexdigest(),'candidate_sha256':hashlib.sha256(b).hexdigest(),'reference_bytes':len(a),'candidate_bytes':len(b)}
        elif dimension=='exit':
            a,b=[value.get('process',{}).get('exit_code') for value in (reference,candidate)];unknown=a is None or b is None
            detail={'reference':a,'candidate':b}
        elif dimension=='files':
            (a,x),(b,y)=[files(value) for value in (reference,candidate)];unknown=x or y;detail={'reference':a,'candidate':b}
        elif dimension in {'http','websocket','commands'}:
            (a,x),(b,y)=[communication(value,dimension,query) for value in (reference,candidate)];unknown=x or y
            detail={'reference':a,'candidate':b,'independent_channels_order':'multiset; per-WebSocket message order retained'}
        elif dimension=='terminal':
            a,b=None,None
            terminals=[value.get('terminal',{}) for value in (reference,candidate)]
            unknown=any(value.get('representation')!='Windows-ConPTY-UTF-8-VT-bytes' for value in terminals)
            if query.get('terminal_view','rendered')=='raw':
                a,b=[normalize(bytes_value(value.get('raw_bytes',{})),dimension,side) for value,side in zip(terminals,['reference','candidate'])]
                detail={'view':'raw','reference_sha256':hashlib.sha256(a).hexdigest(),'candidate_sha256':hashlib.sha256(b).hexdigest()}
            else:
                if any(rule['dimension']=='terminal' for rule in query.get('normalizations',[])):raise ValueError('Terminal literal normalization requires terminal_view:raw')
                rendered=[value.get('rendered',{}) for value in terminals]
                a,b=[value.get('final') for value in rendered];unknown|=a is None or b is None or rendered[0].get('engine')!=rendered[1].get('engine')
                detail={'view':'rendered','reference':a,'candidate':b,'engines':[value.get('engine') for value in rendered]}
        else:
            if 'trace' not in query:raise ValueError('Trace comparison requires explicit nodes and order obligations')
            a,b=[trace(value,query['trace']) for value in (reference,candidate)]
            unknown=a['state']=='unknown' or b['state']=='unknown'
            detail={'reference':a,'candidate':b}
            # Match explicit obligations, not local IDs, timestamps or unselected events.
            a,b=a['state'],b['state']
        same=equal(a,b)
        state='unknown' if unknown or not complete or not compatible else 'same' if same else 'different'
        if dimension=='trace' and not unknown and complete and compatible and a==b=='contradicted':state='different'
        reports.append({'dimension':dimension,'state':state,'observed_values_equal':same,**detail})
    state='different-selected-observations' if any(row['state']=='different' for row in reports) else 'unknown' if any(row['state']=='unknown' for row in reports) else 'same-selected-observations'
    return {'format':'vitruvius.process-comparison/1','state':state,'input_contract_compatible':compatible,'observations_complete':complete,
        'query':query,'query_sha256':sha(query),'dimensions':reports,'normalizations':normalizations,
        'limitations':['Only selected, retained observations were compared; no program or original path was read.',
            'Matching one run does not prove behavioral equivalence for other inputs or environments.',
            'Executable arguments and working directories may differ; declared input steps, environment and selected terminal settings must match.',
            'Trace obligations cover only selected events and observed ordering edges. Timestamps and collector order are not causality.',
            'HTTP and WebSocket projections cover declared services only. Only caller-selected header names are compared; duplicate values are retained.',
            'Command observations describe declared PATH shims and configured responses, not the original external commands.',
            'Literal normalization is caller-declared; original byte identities and replacement counts remain visible.']}


def compare(request,source_bytes):
    try:from .javascript_runtime import saved_pair
    except ImportError:from javascript_runtime import saved_pair
    reference,candidate,candidate_bytes=saved_pair(request,source_bytes,'process.capture','process.capture')
    result=compare_results(reference['result'],candidate['result'],request['parameters']['query'])
    result.update(reference_analysis_sha256=hashlib.sha256(source_bytes).hexdigest(),candidate_analysis_sha256=hashlib.sha256(candidate_bytes).hexdigest())
    return result
