"""Original programs communicate over real loopback HTTP and WebSocket sockets."""
import base64
import socket
import sys

from theseus.process_capture import capture_process
from theseus.process_compare import compare_results


def test_http_binary_body_duplicate_headers_and_response_retained(tmp_path):
    program=tmp_path/'http-original.py'
    program.write_text('''import os,socket,sys
from urllib.parse import urlsplit
url=urlsplit(os.environ['ORIGINAL_SERVICE'])
with socket.create_connection((url.hostname,url.port)) as sock:
    sock.sendall(b'POST '+url.path.encode()+b'/submit?q=%C3%B1 HTTP/1.1\\r\\nHost: original\\r\\nX-Same: first\\r\\nX-Same: second\\r\\nContent-Length: 3\\r\\nConnection: close\\r\\n\\r\\n'+bytes([0,255,7]))
    data=bytearray()
    while True:
        chunk=sock.recv(8192)
        if not chunk:break
        data.extend(chunk)
sys.stdout.buffer.write(bytes(data))
''',encoding='utf8')
    result=capture_process({'argv':[sys.executable,str(program)],'cwd':str(tmp_path),'timeout_seconds':5,
        'services':[{'name':'original','environment_key':'ORIGINAL_SERVICE','http':[{'method':'POST','path':'/submit',
            'response':{'status':201,'data_base64':base64.b64encode(b'answer\x00\xff').decode(),'headers':[['x-same','one'],['x-same','two']]}}]}]},tmp_path/'capture')
    assert result['status']=='complete' and result['services']['closed'],result.get('error',result.get('services'))
    output=base64.b64decode(result['stdout']['base64']);assert output.endswith(b'answer\x00\xff') and output.startswith(b'HTTP/1.1 201')
    events=result['events'];connection=next(row for row in events if row['kind']=='service.connection')
    headers=[(base64.b64decode(a['base64']),base64.b64decode(b['base64'])) for a,b in connection['headers']]
    assert [(a,b) for a,b in headers if a==b'x-same']==[(b'x-same',b'first'),(b'x-same',b'second')]
    assert base64.b64decode(connection['query']['base64'])==b'q=%C3%B1'
    request=next(row for row in events if row['kind']=='http.request');response=next(row for row in events if row['kind']=='http.response')
    assert base64.b64decode(request['body']['base64'])==bytes([0,255,7]) and response['transport_flushed']
    assert {'before':request['id'],'after':response['id'],'basis':'same-observed-channel'} in result['order']['edges']
    from urllib.parse import urlsplit
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',urlsplit(result['services']['bindings']['ORIGINAL_SERVICE']).port))!=0
    assert compare_results(result,result,{'dimensions':['http'],'http_headers':['x-same']})['state']=='same-selected-observations'


def test_websocket_text_binary_messages_and_close_real_client(tmp_path):
    program=tmp_path/'ws-original.py'
    program.write_text('''import os,sys,websocket
url=os.environ['ORIGINAL_SERVICE'].replace('http:','ws:')+'/socket'
ws=websocket.create_connection(url,timeout=3,http_proxy_host=None)
assert ws.recv()=='Ready ñ😀'
ws.send_binary(bytes([0,255,7]))
assert ws.recv()==bytes([255,0,8])
ws.send('completed ñ😀')
assert ws.recv()==''
ws.close()
sys.stdout.buffer.write(b'protocol complete')
''',encoding='utf8')
    result=capture_process({'argv':[sys.executable,str(program)],'cwd':str(tmp_path),'timeout_seconds':7,
        'services':[{'name':'original','environment_key':'ORIGINAL_SERVICE','websocket':[{'path':'/socket','steps':[
            {'kind':'send','text':'Ready ñ😀'},{'kind':'receive','data_base64':base64.b64encode(bytes([0,255,7])).decode()},
            {'kind':'send','data_base64':base64.b64encode(bytes([255,0,8])).decode()},{'kind':'receive','text':'completed ñ😀'},
            {'kind':'close','code':1000}]}]}]},tmp_path/'capture')
    assert result['status']=='complete' and result['process']['exit_code']==0,result.get('services')
    assert base64.b64decode(result['stdout']['base64'])==b'protocol complete'
    events=[row for row in result['events'] if row['kind'].startswith('websocket.')]
    assert [row['kind'] for row in events]==['websocket.accepted','websocket.sent','websocket.received','websocket.sent','websocket.received','websocket.closed']
    assert all(row['declared_content_matches'] for row in events if row['kind']=='websocket.received')
    assert all(row.get('basis')=='same-observed-channel' for row in result['order']['edges'])
    assert compare_results(result,result,{'dimensions':['websocket']})['state']=='same-selected-observations'


def test_declared_command_keeps_unicode_metacharacter_argv_and_binary_streams(tmp_path):
    program=tmp_path/'command-original.py'
    program.write_text('''import subprocess,sys
result=subprocess.run(['scenario_gauge','two words','"quoted"','a&b|c','ñ😀','trailing\\\\'],input=bytes([0,255,7]),capture_output=True)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
raise SystemExit(result.returncode)
''',encoding='utf8')
    result=capture_process({'argv':[sys.executable,str(program)],'cwd':str(tmp_path),'timeout_seconds':10,
        'commands':[{'name':'scenario_gauge','response':{'stdout':{'data_base64':base64.b64encode(b'original\x00\xff').decode()},
            'stderr':{'text':'error ñ😀'},'exit_code':17}}]},tmp_path/'capture')
    assert result['status']=='complete' and result['process']['exit_code']==17,result.get('error',result.get('services'))
    assert base64.b64decode(result['stdout']['base64'])==b'original\x00\xff'
    assert base64.b64decode(result['stderr']['base64'])=='error ñ😀'.encode()
    invocation=next(row for row in result['events'] if row['kind']=='command.invoked')
    assert invocation['argv']==['two words','"quoted"','a&b|c','ñ😀','trailing\\']
    assert base64.b64decode(invocation['stdin']['base64'])==bytes([0,255,7])
    assert invocation['cwd']==str(tmp_path)
    assert result['command_shims'][0]['sha256'] and result['services']['closed']
    assert compare_results(result,result,{'dimensions':['commands']})['state']=='same-selected-observations'


def test_same_stdout_does_not_hide_different_command_arguments(tmp_path):
    program=tmp_path/'command-mutant-original.py'
    program.write_text('import subprocess,sys\nr=subprocess.run(["scenario_gauge",sys.argv[1]],input=b"input",capture_output=True)\nsys.stdout.buffer.write(r.stdout)\n',encoding='utf8')
    configuration={'cwd':str(tmp_path),'timeout_seconds':10,'commands':[{'name':'scenario_gauge','response':{'stdout':{'text':'fixed response'}}}]}
    a=capture_process({**configuration,'argv':[sys.executable,str(program),'original']},tmp_path/'reference-capture')
    b=capture_process({**configuration,'argv':[sys.executable,str(program),'changed-argument']},tmp_path/'candidate-capture')
    assert a['status']==b['status']=='complete'
    assert compare_results(a,b,{'dimensions':['stdout']})['state']=='same-selected-observations'
    result=compare_results(a,b,{'dimensions':['commands']})
    assert result['state']=='different-selected-observations'
    assert result['dimensions'][0]['reference'][0]['argv']==['original']
    assert result['dimensions'][0]['candidate'][0]['argv']==['changed-argument']
