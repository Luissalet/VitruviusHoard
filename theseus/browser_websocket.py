"""Selected WebSocket message projections from retained page CDP events."""
import base64
import binascii
import hashlib
import json


def canonical(value):return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'))


def message(response,direction):
    row={'kind':'message','direction':direction,'reported_message':response,
        'payload_state':'unavailable','representation':'unknown'}
    try:
        opcode=response['opcode'];payload=response['payloadData']
        if not isinstance(payload,str):raise ValueError('The reported payload is not a string')
        if opcode==1 and not isinstance(opcode,bool):
            raw=payload.encode('utf8');row['representation']='reported-utf8-text'
        elif isinstance(opcode,(int,float)) and not isinstance(opcode,bool):
            raw=base64.b64decode(payload,validate=True);row['representation']='reported-base64-binary'
        else:raise ValueError('The reported message opcode is unavailable')
        row.update(payload_state='decoded',payload_bytes=len(raw),payload_sha256=hashlib.sha256(raw).hexdigest())
    except (KeyError,ValueError,UnicodeError,binascii.Error) as exc:row['diagnostic']=str(exc)
    return row


def inventory(result):
    rows={}
    for index,event in enumerate(result['events']):
        method=event['method']
        if method not in {'Network.webSocketCreated','Network.webSocketClosed','Network.webSocketFrameError',
            'Network.webSocketFrameSent','Network.webSocketFrameReceived'}:continue
        params=event['parameters'];key=params['requestId']
        row=rows.setdefault(key,{'request_id':key,'event_indices':[],'events':[],'created_urls':[],'closed_count':0})
        row['event_indices'].append(index)
        if method=='Network.webSocketCreated':
            row['created_urls'].append(params['url']);entry={'kind':'created','url':params['url']}
        elif method=='Network.webSocketClosed':
            row['closed_count']+=1;entry={'kind':'closed'}
        elif method=='Network.webSocketFrameError':entry={'kind':'error','message':params['errorMessage']}
        else:entry=message(params['response'],'sent' if method.endswith('Sent') else 'received')
        row['events'].append(entry)
    for row in rows.values():
        urls=row['created_urls'];row['url']=urls[0] if len(urls)==1 else None
        row['name']=row['url'] or 'WebSocket · URL no resuelta'
        unknown=['whole-connection-completeness']
        if not urls:unknown.append('start-not-observed')
        elif len(urls)!=1:unknown.append('ambiguous-created-events')
        if not row['closed_count']:unknown.append('end-not-observed')
        elif row['closed_count']!=1:unknown.append('ambiguous-closed-events')
        if result.get('status')!='observed':unknown.append('incomplete-capture')
        if result.get('journal_recovery',{}).get('gap'):unknown.append('protocol-journal-gap')
        if any(event.get('payload_state')=='unavailable' for event in row['events']):unknown.append('payload-bytes-unavailable')
        row['unknown']=unknown
        row['scope']='Ordered retained CDP messages and boundaries, not wire fragments or authenticated connection identity'
    return list(rows.values())


def compare(reference,candidate):
    sides=[inventory(result) for result in (reference,candidate)]
    grouped=[]
    for connections in sides:
        groups={}
        for row in connections:
            # Remove only capture-local coordinates. Payload-local IDs and all
            # reported message fields stay literal and ordered inside a stream.
            projection={'url':row['url'],'events':row['events']}
            groups.setdefault(canonical(projection),[]).append(row)
        grouped.append(groups)
    records=[]
    for key in sorted(grouped[0].keys()|grouped[1].keys()):
        streams=[groups.get(key,[]) for groups in grouped];projection=json.loads(key)
        records.append({'name':projection['url'] or 'WebSocket · URL no resuelta','observation':projection,
            'reference_count':len(streams[0]),'candidate_count':len(streams[1]),
            'reference_connections':streams[0],'candidate_connections':streams[1],
            'state':'same-recorded-stream-count' if len(streams[0])==len(streams[1]) else 'different-recorded-stream-count',
            'unknown':sorted({value for side in streams for row in side for value in row['unknown']})})
    return records
