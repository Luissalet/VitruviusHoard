"""Native firmware regions and regular-file extraction with retained source ranges."""
import base64
import bz2
from collections import Counter,deque
import datetime
import hashlib
import gzip
import json
import math
import lzma
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import zipfile
import zlib
import psutil

OPERATIONS=[{'name':'firmware.regions','title':'Firmware · Regiones y entropía','worker':'python',
    'description':'Identifica regiones con Binwalk local, conserva su clasificación y rangos originales y calcula entropía por ventanas. No ejecuta el firmware.',
    'inputSchema':{'type':'object','additionalProperties':False,'properties':{
        'offset':{'type':'integer','minimum':0},'length':{'type':'integer','minimum':1},
        'search_all':{'type':'boolean'},'entropy_window':{'type':'integer','minimum':1},
        'timeout_seconds':{'type':'integer','minimum':1}}}},
    {'name':'firmware.extract','title':'Firmware · Extraer regiones y archivos','worker':'python',
    'description':'Conserva regiones y archivos derivados con hashes, padres y ubicaciones originales. Binwalk identifica; lectores de archivo y 7-Zip leen contenido en archivos regulares propios, sin crear enlaces. Retiene parciales y formatos desconocidos.',
    'inputSchema':{'type':'object','additionalProperties':False,'properties':{
        'offset':{'type':'integer','minimum':0},'length':{'type':'integer','minimum':1},
        'search_all':{'type':'boolean'},'max_depth':{'type':['integer','null'],'minimum':1},
        'timeout_seconds':{'type':'integer','minimum':1}}}}]
# Each scanner or extractor call is stopped after this many seconds unless the request sets timeout_seconds.
TOOL_TIMEOUT_SECONDS=300


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def engines():
    def discover(configured,candidates):
        if configured:return str(Path(configured).resolve()) if Path(configured).is_file() else None
        return next((str(Path(path).resolve()) for path in candidates if path and Path(path).is_file()),None)
    root=Path(__file__).resolve().parents[1]
    name='theseus-firmware-scanner'+('.exe' if os.name=='nt' else '')
    built=root/'.cargo-target/release'/name
    packaged=root/'software_native/engine/firmware-scanner/bin'/name
    return {'binwalk':discover(os.environ.get('THESEUS_BINWALK'),[str(built),str(packaged),shutil.which('binwalk'),'D:/LocalAI/tools/binwalk779/bin/binwalk.exe']),
        'seven_zip':discover(os.environ.get('THESEUS_7ZIP'),[str(Path.home()/'scoop/apps/7zip/current/7z.exe'),shutil.which('7z'),r'C:\Program Files\7-Zip\7z.exe'])}


def available(operation):
    clients=engines()
    if not clients['binwalk']:return 'Instala Binwalk o configura THESEUS_BINWALK.'
    return ''


def inspect_firmware(source,operation,parameters,output,identity):
    clients=engines();folder=output.parent;extracted=folder/'extracted'
    result={'status':'incomplete','selection':{},'engines':{},'regions':[],'entropy':[],
        'artifacts':[],'entries':[],'gaps':[],'observations':[],'unclassified_ranges':[],
        'reader':{'path':str(Path(__file__).resolve()),'sha256':sha(__file__),'python_runtime':sys.version,
            'worker_pid':os.getpid(),'worker_created':psutil.Process().create_time(),'worker_command':psutil.Process().cmdline()},
        'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'coverage':{'whole_image_completeness':'unknown'},
        'limitations':['Engine signatures are classifications, not authenticated firmware component identities.',
            'Decoded member offsets cannot be linearly mapped back through compression; root ranges remain unknown there.',
            'No target program is executed. Links and special archive entries are recorded without creating filesystem links.',
            'Each scanner or extractor call has a time limit; a call that reaches it is stopped and recorded as a gap, not retried.']}
    snapshot=folder/'firmware-input.bin'
    checkpoint_serial=0;latest_checkpoint=None
    def checkpoint():
        nonlocal checkpoint_serial,latest_checkpoint
        document={'operation':operation,'artifact_sha256':identity,'input_sha256':identity,
            'engine':'Theseus firmware analysis','runtime':sys.version.split()[0],'result':result}
        checkpoint_serial+=1
        published=folder/f'checkpoint-{checkpoint_serial:020d}.json';temporary=published.with_suffix('.tmp')
        temporary.write_text(json.dumps(document,ensure_ascii=True,indent=2),encoding='utf8');temporary.replace(published)
        latest_checkpoint=published
        for old in folder.glob('checkpoint-*.json'):
            if old==published:continue
            try:old.unlink()
            except PermissionError:pass  # A reader may still hold an immutable older snapshot on Windows.
    def gap(kind,**data):
        result['gaps'].append({'kind':kind,**data});checkpoint()
    limit=parameters.get('timeout_seconds',TOOL_TIMEOUT_SECONDS)
    def run(args,stdout_file=None):
        start=time.monotonic()
        started=datetime.datetime.now(datetime.timezone.utc).isoformat()
        result['pending_command']=list(map(str,args));checkpoint()
        try:
            if stdout_file:
                with stdout_file.open('wb') as stream:
                    reply=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.PIPE,timeout=limit)
            else:reply=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,timeout=limit)
            returncode,out,err,timed_out=reply.returncode,reply.stdout,reply.stderr,False
        except subprocess.TimeoutExpired as expired:
            # subprocess.run has already killed and reaped the client; keep whatever it wrote.
            returncode,out,err,timed_out=None,expired.stdout,expired.stderr,True
        out=out if isinstance(out,bytes) else b'';err=err if isinstance(err,bytes) else b''
        text=None if stdout_file else out.decode('utf8',errors='replace')
        encoded=None if stdout_file else base64.b64encode(out).decode('ascii')
        row={'command':list(map(str,args)),'exit_code':returncode,'timed_out':timed_out,'timeout_seconds':limit,
            'duration_seconds':round(time.monotonic()-start,4),
            'started_at':started,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'stdout':text,'stdout_base64':encoded,'stderr':err.decode('utf8',errors='replace'),
            'stderr_base64':base64.b64encode(err).decode('ascii')}
        if stdout_file:row.update(stdout_relative_path=stdout_file.name,stdout_sha256=sha(stdout_file),stdout_bytes=stdout_file.stat().st_size)
        result['observations'].append(row);result.pop('pending_command',None);checkpoint();return row
    def artifact(path,parent,location,**extra):
        row={'relative_path':path.name,'sha256':sha(path),'size_bytes':path.stat().st_size,
            'source_location':location,**extra}
        if parent is not None:row['parent_relative_path']=parent
        result['artifacts'].append(row);checkpoint();return row
    def target(label):return extracted/(f'{len(result["artifacts"]):05d}-'+label+'.bin')
    def scan(path,parent,depth,root_start=None):
        log=folder/(f'binwalk-{len(result["observations"]):05d}.json')
        args=[clients['binwalk'],'--quiet','--threads','1','--log',str(log)]
        if parameters.get('search_all',False):args.append('--search-all')
        reply=run(args+[str(path)])
        if reply['timed_out']:
            gap('scanner-timeout',parent_relative_path=parent,command=reply['command'],timeout_seconds=limit);return []
        if reply['exit_code']!=0:gap('scanner-failed',parent_relative_path=parent,diagnostic=reply['stderr'])
        if not log.is_file():gap('missing-scanner-recording',parent_relative_path=parent);return []
        try:recorded=json.loads(log.read_text(encoding='utf8'))
        except (ValueError,UnicodeError) as exc:
            result.setdefault('unparsed_reports',[]).append({'path':str(log),'sha256':sha(log),'text':log.read_text(encoding='utf8',errors='replace')})
            gap('invalid-scanner-json',parent_relative_path=parent,diagnostic=str(exc));return []
        result.setdefault('producer_reports',[]).append({'parent_relative_path':parent,'report':recorded})
        found=[]
        for document in recorded:
            analysis=document.get('Analysis') if isinstance(document,dict) else None
            if not isinstance(analysis,dict) or not isinstance(analysis.get('file_map'),list):
                gap('unrecognized-scanner-record',parent_relative_path=parent);continue
            for raw in analysis['file_map']:
                if not isinstance(raw,dict):gap('invalid-region-record',parent_relative_path=parent);continue
                offset,length=raw.get('offset'),raw.get('size')
                valid=type(offset) is int and type(length) is int and offset>=0 and length>0 and offset+length<=path.stat().st_size
                row={**raw,'parent_relative_path':parent,'depth':depth,'range_valid':valid,
                    'root_file_range':{'offset':root_start+offset,'length':length} if valid and root_start is not None else None}
                result['regions'].append(row)
                if valid:found.append(row)
                else:gap('unknown-or-invalid-region-extent',parent_relative_path=parent,region=raw)
        cursor=0
        for start,end in sorted((row['offset'],row['offset']+row['size']) for row in found):
            if start>cursor:
                result['unclassified_ranges'].append({'parent_relative_path':parent,'offset':cursor,'length':start-cursor,
                    'root_file_range':{'offset':root_start+cursor,'length':start-cursor} if root_start is not None else None})
            cursor=max(cursor,end)
        if cursor<path.stat().st_size:
            result['unclassified_ranges'].append({'parent_relative_path':parent,'offset':cursor,'length':path.stat().st_size-cursor,
                'root_file_range':{'offset':root_start+cursor,'length':path.stat().st_size-cursor} if root_start is not None else None})
        checkpoint();return found
    def extracted_member(origin,metadata,read,queue,depth):
        member=target('member')
        result['in_progress']={'relative_path':member.name,'parent_relative_path':origin,'entry':metadata};checkpoint()
        try:
            with member.open('wb') as stream:
                for block in read():stream.write(block)
            child=artifact(member,origin,'archive member #'+str(metadata['ordinal'])+' '+metadata['name'],archive_entry=metadata)
            queue.append((member,child['relative_path'],depth,None))
            result['entries'].append({'parent_relative_path':origin,**metadata,'artifact_relative_path':child['relative_path']})
        except Exception as exc:
            if member.is_file():artifact(member,origin,'partial archive member '+metadata['name'],partial=True,archive_entry=metadata)
            gap('member-read-failed',parent_relative_path=origin,entry=metadata,diagnostic=type(exc).__name__+': '+str(exc))
        finally:result.pop('in_progress',None);checkpoint()
    def unpack(path,origin,queue,depth,format_name):
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for index,entry in enumerate(archive.infolist()):
                    metadata={'name':entry.orig_filename,'ordinal':index,'size_bytes':entry.file_size,'crc32':entry.CRC,'reader':'python-zip'}
                    if entry.is_dir():result['entries'].append({'parent_relative_path':origin,**metadata,'kind':'directory'});continue
                    if stat.S_ISLNK(entry.external_attr>>16):
                        metadata['link_target_base64']=base64.b64encode(archive.read(entry)).decode('ascii')
                        gap('link-not-created',parent_relative_path=origin,entry=metadata);continue
                    if entry.flag_bits&1:gap('encrypted-entry',parent_relative_path=origin,entry=metadata);continue
                    def read(entry=entry):
                        with archive.open(entry) as stream:yield from iter(lambda:stream.read(1024*1024),b'')
                    extracted_member(origin,metadata,read,queue,depth)
            return
        try:archive=tarfile.open(path,'r:*')
        except tarfile.ReadError:archive=None
        if archive is not None:
            with archive:
                for index,entry in enumerate(archive):
                    metadata={'name':entry.name,'ordinal':index,'size_bytes':entry.size,'reader':'python-tar','link_name':entry.linkname}
                    if entry.isdir():result['entries'].append({'parent_relative_path':origin,**metadata,'kind':'directory'});continue
                    if not entry.isreg():gap('link-or-special-entry-not-created',parent_relative_path=origin,entry=metadata);continue
                    def read(entry=entry):
                        with archive.extractfile(entry) as stream:yield from iter(lambda:stream.read(1024*1024),b'')
                    extracted_member(origin,metadata,read,queue,depth)
            return
        codecs={'gzip':gzip.open,'xz':lzma.open,'lzma':lzma.open,'bzip2':bz2.open}
        if format_name in codecs or format_name=='zlib':
            def read():
                if format_name=='zlib':
                    decoder=zlib.decompressobj()
                    with path.open('rb') as source_stream:
                        for block in iter(lambda:source_stream.read(1024*1024),b''):
                            while block:
                                yield decoder.decompress(block,1024*1024);block=decoder.unconsumed_tail
                        yield decoder.flush()
                    if not decoder.eof:raise ValueError('Compressed stream ended before its trailer')
                else:
                    with codecs[format_name](path,'rb') as stream:yield from iter(lambda:stream.read(1024*1024),b'')
            extracted_member(origin,{'name':format_name+' decompressed stream','ordinal':0,'reader':'python-'+format_name,
                'zlib_runtime':zlib.ZLIB_RUNTIME_VERSION},read,queue,depth)
            return
        if not clients['seven_zip']:
            gap('missing-extractor-dependency',parent_relative_path=origin,dependency='7-Zip',continuation='Configure THESEUS_7ZIP and analyze this retained child again');return
        listing=run([clients['seven_zip'],'l','-slt','-ba','-sccUTF-8','--',str(path)])
        if listing['timed_out']:
            gap('extractor-timeout',parent_relative_path=origin,command=listing['command'],timeout_seconds=limit);return
        if listing['exit_code']!=0:
            gap('extractor-unavailable-for-region',parent_relative_path=origin,diagnostic=listing['stderr']);return
        blocks=re.split(r'\n\s*\n',listing['stdout'].replace('\r',''))
        stream_format=format_name in {'gzip','xz','bzip2','lzma','lz4','zstd'}
        if stream_format and len([block for block in blocks if block.strip()])!=1:
            gap('ambiguous-compressed-stream-listing',parent_relative_path=origin);return
        for index,block in enumerate(blocks):
            if not block.strip():continue
            values={};ambiguous=False
            for line in block.splitlines():
                key,separator,value=line.partition(' = ')
                if not separator or key in values:ambiguous=True
                values[key]=value
            if ambiguous or ('Path' not in values and not stream_format):
                gap('ambiguous-extractor-listing',parent_relative_path=origin,raw=block);continue
            # 7-Zip lists member paths with the host separator; on Windows '\\' stands for the archive's '/'.
            listed=values.get('Path','')
            name=(listed.replace('\\','/') if os.sep=='\\' else listed) if not stream_format else format_name+' decompressed stream'
            metadata={'name':name,'ordinal':index,'reader':'7zip','fields':values,'stream_output':stream_format}
            if values.get('Folder')=='+':result['entries'].append({'parent_relative_path':origin,**metadata,'kind':'directory'});continue
            # 7-Zip prints these fields empty for regular members; only a value marks a link.
            if any(values.get(key,'').strip() for key in ['Symbolic Link','Hard Link','Reparse']):
                gap('link-not-created',parent_relative_path=origin,entry=metadata);continue
            if values.get('Encrypted')=='+':gap('encrypted-entry',parent_relative_path=origin,entry=metadata);continue
            member=target('member');result['in_progress']={'relative_path':member.name,'parent_relative_path':origin,'entry':metadata};checkpoint()
            reply=run([clients['seven_zip'],'x','-so','-spd','-y','-p-','-sccUTF-8','--',str(path)]+([] if stream_format else [values['Path']]),member)
            expected=int(values['Size']) if values.get('Size','').isdigit() else None
            partial=reply['exit_code']!=0 or (expected is not None and member.stat().st_size!=expected) or (expected is None and not stream_format)
            child=artifact(member,origin,'archive member '+name,archive_entry=metadata,partial=partial)
            result['entries'].append({'parent_relative_path':origin,**metadata,'artifact_relative_path':child['relative_path'],'partial':partial})
            result.pop('in_progress',None)
            if partial:gap('member-output-incomplete-or-ambiguous',parent_relative_path=origin,entry=metadata)
            else:queue.append((member,child['relative_path'],depth,None))
            checkpoint()
    try:
        if not clients['binwalk']:raise ValueError(available(operation))
        shutil.copyfile(source,snapshot)
        if sha(snapshot)!=identity or sha(source)!=identity:raise ValueError('Original firmware changed while capturing its bytes')
        size=snapshot.stat().st_size;offset=parameters.get('offset',0);length=parameters.get('length',size-offset)
        if offset<0 or length<=0 or offset+length>size:raise ValueError('Selected interval leaves the original file')
        result['selection']={'offset':offset,'length':length,'original_sha256':identity}
        if offset or length!=size:
            with snapshot.open('rb') as stream:stream.seek(offset);selected=stream.read(length)
            snapshot.write_bytes(selected)
        result['selection']['sha256']=sha(snapshot);checkpoint()
        for name,client in clients.items():
            if client and (name=='binwalk' or operation=='firmware.extract'):
                result['engines'][name]={'path':client,'sha256':sha(client),'version':run([client,'--version'] if name=='binwalk' else [client,'i'])}
        if operation=='firmware.regions':
            scan(snapshot,None,0,offset)
            window=parameters.get('entropy_window',4096)
            with snapshot.open('rb') as stream:
                at=offset
                for block in iter(lambda:stream.read(window),b''):
                    counts=Counter(block)
                    result['entropy'].append({'file_offset':at,'bytes':len(block),'bits_per_byte':-sum((n/len(block))*math.log2(n/len(block)) for n in counts.values())})
                    at+=len(block)
        else:
            extracted.mkdir(exist_ok=False);queue=deque([(snapshot,None,0,offset)]);seen={}
            while queue:
                path,parent,depth,root_start=queue.popleft();digest=sha(path)
                if digest in seen:
                    result.setdefault('reused_observations',[]).append({'parent_relative_path':parent,'same_bytes_as':seen[digest]});checkpoint();continue
                seen[digest]=parent
                found=scan(path,parent,depth,root_start)
                for region in found:
                    label=re.sub(r'[^A-Za-z0-9_.-]','_',str(region.get('name','region')))
                    carved=target(label)
                    with path.open('rb') as stream:
                        stream.seek(region['offset']);remaining=region['size']
                        with carved.open('wb') as destination:
                            while remaining:
                                block=stream.read(min(remaining,1024*1024))
                                if not block:raise ValueError('Region input ended before its recorded range')
                                destination.write(block);remaining-=len(block)
                    input_offset=region['root_file_range']['offset'] if parent is None else region['offset']
                    child=artifact(carved,parent,'file bytes '+str(input_offset)+'..'+str(input_offset+region['size']),
                        input_file_range={'offset':input_offset,'length':region['size']},root_file_range=region['root_file_range'],classification=region.get('name'))
                    if parameters.get('max_depth') is not None and depth>=parameters['max_depth']:
                        gap('depth-limited',parent_relative_path=child['relative_path'],continuation='Analyze this retained child artifact with firmware.extract');continue
                    try:unpack(carved,child['relative_path'],queue,depth+1,region.get('name'))
                    except Exception as exc:gap('region-extraction-failed',parent_relative_path=child['relative_path'],diagnostic=type(exc).__name__+': '+str(exc))
        result['status']='partial' if result['gaps'] else 'observed';result['coverage']['completed_recording']=True
    except Exception as exc:
        result.update(status='partial' if result['artifacts'] or result['regions'] else 'observation-error',error=type(exc).__name__+': '+str(exc))
    finally:
        snapshot.unlink(missing_ok=True);result['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();checkpoint()
        temporary=output.with_suffix('.tmp');shutil.copyfile(latest_checkpoint,temporary);temporary.replace(output)
        for old in folder.glob('checkpoint-*.json'):
            try:old.unlink()
            except PermissionError:pass
    return result


def recording_file(folder,output):
    if output.is_file():return output
    checkpoints=sorted(folder.glob('checkpoint-*.json'))
    return checkpoints[-1] if checkpoints else None


def read_recording(folder,output):
    while True:
        try:return json.loads(output.read_text(encoding='utf8'))
        except FileNotFoundError:
            output=recording_file(folder,folder/'analysis.json')
            if output is None:raise


def freeze_recording(folder,output,cleanup=None):
    """Retain completed checkpoints and freeze an unfinished regular output."""
    retained=folder/'interrupted-analysis.json'
    if retained.exists():return retained
    document=read_recording(folder,output);result=document['result']
    if cleanup is not None:result['orphan_worker_cleanup']=cleanup
    progress=result.pop('in_progress',None)
    if isinstance(progress,dict):
        result['interrupted_output']=progress
        relative=progress['relative_path'];base=(folder/'extracted').resolve();source=(base/relative).resolve()
        if source.parent!=base or source.name!=relative:raise ValueError('Interrupted output leaves its extraction directory')
        if source.is_file() and not any(row['relative_path']==relative for row in result['artifacts']):
            frozen=base/('interrupted-'+relative)
            if not frozen.exists():
                temporary=frozen.with_suffix('.tmp');shutil.copyfile(source,temporary);temporary.replace(frozen)
            row={'relative_path':frozen.name,'parent_relative_path':progress['parent_relative_path'],
                'sha256':sha(frozen),'size_bytes':frozen.stat().st_size,'partial':True,
                'source_location':'interrupted archive output '+progress['entry']['name'],'archive_entry':progress['entry']}
            result['artifacts'].append(row);result['interrupted_output']['retained_relative_path']=frozen.name
    if result.get('pending_command'):result['interrupted_command']=result.pop('pending_command')
    result['interrupted_recording']=True
    temporary=retained.with_suffix('.tmp');temporary.write_text(json.dumps(document,ensure_ascii=True,indent=2),encoding='utf8');temporary.replace(retained)
    return retained


def stop_interrupted_worker(folder,output):
    """Stop only the checkpoint's still-matching structured worker and children."""
    from .comparison import Comparisons
    document=read_recording(folder,output);reader=document['result'].get('reader',{})
    pid=reader.get('worker_pid')
    if type(pid) is not int or pid==os.getpid():return {'status':'no-owned-worker-identity'}
    try:
        process=psutil.Process(pid);command=process.cmdline()
        normalize=lambda value:str(Path(value).resolve()).casefold()
        expected=[str(Path(__file__).with_name('structured.py')),str(folder/'request.json'),str(folder/'analysis.json')]
        if process.create_time()!=reader.get('worker_created') or command!=reader.get('worker_command') or len(command)!=4 or [normalize(value) for value in command[1:]]!=[normalize(value) for value in expected]:
            return {'status':'identity-mismatch','pid':pid}
        targets=[*process.children(recursive=True),process]
        Comparisons._terminate(type('Worker',(),{'pid':pid})())
        _,remaining=psutil.wait_procs(targets,timeout=2)
        return {'status':'terminated-owned-worker' if not remaining else 'termination-not-confirmed','pid':pid,'remaining':[row.pid for row in remaining]}
    except psutil.NoSuchProcess:return {'status':'not-running','pid':pid}
    except psutil.Error as exc:return {'status':'cleanup-error','pid':pid,'error':str(exc)}
