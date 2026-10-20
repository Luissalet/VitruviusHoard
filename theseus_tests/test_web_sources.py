"""Original retained-source fixtures; no target code is executed by the reader."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from theseus.web_sources import export_sources


def identity(data):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def capture():
    script = 'export { gauge } from "./gauge.js?v=2#ñ";\n// 😀\n'
    mapping = json.dumps({'version': 3, 'sources': ['../src/a.ts', '../src/a.ts'],
                         'sourcesContent': ['const ñ = 1;', 'const ñ = 2;'],
                         'names': ['gauge'], 'mappings': 'AAAAA,ACAAC;A'}, ensure_ascii=False).encode()
    result = {'scripts': [
        {'scriptId': '17', 'url': 'https://original.invalid/app.js?v=1', 'sourceMapURL': 'app.js.map',
         'source': {'state': 'captured', 'text': script, 'sha256': identity(script.encode())['sha256'],
                    'utf8_bytes': len(script.encode())}},
        {'scriptId': '18', 'url': 'https://original.invalid/app.js?v=2', 'source': {'state': 'excluded'}},
    ], 'network': [
        {'request_id': 'r1', 'name': 'https://original.invalid/app.js.map',
         'body': {'state': 'captured', 'representation': 'cdp-base64-bytes', **identity(mapping)}},
        {'request_id': 'r2', 'name': 'https://original.invalid/missing.js', 'body': {'state': 'unavailable'}},
    ], 'observations': [
        {'direction': 'sent', 'message': {'id': 23, 'method': 'Network.getResponseBody', 'params': {'requestId': 'r1'}}},
        {'direction': 'received', 'message': {'id': 23, 'result': {'body': base64.b64encode(mapping).decode(), 'base64Encoded': True}}},
    ]}
    return {'operation': 'browser.scenario', 'result': result}, script, mapping


def test_export_retained_sources_preserves_bytes_and_unavailable_occurrences(tmp_path):
    document, script, mapping = capture()
    raw = json.dumps(document, ensure_ascii=False).encode()
    result = export_sources(raw, tmp_path/'export')
    assert result['capture_sha256'] == identity(raw)['sha256']
    entries = result['entries']
    assert len(entries) == 4
    assert entries[0]['url'] != entries[1]['url']
    assert base64.b64decode(entries[0]['content_base64']) == script.encode()
    assert base64.b64decode(entries[2]['content_base64']) == mapping
    assert [row['state'] for row in entries] == ['captured', 'excluded', 'captured', 'unavailable']
    for row in result['artifacts']:
        data = (tmp_path/'export'/row['relative_path']).read_bytes()
        assert identity(data)['sha256'] == row['sha256']
    assert len([path for path in (tmp_path/'export').rglob('*') if path.is_file()]) == 3
    with pytest.raises(FileExistsError):
        export_sources(raw, tmp_path/'export')


@pytest.mark.parametrize('defect', ['script-hash', 'script-length', 'response-hash', 'response-length', 'duplicate-command', 'duplicate-reply', 'missing-reply'])
def test_export_does_not_publish_unverified_content(tmp_path, defect):
    document, _, _ = capture()
    if defect == 'script-hash':
        document['result']['scripts'][0]['source']['sha256'] = '0'*64
    elif defect == 'script-length':
        document['result']['scripts'][0]['source']['utf8_bytes'] += 1
    elif defect.startswith('response-'):
        document['result']['network'][0]['body']['sha256' if defect.endswith('hash') else 'bytes'] = '0'*64 if defect.endswith('hash') else 0
    elif defect == 'duplicate-command':
        document['result']['observations'].append(document['result']['observations'][0])
    elif defect == 'duplicate-reply':
        document['result']['observations'].append(document['result']['observations'][1])
    else:
        document['result']['observations'].pop()
    result = export_sources(json.dumps(document).encode(), tmp_path/'export')
    row = result['entries'][0 if defect.startswith('script-') else 2]
    assert row['state'] == 'unavailable' and row['reason']
    assert 'content_base64' not in row
    assert len(result['artifacts']) == 2


def run_trace(tmp_path, operation, exported, query, error=None):
    source = tmp_path/'export.json'; source.write_text(json.dumps({'operation': 'browser.export_scripts', 'result': exported}), encoding='utf8')
    request = tmp_path/'request.json'; output = tmp_path/'result.json'
    request.write_text(json.dumps({'operation': operation, 'path': str(source), 'expected_input_sha256': identity(source.read_bytes())['sha256'], 'parameters': {'query': query}}), encoding='utf8')
    worker = Path(__file__).resolve().parents[1]/'software_native/engine/dist/entry.js'
    process = subprocess.run(['node', str(worker), str(request), str(output)], capture_output=True, text=True)
    if error is not None:
        assert process.returncode != 0 and error in process.stderr, process.stderr
        return
    assert process.returncode == 0, process.stderr
    return json.loads(output.read_text(encoding='utf8'))['result']


def test_source_trace_preserves_duplicate_segments_and_unmapped_boundaries(tmp_path):
    document, _, _ = capture()
    # Duplicate generated positions, different source occurrence and name.
    mapping = {'version': 3, 'sources': ['../src/a.ts', '../src/a.ts'],
               'sourcesContent': ['first', 'second'], 'names': ['gauge'], 'mappings': 'AAAAA,ACAA;A'}
    exported = export_sources(json.dumps(document).encode(), tmp_path/'export')
    data = json.dumps(mapping).encode(); exported['entries'][2].update(identity(data), content_base64=base64.b64encode(data).decode())
    query = {'script_id': 'script-000000', 'map_id': 'response-000000', 'line': 1, 'column': 2}
    trace = run_trace(tmp_path, 'javascript.trace_source', exported, query)
    assert trace['state'] == 'mapped' and len(trace['mappings']) == 2
    assert [row['source_index'] for row in trace['mappings']] == [0, 1]
    assert [row['source_content'] for row in trace['mappings']] == ['first', 'second']
    assert all(row['resolved_url'] == 'https://original.invalid/src/a.ts' for row in trace['mappings'])
    assert trace['mappings'][0]['name'] == 'gauge'
    query.update(line=2, column=1)
    assert run_trace(tmp_path, 'javascript.trace_source', exported, query)['state'] == 'unmapped'
    query.update(line=3, column=0)
    assert run_trace(tmp_path, 'javascript.trace_source', exported, query)['state'] == 'unmapped'


def test_literal_import_trace_retains_url_versions_and_dynamic_unknowns(tmp_path):
    document, _, _ = capture()
    text = 'import "./gauge.js?v=2#ñ"; export {x} from "pkg/x"; import("./late.js"); import(variable); require("./cjs.js");'
    document['result']['scripts'][0]['source'].update(text=text, sha256=identity(text.encode())['sha256'], utf8_bytes=len(text.encode()))
    exported = export_sources(json.dumps(document).encode(), tmp_path/'export')
    result = run_trace(tmp_path, 'javascript.trace_imports', exported, {'script_id': 'script-000000', 'import_map': {'imports': {'pkg/': './lib/'}}})
    imports = result['imports']
    assert [row['resolved_url'] for row in imports if row['state'] == 'resolved'] == [
        'https://original.invalid/gauge.js?v=2#%C3%B1', 'https://original.invalid/lib/x', 'https://original.invalid/late.js']
    assert any(row['kind'] == 'dynamic-import' and row['state'] == 'computed-unknown' for row in imports)
    assert any(row['kind'] == 'commonjs-require' and row['state'] == 'runtime-resolution-unknown' for row in imports)
    assert all('line' in row and 'column' in row for row in imports)


@pytest.mark.parametrize('mappings', ['g', 'AA', 'AAAAAA', 'AAAA,', '!', 'ggggggggggggB'])
def test_source_trace_rejects_incomplete_or_invalid_vlq(tmp_path, mappings):
    document, _, _ = capture(); exported = export_sources(json.dumps(document).encode(), tmp_path/'export')
    data = json.dumps({'version': 3, 'sources': ['original.ts'], 'names': [], 'mappings': mappings}).encode()
    exported['entries'][2].update(identity(data), content_base64=base64.b64encode(data).decode())
    run_trace(tmp_path, 'javascript.trace_source', exported,
              {'script_id': 'script-000000', 'map_id': 'response-000000', 'line': 1, 'column': 0}, error='VLQ')


def test_indexed_maps_compose_offsets_and_keep_leaf_occurrences(tmp_path):
    document, _, _ = capture(); exported = export_sources(json.dumps(document).encode(), tmp_path/'export')
    leaf = {'version': 3, 'sources': ['original.ts'], 'sourcesContent': ['ñ😀'], 'names': [], 'mappings': 'AAAA;AACA'}
    mapping = {'version': 3, 'sections': [
        {'offset': {'line': 1, 'column': 7}, 'map': {'version': 3, 'sections': [
            {'offset': {'line': 1, 'column': 3}, 'map': leaf}]}},
        {'offset': {'line': 5, 'column': 0}, 'map': leaf},
    ]}
    data = ('\ufeff)]}\'\n'+json.dumps(mapping)).encode()
    exported['entries'][2].update(identity(data), content_base64=base64.b64encode(data).decode())
    query = {'script_id': 'script-000000', 'map_id': 'response-000000', 'line': 3, 'column': 4}
    result = run_trace(tmp_path, 'javascript.trace_source', exported, query)
    assert result['generated_position'] == {'line': 3, 'column': 3}
    assert result['mappings'][0]['section'] == [0, 0]
    assert result['mappings'][0]['source_content'] == 'ñ😀'
    query.update(line=4, column=0)
    result = run_trace(tmp_path, 'javascript.trace_source', exported, query)
    assert result['generated_position'] == {'line': 4, 'column': 0}
    assert result['mappings'][0]['original_line'] == 2
    query.update(line=6)
    assert run_trace(tmp_path, 'javascript.trace_source', exported, query)['mappings'][0]['section'] == [1]


def test_import_map_scopes_null_entries_and_prefix_escape(tmp_path):
    document, _, _ = capture()
    text = 'import "pkg/a"; import "pkg/../escape.js"; import "blocked"; import "fallback";'
    document['result']['scripts'][0]['source'].update(text=text, sha256=identity(text.encode())['sha256'], utf8_bytes=len(text.encode()))
    exported = export_sources(json.dumps(document).encode(), tmp_path/'export')
    result = run_trace(tmp_path, 'javascript.trace_imports', exported, {
        'script_id': 'script-000000', 'importer_url': 'https://original.invalid/nested/script.js',
        'import_map_base_url': 'https://original.invalid/maps/page.html',
        'import_map': {'imports': {'pkg/': './global/', 'blocked': './fallback.js', 'fallback': './fallback.js'},
                       'scopes': {'../nested/': {'pkg/': './scoped/', 'blocked': None}}}})
    assert result['imports'][0]['resolved_url'] == 'https://original.invalid/maps/scoped/a'
    assert result['imports'][1]['state'] == 'unresolved' and 'escapes' in result['imports'][1]['reason']
    assert result['imports'][2]['state'] == 'unresolved' and 'blocks' in result['imports'][2]['reason']
    assert result['imports'][3]['resolved_url'] == 'https://original.invalid/maps/fallback.js'


def test_import_resolution_matches_owned_browser_without_loading_modules(tmp_path):
    from browser_fixture import browser_fixture, browser_path
    from playwright.sync_api import sync_playwright
    if browser_path() is None:
        pytest.skip('Requires owned installed Chromium fixture')
    document, _, _ = capture()
    importer='https://original.invalid/nested/script.js?v=3'
    specifiers=['./gauge.js?v=2#ñ','/root.js','//other.invalid/a.js','pkg/a','pkg/../escape.js',
                'blocked','fallback','bare','#fragment','?query','https://original.invalid/nested/../absolute.js',
                'custom:pkg/a','data:text/javascript,export default 1','\\relative.js','../ñ.js','pkg/%2e%2e/escape.js']
    import_map={'imports':{'pkg/':'./global/','blocked':'./fallback.js','fallback':'./fallback.js',
                           'custom:pkg/':'./custom/'},
                'scopes':{'./nested/':{'pkg/':'./scoped/','blocked':None}}}
    text='\n'.join('import '+json.dumps(value)+';' for value in specifiers)
    document['result']['scripts'][0]['source'].update(text=text, sha256=identity(text.encode())['sha256'], utf8_bytes=len(text.encode()))
    exported=export_sources(json.dumps(document).encode(),tmp_path/'export')
    result=run_trace(tmp_path,'javascript.trace_imports',exported,{
        'script_id':'script-000000','importer_url':importer,'import_map_base_url':'https://original.invalid/', 'import_map':import_map})
    # The oracle is the browser's module resolver. Only our constant resolver
    # stub runs; no captured script, module import or external URL is loaded.
    with browser_fixture(tmp_path/'resolver') as target,sync_playwright() as playwright:
        browser=playwright.chromium.connect_over_cdp(target['endpoint'])
        context=browser.new_context();page=context.new_page();requests=[]
        page.on('request',lambda request:requests.append(request.url))
        # Absolute addresses keep the map's base distinct from the importer's.
        normalized={'imports':{'pkg/':'https://original.invalid/global/','blocked':'https://original.invalid/fallback.js',
                               'fallback':'https://original.invalid/fallback.js','custom:pkg/':'https://original.invalid/custom/'},
                    'scopes':{'https://original.invalid/nested/':{'pkg/':'https://original.invalid/scoped/','blocked':None}}}
        page.set_content('<base href="'+importer+'"><script type="importmap">'+json.dumps(normalized)+
                         '</script><script type="module">globalThis.originalResolver=s=>{try{return {state:"resolved",url:import.meta.resolve(s)}}catch{return {state:"unresolved"}}};</script>')
        page.wait_for_function('typeof globalThis.originalResolver === "function"')
        observed=page.evaluate('(specifiers)=>specifiers.map(globalThis.originalResolver)',specifiers)
        assert requests==[]
        context.close()
    assert len(observed)==len(result['imports'])
    for original,row in zip(observed,result['imports']):
        assert row['state']==original['state'],(row,original)
        if original['state']=='resolved':assert row['resolved_url']==original['url'],(row,original)


def test_export_url_layout_isolates_versions_collisions_and_windows_paths(tmp_path):
    document, script, _ = capture()
    source=document['result']['scripts'][0]['source']
    urls=['https://original.invalid/js/main.js','https://original.invalid/js/ñ.js',
          'https://original.invalid/JS/same.js','https://original.invalid/js/SAME.js',
          'https://original.invalid/js/main.js?v=2','https://original.invalid/../outside.js',
          'https://original.invalid/CON/file.js','https://original.invalid/js/%2fescape.js',
          'https://original.invalid/file.js','https://original.invalid/file.js/child.js']
    document['result']['scripts']=[{'scriptId':str(i),'url':url,'source':source} for i,url in enumerate(urls)]
    document['result']['network']=[]
    result=export_sources(json.dumps(document).encode(),tmp_path/'export')
    entries=result['entries']
    assert entries[0]['relative_path']=='urls/https/original.invalid/js/main.js'
    assert entries[1]['relative_path']=='urls/https/original.invalid/js/ñ.js'
    assert all(row['layout']=='isolated-occurrence' for row in entries[2:])
    assert len({row['relative_path'].casefold() for row in entries})==len(urls)
    for row in entries:
        path=(tmp_path/'export'/row['relative_path']).resolve()
        assert path.is_relative_to((tmp_path/'export').resolve())
        assert path.read_bytes()==script.encode()


def test_browser_export_and_queries_after_close_and_evidence_transfer(tmp_path):
    from fastapi.testclient import TestClient
    from browser_fixture import browser_fixture, browser_path
    from test_browser_runtime import observe, target_id
    from test_native_analysis import wait
    from theseus.api import create_app
    if browser_path() is None:
        pytest.skip('Requires owned installed Chromium fixture')
    mapping = {'version': 3, 'sources': ['source-ñ.ts'], 'sourcesContent': ['const gauge = "😀";'], 'names': ['gauge'], 'mappings': 'AAAAA'}
    inline = 'data:application/json;base64,'+base64.b64encode(json.dumps(mapping, ensure_ascii=False).encode()).decode()
    extra = '\nfunction lazyOriginal(){return import("./late.js?v=2#fragment");}\n//# sourceMappingURL='+inline+'\n'
    with TestClient(create_app(tmp_path/'data'), base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;project=store.create_project('Portable original web sources')['id']
        with browser_fixture(tmp_path/'browser', extra_script=extra) as target:
            chosen=target_id(client,project,target)
            job,_=observe(client,project,'observe',{'inspector_endpoint':target['endpoint'],'target_id':chosen,
                'observation_ms':650,'capture_sources':True,'capture_response_bodies':True})
        for path in target['root'].iterdir():
            path.unlink()

        def start(pid, source, operation, query=None):
            parameters={'source_job_id':source['id']}
            if query is not None:parameters['query']=query
            response=client.post('/api/agent/call',json={'tool':'theseus_analysis_start','arguments':{
                'project_id':pid,'artifact_id':source['result']['artifact_id'],'operation':operation,'parameters':parameters}})
            response.raise_for_status();fresh=wait(client,response.json()['result'])
            assert fresh['state']=='finished',fresh
            return fresh,client.get('/api/jobs/'+fresh['id']+'/analysis.json').json()['result']

        exported,result=start(project,job,'browser.export_scripts')
        assert exported['result']['derived_artifacts']
        script=next(row for row in result['entries'] if row['kind']=='page-script' and row['url'].endswith('/original-%C3%B1.js'))
        source_map=next(row for row in result['entries'] if row.get('script_entry_id')==script['id'])
        query={'script_id':script['id'],'map_id':source_map['id'],'line':1,'column':3}
        _,traced=start(project,exported,'javascript.trace_source',query)
        assert traced['mappings'][0]['source_content']=='const gauge = "😀";'
        _,imports=start(project,exported,'javascript.trace_imports',{'script_id':script['id']})
        assert any(row.get('resolved_url','').endswith('/late.js?v=2#fragment') for row in imports['imports'])
        bundle=client.app.state.evidence.export(project)
        imported=client.app.state.evidence.load(bundle);pid=imported['project']['id']
        for row in exported['result']['derived_artifacts']:
            Path(store.artifact(project,row['id'])['path']).unlink()
        # A new export and new trace use retained JSON only; imported jobs remain historical.
        moved_capture=store.job(imported['id_map'][job['id']])
        fresh,_=start(pid,moved_capture,'browser.export_scripts')
        _,actual=start(pid,fresh,'javascript.trace_source',query)
        assert actual==traced
        moved_export=store.job(imported['id_map'][exported['id']])
        _,direct=start(pid,moved_export,'javascript.trace_source',query)
        assert direct==traced
        assert not client.get('/api/projects/'+pid).json()['runtime_sessions']
        # A source from another project is not silently selected by a global job ID.
        bad=client.post('/api/agent/call',json={'tool':'theseus_analysis_start','arguments':{
            'project_id':project,'artifact_id':exported['result']['artifact_id'],'operation':'javascript.trace_source',
            'parameters':{'source_job_id':moved_export['id'],'query':query}}})
        assert bad.status_code==400
