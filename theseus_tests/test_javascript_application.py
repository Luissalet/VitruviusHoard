import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest

from theseus.api import create_app
from theseus.native_analysis import ENGINE, engine
from test_native_analysis import wait


def test_electron_asar_ast_semantics_and_ipc_without_running_source(tmp_path):
    if not engine()["available"]:
        pytest.skip("Build the native analysis core first")
    source=tmp_path/'source'
    source.mkdir()
    marker=tmp_path/'must-not-exist'
    files={
        'package.json':json.dumps({'name':'local-gauge-fixture','version':'1.0.0','main':'main.cjs'}),
        'main.cjs':"""const {app,BrowserWindow,ipcMain}=require('electron');
const {normalize}=require('./rule.cjs');
ipcMain.handle('gauge:read',(_event,value)=>normalize(value));
function makeWindow(){ const win=new BrowserWindow({webPreferences:{preload:require('node:path').join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false}});win.loadFile('index.html');return win;}
app.whenReady().then(makeWindow);
function decoy(ipcMain){ipcMain.handle('fake:channel',()=>0);}
"""+"require('node:fs').writeFileSync("+json.dumps(str(marker))+",'executed');",
        'rule.cjs':"exports.normalize=function normalize(value){return value<0?0:value*7;};",
        'preload.cjs':"const {contextBridge,ipcRenderer}=require('electron');contextBridge.exposeInMainWorld('gauge',{read:value=>ipcRenderer.invoke('gauge:read',value)});",
        'renderer.js':"document.getElementById('read').onclick=async()=>{document.getElementById('value').textContent=await window.gauge.read(3);};",
        'index.html':'<!doctype html><button id="read">Read</button><output id="value"></output><script src="renderer.js"></script>',
    }
    for name,content in files.items():
        (source/name).write_text(content,encoding='utf-8')
    target=tmp_path/'application.asar'
    script="import {createPackage} from '@electron/asar';await createPackage(process.argv[1],process.argv[2]);"
    subprocess.run([engine()['node'],'--input-type=module','-e',script,str(source),str(target)],cwd=ENGINE,check=True,capture_output=True)
    app=create_app(tmp_path/'data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        project=client.post('/api/projects',json={'name':'Electron static graph'}).json()
        base='/api/projects/'+project['id']
        artifact=client.post(base+'/artifacts',json={'path':str(target)}).json()
        response=client.post(base+'/artifacts/'+artifact['id']+'/analyses',json={'operation':'javascript.application'})
        response.raise_for_status()
        job=wait(client,response.json())
        assert job['state']=='finished',job
        assert not marker.exists()
        document=client.get('/api/jobs/'+job['id']+'/analysis.json').json()['result']
        assert document['statistics']['parsed_javascript_files']==4
        assert document['statistics']['parse_failures']==0
        graph=document['graph']
        assert graph['nodes'] and graph['edges']
        assert len([row for row in graph['nodes'] if row['kind']=='javascript-module'])>=4
        channels=[row for row in graph['nodes'] if row['kind']=='ipc-channel']
        assert len(channels)==1
        assert 'gauge:read' in json.dumps(channels) and 'fake:channel' not in json.dumps(channels)
        assert document['semantic_graph']['nodes'] and document['semantic_graph']['relations']
        assert 'gauge:read' in json.dumps(graph)
        assert 'normalize' in json.dumps(document['semantic_graph'])
        records=client.get('/api/jobs/'+job['id']+'/records/graph.nodes',params={'limit':2}).json()
        assert len(records['records'])==2 and records['has_more']
        header=records['records'][0]
        record=client.get('/api/jobs/'+job['id']+'/records/graph.nodes/'+header['record_key']).json()
        assert record['record'] in graph['nodes']
        assert record['artifact_sha256']==artifact['sha256']
        # Relation order is content-addressed and varies with source locations.
        # The default query excludes candidate edges, so select a resolved edge
        # for this positive traversal rather than whichever hash sorts first.
        dependency=next(row for row in document['semantic_graph']['relations'] if row['resolution']=='resolved')
        # Retained graph queries remain usable after the original archive disappears.
        target.unlink()
        for operation,query in [
            ('javascript.query',{'seed':{'kind':'semantic-node','node_id':dependency['source_node_id']},'direction':'forward-influence'}),
            ('javascript.feature',{'seed':{'kind':'channel','value':'gauge:read'},'direction':'both'}),
        ]:
            response=client.post(base+'/artifacts/'+artifact['id']+'/analyses',json={
                'operation':operation,'parameters':{'source_job_id':job['id'],'query':query}})
            response.raise_for_status()
            derived=wait(client,response.json())
            assert derived['state']=='finished',derived
            assert derived['result']['source_unavailable']
            assert derived['result']['source_analysis_job_id']==job['id']
            assert derived['result']['artifact_sha256']==artifact['sha256']
            result=client.get('/api/jobs/'+derived['id']+'/analysis.json').json()['result']
            if operation=='javascript.query':
                assert result['summary']['total_seed_matches']>0
                assert result['nodes'] and result['relations']
                assert dependency in result['relations']
            else:
                assert result['summary']['matched_seeds']==1
                assert result['summary']['traced_edges']>0
        # A changed saved document cannot silently retain the old receipt identity.
        document_path=Path(job['result']['analysis_file'])
        document_path.write_text(document_path.read_text(encoding='utf-8')+'\n',encoding='utf-8')
        rejected=client.post(base+'/artifacts/'+artifact['id']+'/analyses',json={
            'operation':'javascript.query','parameters':{'source_job_id':job['id'],'query':{'seed':{'kind':'literal','value':7},'direction':'ownership'}}})
        failed=wait(client,rejected.json())
        assert failed['state']=='failed'
        assert 'Retained analysis document changed' in failed['result']['execution']['stderr']
