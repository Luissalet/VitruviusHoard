import React from 'react';
import { copyPage } from './editorial.js';
import { uid } from './model.js';

export function PageControls({ draft, page, change, select, lang }) {
  const en = lang === 'en', pages = [...draft.view.pages].sort((a,b) => (a.order || 0) - (b.order || 0));
  const update = (key, value) => change(next => { next.view.pages.find(p => p.id === page.id)[key] = value; });
  return <div className="de-pages" aria-label={en ? 'Pages' : 'Páginas'}>
    <div className="de-actions"><select className="field" aria-label={en ? 'Page' : 'Página'} value={page.id} onChange={e => select(e.target.value)}>{pages.map(p => <option key={p.id} value={p.id}>{p.title || p.id}</option>)}</select>
      <button className="btn" onClick={() => { const id=uid('page'); change(next => { next.view.pages.push({ id, title:en?'New page':'Nueva página', width:page.width, height:page.height, order:Math.max(...pages.map(p => p.order || 0))+1 }); }); select(id); }}>{en?'Add page':'Añadir página'}</button>
      <button className="btn" onClick={() => change(next => { select(copyPage(next, page)); })}>{en?'Duplicate page':'Duplicar página'}</button>
    </div>
    <details className="de-page-options"><summary>{en?'Page options':'Opciones de página'}</summary>
    <div className="de-page-fields"><label>{en?'Page title':'Título de página'}<input className="field" value={page.title} onChange={e=>update('title', e.target.value)}/></label>{['width','height'].map(key=><label key={key}>{key==='width'?(en?'Page width':'Ancho de página'):(en?'Page height':'Alto de página')}<input className="field" type="number" min="200" value={page[key]} onChange={e=>update(key, Math.max(200,Number(e.target.value)))}/></label>)}</div>
    <div className="de-actions"><button className="btn" disabled={pages[0].id === page.id} onClick={() => change(next => { const i=pages.findIndex(p=>p.id===page.id), ids=pages.map(p=>p.id); [ids[i-1],ids[i]]=[ids[i],ids[i-1]]; for(const p of next.view.pages)p.order=ids.indexOf(p.id); })}>{en?'Move page earlier':'Adelantar página'}</button>
      <button className="btn" disabled={pages.length<2} onClick={() => change(next => { const gone=new Set(next.diagram.nodes.filter(n=>next.view.nodes[n.id]?.page_id===page.id).map(n=>n.id)); next.diagram.nodes=next.diagram.nodes.filter(n=>!gone.has(n.id)); next.diagram.edges=next.diagram.edges.filter(e=>!gone.has(e.from)&&!gone.has(e.to)); next.view.pages=next.view.pages.filter(p=>p.id!==page.id); select(next.view.pages[0].id); })}>{en?'Delete page and its blocks':'Eliminar página y sus bloques'}</button></div>
    </details>
  </div>;
}

export function TextControls({ box, update, draft, change, chosen, lang, error }) {
  const en = lang==='en';
  const image = async file => {
    if (!file) return;
    try {
      if (!['image/png','image/jpeg','image/webp'].includes(file.type)) throw new Error(en?'Choose PNG, JPEG or WebP.':'Elige PNG, JPEG o WebP.');
      const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file);});
      const bitmap=await createImageBitmap(file); bitmap.close();
      const id=uid('image'); change(next=>{next.view.assets[id]={name:file.name,data};next.view.nodes[chosen.id]={...box,asset_id:id,show_label:false};});
    } catch(e) {error(e.message);}
  };
  return <>
    <label>{en?'Font size':'Tamaño de texto'}<input className="field" type="number" min="8" max="144" value={box.font_size||13} onChange={e=>update('font_size',Number(e.target.value))}/></label>
    <label>{en?'Weight':'Peso'}<select className="field" value={box.font_weight||500} onChange={e=>update('font_weight',Number(e.target.value))}>{[400,500,600,700].map(v=><option key={v}>{v}</option>)}</select></label>
    <label>{en?'Text alignment':'Alineación del texto'}<select className="field" value={box.align||'center'} onChange={e=>update('align',e.target.value)}>{['left','center','right'].map((v,i)=><option key={v} value={v}>{en?['Left','Centre','Right'][i]:['Izquierda','Centro','Derecha'][i]}</option>)}</select></label>
    <label className="de-check"><input type="checkbox" checked={box.border!==false} onChange={e=>update('border',e.target.checked)}/>{en?'Shape background and border':'Fondo y borde de la forma'}</label>
    <label>{en?'Text colour':'Color del texto'}<input type="color" value={box.ink||'#1d2433'} onChange={e=>update('ink',e.target.value)}/></label>
    <label>{en?'Move to page':'Mover a página'}<select className="field" value={box.page_id} onChange={e=>update('page_id',e.target.value)}>{draft.view.pages.map(p=><option key={p.id} value={p.id}>{p.title||p.id}</option>)}</select></label>
    <label className="btn de-import">{en?'Import image':'Importar imagen'}<input type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>{image(e.target.files?.[0]);e.target.value='';}}/></label>
    {box.asset_id&&<><label className="de-check"><input type="checkbox" checked={box.show_label!==false} onChange={e=>update('show_label',e.target.checked)}/>{en?'Show text over image':'Mostrar texto sobre imagen'}</label><button className="btn" onClick={()=>change(next=>{next.view.nodes[chosen.id]={...next.view.nodes[chosen.id],asset_id:'',show_label:true};})}>{en?'Remove image':'Quitar imagen'}</button></>}
  </>;
}
