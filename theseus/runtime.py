"""Explicit runtime observations, separate from execution-free artifact analysis."""
import json
from pathlib import Path
import sys

from jsonschema import validate, ValidationError

from .adb_runtime import OPERATIONS as ADB_OPERATIONS, engine
from . import frida_runtime, inspector_runtime, process_capture
from .inspection import digest
from .store import identifier

OPERATIONS=ADB_OPERATIONS+frida_runtime.OPERATIONS+inspector_runtime.OPERATIONS+process_capture.OPERATIONS


def catalog():
    available=engine()
    instrumentation=frida_runtime.engine()
    inspector=inspector_runtime.engine()
    process=process_capture.engine()
    return {'engine': {'adb':available,'frida':instrumentation,'inspector':inspector,'process':process,'external_api_required':False},
        'operations':[{**row,'available':bool(available),'availability_reason':'' if available else 'Instala Android platform-tools o configura THESEUS_ADB.'} for row in ADB_OPERATIONS]+
        [{**row,'available':instrumentation['available'],'availability_reason':'' if instrumentation['available'] else 'Instala el SDK libre Frida en el entorno de Theseus.'} for row in frida_runtime.OPERATIONS]+
        [{**row,'available':inspector['available'],'availability_reason':'' if inspector['available'] else 'Instala websocket-client en el entorno de Theseus.'} for row in inspector_runtime.OPERATIONS]+
        [{**row,'available':True,'availability_reason':'','pty_available':process['pty'],'terminal_renderer_available':process['terminal_renderer']} for row in process_capture.OPERATIONS]}


def start(manager,project_id,operation,parameters=None):
    definition=next((row for row in OPERATIONS if row['name']==operation),None)
    if definition is None:
        raise ValueError('Unknown runtime operation')
    parameters=json.loads(json.dumps(parameters or {}))
    try:
        validate(parameters,definition['inputSchema'])
    except ValidationError as exc:
        raise ValueError('Runtime parameters do not match the operation: '+str(exc)) from exc
    manager.store.project(project_id)
    if operation.startswith('frida.'):
        if not frida_runtime.engine()['available']: raise ValueError('Install the free Frida SDK in the app environment')
        return manager.frida_sessions.start(project_id,operation,parameters)
    inspector=any(row['name']==operation for row in inspector_runtime.OPERATIONS)
    if inspector: inspector_runtime.endpoint(parameters['inspector_endpoint'])
    if inspector and not inspector_runtime.engine()['available']:
        raise ValueError('Install websocket-client in the app environment')
    process=operation=='process.capture'
    if not inspector and not process and not engine():
        raise ValueError('Install Android platform-tools or configure THESEUS_ADB')
    job_id=identifier()
    folder=manager.store.directory/'analyses'/job_id
    folder.mkdir(parents=True)
    (folder/'request.json').write_text(json.dumps({'operation':operation,'parameters':parameters},ensure_ascii=False),encoding='utf8')
    result={'kind':'runtime_analysis','operation':operation,'title':definition['title'],
        'artifact_name':parameters['argv'][0] if process else parameters.get('inspector_endpoint') if inspector else parameters.get('serial','Cliente ADB local'),'parameters':parameters,
        'mutates_device':definition['mutates_device'],'source_kind':'runtime-observation',
        'cases':[],'passed':0,'failed':0,
        'limitations':['Inspector observations do not prove source identity, calls or behavioral equivalence.'] if inspector else ['Cancellation stops owned host clients; it does not undo device changes or certify that a device-side operation stopped.']}
    if operation=='browser.scenario':result['limitations']=['The capture records caller-selected commands and notifications, not authenticated source identity or general behavioral equivalence. Cancellation does not undo target effects.']
    if operation=='browser.coverage':result['limitations']=['Precise coverage resets counters and disables optimized execution until stopped. Interrupted recordings do not confirm profiler cleanup; sources and counts are session observations, not authenticated identity or behavioral equivalence.']
    if process:result['limitations']=['The owned program can change its files and communicate with other processes. Cancellation does not restore its effects; only selected observations are retained.']
    manager.store.save_job(project_id,job_id,'queued',result)
    manager.pool.submit(_run,manager,project_id,job_id,folder,result)
    return manager.store.job(job_id)


def _run(manager,project_id,job_id,folder,result):
    output=folder/'analysis.json'
    state='failed'
    try:
        manager.store.save_job(project_id,job_id,'running',result)
        inspector=any(row['name']==result['operation'] for row in inspector_runtime.OPERATIONS)
        process=result['operation']=='process.capture'
        command=[sys.executable,str(Path(__file__).with_name('process_capture.py' if process else 'inspector_runtime.py' if inspector else 'adb_runtime.py')),str(folder/'request.json'),str(output)]
        execution=manager._execute(job_id,command,{'preserve_adb_server':not inspector})
        result['execution']=execution
        with manager.lock:
            stopped=job_id in manager.cancelled
        state='cancelled' if stopped else 'failed' if execution['exit_code'] or not output.is_file() else 'finished'
        retained=(process_capture.latest(folder) or output) if process else (inspector_runtime.latest(folder) or output) if inspector else output if output.is_file() else folder/'partial.json'
        if process and retained.is_file():
            if json.loads(retained.read_bytes())['result']['status']!='complete' and state=='finished':state='failed'
            if state in {'cancelled','failed'}:retained=process_capture.freeze_recording(folder)
        if inspector and state in {'cancelled','failed'} and retained.is_file():
            retained=inspector_runtime.freeze_recording(folder)
        if state=='failed':
            result['error']='Runtime observation did not complete; inspect the retained client diagnostic. Target effects are not undone.'
        if retained.is_file():
            retain(manager.store,project_id,job_id,retained,result)
        with manager.lock:
            if job_id in manager.cancelled: state='cancelled'
    except InterruptedError:
        state='cancelled'
    except Exception as exc:
        result['error']=type(exc).__name__+': '+str(exc)
        state='failed'
    finally:
        for capture in folder.glob('upload-input*'):
            try:
                capture.unlink(missing_ok=True)
            except OSError as exc:
                result['cleanup_error']=str(exc)
                if state=='finished': state='failed'
        with manager.lock:
            manager.cancelled.discard(job_id)
    manager.store.save_job(project_id,job_id,state,result)


def retain(store,project_id,job_id,output,result):
    document=json.loads(output.read_text(encoding='utf8'))
    snapshot=store.add_artifact(project_id,output)
    result.update(artifact_id=snapshot['id'],artifact_sha256=snapshot['sha256'],analysis_sha256=snapshot['sha256'],
        analysis_file=str(output),source_identity=document['result'].get('target'),runtime=document['runtime'],
        observation_status=document['result']['status'],verdict=document['result'].get('verdict'),sections=store.index_analysis(job_id,document['result']))
    if document.get('operation')=='browser.coverage' and 'progress' in document['result']:
        result['progress']=document['result']['progress']
    result['derived_artifacts'],result['unavailable_derived_artifacts']=[],[]
    for row in document['result'].get('artifacts',[]):
        path=Path(row['path'])
        if not path.is_file() or digest(path)!=row['sha256']:
            result['unavailable_derived_artifacts'].append({'path':str(path),'reason':'Collected file is missing or changed since recording'})
            continue
        child=store.add_artifact(project_id,path)
        if child['sha256']!=row['sha256']:
            result['unavailable_derived_artifacts'].append({'path':str(path),'reason':'Collected file changed while reading its identity'})
            continue
        store.link_artifact(project_id,snapshot['id'],child['id'],job_id,row['source_location'])
        result['derived_artifacts'].append({'id':child['id'],'name':row['name'],'sha256':child['sha256']})


def recover(store):
    for project in store.projects():
        for job in store.items('jobs',project['id']):
            result=job['result']
            if job['state']!='interrupted' or result.get('kind')!='runtime_analysis' or result.get('analysis_file'):
                continue
            folder=store.directory/'analyses'/job['id']
            if not (folder/'request.json').is_file(): continue
            inspector=any(row['name']==result.get('operation') for row in inspector_runtime.OPERATIONS)
            process=result.get('operation')=='process.capture'
            available=(process_capture.latest(folder) or folder/'absent') if process else (inspector_runtime.latest(folder) or folder/'absent') if inspector else folder/'analysis.json' if (folder/'analysis.json').is_file() else folder/'partial.json'
            if not available.is_file(): continue
            try:
                raw=inspector_runtime.recording(folder) if inspector else available.read_bytes()
                if raw is None: continue
                if inspector:
                    result['observer_recovery']=inspector_runtime.stop_interrupted_worker(folder,json.loads(raw))
                    raw=inspector_runtime.recording(folder) or raw
                elif process:
                    result['observer_recovery']=process_capture.stop_interrupted_worker(folder)
                    raw=process_capture.freeze_recording(folder).read_bytes()
                json.loads(raw)
                # Freeze a recording even if an orphaned old client writes again.
                retained=folder/'recovered-observation.json'
                retained.write_bytes(raw)
                retain(store,project['id'],job['id'],retained,result)
                result['recovered_recording']=True
            except (OSError,ValueError) as exc:
                result['recovery_error']=str(exc)
            store.save_job(project['id'],job['id'],'interrupted',result)
