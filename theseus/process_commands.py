"""Materialize declared scenario commands without shell quoting or repo aliases."""
import hashlib
import os
from pathlib import Path
import subprocess

TEXT={'type':'string'}
STREAM={'type':'object','additionalProperties':False,'properties':{'text':TEXT,'data_base64':TEXT},
    'oneOf':[{'required':['text']},{'required':['data_base64']}]}
COMMANDS={'type':'array','items':{'type':'object','additionalProperties':False,'required':['name','response'],
    'properties':{'name':{'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_-]*$'},
        'response':{'type':'object','additionalProperties':False,'properties':{'stdout':STREAM,'stderr':STREAM,
            'exit_code':{'type':'integer','minimum':-2147483648,'maximum':2147483647}}}}}}


def compiler():
    if os.name!='nt':return None
    root=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET'
    return next((path for path in [root/'Framework64/v4.0.30319/csc.exe',root/'Framework/v4.0.30319/csc.exe'] if path.is_file()),None)


def materialize(definitions,folder):
    csc=compiler()
    if csc is None:raise ValueError('The declared command shim backend requires Windows .NET Framework C# compiler')
    names=[row['name'].casefold() for row in definitions]
    reserved={'con','prn','aux','nul',*[name+str(index) for name in ('com','lpt') for index in range(1,10)]}
    if len(set(names))!=len(names) or any(name in reserved for name in names):raise ValueError('Command names must be unique Windows filenames')
    source=Path(__file__).with_name('process_shim.cs');folder=Path(folder);folder.mkdir()
    records=[]
    for row in definitions:
        destination=folder/(row['name']+'.exe')
        result=subprocess.run([str(csc),'/nologo','/target:exe','/optimize+', '/reference:System.Runtime.Serialization.dll',
            '/out:'+str(destination),str(source)],capture_output=True)
        if result.returncode:raise ValueError('Scenario command build failed: '+result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))
        records.append({'name':row['name'],'path':str(destination),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'compiler':str(csc),
            'scope':'PATH-resolved calls only. Absolute paths and current-directory executables can bypass this declared shim.'})
    return records
