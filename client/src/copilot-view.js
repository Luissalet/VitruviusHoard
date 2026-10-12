// Native workspace values supplement explicit dirty-form hooks.
export function captureViewFields(document) {
  const root = document?.getElementById("root");
  if (!root) return [];
  return Array.from(root.querySelectorAll("input,textarea,select"))
    .filter((field) => field.id !== "settings-backend" && !["password", "file", "hidden"].includes(field.type) && field.getClientRects().length)
    .map((field, index) => ({
      label: field.getAttribute("aria-label") || Array.from(field.labels || []).map((label) => label.textContent.trim()).join(" · ")
        || field.getAttribute("data-testid") || field.name || field.placeholder || field.id || `${field.tagName.toLowerCase()} ${index + 1}`,
      type: field.type,
      value: ["checkbox", "radio"].includes(field.type) ? field.checked
        : field.multiple ? Array.from(field.selectedOptions).map((option) => option.value) : field.value,
    }));
}
