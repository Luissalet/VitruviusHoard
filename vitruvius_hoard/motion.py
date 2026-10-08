"""Editable, deterministic motion compositions. No model, cloud or remote assets."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Layer(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["text", "rect", "circle", "line"] = "text"
    text: str = Field("", max_length=1000)
    x: float = Field(0.5, ge=0, le=1)
    y: float = Field(0.5, ge=0, le=1)
    width: float = Field(0.8, gt=0, le=1)
    height: float = Field(0.15, gt=0, le=1)
    size: int = Field(56, ge=8, le=300)
    color: str = Field("#f5f0df", pattern=r"^#[0-9a-fA-F]{6}$")
    effect: Literal["none", "fade", "rise", "slide", "scale", "reveal"] = "rise"
    delay: float = Field(0, ge=0, le=59)
    enter: float = Field(0.6, gt=0, le=10)


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(..., min_length=1, max_length=120)
    duration: float = Field(3, ge=0.2, le=30)
    background: str = Field("#0b1130", pattern=r"^#[0-9a-fA-F]{6}$")
    layers: list[Layer] = Field(..., min_length=1, max_length=40)

    @model_validator(mode="after")
    def timing(self):
        if any(layer.delay >= self.duration for layer in self.layers):
            raise ValueError("Every layer must start before its scene ends")
        return self


class Composition(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    title: str = Field(..., min_length=1, max_length=120)
    width: int = Field(1280, ge=256, le=1920, multiple_of=2)
    height: int = Field(720, ge=256, le=1920, multiple_of=2)
    fps: int = Field(24, ge=1, le=30)
    scenes: list[Scene] = Field(..., min_length=1, max_length=30)

    @model_validator(mode="after")
    def bounded(self):
        if sum(s.duration for s in self.scenes) > 60:
            raise ValueError("A composition can last at most 60 seconds")
        return self


class MotionStore:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "motion.sqlite3"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS compositions (id TEXT, revision INTEGER, body TEXT NOT NULL, PRIMARY KEY(id,revision))")

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def get(self, id: str, revision: int | None = None) -> dict:
        if not re.fullmatch(r"[0-9a-f]{32}", id):
            raise ValueError("Invalid composition id")
        with self.connect() as db:
            row = db.execute("SELECT revision,body FROM compositions WHERE id=? AND (? IS NULL OR revision=?) ORDER BY revision DESC LIMIT 1", (id, revision, revision)).fetchone()
        if not row:
            raise LookupError("Composition or revision not found")
        return {"id": id, "revision": row[0], "composition": json.loads(row[1])}

    def save(self, composition: Composition, id: str | None = None, expected_revision: int | None = None):
        id = id or uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT MAX(revision) FROM compositions WHERE id=?", (id,)).fetchone()[0]
            if current is not None and current != expected_revision:
                raise ValueError(f"Revision conflict: current revision is {current}; read it before saving")
            if current is None and expected_revision is not None:
                raise LookupError("Composition not found")
            revision = (current or 0) + 1
            db.execute("INSERT INTO compositions VALUES (?,?,?)", (id, revision, composition.model_dump_json()))
        return self.get(id)

    def list(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,MAX(revision) FROM compositions GROUP BY id ORDER BY rowid DESC LIMIT 100").fetchall()
        return [{"id": id, "revision": revision, "title": self.get(id)["composition"]["title"]} for id, revision in rows]


def templates() -> dict:
    """Original scene recipes, usable by any Hoard through the same tool."""
    return {"launch": {"title": "Nuevo proyecto", "scenes": [
        {"name": "Presentación", "duration": 3, "layers": [{"text": "Una idea toma forma", "size": 70}]},
        {"name": "Propuesta", "duration": 4, "layers": [{"kind": "rect", "color": "#6d8dff", "height": 0.4, "width": 0.5, "effect": "scale"}, {"text": "Diseña. Revisa. Crea.", "size": 60, "delay": 0.5}]},
        {"name": "Cierre", "duration": 3, "layers": [{"text": "Hazlo tuyo", "effect": "reveal", "color": "#f8d88c"}]}]},
        "caption": {"title": "Una frase", "width": 720, "height": 1280, "scenes": [{"name": "Texto", "duration": 4, "layers": [{"text": "Escribe tu mensaje", "size": 56, "effect": "rise"}]}]},
        "comparison": {"title": "Antes y después", "scenes": [{"name": "Comparación", "duration": 5, "layers": [{"text": "Antes", "x": 0.25, "width": 0.4, "effect": "fade"}, {"text": "Después", "x": 0.75, "width": 0.4, "delay": 1, "effect": "reveal", "color": "#f8d88c"}]}]}}


def page(composition: Composition, *, at: float = 0) -> str:
    body = composition.model_dump_json().replace("<", "\\u003c").replace("&", "\\u0026")
    return _PAGE.replace("__COMPOSITION__", body).replace("__AT__", json.dumps(at))


def export_frames(browser, composition: Composition, output: Path) -> dict:
    """Called only in the existing browser worker; every frame seeks the same scene clock."""
    import math
    from .hoard_link.media.ffmpeg import FFmpeg

    output.mkdir(parents=True, exist_ok=True)
    frames = output / "frames"
    frames.mkdir()
    context = browser.new_context(viewport={"width": composition.width, "height": composition.height}, reduced_motion="no-preference")
    context.route("**/*", lambda route: route.abort())
    count = math.ceil(sum(s.duration for s in composition.scenes) * composition.fps)
    try:
        tab = context.new_page()
        tab.set_content(page(composition), wait_until="load")
        tab.evaluate("document.querySelector('main').style.padding='0'; for(const el of document.querySelectorAll('h1,nav,p')) el.style.display='none'; document.querySelector('svg').style.maxHeight='none'")
        for frame in range(count):
            tab.evaluate("t => window.motionSeek(t)", frame / composition.fps)
            tab.locator("#stage").screenshot(path=str(frames / f"{frame:06d}.png"), animations="disabled")
        FFmpeg().run(["-framerate", str(composition.fps), "-i", frames / "%06d.png", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", output / "motion.mp4"], timeout=120)
        # PNG evidence remains alongside the MP4; no live recording or guessed timestamps.
        return {"frames": count, "fps": composition.fps, "duration": count / composition.fps, "file": str(output / "motion.mp4"), "audio": False}
    finally:
        context.close()


_PAGE = '''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Estudio de movimiento · Vitruvius</title>
<style>:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0b1130;color:#f5f0df;font:16px system-ui}main{max-width:1280px;margin:auto;padding:24px}h1{font:32px Georgia;margin:0 0 24px}svg{display:block;width:100%;max-height:70vh;background:#0b1130}nav{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:24px 0}button{font:inherit;min-height:44px;padding:8px 16px;border:1px solid #6d8dff;background:#141b3f;color:#f5f0df;border-radius:6px;cursor:pointer}button:hover{background:#1b2f9e}:focus-visible{outline:3px solid #f8d88c;outline-offset:3px}input{accent-color:#f8d88c;flex:1;min-width:150px}output{font-variant-numeric:tabular-nums}::selection{background:#6d8dff;color:#0b1130}a{color:#9ab1ff}@media(max-width:600px){main{padding:16px}h1{font-size:26px}}</style>
<main><h1 id="title"></h1><svg id="stage" role="img" aria-label="Previsualización de la composición"></svg>
<nav aria-label="Reproducción"><button id="play">Reproducir</button><label for="seek">Tiempo</label><input id="seek" type="range" min="0" step="0.01"><output id="clock"></output><button id="download">Guardar HTML</button><button id="json">Guardar proyecto</button></nav><p id="scene" aria-live="polite"></p></main>
<script>
const c=__COMPOSITION__, initial=__AT__, total=c.scenes.reduce((n,s)=>n+s.duration,0), NS='http://www.w3.org/2000/svg';
const stage=document.querySelector('#stage'),seek=document.querySelector('#seek'),clock=document.querySelector('#clock'),play=document.querySelector('#play');
document.querySelector('#title').textContent=c.title;stage.setAttribute('viewBox',`0 0 ${c.width} ${c.height}`);seek.max=total;
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;let time=0,playing=false,prev;
function node(name,attrs,text){const n=document.createElementNS(NS,name);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;}
function draw(t){time=Math.max(0,Math.min(total,Number(t)));let offset=0,scene=c.scenes[c.scenes.length-1];for(let i=0;i<c.scenes.length;i++){const s=c.scenes[i];scene=s;if(time<offset+s.duration||i===c.scenes.length-1)break;offset+=s.duration;}const local=Math.min(scene.duration,time-offset);stage.replaceChildren(node('rect',{width:c.width,height:c.height,fill:scene.background}));
for(const l of scene.layers){const raw=Math.max(0,Math.min(1,(local-l.delay)/l.enter)),p=reduced?(local>=l.delay?1:0):1-Math.pow(1-raw,4);if(raw<=0)continue;const x=l.x*c.width,y=l.y*c.height,w=l.width*c.width,h=l.height*c.height;const g=node('g',{opacity:l.effect==='none'?1:p});if(l.effect==='rise')g.setAttribute('transform',`translate(0 ${(1-p)*h*.5})`);if(l.effect==='slide')g.setAttribute('transform',`translate(${(p-1)*w*.3} 0)`);if(l.effect==='scale')g.setAttribute('transform',`translate(${x} ${y}) scale(${.8+.2*p}) translate(${-x} ${-y})`);
if(l.kind==='text'){const text=node('text',{x,y,fill:l.color,'font-size':l.size,'font-family':'Georgia,serif','text-anchor':'middle','dominant-baseline':'middle'});const lines=l.text.split('\\n');lines.forEach((line,i)=>text.appendChild(node('tspan',{x,dy:i===0?-(lines.length-1)*l.size*.6:l.size*1.2},line)));g.appendChild(text);}else if(l.kind==='circle')g.appendChild(node('ellipse',{cx:x,cy:y,rx:w/2,ry:h/2,fill:l.color}));else if(l.kind==='line')g.appendChild(node('line',{x1:x-w/2,x2:x+w/2,y1:y,y2:y,stroke:l.color,'stroke-width':4}));else g.appendChild(node('rect',{x:x-w/2,y:y-h/2,width:w,height:h,fill:l.color,rx:12}));
if(l.effect==='reveal'){const clip=node('clipPath',{id:'clip'+stage.children.length});clip.appendChild(node('rect',{x:x-w/2,y:y-h/2,width:w*p,height:h}));stage.appendChild(clip);g.setAttribute('clip-path',`url(#${clip.id})`);}stage.appendChild(g);}
seek.value=time;clock.textContent=`${time.toFixed(2)} / ${total.toFixed(2)} s`;document.querySelector('#scene').textContent=scene.name;return time;}
window.motionSeek=draw;window.motionComposition=c;window.motionDuration=total;
function frame(now){if(playing){if(prev!==undefined)draw(time+(now-prev)/1000);if(time>=total){playing=false;play.textContent='Reproducir';}prev=now;requestAnimationFrame(frame);}}
play.onclick=()=>{playing=!playing;if(playing){if(time>=total)draw(0);prev=undefined;requestAnimationFrame(frame);}play.textContent=playing?'Pausar':'Reproducir';};seek.oninput=()=>{playing=false;play.textContent='Reproducir';draw(seek.value);};
function save(name,type,value){const u=URL.createObjectURL(new Blob([value],{type}));const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
document.querySelector('#json').onclick=()=>save('motion.json','application/json',JSON.stringify(c,null,2));document.querySelector('#download').onclick=()=>save('motion.html','text/html','<!doctype html>'+document.documentElement.outerHTML);
draw(initial);
</script></html>'''
