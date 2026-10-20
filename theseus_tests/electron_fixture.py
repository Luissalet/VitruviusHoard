"""An original hidden Electron application with independent IPC observations."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import httpx
import psutil


def electron_path():
    explicit=os.environ.get('THESEUS_TEST_ELECTRON')
    path=Path(explicit) if explicit else Path('D:/LocalAI/faustus/desktop/node_modules/electron/dist/electron.exe')
    return path if path.is_file() else None


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


@contextmanager
def electron_fixture(folder,factor=7):
    folder.mkdir(parents=True);source=folder/'application';source.mkdir()
    metadata=folder/'ready.json';oracle=folder/'ipc.jsonl'
    main_port=free_port();renderer_port=free_port()
    while renderer_port==main_port:renderer_port=free_port()
    files={
        'package.json':json.dumps({'name':'original-electron-gauge','version':'1.0.0','main':'main.cjs'}),
        'rule.cjs':"exports.normalize=value=>{if(value==='error')throw new Error('original-ipc-error-ñ');return value<0?0:value*7;};\r\n",
        'preload.cjs':"const {contextBridge,ipcRenderer}=require('electron');contextBridge.exposeInMainWorld('gauge',{read:value=>ipcRenderer.invoke('gauge:read',value)});\r\n",
        'renderer.js':"// Original ñ😀\r\ndocument.querySelector('#read').onclick=async()=>{document.querySelector('#value').textContent=String(await window.gauge.read(3));};\r\n",
        'index.html':'<!doctype html><meta charset="utf-8"><button id="read">Read</button><output id="value">0</output><script src="renderer.js"></script>',
        'main.cjs':"""const {app,BrowserWindow,ipcMain}=require('electron');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {normalize}=require('./rule.cjs');
app.setPath('userData',USER_DATA);app.disableHardwareAcceleration();
ipcMain.handle('gauge:read',(_event,value)=>{
  try{const result=normalize(value);fs.appendFileSync(ORACLE,JSON.stringify({channel:'gauge:read',value,result})+'\\n');return result;}
  catch(error){fs.appendFileSync(ORACLE,JSON.stringify({channel:'gauge:read',value,error:error.message})+'\\n');throw error;}
});
app.whenReady().then(async()=>{
  const win=new BrowserWindow({show:false,width:320,height:240,webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
  await win.loadFile('index.html');
  const server=http.createServer((request,response)=>{
    if(request.url==='/oracle'){response.end(fs.existsSync(ORACLE)?fs.readFileSync(ORACLE):'');return;}
    if(request.url==='/stop'&&request.method==='POST'){response.end('stopping');setImmediate(()=>{server.close();app.quit();});return;}
    response.statusCode=404;response.end();
  });
  server.listen(0,'127.0.0.1',()=>{
    const ready={url:win.webContents.getURL(),oracle_url:'http://127.0.0.1:'+server.address().port,version:process.versions.electron};
    fs.writeFileSync(READY+'.tmp',JSON.stringify(ready));fs.renameSync(READY+'.tmp',READY);
  });
});
""".replace('USER_DATA',json.dumps(str(folder/'profile'))).replace('ORACLE',json.dumps(str(oracle))).replace('READY',json.dumps(str(metadata))),
    }
    files['rule.cjs']=files['rule.cjs'].replace('value*7','value*'+str(factor))
    for name,content in files.items():(source/name).write_bytes(content.encode('utf8'))
    command=[str(electron_path()),f'--inspect=127.0.0.1:{main_port}',f'--remote-debugging-port={renderer_port}',
        '--remote-debugging-address=127.0.0.1','--disable-gpu','--disable-background-networking','--no-first-run',str(source)]
    with (folder/'stdout.log').open('wb') as stdout,(folder/'stderr.log').open('wb') as stderr:
        process=subprocess.Popen(command,cwd=source,env=dict(os.environ,ELECTRON_ENABLE_LOGGING='1'),stdout=stdout,stderr=stderr,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        owner=psutil.Process(process.pid);started=owner.create_time();ready=None
        try:
            deadline=time.monotonic()+30
            while not metadata.is_file():
                assert process.poll() is None and time.monotonic()<deadline,(folder/'stderr.log').read_text(encoding='utf8',errors='replace')
                time.sleep(.05)
            ready=json.loads(metadata.read_text(encoding='utf8'))
            yield {**ready,'root':source,'endpoint':f'http://127.0.0.1:{renderer_port}',
                'main_endpoint':f'http://127.0.0.1:{main_port}','process':process,'oracle':oracle,'files':files}
        finally:
            children=owner.children(recursive=True) if process.poll() is None else []
            identities=[(p,p.create_time(),p.cmdline()) for p in children]
            if process.poll() is None:
                assert owner.create_time()==started and owner.cmdline()==command
                if ready:
                    httpx.post(ready['oracle_url']+'/stop',trust_env=False,timeout=5).raise_for_status()
                    process.wait(timeout=10)
                else:process.terminate();process.wait(timeout=10)
            _,remaining=psutil.wait_procs(children,timeout=5)
            for child,created,args in identities:
                if child in remaining and child.is_running() and child.create_time()==created and child.cmdline()==args:child.terminate()
            _,remaining=psutil.wait_procs([p for p in remaining if p.is_running()],timeout=5)
            assert not remaining,'Owned Electron fixture children did not exit'
