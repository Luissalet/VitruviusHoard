"""Original processes, real pipes/PTY and explicit observation boundaries."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import psutil

from theseus.process_capture import capture_process


def test_pipe_capture_preserves_binary_output_input_exit_and_file_effects(tmp_path):
    program=tmp_path/'original.py'
    program.write_text('import sys\nfrom pathlib import Path\ndata=sys.stdin.buffer.read()\nPath("effect.bin").write_bytes(data)\nsys.stdout.buffer.write(bytes([0,255,13,10])+data)\nsys.stderr.buffer.write("ñ😀".encode())\nraise SystemExit(7)\n',encoding='utf8')
    original=program.read_bytes();input_bytes=b'128\x00\xff\n'
    result=capture_process({'argv':[sys.executable,str(program)],'cwd':str(tmp_path),'mode':'pipes',
        'steps':[{'kind':'input','data_base64':base64.b64encode(input_bytes).decode()}, {'kind':'close_stdin'}],
        'timeout_seconds':5,'files':[{'label':'effect','path':'effect.bin'}]},tmp_path/'capture')
    assert result['status']=='complete' and result['process']['exit_code']==7
    assert base64.b64decode(result['stdout']['base64'])==bytes([0,255,13,10])+input_bytes
    assert base64.b64decode(result['stderr']['base64'])=='ñ😀'.encode()
    assert result['files'][0]['before']['state']=='absent'
    assert result['files'][0]['after']['sha256']==hashlib.sha256(input_bytes).hexdigest()
    assert result['files'][0]['after']['base64']==base64.b64encode(input_bytes).decode()
    assert result['process']['files'][str(program.resolve())]==hashlib.sha256(original).hexdigest()
    assert program.read_bytes()==original
    assert all(event['channel'] and 'channel_sequence' in event for event in result['events'])
    assert result['order']['global_collection_order_is_causality'] is False


def test_real_terminal_interaction_and_rendering(tmp_path):
    program=tmp_path/'original-terminal.py'
    program.write_text('import sys\nprint("\\x1b[2J\\x1b[HReady ñ😀> ",end="",flush=True)\nvalue=input()\nprint("\\x1b[2J\\x1b[HResult="+str(int(value)*7),flush=True)\n',encoding='utf8')
    result=capture_process({'argv':[sys.executable,str(program)],'cwd':str(tmp_path),'mode':'pty',
        'terminal':{'columns':40,'rows':8,'scrollback':20},'timeout_seconds':5,
        'steps':[{'kind':'wait_output','text':'Ready ñ😀>'}, {'kind':'input','text':'3\r'}]},tmp_path/'capture')
    assert result['process']['exit_code']==0
    assert result['status']=='complete' and result['stream_complete'],result['termination']
    assert 'Ready ñ😀>' in result['terminal']['raw_text'] and 'Result=21' in result['terminal']['raw_text']
    rendered=result['terminal']['rendered']
    assert rendered['engine']['name']=='xterm-headless' and rendered['engine']['version']=='6.0.0'
    assert rendered['final']['lines'][0]=='Result=21'
    assert rendered['frames'] and rendered['final']['columns']==40
    assert all(step['state']=='dispatched' for step in result['steps'])


def test_timeout_keeps_prefix_and_stops_only_owned_program(tmp_path):
    program=tmp_path/'original-wait.py'
    program.write_text('import time\nprint("prefix ñ😀",flush=True)\ntime.sleep(60)\n',encoding='utf8')
    result=capture_process({'argv':[sys.executable,str(program)],'cwd':str(tmp_path),'mode':'pipes',
        'timeout_seconds':.4,'environment':{'PYTHONIOENCODING':'utf-8'},'steps':[]},tmp_path/'capture')
    assert result['status']=='partial' and result['termination']['reason']=='explicit-timeout'
    assert base64.b64decode(result['stdout']['base64'])=='prefix ñ😀\r\n'.encode()
    assert result['termination']['owned_process_stopped']
    assert (tmp_path/'capture'/'analysis.json').is_file()
    assert result['limitations']


def test_unread_large_input_does_not_block_the_explicit_timeout(tmp_path):
    program=tmp_path/'unread-original.py'
    program.write_text('import time\ntime.sleep(60)\n',encoding='utf8')
    started=time.monotonic()
    result=capture_process({'argv':[sys.executable,str(program)],'cwd':str(tmp_path),'mode':'pipes',
        'timeout_seconds':.3,'steps':[{'kind':'input','text':'x'*1000000}]},tmp_path/'capture')
    assert time.monotonic()-started<5
    assert result['status']=='partial' and result['termination']['reason']=='explicit-timeout'
    assert result['steps'][0]['state']=='partial' and result['steps'][0]['accepted_bytes']<1000000
    assert result['steps'][0]['input_writer_closed']


def test_recursive_file_observations_keep_original_bytes_and_exclude_observer(tmp_path):
    program=tmp_path/'file-original.py';source=tmp_path/'nested';source.mkdir()
    (source/'before.bin').write_bytes(b'old');(source/'removed.bin').write_bytes(b'remove')
    program.write_text('from pathlib import Path\nPath("nested/before.bin").write_bytes(b"new\\x00\\xff")\nPath("nested/removed.bin").unlink()\nPath("nested/new.bin").write_bytes(b"created")\n',encoding='utf8')
    result=capture_process({'argv':[sys.executable,str(program)],'cwd':str(tmp_path),'mode':'pipes','timeout_seconds':5,
        'steps':[],'files':[{'label':'workspace','path':'.'}]},tmp_path/'capture')
    assert result['status']=='complete'
    before=result['files'][0]['before'];after=result['files'][0]['after']
    assert next(row for row in after['members'] if row['name']=='capture')['state']=='observer-directory-excluded'
    contents=next(row for row in after['members'] if row['name']=='nested')['members']
    assert [row['name'] for row in contents]==['before.bin','new.bin']
    assert base64.b64decode(contents[0]['base64'])==b'new\x00\xff'
    old=next(row for row in before['members'] if row['name']=='nested')['members']
    assert base64.b64decode(old[0]['base64'])==b'old'


def test_runtime_process_capture_is_native_and_transfers_without_a_live_process(tmp_path):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from test_native_analysis import wait
    program=tmp_path/'api-original.py'
    program.write_text('import sys\nsys.stdout.buffer.write(b"original\\x00\\xff")\n',encoding='utf8')
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.app.state.store.create_project('Native process observation')['id']
        catalog=client.post('/api/agent/call',json={'tool':'theseus_runtime_catalog'}).json()['result']
        assert any(row['name']=='process.capture' for row in catalog['operations'])
        response=client.post('/api/agent/call',json={'tool':'theseus_runtime_start','arguments':{
            'project_id':project,'operation':'process.capture','parameters':{'argv':[sys.executable,str(program)],
                'cwd':str(tmp_path),'mode':'pipes','timeout_seconds':5,'steps':[]}}})
        response.raise_for_status();job=wait(client,response.json()['result']);assert job['state']=='finished',job
        document=client.get('/api/jobs/'+job['id']+'/analysis.json').json()
        assert base64.b64decode(document['result']['stdout']['base64'])==b'original\x00\xff'
        imported=client.app.state.evidence.load(client.app.state.evidence.export(project))
        program.unlink()
        actual=client.get('/api/jobs/'+imported['id_map'][job['id']]+'/analysis.json').json()
        assert actual==document
        assert not client.get('/api/projects/'+imported['project']['id']).json()['runtime_sessions']


def test_compare_transferred_process_captures_runs_without_original_paths(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from test_native_analysis import wait
    program=tmp_path/'two-original.py';program.write_text('import sys\nsys.stdout.buffer.write(b"original\\x00\\xff")\n',encoding='utf8')
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.app.state.store.create_project('Transferred process comparison')['id']
        jobs=[]
        for _ in range(2):
            response=client.post('/api/agent/call',json={'tool':'theseus_runtime_start','arguments':{
                'project_id':project,'operation':'process.capture','parameters':{'argv':[sys.executable,str(program)],
                    'cwd':str(tmp_path),'mode':'pipes','timeout_seconds':5,'steps':[]}}})
            response.raise_for_status();job=wait(client,response.json()['result']);assert job['state']=='finished';jobs.append(job)
        loaded=client.app.state.evidence.load(client.app.state.evidence.export(project));program.unlink()
        moved=[client.app.state.store.job(loaded['id_map'][job['id']]) for job in jobs]
        old_paths={Path(job['result']['analysis_file']) for job in jobs}
        exists=Path.exists;calls=[]
        def guarded(path):
            if path in old_paths:calls.append(str(path));raise AssertionError('Original capture path was queried')
            return exists(path)
        monkeypatch.setattr(Path,'exists',guarded)
        response=client.post('/api/agent/call',json={'tool':'theseus_analysis_start','arguments':{
            'project_id':loaded['project']['id'],'artifact_id':moved[0]['result']['artifact_id'],'operation':'process.compare',
            'parameters':{'reference_job_id':moved[0]['id'],'candidate_job_id':moved[1]['id'],
                'query':{'dimensions':['stdout','stderr','exit','files']}}}})
        response.raise_for_status();compared=wait(client,response.json()['result']);assert compared['state']=='finished',compared
        document=client.get('/api/jobs/'+compared['id']+'/analysis.json').json()['result']
        assert document['state']=='same-selected-observations' and calls==[]
        assert compared['result']['original_source_check']=='not-performed-retained-input'
        assert not client.get('/api/projects/'+loaded['project']['id']).json()['runtime_sessions']


def test_job_tracks_child_after_fast_parent_exit_and_waits_for_file_effect(tmp_path):
    program=tmp_path/'parent-original.py'
    program.write_text('import subprocess,sys\nsubprocess.Popen([sys.executable,"-c",\'import time;from pathlib import Path;time.sleep(.25);Path("child-effect.bin").write_bytes(b"complete")\'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW)\n',encoding='utf8')
    result=capture_process({'argv':[sys.executable,str(program)],'cwd':str(tmp_path),'timeout_seconds':5,
        'files':[{'label':'child-effect','path':'child-effect.bin'}]},tmp_path/'capture')
    assert result['status']=='complete' and result['process']['job_accounting']['active_processes']==0
    assert result['process']['job_accounting']['total_processes']>=2
    assert base64.b64decode(result['files'][0]['after']['base64'])==b'complete'


def test_job_stops_child_when_parent_has_already_exited(tmp_path):
    program=tmp_path/'parent-exits-original.py'
    program.write_text('import subprocess,sys\nsubprocess.Popen([sys.executable,"-c",\'import time;time.sleep(60)\'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW)\n',encoding='utf8')
    result=capture_process({'argv':[sys.executable,str(program)],'cwd':str(tmp_path),'timeout_seconds':.35},tmp_path/'capture')
    assert result['status']=='partial' and result['termination']['reason']=='explicit-timeout'
    assert result['termination']['owned_process_stopped']
    assert result['process']['job_accounting']['active_processes']==0


def test_terminal_resize_and_interrupt_preserve_program_handler_and_frames(tmp_path):
    program=tmp_path/'resize-interrupt-original.py'
    # Windows screen-buffer dimensions belong to stdout, not the input handle.
    program.write_text('import os,signal,time\ndef stop(*args):\n print("\\x1b[2J\\x1b[HHandled",flush=True)\n raise SystemExit(23)\nsignal.signal(signal.SIGINT,stop)\nprint("Ready",flush=True)\ninput()\nprint("Size="+str(os.get_terminal_size(1).columns),flush=True)\ntime.sleep(60)\n',encoding='utf8')
    result=capture_process({'argv':[sys.executable,str(program)],'cwd':str(tmp_path),'mode':'pty','timeout_seconds':5,
        'steps':[{'kind':'wait_output','text':'Ready'},{'kind':'resize','columns':60,'rows':10},{'kind':'input','text':'\r'},
            {'kind':'wait_output','text':'Size=60'},{'kind':'signal','signal':'interrupt'}]},tmp_path/'capture')
    assert result['status']=='complete' and result['process']['exit_code']==23,result.get('error',result['termination'])
    rendered=result['terminal']['rendered'];assert rendered['final']['columns']==60 and rendered['final']['rows']==10
    assert rendered['final']['lines'][0]=='Handled'
    assert any(frame['columns']==60 for frame in rendered['frames'])
    assert result['steps'][-1]['mechanism'].startswith('ConPTY input ETX')


def test_large_binary_pipe_output_has_no_lost_tail(tmp_path):
    program=tmp_path/'large-original.py'
    program.write_text('import sys\nsys.stdout.buffer.write(bytes(range(256))*12289)\nsys.stderr.buffer.write(b"last-block\\x00\\xff")\nraise SystemExit(9)\n',encoding='utf8')
    result=capture_process({'argv':[sys.executable,str(program)],'cwd':str(tmp_path),'timeout_seconds':5},tmp_path/'capture')
    assert result['status']=='complete' and result['process']['exit_code']==9
    assert base64.b64decode(result['stdout']['base64'])==bytes(range(256))*12289
    assert base64.b64decode(result['stderr']['base64'])==b'last-block\x00\xff'


def test_native_cancel_retains_prefix_and_never_replays_target(tmp_path):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    from test_native_analysis import wait
    program=tmp_path/'cancel-original.py'
    program.write_text('from pathlib import Path\nimport time\np=Path("counter.txt")\np.write_text(str(int(p.read_text())+1) if p.exists() else "1")\nprint("original-prefix",flush=True)\ntime.sleep(60)\n',encoding='utf8')
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.app.state.store.create_project('Cancelled original')['id']
        reply=client.post('/api/agent/call',json={'tool':'theseus_runtime_start','arguments':{'project_id':project,'operation':'process.capture',
            'parameters':{'argv':[sys.executable,str(program)],'cwd':str(tmp_path)}}})
        reply.raise_for_status();job=reply.json()['result'];prefix=tmp_path/'data'/'analyses'/job['id']/'capture-latest.json'
        deadline=time.monotonic()+5
        while True:
            if prefix.is_file():
                data=json.loads(prefix.read_bytes())
                if base64.b64decode(data['result']['stdout']['base64']).startswith(b'original-prefix'):break
            assert time.monotonic()<deadline;time.sleep(.01)
        target=data['result']['process'];identity=psutil.Process(target['pid']).create_time()
        cancelled=client.post('/api/jobs/'+job['id']+'/cancel');cancelled.raise_for_status()
        deadline=time.monotonic()+8
        while job['state'] in {'queued','running'}:
            assert time.monotonic()<deadline;time.sleep(.02);job=client.app.state.store.job(job['id'])
        assert job['state']=='cancelled' and job['result']['analysis_sha256']
        kept=client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']
        assert kept['status']=='partial' and not kept['stream_complete']
        assert base64.b64decode(kept['stdout']['base64']).startswith(b'original-prefix')
        assert (tmp_path/'counter.txt').read_text()=='1'
        assert not psutil.pid_exists(target['pid']) or psutil.Process(target['pid']).create_time()!=identity


def test_recovery_stops_bound_old_observer_and_freezes_prefix_once(tmp_path):
    from theseus.store import Store,identifier
    from theseus import runtime,process_capture
    store=Store(tmp_path/'data');pid=store.create_project('Interrupted observer')['id'];key=identifier()
    folder=store.directory/'analyses'/key;folder.mkdir(parents=True)
    program=tmp_path/'recovery-original.py'
    program.write_text('from pathlib import Path\nimport time\nPath("started.txt").write_text("once")\nprint("saved-prefix",flush=True)\ntime.sleep(60)\n',encoding='utf8')
    request={'operation':'process.capture','parameters':{'argv':[sys.executable,str(program)],'cwd':str(tmp_path)}}
    request_path=folder/'request.json';request_path.write_text(json.dumps(request),encoding='utf8')
    command=[sys.executable,str(Path(process_capture.__file__).resolve()),str(request_path),str(folder/'analysis.json')]
    worker=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline=time.monotonic()+5
        while True:
            path=folder/'capture-latest.json'
            if path.is_file() and b'saved-prefix' in base64.b64decode(json.loads(path.read_bytes())['result']['stdout']['base64']):break
            assert worker.poll() is None and time.monotonic()<deadline;time.sleep(.01)
        store.save_job(pid,key,'interrupted',{'kind':'runtime_analysis','operation':'process.capture','parameters':request['parameters']})
        runtime.recover(store);job=store.job(key)
        assert job['state']=='interrupted' and job['result']['recovered_recording']
        assert job['result']['observer_recovery']['owned_process_stopped']
        raw=Path(job['result']['analysis_file']).read_bytes();assert hashlib.sha256(raw).hexdigest()==job['result']['analysis_sha256']
        assert json.loads(raw)['result']['status']=='partial'
        assert worker.wait(timeout=5) is not None
        runtime.recover(store);assert Path(job['result']['analysis_file']).read_bytes()==raw
        assert (tmp_path/'started.txt').read_text()=='once'
    finally:
        if worker.poll() is None:
            process_capture.stop_interrupted_worker(folder);worker.wait(timeout=5)
