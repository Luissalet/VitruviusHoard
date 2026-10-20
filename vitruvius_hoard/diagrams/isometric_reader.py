"""Self-contained reading view for authored isometric states and part explanations."""
from html import escape
import json


def reader(row, state_id=None):
    from .mechanism import selected
    content = row["content"]
    states = content.get("mechanism", {}).get("states", [])
    selected(row, state_id)  # Explicit invalid state requests must not fall back.
    frames = {"": row["rendering"]["svg"]["light"]}
    for state in states:
        frames[state["id"]] = selected(row, state["id"])["rendering"]["svg"]["light"]
    data = json.dumps({"content": content, "frames": frames, "initial": state_id or ""}, ensure_ascii=False).replace("<", "\\u003c")
    title = escape(content["diagram"].get("title") or "Mecanismo")
    return '''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>''' + title + '''</title><style>
body{margin:0;font:16px 'Segoe UI',sans-serif;color:#1d2433;background:#f5f6f8}header{padding:20px 24px;border-bottom:1px solid #ccd3df;background:white}h1{font-size:24px;margin:0 0 14px}
label{display:grid;gap:6px;margin:12px 0}select{max-width:100%;font:inherit;padding:9px;border:1px solid #a9b4c5;background:white;color:inherit;border-radius:6px}select:focus-visible,[role=button]:focus-visible{outline:3px solid #2f5bd3;outline-offset:3px}
main{display:grid;grid-template-columns:minmax(0,1fr) 320px}.figure{padding:16px;min-width:0;overflow:auto}svg{display:block;width:100%;height:auto}aside{padding:20px;background:white;border-left:1px solid #ccd3df;min-width:0}p{line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere}small{color:#515c6e}h2{font-size:20px}[data-piece]{cursor:pointer}[data-piece].selected{filter:drop-shadow(0 2px 2px #2f5bd3)}
@media(max-width:700px){main{display:block}header{padding:16px}.figure{padding:8px}aside{border:0;border-top:1px solid #ccd3df}}
</style><header><h1>''' + title + '''</h1><label>Estado<select id="state" aria-label="Estado"><option value="">Figura original</option></select></label><p id="state-description"></p><small>Estados y explicaciones escritos por el autor. Revisión ''' + str(row["revision"]) + '''.</small></header>
<main><div class="figure" id="figure"></div><aside><label>Pieza<select id="piece" aria-label="Pieza"></select></label><h2 id="heading"></h2><p id="description"></p><small id="visibility"></small></aside></main>
<script type="application/json" id="source">''' + data + '''</script><script>
const data=JSON.parse(document.getElementById('source').textContent),model=data.content,states=model.mechanism?.states||[],pieces=model.diagram.pieces;
const state=document.getElementById('state'),piece=document.getElementById('piece'),figure=document.getElementById('figure');
for(const item of states){const option=new Option(item.title,item.id);state.add(option)}for(const item of pieces)piece.add(new Option(item.label||item.id,item.id));
function selectPiece(id){piece.value=id;const part=pieces.find(p=>p.id===id),notes=model.mechanism?.parts.find(p=>p.id===id),current=states.find(s=>s.id===state.value);
document.getElementById('heading').textContent=part?.label||id;document.getElementById('description').textContent=notes?.description||'Sin explicación añadida.';
document.getElementById('visibility').textContent=current?.hidden.includes(id)?'Pieza oculta en este estado.':'';
for(const element of figure.querySelectorAll('[data-piece]')){element.classList.toggle('selected',element.dataset.piece===id);element.setAttribute('aria-pressed',String(element.dataset.piece===id))}}
function display(){figure.innerHTML=data.frames[state.value];const current=states.find(s=>s.id===state.value);document.getElementById('state-description').textContent=current?.description||'';
for(const element of figure.querySelectorAll('[data-piece]')){element.setAttribute('tabindex','0');element.setAttribute('role','button');element.setAttribute('aria-label',pieces.find(p=>p.id===element.dataset.piece)?.label||element.dataset.piece);
element.onclick=()=>selectPiece(element.dataset.piece);element.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectPiece(element.dataset.piece)}}}
selectPiece(piece.value||pieces[0].id)}state.value=data.initial;state.onchange=display;piece.onchange=()=>selectPiece(piece.value);display();
</script></html>'''
