"""Portable, source-bound reading view. Authored links are not measured execution."""
from html import escape
import json


def reader(row, state_id=None):
    if row["content"]["diagram"]["type"] == "isometric":
        from .isometric_reader import reader as isometric_reader
        return isometric_reader(row, state_id)
    if state_id:
        raise ValueError("States apply to isometric diagrams.")
    title = row["content"]["diagram"].get("title") or "Diagrama"
    data = json.dumps(row["content"]["diagram"], ensure_ascii=False).replace("<", "\\u003c")
    return """<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>""" + escape(title) + """</title><style>
body{margin:0;font:16px 'Segoe UI',sans-serif;background:#f5f6f8;color:#1d2433}header{padding:18px 24px;border-bottom:1px solid #d4dae4;background:white}
h1{font-size:22px;margin:0 0 8px}button,select{font:inherit;padding:9px 12px;border:1px solid #bcc5d4;border-radius:5px;background:white;color:inherit}
main{display:grid;grid-template-columns:minmax(0,1fr) 300px;min-height:75vh}.figure{overflow:auto;padding:20px}svg{max-width:100%;height:auto}
aside{padding:20px;border-left:1px solid #d4dae4;background:white}aside p{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.5}
[data-node-id]{cursor:pointer}[data-node-id]:focus{outline:3px solid #2f5bd3;outline-offset:3px}.dim{opacity:.18}.selected>rect,.selected>path{stroke:#2f5bd3;stroke-width:3}
.toolbar{display:flex;gap:8px;flex-wrap:wrap}small{display:block;margin-top:12px;color:#5b6474}@media(max-width:700px){main{display:block}aside{border:0;border-top:1px solid #d4dae4}.figure{padding:8px}}
</style><header><h1>""" + escape(title) + """</h1><div class="toolbar"><select id="direction" aria-label="Recorrido"><option value="down">Relaciones siguientes</option><option value="up">Relaciones anteriores</option></select><button id="reset">Mostrar todo</button></div>
<small>Relaciones escritas en el diagrama. No acreditan ejecución ni impacto medido. Revisión """ + str(row["revision"]) + """.</small></header><main><div class="figure">""" + row["rendering"]["svg"]["light"] + """</div><aside><h2 id="heading">Explorar el diagrama</h2><p id="detail">Selecciona una pieza para leer su explicación y seguir sus relaciones.</p></aside></main>
<script type="application/json" id="source">""" + data + """</script><script>
const model=JSON.parse(document.getElementById('source').textContent), nodes=[...document.querySelectorAll('[data-node-id]')],edges=[...document.querySelectorAll('[data-edge-id]')];
let selected=null;function show(id){selected=id;const seen=new Set([id]),pending=[id],direction=document.getElementById('direction').value;
while(pending.length){const here=pending.shift();for(const edge of model.edges||[]){const from=direction==='up'?edge.to:edge.from,to=direction==='up'?edge.from:edge.to;if(from===here&&!seen.has(to)){seen.add(to);pending.push(to)}}}
for(const element of nodes){const key=element.dataset.nodeId;element.classList.toggle('dim',!seen.has(key));element.classList.toggle('selected',key===id)}
for(const element of edges){const edge=(model.edges||[]).find(e=>e.id===element.dataset.edgeId);element.classList.toggle('dim',!edge||!seen.has(edge.from)||!seen.has(edge.to))}
const node=(model.nodes||[]).find(n=>n.id===id);document.getElementById('heading').textContent=node?.label||id;document.getElementById('detail').textContent=node?.details||'Sin explicación añadida.';}
for(const element of nodes){element.setAttribute('tabindex','0');element.setAttribute('role','button');element.setAttribute('aria-label',(model.nodes||[]).find(n=>n.id===element.dataset.nodeId)?.label||element.dataset.nodeId);element.onclick=()=>show(element.dataset.nodeId);element.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show(element.dataset.nodeId)}}}
document.getElementById('direction').onchange=()=>{if(selected)show(selected)};document.getElementById('reset').onclick=()=>{selected=null;for(const element of [...nodes,...edges])element.classList.remove('dim','selected');document.getElementById('heading').textContent='Explorar el diagrama';document.getElementById('detail').textContent='Selecciona una pieza para leer su explicación y seguir sus relaciones.'};
</script></html>"""


def compare(before, after):
    changes = {}
    for name in ("nodes", "edges", "groups", "pieces"):
        a = {item["id"]: item for item in before["content"]["diagram"].get(name, [])}
        b = {item["id"]: item for item in after["content"]["diagram"].get(name, [])}
        changes[name] = {"added": sorted(b.keys() - a.keys()), "removed": sorted(a.keys() - b.keys()),
                         "changed": [{"id": key, "before": a[key], "after": b[key]} for key in sorted(a.keys() & b.keys()) if a[key] != b[key]]}
    return {"id": after["id"], "before_revision": before["revision"], "after_revision": after["revision"],
            "mechanism_changed": before["content"].get("mechanism") != after["content"].get("mechanism"),
            "changes": changes, "view_changed": before["content"]["view"] != after["content"]["view"],
            "title_changed": before["content"]["diagram"].get("title") != after["content"]["diagram"].get("title")}
