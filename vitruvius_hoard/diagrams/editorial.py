"""Editorial pages extend the retained diagram source, not a second document store."""
from copy import deepcopy
from dataclasses import asdict
from html import escape
import base64
import io
import math
import re
import xml.etree.ElementTree as ET

from .render import FONT_STACK, svg
from .spec import GRAPH_TYPES


def validate_view(content):
    view = content['view']
    if view.get('kind') != 'infographic':
        return
    if content['diagram']['type'] not in GRAPH_TYPES:
        raise ValueError('Editorial pages use a graph document.')
    pages = view.get('pages')
    if not isinstance(pages, list) or not pages:
        raise ValueError('An infographic needs at least one page.')
    ids = set()
    for page in pages:
        if not isinstance(page, dict) or not re.fullmatch(r'[\w-]{1,60}', str(page.get('id', ''))):
            raise ValueError('Each page needs a stable ID.')
        if page['id'] in ids:
            raise ValueError('Page identities must be unique.')
        ids.add(page['id'])
        if not isinstance(page.get('title', ''), str):
            raise ValueError('Page title must be text.')
        for key in ('width', 'height'):
            if not isinstance(page.get(key), (int, float)) or not math.isfinite(page[key]) or page[key] < 200:
                raise ValueError('Page dimensions must be finite and at least 200 pixels.')
        if not isinstance(page.get('order', 0), (int, float)) or not math.isfinite(page.get('order', 0)):
            raise ValueError('Page order must be finite.')
    assets = view.setdefault('assets', {})
    if not isinstance(assets, dict):
        raise ValueError('Editorial assets must be an object keyed by ID.')
    from PIL import Image
    for aid, asset in assets.items():
        if not isinstance(asset, dict) or not isinstance(asset.get('data'), str):
            raise ValueError('An image asset needs embedded data.')
        match = re.fullmatch(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=\s]+)', asset['data'])
        if not match:
            raise ValueError('Embed PNG, JPEG or WebP image data.')
        try:
            with Image.open(io.BytesIO(base64.b64decode(match[2], validate=True))) as image:
                if image.format != {'png':'PNG', 'jpeg':'JPEG', 'webp':'WEBP'}[match[1]]:
                    raise ValueError('Image type differs from embedded data.')
                image.verify()
        except Exception as exc:
            raise ValueError(f'Image asset {aid} is invalid.') from exc
    for node in content['diagram']['nodes']:
        item = view['nodes'].setdefault(node['id'], {})
        item.setdefault('page_id', pages[0]['id'])
        if item['page_id'] not in ids:
            raise ValueError('A node refers to an unknown page.')
        if item.get('asset_id') and item['asset_id'] not in assets:
            raise ValueError('A node refers to an unknown image asset.')


def ordered_pages(content):
    return sorted(content['view']['pages'], key=lambda p: p.get('order', 0))


def import_pages(pages, source):
    from .importers import _drawio_xml, _strip_html
    content = {'diagram': {'type':'flowchart', 'title':'', 'nodes':[], 'edges':[], 'groups':[]},
               'view': {'kind':'infographic', 'pages':[], 'assets':{}, 'nodes':{}, 'edges':{}}, 'source':source}
    used = set()
    for index, page in enumerate(pages):
        model = _drawio_xml(ET.tostring(page, encoding='unicode'))
        pid = page.get('id') or f'page-{index+1}'
        if not re.fullmatch(r'[\w-]{1,60}', pid) or any(p['id']==pid for p in content['view']['pages']):
            pid = f'page-{index+1}'
        content['view']['pages'].append({'id':pid, 'title':page.get('name',''), 'order':index,
                                        'width':max(200,float(model.get('pageWidth',960))), 'height':max(200,float(model.get('pageHeight',720)))})
        cells = {c.get('id'):c for c in model.findall('.//mxCell')}
        identities = {}
        for cid, cell in cells.items():
            if cell.get('vertex')!='1' and cell.get('edge')!='1':
                continue
            value = cell.get('vitruviusId') or cid
            if value in used or len(value)>60:
                value = f'p{index}-' + value[-48:]
            if value in used:
                raise ValueError('Duplicate draw.io object identity.')
            identities[cid]=value
            used.add(value)
        def offset(cid, seen=None):
            seen=set() if seen is None else seen
            if cid not in cells or cid in seen:
                return 0,0
            seen.add(cid)
            geo=cells[cid].find('mxGeometry')
            x,y=offset(cells[cid].get('parent'),seen)
            return x+float(geo.get('x',0) if geo is not None else 0),y+float(geo.get('y',0) if geo is not None else 0)
        for cid,cell in cells.items():
            style=dict(part.split('=',1) for part in (cell.get('style') or '').split(';') if '=' in part)
            if cell.get('vertex')=='1':
                if style.get('container')=='1' or 'swimlane' in (cell.get('style') or ''):
                    content['diagram']['groups'].append({'id':identities[cid], 'label':cell.get('value','')})
                    content['diagram']['type']='architecture'
                    continue
                nid=identities[cid]
                label=cell.get('value','')
                if style.get('html')=='1':
                    label=_strip_html(label)
                shape='diamond' if 'rhombus' in (cell.get('style') or '') else 'cylinder' if style.get('shape')=='cylinder' else 'round' if style.get('rounded')=='1' else 'box'
                parent=identities.get(cell.get('parent'), '')
                group=parent if any(g['id']==parent for g in content['diagram']['groups']) else ''
                content['diagram']['nodes'].append({'id':nid,'label':label,'shape':shape,'group':group})
                geo=cell.find('mxGeometry')
                x,y=offset(cid)
                view={'page_id':pid,'x':max(0,x),'y':max(0,y),'width':max(24,float(geo.get('width',176) if geo is not None else 176)),
                      'height':max(24,float(geo.get('height',64) if geo is not None else 64))}
                for key,raw in (('font_size','fontSize'),('font_weight','fontWeight')):
                    if raw in style:
                        view[key]=float(style[raw])
                if style.get('align') in ('left','center','right'):
                    view['align']=style['align']
                for key,raw in (('fill','fillColor'),('ink','fontColor'),('stroke','strokeColor')):
                    if re.fullmatch(r'#[0-9a-fA-F]{6}',style.get(raw,'')):
                        view[key]=style[raw]
                if style.get('strokeColor')=='none' and style.get('fillColor')=='none':
                    view['border']=False
                if style.get('image','').startswith('data:image/'):
                    # Semicolons are significant in data URIs, unlike other style values.
                    image=re.search(r'(?:^|;)image=(data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+)',cell.get('style',''))
                    if image:
                        aid=f'image-{nid}'
                        content['view']['assets'][aid]={'name':label,'data':image[1]}
                        view['asset_id']=aid
                        view['show_label']=style.get('labelPosition')!='none'
                content['view']['nodes'][nid]=view
        ids={n['id'] for n in content['diagram']['nodes']}
        for cid,cell in cells.items():
            if cell.get('edge')!='1':
                continue
            a,b=identities.get(cell.get('source')),identities.get(cell.get('target'))
            if a not in ids or b not in ids:
                continue
            eid=identities[cid]
            content['diagram']['edges'].append({'id':eid,'from':a,'to':b,'label':cell.get('value',''),
                                                'style':'dashed' if 'dashed=1' in cell.get('style','') else 'solid'})
            points=cell.findall('./mxGeometry/Array[@as="points"]/mxPoint')
            if points:
                content['view']['edges'][eid]={'points':[[float(p.get('x',0)),float(p.get('y',0))] for p in points]}
    return content


def project(content, page):
    result = deepcopy(content)
    nodes = [n for n in result['diagram']['nodes'] if result['view']['nodes'][n['id']]['page_id'] == page['id']]
    ids = {n['id'] for n in nodes}
    result['diagram']['nodes'] = nodes
    result['diagram']['edges'] = [e for e in result['diagram']['edges'] if e['from'] in ids and e['to'] in ids]
    result['diagram']['title'] = ''  # Page headings are editable text blocks.
    result['view']['nodes'] = {k:v for k,v in result['view']['nodes'].items() if k in ids}
    result['view'].pop('kind', None)
    return result


def drawing(content):
    from .documents import document_layout
    pages, checks, scenes = [], [], []
    for page in ordered_pages(content):
        projected = project(content, page)
        diagram, layout = document_layout(projected)
        layout.width, layout.height = page['width'], page['height']
        for node in diagram.nodes:
            box, style = layout.boxes[node.id], content['view']['nodes'][node.id]
            size = style.get('font_size', 13)
            # Use the same character wrapping contract as the editor.
            count = max(4, int((box.w - 25) / (size * .577)))
            box.lines = [line for paragraph in node.label.split('\n') for line in (re.findall(rf'.{{1,{count}}}(?:\s|$)|.{{1,{count}}}', paragraph) or [''])]
            checks.append({'id': f"{page['id']}:{node.id}:bounds", 'ok': box.x >= 0 and box.y >= 0 and box.x + box.w <= layout.width and box.y + box.h <= layout.height,
                           'message': 'Block must fit its page.', 'node_id': node.id, 'page_id': page['id']})
            checks.append({'id': f"{page['id']}:{node.id}:text", 'ok': not style.get('show_label', True) or len(box.lines) * size * 1.3 <= box.h - 12,
                           'message': 'Text needs enough block height.', 'node_id': node.id, 'page_id': page['id']})
        styles = content['view']['nodes']
        assets = {key:asset['data'] for key,asset in content['view']['assets'].items()}
        images = {mode: svg(diagram, content['profile'], mode, layout, styles, assets) for mode in ('light', 'dark')}
        scene = asdict(layout)
        scene['edge_ids'] = [e.id for e in diagram.edges]
        pages.append({**page, 'svg': images, 'scene': scene})
        scenes.append(scene)
    width = max(p['width'] for p in pages)
    height = sum(p['height'] for p in pages) + 24 * (len(pages) - 1)
    combined = {}
    for mode in ('light', 'dark'):
        y, bodies = 0, []
        for p in pages:
            # Nested SVG viewports retain clipping, page dimensions and native IDs.
            inner = p['svg'][mode].replace('<svg ', f'<svg data-page-id="{escape(p["id"], quote=True)}" x="0" y="{y}" ', 1)
            bodies.append(inner)
            y += p['height'] + 24
        combined[mode] = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="{escape(FONT_STACK, quote=True)}">' + ''.join(bodies) + '</svg>'
    return {'svg': combined, 'pages': pages, 'scene': {'boxes': {k:v for s in scenes for k,v in s['boxes'].items()}, 'edge_ids':[], 'routes':[], 'frames':[], 'width':width, 'height':height},
            'gates': checks, 'ok': all(c['ok'] for c in checks)}
