"""Portable figures retain a specific source while previewing one authored page."""
import base64
from copy import deepcopy
import io
from types import SimpleNamespace

from PIL import Image
import pytest

from test_diagram_editorial import sample
from vitruvius_hoard.diagrams.documents import DocumentStore
from vitruvius_hoard.diagrams.document_tools import DocumentGet, get
from vitruvius_hoard.diagrams.exchange import figure, import_document
import json


def test_figure_selected_page_retains_full_frozen_revision(tmp_path):
    store = DocumentStore(tmp_path)
    row = store.save(sample())
    before = deepcopy(row)
    exported = figure(row, page_id='detail', origin_url='http://127.0.0.1:54552/design/')
    assert row == before
    with Image.open(io.BytesIO(base64.b64decode(exported['preview']['data']))) as png:
        assert png.size == (800, 600)
    assert exported['content'] == row['content']
    assert exported['document_id'] == row['id'] and exported['revision'] == 1
    assert exported['origin']['editor_url'] == f'http://127.0.0.1:54552/design/#/diagrams?document={row["id"]}'
    changed = deepcopy(row['content']); changed['diagram']['title'] = 'Updated later'
    store.save(changed, did=row['id'], base_revision=1)
    assert exported['content']['diagram']['title'] == 'Informe de prueba'
    imported, _ = import_document(json.dumps(exported))
    assert imported == row['content']


def test_figure_api_and_mcp_read_have_exact_revision(client, tmp_path):
    row = client.post('/api/diagrams/documents', json={'content':sample()}).json()
    response = client.get(f'/api/diagrams/documents/{row["id"]}/export.vfigure?revision=1&page_id=cover')
    assert response.status_code == 200, response.text
    exported = response.json()
    assert exported['content'] == row['content'] and exported['page_id'] == 'cover'
    assert response.headers['content-disposition'].endswith('.vfigure"')
    with Image.open(io.BytesIO(base64.b64decode(exported['preview']['data']))) as png:
        assert png.size == (640, 480)
    store = DocumentStore(tmp_path)
    own = store.save(sample())
    svc = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path, port=54552))
    result = get(svc, DocumentGet(id=own['id'], revision=1, include_figure=True, page_id='detail'))
    assert result['figure']['content'] == own['content']
    assert result['figure']['page_id'] == 'detail'
    assert 'figure' not in get(svc, DocumentGet(id=own['id']))
    invalid = client.get(f'/api/diagrams/documents/{row["id"]}/export.vfigure?page_id=absent')
    assert invalid.status_code == 400


@pytest.mark.parametrize('origin', ['javascript:alert(1)', 'http://user:pass@localhost/'])
def test_figure_origin_links_are_plain_http_addresses(tmp_path, origin):
    row = DocumentStore(tmp_path).save(sample())
    with pytest.raises(ValueError):
        figure(row, origin_url=origin)
