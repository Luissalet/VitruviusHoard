import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from android_fixture import android_fixture, BUILD, PLATFORM
from test_portfolio import run
from theseus.android import available
from theseus.api import create_app
from theseus.inspection import digest
from theseus.native_analysis import catalog


def test_android_missing_engines_report_capabilities(monkeypatch,tmp_path):
    monkeypatch.setenv('THESEUS_JADX_LIB',str(tmp_path/'missing'))
    rows=[r for r in catalog()['operations'] if r['name'] in {'android.package','android.classes','android.class','android.method','android.references'}]
    assert len(rows)==5 and all(not row['available'] and 'THESEUS_JADX_LIB' in row['availability_reason'] for row in rows)
    monkeypatch.setenv('THESEUS_APKTOOL',str(tmp_path/'absent.jar'))
    assert 'THESEUS_APKTOOL' in available('android.resources')


@pytest.mark.skipif(bool(available('android.package')) or not BUILD.is_dir() or not PLATFORM.is_file(),reason='Requires installed free JADX and Android SDK')
def test_android_real_apk_members_overloads_smali_references_resources_and_transfer(tmp_path):
    source=android_fixture(tmp_path/'original')
    original=digest(source)
    app=create_app(tmp_path/'data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        pid=app.state.store.create_project('Android original fixture')['id']
        artifact=app.state.store.add_artifact(pid,source)
        def analyze(operation,parameters=None):
            job,result=run(client,pid,artifact['id'],'android.'+operation,parameters)
            assert result['status'] not in {'reader-error','decoder-error'},result
            assert result['snapshot_sha256']==original and digest(source)==original
            assert not list(Path(job['result']['analysis_file']).parent.glob('android-input*'))
            return job,result
        _,package=analyze('package')
        assert package['package_name']=='com.theseus.fixture'
        assert package['sdk']['minSdkVersion']=='23' and package['sdk']['targetSdkVersion']=='36'
        assert package['permissions']==['android.permission.CAMERA']
        assert package['class_count']>=3 and package['resources']
        assert package['engine']['jadx_jars'][0]['sha256']
        _,classes=analyze('classes',{'query':'Gauge','limit':None,'include_inner':True})
        assert any(r['name']=='com.theseus.fixture.Gauge.Probe' for r in classes['classes']['rows'])
        _,lower=analyze('classes',{'query':'gauge','limit':None})
        assert lower['classes']['total']==0
        _,page=analyze('classes',{'query':'Gauge','offset':1,'limit':1,'include_inner':True})
        assert page['classes']['rows']==classes['classes']['rows'][1:2]
        _,empty=analyze('classes',{'offset':10**30,'limit':10**30})
        assert empty['classes']['offset']==10**30 and empty['classes']['returned']==0 and not empty['classes']['has_more']
        select={'class_name':'com.theseus.fixture.Gauge'}
        _,cls=analyze('class',select)
        overloads=[m for m in cls['methods'] if m['name']=='normalize']
        assert len(overloads)==2 and [m['overload_index'] for m in overloads]==[0,1]
        assert {m['dex_descriptor'] for m in overloads}=={'(I)I','(Ljava/lang/String;)Ljava/lang/String;'}
        assert cls['fields'] and cls['inner_classes']
        _,activity=analyze('class',{'class_name':'com.theseus.fixture.GaugeActivity','include_code':True})
        assert any(m['synthetic'] for m in activity['methods']) and 'setContentView' in activity['code']
        # No arbitrary overload selection: a failed read retains the diagnostic.
        failed,ambiguous=run(client,pid,artifact['id'],'android.method',{**select,'method_name':'normalize'})
        assert ambiguous['status']=='reader-error' and 'overload_index' in ambiguous['observation']['stderr']
        for m in overloads:
            _,code=analyze('method',{**select,'method_name':'normalize','overload_index':m['overload_index']})
            assert code['method']['dex_descriptor']==m['dex_descriptor'] and code['code']
            assert not code['truncated'] and code['representation']=='decompiled-java'
        _,initializer=analyze('method',{**select,'method_name':'<clinit>'})
        assert initializer['representation']=='smali' and '.method static constructor <clinit>()V' in initializer['code']
        assert initializer['fallback_reason']=='static-initializer-can-be-folded'
        _,native=analyze('method',{**select,'method_name':'readNativeClock'})
        assert native['representation']=='declaration' and native['code'] is None
        integer=next(m for m in overloads if m['dex_descriptor']=='(I)I')
        job,refs=analyze('references',{**select,'method_name':'normalize','overload_index':integer['overload_index'],'resolve_lines':True,'limit':None})
        callers=refs['references']['rows']
        twice=next(r for r in callers if '.twice(' in r.get('raw_method_id',''))
        assert len(twice['direct_dex_invokes'])==2 and len({r['dex_code_unit_offset'] for r in twice['direct_dex_invokes']})==2
        assert twice['direct_invokes_exhaustive'] and twice['raw_instruction_stream_available']
        assert len(twice['decompiled_positions'])==2 and refs['count_semantics']=='containing nodes, not invoke instructions'
        indexed=client.get(f'/api/jobs/{job["id"]}/records/references.rows').json()
        assert indexed['total']==refs['references']['total']
        first=client.get(f'/api/jobs/{job["id"]}/records/references.rows/{indexed["records"][0]["record_key"]}').json()
        assert first['record']==callers[0]
        _,classrefs=analyze('references',{**select,'limit':None})
        assert classrefs['references']['total']>0
        dex=app.state.store.add_artifact(pid,source.parent/'dex/classes.dex')
        _,dexclasses=run(client,pid,dex['id'],'android.classes',{'query':'Gauge','include_inner':True})
        assert dexclasses['classes']['rows']==classes['classes']['rows']
        broken=source.parent/'broken.apk'
        broken.write_bytes(b'Not an APK or DEX')
        invalid=app.state.store.add_artifact(pid,broken)
        _,error=run(client,pid,invalid['id'],'android.package')
        assert error['status']=='unrecognized-input' and error['input_container']=='unknown'
        if not available('android.resources'):
            decoded,resources=analyze('resources')
            paths={r['relative_path'] for r in resources['artifacts']}
            assert 'AndroidManifest.xml' in paths and 'res/values/strings.xml' in paths
            links=app.state.store.artifact_links(pid)
            resource=next(link for link in links if link['source_location']=='res/values/strings.xml')
            child=app.state.store.artifact(pid,resource['child_id'])
            assert 'Original resource 128' in Path(child['path']).read_text()
            assert len(decoded['result']['derived_artifacts'])==len(paths)
        exported=app.state.evidence.export(pid)
        transfer=app.state.evidence.load(exported)
        imported=app.state.store.job(transfer['id_map'][job['id']])
        retained=json.loads(Path(imported['result']['analysis_file']).read_text(encoding='utf8'))
        assert retained['result']['references']==refs['references']
        assert len(app.state.store.artifact_links(transfer['project']['id']))==len(app.state.store.artifact_links(pid))
        assert digest(source)==original
