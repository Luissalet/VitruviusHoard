import React, { useEffect, useRef, useState } from 'react';
import { api } from '../../api.js';
import { clone, uid } from './model.js';

export const selectedState = (content, id) => content?.diagram?.type === 'isometric' && content.mechanism?.states.some(s => s.id === id) ? id : '';

export function IsometricControls({ draft, change, stateId, setStateId, partId, setPartId, mode, lang, inspector, error }) {
  const en = lang === 'en', figure = useRef(null);
  const [preview, setPreview] = useState(null), [busy, setBusy] = useState(true);
  const states = draft.mechanism?.states || [], parts = draft.diagram.pieces;
  const currentId = selectedState(draft, stateId), state = states.find(s => s.id === currentId);
  const part = parts.find(p => p.id === partId) || parts[0];
  const description = draft.mechanism?.parts.find(p => p.id === part.id)?.description || '';
  useEffect(() => {
    let live = true; setBusy(true);
    const timer = setTimeout(() => api.diagramDocumentPreview(draft, currentId).then(data => {
      if (live) { setPreview(data.rendering); setBusy(false); }
    }).catch(e => { if (live) { error(e.message); setBusy(false); } }), 120);
    return () => { live = false; clearTimeout(timer); };
  }, [draft, currentId, error]);
  useEffect(() => {
    for (const element of figure.current?.querySelectorAll('[data-piece]') || []) {
      element.setAttribute('tabindex', '0'); element.setAttribute('role', 'button');
      element.setAttribute('aria-label', parts.find(p => p.id === element.dataset.piece)?.label || element.dataset.piece);
      element.setAttribute('aria-pressed', String(element.dataset.piece === part.id));
    }
  }, [preview, mode, part.id, parts]);
  const pick = event => { const element = event.target.closest('[data-piece]'); if (element) setPartId(element.dataset.piece); };
  const editState = (key, value) => change(next => { next.mechanism.states.find(s => s.id === currentId)[key] = value; });
  const editPart = (key, value) => change(next => { next.diagram.pieces.find(p => p.id === part.id)[key] = value; });
  const addState = () => {
    const id = uid('state');
    change(next => { next.mechanism ||= { parts: [], states: [] }; next.mechanism.states.push({ ...(state ? clone(state) : { description: '', hidden: [], poses: {}, focus_piece: null }), id, title: en ? 'New state' : 'Nuevo estado' }); });
    setStateId(id);
  };
  return <div className={`de-mechanism ${inspector ? '' : 'de-mechanism-wide'}`}>
    <div className="de-mechanism-main">
      <div className="de-mechanism-selectors">
        <label>{en ? 'State' : 'Estado'}<select className="field" aria-label={en ? 'State' : 'Estado'} value={currentId} onChange={e => setStateId(e.target.value)}><option value="">{en ? 'Original figure' : 'Figura original'}</option>{states.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label>
        <label>{en ? 'Part' : 'Pieza'}<select className="field" aria-label={en ? 'Part' : 'Pieza'} value={part.id} onChange={e => setPartId(e.target.value)}>{parts.map(p => <option key={p.id} value={p.id}>{p.label || p.id}{state?.hidden.includes(p.id) ? (en ? ' · hidden' : ' · oculta') : ''}</option>)}</select></label>
      </div>
      <div ref={figure} className="de-mechanism-figure" aria-label={en ? 'Isometric figure' : 'Figura isométrica'} aria-busy={busy} onClick={pick} onKeyDown={e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.closest('[data-piece]')) { e.preventDefault(); pick(e); } }} dangerouslySetInnerHTML={{ __html: preview?.svg[mode] || '' }}/>
      <div className="de-mechanism-reading"><p role="status">{busy ? (en ? 'Updating figure…' : 'Actualizando figura…') : state?.title || (en ? 'Original figure' : 'Figura original')}</p>{state?.description && <p>{state.description}</p>}<strong>{part.label || part.id}</strong><p>{description || (en ? 'Add a part explanation in the inspector.' : 'Añade la explicación de esta pieza en el inspector.')}</p></div>
    </div>
    {inspector && <aside className="de-inspector de-mechanism-inspector" aria-label={en ? 'Mechanism properties' : 'Propiedades del mecanismo'}>
      <label>{en ? 'Part label' : 'Etiqueta de pieza'}<input className="field" maxLength="24" disabled={['coil', 'ring', 'post'].includes(part.kind)} value={part.label} onChange={e => editPart('label', e.target.value)}/></label>
      <label>{en ? 'Part explanation and sources' : 'Explicación y fuentes de la pieza'}<textarea className="field" rows="5" value={description} onChange={e => { const value = e.target.value; change(next => { next.mechanism ||= { parts: [], states: [] }; let entry = next.mechanism.parts.find(p => p.id === part.id); if (!entry) { entry = { id: part.id, description: '' }; next.mechanism.parts.push(entry); } entry.description = value; }); }}/></label>
      <details><summary>{en ? 'Original geometry' : 'Geometría original'}</summary><div className="de-geometry">{Object.entries(part.plan).filter(([key, value]) => value != null && ['x','y','cx','cy','w','d','r'].includes(key)).map(([key,value]) => <label key={key}>{key}<input className="field" type="number" aria-label={`${en ? 'Original' : 'Original'} ${key}`} value={value} onChange={e => editPart('plan', { ...part.plan, [key]: Number(e.target.value) })}/></label>)}{['z','h'].map(key => <label key={key}>{key}<input className="field" type="number" aria-label={`Original ${key}`} value={part[key]} onChange={e => editPart(key, Number(e.target.value))}/></label>)}</div></details>
      <div className="de-actions"><button className="btn" onClick={addState}>{state ? (en ? 'Duplicate state' : 'Duplicar estado') : (en ? 'Add state' : 'Añadir estado')}</button>{state && <button className="btn" onClick={() => { change(next => { next.mechanism.states = next.mechanism.states.filter(s => s.id !== currentId); }); setStateId(''); }}>{en ? 'Delete state' : 'Eliminar estado'}</button>}</div>
      {state && <>
        <label>{en ? 'State name' : 'Nombre del estado'}<input className="field" value={state.title} onChange={e => editState('title', e.target.value)}/></label>
        <label>{en ? 'State explanation' : 'Explicación del estado'}<textarea className="field" rows="3" value={state.description} onChange={e => editState('description', e.target.value)}/></label>
        <label className="de-check"><input type="checkbox" checked={!state.hidden.includes(part.id)} onChange={e => { const visible = e.target.checked; change(next => { const target = next.mechanism.states.find(s => s.id === currentId); target.hidden = visible ? target.hidden.filter(id => id !== part.id) : [...target.hidden, part.id]; if (!visible && target.focus_piece === part.id) target.focus_piece = null; }); }}/>{en ? 'Part visible in this state' : 'Pieza visible en este estado'}</label>
        <div className="de-geometry">{['dx','dy','dz'].map(key => <label key={key}>{key}<input className="field" type="number" step="1" aria-label={`${en ? 'Displacement' : 'Desplazamiento'} ${key}`} value={state.poses[part.id]?.[key] || 0} onChange={e => editState('poses', { ...state.poses, [part.id]: { ...state.poses[part.id], [key]: Number(e.target.value) } })}/></label>)}</div>
        <label>{en ? 'Highlighted part' : 'Pieza destacada'}<select className="field" value={state.focus_piece || ''} onChange={e => editState('focus_piece', e.target.value || null)}><option value="">{en ? 'Keep original' : 'Conservar original'}</option>{parts.filter(p => !state.hidden.includes(p.id)).map(p => <option key={p.id} value={p.id}>{p.label || p.id}</option>)}</select></label>
      </>}
      <p className="help">{en ? 'Authored positions and explanations. Save the document to retain them.' : 'Posiciones y explicaciones escritas. Guarda el documento para conservarlas.'}</p>
    </aside>}
  </div>;
}
