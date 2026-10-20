"""Original loopback message oracle, independent of the product collector."""
import base64
from contextlib import contextmanager
import threading

from websockets.sync.server import serve


@contextmanager
def websocket_fixture():
    rows=[];guard=threading.Lock()
    def handle(connection):
        with guard:
            ordinal=sum(row['kind']=='opened' for row in rows)
            rows.append({'kind':'opened','connection':ordinal,'path':connection.request.path})
        try:
            for value in connection:
                with guard:rows.append({'kind':'received','connection':ordinal,
                    'type':'text' if isinstance(value,str) else 'binary',
                    'value':value if isinstance(value,str) else base64.b64encode(value).decode()})
                connection.send(['echo:',value] if isinstance(value,str) else [value[:2],value[2:]])
        finally:
            with guard:rows.append({'kind':'closed','connection':ordinal})
    with serve(handle,'127.0.0.1',0,compression=None,ping_interval=None,close_timeout=3) as server:
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:yield {'url':'ws://127.0.0.1:'+str(server.socket.getsockname()[1])+'/same','oracle':rows}
        finally:
            server.shutdown();thread.join(timeout=5)
            assert not thread.is_alive()


def expression(url,order):
    import json
    return '''(async()=>{const output=[];for(const label of ORDER){
const s=new WebSocket(URL);s.binaryType='arraybuffer';
await new Promise((ok,no)=>{s.onopen=ok;s.onerror=no});
for(const value of [label+'ñ😀',new Uint8Array([0,255,1,128])]){
const reply=new Promise((ok,no)=>{s.onmessage=e=>ok(typeof e.data==='string'?e.data:Array.from(new Uint8Array(e.data)));s.onerror=no});
s.send(value);output.push(await reply)}
const closed=new Promise(ok=>s.onclose=ok);s.close();await closed}
return output})()'''.replace('URL',json.dumps(url)).replace('ORDER',json.dumps(order))
