"""Owned loopback HTTP and WebSocket scenario services with ASGI observations."""
import asyncio
import base64
from contextlib import contextmanager
import hashlib
import json
import queue
import socket
import threading
import time
import uuid

import uvicorn

TEXT={'type':'string'}
CONTENT={'text':TEXT,'data_base64':TEXT}
HEADERS={'type':'array','items':{'type':'array','minItems':2,'maxItems':2,'items':TEXT}}
WS_STEP={'type':'object','additionalProperties':False,'required':['kind'],'properties':{
    'kind':{'enum':['send','receive','close']},**CONTENT,'code':{'type':'integer','minimum':1000,'maximum':4999}},
    'allOf':[{'if':{'properties':{'kind':{'const':'send'}}},'then':{'oneOf':[{'required':['text']},{'required':['data_base64']}]}}]}
SERVICES={'type':'array','items':{'type':'object','additionalProperties':False,'required':['name','environment_key'],
    'properties':{'name':{'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_-]*$'},
        'environment_key':{'type':'string','pattern':'^[A-Za-z_][A-Za-z0-9_]*$'},
        'http':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['path','method','response'],
            'properties':{'path':TEXT,'method':TEXT,'response':{'type':'object','additionalProperties':False,
                'properties':{'status':{'type':'integer','minimum':200,'maximum':599},'headers':HEADERS,**CONTENT},
                'oneOf':[{'required':['text']},{'required':['data_base64']}]}}}},
        'websocket':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['path','steps'],
            'properties':{'path':TEXT,'subprotocol':TEXT,'steps':{'type':'array','items':WS_STEP}}}}}}}


def blob(data):return {'base64':base64.b64encode(data).decode(),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
def content(value):return base64.b64decode(value['data_base64'],validate=True) if 'data_base64' in value else value.get('text','').encode('utf8')


class ScenarioServices:
    def __init__(self,definitions,commands=None):
        names=[row['name'] for row in definitions];keys=[row['environment_key'].upper() for row in definitions]
        if len(set(names))!=len(names) or len(set(keys))!=len(keys):raise ValueError('Service names and environment keys must be unique')
        for service in definitions:
            http=[(row['method'],row['path']) for row in service.get('http',[])]
            ws=[row['path'] for row in service.get('websocket',[])]
            if len(set(http))!=len(http) or len(set(ws))!=len(ws):raise ValueError('Service routes must be unambiguous')
            for row in service.get('http',[]):
                content(row['response'])
                for key,value in row['response'].get('headers',[]):
                    if any(char in key+value for char in '\r\n'):raise ValueError('HTTP headers cannot contain line delimiters')
                    key.encode('ascii');value.encode('latin1')
            for row in service.get('websocket',[]):
                for step in row['steps']:content(step)
        self.commands={row['name'].casefold():row for row in commands or []}
        for row in self.commands.values():
            for stream in ('stdout','stderr'):content(row['response'].get(stream,{}))
        self.command_prefix='/commands/'+uuid.uuid4().hex
        self.definitions={row['name']:row for row in definitions};self.queue=queue.Queue();self.errors=[];self.serial=0;self.closed=False
        self.socket=socket.socket(socket.AF_INET,socket.SOCK_STREAM);self.socket.bind(('127.0.0.1',0));self.port=self.socket.getsockname()[1]
        self.environment={row['environment_key']:f'http://127.0.0.1:{self.port}/services/{row["name"]}' for row in definitions}
        if self.commands:self.environment['VITRUVIUS_CAPTURE_COMMAND_URL']=f'http://127.0.0.1:{self.port}'+self.command_prefix
        class PrivateServer(uvicorn.Server):
            @contextmanager
            def capture_signals(self):yield
        self.server=PrivateServer(uvicorn.Config(self.application,interface='asgi3',host='127.0.0.1',port=self.port,log_config=None,
            access_log=False,log_level='critical',lifespan='off',server_header=False,date_header=False,
            ws='websockets-sansio',ws_max_size=None,ws_ping_interval=None,timeout_graceful_shutdown=2))
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
        deadline=time.monotonic()+10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic()>deadline:
                self.close();raise RuntimeError('Private scenario service failed to start: '+str(self.errors))
            time.sleep(.005)

    def run(self):
        try:asyncio.run(self.server.serve(sockets=[self.socket]))
        except BaseException as error:self.errors.append(type(error).__name__+': '+str(error))

    def emit(self,channel,kind,**payload):
        self.queue.put({'channel':channel,'kind':kind,'observed_monotonic':time.monotonic(),**payload})

    def read(self):
        rows=[]
        while True:
            try:rows.append(self.queue.get_nowait())
            except queue.Empty:return rows

    async def application(self,scope,receive,send):
        try:await self.handle(scope,receive,send)
        except Exception as error:
            self.errors.append(type(error).__name__+': '+str(error))
            self.emit('service-errors','service.error',error=str(error));raise

    async def handle(self,scope,receive,send):
        self.serial+=1;channel='service:'+str(self.serial)
        path=scope['path'].split('/',3)
        service=self.definitions.get(path[2]) if len(path)>2 and path[1]=='services' else None
        relative='/'+path[3] if len(path)>3 else '/'
        name=service['name'] if service else None
        self.emit(channel,'service.connection',service=name,protocol=scope['type'],path=relative,
            raw_path=blob(scope.get('raw_path',b'')),query=blob(scope['query_string']),
            headers=[[blob(key),blob(value)] for key,value in scope['headers']],
            client=scope.get('client'),http_version=scope.get('http_version'))
        try:
            if scope['type']=='http':
                body=bytearray()
                while True:
                    message=await receive()
                    if message['type']=='http.disconnect':
                        self.emit(channel,'http.disconnected',body=blob(bytes(body)));return
                    chunk=message.get('body',b'');body.extend(chunk)
                    self.emit(channel,'http.request-body',body=blob(chunk),more_body=message.get('more_body',False))
                    if not message.get('more_body',False):break
                if scope['path'].startswith(self.command_prefix+'/'):
                    await self.command(scope,bytes(body),channel,send);return
                routes=[row for row in (service or {}).get('http',[]) if row['path']==relative and row['method']==scope['method']]
                response=routes[0]['response'] if routes else {'status':404,'text':'No declared route'}
                data=content(response);status=response.get('status',200)
                headers=[(key.lower().encode('ascii'),value.encode('latin1')) for key,value in response.get('headers',[])]
                if not any(key==b'content-length' for key,_ in headers):headers.append((b'content-length',str(len(data)).encode()))
                self.emit(channel,'http.request',service=name,method=scope['method'],path=relative,body=blob(bytes(body)),matched=bool(routes))
                await send({'type':'http.response.start','status':status,'headers':headers})
                await send({'type':'http.response.body','body':data})
                self.emit(channel,'http.response',service=name,status=status,headers=[[blob(key),blob(value)] for key,value in headers],body=blob(data),transport_flushed=True)
            elif scope['type']=='websocket':
                routes=[row for row in (service or {}).get('websocket',[]) if row['path']==relative]
                first=await receive()
                if first['type']!='websocket.connect':raise ValueError('Missing WebSocket connect event')
                if not routes:
                    await send({'type':'websocket.close','code':1008});self.emit(channel,'websocket.rejected',service=name);return
                route=routes[0];await send({'type':'websocket.accept','subprotocol':route.get('subprotocol')})
                self.emit(channel,'websocket.accepted',service=name,subprotocol=route.get('subprotocol'))
                for index,step in enumerate(route['steps']):
                    if step['kind']=='send':
                        binary='data_base64' in step;data=content(step)
                        await send({'type':'websocket.send',**({'bytes':data} if binary else {'text':step['text']})})
                        self.emit(channel,'websocket.sent',service=name,step=index,representation='binary' if binary else 'utf8-text',body=blob(data))
                    elif step['kind']=='receive':
                        message=await receive()
                        if message['type']=='websocket.disconnect':
                            self.emit(channel,'websocket.disconnected',service=name,code=message['code'],step=index)
                            self.errors.append('WebSocket disconnected before the declared receive step');return
                        binary=message.get('bytes') is not None;data=message['bytes'] if binary else message.get('text','').encode('utf8')
                        expected=content(step) if any(key in step for key in CONTENT) else None
                        self.emit(channel,'websocket.received',service=name,step=index,representation='binary' if binary else 'utf8-text',body=blob(data),
                            declared_content_matches=None if expected is None else expected==data)
                    else:
                        await send({'type':'websocket.close','code':step.get('code',1000)})
                        self.emit(channel,'websocket.closed',service=name,step=index,code=step.get('code',1000));return
                await send({'type':'websocket.close','code':1000});self.emit(channel,'websocket.closed',service=name,code=1000)
        except Exception as error:
            self.errors.append(type(error).__name__+': '+str(error));self.emit(channel,'service.error',service=name,error=str(error))

    async def command(self,scope,body,channel,send):
        value=json.loads(body);name=scope['path'][len(self.command_prefix)+1:].casefold()
        if name not in self.commands or value.get('name','').casefold()!=name:raise ValueError('Unknown declared command')
        if not isinstance(value.get('argv'),list) or not all(isinstance(arg,str) for arg in value['argv']) or not isinstance(value.get('cwd'),str):
            raise ValueError('Command invocation identity is malformed')
        stdin=base64.b64decode(value['stdin_base64'],validate=True)
        self.emit(channel,'command.invoked',command=self.commands[name]['name'],argv=value['argv'],cwd=value['cwd'],stdin=blob(stdin))
        response=self.commands[name]['response'];stdout=content(response.get('stdout',{}));stderr=content(response.get('stderr',{}))
        reply={'stdout_base64':base64.b64encode(stdout).decode(),'stderr_base64':base64.b64encode(stderr).decode(),'exit_code':response.get('exit_code',0)}
        raw=json.dumps(reply).encode()
        await send({'type':'http.response.start','status':200,'headers':[(b'content-type',b'application/json'),(b'content-length',str(len(raw)).encode())]})
        await send({'type':'http.response.body','body':raw})
        self.emit(channel,'command.response-sent',command=self.commands[name]['name'],stdout=blob(stdout),stderr=blob(stderr),exit_code=reply['exit_code'],
            interpretation='Configured shim response delivered; this is not an execution of the original external command')

    def close(self):
        if self.closed:return
        self.closed=True;self.server.should_exit=True;self.thread.join(timeout=6)
        if self.thread.is_alive():self.server.force_exit=True;self.thread.join(timeout=3)
        self.socket.close()
        if self.thread.is_alive():self.errors.append('Private scenario service thread did not close')
