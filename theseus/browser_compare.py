"""Explicit projections of two hash-bound historical page observations."""
from collections import Counter
import hashlib
import json

from javascript_runtime import saved_pair
from browser_capture import network_inventory
from browser_websocket import compare as compare_websockets


def canonical(value):return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'))
def sha(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def bag(rows):
    return Counter(canonical(row) for row in rows)


def differences(left,right):
    a,b=bag(left),bag(right)
    rows=[]
    for key in sorted(a.keys()|b.keys()):
        value=json.loads(key);unknown=[]
        if 'source_state' in value and value['source_state']!='captured':unknown.append('source_text')
        if 'body_state' in value and value['body_state']!='captured':unknown.append('response_body')
        name=' · '.join(str(value[key]) for key in ('url','script_url','selector','type') if value.get(key)) or 'Sin URL resuelta'
        rows.append({'name':name,'observation':value,'reference_count':a[key],'candidate_count':b[key],'unknown':unknown,
            'state':('same-recorded-metadata-content-unknown' if unknown else 'same-recorded-tuple') if a[key]==b[key] else 'different-recorded-count'})
    return rows


def scripts(result):
    return [{'url':row.get('url'),'source_state':row.get('source',{}).get('state','not-recorded'),
        'source_sha256':row.get('source',{}).get('sha256'),'source_map_url':row.get('sourceMapURL')} for row in result['scripts']]


def network(result):
    socket_ids={event['parameters']['requestId'] for event in result['events']
        if event['method'].startswith('Network.webSocket') and 'requestId' in event['parameters']}
    rows=[row for row in result.get('network',network_inventory(result['events'],'not-recorded'))
        if row.get('request_id') not in socket_ids or 'request' in row or 'response' in row]
    return [{'url':row.get('request',{}).get('url',row.get('response',{}).get('url')),'method':row.get('request',{}).get('method'),
        'request_headers':row.get('request',{}).get('headers'),
        'post_data':row.get('request',{}).get('postData'),
        'post_data_state':'observed' if 'postData' in row.get('request',{}) else 'unknown' if row.get('request',{}).get('hasPostData') else 'absent-or-unreported',
        'response_headers':row.get('response',{}).get('headers'),
        'status':row.get('response',{}).get('status'),'loading':row.get('loading','unknown'),
        'body_state':row['body']['state'],'body_sha256':row['body'].get('sha256'),
        'body_representation':row['body'].get('representation')} for row in rows]


def dom_tree(node):
    if isinstance(node,list):return [dom_tree(child) for child in node]
    if isinstance(node,dict):return {key:dom_tree(value) for key,value in node.items() if key not in {'nodeId','parentId','backendNodeId','frameId'}}
    return node


def listener_rows(result):
    scripts_by_id={}
    for script in result['scripts']:scripts_by_id.setdefault(script['scriptId'],[]).append(script)
    rows=[]
    for selection in result.get('listeners',[]):
        if selection.get('state')!='captured':
            rows.append({'selector':selection['selector'],'state':selection.get('state','unknown')});continue
        for listener in selection['listeners']:
            matching=scripts_by_id.get(listener.get('scriptId'),[]);script=matching[0] if len(matching)==1 else {}
            rows.append({**{key:listener.get(key) for key in ('type','useCapture','passive','once','lineNumber','columnNumber')},
                'selector':selection['selector'],'state':'metadata','script_url':script.get('url'),
                'source_sha256':script.get('source',{}).get('sha256'),
                'source_state':script.get('source',{}).get('state','unknown')})
    return rows


def optional_pair(left,right,kind):
    if left.get('state')!='captured' or right.get('state')!='captured':
        return {'state':'unknown','reference_state':left.get('state','unknown'),'candidate_state':right.get('state','unknown')}
    a=sha(dom_tree(left['root'])) if kind=='dom' else left['sha256']
    b=sha(dom_tree(right['root'])) if kind=='dom' else right['sha256']
    return {'state':'same-recorded-projection' if a==b else 'different-recorded-projection','reference_sha256':a,'candidate_sha256':b}


def scenario_steps(reference,candidate):
    if reference['operation']!='browser.scenario' or candidate['operation']!='browser.scenario':return []
    a,b=reference['result'],candidate['result'];plans=[row['parameters']['steps'] for row in (a,b)]
    receipts=[{row['index']:row for row in result.get('steps',[])} for result in (a,b)]
    rows=[]
    for index in range(max(map(len,plans))):
        requests=[plan[index] if index<len(plan) else None for plan in plans]
        steps=[side.get(index) for side in receipts]
        row={'name':str(index)+' · '+str((requests[0] or requests[1])['method']),'index':index,
            'reference_request':requests[0],'candidate_request':requests[1],
            'reference_receipt':steps[0],'candidate_receipt':steps[1]}
        if requests[0]!=requests[1]:row['state']='unknown-unaligned-literal-request'
        elif any(step is None or step['state']!='completed' for step in steps):row['state']='unknown-incomplete-step'
        else:
            # Exclude only the CDP envelope ID; preserve all response payload values.
            responses=[{key:value for key,value in step['response'].items() if key!='id'} for step in steps]
            row.update(reference_response_sha256=sha(responses[0]),candidate_response_sha256=sha(responses[1]))
            row['state']='same-recorded-response' if responses[0]==responses[1] else 'different-recorded-response'
        rows.append(row)
    return rows


def compare(request,source_bytes):
    kinds=('browser.observe','browser.scenario')
    reference,candidate,candidate_bytes=saved_pair(request,source_bytes,kinds,kinds)
    a,b=reference['result'],candidate['result']
    selections=[row.get('listener_selection',{'state':'not-recorded'}) for row in (a,b)]
    known=all(row['state']=='observed' for row in selections)
    return {'reference_analysis_sha256':hashlib.sha256(source_bytes).hexdigest(),
        'candidate_analysis_sha256':hashlib.sha256(candidate_bytes).hexdigest(),
        'capture_states':{'reference':a['status'],'candidate':b['status']},
        'capture_operations':{'reference':reference['operation'],'candidate':candidate['operation']},
        'scenario_step_alignment':{'state':'literal-positional-requests' if reference['operation']==candidate['operation']=='browser.scenario' else 'unknown-no-two-scenario-definitions'},
        'scenario_steps':scenario_steps(reference,candidate),
        'scripts':differences(scripts(a),scripts(b)),'network':differences(network(a),network(b)),
        'websocket_streams':compare_websockets(a,b),
        'websocket_scope':{'projection':'retained-event-message-streams','collection':'unordered-streams-with-multiplicity',
            'ordering':'exact-inside-each-stream','reference_capture_status':a['status'],'candidate_capture_status':b['status'],
            'absence':'No retained events establish neither absent traffic nor complete connection history'},
        'listeners':{'state':'selected-observations' if known else 'unknown',
            'reference_selection':selections[0],'candidate_selection':selections[1],
            'records':differences(listener_rows(a),listener_rows(b)) if known else []},
        'dom':optional_pair(a.get('dom',{}),b.get('dom',{}),'dom'),
        'screenshot':optional_pair(a.get('screenshot',{}),b.get('screenshot',{}),'screenshot'),
        'limitations':['Only the two retained JSON captures were read. No live page or original path was inspected.',
            'Scenario steps align by position and exact JSON request values; missing observe_ms and explicit zero remain distinct.',
            'Completed step responses exclude only the CDP envelope id. Payload-local identities are not normalized and equal responses do not establish behavioral equivalence.',
            'Unexecuted, incomplete or differently defined steps remain unknown, including a recovered response whose observation interval did not complete.',
            'Equal tuples describe selected observations, not behavioral equivalence or coverage of a whole process.',
            'URL groups and repeated observation counts are not authenticated request or script identities.',
            'WebSocket comparison preserves ordered reported messages inside each connection and unordered stream multiplicities per reported URL. IDs and clocks are capture-local; payload values stay literal.',
            'CDP WebSocketFrame reports complete messages, not authenticated wire fragments. Missing boundaries and journal gaps remain unknown even when retained streams match.',
            'Listener tuples describe metadata for the caller-selected selectors, not callback invocations or authenticated element identity.',
            'Capture-local script/request IDs, clocks and ordering are excluded from tuple comparison; original events remain in each source.',
            'Missing script texts and response bodies remain unknown even if their metadata tuples match.',
            'Incomplete captures compare only their recorded prefixes; absence does not establish that an event did not occur.',
            'DOM projection removes only nodeId, parentId, backendNodeId and frameId keys; attributes, text, child order and other values remain exact.',
            'A screenshot comparison concerns recorded PNG hashes, not semantic or visual equivalence.']}
