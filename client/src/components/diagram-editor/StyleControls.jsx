import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api.js';
import { useCopilotForm, useCopilotRefresh } from '../../copilot-hooks.js';

export function StyleControls({ box, colours, selection, change, lang, error }) {
  const en=lang==='en';
  const [styles,setStyles]=useState([]),[selected,setSelected]=useState(''),[name,setName]=useState(''),[draftStyle,setDraftStyle]=useState(),[pending,setPending]=useState(false);
  const style=styles.find(s=>s.id===selected);
  // A library refresh can advance the head without advancing a pending name's base.
  const state=useRef();state.current={style,name,draftStyle};
  const refresh=useCallback(async()=>{
    try { const result=await api.diagramStyles(),current=state.current,incoming=result.styles.find(s=>s.id===current.style?.id);
      if(current.style && current.name===current.draftStyle?.name){setName(incoming?.name||'');setDraftStyle(incoming);}
      setStyles(result.styles);setSelected(id=>result.styles.some(s=>s.id===id)?id:''); }
    catch(e){error(e.message);}
  },[error]);
  useEffect(()=>{refresh();},[refresh]);
  useCopilotRefresh(refresh);
  useCopilotForm('diagram-style-library',{objectId:style?.id,initial:{name:draftStyle?.name||'',revision:draftStyle?.revision},current:{name,revision:draftStyle?.revision,selected_nodes:selection}});
  const values={fill:box.fill||colours.surface,stroke:box.stroke||colours.border,ink:box.ink||colours.ink,
    font_size:box.font_size||13,font_weight:box.font_weight||500,align:box.align||'center',border:box.border!==false,show_label:box.show_label!==false};
  const save=async update=>{
    const submitted={name:name.trim(),values,...(update?{id:style.id,base_revision:draftStyle.revision}:{})};
    setPending(true);
    try {const saved=await api.diagramStyleSave(submitted);await refresh();setSelected(saved.id);setName(saved.name);setDraftStyle(saved);}
    catch(e){error(e.message);}finally{setPending(false);}
  };
  const remove=async()=>{
    setPending(true);
    try{await api.diagramStyleRemove(style.id,style.revision);await refresh();setName('');}
    catch(e){error(e.message);}finally{setPending(false);}
  };
  return <details className="de-style-library"><summary>{en?'Reusable styles':'Estilos reutilizables'}</summary>
    <label>{en?'Library style':'Estilo de la biblioteca'}<select className="field" aria-label={en?'Library style':'Estilo de la biblioteca'} value={selected} disabled={pending} onChange={e=>{const chosen=styles.find(s=>s.id===e.target.value);setSelected(e.target.value);setName(chosen?.name||'');setDraftStyle(chosen);}}><option value="">{en?'Choose a style…':'Elige un estilo…'}</option>{styles.map(s=><option key={s.id} value={s.id}>{s.name} · r{s.revision}</option>)}</select></label>
    <div className="de-actions"><button className="btn" disabled={!style||pending} onClick={()=>change(next=>{for(const id of selection)next.view.nodes[id]={...next.view.nodes[id],...style.values};})}>{en?'Apply to selection':'Aplicar a la selección'}</button><button className="btn" disabled={pending} onClick={refresh}>{en?'Refresh library':'Actualizar biblioteca'}</button></div>
    <label>{en?'Style name':'Nombre del estilo'}<input className="field" value={name} maxLength="160" disabled={pending} onChange={e=>setName(e.target.value)}/></label>
    <div className="de-actions"><button className="btn" disabled={pending||!name.trim()} onClick={()=>save(false)}>{pending?(en?'Saving…':'Guardando…'):(en?'Save shape as new style':'Guardar forma como estilo nuevo')}</button><button className="btn" disabled={pending||!style||!name.trim()} onClick={()=>save(true)}>{en?'Update style from this shape':'Actualizar estilo con esta forma'}</button><button className="btn" disabled={pending||!style} onClick={remove}>{en?'Remove from library':'Retirar de la biblioteca'}</button></div>
    <p className="help">{en?'Copies appearance only. Text, positions, pages and images stay on each shape. Updating the library keeps previously applied styles unchanged.':'Copia sólo el aspecto. Cada forma conserva texto, posición, página e imagen. Cambiar la biblioteca conserva los estilos ya aplicados.'}</p>
  </details>;
}
