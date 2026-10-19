"""Product-owned Android observations with explicit device selection and raw receipts."""
import base64
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import time

if __package__:
    from .signals import sha
else:
    from signals import sha


def engine():
    configured=os.environ.get('THESEUS_ADB')
    candidates=[configured] if configured else [shutil.which('adb'),str(Path.home()/'AppData/Local/Android/Sdk/platform-tools/adb.exe')]
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()),None)


S={'type':'string','minLength':1}
ABSOLUTE={'type':'string','minLength':1,'pattern':'^/'}
PACKAGE={'type':'string','pattern':r'^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$'}
SERIAL={'serial':S}
PAGE={'query':{'type':'string'},'offset':{'type':'integer','minimum':0},'limit':{'type':['integer','null'],'minimum':0}}
EXTRA={'type':'object','additionalProperties':False,'required':['name','type','value'],
    'properties':{'name':S,'type':{'enum':['string','boolean','int','long','float']},'value':{'type':['string','boolean','integer','number']}}}
OPERATIONS=[]
def operation(name,title,description,properties=None,required=None,mutates=False,device=True):
    OPERATIONS.append({'name':'adb.'+name,'title':'Android · '+title,'description':description,'mutates_device':mutates,
        'inputSchema':{'type':'object','additionalProperties':False,'properties':{**(SERIAL if device else {}),**(properties or {})},
            'required':(['serial'] if device else [])+(required or [])}})

operation('client','Cliente instalado','Ruta, hash y versión del cliente ADB. No conecta con dispositivos ni arranca el servidor.',device=False)
operation('devices','Dispositivos conectados','Lista seriales, estado y metadatos declarados por ADB. Puede iniciar su servidor local; no modifica dispositivos.',device=False)
operation('device','Identidad del dispositivo','Propiedades de compilación, versión, SDK, ABI y tipo declarado del dispositivo seleccionado.')
operation('packages','Paquetes instalados','Paquetes y rutas APK del dispositivo. Las rutas son remotas, no archivos locales.',{**PAGE,'scope':{'enum':['all','third-party','system']}})
operation('package','Datos de un paquete','Salida completa dumpsys package con versión, UID, instalador y marcas declaradas; campos no reconocidos permanecen desconocidos.',{'package_name':PACKAGE},['package_name'])
operation('pull_package','Recoger APK y splits','Recoge base y todos los APK divididos que declara pm path en un directorio nuevo, con hashes y errores por archivo.',{'package_name':PACKAGE,'output_directory':S},['package_name'])
operation('logcat','Leer registro','Lee un volcado de logcat sin limpiar ni emitir streaming. lines selecciona las líneas recientes (por defecto200); null solicita el volcado completo.',{'buffer':{'enum':['main','system','crash','events','radio','all']},'lines':{'type':['integer','null'],'minimum':1},'pid':{'type':'integer','minimum':1}})
operation('pull_file','Recoger archivo','Copia un archivo remoto a un directorio nuevo y conserva su identidad, sin modificar el original del dispositivo.',{'remote_path':ABSOLUTE,'output_directory':S},['remote_path'])
operation('push_file','Enviar archivo','Envía un archivo local al dispositivo. Si existe el destino, overwrite debe ser explícito; conserva hashes y resultado de verificación disponible.',{'local_path':S,'remote_path':ABSOLUTE,'overwrite':{'type':'boolean'}},['local_path','remote_path'],mutates=True)
operation('screen','Capturar pantalla','Recoge un PNG mediante exec-out; no crea archivos en el dispositivo ni interactúa con él.',{'output_directory':S})
operation('processes','Procesos activos','Conserva ps -A completo y proyecta las columnas declaradas por su cabecera.')
operation('directory','Contenido de un directorio','Nombres y enlaces preservan saltos de línea mediante entradas NUL y metadatos separados; no sigue enlaces.',{'remote_path':ABSOLUTE,**PAGE},['remote_path'])
operation('features','Funciones del dispositivo','Funciones de hardware y software declaradas por el sistema.')
operation('services','Servicios Binder','Servicios e interfaces declarados por service list.')
operation('display','Pantalla y densidad','Tamaños físicos y overrides declarados por wm; no cambia su configuración.')
operation('window','Foco de ventanas','Declaraciones de foco con su contexto y líneas originales. No elige un foco singular si hay varios.')
operation('setting','Leer ajuste','Lee una clave de system, secure o global. null conserva la observación literal del dispositivo.',{'namespace':{'enum':['system','secure','global']},'key':S},['namespace','key'])
operation('bugreport','Recoger informe del sistema','Recoge el archivo bugreport del dispositivo en un directorio nuevo. Puede tardar varios minutos; conserva el archivo y el diagnóstico.',{'output_directory':S})
operation('resolve_packages','Buscar paquetes','Busca por substring sin distinguir mayúsculas en los paquetes y conserva sus rutas APK remotas.',PAGE)
operation('install','Instalar APK','Instala el APK local seleccionado. replace_requested indica si se solicitó -r; un Success no prueba si había una versión previa.',{'local_path':S,'replace':{'type':'boolean'}},['local_path'],mutates=True)
operation('uninstall','Desinstalar paquete','Solicita desinstalar para el usuario0, sin conservar datos. Retiene el veredicto y el motivo del sistema.',{'package_name':PACKAGE},['package_name'],mutates=True)
operation('start_app','Iniciar aplicación','Resuelve la actividad MAIN/LAUNCHER del paquete e inicia am start -W; conserva informe y fallos del intento.',{'package_name':PACKAGE},['package_name'],mutates=True)
operation('start_activity','Iniciar actividad o intent','Inicia am start -W con acción, URI/componente opcionales y extras tipados; conserva el informe completo.',{'action':S,'data_uri':S,'component':S,'extras':{'type':'array','items':EXTRA}},['action'],mutates=True)
operation('stop_app','Detener aplicación','Ejecuta am force-stop sobre el paquete seleccionado; no afirma que antes tuviese procesos activos.',{'package_name':PACKAGE},['package_name'],mutates=True)


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def inspect(operation_name,p,output):
    executable=engine()
    if not executable:
        raise ValueError('Install Android platform-tools or configure THESEUS_ADB')
    observations=[]
    result={'status':'incomplete','selection':p,'observations':observations,'started_at':stamp(),
        'engine':{'path':executable,'sha256':sha(executable)}}
    def checkpoint():
        document={'operation':operation_name,'runtime':sys.version.split()[0],
            'engine':'Theseus runtime observation','result':{**result,'status':'incomplete'}}
        temporary=output.parent/'partial.tmp'
        temporary.write_text(json.dumps(document,ensure_ascii=True,indent=2),encoding='utf8')
        temporary.replace(output.parent/'partial.json')
    def run(args,device=True,binary=False,expected=(0,)):
        command=[executable]+(['-s',p['serial']] if device else [])+list(map(str,args))
        started=stamp();t=time.monotonic()
        reply=subprocess.run(command,stdin=subprocess.DEVNULL,capture_output=True)
        row={'command':command,'started_at':started,'finished_at':stamp(),'duration_seconds':round(time.monotonic()-t,4),
            'exit_code':reply.returncode,'expected_exit_codes':list(expected),'stdout':None if binary else reply.stdout.decode('utf8',errors='replace'),
            'stderr':reply.stderr.decode('utf8',errors='replace'),'stdout_base64':base64.b64encode(reply.stdout).decode('ascii'),
            'stderr_base64':base64.b64encode(reply.stderr).decode('ascii'),'stdout_encoding':'binary' if binary else 'utf8-replacement'}
        observations.append(row)
        checkpoint()
        return row
    def shell(*args,expected=(0,)):
        return run(['shell','-T',' '.join(shlex.quote(str(v)) for v in args)],expected=expected)
    def raw_shell(*args):
        # Windows adb shell translates LF even without a PTY. The server's
        # shell-v2 protocol preserves stdout/stderr bytes and the remote exit.
        command=' '.join(shlex.quote(str(v)) for v in args)
        configured=os.environ.get('ADB_SERVER_SOCKET','tcp:127.0.0.1:'+os.environ.get('ANDROID_ADB_SERVER_PORT','5037'))
        match=re.fullmatch(r'tcp:([^:]+):(\d+)',configured)
        if not match: raise ValueError('Raw ADB observations require a TCP ADB_SERVER_SOCKET')
        host,port=match.group(1),int(match.group(2))
        reply={'transport':'adb-server-shell-v2','server':{'host':host,'port':port},'device_command':command,
            'started_at':stamp(),'expected_exit_codes':[0],'exit_code':None,'device_exit_code':None}
        stdout,stderr,unknown=bytearray(),bytearray(),[]
        started=time.monotonic()
        try:
            with socket.create_connection((host,port)) as connection:
                def read(size):
                    data=bytearray()
                    while len(data)<size:
                        block=connection.recv(size-len(data))
                        if not block: raise EOFError('ADB stream ended before its exit frame')
                        data.extend(block)
                    return bytes(data)
                def service(value):
                    encoded=value.encode('utf8')
                    connection.sendall(f'{len(encoded):04x}'.encode()+encoded)
                    status=read(4)
                    if status==b'FAIL': raise ValueError(read(int(read(4),16)).decode('utf8',errors='replace'))
                    if status!=b'OKAY': raise ValueError('Unrecognized ADB server response')
                service('host:transport:'+p['serial'])
                service('shell,v2,raw:'+command)
                while True:
                    header=read(5)
                    payload=read(int.from_bytes(header[1:5],'little'))
                    if header[0]==1: stdout.extend(payload)
                    elif header[0]==2: stderr.extend(payload)
                    elif header[0]==3:
                        if len(payload)!=1: raise ValueError('Unrecognized ADB exit frame')
                        reply.update(exit_code=payload[0],device_exit_code=payload[0])
                        break
                    else: unknown.append({'id':header[0],'base64':base64.b64encode(payload).decode('ascii')})
        except Exception as exc:
            reply['transport_error']=type(exc).__name__+': '+str(exc)
        reply.update(finished_at=stamp(),duration_seconds=round(time.monotonic()-started,4),
            stdout=stdout.decode('utf8',errors='replace'),stderr=stderr.decode('utf8',errors='replace'),
            stdout_base64=base64.b64encode(stdout).decode('ascii'),stderr_base64=base64.b64encode(stderr).decode('ascii'),
            device_payload_base64=base64.b64encode(stdout).decode('ascii'),unknown_frames=unknown)
        observations.append(reply)
        checkpoint()
        return reply
    def page(rows):
        matches=[row for row in rows if p.get('query','').casefold() in str(row).casefold()]
        offset,limit=p.get('offset',0),p.get('limit')
        selected=matches[offset:] if limit is None else matches[offset:offset+limit]
        return selected,{'observed':len(rows),'matching':len(matches),'offset':offset,'returned':len(selected),'has_more':offset+len(selected)<len(matches)}
    def directory():
        base=Path(p['output_directory']).expanduser().resolve() if p.get('output_directory') else None
        destination=base/(p.get('package_name') or output.parent.name) if base else output.parent/'collected'
        destination.mkdir(parents=True,exist_ok=False)
        return destination
    def collected(path,location):
        if path.is_file():
            result.setdefault('artifacts',[]).append({'path':str(path),'name':path.name,'source_location':location,
                'sha256':sha(path),'size_bytes':path.stat().st_size})
    version=run(['version'],device=False)
    result.update(status='observed',engine={'path':executable,'sha256':sha(executable),'version':version},
        limitations=['Each observation describes the selected client invocation and captured device state, not general behavior or a continuous trace.',
            'Recorded runtime JSON is the source artifact for these records; its hash identifies the recording, not an APK or the device.'])
    try:
        short=operation_name.removeprefix('adb.')
        if short=='client':
            result.update(status='observed' if version['exit_code']==0 else 'command-error',finished_at=stamp())
            return result
        if short=='devices':
            observed=run(['devices','-l'],device=False)
            result['devices']=[]
            for line in observed['stdout'].splitlines()[1:]:
                parts=line.split()
                if len(parts)<2 or line.startswith('*'): continue
                metadata=dict(part.split(':',1) for part in parts[2:] if ':' in part)
                result['devices'].append({'serial':parts[0],'state':parts[1],'metadata':metadata,'raw_line':line,
                    'kind':'emulator-candidate' if parts[0].startswith('emulator-') else 'device','kind_basis':'serial naming only, not verified hardware'})
        else:
            fingerprint=shell('getprop','ro.build.fingerprint')
            result['target']={'serial':p['serial'],'build_fingerprint':fingerprint['stdout'].strip() if fingerprint['exit_code']==0 else None}
            if short=='device':
                props=shell('getprop')
                result['properties']=[{'name':m.group(1),'value':m.group(2)} for line in props['stdout'].splitlines() if (m:=re.fullmatch(r'\[(.*?)\]: \[(.*)\]',line))]
            elif short in {'packages','resolve_packages'}:
                args=['pm','list','packages','-f']+(['-3'] if p.get('scope')=='third-party' else ['-s'] if p.get('scope')=='system' else [])
                packages=shell(*args)
                rows=[]
                for line in packages['stdout'].splitlines():
                    if line.startswith('package:') and '=' in line:
                        path,name=line[8:].rsplit('=',1)
                        rows.append({'package_name':name,'device_apk_path':path,'raw_line':line})
                result['packages'],result['coverage']=page(rows)
            elif short=='package':
                reply=shell('dumpsys','package',p['package_name'])
                result['package_name']=p['package_name']
                facts=[]
                for i,line in enumerate(reply['stdout'].splitlines()):
                    if re.search(r'\b(versionCode|versionName|userId|firstInstallTime|lastUpdateTime|installerPackageName|pkgFlags)=',line):
                        facts.append({'line_number':i+1,'text':line})
                result['declared_facts']=facts
            elif short in {'pull_package','pull_file'}:
                destination=directory()
                if short=='pull_package':
                    paths=shell('pm','path',p['package_name'])
                    remote=[line[8:] for line in paths['stdout'].splitlines() if line.startswith('package:')]
                else:
                    remote=[p['remote_path']]
                result['transfers']=[]
                for i,path in enumerate(remote):
                    suffix=Path(path).suffix if re.fullmatch(r'\.[A-Za-z0-9]+',Path(path).suffix) else '.bin'
                    target=destination/(str(i)+'-'+hashlib.sha256(path.encode('utf8')).hexdigest()+suffix)
                    reply=run(['pull',path,str(target)])
                    result['transfers'].append({'device_path':path,'host_path':str(target),'exit_code':reply['exit_code'],'captured':target.is_file()})
                    collected(target,path)
                if not remote: result['status']='no-package-paths'
            elif short in {'install','push_file'}:
                original=Path(p['local_path']).expanduser().resolve()
                before=sha(original)
                snapshot=output.parent/('upload-input'+original.suffix)
                try:
                    shutil.copyfile(original,snapshot)
                    if sha(snapshot)!=before or sha(original)!=before:
                        raise ValueError('Local input changed while capturing its bytes')
                    result['local_source']={'path':str(original),'sha256':before,'size_bytes':snapshot.stat().st_size}
                    if short=='install':
                        reply=run(['install']+(['-r'] if p.get('replace') else [])+[str(snapshot)])
                        result.update(replace_requested=p.get('replace',False),replaced=None,
                            verdict='success' if 'Success' in reply['stdout'].splitlines() else 'refused')
                    else:
                        remote=p['remote_path']
                        exists=shell('test','-e',remote,expected=(0,1))
                        if exists['exit_code']==0 and not p.get('overwrite',False):
                            result['status']='destination-exists'
                        else:
                            reply=run(['push',str(snapshot),remote])
                            check=shell('sha256sum','--',remote)
                            match=re.match(r'^([0-9a-fA-F]{64})\b',check['stdout']) if check['exit_code']==0 else None
                            remote_sha=match.group(1).lower() if match else None
                            result.update(device_sha256=remote_sha,verified=None if remote_sha is None else remote_sha==before)
                            result['limitations'].append('The destination existence check is not an atomic create; concurrent device writers can race it.')
                    result['local_source_changed']=not original.is_file() or sha(original)!=before
                finally:
                    snapshot.unlink(missing_ok=True)
            elif short=='screen':
                reply=run(['exec-out','screencap','-p'],binary=True)
                raw=base64.b64decode(reply['stdout_base64'])
                if raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw)>=24:
                    target=directory()/'screen.png'
                    target.write_bytes(raw)
                    result['dimensions']={'width':int.from_bytes(raw[16:20],'big'),'height':int.from_bytes(raw[20:24],'big')}
                    collected(target,'exec-out screencap -p')
                else: result['status']='not-png'
            elif short=='processes':
                reply=shell('ps','-A')
                lines=reply['stdout'].splitlines()
                columns=lines[0].split() if lines else []
                result['processes']=[dict(zip(columns,line.split(maxsplit=len(columns)-1))) for line in lines[1:]] if columns else []
            elif short=='directory':
                reply=raw_shell('find',p['remote_path'],'-mindepth','1','-maxdepth','1','-print0')
                names=base64.b64decode(reply['device_payload_base64']).split(b'\0')
                rows=[{'path':name.decode('utf8',errors='replace'),'path_base64':base64.b64encode(name).decode('ascii'),
                    'utf8_valid':name.decode('utf8',errors='replace').encode('utf8')==name} for name in names if name]
                selected,result['coverage']=page(rows)
                for row in selected:
                    if not row['utf8_valid']:
                        row.update(metadata_available=False,metadata_error='Raw path is not UTF-8; a replacement spelling was not used for lookup')
                        continue
                    info=shell('stat','-c','%f:%u:%g:%s:%Y','--',row['path'])
                    values=info['stdout'].strip().split(':')
                    row['metadata_available']=info['exit_code']==0 and len(values)==5
                    if row['metadata_available']:
                        mode=int(values[0],16)
                        row.update(mode=oct(mode),uid=values[1],gid=values[2],size_bytes=values[3],modified_epoch=values[4],kind='symlink' if stat.S_ISLNK(mode) else 'directory' if stat.S_ISDIR(mode) else 'file' if stat.S_ISREG(mode) else 'other')
                        if stat.S_ISLNK(mode):
                            link=raw_shell('readlink','-n','--',row['path'])
                            row['symlink_target']=base64.b64decode(link['device_payload_base64']).decode('utf8',errors='replace') if link['device_exit_code']==0 else None
                            row['symlink_target_base64']=link['device_payload_base64'] if link['device_exit_code']==0 else None
                result['entries']=selected
            elif short=='logcat':
                args=['logcat','-d','-b',p.get('buffer','main')]
                if p.get('lines',200) is not None: args+=['-t',str(p.get('lines',200))]
                if 'pid' in p: args+=['--pid',str(p['pid'])]
                run(args)
            elif short in {'features','services','display','window','setting'}:
                if short=='features':
                    reply=shell('pm','list','features');result['features']=reply['stdout'].splitlines()
                elif short=='services':
                    reply=shell('service','list');result['services']=reply['stdout'].splitlines()
                elif short=='display':
                    result['size']=shell('wm','size')['stdout'];result['density']=shell('wm','density')['stdout']
                elif short=='setting':
                    result['value']=shell('settings','get',p['namespace'],p['key'])['stdout'].removesuffix('\n').removesuffix('\r')
                else:
                    reply=shell('dumpsys','window','windows')
                    focus=[{'line_number':i+1,'text':line} for i,line in enumerate(reply['stdout'].splitlines()) if re.search(r'mCurrentFocus|mFocusedApp|mTopFocusedDisplayId',line)]
                    if not focus:
                        reply=shell('dumpsys','window','displays')
                        focus=[{'line_number':i+1,'text':line} for i,line in enumerate(reply['stdout'].splitlines()) if re.search(r'mCurrentFocus|mFocusedApp|mTopFocusedDisplayId',line)]
                    result['focus_declarations']=focus
                    result['focus_summary']='multiple-or-contextual' if len(focus)>1 else 'single-declaration' if focus else 'unknown'
            elif short=='bugreport':
                destination=directory()
                reply=run(['bugreport',str(destination/'bugreport.zip')])
                for target in destination.iterdir(): collected(target,'adb bugreport')
            elif short=='uninstall':
                reply=shell('pm','uninstall','--user','0',p['package_name'])
                result['verdict']='success' if 'Success' in reply['stdout'].splitlines() else 'refused'
            elif short=='stop_app':
                shell('am','force-stop',p['package_name'])
            elif short in {'start_app','start_activity'}:
                args=['am','start','-W']
                if short=='start_app':
                    resolved=shell('cmd','package','resolve-activity','--brief','-a','android.intent.action.MAIN','-c','android.intent.category.LAUNCHER',p['package_name'])
                    components=[line.strip() for line in resolved['stdout'].splitlines() if re.fullmatch(r'[A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+',line.strip())]
                    result['resolved_components']=components
                    if len(components)==1: args+=['-n',components[0]]
                    else: result['status']='launcher-unresolved'
                else:
                    args+=['-a',p['action']]
                    for key,flag in [('data_uri','-d'),('component','-n')]:
                        if key in p: args+=[flag,p[key]]
                    for extra in p.get('extras',[]):
                        kind,value=extra['type'],extra['value']
                        if kind=='string' and not isinstance(value,str):
                            raise ValueError('String extra must be a JSON string')
                        if kind=='boolean':
                            if not isinstance(value,bool): raise ValueError('Boolean extra must be a JSON boolean')
                            value=str(value).lower()
                        if kind in {'int','long'}:
                            if isinstance(value,bool) or not isinstance(value,(int,str)) or (isinstance(value,str) and not re.fullmatch(r'[+-]?\d+',value)):
                                raise ValueError('Integer extra must be an integer or its exact decimal string')
                            value=int(value)
                            bits=32 if kind=='int' else 64
                            if not -2**(bits-1)<=value<2**(bits-1): raise ValueError('Integer extra outside its declared type')
                        if kind=='float' and (isinstance(value,bool) or not math.isfinite(float(value))):
                            raise ValueError('Float extra must be a finite numeric value')
                        args+=[{'string':'--es','boolean':'--ez','int':'--ei','long':'--el','float':'--ef'}[kind],extra['name'],str(value)]
                if result['status']!='launcher-unresolved':
                    reply=shell(*args)
                    lines=reply['stdout'].splitlines()+reply['stderr'].splitlines()
                    result['launch_report']=[{'text':line} for line in lines]
                    result['verdict']='success' if reply['exit_code']==0 and any(line.strip()=='Status: ok' for line in lines) and not any(re.match(r'\s*Error(?:\b|:)',line) for line in lines) else 'refused-or-unknown'
            else:
                raise ValueError('Unknown runtime operation')
    except Exception as exc:
        result.update(status='observation-error',error=type(exc).__name__+': '+str(exc))
    if result['status']=='observed' and result.get('verdict') in {'refused','refused-or-unknown'}: result['status']='refused-or-unknown'
    if result['status']=='observed' and any(row['exit_code'] not in row['expected_exit_codes'] or ('device_exit_code' in row and row['device_exit_code']!=0) for row in observations): result['status']='command-error'
    result['finished_at']=stamp()
    return result


if __name__=='__main__':
    request_path,output=map(Path,sys.argv[1:3])
    request=json.loads(request_path.read_text(encoding='utf8'))
    result=inspect(request['operation'],request['parameters'],output)
    output.write_text(json.dumps({'operation':request['operation'],'runtime':sys.version.split()[0],
        'engine':'Theseus runtime observation','result':result},ensure_ascii=True,indent=2),encoding='utf8')
    (output.parent/'partial.json').unlink(missing_ok=True)
    print(json.dumps({'ok':True,'status':result['status']}))
