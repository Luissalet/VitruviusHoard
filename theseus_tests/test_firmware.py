import json
import gzip
import os
from pathlib import Path
import subprocess
import sys
import time

from fastapi.testclient import TestClient
import pytest

from firmware_fixture import embedded_streams,archive_image,many_members
from test_portfolio import run
from theseus.api import create_app
from theseus.firmware import engines,sha,recording_file,read_recording,freeze_recording
from theseus.store import identifier


CLIENTS=engines()
real=pytest.mark.skipif(not CLIENTS['binwalk'],reason='Requires installed generic free Binwalk')


def project_artifact(app,tmp_path,content):
    source=tmp_path/'original-firmware.bin';source.write_bytes(content)
    project=app.state.store.create_project('Original firmware fixture')
    return source,project['id'],app.state.store.add_artifact(project['id'],source)


def test_firmware_catalog_reports_actual_required_engine_without_starting_it(tmp_path,monkeypatch):
    monkeypatch.setenv('THESEUS_BINWALK',str(tmp_path/'missing.exe'))
    app=create_app(tmp_path/'data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        rows=[row for row in client.get('/api/analyses/catalog').json()['operations'] if row['name'].startswith('firmware.')]
        assert len(rows)==2 and not any(row['available'] for row in rows)


@real
def test_real_firmware_regions_selected_offsets_entropy_and_regular_extraction(tmp_path,monkeypatch):
    image,ranges=embedded_streams();app=create_app(tmp_path/'data')
    source,pid,artifact=project_artifact(app,tmp_path,image)
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        _,observed=run(client,pid,artifact['id'],'firmware.regions',{'search_all':True,'entropy_window':64})
        assert observed['status']=='observed'
        for expected in ranges:
            row=next(row for row in observed['regions'] if row['name']==expected['name'])
            assert row['offset']==expected['offset'] and row['size']==expected['length']
            assert row['root_file_range']=={'offset':expected['offset'],'length':expected['length']}
        assert sum(row['bytes'] for row in observed['entropy'])==len(image)
        assert all(0<=row['bits_per_byte']<=8 for row in observed['entropy'])
        assert observed['unclassified_ranges'][0]['offset']==0 and observed['unclassified_ranges'][0]['length']==128
        # Native readers remain useful without an optional extra archive decoder.
        monkeypatch.setenv('THESEUS_7ZIP',str(tmp_path/'missing-7zip.exe'))
        job,extracted=run(client,pid,artifact['id'],'firmware.extract',{'search_all':True})
        assert extracted['status']=='observed' and len(extracted['artifacts'])==6
        folder=Path(job['result']['analysis_file']).parent
        bodies=[row for row in extracted['artifacts'] if row.get('archive_entry')]
        assert [(folder/'extracted'/row['relative_path']).read_bytes() for row in bodies]==[row['body'] for row in ranges]
        assert all(row['root_file_range'] is not None for row in extracted['artifacts'] if row.get('classification'))
        assert all(row.get('parent_relative_path') for row in bodies)
        links=app.state.store.artifact_links(pid);assert len(links)==6
        assert len([row for row in links if row['parent_id']==artifact['id']])==3
        assert not (folder/'firmware-input.bin').exists() and source.read_bytes()==image
        sliced,selected=run(client,pid,artifact['id'],'firmware.regions',{'offset':ranges[0]['offset'],'length':ranges[0]['length']})
        assert selected['selection']['offset']==128 and selected['regions'][0]['root_file_range']['offset']==128
        app.state.store.add_finding(pid,artifact['id'],'file bytes128..174','Recorded gzip region','Engine classification, not component authentication')
        imported=app.state.evidence.load(app.state.evidence.export(pid))
        moved=client.get('/api/jobs/'+imported['id_map'][job['id']]+'/analysis.json').json()
        assert moved['result']==extracted and len(app.state.store.artifact_links(imported['project']['id']))==6


@real
@pytest.mark.parametrize('kind',['zip','tar'])
def test_archive_member_names_duplicates_and_links_do_not_become_host_paths(tmp_path,kind):
    app=create_app(tmp_path/'data');source,pid,artifact=project_artifact(app,tmp_path,archive_image(kind))
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        job,result=run(client,pid,artifact['id'],'firmware.extract')
        assert any('link' in row['kind'] for row in result['gaps']),result
        folder=Path(job['result']['analysis_file']).parent/'extracted'
        assert not (tmp_path/'outside').exists()
        assert all(path.is_file() and not path.is_symlink() for path in folder.iterdir())
        entries=[row for row in result['artifacts'] if row.get('archive_entry') and not row.get('partial')]
        if kind=='zip':
            repeated=[row for row in entries if row['archive_entry']['name']=='repeat.bin']
            assert [(folder/row['relative_path']).read_bytes() for row in repeated]==[b'First original',b'Second original']
            assert any(row['archive_entry']['name']=="../outside\nquote'.bin" for row in entries)
        else:assert any(row['archive_entry']['name']=='../outside' for row in entries)


@real
@pytest.mark.skipif(not CLIENTS['seven_zip'],reason='Requires installed optional 7-Zip decoder')
def test_real_7zip_archive_decoding_keeps_each_member_and_hash(tmp_path):
    source_dir=tmp_path/'members';source_dir.mkdir()
    (source_dir/'measure.txt').write_bytes(b'Original 7zip measure128')
    (source_dir/'units.bin').write_bytes(b'Original 7zip units256\x00')
    compressed=tmp_path/'original.7z'
    reply=subprocess.run([CLIENTS['seven_zip'],'a','-t7z',str(compressed),'measure.txt','units.bin'],cwd=source_dir,capture_output=True)
    assert reply.returncode==0,(reply.stdout,reply.stderr)
    app=create_app(tmp_path/'data');source,pid,artifact=project_artifact(app,tmp_path,b'Prefix'.ljust(128,b'\xff')+compressed.read_bytes())
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        job,result=run(client,pid,artifact['id'],'firmware.extract')
        assert result['status']=='observed',result['gaps']
        folder=Path(job['result']['analysis_file']).parent/'extracted'
        members=[row for row in result['artifacts'] if row.get('archive_entry')]
        assert len(members)==2
        for row in members:
            assert (folder/row['relative_path']).read_bytes()==(source_dir/row['archive_entry']['name']).read_bytes()
            assert sha(folder/row['relative_path'])==row['sha256'] and not row['partial']


@real
def test_selected_interval_links_use_original_file_offsets_not_staging_offsets(tmp_path):
    image,ranges=embedded_streams();app=create_app(tmp_path/'data')
    source,pid,artifact=project_artifact(app,tmp_path,image)
    selected=ranges[0]
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        job,result=run(client,pid,artifact['id'],'firmware.extract',{'offset':selected['offset'],'length':selected['length']})
        row=result['artifacts'][0]
        assert row['input_file_range']=={'offset':128,'length':46}
        assert row['root_file_range']==row['input_file_range']
        links=app.state.store.artifact_links(pid)
        assert next(link for link in links if link['parent_id']==artifact['id'])['source_location']=='file bytes 128..174'


@real
def test_interrupted_real_firmware_worker_is_stopped_and_recording_recovered_without_replay(tmp_path,monkeypatch):
    app=create_app(tmp_path/'data');source,pid,artifact=project_artifact(app,tmp_path,many_members())
    job_id=identifier();folder=app.state.store.directory/'analyses'/job_id;folder.mkdir(parents=True)
    request={'operation':'firmware.extract','path':str(source),'parameters':{}}
    (folder/'request.json').write_text(json.dumps(request),encoding='utf8')
    result={'kind':'native_analysis','operation':'firmware.extract','artifact_id':artifact['id'],'artifact_name':artifact['name'],'cases':[]}
    app.state.store.save_job(pid,job_id,'running',result)
    command=[sys.executable,str(Path(__file__).parents[1]/'theseus/structured.py'),str(folder/'request.json'),str(folder/'analysis.json')]
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    deadline=time.monotonic()+30
    try:
        while True:
            if process.poll() is not None:
                stdout,stderr=process.communicate()
                pytest.fail('Worker ended before interruption fixture:\n'+stderr.decode('utf8',errors='replace'))
            assert time.monotonic()<deadline
            try:
                checkpoint=recording_file(folder,folder/'analysis.json')
                if checkpoint is None:time.sleep(.002);continue
                document=json.loads(checkpoint.read_text(encoding='utf8'))
            except FileNotFoundError:time.sleep(.002);continue
            if document['result'].get('in_progress'):break
            time.sleep(.002)
        monkeypatch.setattr(subprocess,'Popen',lambda *a,**kw:pytest.fail('Recovery must not replay or launch another client'))
        recovered=create_app(tmp_path/'data');saved=recovered.state.store.job(job_id)
        process.wait(timeout=10)
        assert saved['state']=='interrupted' and saved['result']['recovered_recording']
        retained=json.loads(Path(saved['result']['analysis_file']).read_text(encoding='utf8'))
        assert retained['result']['orphan_worker_cleanup']['status'] in {'terminated-owned-worker','not-running'}
        assert saved['result']['sections']['regions'] and not (folder/'firmware-input.bin').exists()
        raw=Path(saved['result']['analysis_file']).read_bytes()
        (folder/'analysis.json').write_text('{}')
        assert Path(saved['result']['analysis_file']).read_bytes()==raw
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=10)


def test_interrupted_member_prefix_is_frozen_before_later_writer_changes(tmp_path):
    folder=tmp_path/'analysis';extracted=folder/'extracted';extracted.mkdir(parents=True)
    carved=extracted/'carve.bin';carved.write_bytes(b'Original carved bytes')
    pending=extracted/'pending.bin';pending.write_bytes(b'prefix observed')
    result={'status':'incomplete','artifacts':[{'relative_path':carved.name,'sha256':sha(carved)}],
        'in_progress':{'relative_path':pending.name,'parent_relative_path':carved.name,'entry':{'name':'original member','ordinal':0}},
        'pending_command':['7zip','x','original-carve']}
    output=folder/'analysis.json';output.write_text(json.dumps({'result':result}),encoding='utf8')
    frozen=freeze_recording(folder,output);saved=json.loads(frozen.read_text(encoding='utf8'))['result']
    row=saved['artifacts'][-1];assert row['partial'] and row['parent_relative_path']==carved.name
    pending.write_bytes(b'Later writer changed and extended the member')
    assert (extracted/row['relative_path']).read_bytes()==b'prefix observed'
    assert sha(extracted/row['relative_path'])==row['sha256'] and saved['interrupted_command']==['7zip','x','original-carve']


@real
def test_nested_regions_keep_parent_chain_unknown_root_mapping_and_depth_continuation(tmp_path):
    body=b'Original nested measure128\x00'
    content=b'Nested original'.ljust(128,b'\xff')+gzip.compress(gzip.compress(body,mtime=0),mtime=0)
    app=create_app(tmp_path/'data');source,pid,artifact=project_artifact(app,tmp_path,content)
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        _,limited=run(client,pid,artifact['id'],'firmware.extract',{'max_depth':1})
        assert limited['status']=='partial' and any(row['kind']=='depth-limited' for row in limited['gaps'])
        job,complete=run(client,pid,artifact['id'],'firmware.extract',{'max_depth':None})
        assert complete['status']=='observed'
        folder=Path(job['result']['analysis_file']).parent/'extracted'
        assert (folder/complete['artifacts'][-1]['relative_path']).read_bytes()==body
        nested=next(row for row in complete['regions'] if row['depth']==1)
        assert nested['root_file_range'] is None and nested['parent_relative_path']
        assert complete['coverage']['whole_image_completeness']=='unknown'


@real
def test_real_firmware_cancellation_keeps_completed_recording_and_stops_owned_clients(tmp_path):
    content=many_members()
    app=create_app(tmp_path/'data');source,pid,artifact=project_artifact(app,tmp_path,content)
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        response=client.post('/api/projects/'+pid+'/artifacts/'+artifact['id']+'/analyses',json={'operation':'firmware.extract','parameters':{}})
        response.raise_for_status();job=response.json();folder=app.state.store.directory/'analyses'/job['id']
        deadline=time.monotonic()+30
        while True:
            assert time.monotonic()<deadline
            assert app.state.store.job(job['id'])['state'] in {'queued','running'}
            checkpoint=recording_file(folder,folder/'analysis.json')
            if checkpoint is not None:
                try:document=read_recording(folder,checkpoint)
                except FileNotFoundError:continue
                if document['result'].get('in_progress'):break
            time.sleep(.002)
        app.state.comparisons.cancel(job['id'])
        while app.state.store.job(job['id'])['state'] in {'queued','running'}:
            assert time.monotonic()<deadline;time.sleep(.01)
        saved=app.state.store.job(job['id'])
        assert saved['state']=='cancelled',saved
        assert client.get('/api/jobs/'+job['id']+'/analysis.json').status_code==200
        assert saved['result']['sections']['regions'] and saved['result']['derived_artifacts']
        assert not (folder/'firmware-input.bin').exists() and source.read_bytes()==content
