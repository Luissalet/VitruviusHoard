import React, { useEffect, useRef, useState } from 'react';
import { useApp } from '../App.jsx';
import { useCopilotForm, useCopilotObjects, useCopilotRefresh } from '../copilot-hooks.js';
import { api } from '../api.js';

const normalise = recipe => ({ width: 1280, height: 720, fps: 24, ...structuredClone(recipe) });

async function request(path, body) {
  const response = await fetch('/api/motions' + path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!response.ok) { const text = await response.text(); throw new Error(text.slice(0, 500)); }
  return path === '/preview' ? response.text() : response.json();
}

export default function Motion() {
  const { lang } = useApp(), es = lang === 'es';
  const [recipes, setRecipes] = useState({}), [saved, setSaved] = useState([]), [draft, setDraft] = useState(null), [record, setRecord] = useState(null);
  const [baseline, setBaseline] = useState(null);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const [html, setHtml] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [download, setDownload] = useState(null), [dirty, setDirty] = useState(false);
  const stateRef = useRef({ record, draft, dirty });
  stateRef.current = { record, draft, dirty };
  const refresh = async () => setSaved((await request('')).compositions);
  useEffect(() => { request('/templates').then(r => { setRecipes(r.templates); const first = normalise(r.templates.launch); setDraft(first); setBaseline(first); }).catch(e => setError(e.message)); refresh().catch(e => setError(e.message)); }, []);
  // An agent turn may have saved a newer revision: show it in place unless there are unsaved edits (a later save then reports the revision conflict).
  async function reloadFromAgent() {
    const before = stateRef.current;
    await refresh();
    const changed = () => {
      const now = stateRef.current;
      return !before.record || now.record?.id !== before.record.id || now.dirty || now.draft !== before.draft;
    };
    if (changed()) return;
    const latest = await api.motion(before.record.id);
    if (changed() || latest.revision <= stateRef.current.record.revision) return;
    setRecord(latest); setDraft(latest.composition); setBaseline(latest.composition); setHtml(''); setDownload(null);
  }
  useCopilotRefresh(reloadFromAgent);
  useCopilotObjects(record ? [{ kind: 'motion', id: record.id }] : []);
  useCopilotForm(record ? 'motion-form' : 'motion-draft', { objectId: record?.id, initial: baseline || {}, current: draft || {} });
  const edit = value => { setDraft(value); setDirty(true); setDownload(null); };
  async function work(fn) { setError(''); setBusy(true); try { await fn(); } catch(e) { setError(e.message); } finally { setBusy(false); } }
  async function save() { const submitted = draftRef.current; const r = await request('', { composition: submitted, ...(record ? { id: record.id, expected_revision: record.revision } : {}) }); setRecord(r); setBaseline(submitted); setDirty(JSON.stringify(draftRef.current) !== JSON.stringify(submitted)); await refresh(); return r; }
  function sceneEdit(index, field, value) { edit({ ...draft, scenes: draft.scenes.map((s,i) => i === index ? { ...s, [field]: value } : s) }); }
  function layerEdit(index, layer, field, value) { const s = draft.scenes[index]; sceneEdit(index, 'layers', s.layers.map((l,i) => i === layer ? { ...l, [field]: value } : l)); }
  const label = (a,b) => es ? a : b;
  return <section className="space-y-6">
    <h1 className="text-3xl font-semibold">{label('Movimiento', 'Motion')}</h1>
    <p className="help">{label('Compón escenas, revisa los tiempos y exporta un vídeo. Las versiones anteriores se conservan.', 'Compose scenes, review timing and export a video. Previous versions are kept.')}</p>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="flex flex-wrap gap-3">
      <label>{label('Punto de partida', 'Starting point')} <select className="field" disabled={busy || dirty} defaultValue="launch" onChange={e => { const next = normalise(recipes[e.target.value]); setDraft(next); setBaseline(next); setRecord(null); setHtml(''); setDownload(null); }}>{Object.keys(recipes).map(k => <option key={k} value={k}>{recipes[k].title}</option>)}</select></label>
      <label>{label('Guardados', 'Saved')} <select className="field" disabled={busy || dirty} value={record?.id || ''} onChange={e => e.target.value && work(async() => { const r = await request('/' + e.target.value); setRecord(r); setDraft(r.composition); setBaseline(r.composition); setHtml(''); setDownload(null); })}><option value="">{label('Seleccionar', 'Choose')}</option>{saved.map(r => <option key={r.id} value={r.id}>{r.title} · v{r.revision}</option>)}</select></label>
    </div>
    {draft && <>
      <div className="grid gap-4 lg:grid-cols-[minmax(300px,1fr)_minmax(0,1.4fr)]">
        <div className="space-y-5">
          <label className="block">{label('Título','Title')}<input className="field w-full" value={draft.title} maxLength={120} onChange={e => edit({...draft,title:e.target.value})}/></label>
          <label className="block">{label('Formato','Format')}<select className="field w-full" value={draft.height > draft.width ? 'portrait' : draft.height === draft.width ? 'square' : 'landscape'} onChange={e => { const sizes={portrait:[720,1280],square:[1080,1080],landscape:[1280,720]}; const [width,height]=sizes[e.target.value]; edit({...draft,width,height}); }}><option value="landscape">16:9</option><option value="portrait">9:16</option><option value="square">1:1</option></select></label>
          {draft.scenes.map((s,i) => <fieldset key={i} className="border-t pt-4 space-y-3" style={{borderColor:'var(--line)'}}>
            <legend className="font-semibold">{label('Escena','Scene')} {i+1}</legend>
            <div className="flex gap-2"><input aria-label={label('Nombre de escena','Scene name')} className="field min-w-0 flex-1" value={s.name} onChange={e=>sceneEdit(i,'name',e.target.value)}/><label>{label('Segundos','Seconds')}<input className="field w-20" type="number" min="0.2" max="30" step="0.1" value={s.duration} onChange={e=>sceneEdit(i,'duration',Number(e.target.value))}/></label><label>{label('Fondo','Background')}<input type="color" value={s.background || '#0b1130'} onChange={e=>sceneEdit(i,'background',e.target.value)}/></label></div>
            {s.layers.map((l,j) => <div key={j} className="space-y-2">
              {(l.kind || 'text') === 'text' && <textarea className="field w-full" aria-label={label('Texto','Text')} value={l.text} rows={2} onChange={e=>layerEdit(i,j,'text',e.target.value)}/>}
              <div className="flex flex-wrap gap-3"><label>{label('Entrada','Entrance')} <select className="field" value={l.effect || 'rise'} onChange={e=>layerEdit(i,j,'effect',e.target.value)}>{[['none','Sin efecto','None'],['fade','Aparecer','Fade'],['rise','Subir','Rise'],['slide','Deslizar','Slide'],['scale','Ampliar','Scale'],['reveal','Revelar','Reveal']].map(([v,a,b])=><option key={v} value={v}>{label(a,b)}</option>)}</select></label><label>{label('Color','Colour')} <input type="color" value={l.color || '#f5f0df'} onChange={e=>layerEdit(i,j,'color',e.target.value)}/></label><label>{label('Espera (s)','Delay (s)')} <input type="number" className="field w-20" value={l.delay || 0} min="0" max="59" step="0.1" onChange={e=>layerEdit(i,j,'delay',Number(e.target.value))}/></label></div>
              <details className="help"><summary>{label('Posición y tamaño', 'Position and size')}</summary><div className="grid grid-cols-2 gap-3 py-3">{[['x','X',0,1,.01,.5],['y','Y',0,1,.01,.5],['width',label('Anchura','Width'),.01,1,.01,.8],['height',label('Altura','Height'),.01,1,.01,.15],['size',label('Texto (px)','Text (px)'),8,300,1,56],['enter',label('Entrada (s)','Entrance (s)'),.1,10,.1,.6]].map(([key,title,min,max,step,fallback]) => <label key={key}>{title}<input className="field w-full" type="number" min={min} max={max} step={step} value={l[key] ?? fallback} onChange={e=>layerEdit(i,j,key,Number(e.target.value))}/></label>)}<label>{label('Elemento','Element')}<select className="field" value={l.kind || 'text'} onChange={e=>layerEdit(i,j,'kind',e.target.value)}>{['text','rect','circle','line'].map(kind=><option key={kind}>{kind}</option>)}</select></label>{s.layers.length>1 && <button className="btn btn-sm" onClick={()=>sceneEdit(i,'layers',s.layers.filter((_,n)=>n!==j))}>{label('Quitar elemento','Remove element')}</button>}</div></details>
            </div>)}
            <button className="btn btn-sm" disabled={s.layers.length >= 40} onClick={()=>sceneEdit(i,'layers',[...s.layers,{kind:'text',text:label('Nuevo texto','New text'),y:0.7,size:40,effect:'fade',delay:Math.min(0.5,s.duration/2)}])}>{label('Añadir texto','Add text')}</button>
            {draft.scenes.length>1 && <button className="btn btn-sm ml-2" onClick={()=>edit({...draft,scenes:draft.scenes.filter((_,n)=>n!==i)})}>{label('Quitar escena','Remove scene')}</button>}
          </fieldset>)}
          <button className="btn" disabled={draft.scenes.length>=30} onClick={()=>edit({...draft,scenes:[...draft.scenes,{name:label('Nueva escena','New scene'),duration:3,layers:[{text:label('Tu mensaje','Your message')}]}]})}>{label('Añadir escena','Add scene')}</button>
        </div>
        <div className="lg:sticky lg:top-6 self-start space-y-4">
          <div className="flex gap-3 flex-wrap"><button className="btn" disabled={busy} onClick={()=>work(async()=>setHtml(await request('/preview',draft)))}>{label('Previsualizar','Preview')}</button><button className="btn" disabled={busy} onClick={()=>work(save)}>{label('Guardar versión','Save version')}</button><button className="btn" disabled={busy} onClick={()=>work(async()=>{const r=dirty||!record?await save():record;const result=await request('/render',{id:r.id,revision:r.revision,video:true});if(result.error)throw new Error(result.error);setDownload(result.download);})}>{busy?label('Trabajando…','Working…'):label('Exportar MP4','Export MP4')}</button></div>
          <p className="help" role="status">{dirty?label('Cambios sin guardar','Unsaved changes'):record?`v${record.revision}`:label('Sin guardar','Not saved')} · {label('MP4 sin sonido; puedes añadir audio en Lumiere.','Silent MP4; add audio in Lumiere.')}</p>
          {download && <a href={download} download className="btn">{label('Descargar vídeo','Download video')}</a>}
          {html ? <iframe title={label('Composición animada','Motion composition')} sandbox="allow-scripts allow-downloads" srcDoc={html} className="w-full border-0 h-[760px]"/> : <p className="help py-20 text-center">{label('Previsualiza para ver las escenas y ajustar su ritmo.','Preview to see your scenes and adjust their rhythm.')}</p>}
        </div>
      </div>
    </>}
  </section>;
}
