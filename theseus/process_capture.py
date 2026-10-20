"""Owned local processes with retained stream, terminal and file observations."""
import base64
import codecs
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time

import psutil

try:from .process_services import SERVICES, ScenarioServices
except ImportError:from process_services import SERVICES, ScenarioServices
try:from .process_commands import COMMANDS, compiler, materialize
except ImportError:from process_commands import COMMANDS, compiler, materialize

TEXT={'type':'string'}
POSITIVE={'type':'number','exclusiveMinimum':0}
STEPS={'type':'array','items':{'type':'object','additionalProperties':False,'required':['kind'],
    'properties':{'kind':{'enum':['input','close_stdin','wait_output','resize','signal','wait_event']},'text':TEXT,'data_base64':TEXT,
        'at_seconds':{'type':'number','minimum':0},'channel':{'enum':['stdout','stderr','terminal']},
        'signal':{'enum':['interrupt','terminate','kill']},'event_match':{'type':'object','minProperties':1},
        'columns':{'type':'integer','minimum':1},'rows':{'type':'integer','minimum':1}},
    'allOf':[
        {'if':{'properties':{'kind':{'enum':['input','wait_output']}}},'then':{'oneOf':[{'required':['text']},{'required':['data_base64']}]}},
        {'if':{'properties':{'kind':{'const':'resize'}}},'then':{'required':['columns','rows']}},
        {'if':{'properties':{'kind':{'const':'signal'}}},'then':{'required':['signal']}},
        {'if':{'properties':{'kind':{'const':'wait_event'}}},'then':{'required':['event_match']}},
    ]}}
PARAMETERS={'type':'object','additionalProperties':False,'required':['argv'],'properties':{
    'argv':{'type':'array','minItems':1,'items':{'type':'string','minLength':1}},'cwd':TEXT,
    'mode':{'enum':['pipes','pty']},'environment':{'type':'object','additionalProperties':TEXT},
    'timeout_seconds':POSITIVE,'steps':STEPS,'services':SERVICES,'commands':COMMANDS,
    'terminal':{'type':'object','additionalProperties':False,'properties':{
        'columns':{'type':'integer','minimum':1},'rows':{'type':'integer','minimum':1},'scrollback':{'type':'integer','minimum':0}}},
    'files':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['label','path'],'properties':{'label':TEXT,'path':TEXT}}},
}}
OPERATIONS=[{'name':'process.capture','title':'Procesos · Capturar escenario','provider':'process','mutates_device':False,'mutates_target':True,
    'description':'Ejecuta el programa indicado y guarda sus entradas, salida, terminal y archivos seleccionados. Sus efectos persisten. El timeout es opcional y explícito; cancelar detiene sólo los procesos iniciados por la captura.',
    'inputSchema':PARAMETERS}]


def engine():
    renderer=Path(__file__).resolve().parents[1]/'software_native/engine/dist/process-terminal.js'
    return {'available':True,'pipes':True,'pty':os.name=='nt','terminal_renderer':bool(shutil.which('node') and renderer.is_file()),
        'command_shim_compiler':str(compiler()) if compiler() else None,'external_api_required':False}


def _bytes(data):
    return {'base64':base64.b64encode(data).decode('ascii'),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}


def _write(path,document):
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf8')
    temporary.replace(path)


def _file(path,excluded=None):
    try:
        if excluded is not None and path.absolute()==excluded.absolute():return {'state':'observer-directory-excluded'}
        metadata=path.lstat()
        if path.is_symlink() or getattr(metadata,'st_file_attributes',0)&0x400:
            return {'state':'link-not-followed','target':os.readlink(path) if path.is_symlink() else None}
        if path.is_dir():
            return {'state':'directory','members':[{'name':member.name,**_file(member,excluded)} for member in sorted(path.iterdir(),key=lambda value:value.name)]}
        before=(metadata.st_size,metadata.st_mtime_ns)
        data=path.read_bytes();after=path.stat()
        return {'state':'file' if before==(after.st_size,after.st_mtime_ns) else 'unstable','mode':metadata.st_mode,**_bytes(data)}
    except FileNotFoundError:return {'state':'absent'}
    except OSError as error:return {'state':'unavailable','error':str(error)}


def _identity(pid):
    process=psutil.Process(pid)
    return {'pid':pid,'created':process.create_time(),'command':process.cmdline()}


def _stop(identity):
    try:
        parent=psutil.Process(identity['pid'])
        if parent.create_time()!=identity['created'] or parent.cmdline()!=identity['command']:
            return {'owned_process_stopped':False,'reason':'process-identity-changed'}
        children=parent.children(recursive=True)
        saved=[_identity(child.pid) for child in children]+[identity]
        for row in reversed(saved):
            try:
                child=psutil.Process(row['pid'])
                if child.create_time()==row['created'] and child.cmdline()==row['command']:child.terminate()
            except psutil.NoSuchProcess:pass
        _,remaining=psutil.wait_procs([parent,*children],timeout=2)
        by_pid={row['pid']:row for row in saved}
        for child in remaining:
            row=by_pid[child.pid]
            try:
                if child.create_time()==row['created'] and child.cmdline()==row['command']:child.kill()
            except psutil.NoSuchProcess:pass
        _,remaining=psutil.wait_procs(remaining,timeout=2)
        return {'owned_process_stopped':not remaining,'remaining':[p.pid for p in remaining],'identities':saved}
    except psutil.NoSuchProcess:return {'owned_process_stopped':True,'remaining':[]}


class Pipes:
    def __init__(self,argv,cwd,environment,terminal):
        self.job=None
        self.process=subprocess.Popen(argv,cwd=cwd,env=environment,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)|(0x4 if os.name=='nt' else 0))
        self.pid=self.process.pid;self.queue=queue.Queue();self.eof=set();self.threads=[];self.errors={}
        if os.name=='nt':
            try:
                try:from .process_windows import WindowsJob
                except ImportError:from process_windows import WindowsJob
                self.job=WindowsJob();self.job.assign(self.pid)
                threads=psutil.Process(self.pid).threads()
                if len(threads)!=1:raise OSError('The new suspended process does not have one initial thread')
                self.job.resume(thread_id=threads[0].id)
            except BaseException:
                self.process.terminate();self.process.wait(timeout=5)
                if self.job is not None:self.job.close()
                for stream in [self.process.stdin,self.process.stdout,self.process.stderr]:stream.close()
                raise
        def reader(channel,stream):
            try:
                while data:=os.read(stream.fileno(),65536):self.queue.put((channel,data))
            except OSError as error:self.errors[channel]=str(error)
            finally:self.queue.put((channel,None));stream.close()
        for channel,stream in [('stdout',self.process.stdout),('stderr',self.process.stderr)]:
            thread=threading.Thread(target=reader,args=(channel,stream),daemon=True);thread.start();self.threads.append(thread)
    def read(self):
        rows=[]
        while True:
            try:channel,data=self.queue.get_nowait()
            except queue.Empty:break
            if data is None:self.eof.add(channel)
            else:rows.append((channel,data))
        if not rows and self.errors:raise OSError('Process stream read failed: '+json.dumps(self.errors))
        return rows
    def poll(self):return self.process.poll()
    def write_some(self,data):return os.write(self.process.stdin.fileno(),data)
    def finalize_output(self):pass
    def close_input(self):self.process.stdin.close()
    def resize(self,columns,rows):raise ValueError('Resize requires pseudoterminal mode')
    def signal(self,name):
        if name=='interrupt' and os.name=='nt':raise ValueError('Windows pipe capture has no attached console for Ctrl+C; use pty mode or terminate/kill')
        self.process.send_signal({'interrupt':signal.SIGINT,'terminate':signal.SIGTERM,'kill':getattr(signal,'SIGKILL',signal.SIGTERM)}[name])
        return 'TerminateProcess' if os.name=='nt' else 'POSIX-signal'
    def complete(self):return self.eof=={'stdout','stderr'}
    def close(self):
        if self.job is not None:self.job.close()
        if not self.process.stdin.closed:self.process.stdin.close()
        for thread in self.threads:thread.join(timeout=1)


class InputWrite:
    """Drain a caller-selected input without blocking capture/cancellation."""
    def __init__(self,session,data):
        self.accepted=0;self.error=None;self.started=time.monotonic();self.done=threading.Event()
        def send():
            try:
                while self.accepted<len(data):
                    count=session.write_some(data[self.accepted:self.accepted+65536])
                    if not count:raise OSError('The input channel accepted no bytes')
                    self.accepted+=count
            except (OSError,ValueError) as error:self.error=str(error)
            finally:self.done.set()
        self.thread=threading.Thread(target=send,daemon=True);self.thread.start()


def _render(folder,terminal,frames):
    worker=Path(__file__).resolve().parents[1]/'software_native/engine/dist/process-terminal.js'
    request=folder/'terminal-render-request.json';output=folder/'terminal-render.json'
    _write(request,{'terminal':terminal,'frames':frames})
    process=subprocess.run([shutil.which('node') or 'node',str(worker),str(request),str(output)],capture_output=True)
    if process.returncode:raise ValueError('Terminal renderer failed: '+process.stderr.decode('utf8',errors='replace'))
    return json.loads(output.read_text(encoding='utf8'))


def capture_process(parameters,folder,cancelled=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    latest=folder/'capture-latest.json'
    if latest.exists():raise FileExistsError('This process capture has already started; inspect its retained result')
    argv=list(parameters['argv']);cwd=Path(parameters.get('cwd') or os.getcwd()).resolve()
    environment={**os.environ,**parameters.get('environment',{})}
    if os.name=='nt':environment={key.upper():value for key,value in environment.items()}
    executable=Path(argv[0]);candidate=executable if executable.is_absolute() else cwd/executable
    argv[0]=str(candidate.resolve()) if candidate.is_file() else shutil.which(argv[0],path=environment.get('PATH')) or str(candidate.absolute())
    mode=parameters.get('mode','pipes');terminal={'columns':80,'rows':24,'scrollback':1000,**parameters.get('terminal',{})}
    timeout=parameters.get('timeout_seconds')
    if timeout is not None and timeout<=0:raise ValueError('An explicit timeout must be positive')
    if mode not in {'pipes','pty'}:raise ValueError('Process mode is pipes or pty')
    if mode=='pty' and os.name!='nt':raise ValueError('The current pseudoterminal backend requires Windows; pipe mode is portable')
    process_files={}
    for argument in argv:
        try:
            path=Path(argument);path=path if path.is_absolute() else cwd/path
            if path.is_file():process_files[str(path.resolve())]=hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:pass
    observed=[]
    for row in parameters.get('files',[]):
        path=Path(row['path']);path=path.absolute() if path.is_absolute() else (cwd/path).absolute()
        observed.append({'label':row['label'],'path':str(path),'before':_file(path,folder)})
    result={'format':'vitruvius.process-capture/1','status':'capturing','target':{'argv':argv,'cwd':str(cwd)},
      'contract':parameters,'contract_sha256':hashlib.sha256(json.dumps(parameters,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
      'process':{'argv':argv,'cwd':str(cwd),'files':process_files,'exit_code':None},'steps':[],'events':[],
      'files':observed,'order':{'global_collection_order_is_causality':False,'edges':[]},'termination':{},
      'limitations':['Observations cover only this selected run and explicit files; effects are not restored.',
        'Collection timestamps do not imply causality between independent channels.',
        'Ambient environment and concurrent changes outside the observed process remain unknown.']}
    outputs={'stdout':bytearray(),'stderr':bytearray(),'terminal':bytearray()};frames=[];counts={};last={};started=time.monotonic()
    decoder=codecs.getincrementaldecoder('utf8')();descendants={};pending_input=None
    def event(channel,kind,**payload):
        counts[channel]=counts.get(channel,0)+1;key=f'{channel}:{counts[channel]}'
        row={'id':key,'channel':channel,'channel_sequence':counts[channel],'at_seconds':time.monotonic()-started,'kind':kind,**payload}
        if channel in last:result['order']['edges'].append({'before':last[channel],'after':key,'basis':'same-observed-channel'})
        last[channel]=key;result['events'].append(row);return key
    def persist(final=False):
        result['stdout']=_bytes(bytes(outputs['stdout']));result['stderr']=_bytes(bytes(outputs['stderr']))
        result['terminal']={'raw_text':outputs['terminal'].decode('utf8',errors='replace'),'raw_bytes':_bytes(bytes(outputs['terminal'])),
            'representation':'Windows-ConPTY-UTF-8-VT-bytes' if mode=='pty' else 'not-selected'}
        if mode=='pty' and final:
            try:
                decoder.decode(b'',final=True)
                result['terminal']['rendered']=_render(folder,terminal,frames)
            except (OSError,ValueError,UnicodeError) as error:
                result['terminal']['rendering']={'state':'unavailable','error':str(error)}
                result['status']='partial'
        document={'operation':'process.capture','runtime':sys.version.split()[0],'result':result}
        _write(latest,document)
        if final:_write(folder/'analysis.json',document)
    def collect():
        changed=collect_services()
        for channel,data in session.read():
            outputs[channel].extend(data);key=event(channel,'output',**_bytes(data));changed=True
            if channel=='terminal':
                decoded=decoder.decode(data)
                if decoded:frames.append({'kind':'output','event_id':key,'text':decoded})
        return changed
    def collect_services():
        rows=services.read() if services is not None else []
        for row in rows:
            channel,kind=row.pop('channel'),row.pop('kind');row['observed_at_seconds']=row.pop('observed_monotonic')-started
            event(channel,kind,**row)
        return bool(rows)
    persist()
    session=None;owner=None;services=None;reason='natural-exit'
    try:
        if parameters.get('services') or parameters.get('commands'):
            services=ScenarioServices(parameters.get('services',[]),parameters.get('commands',[]));environment.update(services.environment)
            result['services']={'bindings':services.environment,'observation_layer':'ASGI HTTP bodies and complete WebSocket messages; not TCP/TLS packets or frame fragmentation'}
        if parameters.get('commands'):
            result['command_shims']=materialize(parameters['commands'],folder/'command-shims')
            environment['PATH']=str(folder/'command-shims')+os.pathsep+environment.get('PATH','')
        result['observer_startup_seconds']=time.monotonic()-started
        started=time.monotonic()
        if mode=='pty':
            try:from .process_windows import WindowsTerminal
            except ImportError:from process_windows import WindowsTerminal
            session=WindowsTerminal(argv,cwd,environment,terminal)
        else:session=Pipes(argv,cwd,environment,terminal)
        owner=_identity(session.pid);result['process'].update(owner);_write(folder/'process-owner.json',owner)
        event('lifecycle','started',identity=owner);persist()
        steps=parameters.get('steps',[]);next_step=0
        while True:
            changed=collect()
            exit_code=session.poll();elapsed=time.monotonic()-started
            try:
                parent=psutil.Process(owner['pid'])
                if parent.create_time()==owner['created']:
                    for child in parent.children(recursive=True):
                        try:descendants[(child.pid,child.create_time())]=_identity(child.pid)
                        except psutil.NoSuchProcess:pass
            except psutil.NoSuchProcess:pass
            live=[]
            for row in descendants.values():
                try:
                    child=psutil.Process(row['pid'])
                    if child.create_time()==row['created'] and child.is_running() and child.status()!=psutil.STATUS_ZOMBIE:live.append(row)
                except psutil.NoSuchProcess:pass
            active_job=session.job.accounting()['active_processes'] if getattr(session,'job',None) else None
            child_alive=bool(live) or (active_job is not None and active_job>0 and exit_code is not None)
            if exit_code is not None and not child_alive:session.finalize_output()
            while next_step<len(steps):
                step=steps[next_step]
                if elapsed<step.get('at_seconds',0):break
                if step['kind']=='wait_output':
                    selected=step.get('channel','terminal' if mode=='pty' else 'stdout')
                    needle=base64.b64decode(step['data_base64'],validate=True) if 'data_base64' in step else step['text'].encode('utf8')
                    if needle not in outputs[selected]:break
                if step['kind']=='wait_event':
                    try:from .process_compare import subset
                    except ImportError:from process_compare import subset
                    if not any(subset(row,step['event_match']) for row in result['events']):break
                row={'index':next_step,'definition':step,'state':'dispatched','at_seconds':elapsed}
                try:
                    pty_interrupt=step['kind']=='signal' and step['signal']=='interrupt' and mode=='pty'
                    if step['kind']=='input' or pty_interrupt:
                        if pending_input is None:
                            data=b'\x03' if pty_interrupt else base64.b64decode(step['data_base64'],validate=True) if 'data_base64' in step else step['text'].encode('utf8')
                            pending_input=InputWrite(session,data)
                        if not pending_input.done.is_set():break
                        row.update(accepted_bytes=pending_input.accepted,at_seconds=pending_input.started-started,
                            completed_at_seconds=time.monotonic()-started)
                        error=pending_input.error
                        pending_input=None
                        if pty_interrupt:row['mechanism']='ConPTY input ETX; target console input mode determines interrupt handling'
                        if error:raise OSError(error)
                    elif step['kind']=='close_stdin':session.close_input()
                    elif step['kind']=='resize':
                        session.resize(step['columns'],step['rows'])
                        key=event('terminal','resize',columns=step['columns'],rows=step['rows'])
                        frames.append({'kind':'resize','event_id':key,'columns':step['columns'],'rows':step['rows']})
                    elif step['kind']=='signal':row['mechanism']=session.signal(step['signal'])
                    elif step['kind'] not in {'wait_output','wait_event'}:raise ValueError('Unknown process interaction kind')
                    row['event_id']=event('interaction',step['kind'],step_index=next_step)
                except (OSError,ValueError) as error:row.update(state='failed',error=str(error));reason='step-error'
                result['steps'].append(row);next_step+=1;changed=True
                if row['state']=='failed':break
            if changed:persist()
            if reason=='step-error':break
            if exit_code is not None and not child_alive and session.complete():break
            if cancelled is not None and cancelled():reason='cancelled';break
            if timeout is not None and elapsed>=timeout:reason='explicit-timeout';break
            time.sleep(.002)
        if exit_code is None or child_alive:
            outcomes=[session.job.stop()] if getattr(session,'job',None) else [_stop(row) for row in [owner,*live]]
            result['termination']={'owned_process_stopped':all(row['owned_process_stopped'] for row in outcomes),'outcomes':outcomes}
        else:result['termination']={'owned_process_stopped':True,'remaining':[]}
        if session.poll() is not None:session.finalize_output()
        # Collect the pipe EOF/tail after stopping the owned process. A missing
        # EOF remains explicit, never inferred from a quiet polling interval.
        for thread in getattr(session,'threads',[]):thread.join(timeout=2)
        if pending_input is not None:
            pending_input.thread.join(timeout=2)
            result['steps'].append({'index':next_step,'definition':steps[next_step],'state':'partial',
                'accepted_bytes':pending_input.accepted,'accepted_bytes_is_lower_bound':True,
                'error':pending_input.error,'input_writer_closed':not pending_input.thread.is_alive()})
            next_step+=1
        collect()
        result['process']['exit_code']=session.poll()
        result['process']['observed_descendants']=list(descendants.values())
        if getattr(session,'job',None):result['process']['job_accounting']=session.job.accounting()
        result['termination']['reason']=reason
        result['stream_complete']=session.complete()
        result['status']='complete' if reason=='natural-exit' and session.complete() and next_step==len(steps) and all(row['state']=='dispatched' for row in result['steps']) else 'partial'
        for index in range(next_step,len(steps)):result['steps'].append({'index':index,'definition':steps[index],'state':'not-dispatched'})
        event('lifecycle','ended',exit_code=result['process']['exit_code'],reason=reason)
    except Exception as error:
        result.update(status='partial',error=type(error).__name__+': '+str(error))
        if session is not None and owner is not None:result['termination']={**_stop(owner),'reason':'observer-error'}
    finally:
        if services is not None:
            services.close()
            collect_services()
            result['services']['closed']=not services.thread.is_alive();result['services']['errors']=services.errors
            if services.errors:result['status']='partial'
        if session is not None:
            try:session.close()
            except OSError as error:result.update(status='partial',cleanup_error=str(error))
        for row in observed:row['after']=_file(Path(row['path']),folder)
        result['process']['input_file_changes']=[]
        for path,sha256 in process_files.items():
            current=_file(Path(path),folder)
            if current.get('sha256')!=sha256:result['process']['input_file_changes'].append({'path':path,'before_sha256':sha256,'after':current})
        if result['process']['input_file_changes']:result['limitations'].append('Selected program input files changed during observation; captured runtime behavior is not bound to unchanged original bytes.')
        persist(final=True)
    return result


def latest(folder):
    return next((path for path in [folder/'analysis.json',folder/'capture-latest.json'] if path.is_file()),None)


def freeze_recording(folder):
    source=latest(folder)
    if source is None:raise ValueError('No retained process observation prefix')
    document=json.loads(source.read_bytes())
    document['result'].update(status='partial',stream_complete=False)
    document['result'].setdefault('termination',{})['observer_state']='interrupted-or-cancelled'
    document['result']['limitations'].append('The observer did not finish; the retained prefix does not confirm all target effects or stream closure.')
    target=folder/'frozen-process-observation.json';_write(target,document);return target


def stop_interrupted_worker(folder):
    source=folder/'capture-observer.json'
    if not source.is_file():return {'state':'observer-identity-unavailable'}
    identity=json.loads(source.read_text(encoding='utf8'))
    command=identity.get('command',[])
    if str(Path(__file__).resolve()) not in command or str(folder/'request.json') not in command:
        return {'state':'observer-command-not-bound-to-job'}
    return _stop(identity)


def main():
    from jsonschema import validate
    request_path,output=map(Path,sys.argv[1:3]);request=json.loads(request_path.read_text(encoding='utf8'))
    if request.get('operation')!='process.capture':raise ValueError('Unknown process capture operation')
    validate(request['parameters'],PARAMETERS)
    _write(output.parent/'capture-observer.json',_identity(os.getpid()))
    result=capture_process(request['parameters'],output.parent)
    print(json.dumps({'ok':True,'operation':'process.capture','status':result['status']}))


if __name__=='__main__':main()
