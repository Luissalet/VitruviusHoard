from pathlib import Path
import stat
import struct
import zipfile

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from test_retained_comparisons import analyze,start,document
from test_native_analysis import wait


def test_saved_directory_inventories_compare_content_and_members_without_originals(tmp_path):
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.post('/api/projects',json={'name':'Inventory versions'}).json()
        artifacts=[];jobs=[]
        for name,changed in [('reference',False),('same',False),('changed',True)]:
            root=tmp_path/name;root.mkdir()
            (root/'rule-ñ😀.js').write_bytes(('exports.limit='+('256' if changed else '128')+';\r\n').encode())
            (root/('added.bin' if changed else 'removed.bin')).write_bytes(b'\x00\xff\r\n')
            (root/'empty').mkdir()
            artifact,job=analyze(client,project,root,'artifact.inventory');artifacts.append(artifact);jobs.append(job)
            for path in root.iterdir():
                if path.is_file():path.unlink()
        for candidate in (1,2):
            job=start(client,project,artifacts[0]['id'],'artifact.compare',{'reference_job_id':jobs[0]['id'],'candidate_job_id':jobs[candidate]['id']})
            result=document(client,job)
            assert [row['analysis_sha256'] for row in result['retained_inputs']]==[jobs[index]['result']['analysis_sha256'] for index in (0,candidate)]
            if candidate==1:
                assert result['status']=='unchanged',result
            else:
                assert result['status']=='changed',result
                changes={row['logical_path']:row for row in result['changes']}
                assert any('rule-ñ😀.js' in path and 'content' in row['dimensions'] for path,row in changes.items()),result
                assert any(row['classification']=='added' and 'added.bin' in path for path,row in changes.items())
                assert any(row['classification']=='removed' and 'removed.bin' in path for path,row in changes.items())
                rows=client.get('/api/jobs/'+job['id']+'/records/changes',params={'query':'rule-'}).json()
                assert rows['total']==1,rows
                record=client.get('/api/jobs/'+job['id']+'/records/changes/'+rows['records'][0]['record_key']).json()
                assert {row['side'] for row in record['sources']}=={'reference','candidate'}
                bundle=client.app.state.evidence.export(project['id']);moved=client.app.state.evidence.load(bundle)
                assert document(client,{'id':moved['id_map'][job['id']]})==result
        saved=Path(jobs[1]['result']['analysis_file']);saved.write_bytes(saved.read_bytes()+b'\n')
        rejected=client.post(f'/api/projects/{project["id"]}/artifacts/{artifacts[0]["id"]}/analyses',json={'operation':'artifact.compare','parameters':{'reference_job_id':jobs[0]['id'],'candidate_job_id':jobs[1]['id']}})
        failure=wait(client,rejected.json())
        assert failure['state']=='failed' and 'Candidate analysis changed' in failure['result']['execution']['stderr']
        saved.write_bytes(saved.read_bytes()[:-1])
        reference=Path(jobs[0]['result']['analysis_file']);reference.write_bytes(reference.read_bytes()+b'\n')
        rejected=client.post(f'/api/projects/{project["id"]}/artifacts/{artifacts[0]["id"]}/analyses',json={'operation':'artifact.compare','parameters':{'reference_job_id':jobs[0]['id'],'candidate_job_id':jobs[1]['id']}})
        failure=wait(client,rejected.json())
        assert failure['state']=='failed' and 'Retained analysis document changed' in failure['result']['execution']['stderr']


@pytest.mark.parametrize('kind',['file','zip-mode','zip-duplicate','zip-encrypted-marker','zip-unreadable'])
def test_saved_inventory_content_metadata_duplicates_and_unreadable_members(tmp_path,kind):
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');project=client.post('/api/projects',json={'name':kind}).json();artifacts=[];jobs=[]
        for index in range(2):
            folder=tmp_path/str(index);folder.mkdir();path=folder/('original.bin' if kind=='file' else 'original.zip')
            if kind=='file':
                path.write_bytes(b'\x00\xff\r\n'*20000+bytes([128 if index==0 else 129]))
            else:
                with zipfile.ZipFile(path,'w') as archive:
                    entry=zipfile.ZipInfo('rule-ñ😀.js',date_time=(2026,10,18,12,0,0));entry.create_system=3
                    entry.external_attr=(stat.S_IFREG|(0o755 if kind=='zip-mode' and index==1 else 0o644))<<16
                    archive.writestr(entry,b'exports.limit=128;\r\n')
                    if kind=='zip-duplicate':
                        duplicate=zipfile.ZipInfo(entry.filename,date_time=entry.date_time);duplicate.create_system=3
                        duplicate.external_attr=entry.external_attr
                        archive.writestr(duplicate,b'exports.limit=256;\r\n')
                if kind=='zip-unreadable':
                    raw=bytearray(path.read_bytes());struct.pack_into('<H',raw,8,99)
                    struct.pack_into('<H',raw,raw.index(b'PK\x01\x02')+10,99);path.write_bytes(raw)
                if kind=='zip-encrypted-marker':
                    # An original metadata-only fixture, not ciphertext or a decryption test.
                    raw=bytearray(path.read_bytes());central=raw.index(b'PK\x01\x02')
                    for offset in (6,central+8):struct.pack_into('<H',raw,offset,struct.unpack_from('<H',raw,offset)[0]|1)
                    path.write_bytes(raw)
            if kind=='zip-unreadable':
                artifact=client.post(f'/api/projects/{project["id"]}/artifacts',json={'path':str(path)}).json()
                reply=client.post(f'/api/projects/{project["id"]}/artifacts/{artifact["id"]}/analyses',json={'operation':'artifact.inventory'})
                job=wait(client,reply.json());assert job['state']=='failed' and 'Compression method not supported' in job['result']['execution']['stderr']
                artifacts.append(artifact);jobs.append(job);continue
            artifact,job=analyze(client,project,path,'artifact.inventory');artifacts.append(artifact);jobs.append(job);path.unlink()
        if kind=='zip-unreadable':
            rejected=client.post(f'/api/projects/{project["id"]}/artifacts/{artifacts[0]["id"]}/analyses',json={'operation':'artifact.compare','parameters':{'reference_job_id':jobs[0]['id'],'candidate_job_id':jobs[1]['id']}})
            assert rejected.status_code==400 and 'completed artifact.inventory' in rejected.text
            return
        compared=start(client,project,artifacts[0]['id'],'artifact.compare',{'reference_job_id':jobs[0]['id'],'candidate_job_id':jobs[1]['id']})
        result=document(client,compared)
        if kind=='file':
            assert result['status']=='changed' and any('content' in row['dimensions'] for row in result['changes']),result
        elif kind=='zip-mode':
            assert result['status']=='changed' and any('executable' in row['dimensions'] for row in result['changes']),result
        else:
            assert result['status'] in {'unknown','truncated'} and result['summary']['unknown']>0,result
            assert result['limitations'],result
        assert len(result['retained_inputs'])==2
        for row in result['retained_inputs']:
            assert row['artifact_sha256']==row['inventory_root_sha256']
        assert all(len(row['evidence_links'])==2 for row in result['changes'])
