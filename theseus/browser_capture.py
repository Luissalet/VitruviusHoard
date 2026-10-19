"""Optional page snapshots over an explicitly selected existing CDP connection."""
import base64
from datetime import datetime, timezone
import hashlib


def network_inventory(events,body_state='excluded'):
    inventory={}
    for index,event in enumerate(events):
        if not event['method'].startswith('Network.'):continue
        params=event['parameters'];request_id=params.get('requestId')
        if request_id is None:continue
        row=inventory.setdefault(request_id,{'request_id':request_id,'event_indices':[],'body':{'state':body_state}})
        row['event_indices'].append(index)
        if event['method']=='Network.requestWillBeSent':
            row['request']=params['request'];row['name']=params['request']['url']
        if event['method']=='Network.responseReceived':
            row['response']=params['response'];row.setdefault('name',params['response']['url'])
        if event['method']=='Network.loadingFinished':row['loading']='finished'
        if event['method']=='Network.loadingFailed':row['loading']='failed';row['failure']=params
    return list(inventory.values())


def capture_page(capture):
    result=capture.result;parameters=capture.parameters
    result['page_selection']={key:parameters.get(key,False) for key in
        ('capture_dom','capture_sources','capture_response_bodies','capture_screenshot')}
    result['page_selection']['listener_selector']=parameters.get('listener_selector')
    result['listener_selection']={'state':'excluded'}
    result['limitations'] += [
        'Network events cover only the observed window; producer timestamps and collector UTC are separate clocks.',
        'Request IDs and DOM node/remote object IDs are local to this capture, not cross-capture identities.',
        'Response text is a UTF-8 representation returned by CDP, not proof of original wire encoding or bytes.',
        'DOM and listener presence do not prove a callback invocation. Source-map URLs are not fetched.',
        'Bodies are read only for the completed request inventory selected at capture time; evicted/unavailable bodies remain unknown.']

    def artifact(body,name,location):
        path=capture.folder/name;path.write_bytes(body)
        row={'path':str(path),'name':name,'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body),'source_location':location}
        result['artifacts'].append(row)
        return {'artifact_name':name,'sha256':row['sha256'],'bytes':len(body)}

    if parameters.get('capture_dom') or parameters.get('listener_selector'):
        capture.command('DOM.enable')
        root=capture.command('DOM.getDocument',{'depth':-1 if parameters.get('capture_dom') else 0,'pierce':True})['root']
        result['dom']={'state':'captured','recorded_at':datetime.now(timezone.utc).isoformat(),'root':root} if parameters.get('capture_dom') else {'state':'excluded'}
        result['listeners']=[]
        if parameters.get('listener_selector'):
            selector=parameters['listener_selector']
            nodes=capture.command('DOM.querySelectorAll',{'nodeId':root['nodeId'],'selector':selector})['nodeIds']
            result['listener_selection']={'selector':selector,'matched_nodes':len(nodes),'state':'observed'}
            for node_id in nodes:
                row={'name':selector,'selector':selector,'node_id':node_id}
                object_id=None
                try:
                    resolved=capture.command('DOM.resolveNode',{'nodeId':node_id})['object']
                    object_id=resolved['objectId']
                    row.update(state='captured',listeners=capture.command('DOMDebugger.getEventListeners',{'objectId':object_id,'depth':-1,'pierce':True})['listeners'])
                except (ValueError,KeyError) as exc:
                    row.update(state='unavailable',diagnostic=str(exc))
                finally:
                    if object_id:
                        try:capture.command('Runtime.releaseObject',{'objectId':object_id})
                        except ValueError as exc:row['release_diagnostic']=str(exc)
                result['listeners'].append(row);capture.checkpoint(force=False)
    else:
        result['dom']={'state':'excluded'};result['listeners']=[]
        result['listener_selection']={'state':'excluded'}

    result['network']=network_inventory(result['events'])
    if parameters.get('capture_response_bodies'):
        for index,row in enumerate(result['network']):
            if row.get('loading')!='finished':
                row['body']={'state':'unavailable','reason':'Request did not finish in the selected observation inventory'}
                continue
            try:
                reply=capture.command('Network.getResponseBody',{'requestId':row['request_id']})
                binary=reply['base64Encoded'];data=base64.b64decode(reply['body'],validate=True) if binary else reply['body'].encode('utf8')
                recorded=artifact(data,'response-body-'+str(index).zfill(6)+'.bin','CDP request_id '+str(row['request_id']))
                row['body']={'state':'captured','representation':'cdp-base64-bytes' if binary else 'cdp-text-utf8',**recorded}
            except (ValueError,KeyError,UnicodeError) as exc:
                row['body']={'state':'unavailable','diagnostic':str(exc)}
            capture.checkpoint(force=False)
    if parameters.get('capture_screenshot'):
        try:
            reply=capture.command('Page.captureScreenshot',{'format':'png','fromSurface':True})
            body=base64.b64decode(reply['data'],validate=True)
            if not body.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('CDP did not return a PNG signature')
            result['screenshot']={'state':'captured','format':'png','recorded_at':datetime.now(timezone.utc).isoformat(),
                **artifact(body,'observed-page.png','CDP Page.captureScreenshot; viewport at capture time')}
        except (ValueError,KeyError) as exc:
            result['screenshot']={'state':'unavailable','diagnostic':str(exc)}
    else:result['screenshot']={'state':'excluded'}
    capture.checkpoint()
