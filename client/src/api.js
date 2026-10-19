// Thin fetch wrapper: JSON in/out, `{ error }` bodies become exceptions.
async function request(method, path, { params, body } = {}) {
  const url = new URL(path.startsWith("/api/") ? "/design" + path : path, window.location.origin);
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  }
  const response = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { error: text };
  }
  if (!response.ok) throw new Error((data && data.error) || `Error ${response.status}`);
  if (data?.download_url?.startsWith('/api/')) data.download_url='/design'+data.download_url;
  if (path.startsWith('/design/api/diagrams') && data?.files) data.files=Object.fromEntries(Object.entries(data.files).map(([k,v])=>[k,typeof v==='string'&&v.startsWith('/api/')?'/design'+v:v]));
  return data;
}

export const api = {
  health: () => request("GET", "/design/api/health"),
  status: () => request("GET", "/design/api/status"),

  librarySearch: (params) => request("GET", "/design/api/library/search", { params }),
  embeddings: () => request("GET", "/design/api/library/embeddings"),
  embeddingsBuild: () => request("POST", "/design/api/library/embeddings", { body: {} }),
  libraryBrief: (body) => request("POST", "/design/api/library/brief", { body }),
  libraryRules: (params) => request("GET", "/design/api/library/rules", { params }),

  catalogStyles: (limit) => request("GET", "/design/api/catalog/styles", { params: { limit } }),
  catalogPalettes: (limit) => request("GET", "/design/api/catalog/palettes", { params: { limit } }),
  catalogFonts: (limit) => request("GET", "/design/api/catalog/fonts", { params: { limit } }),

  sources: () => request("GET", "/design/api/sources"),
  sourceAdd: (body) => request("POST", "/design/api/sources", { body }),
  sourceIngest: (id) => request("POST", `/design/api/sources/${encodeURIComponent(id)}/ingest`),

  renders: (limit) => request("GET", "/design/api/renders", { params: { limit } }),
  renderCreate: (body) => request("POST", "/design/api/renders", { body }),
  render: (id) => request("GET", `/design/api/renders/${encodeURIComponent(id)}`),
  renderFileUrl: (id, name) => `/design/api/renders/${encodeURIComponent(id)}/files/${name}`,
  renderCritique: (id, body) => request("POST", `/design/api/renders/${encodeURIComponent(id)}/critique`, { body }),
  lint: (body) => request("POST", "/design/api/lint", { body }),
  assay: (body) => request("POST", "/design/api/page-check", { body }),
  renderCompare: (body) => request("POST", "/design/api/renders/compare", { body }),

  tokensList: (limit) => request("GET", "/design/api/tokens", { params: { limit } }),
  tokensCreate: (body) => request("POST", "/design/api/tokens", { body }),
  tokensGet: (id) => request("GET", `/design/api/tokens/${encodeURIComponent(id)}`),
  tokensDelete: (id) => request("DELETE", `/design/api/tokens/${encodeURIComponent(id)}`),
  tokensExportUrl: (id, format) => `/design/api/tokens/${encodeURIComponent(id)}/export?format=${format}`,
  tokensExport: (id, format) => request("GET", `/design/api/tokens/${encodeURIComponent(id)}/export`, { params: { format } }),
  tokensPreview: (id, body) => request("POST", `/design/api/tokens/${encodeURIComponent(id)}/preview`, { body }),
  tokensPlaygroundUrl: (id, dark) => `/design/api/tokens/${encodeURIComponent(id)}/playground?dark=${dark ? "true" : "false"}`,

  diagramTypes: (params) => request("GET", "/design/api/diagrams/types", { params }),
  diagrams: (limit) => request("GET", "/design/api/diagrams", { params: { limit } }),
  diagram: (id) => request("GET", `/design/api/diagrams/${encodeURIComponent(id)}`),
  diagramRender: (body) => request("POST", "/design/api/diagrams", { body }),
  diagramDelete: (id) => request("DELETE", `/design/api/diagrams/${encodeURIComponent(id)}`),
  diagramSvgUrl: (id, mode) => `/design/api/diagrams/${encodeURIComponent(id)}/${mode}.svg`,
  diagramBrands: () => request("GET", "/design/api/diagrams/brands"),
  diagramBrandOnboard: (body) => request("POST", "/design/api/diagrams/brands", { body }),

  appTemplates: () => request("GET", "/design/api/app-projects/templates"),
  appProjects: () => request("GET", "/design/api/app-projects"),
  appProject: (id, revision) => request("GET", `/design/api/app-projects/${encodeURIComponent(id)}`, { params: { revision } }),
  appProjectCreate: (body) => request("POST", "/design/api/app-projects", { body }),
  appProjectUpdate: (id, body) => request("PUT", `/design/api/app-projects/${encodeURIComponent(id)}`, { body }),
  appProjectPreview: (id, body) => request("POST", `/design/api/app-projects/${encodeURIComponent(id)}/preview`, { body }),
  appProjectExport: (id, body) => request("POST", `/design/api/app-projects/${encodeURIComponent(id)}/export`, { body }),
  appProjectRender: (id, body) => request("POST", `/design/api/app-projects/${encodeURIComponent(id)}/render`, { body }),
  referenceCollections: () => request("GET", "/design/api/reference-collections"),
  referenceImportCollection: (body) => request("POST", "/design/api/reference-collections/import", { body }),
  designPatterns: () => request("GET", "/design/api/design-patterns"),
  designPattern: (body) => request("POST", "/design/api/design-patterns/generate", { body }),
  references: (params) => request("GET", "/design/api/references", { params }),
  referenceAdd: (body) => request("POST", "/design/api/references", { body }),
  reference: (id) => request("GET", `/design/api/references/${encodeURIComponent(id)}`),
  referenceDelete: (id) => request("DELETE", `/design/api/references/${encodeURIComponent(id)}`),
  referenceFileUrl: (id, name) => `/design/api/references/${encodeURIComponent(id)}/files/${name}`,

  motions: () => request("GET", "/design/api/motions"),
  motion: (id) => request("GET", `/design/api/motions/${encodeURIComponent(id)}`),

  settings: () => request("GET", "/design/api/settings"),
  settingsUpdate: (body) => request("PUT", "/design/api/settings", { body }),
};
