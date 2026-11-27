const NAVIGATION = new Set(["click", "scroll", "navigate"]);
const MAX_ENTRIES = 120;

export function conversationEntry(value, projectId) {
  if (!projectId || typeof value?.id !== "string" || !value.id || value.id.length > 180
      || !["user", "assistant"].includes(value.role) || typeof value.text !== "string"
      || !value.text.trim() || value.text.length > 60000) return null;
  const speaker = typeof value.speaker === "string" ? value.speaker.slice(0, 100) : "";
  return { id: value.id, projectId, kind: "speech", role: value.role, text: value.text, speaker };
}

export function recordCanvasActivity(entries, entry) {
  const index = entries.findIndex((item) => item.id === entry.id);
  if (index !== -1) return entries.map((item, i) => i === index ? entry : item);
  if (entries.length < MAX_ENTRIES) return [...entries, entry];
  const recent = [...entries.slice(1), entry];
  const latestRequest = entry.role === "user" ? entry : entries.findLast((item) => item.role === "user");
  if (!latestRequest || recent.includes(latestRequest)) return recent;
  return [latestRequest, ...recent.slice(1)];
}

export function groupCanvasActivity(entries) {
  const groups = [];
  for (const entry of entries) {
    const last = groups.at(-1);
    if (!NAVIGATION.has(entry.kind)) groups.push(entry);
    else if (last?.kind === "interactions") last.steps.push(entry);
    else groups.push({ id: "interactions:" + entry.id, kind: "interactions", steps: [entry] });
  }
  return groups;
}
