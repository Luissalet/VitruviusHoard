"""Project-owned instrumentation sessions and immutable runtime observations."""
import base64
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import threading
import time

from .inspection import digest
from .store import identifier,now


S={'type':'string','minLength':1}
DEVICE={'device_id':S,'remote_endpoint':S,'token':S}
SESSION={'session_id':S}
def definition(name,title,description,properties,required,mutates=False):
    return {'name':'frida.'+name,'title':'Instrumentación · '+title,'description':description,
        'mutates_device':False,'mutates_target':mutates,'provider':'frida',
        'inputSchema':{'type':'object','additionalProperties':False,'properties':properties,'required':required}}


OPERATIONS=[
    definition('devices','Dispositivos disponibles','Enumera dispositivos del SDK. Sólo conecta un remoto si indicas su endpoint; no adjunta procesos.',{'remote_endpoint':S,'token':S},[]),
    definition('processes','Procesos del dispositivo','Lista PID, nombre y metadatos observados en el dispositivo seleccionado.',DEVICE,['device_id']),
    definition('start','Abrir sesión','Adjunta un PID exacto o crea argv suspendido. Carga scripts antes de reanudar; cerrar reanuda un spawn pausado y desconecta sin matar el proceso.',
        {**DEVICE,'mode':{'enum':['attach','spawn']},'pid':{'type':'integer','minimum':1},'argv':{'type':'array','minItems':1,'items':S},'cwd':S},['device_id','mode'],True),
    definition('load','Cargar script','Ejecuta JavaScript del usuario en el proceso. Puede leer o cambiar memoria y comportamiento. Conserva hash del texto, mensajes y errores; no guarda el texto.',
        {**SESSION,'source':S,'name':S,'runtime':{'enum':['qjs','v8']}},['session_id','source'],True),
    definition('resume','Reanudar proceso creado','Reanuda únicamente el proceso creado y aún pausado por esta sesión.',SESSION,['session_id'],True),
    definition('unload','Descargar script','Retira la instrumentación de un script seleccionado. Sus cambios previos no se revierten.',{**SESSION,'script_id':S},['session_id','script_id'],True),
    definition('status','Estado y mensajes','Congela todos los eventos grabados hasta este momento con secuencias, tiempos y bytes. Consulta y pagina el resultado como cualquier análisis.',SESSION,['session_id']),
    definition('close','Cerrar sesión','Descarga scripts, reanuda un spawn aún pausado y desconecta la instrumentación. No mata el proceso; su estado final queda desconocido.',SESSION,['session_id'],True),
    definition('observe','Ventana de instrumentación','Adjunta un PID exacto, carga el script durante una ventana finita y desconecta al terminar. No mata el proceso ni revierte efectos del script.',
        {**DEVICE,'pid':{'type':'integer','minimum':1},'source':S,'duration_seconds':{'type':'integer','minimum':1}},['device_id','pid','source'],True),
]


def engine():
    # Dependency discovery must not import the SDK or contact its device manager.
    try:
        version=importlib.metadata.version('frida')
        available=importlib.util.find_spec('frida') is not None
    except importlib.metadata.PackageNotFoundError:
        version=None;available=False
    return {'available':available,'version':version,'external_api_required':False}


def safe_value(value):
    if isinstance(value,bytes): return {'encoding':'base64','bytes':len(value),'data':base64.b64encode(value).decode()}
    if isinstance(value,dict): return {k:safe_value(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [safe_value(v) for v in value]
    return value


class Session:
    def __init__(self,session_id,project_id,folder,device_manager,device,target):
        self.id,self.project_id,self.folder=session_id,project_id,folder
        self.device_manager,self.device,self.target=device_manager,device,target
        self.connection=None;self.scripts={};self.paused=False;self.state='starting'
        self.action_lock=threading.Lock();self.events_lock=threading.Lock();self.sequence=0
        self.recording_error=None

    def event(self,kind,**value):
        with self.events_lock:
            self.sequence+=1
            event={'sequence':self.sequence,'recorded_at':now(),'kind':kind,**safe_value(value)}
            try:
                with (self.folder/'events.jsonl').open('a',encoding='utf8',newline='\n') as output:
                    output.write(json.dumps(event,ensure_ascii=False,allow_nan=False)+'\n')
            except (OSError,ValueError) as exc:
                self.recording_error=type(exc).__name__+': '+str(exc)

    def snapshot(self):
        with self.events_lock:
            events=read_events(self.folder/'events.jsonl')
            return {'session_id':self.id,'target':self.target,'session_state':self.state,
                'spawn_paused':self.paused,'scripts':[{'script_id':key,**value['metadata']} for key,value in self.scripts.items()],
                'events':events,'recording_error':self.recording_error,'target_final_state':'unknown'}


def read_events(path):
    if not path.is_file(): return []
    rows=[]
    for index,line in enumerate(path.read_bytes().splitlines()):
        try: rows.append(json.loads(line))
        except (ValueError,UnicodeError):
            rows.append({'kind':'recording-gap','line':index+1,'raw_base64':base64.b64encode(line).decode()})
    return rows


class FridaSessions:
    def __init__(self,manager):
        self.manager,self.store=manager,manager.store
        self.sessions={};self.cancellables={};self.lock=threading.Lock()

    def start(self,project_id,operation,parameters):
        import frida
        self.store.project(project_id)
        if operation=='frida.start':
            if parameters['mode']=='attach' and ('pid' not in parameters or 'argv' in parameters):
                raise ValueError('Attach requires one exact pid and no argv')
            if parameters['mode']=='spawn' and ('argv' not in parameters or 'pid' in parameters):
                raise ValueError('Spawn requires argv and no pid')
        if parameters.get('remote_endpoint') and parameters.get('device_id','remote')!='remote':
            raise ValueError('An explicit remote endpoint uses device_id remote')
        if parameters.get('token') and not parameters.get('remote_endpoint'):
            raise ValueError('A remote token requires an explicit endpoint')
        if 'session_id' in parameters: self.selected(project_id,parameters['session_id'])
        job_id=identifier();folder=self.store.directory/'analyses'/job_id;folder.mkdir(parents=True)
        public={k:v for k,v in parameters.items() if k not in {'token','source'}}
        if 'source' in parameters: public['source_sha256']=hashlib.sha256(parameters['source'].encode()).hexdigest()
        row=next(row for row in OPERATIONS if row['name']==operation)
        result={'kind':'runtime_analysis','operation':operation,'title':row['title'],'artifact_name':'Instrumentación Frida',
            'parameters':public,'mutates_target':row['mutates_target'],'source_kind':'runtime-observation',
            'cases':[],'passed':0,'failed':0,'limitations':['Script effects are not undone by unloading, cancellation or detach. Captures are historical; target final state is unknown.']}
        cancellable=frida.Cancellable()
        with self.lock: self.cancellables[job_id]=cancellable
        self.store.save_job(project_id,job_id,'queued',result)
        self.manager.pool.submit(self.run,project_id,job_id,operation,parameters,folder,result,cancellable)
        return self.store.job(job_id)

    def selected(self,project_id,session_id):
        with self.lock: session=self.sessions.get(session_id)
        if session is None or session.project_id!=project_id:
            raise ValueError('Select a live instrumentation session in this project; historical captures are not connections')
        return session

    def cancel(self,job_id):
        with self.lock: active=self.cancellables.get(job_id)
        if active: active.cancel()

    def connections(self,project_id):
        with self.lock: sessions=[s for s in self.sessions.values() if s.project_id==project_id and s.state!='closed']
        return [{'session_id':s.id,'target':dict(s.target),'session_state':s.state,'spawn_paused':s.paused,
            'scripts':[{'script_id':key,**value['metadata']} for key,value in list(s.scripts.items())]} for s in sessions]

    def run(self,project_id,job_id,operation,parameters,folder,result,cancellable):
        import frida
        from .runtime import retain
        state='failed';observation={'status':'incomplete','started_at':now(),'parameters':result['parameters']}
        session=None
        try:
            self.store.save_job(project_id,job_id,'running',result)
            sdk_path=Path(frida._frida.__file__)
            observation['engine']={'name':'Frida SDK','version':frida.__version__,'path':str(sdk_path),'sha256':digest(sdk_path)}
            with cancellable:
                with self.manager.lock:
                    if job_id in self.manager.cancelled: raise InterruptedError()
                observation.update(self.operate(project_id,job_id,operation,parameters,folder))
            observation['status']='observed';state='finished'
        except Exception as exc:
            message=type(exc).__name__+': '+str(exc)
            if parameters.get('token'): message=message.replace(parameters['token'],'[redacted]')
            result['error']=message;observation['error']=message
            state='cancelled' if isinstance(exc,(InterruptedError,frida.OperationCancelledError)) else 'failed'
        finally:
            session_id=observation.get('session_id',parameters.get('session_id',job_id if operation in {'frida.start','frida.observe'} else None))
            if session_id:
                with self.lock: session=self.sessions.get(session_id)
                if session:
                    observation.update(session.snapshot());result.update(session_id=session_id,recorded_session_state=session.state)
                    if operation in {'frida.start','frida.observe'}: result['session_state']=session.state
            observation['finished_at']=now()
            try:
                output=folder/'analysis.json'
                output.write_text(json.dumps({'runtime':'frida-sdk','operation':operation,'result':observation},ensure_ascii=False,allow_nan=False),encoding='utf8')
                retain(self.store,project_id,job_id,output,result)
            except Exception as exc:
                result['recording_error']=type(exc).__name__+': '+str(exc);state='failed'
            with self.manager.lock:
                if job_id in self.manager.cancelled: state='cancelled'
                self.manager.cancelled.discard(job_id)
            with self.lock: self.cancellables.pop(job_id,None)
            self.store.save_job(project_id,job_id,state,result)

    def connect(self,parameters):
        import frida
        manager=frida.DeviceManager()
        try:
            if parameters.get('remote_endpoint'):
                options={'token':parameters['token']} if parameters.get('token') else {}
                device=manager.add_remote_device(parameters['remote_endpoint'],**options)
            elif 'device_id' in parameters:
                device=manager.get_device_by_id(parameters['device_id'],0)
            else: device=None
            return manager,device
        except Exception:
            manager.close();raise

    def operate(self,project_id,job_id,operation,parameters,folder):
        if operation=='frida.observe':
            import frida
            self.operate(project_id,job_id,'frida.start',{**parameters,'mode':'attach'},folder)
            session=self.selected(project_id,job_id)
            try:
                self.operate(project_id,job_id,'frida.load',{'session_id':job_id,'source':parameters['source']},folder)
                end=time.monotonic()+parameters.get('duration_seconds',1)
                while time.monotonic()<end:
                    with self.manager.lock:
                        if job_id in self.manager.cancelled: raise InterruptedError()
                    time.sleep(min(.05,max(0,end-time.monotonic())))
            finally:
                with frida.Cancellable(): self.close_session(session)
            return {'session_id':job_id,'requested_duration_seconds':parameters.get('duration_seconds',1)}
        if operation in {'frida.devices','frida.processes'}:
            manager,device=self.connect(parameters)
            try:
                if operation=='frida.devices':
                    devices=manager.enumerate_devices()
                    return {'devices':[{'id':d.id,'name':d.name,'type':d.type} for d in devices]}
                return {'target':{'device_id':device.id,'device_name':device.name,'device_type':device.type},
                    'processes':[{'pid':p.pid,'name':p.name,'parameters':safe_value(p.parameters)} for p in device.enumerate_processes(scope='metadata')]}
            finally: manager.close()
        if operation=='frida.start':
            manager,device=self.connect(parameters)
            session=Session(job_id,project_id,folder,manager,device,{'device_id':device.id,'device_name':device.name,'device_type':device.type,'mode':parameters['mode']})
            with self.lock: self.sessions[job_id]=session
            with session.action_lock:
                try:
                    pid=parameters['pid'] if parameters['mode']=='attach' else device.spawn(parameters['argv'],**({'cwd':parameters['cwd']} if parameters.get('cwd') else {}))
                    session.target['pid']=pid;session.paused=parameters['mode']=='spawn'
                    (folder/'frida-session.json').write_text(json.dumps({'session_id':job_id,'project_id':project_id,'target':session.target,'started_at':now()}),encoding='utf8')
                    session.event('target-selected',target=session.target,spawn_paused=session.paused)
                    session.connection=device.attach(pid)
                    def detached(reason,crash=None):
                        session.state='detached';session.event('detached',reason=reason,crash=str(crash) if crash else None)
                    session.connection.on('detached',detached)
                    session.state='open';session.event('attached')
                    return {'session_id':session.id}
                except Exception:
                    # Outside the cancelled SDK context, resume a newly created suspended process.
                    import frida
                    with frida.Cancellable(): self.close_session(session)
                    raise
        session=self.selected(project_id,parameters['session_id'])
        with session.action_lock:
            if operation=='frida.close': self.close_session(session)
            elif operation=='frida.status': pass
            elif session.state!='open': raise ValueError('Instrumentation session is no longer attached')
            elif operation=='frida.resume':
                if not session.paused: raise ValueError('Only this session\'s paused spawn can be resumed')
                session.device.resume(session.target['pid']);session.paused=False;session.event('resumed')
            elif operation=='frida.load':
                script_id=identifier();source=parameters['source']
                metadata={'name':parameters.get('name','instrumentation'),'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'source_bytes':len(source.encode())}
                script=session.connection.create_script(source,name=metadata['name'],runtime=parameters.get('runtime','qjs'))
                script.on('message',lambda message,data:session.event('script-message',script_id=script_id,message=message,data=data))
                session.scripts[script_id]={'script':script,'metadata':metadata}
                session.event('script-created',script_id=script_id,**metadata)
                script.load();session.event('script-loaded',script_id=script_id)
                return {'session_id':session.id,'script_id':script_id}
            elif operation=='frida.unload':
                script_id=parameters['script_id'];loaded=session.scripts.get(script_id)
                if not loaded: raise ValueError('Select a loaded script in this session')
                loaded['script'].unload();session.scripts.pop(script_id);session.event('script-unloaded',script_id=script_id)
            return {'session_id':session.id}

    def close_session(self,session):
        if session.state=='closed': return
        # Unload failures are recorded; detach still removes the session's instrumentation.
        for script_id,value in list(session.scripts.items()):
            try: value['script'].unload();session.scripts.pop(script_id);session.event('script-unloaded',script_id=script_id)
            except Exception as exc: session.event('cleanup-diagnostic',stage='unload',script_id=script_id,error=str(exc))
        if session.paused:
            session.device.resume(session.target['pid']);session.paused=False;session.event('resumed-before-detach')
        if session.connection and not session.connection.is_detached: session.connection.detach()
        session.scripts.clear()
        session.device_manager.close();session.state='closed';session.event('closed',target_final_state='unknown')
        start=self.store.job(session.id)
        start['result']['session_state']='closed'
        self.store.save_job(session.project_id,session.id,start['state'],start['result'])

    def shutdown(self):
        # The worker pool has already joined; create a final capture without new work.
        with self.lock: sessions=list(self.sessions.values())
        for session in sessions:
            if session.state=='closed': continue
            import frida
            job_id=identifier();folder=self.store.directory/'analyses'/job_id;folder.mkdir()
            row=next(r for r in OPERATIONS if r['name']=='frida.close')
            result={'kind':'runtime_analysis','operation':'frida.close','title':row['title'],'artifact_name':'Instrumentación Frida','source_kind':'runtime-observation','cases':[],'passed':0,'failed':0,'parameters':{'session_id':session.id},'shutdown_capture':True}
            self.run(session.project_id,job_id,'frida.close',{'session_id':session.id},folder,result,frida.Cancellable())


def recover(store):
    """Freeze available journals; never import the SDK or reconnect after restart."""
    from .runtime import retain
    for project in store.projects():
        for start in store.items('jobs',project['id']):
            if start['result'].get('operation') not in {'frida.start','frida.observe'} or start['result'].get('session_state') in {'closed','interrupted','imported'}: continue
            folder=store.directory/'analyses'/start['id'];metadata=folder/'frida-session.json'
            if not metadata.is_file(): continue
            try:
                recorded=json.loads(metadata.read_text(encoding='utf8'))
                job_id=identifier();destination=store.directory/'analyses'/job_id;destination.mkdir()
                output=destination/'analysis.json'
                output.write_text(json.dumps({'runtime':'frida-sdk-historical','operation':'frida.status','result':{
                    'status':'incomplete','session_id':start['id'],'session_state':'interrupted','target':recorded['target'],
                    'events':read_events(folder/'events.jsonl'),'connection_restored':False,'target_final_state':'unknown',
                    'limitations':['Connection was lost. No attach, spawn, resume or script replay was attempted.']}},ensure_ascii=False),encoding='utf8')
                result={'kind':'runtime_analysis','operation':'frida.status','title':'Instrumentación · Grabación interrumpida','artifact_name':'Instrumentación Frida','source_kind':'runtime-observation','cases':[],'passed':0,'failed':0}
                store.save_job(project['id'],job_id,'interrupted',result)
                retain(store,project['id'],job_id,output,result);store.save_job(project['id'],job_id,'interrupted',result)
                start['result']['session_state']='interrupted';start['result']['recovered_recording_job_id']=job_id
            except (OSError,ValueError) as exc: start['result']['recovery_error']=str(exc)
            store.save_job(project['id'],start['id'],start['state'],start['result'])
