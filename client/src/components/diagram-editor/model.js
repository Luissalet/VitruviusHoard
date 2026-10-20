// Object identities, geometry and local draft merges are shared by editor actions.
export const uid = (prefix) => `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
export const clone = (value) => structuredClone(value);
export const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);

export function mergeDraft(base, wanted, current, path = "") {
  if (equal(base, wanted) || equal(wanted, current)) return clone(current);
  if (equal(base, current)) return wanted === undefined ? undefined : clone(wanted);
  if (base === undefined && /^\/view\/(nodes|edges)\/[^/]+$/.test(path)
      && [wanted, current].every(v => v && !Array.isArray(v) && typeof v === "object")) base = {};
  if ([base, wanted, current].every(v => v && !Array.isArray(v) && typeof v === "object")) {
    const out = {};
    for (const key of new Set([...Object.keys(current), ...Object.keys(wanted), ...Object.keys(base)])) {
      const value = mergeDraft(base[key], wanted[key], current[key], `${path}/${key}`);
      if (value !== undefined) out[key] = value;
    }
    return out;
  }
  if ([base, wanted, current].every(Array.isArray) && [...base, ...wanted, ...current].every(v => v?.id)) {
    const maps = [base, wanted, current].map(items => Object.fromEntries(items.map(v => [v.id, v])));
    const out = mergeDraft(...maps, path);
    return [...new Set([...current, ...wanted].map(v => v.id))].filter(id => out[id]).map(id => out[id]);
  }
  throw new Error(`Conflicto de edición: ${path}`);
}

export function geometry(content, scene) {
  return Object.fromEntries(content.diagram.nodes.map((node, i) => [node.id, {
    x: 60 + (i % 4) * 220, y: 80 + Math.floor(i / 4) * 140, width: 176, height: 64,
    ...(scene?.boxes?.[node.id] ? { x: scene.boxes[node.id].x, y: scene.boxes[node.id].y,
      width: scene.boxes[node.id].w, height: scene.boxes[node.id].h } : {}),
    ...content.view?.nodes?.[node.id],
  }]));
}

export function connector(edge, boxes, view = {}, edges = []) {
  const a = boxes[edge.from], b = boxes[edge.to];
  if (!a || !b) return [];
  const ac = [a.x + a.width / 2, a.y + a.height / 2], bc = [b.x + b.width / 2, b.y + b.height / 2];
  const horizontal = Math.abs(bc[0] - ac[0]) >= Math.abs(bc[1] - ac[1]);
  const returning = edge.from !== edge.to && edges.slice(0, edges.indexOf(edge)).some(other => other.from === edge.to && other.to === edge.from);
  const s = view.source_port && view.source_port !== "auto" ? view.source_port : returning ? "right" : horizontal ? bc[0] >= ac[0] ? "right" : "left" : bc[1] >= ac[1] ? "bottom" : "top";
  const t = view.target_port && view.target_port !== "auto" ? view.target_port : returning ? "right" : horizontal ? bc[0] >= ac[0] ? "left" : "right" : bc[1] >= ac[1] ? "top" : "bottom";
  const port = (r, side) => ({ top: [r.x + r.width / 2, r.y], bottom: [r.x + r.width / 2, r.y + r.height], left: [r.x, r.y + r.height / 2], right: [r.x + r.width, r.y + r.height / 2] })[side];
  const start = port(a, s), end = port(b, t);
  if (view.points?.length) return [start, ...view.points, end];
  if (returning) { const lane = Math.max(a.x + a.width, b.x + b.width) + 40; return [start, [lane, start[1]], [lane, end[1]], end]; }
  if (edge.from === edge.to) return [start, [a.x + a.width + 36, start[1]], [a.x + a.width + 36, a.y - 24], [ac[0], a.y - 24], [ac[0], a.y]];
  return s === "left" || s === "right" ? [start, [(start[0] + end[0]) / 2, start[1]], [(start[0] + end[0]) / 2, end[1]], end]
    : [start, [start[0], (start[1] + end[1]) / 2], [end[0], (start[1] + end[1]) / 2], end];
}

export const templates = {
  flow: { type: "flowchart", title: "Proceso con revisión", nodes: [{ id: "start", label: "Recibir solicitud", shape: "pill" }, { id: "review", label: "¿Está completa?", shape: "diamond" }, { id: "finish", label: "Resolver", shape: "pill" }, { id: "fix", label: "Pedir información" }], edges: [{ id: "e1", from: "start", to: "review" }, { id: "e2", from: "review", to: "finish", label: "Sí" }, { id: "e3", from: "review", to: "fix", label: "No" }, { id: "e4", from: "fix", to: "review" }] },
  architecture: { type: "architecture", title: "Arquitectura de ejemplo", direction: "LR", groups: [{ id: "app", label: "Aplicación" }], nodes: [{ id: "person", label: "Persona" }, { id: "client", label: "Interfaz", group: "app" }, { id: "service", label: "Servicio", group: "app" }, { id: "data", label: "Datos", shape: "cylinder", group: "app" }], edges: [{ id: "e1", from: "person", to: "client" }, { id: "e2", from: "client", to: "service" }, { id: "e3", from: "service", to: "data" }] },
  tree: { type: "flowchart", title: "Organigrama de ejemplo", nodes: [{ id: "lead", label: "Coordinación" }, { id: "design", label: "Diseño" }, { id: "production", label: "Producción" }, { id: "support", label: "Soporte" }], edges: [{ id: "e1", from: "lead", to: "design" }, { id: "e2", from: "lead", to: "production" }, { id: "e3", from: "lead", to: "support" }] },
  concepts: { type: "flowchart", title: "Mapa conceptual", direction: "LR", nodes: [{ id: "idea", label: "Idea central", shape: "round" }, { id: "cause", label: "Causas" }, { id: "effect", label: "Consecuencias" }, { id: "example", label: "Ejemplos" }], edges: [{ id: "e1", from: "cause", to: "idea" }, { id: "e2", from: "idea", to: "effect" }, { id: "e3", from: "idea", to: "example" }] },
  comparison: { type: "flowchart", title: "Comparación", direction: "LR", nodes: [{ id: "question", label: "Criterio de comparación", shape: "pill" }, { id: "one", label: "Opción A\nVentajas y límites" }, { id: "two", label: "Opción B\nVentajas y límites" }], edges: [{ id: "e1", from: "question", to: "one" }, { id: "e2", from: "question", to: "two" }] },
};
