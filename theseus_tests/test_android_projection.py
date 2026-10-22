"""Explicit Android projections, independent of running target applications."""
import hashlib
import json
from pathlib import Path
import time

import pytest
from jsonschema import validate

from theseus.android import OPERATIONS, apktool_metadata, decoded_strings, resource_projection, package_summary, package_view
from theseus.comparison import Comparisons
from theseus.evidence import Evidence
from theseus.store import Store
from theseus.workflow import Workflow, fingerprint


@pytest.mark.parametrize('operation,parameters', [
    ('android.resources', {'locale':'es'}),
    ('android.resources', {'locales':['es','fr'], 'include_strings':False}),
    ('android.package', {'detail':'summary'}),
])
def test_catalog_admits_selected_projection(operation, parameters):
    definition = next(row for row in OPERATIONS if row['name'] == operation)
    validate(parameters, definition['inputSchema'])


def decoded_folder(tmp_path):
    (tmp_path / 'res/values').mkdir(parents=True)
    (tmp_path / 'AndroidManifest.xml').write_text('<manifest package="own.review"/>', encoding='utf8')
    (tmp_path / 'apktool.yml').write_text('versionInfo:\n  versionCode: 45.1\n  versionName: "null"\nsdkInfo:\n  minSdkVersion: 24\n  targetSdkVersion: 36\n', encoding='utf8')
    (tmp_path / 'res/values/strings.xml').write_text('<resources><string name="default">Default</string></resources>', encoding='utf8')
    return tmp_path


def test_lexical_string_values_keep_entities_whitespace_comments_and_duplicates():
    text = '<resources>\n<string name="a"> Hola &amp; mundo&#10; </string><string name="b">uno<!-- skip -->dos</string><string name="empty"/><string name="a">second</string><string name="markup"><b>bold</b></string><string>unnamed</string><string name="cdata"><![CDATA[text]]></string></resources>'
    entries, skipped = decoded_strings(text)
    assert entries == [{'name':'a','value':' Hola &amp; mundo&#10; '}, {'name':'b','value':'unodos'},
                       {'name':'empty','value':''}, {'name':'a','value':'second'}]
    assert skipped == 3


def test_locale_aliases_share_physical_table_and_keep_requested_labels(tmp_path):
    folder = decoded_folder(tmp_path)
    for suffix, word in [('pt-rBR','Olá'),('es','Hola'),('night','Night'),('en-rUS-night','Configured'),('b+zh+Hans+CN','你好')]:
        path=folder/'res'/('values-'+suffix)/'strings.xml'
        path.parent.mkdir()
        path.write_text('<resources><string name="greeting">'+word+'</string></resources>',encoding='utf8')
    result=resource_projection(folder, {'locale':'pt-BR','locales':['pt-rBR','es','es']})
    assert result['locales']==['b+zh+Hans+CN','es','pt-rBR']
    assert [row['locale'] for row in result['string_tables']]==['pt-BR','pt-rBR','es']
    assert result['strings']==[{'name':'greeting','value':'Olá'}]
    assert result['string_tables'][0]['strings']==result['string_tables'][1]['strings']
    assert result['coverage']=='complete'
    assert result['metadata']=={'version_code':'45.1','version_name':'null','min_sdk_version':'24','target_sdk_version':'36','package_name':'own.review'}


def test_missing_malformed_and_unparsed_tables_have_distinct_counts(tmp_path):
    folder=decoded_folder(tmp_path)
    for locale,text in [('es','<resources><string name="ok">a</string><string name="markup"><b>b</b></string></resources>'),
                        ('fr','<resources><string name="unclosed">'),('de','<not-resources/>')]:
        path=folder/'res'/('values-'+locale)/'strings.xml';path.parent.mkdir();path.write_text(text)
    result=resource_projection(folder, {'locales':['es','fr','de','it']})
    default,es,fr,de,it=result['string_tables']
    assert default['locale'] is None and default['total_count']==1
    assert (es['total_count'],es['unparsed_count'],es['coverage'])==(1,1,'partial')
    assert fr['status']==de['status']=='malformed'
    assert fr['total_count'] is None and de['unparsed_count'] is None
    assert (it['status'],it['total_count'],it['coverage'])==('missing',0,'complete')
    assert result['coverage']=='partial'
    incomplete=resource_projection(folder, {'locale':'it'}, decoded=False)['string_tables'][0]
    assert incomplete['status']=='unavailable' and incomplete['total_count'] is None and incomplete['coverage']=='partial'


def test_string_projection_is_explicit_and_does_not_add_a_silent_output_cap(tmp_path):
    folder=decoded_folder(tmp_path)
    path=folder/'res/values/strings.xml'
    path.write_text('<resources>'+''.join(f'<string name="s{i}">{i}</string>' for i in range(2005))+'</resources>')
    complete=resource_projection(folder,{})
    assert len(complete['strings'])==complete['string_tables'][0]['total_count']==2005
    assert complete['coverage']=='complete'
    selected=resource_projection(folder,{'include_strings':False})
    assert selected['strings']==selected['string_tables']==[]
    assert selected['manifest']=='<manifest package="own.review"/>' and selected['metadata']['version_code']=='45.1'


@pytest.mark.parametrize('locale',['night','car','../es','es/night','pt-br','b+zh+../CN'])
def test_locale_configuration_and_paths_are_not_locale_tables(tmp_path,locale):
    with pytest.raises(ValueError,match='Android locale'):
        resource_projection(tmp_path,{'locale':locale})


def test_yaml_scalar_spelling_null_and_tags_do_not_construct_objects(tmp_path):
    assert apktool_metadata('!!brut.androlib.meta.MetaInfo\nversionInfo: {versionCode: 0x2d, versionName: null}\nsdkInfo: {minSdkVersion: "null", targetSdkVersion: 036}') == {
        'version_code':'0x2d','version_name':None,'min_sdk_version':'null','target_sdk_version':'036'}
    marker=tmp_path/'must-not-exist'
    with pytest.raises(ValueError):
        apktool_metadata('!!python/object/apply:pathlib.Path.touch ["'+str(marker)+'"]')
    assert not marker.exists()
    with pytest.raises(ValueError,match='duplicate'):
        apktool_metadata('versionInfo: {versionCode: 1, versionCode: 2}')
    folder=decoded_folder(tmp_path)
    (folder/'apktool.yml').write_text('versionInfo: [')
    result=resource_projection(folder,{})
    assert result['metadata']['version_code'] is None and result['coverage']=='partial'


def package_document(tmp_path):
    report={'manifest_xml':'A😀B','package_name':'own.review','version_code':'73','version_name':'7.3',
        'sdk':{'minSdkVersion':'24','targetSdkVersion':'36'},'permissions':['perm.one','perm.two'],
        'class_count':3,'resources':[{'name':'AndroidManifest.xml'}],'engine':{'reader':'original-fixture'},
        'observation':{'stdout':'raw calls not in summary'},'compilation':{'stdout':'compiler calls not in summary'}}
    path=tmp_path/'analysis.json'
    path.write_text(json.dumps({'operation':'android.package','artifact_sha256':'a'*64,'runtime':'fixture','result':report},ensure_ascii=False),encoding='utf8')
    return path,report,hashlib.sha256(path.read_bytes()).hexdigest()


def test_package_summary_preserves_declarations_and_excludes_full_text_and_calls(tmp_path):
    path,report,digest=package_document(tmp_path)
    summary=package_summary(report)
    assert summary['sdk']==report['sdk'] and summary['permissions']==report['permissions']
    assert summary['class_count']==3 and summary['resource_count']==1
    assert summary['engine']==report['engine']
    assert summary['manifest']['text_code_units']==4 and summary['manifest']['text_included'] is False
    assert all(key not in summary for key in ('manifest_xml','observation','compilation'))
    view=package_view(path,{'facet':'summary'},digest)
    assert view['summary']==summary and view['parent_analysis_sha256']==digest


def test_manifest_windows_count_utf16_and_preserve_whole_unicode_characters(tmp_path):
    path,report,digest=package_document(tmp_path)
    short=package_view(path,{'offset':0,'limit':2},digest)
    assert short['text']=='A' and short['coverage']['next_offset']==1 and short['coverage']['examined']==1
    emoji=package_view(path,{'offset':1,'limit':2},digest)
    assert emoji['text']=='😀' and emoji['coverage']['examined']==2 and emoji['unit']=='utf16-code-units'
    tail=package_view(path,{'offset':3,'limit':2},digest)
    assert tail['text']=='B' and tail['coverage']['exhausted'] is True
    assert package_view(path,{'offset':99,'limit':2},digest)['coverage']['examined']==0
    with pytest.raises(ValueError,match='surrogate'):
        package_view(path,{'offset':2,'limit':2},digest)
    with pytest.raises(ValueError,match='Increase'):
        package_view(path,{'offset':1,'limit':1},digest)
    with pytest.raises(ValueError,match='changed'):
        package_view(path,{},'b'*64)


def test_actual_retained_worker_does_not_reopen_original_or_require_java(tmp_path,monkeypatch):
    from theseus import native_analysis
    store=Store(tmp_path/'data');project=store.create_project('Retained Android text')
    target=tmp_path/'own.bin';target.write_bytes(b'own original')
    artifact=store.add_artifact(project['id'],target)
    source_job='1'*32
    folder=store.directory/'analyses'/source_job;folder.mkdir(parents=True)
    path,report,digest=package_document(folder)
    doc=json.loads(path.read_text(encoding='utf8'));doc['artifact_sha256']=artifact['sha256']
    path.write_text(json.dumps(doc,ensure_ascii=False),encoding='utf8');digest=hashlib.sha256(path.read_bytes()).hexdigest()
    store.save_job(project['id'],source_job,'imported',{'kind':'native_analysis','operation':'android.package',
        'artifact_id':artifact['id'],'artifact_sha256':artifact['sha256'],'analysis_file':str(path),'analysis_sha256':digest})
    target.rename(tmp_path/'own.bin.retired')
    monkeypatch.setenv('THESEUS_JAVA_HOME',str(tmp_path/'no-java'))
    manager=Comparisons(store)
    try:
        job=native_analysis.start(manager,project['id'],artifact['id'],'android.package_view',
            {'source_job_id':source_job,'offset':1,'limit':2})
        deadline=time.monotonic()+15
        while job['state'] in {'queued','running'} and time.monotonic()<deadline:
            time.sleep(.02);job=store.job(job['id'])
        assert job['state']=='finished',job
        assert store.analysis_record(job['id'],'text','0')['record']=='😀'
        assert job['result']['original_source_check']=='not-performed-retained-input'
        assert job['result']['source_analysis_sha256']==digest
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    finally:
        manager.shutdown()


def test_physical_decoded_text_keeps_crlf_and_cr(tmp_path):
    folder=decoded_folder(tmp_path)
    manifest='<manifest\r\n package="own.review"/>\r\n'
    value='first\r\nsecond\rthird'
    (folder/'AndroidManifest.xml').write_bytes(manifest.encode('utf8'))
    (folder/'res/values/strings.xml').write_bytes(('<resources><string name="lines">'+value+'</string></resources>').encode('utf8'))
    result=resource_projection(folder,{})
    assert result['strings']==[{'name':'lines','value':value}]
    assert result['manifest']==manifest and result['coverage']=='complete'


def test_summary_links_digest_and_literal_ids_survive_repeated_transfer(tmp_path):
    from theseus import native_analysis
    store=Store(tmp_path/'data');project=store.create_project('Portable Android summary')
    original=tmp_path/'own.apk';original.write_bytes(b'own original; never executed')
    artifact=store.add_artifact(project['id'],original)
    source_job='3'*32
    folder=store.directory/'analyses'/source_job;folder.mkdir(parents=True)
    path,report,_=package_document(folder)
    report['engine']={'parent_job_id':source_job,'source_job_id':source_job,'job_id':source_job}
    document=json.loads(path.read_text(encoding='utf8'))
    document.update(artifact_sha256=artifact['sha256'],result=report)
    raw=json.dumps(document,ensure_ascii=False).encode('utf8');path.write_bytes(raw)
    base={'kind':'native_analysis','operation':'android.package','artifact_id':artifact['id'],'parameters':{'detail':'summary'}}
    store.save_job(project['id'],source_job,'running',base)
    native_analysis.retain(store,project['id'],source_job,artifact,folder,path,base)
    store.save_job(project['id'],source_job,'finished',base)
    original.rename(tmp_path/'own.apk.retired')
    manager=Comparisons(store);evidence=Evidence(Workflow(manager))
    parent_project=project['id'];parent_job=source_job;parent_artifact=artifact['id']
    try:
        for turn in range(3):
            imported=evidence.load(evidence.export(parent_project),'Transfer '+str(turn))
            parent_project=imported['project']['id'];parent_job=imported['id_map'][parent_job]
            parent_artifact=imported['id_map'][parent_artifact]
            job=store.job(parent_job);delivery=job['result']['delivery']
            assert delivery['parent_job_id']==parent_job and delivery['manifest_view']['source_job_id']==parent_job
            payload={k:v for k,v in delivery.items() if k!='view_sha256'}
            assert delivery['view_sha256']==hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()
            assert delivery['summary']['engine']==report['engine']
            assert delivery['parent_analysis_sha256']==hashlib.sha256(raw).hexdigest()
            assert path.read_bytes()==raw and Path(job['result']['analysis_file']).read_bytes()==raw
            selection=delivery['manifest_view']
            view=native_analysis.start(manager,parent_project,parent_artifact,selection['operation'],
                {k:v for k,v in selection.items() if k!='operation'})
            deadline=time.monotonic()+15
            while view['state'] in {'queued','running'} and time.monotonic()<deadline:
                time.sleep(.02);view=store.job(view['id'])
            assert view['state']=='finished',view
            assert store.analysis_record(view['id'],'text','0')['record']==report['manifest_xml']
        for field,value,diagnostic in [('parent_job_id','missing','missing jobs'),('view_sha256','0'*64,'summary delivery SHA')]:
            bundle=evidence.export(parent_project)
            source=next(row for row in bundle['payload']['jobs'] if row['id']==parent_job)
            source['result']['delivery'][field]=value
            bundle['manifest']['sha256']=fingerprint(bundle['payload'])
            with pytest.raises(ValueError,match=diagnostic):
                evidence.load(bundle)
    finally:
        manager.shutdown()
