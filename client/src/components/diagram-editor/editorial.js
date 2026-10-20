import { clone, uid } from './model.js';

export const editorialNames = {
  es: { editorialComparison: 'Infografía · comparación', editorialTimeline: 'Infografía · cronología', editorialProcess: 'Infografía · proceso', editorialRelations: 'Infografía · relaciones' },
  en: { editorialComparison: 'Infographic · comparison', editorialTimeline: 'Infographic · timeline', editorialProcess: 'Infographic · process', editorialRelations: 'Infographic · relationships' },
};

export function editorialTemplate(kind) {
  const title = editorialNames.es[kind];
  const diagram = { type: 'flowchart', title, nodes: [], edges: [], groups: [] };
  const view = { kind: 'infographic', pages: [{ id: 'page-1', title: 'Página 1', width: 960, height: 720, order: 0 }], assets: {}, nodes: {}, edges: {} };
  const add = (id, label, x, y, width, height, style = {}) => {
    diagram.nodes.push({ id, label, shape: 'box' });
    view.nodes[id] = { page_id:'page-1', x, y, width, height, font_size:22, align:'left', border:false, ...style };
  };
  add('title', title.replace('Infografía · ', ''), 48, 32, 864, 80, { font_size:40, font_weight:700 });
  if (kind === 'editorialComparison') {
    add('question', 'Compara con los mismos criterios: utilidad, coste y límites.', 48, 118, 864, 68);
    add('a', 'Opción A\nDescribe aquí su utilidad y sus límites.', 48, 230, 408, 260, { border:true, font_size:26 });
    add('b', 'Opción B\nDescribe aquí su utilidad y sus límites.', 504, 230, 408, 260, { border:true, font_size:26 });
    add('sources', 'Fuentes y fecha de la comparación: añade tus referencias.', 48, 560, 864, 80, { font_size:18 });
  } else {
    const labels = kind === 'editorialTimeline' ? ['Inicio\nFecha y contexto', 'Cambio\nHecho principal', 'Situación actual\nResultado y fecha']
      : kind === 'editorialProcess' ? ['Entrada\nQué necesitas', 'Trabajo\nQué ocurre', 'Resultado\nCómo comprobarlo']
      : ['Origen\nCausa o contexto', 'Idea central\nRelación principal', 'Consecuencia\nEfecto observado'];
    labels.forEach((label, i) => add('step-' + i, label, 48 + i * 296, 260, 264, 180, { border:true, align:'center' }));
    diagram.edges = [{ id:'link-1', from:'step-0', to:'step-1', label:'' }, { id:'link-2', from:'step-1', to:'step-2', label:'' }];
    add('notes', 'Explica las fechas, los pasos o las relaciones con tus propios datos y fuentes.', 48, 520, 864, 120);
  }
  return { diagram, view };
}

export function copyPage(content, page) {
  const nextPage = { ...page, id:uid('page'), title:page.title + ' · copia', order:Math.max(...content.view.pages.map(p => p.order || 0)) + 1 };
  const source = content.diagram.nodes.filter(n => content.view.nodes[n.id]?.page_id === page.id);
  const mapped = Object.fromEntries(source.map(n => [n.id, uid('node')]));
  const groups = Object.fromEntries([...new Set(source.map(n => n.group).filter(Boolean))].map(id => [id, uid('group')]));
  content.diagram.groups.push(...content.diagram.groups.filter(g => groups[g.id]).map(g => ({ ...clone(g), id:groups[g.id] })));
  for (const node of source) {
    const id = mapped[node.id];
    content.diagram.nodes.push({ ...clone(node), id, group:groups[node.group] || '' });
    content.view.nodes[id] = { ...clone(content.view.nodes[node.id]), page_id:nextPage.id };
  }
  for (const edge of [...content.diagram.edges]) if (mapped[edge.from] && mapped[edge.to]) {
    const id = uid('edge');
    content.diagram.edges.push({ ...clone(edge), id, from:mapped[edge.from], to:mapped[edge.to] });
    if (content.view.edges[edge.id]) content.view.edges[id] = clone(content.view.edges[edge.id]);
  }
  content.view.pages.push(nextPage);
  return nextPage.id;
}
