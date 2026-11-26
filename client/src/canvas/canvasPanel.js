// Pure helpers of the Canvas screen (no DOM or React: they run under `node --test`).

/** The modes of the canvas toolbar, in order. `handles` only shows when the preview says it supports it. */
export const MODES = ["navigate", "select", "comment", "handles"];

/** Messages the inspector inside the preview sends to its host (see `preview-inspector.js`). */
const FROM_PAGE = new Set(["dock/inspector-ready", "dock/select", "dock/comment-target", "dock/comment-anchors", "dock/comment-focus"]);

/** True for an inspector message from the visible preview frame: right window, right origin, right envelope. */
export function isCanvasMessage(event, frameWindow, origin) {
  const data = event?.data;
  return Boolean(frameWindow) && event.source === frameWindow && event.origin === origin
    && data?.hoardDock === 1 && FROM_PAGE.has(data.type);
}

/** Which modes this preview supports, from its `dock/inspector-ready` message. */
export function supportedModes(data) {
  const modes = ["navigate"];
  if (Array.isArray(data?.selection)) modes.push("select");
  if (data && "comment_mode" in data) modes.push("comment");
  if (data?.handles === true || (Array.isArray(data?.capabilities) && data.capabilities.includes("handles"))) modes.push("handles");
  return modes;
}

/** The mode the page reports it is in. */
export function modeFromPage(data) {
  if (data?.handles_mode) return "handles";
  if (data?.comment_mode) return "comment";
  if (data?.mode) return "select";
  return "navigate";
}

/** What to post to the preview to enter `mode` (navigate leaves every mode). */
export function modeMessages(mode, current) {
  if (mode === "navigate") {
    if (current === "comment") return [{ type: "inspect/mode", on: false, kind: "comment" }];
    if (current === "handles") return [{ type: "inspect/mode", on: false, kind: "handles" }];
    return current === "select" ? [{ type: "inspect/mode", on: false }] : [];
  }
  return [mode === "select" ? { type: "inspect/mode", on: true } : { type: "inspect/mode", on: true, kind: mode }];
}

/** `tag.class` of an element. */
export function elementLabel(item) {
  const name = (item?.tag || "element") + (item?.classes?.length ? "." + item.classes.slice(0, 2).join(".") : "");
  const text = item?.text ? ` "${item.text.length > 40 ? item.text.slice(0, 39) + "…" : item.text}"` : "";
  return name + text;
}

/**
 * The screen context the Dock bridge sends to the host (Faustus) with each change. The host keeps `focus` as
 * `{kind, id, label}` and `summary` up to 400 characters, so the selection and the open comments travel as short text
 * in `summary`: element, source position and revision. The agent reads the full detail with the project tools.
 */
export function canvasContext({ project, revision, mode, selection = [], comments = [] }, max = 400) {
  if (!project) return { view: "canvas" };
  const open = comments.filter((comment) => ["pending", "seen", "answered"].includes(comment.status));
  const parts = [`${project.name}${revision ? ` @${String(revision).slice(0, 12)}` : ""}`];
  if (mode && mode !== "navigate") parts.push(`mode ${mode}`);
  if (selection.length) parts.push(`selected ${selection.length}: ` + selection.slice(0, 4).map((item) => {
    const where = item.vsrc || (item.vgen ? `{{${item.vgen}}}` : item.selector || "");
    const text = item.text ? ` "${String(item.text).slice(0, 30)}"` : "";
    return `${item.tag || "element"}${text}${where ? ` ${where}` : ""}${item.same_vsrc_count > 1 ? ` x${item.same_vsrc_count}` : ""}`;
  }).join("; "));
  if (open.length) parts.push(`open comments ${open.length}: ` + open.slice(0, 3).map((comment) =>
    `#${comment.n} ${String(comment.note || "").slice(0, 40)}`).join("; "));
  const summary = parts.join(" · ");
  return {
    view: "canvas",
    focus: { kind: "app_project", id: project.id, label: project.name },
    summary: summary.length > max ? summary.slice(0, max - 1) + "…" : summary,
  };
}
