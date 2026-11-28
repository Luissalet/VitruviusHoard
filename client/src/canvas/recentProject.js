const KEY = "vitruvius-recent-project";

export function rememberProject(id) {
  try {
    if (id) localStorage.setItem(KEY, id);
    else localStorage.removeItem(KEY);
  } catch {
    // Storage can be disabled in an embedded workbench.
  }
}

export function recentProjectId(projects) {
  try {
    const id = localStorage.getItem(KEY);
    return projects.some((project) => project.id === id) ? id : null;
  } catch {
    return null;
  }
}
