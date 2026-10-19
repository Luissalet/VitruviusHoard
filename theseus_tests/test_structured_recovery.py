import base64
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from test_portfolio import run
from theseus.api import create_app
from theseus.inspection import digest


def test_sqlite_retains_wal_rows_blob_int64_and_readonly_queries(tmp_path):
    source = tmp_path / 'source.sqlite'
    writer = sqlite3.connect(source)
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE parent(id INTEGER PRIMARY KEY)')
        writer.execute('CREATE TABLE item(id INTEGER REFERENCES parent(id), payload BLOB, amount INTEGER, note TEXT)')
        writer.execute('INSERT INTO parent VALUES (1)')
        writer.execute('INSERT INTO item VALUES (1,?,?,?)', (bytes([0,128,255]), 2**63-1, 'árbol'))
        writer.commit()
        originals = {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
        app = create_app(tmp_path / 'data')
        with TestClient(app, base_url='http://127.0.0.1:5217') as client:
            client.get('/')
            pid = app.state.store.create_project('SQLite family')['id']
            artifact = app.state.store.add_artifact(pid, source)
            job, result = run(client, pid, artifact['id'], 'sqlite.database', {'query': 'SELECT * FROM item WHERE id=? ORDER BY id', 'bindings': [1]})
            assert result['columns'] == ['id', 'payload', 'amount', 'note']
            assert result['rows'][0]['values'] == [1, {'type': 'blob', 'bytes': 3, 'base64': base64.b64encode(bytes([0,128,255])).decode()}, {'type': 'integer', 'decimal': str(2**63-1)}, 'árbol']
            assert any(row['name'] == 'item' and row['foreign_keys'] for row in result['tables'])
            assert source.name + '-wal' in result['source_files']
            _, unusual = run(client, pid, artifact['id'], 'sqlite.database', {'query': "SELECT 1e999,CAST(x'80FF' AS TEXT)"})
            assert unusual['rows'][0]['values'] == [{'type': 'real', 'representation': 'inf'},
                {'type': 'text', 'invalid_utf8': True, 'base64': base64.b64encode(bytes([128,255])).decode()}]
            assert all(path.read_bytes() == content for path, content in originals.items())
            assert not (Path(job['result']['analysis_file']).parent / 'sqlite-input').exists()
            for query in ['DELETE FROM item', "ATTACH DATABASE '" + str(tmp_path / 'must-not-exist.sqlite') + "' AS other"]:
                reply = client.post(f'/api/projects/{pid}/artifacts/{artifact["id"]}/analyses', json={'operation': 'sqlite.database', 'parameters': {'query': query}})
                from test_native_analysis import wait
                failed = wait(client, reply.json())
                assert failed['state'] == 'failed'
                assert not (Path(failed['result']['execution']['argv'][-1]).parent / 'sqlite-input').exists()
            assert not (tmp_path / 'must-not-exist.sqlite').exists()
            assert all(path.read_bytes() == content for path, content in originals.items())
    finally:
        writer.close()


def test_recovery_preserves_original_utf8_ranges_maps_and_does_not_run_code(tmp_path):
    source = tmp_path / 'bundle.js'
    marker = tmp_path / 'must-not-exist'
    text = '/* árbol */ var modules={0:function(module,exports,require){exports["normalize"]=n=>n<10?n+(64+64):-1;}};\n' + 'require("fs").writeFileSync(' + json.dumps(str(marker)) + ',"executed");'
    source.write_text(text, encoding='utf-8')
    before = source.read_bytes()
    app = create_app(tmp_path / 'data')
    with TestClient(app, base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        pid = app.state.store.create_project('Recovery')['id']
        artifact = app.state.store.add_artifact(pid, source)
        job, result = run(client, pid, artifact['id'], 'javascript.recover', {'query': {'rewrite_level': 'aggressive'}})
        assert not marker.exists() and source.read_bytes() == before
        assert len(result['modules']) == 1
        module = result['modules'][0]
        interval = module['byte_ranges'][0]
        assert before[interval['start']:interval['end']].decode('utf-8') == module['original_text']
        recovered = (Path(result['output_root']) / module['artifact']['relative_path']).read_text(encoding='utf-8')
        assert 'exports.normalize' in recovered and '128' in recovered
        assert module['source_map']
        mapping = json.loads((Path(result['output_root']) / module['source_map']['relative_path']).read_text(encoding='utf-8'))
        assert mapping['sourcesContent'] == [before.decode('utf-8')]
        assert len(app.state.store.artifact_links(pid)) == len(result['artifacts'])
        assert len(job['result']['derived_artifacts']) == len(result['artifacts'])
        transferred = app.state.evidence.load(app.state.evidence.export(pid))
        assert all(row['id'] in {artifact['id'] for artifact in app.state.store.items('artifacts', transferred['project']['id'])}
                   for receipt in app.state.store.items('jobs', transferred['project']['id']) for row in receipt['result'].get('derived_artifacts', []))
        assert digest(source) == artifact['sha256']
