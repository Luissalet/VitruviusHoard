"""Original, dependency-free HTML studies for the design workbench."""
from __future__ import annotations

import hashlib
import html
import json
import re

_PATTERNS = [
    ("editorial", "Editorial grid", "Retícula editorial", "Typography, asymmetric grid and a live scale control.", ["layout", "typography"]),
    ("diorama", "Layered landscape", "Paisaje por capas", "Own SVG landscape with pointer parallax and depth control.", ["svg", "layers"]),
    ("elastic", "Elastic lettering", "Letras elásticas", "Grapheme-aware lettering with replay and adjustable spacing.", ["typography", "motion"]),
    ("symmetry", "Radial drawing", "Dibujo radial", "Draw repeated strokes on Canvas; clear or export your image.", ["canvas", "interaction"]),
    ("constellation", "Constellation map", "Mapa de constelaciones", "Connect keyboard-accessible points and export the SVG.", ["svg", "interaction"]),
    ("halftone", "Halftone field", "Campo de semitonos", "Procedural Canvas dots with adjustable density.", ["canvas", "texture"]),
    ("pulse", "Pulse study", "Estudio de pulsos", "Adjust wave frequency and amplitude; pause or resume motion.", ["canvas", "motion"]),
    ("holographic", "Prismatic card", "Tarjeta prismática", "Pointer tilt, keyboard rotation and a reduced-motion alternative.", ["css", "interaction"]),
]


def catalogue():
    return [{"id": key, "name": name, "name_es": spanish, "description": description, "tags": list(tags)}
            for key, name, spanish, description, tags in _PATTERNS]


def generate(id: str, text: str = "FORM / FIELD", accent: str = "#e36a39"):
    pattern = next((item for item in catalogue() if item["id"] == id), None)
    if not pattern:
        raise ValueError(f"Unknown design pattern: {id}")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
        raise ValueError("accent must be a six-digit hex colour")
    title = html.escape(text)
    literal = json.dumps(text, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    common = """*{box-sizing:border-box}body{margin:0;background:#f1ede3;color:#232521;font:16px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:clamp(20px,5vw,64px)}h1{font-size:clamp(36px,8vw,96px);line-height:1.02;overflow-wrap:anywhere;margin:0 0 30px}button,input{font:inherit}button{min-height:44px;padding:8px 16px;border:1px solid currentColor;background:transparent;color:inherit;cursor:pointer}button:focus-visible,input:focus-visible{outline:3px solid var(--accent);outline-offset:4px}.controls{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:24px 0}label{display:flex;gap:10px;align-items:center;flex-wrap:wrap}canvas,svg{display:block;width:100%;max-width:100%;height:auto}p{max-width:55ch}output{font-variant-numeric:tabular-nums}@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}"""
    body, css, script = "", "", ""
    if id == "editorial":
        body = f'<header><p>STUDY 01 · TYPE AND SPACE</p><h1 id="heading">{title}</h1></header><div class="spread"><p class="number">01</p><article><h2>Measure the empty space.</h2><p>A heading, a rule and a small paragraph form a composition. Move the scale control to compare their proportions.</p><label>Heading scale <input id="scale" type="range" min="36" max="110" value="80"><output id="value">80</output></label></article><div class="shape" aria-hidden="true"></div></div>'
        css = '.spread{display:grid;grid-template-columns:1fr 2fr 2fr;gap:32px;border-top:2px solid;padding-top:32px}.number{font:100px/1 Georgia,serif;margin:0}.shape{background:var(--accent);aspect-ratio:1;border-radius:50% 50% 0 50%}@media(max-width:650px){.spread{grid-template-columns:1fr}.shape{max-width:250px}}'
        script = "scale.oninput=()=>{heading.style.fontSize=scale.value+'px';value.textContent=scale.value}"
    elif id == "diorama":
        body = f'<h1>{title}</h1><svg id="scene" viewBox="0 0 900 540" role="img" aria-label="Layered landscape"><rect width="900" height="540" fill="#d7d8b1"/><circle cx="680" cy="110" r="60" fill="#f8efd9"/><g id="layers"><path data-depth="1" d="M0 350L150 150L330 340L520 130L720 340L900 180V540H0Z" fill="#819789"/><path data-depth="2" d="M0 420Q210 220 460 400T900 300V540H0Z" fill="#466f68"/><path data-depth="3" d="M0 470Q250 330 460 460T900 420V540H0Z" fill="#244f4d"/><path data-depth="4" d="M0 520Q270 400 570 510T900 470V540H0Z" fill="#173c3c"/></g></svg><div class="controls"><label>Depth <input id="depth" type="range" min="0" max="20" value="10"></label><button id="reset">Centre layers</button></div>'
        css = '#scene{border:12px solid #fbf7ef;box-shadow:0 12px 25px #173c3c25;overflow:hidden}'
        script = "const move=x=>document.querySelectorAll('[data-depth]').forEach(p=>p.setAttribute('transform',`translate(${x*Number(depth.value)*Number(p.dataset.depth)} 0)`));scene.onpointermove=e=>{if(!reduced.matches)move((e.clientX-scene.getBoundingClientRect().left)/scene.getBoundingClientRect().width-.5)};scene.onpointerleave=()=>move(0);reset.onclick=()=>move(0);depth.oninput=()=>move(.3);reduced.onchange=()=>move(0);"
    elif id == "elastic":
        body = '<p>STUDY 03 · LETTER RHYTHM</p><h1 id="letters" aria-label="'+title+'"></h1><div class="controls"><button id="replay">Replay</button><label>Spacing <input id="spacing" type="range" min="0" max="18" value="2"></label></div>'
        css = '#letters{min-height:200px;line-height:1.3}#letters span{display:inline-block;color:var(--accent);white-space:pre-wrap}'
        script = f"const text={literal};const segments=typeof Intl.Segmenter==='function'?[...new Intl.Segmenter(undefined,{{granularity:'grapheme'}}).segment(text)].map(x=>x.segment):Array.from(text);for(const ch of segments){{const span=document.createElement('span');span.textContent=ch;span.setAttribute('aria-hidden','true');letters.append(span)}}replay.onclick=()=>{{for(const [i,span] of [...letters.children].entries()){{span.getAnimations().forEach(a=>a.cancel());if(!reduced.matches)span.animate([{{transform:'translateY(0) scaleY(1)'}},{{transform:'translateY(-25px) scaleY(1.4)'}},{{transform:'translateY(0) scaleY(1)'}}],{{duration:700,delay:i*35,easing:'cubic-bezier(.2,.8,.3,1)'}})}}}};spacing.oninput=()=>letters.style.letterSpacing=spacing.value+'px';"
    elif id in ("symmetry", "halftone", "pulse"):
        body = f'<p>CANVAS STUDY</p><h1>{title}</h1><canvas id="canvas" width="960" height="600" aria-label="{html.escape(pattern["name"])}"></canvas>'
        css = 'canvas{background:#202b2b;border-radius:2px;touch-action:none}body{background:#e2e9e2}h1{font:clamp(40px,7vw,80px)/1.1 Georgia,serif}'
        setup = 'const ctx=canvas.getContext("2d");const W=canvas.width,H=canvas.height;'
        download = "exportImage.onclick=()=>{const a=document.createElement('a');a.download='study.png';a.href=canvas.toDataURL('image/png');a.click()};"
        if id == "symmetry":
            body += '<div class="controls"><label>Sectors <input id="sectors" type="range" min="2" max="16" value="8"></label><button id="clear">Clear drawing</button><button id="exportImage">Export PNG</button></div><p>Drag on the field to draw repeated strokes. Each new stroke uses the current sector count.</p>'
            script = setup + "let previous=null;const point=e=>{const r=canvas.getBoundingClientRect();return[(e.clientX-r.left)*W/r.width-W/2,(e.clientY-r.top)*H/r.height-H/2]};canvas.onpointerdown=e=>{canvas.setPointerCapture(e.pointerId);previous=point(e)};canvas.onpointermove=e=>{if(!previous)return;const p=point(e);for(let i=0;i<Number(sectors.value);i++){ctx.save();ctx.translate(W/2,H/2);ctx.rotate(i*Math.PI*2/Number(sectors.value));ctx.strokeStyle=getComputedStyle(document.body).getPropertyValue('--accent');ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(...previous);ctx.lineTo(...p);ctx.stroke();ctx.restore()}previous=p};canvas.onpointerup=canvas.onpointercancel=()=>previous=null;clear.onclick=()=>ctx.clearRect(0,0,W,H);" + download
        elif id == "halftone":
            body += '<div class="controls"><label>Dot distance <input id="density" type="range" min="8" max="36" value="18"><output id="value">18</output></label><button id="exportImage">Export PNG</button></div>'
            script = setup + "function draw(){ctx.clearRect(0,0,W,H);const d=Number(density.value);value.textContent=d;ctx.fillStyle=getComputedStyle(document.body).getPropertyValue('--accent');for(let y=d;y<H;y+=d)for(let x=d;x<W;x+=d){const wave=(Math.sin(x/90+y/130)+Math.cos(y/70))/4+.5;ctx.beginPath();ctx.arc(x,y,Math.max(1,wave*d*.46),0,Math.PI*2);ctx.fill()}}density.oninput=draw;draw();" + download
        else:
            body += '<div class="controls"><label>Frequency <input id="frequency" type="range" min="1" max="12" value="4"></label><label>Amplitude <input id="amplitude" type="range" min="10" max="180" value="90"></label><button id="pause" aria-pressed="false">Pause</button></div><p>A graphic wave study; these controls change the drawing.</p>'
            script = setup + "let running=!reduced.matches,phase=0,frame=null;function draw(){ctx.clearRect(0,0,W,H);ctx.strokeStyle=getComputedStyle(document.body).getPropertyValue('--accent');ctx.lineWidth=4;ctx.beginPath();for(let x=0;x<W;x++){const y=H/2+Math.sin(x/W*Math.PI*2*Number(frequency.value)+phase)*Number(amplitude.value);x?ctx.lineTo(x,y):ctx.moveTo(x,y)}ctx.stroke()}function tick(){phase+=.025;draw();if(running)frame=requestAnimationFrame(tick)}function sync(){cancelAnimationFrame(frame);pause.textContent=running?'Pause':'Play';pause.setAttribute('aria-pressed',String(!running));if(running)tick();else draw()}pause.onclick=()=>{running=!running;sync()};frequency.oninput=amplitude.oninput=draw;reduced.onchange=()=>{running=!reduced.matches;sync()};sync();"
    elif id == "constellation":
        body = f'<p>POINT / LINE</p><h1>{title}</h1><svg id="map" viewBox="0 0 900 540" aria-label="Constellation drawing"><g id="edges"></g><g id="points"></g></svg><div class="controls"><button id="clear">Clear connections</button><button id="exportSvg">Export SVG</button><output id="status" aria-live="polite">Select a point, then another.</output></div>'
        css = 'body{background:#101d2d;color:#e9f0eb}#map{background:#18293d}circle{fill:#d7e5d8;stroke:#18293d;stroke-width:5;cursor:pointer}circle:focus{outline:none;stroke:var(--accent)}line{stroke:var(--accent);stroke-width:3}'
        script = "const ns='http://www.w3.org/2000/svg';let selected=null,count=0;const coordinates=[[130,120],[270,260],[370,100],[540,220],[730,100],[780,400],[580,440],[360,410],[140,430]];coordinates.forEach(([x,y],i)=>{const c=document.createElementNS(ns,'circle');for(const [k,v] of Object.entries({cx:x,cy:y,r:18,tabindex:0,role:'button','aria-label':'Point '+(i+1)}))c.setAttribute(k,v);const select=()=>{if(selected&&selected!==c){const l=document.createElementNS(ns,'line');for(const [k,v] of Object.entries({x1:selected.getAttribute('cx'),y1:selected.getAttribute('cy'),x2:x,y2:y}))l.setAttribute(k,v);edges.append(l);count++;status.textContent=count+' connections';selected=null}else{selected=c;status.textContent='Point '+(i+1)+' selected'}};c.onclick=select;c.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select()}};points.append(c)});clear.onclick=()=>{edges.replaceChildren();selected=null;count=0;status.textContent='Select a point, then another.'};exportSvg.onclick=()=>{const copy=map.cloneNode(true);copy.setAttribute('xmlns',ns);copy.querySelectorAll('circle').forEach(c=>{c.setAttribute('fill','#d7e5d8');c.setAttribute('stroke','#18293d')});copy.querySelectorAll('line').forEach(l=>{l.setAttribute('stroke',getComputedStyle(document.body).getPropertyValue('--accent').trim());l.setAttribute('stroke-width','3')});const blob=new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='constellation.svg';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};"
    else:
        body = f'<p>MATERIAL STUDY · LIGHT AND ANGLE</p><div class="stage"><article id="card"><span>FIELD NOTES / 08</span><h1>{title}</h1><p>Move the pointer to change the viewing angle, or use the rotation control.</p><span class="serial">008 — 240</span></article></div><div class="controls"><label>Rotation <input id="rotation" type="range" min="-18" max="18" value="0"></label><button id="reset">Reset angle</button></div>'
        css = 'body{background:#171a20;color:#f4f3ec}.stage{perspective:900px;padding:35px 5px}#card{position:relative;max-width:680px;margin:auto;padding:clamp(24px,5vw,56px);border:1px solid #b4b7bb;border-radius:18px;background:linear-gradient(125deg,#41605f,#4e3a62 45%,#78623c);box-shadow:0 30px 40px #0005;transition:transform .15s}#card h1{font:clamp(32px,6vw,72px)/1.1 Georgia,serif;margin-top:45px}.serial{display:block;text-align:right;margin-top:40px}'
        script = "const tilt=(x,y)=>card.style.transform=`rotateY(${x}deg) rotateX(${y}deg)`;card.onpointermove=e=>{if(reduced.matches)return;const r=card.getBoundingClientRect();tilt(((e.clientX-r.left)/r.width-.5)*24,((e.clientY-r.top)/r.height-.5)*-16)};card.onpointerleave=()=>tilt(Number(rotation.value),0);rotation.oninput=()=>tilt(Number(rotation.value),0);reset.onclick=()=>{rotation.value=0;tilt(0,0)};reduced.onchange=()=>tilt(0,0);"
    bindings = "".join(f"const {key}=document.getElementById({json.dumps(key)});" for key in re.findall(r'id="([A-Za-z][A-Za-z0-9]*)"', body))
    source = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title><style>:root{{--accent:{accent}}}{common}{css}</style></head><body><main>{body}</main><script>const reduced=matchMedia("(prefers-reduced-motion: reduce)");{bindings}{script}</script></body></html>'
    return {"pattern": pattern, "parameters": {"text": text, "accent": accent}, "html": source,
            "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()}
