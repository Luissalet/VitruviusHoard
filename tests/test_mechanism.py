"""Authored poses preserve originals, retained revisions and independent edits."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from vitruvius_hoard.diagrams.documents import DocumentStore, normalize, drawing
from vitruvius_hoard.diagrams.document_tools import DocumentEdit, DocumentGet, edit, get
from vitruvius_hoard.diagrams.exchange import figure, import_document
from vitruvius_hoard.diagrams.mechanism import diagram_for
from vitruvius_hoard.diagrams.reader import reader, compare


def sample():
    return {'diagram': {'type':'isometric', 'title':'Conjunto de prueba', 'pieces':[
        {'id':'base','kind':'slab','plan':{'x':0,'y':0,'w':120,'d':80},'h':10,'label':'Base'},
        {'id':'lid','kind':'plate','plan':{'x':5,'y':5,'w':110,'d':70},'z':10,'h':5,'label':'Tapa','lit':True},
        {'id':'knob','kind':'cylinder','plan':{'cx':60,'cy':40,'r':12},'z':15,'h':12}]},
        'mechanism':{'parts':[{'id':'lid','description':'Tapa desmontable. Fuente: dibujo del autor.'}],
        'states':[{'id':'open','title':'Desmontado','description':'Separación explicativa de la tapa.',
                   'poses':{'lid':{'dz':40},'knob':{'dz':40}},'hidden':[],'focus_piece':'lid'},
                  {'id':'inside','title':'Interior','hidden':['lid','knob'],'poses':{},'focus_piece':'base'}]}}


def test_derived_geometry_keeps_original_and_hidden_sources(tmp_path):
    row=DocumentStore(tmp_path).save(sample()); original=deepcopy(row)
    moved=diagram_for(row['content'],'open')
    assert moved['pieces'][1]['z']==50 and row['content']['diagram']['pieces'][1]['z']==10
    assert len(diagram_for(row['content'],'inside')['pieces'])==1
    assert row==original
    assert drawing(row['content'],'open')['svg']['light']!=row['rendering']['svg']['light']
    assert 'data-piece="lid"' not in drawing(row['content'],'inside')['svg']['light']


def test_native_part_and_state_edits_merge_and_selective_undo(tmp_path):
    store=DocumentStore(tmp_path);row=store.save(sample())
    svc=SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path,port=54580))
    def apply(revision,changes):return edit(svc,DocumentEdit(id=row['id'],base_revision=revision,edits=changes))
    apply(1,[{'collection':'mechanism_states','id':'open','values':{'description':'Explicación manual conservada'}}])
    changed=apply(1,[{'collection':'pieces','id':'lid','values':{'label':'Cubierta'}},
                     {'collection':'mechanism_parts','id':'lid','values':{'description':'Nueva fuente'}}])
    assert changed['revision']==3
    assert changed['content']['mechanism']['states'][0]['description']=='Explicación manual conservada'
    apply(3,[{'collection':'mechanism_states','id':'inside','values':{'title':'Interior manual'}}])
    undone=store.undo(row['id'],3)
    assert undone['content']['diagram']['pieces'][1]['label']=='Tapa'
    assert undone['content']['mechanism']['states'][0]['description']=='Explicación manual conservada'
    assert undone['content']['mechanism']['states'][1]['title']=='Interior manual'
    assert store.get(row['id'],3)['content']==changed['content']
    assert compare(row,store.get(row['id']))['mechanism_changed']
    with pytest.raises(Exception,match='changed'):
        apply(1,[{'collection':'mechanism_states','id':'open','values':{'description':'Conflicto'}}])


@pytest.mark.parametrize('mutation',[
    lambda c:c['mechanism']['parts'].append({'id':'missing','description':'Wrong'}),
    lambda c:c['mechanism']['states'][0]['poses'].update(missing={'dz':2}),
    lambda c:c['mechanism']['states'][0].update(hidden=['base','lid','knob']),
    lambda c:c['mechanism']['states'][0].update(hidden=['lid']),
    lambda c:c['mechanism']['states'][0]['poses']['lid'].update(dz=float('inf')),
    lambda c:c['mechanism']['states'][0]['poses']['lid'].update(dz=6000),
    lambda c:c['mechanism']['states'].append(deepcopy(c['mechanism']['states'][0])),
])
def test_invalid_states_rejected_before_saving(mutation,tmp_path):
    content=sample();mutation(content)
    with pytest.raises(ValueError):DocumentStore(tmp_path).save(content)
    assert not DocumentStore(tmp_path).list()


def test_reader_keeps_explanations_safe_and_all_states(tmp_path):
    content=sample();content['mechanism']['parts'][0]['description']='</script><img src=x onerror=bad()>'
    row=DocumentStore(tmp_path).save(content)
    html=reader(row,'open')
    assert '\\u003c/script>' in html and '<img src=x onerror=bad()>' not in html
    assert '"initial": "open"' in html and 'Interior' in html and 'data-piece' in html
    with pytest.raises(ValueError,match='Unknown'):reader(row,'missing')


def test_api_and_portable_figure_capture_state_not_mutated_source(client,tmp_path):
    response=client.post('/api/diagrams/documents',json={'content':sample()});assert response.status_code==201,response.text
    row=response.json();url=f'/api/diagrams/documents/{row["id"]}'
    svg=client.get(url+'/export.svg?state_id=inside');assert svg.status_code==200
    assert 'data-piece="lid"' not in svg.text
    preview=client.post('/api/diagrams/documents/preview',json={'content':row['content'],'state_id':'inside'})
    assert preview.status_code==200 and preview.json()['rendering']['svg']['light']==svg.text
    captured=client.get(url+'/export.vfigure?state_id=inside');assert captured.status_code==200,captured.text
    captured=captured.json();assert captured['state_id']=='inside' and captured['content']==row['content']
    assert len(import_document(json.dumps(captured))[0]['diagram']['pieces'])==3
    assert client.get(url+'/viewer?state_id=missing').status_code==404
    assert client.get(url+'/export.vfigure?state_id=missing').status_code==400
    assert client.get(url).json()['content']==row['content']
    own=DocumentStore(tmp_path).save(sample());svc=SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path,port=54580))
    got=get(svc,DocumentGet(id=own['id'],state_id='inside',include_svg=True,include_figure=True))
    assert got['rendering']['svg']['light']==svg.text
    assert got['figure']['state_id']=='inside' and got['figure']['content']==own['content']
    assert got['state_id']=='inside' and got['exports']['png'].endswith('&state_id=inside')
    assert got['files']['light'].endswith('&state_id=inside')


def test_a_graph_cannot_silently_ignore_a_requested_state():
    graph=normalize({'diagram':{'type':'flowchart','nodes':[{'id':'a'}]}})
    with pytest.raises(ValueError,match='isometric'):drawing(graph,'open')
