"""Finite precise coverage on one selected page, driven by external actions."""
import hashlib
import json
import sys
import time
from websocket import WebSocketException


def progress(capture,state,**fields):
    receipt={**capture.result.get('progress',{}),'state':state,**fields}
    capture.result['progress']=receipt
    temporary=capture.folder/'progress.tmp'
    temporary.write_text(json.dumps(receipt,ensure_ascii=True),encoding='utf8')
    temporary.replace(capture.folder/'progress.json')
    capture.checkpoint()


def selected_frame(script,contexts):
    return (script.get('executionContextAuxData') or contexts.get(script.get('executionContextId'),{})).get('frameId')


def requests(events,scripts):
    rows=[]
    for event in events:
        if event['method']!='Network.requestWillBeSent':continue
        params=event['parameters'];initiator=params.get('initiator',{});callsites=[];parents=[]
        stack=initiator.get('stack')
        while stack:
            for frame in stack.get('callFrames',[]):
                script_id=frame.get('scriptId','')
                callsites.append({**frame,'source_association':'script_id' if script_id in scripts else 'unknown',
                    'source_sha256':scripts.get(script_id,{}).get('source',{}).get('sha256'),
                    'coordinate_units':'zero-based-resource-line-and-utf16-column'})
            if stack.get('parentId'):parents.append(stack['parentId'])
            stack=stack.get('parent')
        rows.append({'name':params['request']['url'],'request_id':params['requestId'],
            'request':params['request'],'timestamp_seconds':params.get('timestamp'),
            'initiator':initiator,'callsites':callsites,'async_parent_ids':parents,'causal_attribution':'unknown'})
    return rows


def capture_coverage(capture):
    result=capture.result;command=capture.command
    from inspector_runtime import utc
    frame=command('Page.getFrameTree')['frameTree']['frame']
    result['coverage_target']={'frame_id':frame['id'],'loader_id':frame.get('loaderId'),'initial_url':frame['url']}
    result['capture_mode']='precise-main-document-coverage-and-script-texts'
    result['instrumentation']={'resets_execution_counters':True,'disables_optimized_execution':True,
        'executes_selected_code':False,'page_ownership':'external','cleanup':'not-confirmed'}
    result['coverage']={'state':'unavailable','offset_units':'utf16-code-units','end_offset':'exclusive','scripts':[]}
    result['coverage_functions']=[]
    command('Profiler.enable')
    armed=False;completed=False
    try:
        producer=command('Profiler.startPreciseCoverage',{'callCount':True,'detailed':True})
        armed=True;start_events=len(result['events'])
        duration=capture.parameters.get('observation_ms',10000)
        window={'armed_at':utc(),'requested_ms':duration,'producer_started_seconds':producer.get('timestamp'),
            'armed_protocol_sequence':capture.journal_entries,'end_reason':'window_elapsed'}
        result['coverage_window']=window
        progress(capture,'armed',armed_at=window['armed_at'],requested_ms=duration,
            armed_protocol_sequence=capture.journal_entries,frame_id=frame['id'])
        deadline=time.monotonic()+duration/1000
        checked_events=start_events
        while time.monotonic()<deadline:
            capture.receive()
            changed=[event for event in result['events'][checked_events:] if event['method']=='Page.frameNavigated'
                and event['parameters']['frame'].get('id')==frame['id']
                and event['parameters']['frame'].get('loaderId')!=frame.get('loaderId')]
            checked_events=len(result['events'])
            if changed:
                window['end_reason']='document_changed';break
        window['ended_at']=utc();end_events=len(result['events'])
        progress(capture,'sampling',ended_at=window['ended_at'],end_reason=window['end_reason'])
        sample=command('Profiler.takePreciseCoverage')
        window['producer_sampled_seconds']=sample.get('timestamp')
        command('Profiler.stopPreciseCoverage');armed=False
        result['instrumentation']['cleanup']='confirmed'
        capture.window_closed=True
        contexts={row['id']:row.get('auxData',{}) for row in result['contexts']}
        inventory={row['scriptId']:row for row in result['scripts']}
        retained={};excluded=[]
        for index,row in enumerate(sample['result']):
            script=inventory.get(row['scriptId'],{})
            if selected_frame(script,contexts)!=frame['id']:
                excluded.append({'script_id':row['scriptId'],'reported_url':row['url'],'reason':'Not bound to the selected main document frame'})
                continue
            source={'state':'unavailable','reason':'Script text was not returned'}
            try:
                text=command('Debugger.getScriptSource',{'scriptId':row['scriptId']})['scriptSource']
                raw=text.encode('utf8');digest=hashlib.sha256(raw).hexdigest()
                source={'state':'captured','text':text,'sha256':digest,'utf8_bytes':len(raw),'utf16_units':len(text.encode('utf-16-le'))//2}
                path=capture.folder/('coverage-script-'+str(index).zfill(6)+'.js');path.write_bytes(raw)
                result['artifacts'].append({'path':str(path),'name':path.name,'sha256':digest,
                    'source_location':'target '+result['target']['id']+' · CDP script_id '+row['scriptId']+' · reported URL '+row['url']})
            except (ValueError,KeyError,UnicodeError) as exc:source={'state':'unavailable','reason':str(exc)}
            script['source']=source
            functions=[]
            for function in row['functions']:
                ranges=[{**item,'source_bounds':'verified' if source['state']=='captured'
                    and 0<=item['startOffset']<=item['endOffset']<=source['utf16_units'] else 'unknown'} for item in function['ranges']]
                functions.append({**function,'ranges':ranges})
                result['coverage_functions'].append({'name':function['functionName'] or '<anonymous>',
                    'script_id':row['scriptId'],'reported_url':row['url'],'source_state':source['state'],
                    'source_sha256':source.get('sha256'),'offset_units':'utf16-code-units','end_offset':'exclusive',
                    'branch_scope':'producer-block-ranges' if function['isBlockCoverage'] else 'unknown-function-level',
                    **function,'ranges':ranges})
            item={'name':row['url'],'script_id':row['scriptId'],'reported_url':row['url'],
                'reported_script':script,'source':source,'functions':functions}
            result['coverage']['scripts'].append(item);retained[row['scriptId']]=item;capture.checkpoint(force=False)
        result['coverage'].update(state='captured',excluded_scripts=excluded,coverage_absence='unknown',
            document_scope='selected-document' if window['end_reason']=='window_elapsed' else 'transition-unknown',
            scope='Selected main document frame; nested producer ranges and counts are not summed')
        result['coverage_requests']=requests(result['events'][start_events:end_events],retained)
        result['limitations'] += ['Precise coverage resets execution counters and disables optimized execution until stopped.',
            'Coverage ranges are nested UTF-16 code-unit intervals with exclusive ends; they are not byte or code-point offsets.',
            'Script IDs bind sources and initiators only inside this selected CDP session. URLs and callsites do not authenticate UI causality.',
            'Workers, child frames, external processes and unreported scripts are outside the selected main-document coverage claim.',
            'A missing range or script is unknown coverage. Counts are producer observations, not source identity or behavioral equivalence.']
        if window['end_reason']!='window_elapsed':raise ValueError('The selected document changed; its finite coverage is incomplete')
        progress(capture,'ended',cleanup='confirmed');completed=True
    finally:
        failure=sys.exc_info()[1]
        if armed:
            try:
                command('Profiler.stopPreciseCoverage');result['instrumentation']['cleanup']='confirmed'
            except (ValueError,OSError,WebSocketException) as exc:result['instrumentation']['cleanup_error']=str(exc)
        if not completed and 'progress' in result:
            progress(capture,'incomplete',cleanup=result['instrumentation']['cleanup'],diagnostic=str(failure))
        capture.checkpoint()
