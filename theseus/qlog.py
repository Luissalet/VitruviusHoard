"""Offline qlog recordings; recorded ranges never imply transport completeness."""
import json
from pathlib import Path
import re


OPERATIONS = [{"name":"network.qlog","title":"QUIC · Grabación qlog","worker":"python",
    "description":"Lee qlog0.3 JSON/JSON-SEQ: eventos completos, trazas, pérdidas declaradas y rangos STREAM observados. Conserva números exactos, selección y errores parciales; no reconstruye cuerpos ni prueba integridad de red.",
    "inputSchema":{"type":"object","additionalProperties":False,"properties":{
        "trace_index":{"type":"integer","minimum":0},"event_name":{"type":"string"},
        "offset":{"type":"integer","minimum":0},"limit":{"type":["integer","null"],"minimum":0},
        "profile":{"enum":["generic","aioquic-json-0.3"]}}}}]


class Number(str):
    """A JSON numeric token, preserving its spelling and type without rounding."""


def preserve(value):
    if isinstance(value,Number): return {"type":"json-number","lexeme":str(value)}
    if isinstance(value,dict): return {key:preserve(item) for key,item in value.items()}
    if isinstance(value,list): return [preserve(item) for item in value]
    return value


def unsigned(value):
    if type(value) in {str,Number} and len(value)<=19 and re.fullmatch(r'0|[1-9][0-9]*',value):
        number=int(value)
        if number<2**62: return number
    return None


def decode(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('Duplicate JSON key: '+key)
            result[key]=value
        return result
    def constant(value): raise ValueError('Non-JSON numeric constant: '+value)
    return json.loads(raw.decode('utf8'),parse_int=Number,parse_float=Number,
        parse_constant=constant,object_pairs_hook=pairs)


def inspect_qlog(path,parameters):
    raw=Path(path).read_bytes()
    result={'status':'observed','format':None,'header':None,'traces':[],'events':[],
        'streams':[],'loss_declarations':[],'diagnostics':[],
        'limitations':['Recorded events do not establish a complete network trace, successful delivery or application equivalence.',
            'STREAM ranges record frame metadata, not captured payload bytes or reconstructed HTTP bodies.',
            'The recording does not authenticate its producer, vantage point or clock.'],
        'target_execution':'not-performed'}
    traces=[]
    def diagnostic(location,message):
        result['diagnostics'].append({'location':location,'message':message})
    def add_trace(trace_index,metadata,events,location):
        if not isinstance(metadata,dict):
            diagnostic(location,'Trace is not an object');return
        if not isinstance(events,list):
            diagnostic(location,'Trace events is not an array');return
        traces.append((trace_index,metadata,events,location))
    if raw.lstrip().startswith(b'\x1e'):
        result['format']='JSON-SEQ'
        records=[];position=0
        for ordinal,part in enumerate(raw.split(b'\x1e')):
            start=position;position+=len(part)+1
            if ordinal==0:
                if part.strip(): diagnostic({'byte_offset':0},'Bytes before first record separator')
                continue
            location={'record_ordinal':ordinal-1,'byte_offset':start,'byte_length':len(part)}
            try: records.append((decode(part),location))
            except (ValueError,UnicodeError) as exc:
                diagnostic(location,str(exc))
                # A malformed first header must never promote an event to header.
                if ordinal==1: records.append((None,location))
        header=records[0][0] if records else None
        if not isinstance(header,dict): diagnostic({'record_ordinal':0},'Missing valid qlog sequence header')
        else:
            result['header']=preserve(header)
            if header.get('qlog_format')!='JSON-SEQ': diagnostic({'record_ordinal':0},'Header must declare JSON-SEQ')
            add_trace(0,header.get('trace'),[(event,location) for event,location in records[1:]],{'record_ordinal':0,'pointer':'/trace'})
    else:
        result['format']='JSON'
        try: header=decode(raw)
        except (ValueError,UnicodeError) as exc:
            diagnostic({'byte_offset':0},str(exc));header=None
        if not isinstance(header,dict): diagnostic({'pointer':''},'Missing valid qlog object')
        else:
            result['header']=preserve({key:value for key,value in header.items() if key!='traces'})
            if header.get('qlog_format','JSON')!='JSON': diagnostic({'pointer':'/qlog_format'},'Header does not declare JSON')
            listed=header.get('traces')
            if not isinstance(listed,list): diagnostic({'pointer':'/traces'},'Expected a trace array')
            else:
                for i,trace in enumerate(listed):
                    metadata={key:value for key,value in trace.items() if key!='events'} if isinstance(trace,dict) else trace
                    events=trace.get('events') if isinstance(trace,dict) else None
                    located=[(event,{'pointer':f'/traces/{i}/events/{n}'}) for n,event in enumerate(events)] if isinstance(events,list) else events
                    add_trace(i,metadata,located,{'pointer':f'/traces/{i}'})
    supported=isinstance(header,dict) and type(header.get('qlog_version')) is str and header['qlog_version']=='0.3' and header.get('qlog_format','JSON')==result['format']
    if not supported: diagnostic({'pointer':'/qlog_version'},'Unsupported or missing qlog version; no transport facts derived')
    result['profile']={'selected':parameters.get('profile','generic'),'producer_authenticated':False,
        'transport_facts':supported,'clock':{'unit':'unknown','domain':'unknown'}}
    if supported and parameters.get('profile')=='aioquic-json-0.3':
        result['profile']['clock']={'unit':'milliseconds','domain':'unix-epoch','basis':'caller-selected producer profile, not authentication'}
    all_events=[];groups={}
    for trace_index,metadata,events,location in traces:
        trace={'trace_index':trace_index,'location':location,'metadata':preserve(metadata),'recorded_events':len(events)}
        result['traces'].append(trace)
        for ordinal,(event,source) in enumerate(events):
            row={'trace_index':trace_index,'ordinal':ordinal,'location':source,'event':preserve(event)}
            row['name']=event.get('name') if isinstance(event,dict) and type(event.get('name')) is str else None
            all_events.append(row)
            if not isinstance(event,dict) or row['name'] is None:
                diagnostic(source,'Event must be an object with a string name');continue
            if not supported: continue
            data=event.get('data')
            if row['name']=='recovery:packet_lost':
                result['loss_declarations'].append({'trace_index':trace_index,'ordinal':ordinal,'location':source,'data':preserve(data),'basis':'producer-declared loss, not independently verified'})
            if row['name'] not in {'transport:packet_sent','transport:packet_received'}: continue
            frames=data.get('frames') if isinstance(data,dict) else None
            if not isinstance(frames,list):
                diagnostic(source,'Packet frame list is absent or invalid; STREAM coverage is unknown for this event');continue
            for frame_index,frame in enumerate(frames):
                if not isinstance(frame,dict) or frame.get('frame_type')!='stream': continue
                values=[unsigned(frame.get(key)) for key in ['stream_id','offset','length']]
                fin=frame.get('fin')
                if any(value is None for value in values) or (fin is not None and type(fin) is not bool):
                    diagnostic({**source,'frame_index':frame_index},'STREAM numeric fields or fin invalid; frame excluded from derived ranges');continue
                stream_id,offset,length=values
                if offset+length>=2**62:
                    diagnostic({**source,'frame_index':frame_index},'STREAM end exceeds the QUIC variable-length integer range');continue
                direction='sent' if row['name'].endswith('_sent') else 'received'
                group=groups.setdefault((trace_index,direction,stream_id),[])
                group.append({'ordinal':ordinal,'frame_index':frame_index,'location':source,
                    'offset':str(offset),'length':str(length),'fin':fin})
    for (trace_index,direction,stream_id),frames in groups.items():
        ranges=sorted((int(frame['offset']),int(frame['offset'])+int(frame['length'])) for frame in frames if int(frame['length']))
        merged=[]
        for start,end in ranges:
            if merged and start<=merged[-1][1]: merged[-1][1]=max(end,merged[-1][1])
            else: merged.append([start,end])
        total=sum(int(frame['length']) for frame in frames);unique=sum(end-start for start,end in merged)
        finals=sorted({int(frame['offset'])+int(frame['length']) for frame in frames if frame['fin'] is True})
        result['streams'].append({'trace_index':trace_index,'direction':direction,'stream_id':str(stream_id),
            'basis':'derived from all recorded valid STREAM frame ranges before event selection',
            'contributions':frames,'covered_ranges':[{'start':str(start),'end':str(end)} for start,end in merged],
            'frame_length_sum':str(total),'unique_bytes':str(unique),'repeated_bytes':str(total-unique),
            'reported_final_sizes':[str(value) for value in finals],
            'inconsistent_final_sizes':len(finals)>1,'payload_bytes':'not-recorded-by-range-metadata',
            'delivery_complete':'unknown'})
    selected=[row for row in all_events if ('trace_index' not in parameters or row['trace_index']==parameters['trace_index'])
        and parameters.get('event_name','') in (row['name'] or '')]
    offset,limit=parameters.get('offset',0),parameters.get('limit')
    result['events']=selected[offset:] if limit is None else selected[offset:offset+limit]
    result['coverage']={'recorded_events':len(all_events),'matching_events':len(selected),'offset':offset,
        'returned_events':len(result['events']),'has_more':offset+len(result['events'])<len(selected),'network_completeness':'unknown'}
    if 'trace_index' in parameters and parameters['trace_index'] not in {trace[0] for trace in traces}: diagnostic({'trace_index':parameters['trace_index']},'Selected valid trace does not exist')
    if result['diagnostics']: result['status']='partial' if all_events else 'invalid-or-unsupported'
    return result
