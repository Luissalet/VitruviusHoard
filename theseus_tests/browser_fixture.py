"""Owned software-rendered browser and an original loopback-only application."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
from urllib.parse import unquote,urlsplit

import psutil


def browser_path():
    explicit=os.environ.get('THESEUS_TEST_CHROMIUM')
    if explicit:return Path(explicit)
    root=Path(os.environ.get('LOCALAPPDATA',''))/'ms-playwright'
    candidates=sorted(root.glob('chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe'))
    return candidates[-1] if candidates else None


@contextmanager
def browser_fixture(folder,http_port=0,debugging_port=0,rule_limit=128,extra_script=''):
    folder.mkdir(parents=True);application=folder/'application';application.mkdir()
    script=application/'original-ñ.js'
    script.write_bytes(('// original ñ😀\r\nglobalThis.ruleLimit='+str(rule_limit)+';\r\nlet tick=0;function measureOriginal(){document.querySelector("#value").textContent="131";globalThis.lastAction={value:document.querySelector("#entry").value,limit:globalThis.ruleLimit};fetch("/action",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(globalThis.lastAction)});}\r\n'
        'document.querySelector("#measure").addEventListener("click",measureOriginal);\r\n'
        'setInterval(()=>{document.querySelector("#value").dataset.tick=String(++tick);document.querySelector("#value").textContent=String(tick);new Function("return "+tick)();'
        'for(const path of ["/binary","/redirect","/failure","/text"])fetch(path).then(r=>r.arrayBuffer()).catch(()=>{});'
        'fetch("/submit",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({value:tick})}).then(r=>r.json());},300);\r\n'
        '//# sourceMappingURL=original-ñ.js.map\r\n'+extra_script).encode())
    html=application/'index.html';html.write_text('<!doctype html><meta charset="utf-8"><style>#entry{position:absolute;left:20px;top:20px;width:200px}#measure{position:absolute;left:20px;top:60px;width:100px;height:30px}#value{position:absolute;left:140px;top:60px}</style><input id="entry" aria-label="Value"><button id="measure">Measure</button><output id="value">0</output><script src="/original-%C3%B1.js"></script>',encoding='utf8')
    (application/'package.json').write_text(json.dumps({'name':'original-browser-fixture','main':script.name}),encoding='utf8')
    requests=[];posts=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body=self.rfile.read(int(self.headers['Content-Length']));path=unquote(urlsplit(self.path).path);requests.append(path);posts.append({'path':path,'body':body})
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            path=unquote(urlsplit(self.path).path);requests.append(path)
            if path=='/redirect':
                self.send_response(302);self.send_header('Location','/binary');self.send_header('Content-Length','0');self.end_headers();return
            if path=='/failure':
                self.send_response(200);self.send_header('Content-Length','4');self.end_headers();self.wfile.write(b'x');self.wfile.flush();self.close_connection=True;return
            body,kind=(script.read_bytes(),'application/javascript; charset=utf-8') if path=='/'+script.name else (bytes([0,255,13,10]),'application/octet-stream') if path=='/binary' else ('original ñ😀'.encode(),'text/plain; charset=utf-8') if path=='/text' else (html.read_bytes(),'text/html; charset=utf-8')
            self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',http_port),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    url='http://127.0.0.1:'+str(server.server_port)+'/'
    diagnostic=folder/'browser.err.log'
    command=[str(browser_path()),'--disable-gpu','--disable-background-networking','--disable-extensions','--disable-sync','--no-first-run','--no-default-browser-check','--remote-debugging-port='+str(debugging_port),'--remote-debugging-address=127.0.0.1','--user-data-dir='+str(folder/'profile'),'--window-size=800,600',url]
    process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=diagnostic.open('wb'),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    identity=psutil.Process(process.pid);created=identity.create_time();arguments=identity.cmdline()
    try:
        end=time.monotonic()+15
        while True:
            text=diagnostic.read_text(encoding='utf8');match=re.search(r'ws://127\.0\.0\.1:(\d+)/',text)
            if match and '/'+script.name in requests:break
            assert process.poll() is None and time.monotonic()<end,text
            time.sleep(.05)
        yield {'root':application,'script':script,'url':url,'endpoint':'http://127.0.0.1:'+match[1],'process':process,'requests':requests,'posts':posts}
    finally:
        try:
            if process.poll() is None:
                assert identity.is_running() and identity.create_time()==created and identity.cmdline()==arguments
                # Stop the parent first so it cannot replace a terminated utility.
                owned=[identity,*identity.children(recursive=True)]
                cleanup=[{'pid':p.pid,'create_time':p.create_time(),'command':p.cmdline()} for p in owned]
                (folder/'cleanup-processes.json').write_text(json.dumps(cleanup),encoding='utf8')
                closing={'started_epoch':time.time(),'grace_seconds':5,'confirmation_seconds':30,'confirmed':False}
                # This fixture owns the whole browser. Close it gracefully before
                # terminating verified leftovers; production observers never do this.
                close={}
                try:
                    import websocket
                    address=re.search(r'ws://127\.0\.0\.1:\d+/devtools/browser/[A-Za-z0-9-]+',text).group()
                    connection=websocket.create_connection(address,timeout=2,suppress_origin=True,http_no_proxy=['*'])
                    try:connection.send(json.dumps({'id':1,'method':'Browser.close'}));close['sent']=True
                    finally:connection.close()
                except (OSError,ValueError,AttributeError,websocket.WebSocketException) as exc:close['error']=str(exc)
                (folder/'cleanup-close.json').write_text(json.dumps(close),encoding='utf8')
                try:
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        closing['grace_expired']=True
                        # Refresh while the original root is still attached so
                        # a utility created during the grace is also accounted for.
                        if identity.is_running():
                            assert identity.cmdline()==arguments
                            seen={(row['pid'],row['create_time']) for row in cleanup}
                            for child in identity.children(recursive=True):
                                try:
                                    saved={'pid':child.pid,'create_time':child.create_time(),'command':child.cmdline()}
                                except psutil.NoSuchProcess:continue
                                if (saved['pid'],saved['create_time']) not in seen:
                                    owned.append(child);cleanup.append(saved)
                                    seen.add((saved['pid'],saved['create_time']))
                            (folder/'cleanup-processes.json').write_text(json.dumps(cleanup),encoding='utf8')
                        for child,saved in zip(owned,cleanup):
                            try:
                                # is_running checks creation afresh; create_time
                                # alone can return its cached value after PID reuse.
                                if not child.is_running():continue
                                assert child.create_time()==saved['create_time']
                                child.terminate()
                            except psutil.NoSuchProcess:pass
                        # Windows termination can finish after the signal returns.
                        # Confirm through the retained Popen handle, not a new PID.
                        process.wait(timeout=30)
                    live=[child for child in owned[1:] if child.is_running()]
                    _,remaining=psutil.wait_procs(live,timeout=5)
                    identities={row['pid']:row for row in cleanup}
                    for child in remaining:
                        try:
                            if not child.is_running():continue
                            saved=identities[child.pid]
                            assert child.create_time()==saved['create_time']
                            child.terminate()
                        except psutil.NoSuchProcess:pass
                    _,remaining=psutil.wait_procs([child for child in remaining if child.is_running()],timeout=5)
                    assert not remaining,[(p.pid,p.name()) for p in remaining]
                    assert process.poll() is not None
                    closing['confirmed']=True
                finally:
                    closing.update(finished_epoch=time.time(),root_exit_code=process.poll(),identities=cleanup)
                    (folder/'cleanup-result.json').write_text(json.dumps(closing),encoding='utf8')
        finally:server.shutdown();server.server_close()
