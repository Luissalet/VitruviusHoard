// Thin fetch wrapper: JSON in/out, `{ error }` bodies become exceptions.
async function request(method, path, { params, body } = {}) {
  const url = new URL(path, window.location.origin);
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
  return data;
}

export const api = {
  health: () => request("GET", "/api/health"),
  status: () => request("GET", "/api/status"),

  librarySearch: (params) => request("GET", "/api/library/search", { params }),
  libraryBrief: (body) => request("POST", "/api/library/brief", { body }),
  libraryRules: (params) => request("GET", "/api/library/rules", { params }),

  catalogStyles: (limit) => request("GET", "/api/catalog/styles", { params: { limit } }),
  catalogPalettes: (limit) => request("GET", "/api/catalog/palettes", { params: { limit } }),
  catalogFonts: (limit) => request("GET", "/api/catalog/fonts", { params: { limit } }),

  sources: () => request("GET", "/api/sources"),
  sourceAdd: (body) => request("POST", "/api/sources", { body }),
  sourceIngest: (id) => request("POST", `/api/sources/${encodeURIComponent(id)}/ingest`),

  renders: (limit) => request("GET", "/api/renders", { params: { limit } }),
  renderCreate: (body) => request("POST", "/api/renders", { body }),
  render: (id) => request("GET", `/api/renders/${encodeURIComponent(id)}`),
  renderFileUrl: (id, name) => `/api/renders/${encodeURIComponent(id)}/files/${name}`,
  renderCritique: (id, body) => request("POST", `/api/renders/${encodeURIComponent(id)}/critique`, { body }),
  lint: (body) => request("POST", "/api/lint", { body }),
  assay: (body) => request("POST", "/api/assay", { body }),
  renderCompare: (body) => request("POST", "/api/renders/compare", { body }),

  tokensList: (limit) => request("GET", "/api/tokens", { params: { limit } }),
  tokensCreate: (body) => request("POST", "/api/tokens", { body }),
  tokensGet: (id) => request("GET", `/api/tokens/${encodeURIComponent(id)}`),
  tokensDelete: (id) => request("DELETE", `/api/tokens/${encodeURIComponent(id)}`),
  tokensExportUrl: (id, format) => `/api/tokens/${encodeURIComponent(id)}/export?format=${format}`,
  tokensExport: (id, format) => request("GET", `/api/tokens/${encodeURIComponent(id)}/export`, { params: { format } }),
  tokensPreview: (id, body) => request("POST", `/api/tokens/${encodeURIComponent(id)}/preview`, { body }),
  tokensPlaygroundUrl: (id, dark) => `/api/tokens/${encodeURIComponent(id)}/playground?dark=${dark ? "true" : "false"}`,

  references: (params) => request("GET", "/api/references", { params }),
  referenceAdd: (body) => request("POST", "/api/references", { body }),
  reference: (id) => request("GET", `/api/references/${encodeURIComponent(id)}`),
  referenceDelete: (id) => request("DELETE", `/api/references/${encodeURIComponent(id)}`),
  referenceFileUrl: (id, name) => `/api/references/${encodeURIComponent(id)}/files/${name}`,

  settings: () => request("GET", "/api/settings"),
  settingsUpdate: (body) => request("PUT", "/api/settings", { body }),
};
