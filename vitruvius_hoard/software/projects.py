"""Project-owned immutable environment, source and result references."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid
from .runtime import profile


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def retained(project_id='', reference_id=''):
    path=profile()/'software-links.db'
    if not path.exists():
        return {'references':[]}
    with sqlite3.connect(path) as db:
        rows=db.execute('SELECT body FROM revisions ORDER BY stamp DESC').fetchall()
    records=[json.loads(row[0]) for row in rows]
    return {'references':[r for r in records if (not project_id or r['project_id']==project_id) and (not reference_id or r['id']==reference_id)]}


def save(project, kind, native, *, environment_id='', native_project_id='', artifact_id='', file='', reference_id='', expected_revision=0):
    profile().mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(profile()/'software-links.db',timeout=30) as db:
        db.execute('CREATE TABLE IF NOT EXISTS revisions(id TEXT, revision INTEGER, stamp REAL, body TEXT, PRIMARY KEY(id,revision))')
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT body FROM revisions WHERE id=? ORDER BY revision DESC LIMIT 1',(reference_id,)).fetchone()
        old=json.loads(row[0]) if row else None
        if (old['revision'] if old else 0)!=expected_revision:
            raise ValueError('Reference changed; read current revision before editing')
        if old and old['project_id']!=project['id']:
            raise ValueError('A reference cannot change its owning project')
        if reference_id and old is None:
            raise LookupError('Reference does not exist')
        record={'id':reference_id or uuid.uuid4().hex,'revision':expected_revision+1,'project_id':project['id'],
                'source_revision':project['selected_revision'],'source_sha256':project['source_sha256'],
                'kind':kind,'environment_id':environment_id,'native_project_id':native_project_id,'artifact_id':artifact_id,
                'file':file,'created_at':time.time(),'native':native,'native_sha256':digest(native)}
        if file and file != '.':
            record['file_sha256']=hashlib.sha256(project['files'][file].encode()).hexdigest()
        if file == '.':
            record['source_tree_sha256']=native.get('sha256') or native.get('result',{}).get('artifact_sha256') or native.get('result',{}).get('initial_source_sha256')
        db.execute('INSERT INTO revisions VALUES (?,?,?,?)',(record['id'],record['revision'],record['created_at'],json.dumps(record,ensure_ascii=False)))
    return record


class Projects:
    def __init__(self,runtime,admitted=()):
        self.runtime=runtime
        self.admitted=set(admitted)

    async def call(self,name,args):
        module='theseus' if name.startswith('theseus_') else 'babel'
        return await self.runtime.call(name,args,admitted=module in self.admitted)

    async def native(self,name,args):
        value=await self.call(name,args)
        return value['result']

    def selected(self,project_id,revision=''):
        owner=self.runtime.modules['design']
        if owner.state!='on':
            raise ValueError('Enable design explicitly first')
        return owner.app.state.services.app_projects.get(project_id,revision or None)

    async def execute(self,name,args):
        project=self.selected(args['project_id'],args.get('source_revision',''))
        if name=='software_project_read':
            return {'project':project,**retained(project['id'])}
        common={key:args[key] for key in ('reference_id','expected_revision') if key in args}
        if name=='software_environment_link':
            owner=self.runtime.modules['babel']
            if owner.state!='on':
                raise ValueError('Enable babel explicitly first')
            environment_id=args.get('environment_id','')
            if not environment_id:
                added=await self.call('docs_add_environment',{'path':args['path'],'index_dependencies':False})
                environment_id=added['environment']['id']
            from babels_hoard.environments import get_environment
            env=get_environment(owner.app.state.database.conn(),environment_id)
            if not env:
                raise LookupError('Environment does not exist')
            return save(project,'environment',env,environment_id=environment_id,**common)
        file=args.get('file','')
        if file != '.' and file not in project['files']:
            raise LookupError('File does not belong to the selected source revision')
        if name=='software_check':
            if file == '.':
                raise ValueError('Select one source file for the API checker')
            env=args['environment_id']
            if not any(r['kind']=='environment' and r['environment_id']==env and r['source_revision']==project['selected_revision'] for r in retained(project['id'])['references']):
                raise ValueError('Link the explicit environment to this source revision before checking')
            result=await self.call('api_check_code',{'code':project['files'][file],'env':env,'language':args.get('language','python')})
            return save(project,'check',result,environment_id=env,file=file,**common)
        owner=self.runtime.modules['theseus']
        if owner.state!='on':
            raise ValueError('Enable theseus explicitly first')
        native_project_id=args.get('native_project_id','')
        source=profile()/'design/app-projects'/project['id']/'revisions'/project['selected_revision']/'source'
        if file == '.':
            physical={p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*') if p.is_file()}
            expected_files={name:value.encode() for name,value in project['files'].items()}
            if physical!=expected_files:
                raise ValueError('Retained source tree differs from its recorded revision')
            from theseus.inspection import digest as tree_digest
            expected=tree_digest(source)
        else:
            expected=hashlib.sha256(project['files'][file].encode()).hexdigest()
        if name=='software_inspect':
            if not native_project_id:
                native=await self.native('theseus_project_create',{'name':project['name'],'question':'Inspect retained source revision '+project['selected_revision']})
                native_project_id=native['id']
            path=source if file=='.' else source/file
            from theseus.inspection import digest as native_digest
            if native_digest(path)!=expected:
                raise ValueError('Retained source bytes changed; do not relabel this revision')
            artifact=await self.native('theseus_artifact_add',{'project_id':native_project_id,'path':str(path)})
            if artifact['sha256']!=expected or native_digest(path)!=expected:
                raise ValueError('Source changed during inspection; register a new source revision')
            return save(project,'artifact',artifact,native_project_id=native_project_id,artifact_id=artifact['id'],file=file,**common)
        artifact_id=args['artifact_id']
        artifact=await self.native('theseus_artifact_read',{'project_id':native_project_id,'artifact_id':artifact_id})
        if artifact['sha256']!=expected:
            raise ValueError('Artifact belongs to another source revision')
        if name=='software_analysis_start':
            result=await self.native('theseus_analysis_start',{'project_id':native_project_id,'artifact_id':artifact_id,'operation':args['operation'],'parameters':args.get('parameters',{})})
            return save(project,'analysis-job',result,native_project_id=native_project_id,artifact_id=artifact_id,file=file,**common)
        job=await self.native('theseus_job_read',{'job_id':args['job_id']})
        if job['project_id']!=native_project_id:
            raise ValueError('Result belongs to another native project')
        observed=job['result'].get('artifact_sha256')
        if observed and observed!=expected:
            raise ValueError('Analysis consumed another source identity; cannot attribute it to this revision')
        # Results are retained only for a job started through this exact source link.
        started=[r for r in retained(project['id'])['references'] if r['kind']=='analysis-job' and r['native'].get('id')==args['job_id'] and r['artifact_id']==artifact_id and r['source_revision']==project['selected_revision']]
        if not started:
            raise ValueError('Job is not associated with this source revision and artifact')
        analysis=job['result'].get('analysis_file')
        if analysis:
            analysis_path=Path(analysis).resolve()
            if not analysis_path.is_relative_to((profile()/'theseus').resolve()):
                raise ValueError('Migrate the retained analysis into the owner profile before linking it')
            raw=analysis_path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=job['result'].get('analysis_sha256'):
                raise ValueError('Retained analysis changed; do not relabel its historical hash')
            job={**job,'retained_analysis':json.loads(raw)}
        return save(project,'analysis-result',job,native_project_id=native_project_id,artifact_id=artifact_id,file=file,**common)
