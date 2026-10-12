// Pure helpers behind window.hoardCopilot: no DOM or React at import time, so they run under plain `node --test`.

export const CONTEXT_REQUEST = "hoard:copilot-context-request";
export const REFRESH_EVENT = "vitruvius:copilot-updated";

const NO_OBJECT = new Set(["", "new", "undefined", "null"]);

/** True when a reference names no stored object ("new", empty, placeholders). */
export function isNoObjectId(id) {
  return id === undefined || id === null || NO_OBJECT.has(String(id).trim().toLowerCase());
}

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** Keys of `current` whose value differs from `initial` (deep compare); a key missing from `current` is not reported. */
export function changedFields(initial, current) {
  const base = initial || {};
  return Object.fromEntries(Object.entries(current || {}).filter(([key, value]) => !same(value, base[key])));
}

/** Snapshot a form hands to the copilot. `objectId` is omitted for create forms. */
export function formSnapshot(kind, { objectId, initial, current } = {}) {
  const fields = changedFields(initial, current);
  return { kind, ...(isNoObjectId(objectId) ? {} : { object_id: String(objectId) }), dirty: Object.keys(fields).length > 0, fields };
}

/** Ask every mounted form and view (they answer synchronously): the last dirty form wins, else the last one; views name the objects they show. */
export function collectEditor(dispatch) {
  const answers = [];
  const refs = [];
  try {
    dispatch({
      provide: (snapshot) => { if (snapshot && typeof snapshot === "object" && snapshot.kind) answers.push(snapshot); },
      provideObjects: (list) => { if (Array.isArray(list)) refs.push(...list); },
    });
  } catch { /* a broken form must not break the turn */ }
  const dirty = answers.filter((a) => a.dirty);
  const editor = dirty.length ? dirty[dirty.length - 1] : answers[answers.length - 1];
  return { editor, refs };
}

// One entry per object kind the views can show: the client API call that reads it and how its title is spelled.
export const OBJECT_KINDS = {
  render: { get: (api, id) => api.render(id), title: (r) => r.title || r.url, url: "#/critique" },
  "design-system": { get: (api, id) => api.tokensGet(id), title: (r) => r.name, url: "#/tokens" },
  diagram: { get: (api, id) => api.diagram(id), title: (r) => r.title || r.type, url: "#/diagrams" },
  reference: { get: (api, id) => api.reference(id), title: (r) => r.title || r.url, url: "#/gallery" },
  motion: { get: (api, id) => api.motion(id), title: (r) => r.composition?.title, url: "#/motion" },
};

/** Read the objects the views say they show; anything that no longer resolves (or is "new") is dropped, never thrown. */
export async function resolveObjects(refs, api) {
  const seen = new Set();
  const wanted = [];
  for (const ref of refs || []) {
    const kind = ref && OBJECT_KINDS[ref.kind];
    if (!kind || isNoObjectId(ref.id)) continue;
    const key = `${ref.kind}:${ref.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    wanted.push({ ref, kind });
  }
  const found = await Promise.all(wanted.map(async ({ ref, kind }) => {
    try {
      const row = await kind.get(api, String(ref.id));
      if (!row || typeof row !== "object") return null;
      const id = String(row.id ?? "");
      if (!id || id !== String(ref.id)) return null;
      return { kind: ref.kind, object_id: id, title: String(kind.title(row) || id), url: kind.url };
    } catch { return null; }
  }));
  return found.filter(Boolean);
}

/**
 * Build `{ project?, active_objects?, editor? }` for the current view. Every part is optional: a failing read omits
 * that part, an id that does not resolve (or "new") means "no object", and the promise never rejects. The app has
 * no projects, so `project` is never set.
 *  - api: the app's client API (`api.render(id)`, `api.tokensGet(id)`, ...)
 *  - ask: `(detail) => void` that dispatches the context request to the mounted forms and views
 */
export async function buildContext({ api, ask }) {
  const out = { active_objects: [] }; // possibly empty: overrides the launcher's guesses from the URL
  let editor;
  let refs = [];
  try {
    const collected = collectEditor(ask);
    editor = collected.editor;
    refs = collected.refs;
  } catch { /* omit the editor part */ }

  // The pages take no id from the route (`#/tokens` is the page, not an object), so only the objects a view reports count.
  try {
    const objects = await resolveObjects(refs, api);
    out.active_objects = objects; // possibly empty: overrides the launcher's guesses from the URL
  } catch { /* no objects */ }

  if (editor) out.editor = editor;
  return out;
}
