"""Retained editorial pages keep semantic identities through edits and exports."""
from copy import deepcopy
import base64
import io
import json
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from PIL import Image
import pytest

from vitruvius_hoard.diagrams.documents import DocumentStore, normalize
from vitruvius_hoard.diagrams.document_tools import DocumentEdit, edit, public
from vitruvius_hoard.diagrams.exchange import drawio, import_document, image


def sample():
    buf=io.BytesIO()
    Image.new('RGB',(12,12),'#12ab45').save(buf,format='PNG')
    return {'diagram':{'type':'flowchart','title':'Informe de prueba','nodes':[
        {'id':'heading','label':'Comparación de costes: 25,50 €'}, {'id':'body','label':'Texto editable con acentos. ' * 14}],
        'edges':[{'id':'link','from':'heading','to':'body','label':'Detalle'}]},
        'view':{'kind':'infographic','pages':[{'id':'cover','title':'Comparación','width':640,'height':480,'order':0},
                                             {'id':'detail','title':'Detalle','width':800,'height':600,'order':1}],
                'assets':{'picture':{'name':'Synthetic green square','data':'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()}},
                'nodes':{'heading':{'page_id':'cover','x':30,'y':40,'width':580,'height':180,'font_size':32,'font_weight':700,'align':'left','border':False,'asset_id':'picture'},
                         'body':{'page_id':'detail','x':40,'y':40,'width':720,'height':500,'font_size':22,'font_weight':400,'align':'left','border':False}}}}


def test_pages_retain_long_text_images_and_frozen_render(tmp_path):
    row=DocumentStore(tmp_path).save(sample())
    assert [p['id'] for p in row['rendering']['pages']]==['cover','detail']
    cover,detail=row['rendering']['pages']
    assert cover['scene']['boxes']['heading']['x']==30
    assert 'font-size="32"' in cover['svg']['light']
    assert 'data:image/png;base64,' in cover['svg']['light']
    assert 'data-node-id="body"' not in cover['svg']['light']
    assert 'data-node-id="heading"' not in detail['svg']['light']
    assert len(row['content']['diagram']['nodes'][1]['label'])>160
    assert row['content']['diagram']['edges'][0]['id']=='link'
    small=public(row)
    assert 'svg' not in small['rendering'] and 'svg' not in small['rendering']['pages'][0]
    assert row['rendering']['pages'][0]['svg']  # response filtering never mutates the source


def test_independent_page_edits_merge_and_undo_keeps_other_page(tmp_path):
    store=DocumentStore(tmp_path)
    first=store.save(sample())
    a=deepcopy(first['content']); a['view']['pages'][0]['title']='Portada corregida'
    second=store.save(a,did=first['id'],base_revision=1)
    b=deepcopy(first['content']); b['view']['nodes']['body']['x']=55
    third=store.save(b,did=first['id'],base_revision=1)
    assert third['content']['view']['pages'][0]['title']=='Portada corregida'
    undone=store.undo(first['id'],second['revision'])
    assert undone['content']['view']['pages'][0]['title']=='Comparación'
    assert undone['content']['view']['nodes']['body']['x']==55
    assert store.get(first['id'],1)['content']==first['content']


def test_page_actions_use_native_object_edit(tmp_path):
    row=DocumentStore(tmp_path).save(sample())
    services=SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path))
    result=edit(services,DocumentEdit(id=row['id'],base_revision=1,edits=[
        {'collection':'pages','id':'detail','values':{'width':900,'title':'Más detalle'}},
        {'collection':'view_nodes','id':'body','values':{'font_size':24,'ink':'#003366'}}]))
    assert result['content']['view']['pages'][1]['width']==900
    assert result['content']['view']['nodes']['body']['ink']=='#003366'


@pytest.mark.parametrize('mutate',[
    lambda c:c['view']['nodes']['body'].update(page_id='missing'),
    lambda c:c['view']['pages'][1].update(id='cover'),
    lambda c:c['view']['pages'][0].update(width=float('inf')),
    lambda c:c['view']['nodes']['body'].update(font_size=float('nan')),
    lambda c:c['view']['assets']['picture'].update(data='data:image/png;base64,AAAA'),
])
def test_invalid_pages_are_not_published(tmp_path,mutate):
    store=DocumentStore(tmp_path); first=store.save(sample())
    bad=deepcopy(first['content']); mutate(bad)
    with pytest.raises(ValueError): store.save(bad,did=first['id'],base_revision=1)
    assert store.get(first['id'])['revision']==1


def test_drawio_retains_page_sizes_long_text_and_image(tmp_path):
    row=DocumentStore(tmp_path).save(sample())
    xml=drawio(row)
    assert len(ET.fromstring(xml).findall('./diagram'))==2
    content,warnings=import_document(xml)
    assert warnings
    assert [(p['width'],p['height']) for p in content['view']['pages']]==[(640,480),(800,600)]
    assert [n['label'] for n in content['diagram']['nodes']]==[n['label'] for n in row['content']['diagram']['nodes']]
    assert content['view']['nodes']['heading']['font_size']==32
    aid=content['view']['nodes']['heading']['asset_id']
    assert content['view']['assets'][aid]['data']==row['content']['view']['assets']['picture']['data']
    assert content['diagram']['edges']==row['content']['diagram']['edges']


def test_editorial_exports_are_real_png_and_multipage_pdf(tmp_path):
    row=DocumentStore(tmp_path).save(sample())
    png=image(row,'png')
    with Image.open(io.BytesIO(png)) as rendered:
        assert rendered.size==(800,1104)
        assert rendered.convert('RGB').getpixel((32,50))==(255,255,255)  # image is contained, never stretched
    pdf=image(row,'pdf')
    PdfReader = pytest.importorskip('pypdf', reason='Optional PDF inspection dependency').PdfReader
    pages=PdfReader(io.BytesIO(pdf)).pages
    assert len(pages)==2
    assert tuple(float(v) for v in pages[0].mediabox[2:])==(480,360)
    assert tuple(float(v) for v in pages[1].mediabox[2:])==(600,450)
    assert 'Comparación' in pages[0].extract_text()
