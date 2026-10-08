"""A failed source import must not be reported as a successful command."""
import json
import sys

import pytest

from scripts import ingest


@pytest.mark.parametrize('known,ok,expected', [(True, True, 0), (True, False, 1), (False, False, 1)])
def test_cli_exit_reflects_source_result(monkeypatch, tmp_path, capsys, known, ok, expected):
    source_root = tmp_path / 'fixture'
    (source_root / 'vitruvius_hoard').mkdir(parents=True)
    (source_root / 'vitruvius_hoard' / 'seeds.json').write_text(json.dumps({
        'sources': [{'id': 'demo', 'kind': 'local', 'url': str(tmp_path / 'docs')}] if known else []
    }), encoding='utf-8')
    monkeypatch.setattr(ingest, 'ROOT', source_root)
    monkeypatch.setattr(sys, 'argv', ['ingest.py', 'demo', '--data-dir', str(tmp_path / 'data')])
    calls = []

    def fake_ingest(db, config, row):
        calls.append(row['id'])
        return {'ok': ok, 'docs': 2, 'chunks': 5} if ok else {'ok': False, 'error': 'fetch failed'}

    monkeypatch.setattr(ingest, 'ingest_source', fake_ingest)
    assert ingest.main() == expected
    assert calls == (['demo'] if known else [])
    output = capsys.readouterr()
    if expected:
        assert ('fetch failed' if known else 'unknown source') in output.err
    else:
        assert '2 docs, 5 chunks' in output.out
