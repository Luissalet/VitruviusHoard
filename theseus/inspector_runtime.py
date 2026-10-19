"""Inert discovery and explicitly selected V8 Inspector observation worker."""
import base64
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit,urlunsplit


S={'type':'string','minLength':1}
OPERATIONS=[
    {'name':'javascript.targets','title':'JavaScript · Destinos Inspector','provider':'inspector','mutates_device':False,
     'description':'Lista los destinos del endpoint Inspector indicado. No adjunta ni arranca procesos; las URLs comunicadas no prueban identidad física.',
     'inputSchema':{'type':'object','additionalProperties':False,'required':['inspector_endpoint'],'properties':{'inspector_endpoint':S}}},
    {'name':'javascript.observe','title':'JavaScript · Observar contexto y scripts','provider':'inspector','mutates_device':False,
     'description':'Conecta al target ID exacto, recoge contextos/scripts durante una ventana y desconecta sin evaluar, pausar, reanudar ni cerrar el destino. Capturar textos es una opción explícita adicional.',
     'inputSchema':{'type':'object','additionalProperties':False,'required':['inspector_endpoint','target_id'],
        'properties':{'inspector_endpoint':S,'target_id':S,'observation_ms':{'type':'integer','minimum':0},'capture_sources':{'type':'boolean'}}}},
]
OPERATIONS += [
    {'name':'browser.targets','title':'Web · Destinos CDP','provider':'inspector','mutates_device':False,
     'description':'Lista destinos del endpoint CDP explícito, sin adjuntar ni iniciar un navegador.',
     'inputSchema':OPERATIONS[0]['inputSchema']},
    {'name':'browser.observe','title':'Web · Observar página y red','provider':'inspector','mutates_device':False,
     'description':'Observa metadatos de la página seleccionada durante una ventana. DOM, listeners, textos, cuerpos y PNG se eligen explícitamente; no navega, evalúa, pausa ni cierra el destino.',
     'inputSchema':{'type':'object','additionalProperties':False,'required':['inspector_endpoint','target_id'],
        'properties':{**OPERATIONS[1]['inputSchema']['properties'],
            'observation_ms':{'type':'integer','minimum':0,'default':1000},
            'capture_dom':{'type':'boolean'},'listener_selector':S,
            'capture_response_bodies':{'type':'boolean'},'capture_screenshot':{'type':'boolean'}}}},
]
OPERATIONS += [{**OPERATIONS[-1],'name':'browser.scenario','title':'Web · Ejecutar escenario CDP','mutates_device':True,
    'description':'Ejecuta los comandos CDP indicados, en orden, en la página seleccionada. Cada paso conserva su respuesta o error; cancelar no revierte sus efectos. No añade navegación, pulsaciones ni evaluación implícitas.',
    'inputSchema':{**OPERATIONS[-1]['inputSchema'],'required':['inspector_endpoint','target_id','steps'],
        'properties':{**OPERATIONS[-1]['inputSchema']['properties'],'steps':{'type':'array','minItems':1,
            'items':{'type':'object','additionalProperties':False,'required':['method','parameters'],
                'properties':{'method':S,'parameters':{'type':'object'},'observe_ms':{'type':'integer','minimum':0}}}}}}}]
OPERATIONS += [{'name':'browser.coverage','title':'Web · Cobertura precisa de JavaScript','provider':'inspector','mutates_device':True,
    'description':'Arma contadores precisos en la página seleccionada y recoge rangos UTF-16, textos e iniciadores durante una ventana finita. Reinicia contadores y desactiva temporalmente la optimización. Espera el recibo de armada antes de tus acciones externas; no navega, pulsa ni evalúa código.',
    'inputSchema':{'type':'object','additionalProperties':False,'required':['inspector_endpoint','target_id'],
        'properties':{'inspector_endpoint':S,'target_id':S,'observation_ms':{'type':'integer','minimum':1,'default':10000}}}}]


def engine():
    try:
        version=importlib.metadata.version('websocket-client')
        available=importlib.util.find_spec('websocket') is not None
    except importlib.metadata.PackageNotFoundError:
        version=None;available=False
    return {'available':available,'version':version,'external_api_required':False}


def utc(): return datetime.now(timezone.utc).isoformat()
def sha(raw): return hashlib.sha256(raw).hexdigest()


def endpoint(value):
    parsed=urlsplit(value)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError('Inspector endpoint must be an explicit HTTP(S) address without credentials, query or fragment')
    return value.rstrip('/')


def websocket_address(base,reported):
    selected=urlsplit(base);target=urlsplit(reported)
    expected='wss' if selected.scheme=='https' else 'ws'
    if target.scheme!=expected or target.username is not None or target.password is not None or target.fragment:
        raise ValueError('Target did not report a compatible WebSocket address')
    if (target.hostname,target.port or (443 if expected=='wss' else 80))!=(selected.hostname,selected.port or (443 if selected.scheme=='https' else 80)):
        raise ValueError('Reported WebSocket belongs to a different endpoint; select that endpoint explicitly')
    return urlunsplit(target)


def apply_protocol_observation(result,row):
    result['observations'].append(row)
    value=row['message'];method=value.get('method')
    if row.get('direction')=='received' and method:
        result['events'].append({'method':method,'parameters':value.get('params',{}),'recorded_at':row['recorded_at']})
        if method=='Debugger.scriptParsed':result['scripts'].append(dict(value['params']))
        if method=='Runtime.executionContextCreated':result['contexts'].append(dict(value['params']['context']))


class Capture:
    def __init__(self,request,output):
        import psutil
        self.operation=request['operation'];self.parameters=request['parameters'];self.output=output
        self.folder=output.parent;self.sequence=0;self.socket=None;self.command_id=0;self.window_closed=False
        self.journal_entries=0;self.journal_bytes=0;self.last_checkpoint=0
        process=psutil.Process()
        self.result={'status':'incomplete','started_at':utc(),'parameters':self.parameters,'observations':[],
            'scripts':[],'contexts':[],'events':[],'artifacts':[],'excluded_event_counts':{},
            'worker':{'pid':os.getpid(),'create_time':process.create_time(),'command':process.cmdline()},
            'collector':{'python':sys.version,'websocket_client':engine()['version'],'reader_sha256':sha(Path(__file__).read_bytes())},
            'limitations':['Discovery URLs and producer metadata do not authenticate a physical executable or source path.',
                'Script presence and context metadata do not prove calls, imports, IPC or behavioral equivalence.',
                'This is an observed window, not a complete history of the target.']}
        if self.operation=='browser.scenario':self.result['steps']=[]
        self.checkpoint()

    def document(self):
        self.result['protocol_journal']={'entries':self.journal_entries,'bytes':self.journal_bytes}
        return {'runtime':'page-cdp' if self.operation.startswith('browser.') else 'v8-inspector','operation':self.operation,'result':self.result}

    def checkpoint(self,force=True):
        if not force and time.monotonic()-self.last_checkpoint<.25:return
        self.sequence+=1
        path=self.folder/('partial-'+str(self.sequence).zfill(20)+'.json')
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.document(),ensure_ascii=True,allow_nan=False),encoding='utf8')
        temporary.replace(path)
        self.last_checkpoint=time.monotonic()
        for previous in self.folder.glob('partial-*.json'):
            if previous!=path:
                try: previous.unlink()
                except PermissionError: pass

    def protocol(self,row):
        entry={'sequence':self.journal_entries+1,'observation':row}
        raw=json.dumps(entry,ensure_ascii=True,allow_nan=False).encode('utf8')+b'\n'
        with (self.folder/'protocol.jsonl').open('ab') as handle:handle.write(raw)
        self.journal_entries+=1;self.journal_bytes+=len(raw)
        apply_protocol_observation(self.result,row)

    def http(self,base,path):
        import httpx
        started=utc()
        response=httpx.get(base+path,trust_env=False,timeout=None,follow_redirects=False)
        self.result['observations'].append({'transport':'http','url':base+path,'started_at':started,'finished_at':utc(),
            'status_code':response.status_code,'body_sha256':sha(response.content),'body_base64':base64.b64encode(response.content).decode()})
        self.checkpoint();response.raise_for_status()
        return response.json()

    def receive(self):
        import websocket
        try: raw=self.socket.recv()
        except websocket.WebSocketTimeoutException: return None
        if raw in {'',b''}: raise OSError('Inspector closed its selected connection')
        encoded=raw.encode() if isinstance(raw,str) else raw
        value=json.loads(encoded)
        method=value.get('method')
        included=not method or method in {'Debugger.scriptParsed','Debugger.scriptFailedToParse','Debugger.paused','Debugger.resumed',
            'Runtime.executionContextCreated','Runtime.executionContextDestroyed','Runtime.executionContextsCleared'}
        included=included or (self.operation.startswith('browser.') and method.startswith(('Page.','Network.')))
        if self.operation=='browser.scenario':included=True
        if method and self.operation.startswith('browser.') and self.window_closed:included=False
        if included:
            self.protocol({'transport':'cdp','direction':'received','recorded_at':utc(),
                'raw_base64':base64.b64encode(encoded).decode(),'message':value})
        else:
            counts=self.result['excluded_event_counts'];counts[method]=counts.get(method,0)+1
        if included:self.checkpoint(force=False)
        return value

    def command(self,method,parameters=None,raw_reply=False):
        self.command_id+=1;message={'id':self.command_id,'method':method,'params':parameters or {}}
        self.socket.send(json.dumps(message));self.protocol({'transport':'cdp','direction':'sent','recorded_at':utc(),'message':message})
        while True:
            reply=self.receive()
            if reply and reply.get('id')==message['id']:
                if raw_reply:return reply
                if 'error' in reply: raise ValueError('Inspector command failed: '+json.dumps(reply['error']))
                return reply.get('result',{})

    def run_steps(self):
        for index,request in enumerate(self.parameters['steps']):
            step={'name':str(index)+' · '+request['method'],'index':index,'request':request,'state':'started',
                'command_id':self.command_id+1,'protocol_sequence_start':self.journal_entries+1,'started_at':utc()}
            self.result['steps'].append(step);self.checkpoint()
            try:
                reply=self.command(request['method'],request['parameters'],raw_reply=True)
                step['response']=reply
                if 'error' in reply:
                    step['state']='protocol-error'
                    raise ValueError('Scenario CDP command failed: '+json.dumps(reply['error']))
                if 'exceptionDetails' in reply.get('result',{}):
                    step['state']='javascript-exception'
                    raise ValueError('Scenario JavaScript exception: '+json.dumps(reply['result']['exceptionDetails']))
                step['state']='observing';self.checkpoint()
                end=time.monotonic()+request.get('observe_ms',0)/1000
                while time.monotonic()<end:self.receive()
                step['state']='completed'
            except Exception as exc:
                if step['state'] not in {'protocol-error','javascript-exception'}:step['state']='incomplete'
                step['error']=type(exc).__name__+': '+str(exc)
                raise
            finally:
                step['finished_at']=utc();step['protocol_sequence_end']=self.journal_entries;self.checkpoint()

    def run(self):
        import websocket
        base=endpoint(self.parameters['inspector_endpoint'])
        self.result['version']=self.http(base,'/json/version')
        targets=self.http(base,'/json/list')
        if not isinstance(targets,list): raise ValueError('Inspector target discovery is not an array')
        self.result['targets']=[{**row,'location_state':'reported-unverified'} for row in targets]
        self.checkpoint()
        if self.operation in {'javascript.targets','browser.targets'}: return
        selected=[row for row in targets if row.get('id')==self.parameters['target_id']]
        if len(selected)!=1: raise ValueError('Select one current target ID from this Inspector endpoint')
        target=selected[0]
        browser=self.operation.startswith('browser.')
        if browser and target.get('type')!='page': raise ValueError('Select a current page target for browser observation')
        self.result['target']={**target,'location_state':'reported-unverified'}
        self.result['capture_mode']='metadata-and-selected-source-texts' if self.parameters.get('capture_sources') else 'passive-metadata'
        if browser and any(self.parameters.get(key) for key in ('capture_sources','capture_dom','listener_selector','capture_response_bodies','capture_screenshot')):
            self.result['capture_mode']='page-metadata-and-selected-snapshots'
        address=websocket_address(base,target.get('webSocketDebuggerUrl',''))
        self.socket=websocket.create_connection(address,timeout=None,suppress_origin=True,http_no_proxy=['*'])
        self.socket.settimeout(.1)
        try:
            if browser:
                self.command('Page.enable');self.command('Network.enable')
            self.command('Runtime.enable');self.command('Debugger.enable')
            if self.operation=='browser.coverage':
                from browser_coverage import capture_coverage
                capture_coverage(self)
                return
            if self.operation=='browser.scenario':
                self.result['capture_mode']='explicit-scenario-and-selected-snapshots'
                self.result['limitations'].append('Only caller-listed scenario commands are executed. Command effects are not undone; notification timing does not establish causality. Protocol and JavaScript errors stop the remaining sequence.')
                self.run_steps()
            duration=self.parameters.get('observation_ms',1000 if browser else 100)
            self.result['observation_window']={'started_at':utc(),'requested_ms':duration,'initial_inventory':'Runtime/Debugger enable notifications are retained before the timed window'}
            end=time.monotonic()+duration/1000
            while time.monotonic()<end: self.receive()
            self.result['observation_window']['ended_at']=utc()
            if browser:
                self.window_closed=True
                self.result['limitations'].append('Unsolicited notifications after the metadata window are excluded and counted; selected snapshot command replies remain recorded with their later collection times.')
            self.checkpoint()
            if self.parameters.get('capture_sources'):
                # Capture only this observed script inventory. Scripts parsed while
                # reading source remain independently recorded, not silently chased.
                for index,script in enumerate(list(self.result['scripts'])):
                    try:
                        reply=self.command('Debugger.getScriptSource',{'scriptId':script['scriptId']})
                        text=reply['scriptSource']
                        body=text.encode('utf8')
                        script['source']={'state':'captured','text':text,'sha256':sha(body),'utf8_bytes':len(body),'utf16_units':len(text.encode('utf-16-le'))//2}
                        path=self.folder/('captured-script-'+str(index).zfill(6)+'.js');path.write_bytes(body)
                        self.result['artifacts'].append({'path':str(path),'name':path.name,'sha256':sha(body),
                            'source_location':'target '+str(target['id'])+' · CDP script_id '+str(script['scriptId'])+' · reported URL '+script.get('url','')})
                    except (ValueError,KeyError,UnicodeError) as exc:
                        script['source']={'state':'unavailable','reason':type(exc).__name__+': '+str(exc)}
                    self.checkpoint(force=False)
            if browser:
                from browser_capture import capture_page
                capture_page(self)
            for script in self.result['scripts']:
                script.setdefault('source',{'state':'excluded','reason':'Source text was not selected in this observation inventory'})
        finally:
            self.socket.close();self.socket=None
            self.result['connection_closed']=True


def latest(folder):
    final=folder/'analysis.json'
    if final.is_file(): return final
    paths=sorted(folder.glob('partial-*.json'))
    return paths[-1] if paths else None


def restore_step_responses(document):
    if document['operation']!='browser.scenario':return False
    result=document['result'];responses={row['message']['id']:row for row in result['observations']
        if row.get('direction')=='received' and 'id' in row['message']}
    changed=False
    for step in result['steps']:
        row=responses.get(step['command_id'])
        if 'response' in step or row is None:continue
        reply=row['message'];step['response']=reply
        step['state']='protocol-error-recovered' if 'error' in reply else 'javascript-exception-recovered' if 'exceptionDetails' in reply.get('result',{}) else 'response-recovered'
        step['response_recorded_at']=row['recorded_at']
        step['recovery_note']='Response recovered from selected protocol frames; completion of the requested observation interval is unknown.'
        changed=True
    return changed


def recording(folder):
    while True:
        path=latest(folder)
        if path is None: return None
        try: raw=path.read_bytes();break
        except FileNotFoundError: continue
    document=json.loads(raw);result=document['result'];marker=result.get('protocol_journal',{'entries':0,'bytes':0})
    restored=restore_step_responses(document)
    journal=folder/'protocol.jsonl'
    tail=b''
    if journal.is_file():
        with journal.open('rb') as handle:
            handle.seek(marker['bytes']);tail=handle.read()
    if not tail:return json.dumps(document,ensure_ascii=True,allow_nan=False).encode('utf8') if restored else raw
    consumed=0;applied=0;gap=None
    for line in tail.splitlines(keepends=True):
        try:
            entry=json.loads(line)
            if not line.endswith(b'\n') or entry['sequence']!=marker['entries']+applied+1:raise ValueError('Incomplete or out-of-sequence journal entry')
            apply_protocol_observation(result,entry['observation']);applied+=1;consumed+=len(line)
        except (ValueError,KeyError,TypeError):
            gap={'byte_offset':marker['bytes']+consumed,'raw_base64':base64.b64encode(tail[consumed:]).decode('ascii')};break
    result['protocol_journal']={'entries':marker['entries']+applied,'bytes':marker['bytes']+consumed}
    result['journal_recovery']={'applied_entries':applied,'gap':gap,'scope':'Complete selected protocol entries after the last snapshot; higher-level snapshot summaries may remain incomplete.'}
    restore_step_responses(document)
    return json.dumps(document,ensure_ascii=True,allow_nan=False).encode('utf8')


def freeze_recording(folder):
    raw=recording(folder)
    if raw is None:return None
    path=folder/'interrupted-observation.json';path.write_bytes(raw)
    return path


def stop_interrupted_worker(folder,document):
    """Terminate only the recorded observation client, never its external target."""
    import psutil
    worker=document['result'].get('worker',{});command=worker.get('command',[])
    if len(command)!=4 or Path(command[1]).name!='inspector_runtime.py': return {'status':'unverified-worker'}
    expected=[str((folder/'request.json').resolve()),str((folder/'analysis.json').resolve())]
    if [str(Path(p).resolve()) for p in command[2:]]!=expected: return {'status':'unverified-job-paths'}
    try:
        process=psutil.Process(worker['pid'])
        if process.create_time()!=worker['create_time'] or process.cmdline()!=command: return {'status':'different-process'}
        process.terminate();process.wait(timeout=5)
        return {'status':'owned-observer-stopped','pid':process.pid}
    except psutil.NoSuchProcess: return {'status':'already-stopped'}
    except (psutil.Error,KeyError) as exc: return {'status':'unknown','diagnostic':str(exc)}


def main():
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'));output=Path(sys.argv[2]);capture=Capture(request,output)
    code=0
    try: capture.run();capture.result['status']='observed'
    except Exception as exc:
        capture.result['error']=type(exc).__name__+': '+str(exc);code=1
    finally:
        if capture.socket: capture.socket.close()
        capture.result['finished_at']=utc()
        temporary=output.with_suffix('.tmp')
        temporary.write_text(json.dumps(capture.document(),ensure_ascii=True,allow_nan=False),encoding='utf8')
        temporary.replace(output)
    return code


if __name__=='__main__': raise SystemExit(main())
