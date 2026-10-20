"""Owned WASM worker identity and recorded prefixes; never rerun a reader."""
import hashlib
import json
import os
from pathlib import Path

import psutil


def path_key(path):
    if not isinstance(path,str):raise ValueError('A recorded worker path must be a string')
    return os.path.normcase(os.path.abspath(path))


def command_key(command):
    if not isinstance(command,list) or len(command)!=4 or any(not isinstance(value,str) for value in command):
        raise ValueError('A WASM worker needs its exact executable, entry, request and output arguments')
    return [path_key(value) for value in command]


def record_worker(folder,process,command):
    """A failed identity write does not repeat or block the selected inspection."""
    try:
        if process.poll() is not None:return {'recorded':False,'reason':'The worker exited before its identity was recorded'}
        running=psutil.Process(process.pid);observed=running.cmdline()
        if command_key(observed)!=command_key(command):
            return {'recorded':False,'reason':'The started worker command could not be bound to its request'}
        identity={'format':'vitruvius.wasm-worker/1','pid':running.pid,'created':running.create_time(),
                  'command':observed,'executable':running.exe()}
        path=Path(folder)/'wasm-worker.json';temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(identity,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(path)
        return {'recorded':True,'identity_file':str(path),'identity':identity}
    except (OSError,ValueError,psutil.Error) as error:
        return {'recorded':False,'reason':str(error)}


def recording(folder,output):
    folder=Path(folder).resolve();output=Path(output)
    selected=output if output.is_file() else output.with_name(output.name+'.partial.json')
    if not selected.is_file():return None
    if selected.resolve().parent!=folder:raise ValueError('WASM observation leaves its job directory')
    raw=selected.read_bytes();document=json.loads(raw);value=document.get('result')
    if document.get('operation')!='wasm.artifact' or not isinstance(value,dict) or value.get('format')!='vitruvius.wasm-observation/1':
        raise ValueError('Not a retained WASM reader observation')
    sha=document.get('artifact_sha256');artifact=value.get('artifact',{})
    if not isinstance(sha,str) or len(sha)!=64 or any(char not in '0123456789abcdef' for char in sha) or artifact.get('sha256')!=sha:
        raise ValueError('WASM observation artifact identities disagree')
    request=json.loads((folder/'request.json').read_text(encoding='utf8'))
    if path_key(artifact.get('path'))!=path_key(request['path']):
        raise ValueError('WASM observation is not bound to its selected path')
    return selected,raw,document


def stop_interrupted_worker(folder,command):
    path=Path(folder)/'wasm-worker.json'
    if not path.is_file():return {'status':'no-recorded-worker-identity'}
    identity=json.loads(path.read_text(encoding='utf8'))
    if identity.get('format')!='vitruvius.wasm-worker/1' or command_key(identity.get('command'))!=command_key(command):
        return {'status':'worker-command-mismatch'}
    if type(identity.get('pid')) is not int or identity['pid']<=0 or type(identity.get('created')) not in {int,float} or identity['created']<=0:
        return {'status':'invalid-worker-identity'}
    try:parent=psutil.Process(identity['pid'])
    except psutil.NoSuchProcess:return {'status':'not-running','pid':identity['pid']}
    try:same_command=command_key(parent.cmdline())==command_key(identity['command'])
    except ValueError:same_command=False
    if parent.create_time()!=identity.get('created') or not same_command:
        return {'status':'worker-identity-mismatch','pid':identity['pid']}
    processes=[parent,*parent.children(recursive=True)]
    identities={process.pid:(process.create_time(),process.cmdline()) for process in processes}
    for process in reversed(processes):
        try:
            if (process.create_time(),process.cmdline())==identities[process.pid]:process.terminate()
        except psutil.NoSuchProcess:pass
    _,alive=psutil.wait_procs(processes,timeout=5)
    for process in alive:
        if (process.create_time(),process.cmdline())==identities[process.pid]:process.kill()
    _,alive=psutil.wait_procs(alive,timeout=5)
    if alive:raise RuntimeError('The recorded owned WASM worker did not stop')
    return {'status':'terminated-owned-worker','pid':identity['pid']}


def freeze_recording(folder,output):
    observed=recording(folder,output)
    if observed is None:return None
    path,raw,document=observed
    frozen=Path(folder)/'wasm-recovered.json';temporary=frozen.with_suffix('.tmp')
    temporary.write_bytes(raw);temporary.replace(frozen)
    return frozen,{'source_file':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
