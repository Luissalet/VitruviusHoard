from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_diagram_editorial import sample
from vitruvius_hoard.diagrams.documents import DocumentStore
from vitruvius_hoard.diagrams.styles import StyleStore
from vitruvius_hoard.diagrams.document_tools import StyleApply,style_apply,DocumentEdit,edit
from vitruvius_hoard.hoard_link.agentkit import AppError


def test_style_discovery_never_creates_store(tmp_path):
    library=StyleStore(tmp_path)
    assert library.list()==[]
    assert not library.documents.path.exists()
    with pytest.raises(LookupError):library.get('0'*12)
    assert not library.documents.path.exists()
    DocumentStore(tmp_path).save(sample())
    assert library.list()==[]
    with pytest.raises(LookupError):library.get('0'*12)
    assert library.list()==[]


def test_library_versions_merge_fields_and_keep_removed_source(tmp_path):
    library=StyleStore(tmp_path)
    first=library.save('Hallazgo',{'fill':'#123456','ink':'#ffffff'})
    second=library.save('Evidencia',first['values'],sid=first['id'],base_revision=1)
    third=library.save(first['name'],{**first['values'],'fill':'#445566'},sid=first['id'],base_revision=1)
    assert third['name']==second['name'] and third['values']['fill']=='#445566'
    with pytest.raises(AppError):library.save(first['name'],{'fill':'#667788','ink':'#ffffff'},sid=first['id'],base_revision=1)
    with pytest.raises(ValueError):library.remove(first['id'],2)
    assert library.list()[0]['revision']==3
    library.remove(first['id'],3)
    assert library.list()==[]
    assert library.get(first['id'],1)['values']==first['values']
    with pytest.raises(LookupError):library.get(first['id'])
    restored=library.save('Restaurado',first['values'],sid=first['id'],base_revision=3)
    assert restored['revision']==4 and library.list()[0]['id']==first['id']


@pytest.mark.parametrize('invalid',[{}, {'x':4},{'asset_id':'photo'},{'fill':'red'},{'font_size':500},{'align':'justify'},{'border':'no'}])
def test_style_rejects_content_geometry_and_invalid_appearance(tmp_path,invalid):
    with pytest.raises(ValueError):StyleStore(tmp_path).save('Inválido',invalid)
    assert StyleStore(tmp_path).list()==[]


def test_native_apply_copies_snapshot_and_preserves_later_fields(tmp_path):
    documents=DocumentStore(tmp_path);library=StyleStore(tmp_path)
    original=documents.save(sample());before=deepcopy(original['content'])
    style=library.save('Aviso',{'fill':'#eecc88','ink':'#111111','font_size':24,'align':'left'})
    nodes=[n['id'] for n in before['diagram']['nodes']]
    services=SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path))
    # A person moves a shape and edits text after the assistant read revision 1.
    moved=edit(services,DocumentEdit(id=original['id'],base_revision=1,edits=[
        {'collection':'view_nodes','id':nodes[0],'values':{'x':250}},
        {'collection':'nodes','id':nodes[0],'values':{'label':'Texto manual conservado'}}]))
    changed=style_apply(services,StyleApply(id=original['id'],base_revision=1,style_id=style['id'],style_revision=1,node_ids=nodes))
    for nid in nodes:
        assert all(changed['content']['view']['nodes'][nid][key]==value for key,value in style['values'].items())
        for key in ('asset_id','page_id','width','height'):
            assert changed['content']['view']['nodes'][nid].get(key)==before['view']['nodes'][nid].get(key)
    assert changed['content']['view']['nodes'][nodes[0]]['x']==250
    assert changed['content']['diagram']['nodes'][0]['label']=='Texto manual conservado'
    frozen=deepcopy(changed['content'])
    library.save('Aviso modificado',{'fill':'#ffffff'},sid=style['id'],base_revision=1)
    library.remove(style['id'],2)
    assert documents.get(original['id'])['content']==frozen
    undone=documents.undo(original['id'],changed['revision'])
    assert undone['content']==moved['content']
    # The retained style is reusable in another independent document.
    other=documents.save(sample())
    reused=style_apply(services,StyleApply(id=other['id'],base_revision=1,style_id=style['id'],style_revision=1,node_ids=[nodes[0]]))
    assert reused['content']['view']['nodes'][nodes[0]]['fill']=='#eecc88'


def test_same_style_field_conflicts_with_later_manual_change(tmp_path):
    documents=DocumentStore(tmp_path);original=documents.save(sample())
    nid=original['content']['diagram']['nodes'][0]['id']
    services=SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path))
    style=StyleStore(tmp_path).save('Nuevo',{'fill':'#112233'})
    edit(services,DocumentEdit(id=original['id'],base_revision=1,edits=[{'collection':'view_nodes','id':nid,'values':{'fill':'#eeffee'}}]))
    with pytest.raises(AppError):style_apply(services,StyleApply(id=original['id'],base_revision=1,style_id=style['id'],style_revision=1,node_ids=[nid]))
    assert documents.get(original['id'])['content']['view']['nodes'][nid]['fill']=='#eeffee'


def test_style_api_uses_same_snapshot_contract(client):
    style=client.post('/api/diagrams/styles',json={'name':'Lectura','values':{'fill':'#f0e0d0','font_size':20}})
    assert style.status_code==201,style.text
    style=style.json();assert client.get('/api/diagrams/styles').json()['styles'][0]['id']==style['id']
    row=client.post('/api/diagrams/documents',json={'content':sample()}).json()
    nid=row['content']['diagram']['nodes'][0]['id']
    changed=client.post('/api/diagrams/styles/apply',json={'id':row['id'],'base_revision':1,'style_id':style['id'],'style_revision':1,'node_ids':[nid]})
    assert changed.status_code==200,changed.text
    assert changed.json()['content']['view']['nodes'][nid]['fill']=='#f0e0d0'
    result=client.post('/api/diagrams/styles/remove',json={'id':style['id'],'base_revision':1})
    assert result.status_code==200
    assert client.get('/api/diagrams/styles').json()['styles']==[]
    assert client.get('/api/diagrams/styles/'+style['id']+'?revision=1').json()['values']==style['values']
