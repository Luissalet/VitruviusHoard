"""SQLite reader against databases written and read by an independent SQLite binding.

The databases are written by Node's built-in SQLite in a separate process, which keeps its
WAL connection open while the product reads. The expected schema and exact typed cell values
also come from that binding, not from the Python module the reader uses.
"""
import base64
import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest

from test_native_analysis import wait
from test_portfolio import run
from theseus.api import create_app
from theseus.native_analysis import engine

SCHEMA = r'''
PRAGMA journal_mode=WAL;
PRAGMA wal_autocheckpoint=0;
PRAGMA foreign_keys=ON;
CREATE TABLE owner(id INTEGER PRIMARY KEY, "display ""name""" TEXT NOT NULL UNIQUE);
CREATE TABLE measure(
  id INTEGER PRIMARY KEY,
  owner_id INTEGER REFERENCES owner(id) ON DELETE CASCADE,
  amount INTEGER,
  ratio REAL,
  note TEXT,
  payload BLOB,
  doubled INTEGER GENERATED ALWAYS AS (amount * 2) VIRTUAL,
  label TEXT GENERATED ALWAYS AS ('#' || id) STORED
);
CREATE TABLE strict_pair(k TEXT PRIMARY KEY, v INTEGER NOT NULL) STRICT, WITHOUT ROWID;
CREATE INDEX measure_owner ON measure(owner_id) WHERE owner_id IS NOT NULL;
CREATE UNIQUE INDEX measure_note ON measure(note);
CREATE VIEW owner_totals AS SELECT owner_id, sum(amount) AS total FROM measure GROUP BY owner_id;
CREATE TRIGGER measure_guard BEFORE INSERT ON measure WHEN NEW.amount = 13 BEGIN SELECT RAISE(ABORT, 'unlucky'); END;
CREATE VIRTUAL TABLE search USING fts5(body);
'''

WRITER = r'''
import {DatabaseSync} from 'node:sqlite';
const [path, schema] = process.argv.slice(1);
const db = new DatabaseSync(path);
db.exec(schema);
db.exec(`INSERT INTO owner VALUES (1, 'árbol'), (2, 'ok')`);
const insert = db.prepare('INSERT INTO measure(id, owner_id, amount, ratio, note, payload) VALUES (?, ?, ?, ?, ?, ?)');
insert.setAllowBareNamedParameters?.(true);
insert.run(1, 1, 9223372036854775807n, -0.0, 'first', new Uint8Array([0, 128, 255]));
insert.run(2, 1, -9223372036854775808n, 1.5e300, 'second', null);
insert.run(3, null, 9007199254740993n, 0.1, null, new Uint8Array([]));
db.exec(`INSERT INTO measure(id, owner_id, amount, ratio, note) VALUES (4, 2, 7, 9e999, CAST(x'80FF41' AS TEXT))`);
db.exec(`INSERT INTO strict_pair VALUES ('b', 2), ('a', 1)`);
db.exec(`INSERT INTO search(body) VALUES ('ingeniería inversa'), ('observed bytes')`);
process.stdout.write('ready\n');
process.stdin.once('data', () => { db.close(); process.exit(0); });
'''

ORACLE = r'''
import {DatabaseSync} from 'node:sqlite';
const [path, query] = process.argv.slice(1);
const db = new DatabaseSync(path, {readOnly: true});
const schema = db.prepare('SELECT type, name, tbl_name AS "table", sql FROM sqlite_schema ORDER BY type, name').all();
const quote = name => '"' + name.replaceAll('"', '""') + '"';
const tables = schema.filter(row => ['table', 'view'].includes(row.type) && !row.name.startsWith('sqlite_')).map(row => ({
  name: row.name, kind: row.type,
  columns: db.prepare(`PRAGMA table_xinfo(${quote(row.name)})`).all().map(Object.values),
  foreign_keys: db.prepare(`PRAGMA foreign_key_list(${quote(row.name)})`).all().map(Object.values),
  indexes: db.prepare(`PRAGMA index_list(${quote(row.name)})`).all().map(Object.values)}));
const statement = db.prepare(query);
const columns = statement.columns().map(column => column.name);
const cells = [];
for (const name of columns) {
  const typed = db.prepare(`SELECT typeof(${quote(name)}) AS t, CAST(${quote(name)} AS TEXT) AS d, hex(${quote(name)}) AS h,
    printf('%!.17g', ${quote(name)}) AS r FROM (${query})`).all();
  cells.push(typed);
}
const rows = cells.length ? cells[0].map((_, index) => cells.map(column => column[index])) : [];
process.stdout.write(JSON.stringify({schema, tables, columns, rows}));
'''

QUERY = 'SELECT id, owner_id, amount, ratio, note, payload, doubled, label FROM measure ORDER BY id'


def node(script, *arguments, **options):
    return subprocess.run([engine()['node'], '--no-warnings', '--input-type=module', '-e', script, *arguments],
                          capture_output=True, text=True, encoding='utf8', **options)


def canonical(cell):
    if cell is None:
        return ('null', None)
    if isinstance(cell, bool):
        raise AssertionError('Unexpected boolean cell')
    if isinstance(cell, int):
        return ('integer', str(cell))
    if isinstance(cell, float):
        return ('real', cell)
    if isinstance(cell, str):
        return ('text', cell.encode('utf8').hex().upper())
    kind = cell['type']
    if kind == 'integer':
        return ('integer', cell['decimal'])
    if kind == 'real':
        return ('real', float(cell['representation']))
    if kind == 'text':
        return ('text', base64.b64decode(cell['base64']).hex().upper())
    if kind == 'blob':
        return ('blob', base64.b64decode(cell['base64']).hex().upper())
    raise AssertionError(cell)


def expected(cell):
    kind = cell['t']
    if kind == 'null':
        return ('null', None)
    if kind == 'integer':
        return ('integer', cell['d'])
    if kind == 'real':
        text = cell['r'].replace('Inf', 'inf')
        return ('real', float(text))
    return (kind, cell['h'])


@pytest.fixture
def written(tmp_path):
    source = tmp_path / 'written.sqlite'
    writer = subprocess.Popen([engine()['node'], '--no-warnings', '--input-type=module', '-e', WRITER, str(source), SCHEMA],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf8')
    try:
        line = writer.stdout.readline()
        assert line == 'ready\n', writer.stderr.read()
        assert Path(str(source) + '-wal').stat().st_size > 0
        yield source
    finally:
        if writer.poll() is None:
            writer.stdin.write('done\n')
            writer.stdin.flush()
            writer.wait(timeout=10)


def test_independently_written_wal_family_schema_and_exact_values(tmp_path, written):
    oracle = json.loads(node(ORACLE, str(written), QUERY, check=True).stdout)
    family = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.name.startswith('written.sqlite')}
    with TestClient(create_app(tmp_path / 'profile', port=64229), base_url='http://127.0.0.1:64229') as client:
        client.get('/')
        store = client.app.state.store
        pid = store.create_project('Independent SQLite')['id']
        artifact = store.add_artifact(pid, written)
        _, result = run(client, pid, artifact['id'], 'sqlite.database', {'query': QUERY})
        _, paged = run(client, pid, artifact['id'], 'sqlite.database', {'query': QUERY, 'offset': 1, 'limit': 2})
        _, table = run(client, pid, artifact['id'], 'sqlite.database', {'table': 'strict_pair'})
        _, fts = run(client, pid, artifact['id'], 'sqlite.database', {'query': "SELECT body FROM search WHERE search MATCH 'bytes'"})
        _, pragma = run(client, pid, artifact['id'], 'sqlite.database', {'query': 'PRAGMA table_xinfo(measure)'})
        _, check = run(client, pid, artifact['id'], 'sqlite.database', {'query': 'PRAGMA integrity_check'})
    assert result['schema'] == oracle['schema']
    assert result['tables'] == oracle['tables']
    assert {row['name'] for row in result['tables']} >= {'owner', 'measure', 'strict_pair', 'owner_totals', 'search'}
    assert any(row['type'] == 'trigger' and row['name'] == 'measure_guard' for row in result['schema'])
    assert result['columns'] == oracle['columns']
    assert [[canonical(cell) for cell in row['values']] for row in result['rows']] == [[expected(cell) for cell in row] for row in oracle['rows']]
    assert [row['ordinal'] for row in result['rows']] == [0, 1, 2, 3]
    # REAL affinity stores an integral -0.0 as integer 0; both readers agree on 0.0 above.
    assert result['rows'][0]['values'][3] == 0.0
    assert result['rows'][3]['values'][3] == {'type': 'real', 'representation': 'inf'}
    assert result['rows'][3]['values'][4]['invalid_utf8'] is True
    assert {'written.sqlite', 'written.sqlite-wal'} <= set(result['source_files'])
    assert [row['ordinal'] for row in paged['rows']] == [1, 2] and paged['coverage']['rows_returned'] == 2
    assert table['columns'] == ['k', 'v'] and [row['values'] for row in table['rows']] == [['a', 1], ['b', 2]]
    assert [row['values'] for row in fts['rows']] == [['observed bytes']]
    assert [row['values'] for row in pragma['rows']] == next(row['columns'] for row in oracle['tables'] if row['name'] == 'measure')
    assert [row['values'] for row in check['rows']] == [['ok']]
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.name.startswith('written.sqlite')} == family


@pytest.mark.parametrize('parameters,reason', [
    ({'query': "INSERT INTO owner VALUES (3, 'x')"}, 'not authorized'),
    ({'query': 'PRAGMA journal_mode=DELETE'}, 'not authorized'),
    ({'query': 'PRAGMA user_version=5'}, 'not authorized'),
    ({'query': 'PRAGMA wal_checkpoint(TRUNCATE)'}, 'not authorized'),
    ({'query': 'UPDATE measure SET amount = 1'}, 'not authorized'),
    ({'query': 'CREATE TEMP TABLE scratch(x)'}, 'not authorized'),
    ({'query': "ATTACH DATABASE 'other.sqlite' AS other"}, 'not authorized'),
    ({'query': 'VACUUM'}, 'authorization denied'),
    ({'table': 'missing'}, 'Select an existing table or view'),
])
def test_writes_pragmas_and_unknown_tables_are_rejected_without_changing_the_family(tmp_path, written, parameters, reason):
    family = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.name.startswith('written.sqlite')}
    with TestClient(create_app(tmp_path / 'profile', port=64229), base_url='http://127.0.0.1:64229') as client:
        client.get('/')
        store = client.app.state.store
        pid = store.create_project('Rejected SQLite')['id']
        artifact = store.add_artifact(pid, written)
        reply = client.post(f'/api/projects/{pid}/artifacts/{artifact["id"]}/analyses', json={'operation': 'sqlite.database', 'parameters': parameters})
        reply.raise_for_status()
        job = wait(client, reply.json())
    assert job['state'] == 'failed' and job['result']['execution']['exit_code'] != 0
    # The authorizer itself must refuse, not an earlier parse error.
    assert reason in job['result']['execution']['stderr'], job['result']['execution']['stderr']
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.name.startswith('written.sqlite')} == family
    assert node(ORACLE, str(written), 'SELECT count(*) AS n FROM owner', check=True).stdout


def test_non_sqlite_file_is_a_reported_failure(tmp_path):
    source = tmp_path / 'not.sqlite'
    source.write_bytes(b'SQLite format 2\0' + b'\0' * 100)
    with TestClient(create_app(tmp_path / 'profile', port=64229), base_url='http://127.0.0.1:64229') as client:
        client.get('/')
        store = client.app.state.store
        pid = store.create_project('Not SQLite')['id']
        artifact = store.add_artifact(pid, source)
        reply = client.post(f'/api/projects/{pid}/artifacts/{artifact["id"]}/analyses', json={'operation': 'sqlite.database', 'parameters': {}})
        reply.raise_for_status()
        job = wait(client, reply.json())
    assert job['state'] == 'failed' and 'database' in job['result']['execution']['stderr'].lower()
